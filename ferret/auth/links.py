"""Emailed sign-in links: single use, 15 minutes, stored as hashes."""

import re
import sqlite3
from dataclasses import dataclass

from ferret.auth.tokens import hash_token, new_token

LINK_TTL_SECONDS = 15 * 60
_KEEP_SECONDS = 24 * 60 * 60  # old rows kept a day so the expired state can pre-fill the email
_MAX_TOKEN_LENGTH = 128
_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


@dataclass(frozen=True)
class LinkResult:
    ok: bool
    email: str | None


def normalize_email(raw: str) -> str | None:
    email = raw.strip().lower()
    if not email or len(email) > 254 or not _EMAIL_RE.fullmatch(email):
        return None
    return email


def issue_link(conn: sqlite3.Connection, email: str, *, now: int) -> str:
    token = new_token()
    with conn:
        conn.execute("DELETE FROM login_links WHERE expires_at < ?", (now - _KEEP_SECONDS,))
        conn.execute(
            "INSERT INTO login_links (token_hash, email, expires_at, used_at)"
            " VALUES (?, ?, ?, NULL)",
            (hash_token(token), email, now + LINK_TTL_SECONDS),
        )
    return token


def consume_link(conn: sqlite3.Connection, token: str, *, now: int) -> LinkResult:
    if not token or len(token) > _MAX_TOKEN_LENGTH:
        return LinkResult(False, None)
    token_hash = hash_token(token)
    # One UPDATE ... RETURNING keeps the link single-use even when two clicks race.
    with conn:
        row = conn.execute(
            "UPDATE login_links SET used_at = :now"
            " WHERE token_hash = :h AND used_at IS NULL AND expires_at > :now RETURNING email",
            {"now": now, "h": token_hash},
        ).fetchone()
    if row is not None:
        return LinkResult(True, row["email"])
    row = conn.execute(
        "SELECT email FROM login_links WHERE token_hash = ?", (token_hash,)
    ).fetchone()
    return LinkResult(False, row["email"] if row else None)
