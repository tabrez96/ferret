"""Connecting Gmail: a separate Google consent for gmail.readonly, and the stored token."""

import sqlite3
from dataclasses import dataclass, field
from typing import Protocol

import httpx
from authlib.common.errors import AuthlibBaseError
from authlib.integrations.httpx_client import OAuth2Client

from ferret.auth.google import AUTHORIZE_URL, TOKEN_URL
from ferret.config import Settings
from ferret.gmail.client import GMAIL_SCOPE
from ferret.keys import FIELD_GMAIL_REFRESH_TOKEN, encrypt_field

PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"


class GmailConnectError(Exception):
    """Connecting Gmail failed; the user sees a retry notice."""


@dataclass(frozen=True)
class GmailGrant:
    email: str
    refresh_token: str = field(repr=False)  # never in a repr, traceback or log


class GmailOAuth(Protocol):
    def authorization_url(self, *, state: str, code_verifier: str, redirect_uri: str) -> str: ...

    def fetch_grant(self, *, code: str, code_verifier: str, redirect_uri: str) -> GmailGrant: ...


class AuthlibGmail:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._transport = transport

    def _client(self, redirect_uri: str) -> OAuth2Client:
        return OAuth2Client(
            client_id=self._client_id,
            client_secret=self._client_secret,
            scope=GMAIL_SCOPE,
            redirect_uri=redirect_uri,
            code_challenge_method="S256",
            timeout=10,
            transport=self._transport,
        )

    def authorization_url(self, *, state: str, code_verifier: str, redirect_uri: str) -> str:
        # prompt=consent makes Google return a refresh token on every connect, reconnects included.
        with self._client(redirect_uri) as client:
            url, _ = client.create_authorization_url(
                AUTHORIZE_URL,
                state=state,
                code_verifier=code_verifier,
                access_type="offline",
                prompt="consent",
            )
        return url

    def fetch_grant(self, *, code: str, code_verifier: str, redirect_uri: str) -> GmailGrant:
        try:
            with self._client(redirect_uri) as client:
                token = client.fetch_token(TOKEN_URL, code=code, code_verifier=code_verifier)
                response = client.get(PROFILE_URL)
                response.raise_for_status()
                info = response.json()
        except AuthlibBaseError, httpx.HTTPError, ValueError:
            # from None: the cause can carry the token response.
            raise GmailConnectError("Gmail connect failed") from None
        refresh_token = token.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token:
            raise GmailConnectError("Google returned no refresh token")
        # The user can untick the Gmail box on Google's granular consent screen.
        if GMAIL_SCOPE not in str(token.get("scope", "")).split():
            raise GmailConnectError("Gmail access was not granted")
        email = info.get("emailAddress") if isinstance(info, dict) else None
        if not isinstance(email, str) or not email:
            raise GmailConnectError("Gmail returned no address")
        return GmailGrant(email=email, refresh_token=refresh_token)


def gmail_oauth_from_settings(settings: Settings) -> GmailOAuth | None:
    if settings.google_client_id and settings.google_client_secret:
        return AuthlibGmail(settings.google_client_id, settings.google_client_secret)
    return None


def save_connection(
    user_db: sqlite3.Connection, dek: bytes, grant: GmailGrant, *, now: int
) -> None:
    """Store the token encrypted. A reconnect resets last_checked_at; gmail_seen stops repeats."""
    ciphertext, nonce = encrypt_field(dek, grant.refresh_token, field=FIELD_GMAIL_REFRESH_TOKEN)
    with user_db:
        user_db.execute(
            "INSERT OR REPLACE INTO gmail_account (id, email, refresh_token_ciphertext, nonce,"
            " connected_at, last_checked_at, status) VALUES (1, ?, ?, ?, ?, NULL, 'connected')",
            (grant.email, ciphertext, nonce, now),
        )


def delete_connection(user_db: sqlite3.Connection) -> None:
    with user_db:
        user_db.execute("DELETE FROM gmail_account WHERE id = 1")
