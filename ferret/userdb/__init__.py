"""Per-user encrypted database."""

import re
from pathlib import Path

from sqlcipher3 import dbapi2 as sqlcipher

from ferret.db import migrate
from ferret.keys import sqlcipher_key
from ferret.userdb.schema import MIGRATIONS

USER_ID_RE = re.compile(r"[0-9a-f]{32}")


class UserDbKeyError(Exception):
    """The key does not open this user database (wrong DEK or not a database)."""


def user_db_path(users_dir: Path, user_id: str) -> Path:
    if not USER_ID_RE.fullmatch(user_id):
        raise ValueError("invalid user id")
    return users_dir / f"{user_id}.db"


def open_user_db(users_dir: Path, user_id: str, dek: bytes) -> sqlcipher.Connection:
    path = user_db_path(users_dir, user_id)
    users_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    # A request's connection may hop worker threads, but is never used concurrently.
    conn = sqlcipher.connect(str(path), check_same_thread=False)
    # Raw-key form (no passphrase KDF). Must be the first statement on the connection.
    conn.execute(f"PRAGMA key = \"x'{sqlcipher_key(dek).hex()}'\"")
    row = conn.execute("PRAGMA cipher_version").fetchone()
    if not row or not row[0]:
        conn.close()
        raise RuntimeError(
            "SQLCipher is not available; refusing to open an unencrypted user database"
        )
    try:
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except sqlcipher.DatabaseError as exc:
        conn.close()
        raise UserDbKeyError("cannot open user database") from exc
    conn.row_factory = sqlcipher.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn, MIGRATIONS)
    return conn
