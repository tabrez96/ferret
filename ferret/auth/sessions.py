"""Server-side sessions. The cookie holds a random token; control.db holds its hash."""

import sqlite3
from dataclasses import dataclass

from ferret.auth.tokens import hash_token, new_token

SESSION_TTL_SECONDS = 30 * 24 * 60 * 60
_MAX_TOKEN_LENGTH = 128


@dataclass(frozen=True)
class SessionUser:
    user_id: str
    email: str
    method: str  # "email" | "google"


def create_session(
    conn: sqlite3.Connection, user_id: str, *, now: int, method: str = "email"
) -> str:
    token = new_token()
    with conn:
        conn.execute("DELETE FROM sessions WHERE user_id = ? AND expires_at <= ?", (user_id, now))
        conn.execute(
            "INSERT INTO sessions (id_hash, user_id, created_at, expires_at, method)"
            " VALUES (?, ?, ?, ?, ?)",
            (hash_token(token), user_id, now, now + SESSION_TTL_SECONDS, method),
        )
    return token


def get_session_user(
    conn: sqlite3.Connection, token: str | None, *, now: int
) -> SessionUser | None:
    if not token or len(token) > _MAX_TOKEN_LENGTH:
        return None
    row = conn.execute(
        "SELECT users.id AS user_id, users.email AS email, sessions.method AS method"
        " FROM sessions JOIN users ON users.id = sessions.user_id"
        " WHERE sessions.id_hash = ? AND sessions.expires_at > ?",
        (hash_token(token), now),
    ).fetchone()
    if row is None:
        return None
    return SessionUser(user_id=row["user_id"], email=row["email"], method=row["method"])


def delete_session(conn: sqlite3.Connection, token: str | None) -> None:
    if not token or len(token) > _MAX_TOKEN_LENGTH:
        return
    with conn:
        conn.execute("DELETE FROM sessions WHERE id_hash = ?", (hash_token(token),))
