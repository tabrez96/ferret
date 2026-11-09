"""control.db: accounts, sessions, jobs and wrapped keys. Holds nothing financial."""

import sqlite3
import uuid
from pathlib import Path

from ferret.db import migrate
from ferret.keys import new_dek, unwrap_dek, wrap_dek

_V1 = """
CREATE TABLE users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    google_sub TEXT UNIQUE,
    wrapped_dek BLOB NOT NULL,
    created_at INTEGER NOT NULL
) STRICT;
CREATE TABLE sessions (
    id_hash BLOB PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
) STRICT;
CREATE INDEX sessions_user ON sessions(user_id);
CREATE TABLE login_links (
    token_hash BLOB PRIMARY KEY,
    email TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    used_at INTEGER
) STRICT;
CREATE TABLE mcp_tokens (
    id INTEGER PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash BLOB NOT NULL UNIQUE,
    created_at INTEGER NOT NULL,
    last_used_at INTEGER,
    revoked_at INTEGER
) STRICT;
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY,
    user_id TEXT,
    kind TEXT NOT NULL CHECK (kind IN ('parse_statement', 'gmail_poll', 'sweep_pending',
                                       'delete_account')),
    payload_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'done', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    run_after INTEGER NOT NULL,
    created_at INTEGER NOT NULL
) STRICT;
CREATE INDEX jobs_ready ON jobs(status, run_after);
CREATE TABLE problem_reports (
    id INTEGER PRIMARY KEY,
    bank TEXT NOT NULL,
    statement_month TEXT NOT NULL,
    currency TEXT NOT NULL CHECK (length(currency) = 3 AND currency = upper(currency)),
    opening INTEGER NOT NULL,
    closing INTEGER NOT NULL,
    expected INTEGER NOT NULL,
    parsed INTEGER NOT NULL,
    created_at INTEGER NOT NULL
) STRICT;
"""

# jobs.user_id has no foreign key on purpose: sweep_pending is global and delete_account removes
# the user row itself. problem_reports has no user id by design.
MIGRATIONS: list[str] = [_V1]


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    migrate(conn, MIGRATIONS)
    return conn


def create_user(
    conn: sqlite3.Connection,
    kek: bytes,
    email: str,
    *,
    now: int,
    google_sub: str | None = None,
) -> tuple[str, bytes]:
    """Create a user with a fresh data key. Returns `(user_id, dek)`."""
    user_id = uuid.uuid4().hex
    dek = new_dek()
    with conn:
        conn.execute(
            "INSERT INTO users (id, email, google_sub, wrapped_dek, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (user_id, email, google_sub, wrap_dek(kek, dek, user_id), now),
        )
    return user_id, dek


def load_dek(conn: sqlite3.Connection, kek: bytes, user_id: str) -> bytes:
    row = conn.execute("SELECT wrapped_dek FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise LookupError("unknown user")
    return unwrap_dek(kek, row["wrapped_dek"], user_id)
