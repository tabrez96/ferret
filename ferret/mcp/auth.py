"""MCP bearer tokens: look up by SHA-256, refuse revoked ones, rate limit per token."""

import sqlite3
from dataclasses import dataclass

from ferret import ratelimit
from ferret.auth.tokens import hash_token

MCP_LIMIT = 60
MCP_WINDOW_SECONDS = 60
_MAX_TOKEN_LENGTH = 128


@dataclass(frozen=True)
class McpCaller:
    user_id: str
    token_id: int


def bearer_token(authorization: str | None) -> str | None:
    """The token from an `Authorization: Bearer <token>` header, else None."""
    scheme, _, value = (authorization or "").partition(" ")
    value = value.strip()
    if scheme.lower() != "bearer" or not value or len(value) > _MAX_TOKEN_LENGTH:
        return None
    return value


def find_token(conn: sqlite3.Connection, token: str | None) -> McpCaller | None:
    """The caller for an active token. None when missing, unknown or revoked."""
    if token is None:
        return None
    row = conn.execute(
        "SELECT id, user_id FROM mcp_tokens WHERE token_hash = ? AND revoked_at IS NULL",
        (hash_token(token),),
    ).fetchone()
    return None if row is None else McpCaller(row["user_id"], row["id"])


def rate_bucket(caller: McpCaller) -> str:
    # Ends in `:<user_id>` so control.delete_user clears it with the account.
    return f"mcp:{caller.token_id}:{caller.user_id}"


def admit(conn: sqlite3.Connection, caller: McpCaller, *, now: int) -> bool:
    """Count one request against the token's limit and log last_used_at. False when over."""
    if not ratelimit.allow(
        conn, rate_bucket(caller), now=now, limit=MCP_LIMIT, window=MCP_WINDOW_SECONDS
    ):
        return False
    with conn:
        conn.execute("UPDATE mcp_tokens SET last_used_at = ? WHERE id = ?", (now, caller.token_id))
    return True
