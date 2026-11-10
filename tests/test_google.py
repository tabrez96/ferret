import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from ferret.auth.google import (
    GOOGLE_SCOPES,
    TOKEN_URL,
    USERINFO_URL,
    AuthlibGoogle,
    GoogleError,
    google_from_settings,
    parse_identity,
)
from ferret.config import Settings

REDIRECT = "https://ferret.test/signin/google/callback"


def make(handler) -> AuthlibGoogle:
    return AuthlibGoogle("cid", "secret", transport=httpx.MockTransport(handler))


def fetch(google: AuthlibGoogle):
    return google.fetch_identity(code="the-code", code_verifier="v" * 43, redirect_uri=REDIRECT)


def test_scopes_are_openid_email_only():
    assert GOOGLE_SCOPES == "openid email"
    assert "gmail" not in GOOGLE_SCOPES


def test_authorization_url():
    url = AuthlibGoogle("cid", "secret").authorization_url(
        state="st", code_verifier="v" * 43, redirect_uri=REDIRECT
    )
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert parsed.netloc == "accounts.google.com"
    assert query["scope"] == ["openid email"]
    assert query["client_id"] == ["cid"]
    assert query["redirect_uri"] == [REDIRECT]
    assert query["state"] == ["st"]
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"]
    assert query["prompt"] == ["select_account"]
    assert "gmail" not in url


def test_fetch_identity():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == TOKEN_URL:
            seen["body"] = parse_qs(request.content.decode())
            return httpx.Response(200, json={"access_token": "at", "token_type": "Bearer"})
        assert str(request.url) == USERINFO_URL
        assert request.headers["authorization"] == "Bearer at"
        return httpx.Response(200, json={"sub": "1", "email": "A@x.com", "email_verified": True})

    identity = fetch(make(handler))
    assert (identity.sub, identity.email, identity.email_verified) == ("1", "A@x.com", True)
    assert seen["body"]["code"] == ["the-code"]
    assert seen["body"]["code_verifier"] == ["v" * 43]


def test_fetch_identity_token_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    with pytest.raises(GoogleError):
        fetch(make(handler))


def test_fetch_identity_userinfo_error():
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == TOKEN_URL:
            return httpx.Response(200, json={"access_token": "at", "token_type": "Bearer"})
        return httpx.Response(500)

    with pytest.raises(GoogleError):
        fetch(make(handler))


@pytest.mark.parametrize("body", ["not json", json.dumps(["list"])])
def test_fetch_identity_malformed_userinfo(body):
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == TOKEN_URL:
            return httpx.Response(200, json={"access_token": "at", "token_type": "Bearer"})
        return httpx.Response(200, content=body)

    with pytest.raises(GoogleError):
        fetch(make(handler))


@pytest.mark.parametrize("sub", [None, "", 5, "x" * 256])
def test_parse_identity_bad_sub(sub):
    info = {"email": "a@x.com"} if sub is None else {"sub": sub}
    with pytest.raises(GoogleError):
        parse_identity(info)


@pytest.mark.parametrize(
    ("value", "verified"),
    [(True, True), ("true", True), (False, False), ("false", False), ("yes", False), (1, False)],
)
def test_parse_identity_verified(value, verified):
    assert parse_identity({"sub": "1", "email_verified": value}).email_verified is verified


def test_parse_identity_missing_verified_and_bad_email():
    identity = parse_identity({"sub": "1", "email": 5})
    assert identity.email is None and not identity.email_verified
    assert parse_identity({"sub": "x" * 255}).sub == "x" * 255


def test_google_from_settings():
    base = Settings(data_dir=None, master_key_file=None)  # type: ignore[arg-type]
    assert google_from_settings(base) is None
    only_id = Settings(data_dir=None, master_key_file=None, google_client_id="i")  # type: ignore[arg-type]
    assert google_from_settings(only_id) is None
    both = Settings(
        data_dir=None,  # type: ignore[arg-type]
        master_key_file=None,
        google_client_id="i",
        google_client_secret="s",
    )
    assert isinstance(google_from_settings(both), AuthlibGoogle)
