"""The Gmail interface the poll job uses, and the Google client behind it."""

import base64
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import httplib2
from google.auth.exceptions import RefreshError, TransportError
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from ferret.config import Settings


class GmailError(Exception):
    """A Gmail call failed; the next poll tries again."""


class GmailRevoked(GmailError):
    """Google rejected the refresh token (revoked or expired)."""


class GmailApi(Protocol):
    def search(self, query: str) -> list[str]:
        """Message ids, newest first."""
        ...

    def pdf_attachments(self, message_id: str) -> list[bytes]: ...


GmailFactory = Callable[[str], GmailApi]  # refresh token -> client

GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
TOKEN_URL = "https://oauth2.googleapis.com/token"
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024  # same limit as a manual upload
_PAGE_SIZE = 100
_RETRIES = 2  # googleapiclient retries 429/5xx with backoff
_REVOKED_403_REASONS = ("insufficientPermissions", "ACCESS_TOKEN_SCOPE_INSUFFICIENT")


@dataclass(frozen=True)
class PdfPart:
    attachment_id: str | None  # set when the body must be fetched separately
    data: str | None  # base64url body when Gmail sent it inline


def pdf_parts(payload: Mapping[str, Any]) -> list[PdfPart]:
    """PDF attachments in a Gmail message payload (format=full), in message order."""

    def _walk(part: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
        yield part
        for child in part.get("parts") or []:
            if isinstance(child, Mapping):
                yield from _walk(child)

    found = []
    for part in _walk(payload):
        is_pdf = str(part.get("mimeType", "")).lower() == "application/pdf" or str(
            part.get("filename", "")
        ).lower().endswith(".pdf")
        if not is_pdf:
            continue
        body = part.get("body") or {}
        if body.get("size", 0) > MAX_ATTACHMENT_BYTES:
            continue
        if body.get("attachmentId"):
            found.append(PdfPart(attachment_id=body["attachmentId"], data=None))
        elif body.get("data"):
            found.append(PdfPart(attachment_id=None, data=body["data"]))
    return found


def decode_body(data: str) -> bytes:
    """Gmail bodies are base64url, sometimes without padding."""
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def map_error(exc: Exception) -> GmailError:
    """Turn a Google client failure into the poll job's error types."""
    if isinstance(exc, RefreshError):
        if "invalid_grant" in str(exc):
            return GmailRevoked("refresh token rejected")
        return GmailError("token refresh failed")
    if isinstance(exc, HttpError):
        status = exc.resp.status
        if status == 401:
            return GmailRevoked("unauthorised")
        content = (exc.content or b"").decode("utf-8", "replace")
        if status == 403 and any(reason in content for reason in _REVOKED_403_REASONS):
            return GmailRevoked("gmail scope not granted")
        return GmailError(f"gmail http {status}")
    return GmailError(type(exc).__name__)


_GOOGLE_ERRORS = (
    RefreshError,
    TransportError,
    HttpError,
    httplib2.HttpLib2Error,
    OSError,
    ValueError,
)


class GoogleGmail:
    def __init__(self, service: Any) -> None:
        self._messages = service.users().messages()

    @classmethod
    def from_refresh_token(
        cls, refresh_token: str, *, client_id: str, client_secret: str
    ) -> GoogleGmail:
        credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri=TOKEN_URL,
            client_id=client_id,
            client_secret=client_secret,
            scopes=[GMAIL_SCOPE],
        )
        # The discovery document bundled with the library is used: nothing is fetched here.
        service = build(
            "gmail", "v1", credentials=credentials, cache_discovery=False, static_discovery=True
        )
        return cls(service)

    def search(self, query: str) -> list[str]:
        ids: list[str] = []
        page_token: str | None = None
        try:
            while True:
                response = self._messages.list(
                    userId="me", q=query, maxResults=_PAGE_SIZE, pageToken=page_token
                ).execute(num_retries=_RETRIES)
                ids.extend(m["id"] for m in response.get("messages", []))
                page_token = response.get("nextPageToken")
                if not page_token:
                    return ids
        except _GOOGLE_ERRORS as exc:
            raise map_error(exc) from exc

    def pdf_attachments(self, message_id: str) -> list[bytes]:
        try:
            message = self._messages.get(userId="me", id=message_id, format="full").execute(
                num_retries=_RETRIES
            )
            files = []
            for part in pdf_parts(message.get("payload") or {}):
                data = part.data
                if data is None:
                    data = (
                        self._messages.attachments()
                        .get(userId="me", messageId=message_id, id=part.attachment_id)
                        .execute(num_retries=_RETRIES)["data"]
                    )
                files.append(decode_body(data))
            return files
        except _GOOGLE_ERRORS as exc:
            raise map_error(exc) from exc


def gmail_factory_from_settings(settings: Settings) -> GmailFactory | None:
    client_id, client_secret = settings.google_client_id, settings.google_client_secret
    if not (client_id and client_secret):
        return None

    def factory(refresh_token: str) -> GmailApi:
        return GoogleGmail.from_refresh_token(
            refresh_token, client_id=client_id, client_secret=client_secret
        )

    return factory
