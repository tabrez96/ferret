from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from ferret.auth.google import TOKEN_URL
from ferret.config import Settings
from ferret.gmail.client import GMAIL_SCOPE
from ferret.gmail.connect import (
    PROFILE_URL,
    AuthlibGmail,
    GmailConnectError,
    GmailGrant,
    delete_connection,
    gmail_oauth_from_settings,
    save_connection,
)
from ferret.keys import FIELD_GMAIL_REFRESH_TOKEN, decrypt_field

REDIRECT = "https://ferret.test/gmail/callback"
TOKEN = "1//refresh-" + "z" * 40


def make(handler) -> AuthlibGmail:
    return AuthlibGmail("cid", "secret", transport=httpx.MockTransport(handler))


def fetch(oauth: AuthlibGmail) -> GmailGrant:
    return oauth.fetch_grant(code="the-code", code_verifier="v" * 43, redirect_uri=REDIRECT)


def token_response(**overrides) -> httpx.Response:
    body = {
        "access_token": "at",
        "token_type": "Bearer",
        "refresh_token": TOKEN,
        "scope": GMAIL_SCOPE,
    }
    body.update(overrides)
    return httpx.Response(200, json={k: v for k, v in body.items() if v is not None})


def handler_for(token: httpx.Response, profile: httpx.Response | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == TOKEN_URL:
            return token
        assert str(request.url) == PROFILE_URL
        return profile or httpx.Response(200, json={"emailAddress": "g@example.com"})

    return handler


def test_authorization_url_asks_gmail_readonly_offline():
    url = AuthlibGmail("cid", "secret").authorization_url(
        state="st", code_verifier="v" * 43, redirect_uri=REDIRECT
    )
    query = parse_qs(urlparse(url).query)
    assert query["scope"] == [GMAIL_SCOPE]
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["state"] == ["st"]
    assert query["redirect_uri"] == [REDIRECT]


def test_fetch_grant():
    grant = fetch(make(handler_for(token_response())))
    assert (grant.email, grant.refresh_token) == ("g@example.com", TOKEN)
    assert TOKEN not in repr(grant)


@pytest.mark.parametrize(
    "token",
    [
        token_response(refresh_token=None),
        token_response(scope="openid email"),
        httpx.Response(400, json={"error": "invalid_grant"}),
    ],
    ids=["no-refresh-token", "scope-missing", "token-endpoint-400"],
)
def test_fetch_grant_rejects_token(token):
    with pytest.raises(GmailConnectError):
        fetch(make(handler_for(token)))


@pytest.mark.parametrize(
    "profile",
    [httpx.Response(500), httpx.Response(200, json={}), httpx.Response(200, content="nope")],
    ids=["500", "no-address", "not-json"],
)
def test_fetch_grant_rejects_profile(profile):
    with pytest.raises(GmailConnectError):
        fetch(make(handler_for(token_response(), profile)))


def test_from_settings(monkeypatch, tmp_path):
    base = Settings.from_env({"FERRET_DATA_DIR": str(tmp_path)})
    assert gmail_oauth_from_settings(base) is None
    configured = Settings.from_env(
        {
            "FERRET_DATA_DIR": str(tmp_path),
            "FERRET_GOOGLE_CLIENT_ID": "cid",
            "FERRET_GOOGLE_CLIENT_SECRET": "secret",
        }
    )
    assert isinstance(gmail_oauth_from_settings(configured), AuthlibGmail)


def test_save_and_delete_connection(user, clock):
    grant = GmailGrant("g@example.com", TOKEN)
    save_connection(user.db, user.dek, grant, now=clock())
    row = user.db.execute("SELECT * FROM gmail_account").fetchone()
    assert row["refresh_token_ciphertext"] != TOKEN.encode()
    assert TOKEN.encode() not in row["refresh_token_ciphertext"]
    decrypted = decrypt_field(
        user.dek, row["refresh_token_ciphertext"], row["nonce"], field=FIELD_GMAIL_REFRESH_TOKEN
    )
    assert decrypted == TOKEN
    assert (row["status"], row["last_checked_at"], row["email"]) == (
        "connected",
        None,
        "g@example.com",
    )
    delete_connection(user.db)
    assert user.db.execute("SELECT COUNT(*) FROM gmail_account").fetchone()[0] == 0


def test_reconnect_resets_status(user, clock):
    grant = GmailGrant("g@example.com", TOKEN)
    save_connection(user.db, user.dek, grant, now=clock())
    with user.db:
        user.db.execute("UPDATE gmail_account SET status = 'stopped', last_checked_at = 5")
    save_connection(user.db, user.dek, grant, now=clock())
    row = user.db.execute("SELECT status, last_checked_at FROM gmail_account").fetchone()
    assert tuple(row) == ("connected", None)
