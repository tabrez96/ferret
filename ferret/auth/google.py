"""Google sign-in (OpenID Connect). Asks only for openid and email; Gmail is a separate step."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

import httpx
from authlib.common.errors import AuthlibBaseError
from authlib.integrations.httpx_client import OAuth2Client

from ferret.config import Settings

GOOGLE_SCOPES = "openid email"
AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
_MAX_SUB_LENGTH = 255


class GoogleError(Exception):
    """Google sign-in failed; the user sees the generic Google notice."""


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str | None
    email_verified: bool


class GoogleOAuth(Protocol):
    def authorization_url(self, *, state: str, code_verifier: str, redirect_uri: str) -> str: ...

    def fetch_identity(
        self, *, code: str, code_verifier: str, redirect_uri: str
    ) -> GoogleIdentity: ...


def parse_identity(info: Mapping[str, object]) -> GoogleIdentity:
    sub = info.get("sub")
    if not isinstance(sub, str) or not sub or len(sub) > _MAX_SUB_LENGTH:
        raise GoogleError("Google returned no usable account id")
    email = info.get("email")
    verified = info.get("email_verified")
    return GoogleIdentity(
        sub=sub,
        email=email if isinstance(email, str) else None,
        email_verified=verified is True or verified == "true",
    )


class AuthlibGoogle:
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
            scope=GOOGLE_SCOPES,
            redirect_uri=redirect_uri,
            code_challenge_method="S256",
            timeout=10,
            transport=self._transport,
        )

    def authorization_url(self, *, state: str, code_verifier: str, redirect_uri: str) -> str:
        with self._client(redirect_uri) as client:
            url, _ = client.create_authorization_url(
                AUTHORIZE_URL,
                state=state,
                code_verifier=code_verifier,
                prompt="select_account",
            )
        return url

    def fetch_identity(self, *, code: str, code_verifier: str, redirect_uri: str) -> GoogleIdentity:
        # The identity comes from the userinfo endpoint over TLS, using the access token just
        # obtained with the code, PKCE verifier and client secret, so no ID token is parsed.
        try:
            with self._client(redirect_uri) as client:
                client.fetch_token(TOKEN_URL, code=code, code_verifier=code_verifier)
                response = client.get(USERINFO_URL)
                response.raise_for_status()
                info = response.json()
        except (AuthlibBaseError, httpx.HTTPError, ValueError) as exc:
            raise GoogleError("Google sign-in failed") from exc
        if not isinstance(info, dict):
            raise GoogleError("Google sign-in failed")
        return parse_identity(info)


def google_from_settings(settings: Settings) -> GoogleOAuth | None:
    if settings.google_client_id and settings.google_client_secret:
        return AuthlibGoogle(settings.google_client_id, settings.google_client_secret)
    return None
