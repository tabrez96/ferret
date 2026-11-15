import base64

import httplib2
import pytest
from google.auth.exceptions import RefreshError, TransportError
from googleapiclient.errors import HttpError

from ferret.config import Settings
from ferret.gmail.client import (
    MAX_ATTACHMENT_BYTES,
    GmailError,
    GmailRevoked,
    GoogleGmail,
    PdfPart,
    decode_body,
    gmail_factory_from_settings,
    map_error,
    pdf_parts,
)


def http_error(status, reason=""):
    content = b'{"error": {"errors": [{"reason": "%s"}]}}' % reason.encode()
    return HttpError(httplib2.Response({"status": status}), content)


def pdf(attachment_id=None, data=None, mime="application/pdf", filename="s.pdf", size=10):
    body = {"size": size}
    if attachment_id:
        body["attachmentId"] = attachment_id
    if data:
        body["data"] = data
    return {"mimeType": mime, "filename": filename, "body": body}


def test_pdf_parts_top_level_attachment():
    payload = pdf(attachment_id="a1")
    assert pdf_parts(payload) == [PdfPart("a1", None)]


def test_pdf_parts_nested_multipart():
    payload = {
        "mimeType": "multipart/mixed",
        "parts": [
            {"mimeType": "multipart/alternative", "parts": [pdf(attachment_id="a1")]},
            pdf(attachment_id="a2"),
        ],
    }
    assert pdf_parts(payload) == [PdfPart("a1", None), PdfPart("a2", None)]


def test_pdf_parts_octet_stream_with_pdf_name():
    part = pdf(attachment_id="a1", mime="application/octet-stream", filename="x.PDF")
    payload = {"parts": [part]}
    assert pdf_parts(payload) == [PdfPart("a1", None)]


def test_pdf_parts_ignores_non_pdf():
    payload = {
        "parts": [
            pdf(attachment_id="a1", mime="image/png", filename="logo.png"),
            pdf(attachment_id="a2", mime="text/plain", filename=""),
            "junk",
        ]
    }
    assert pdf_parts(payload) == []


def test_pdf_parts_inline_data():
    assert pdf_parts(pdf(data="QUJD")) == [PdfPart(None, "QUJD")]


def test_pdf_parts_skips_oversize_and_empty():
    payload = {
        "parts": [
            pdf(attachment_id="big", size=MAX_ATTACHMENT_BYTES + 1),
            pdf(),
            {"mimeType": "application/pdf", "body": None},
        ]
    }
    assert pdf_parts(payload) == []


def test_decode_body_adds_padding():
    data = base64.urlsafe_b64encode(b"%PDF-1").decode().rstrip("=")
    assert decode_body(data) == b"%PDF-1"


def test_map_error_invalid_grant_is_revoked():
    exc = RefreshError(
        "invalid_grant: Token has been expired or revoked.", {"error": "invalid_grant"}
    )
    assert isinstance(map_error(exc), GmailRevoked)


def test_map_error_other_refresh_error():
    err = map_error(RefreshError("temporarily_unavailable"))
    assert isinstance(err, GmailError) and not isinstance(err, GmailRevoked)


def test_map_error_401_is_revoked():
    assert isinstance(map_error(http_error(401)), GmailRevoked)


def test_map_error_403_scope_is_revoked():
    assert isinstance(map_error(http_error(403, "insufficientPermissions")), GmailRevoked)


def test_map_error_403_rate_limit_is_retryable():
    err = map_error(http_error(403, "rateLimitExceeded"))
    assert isinstance(err, GmailError) and not isinstance(err, GmailRevoked)


@pytest.mark.parametrize("exc", [http_error(500), TransportError("x"), TimeoutError()])
def test_map_error_500_and_network(exc):
    err = map_error(exc)
    assert isinstance(err, GmailError) and not isinstance(err, GmailRevoked)


class FakeRequest:
    def __init__(self, result):
        self.result = result

    def execute(self, num_retries=0):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeAttachments:
    def __init__(self, results, calls):
        self.results, self.calls = results, calls

    def get(self, **kw):
        self.calls.append(("attachments.get", kw))
        return FakeRequest(self.results[kw["id"]])


class FakeMessages:
    def __init__(self, lists=(), message=None, attachments=None):
        self.lists, self.message, self.attachments_by_id = list(lists), message, attachments or {}
        self.calls = []

    def list(self, **kw):
        self.calls.append(("list", kw))
        return FakeRequest(self.lists.pop(0))

    def get(self, **kw):
        self.calls.append(("get", kw))
        return FakeRequest(self.message)

    def attachments(self):
        return FakeAttachments(self.attachments_by_id, self.calls)


class FakeService:
    def __init__(self, messages):
        self._messages = messages

    def users(self):
        return self

    def messages(self):
        return self._messages


def gmail_with(**kw):
    messages = FakeMessages(**kw)
    return GoogleGmail(FakeService(messages)), messages


def test_search_paginates():
    gmail, messages = gmail_with(
        lists=[{"messages": [{"id": "m1"}], "nextPageToken": "p2"}, {"messages": [{"id": "m2"}]}]
    )
    assert gmail.search("from:bank") == ["m1", "m2"]
    first, second = (kw for _, kw in messages.calls)
    assert second["pageToken"] == "p2"
    assert first["userId"] == second["userId"] == "me"
    assert first["q"] == second["q"] == "from:bank"


def test_search_empty():
    gmail, _ = gmail_with(lists=[{}])
    assert gmail.search("q") == []


def test_search_maps_errors():
    gmail, _ = gmail_with(lists=[http_error(401)])
    with pytest.raises(GmailRevoked):
        gmail.search("q")


def test_pdf_attachments_fetches_and_decodes():
    inline = base64.urlsafe_b64encode(b"one").decode()
    remote = base64.urlsafe_b64encode(b"two").decode().rstrip("=")
    message = {"payload": {"parts": [pdf(data=inline), pdf(attachment_id="att")]}}
    gmail, messages = gmail_with(message=message, attachments={"att": {"data": remote}})
    assert gmail.pdf_attachments("m1") == [b"one", b"two"]
    kw = [kw for name, kw in messages.calls if name == "attachments.get"][0]
    assert kw == {"userId": "me", "messageId": "m1", "id": "att"}


def test_pdf_attachments_maps_errors():
    gmail, _ = gmail_with(message=RefreshError("invalid_grant"))
    with pytest.raises(GmailRevoked):
        gmail.pdf_attachments("m1")


def test_factory_none_without_settings(tmp_path):
    assert gmail_factory_from_settings(Settings(data_dir=tmp_path, master_key_file=None)) is None
    only_id = Settings(data_dir=tmp_path, master_key_file=None, google_client_id="id")
    assert gmail_factory_from_settings(only_id) is None


def test_factory_builds_google_gmail(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        master_key_file=None,
        google_client_id="id",
        google_client_secret="secret",
    )
    assert isinstance(gmail_factory_from_settings(settings)("refresh"), GoogleGmail)
