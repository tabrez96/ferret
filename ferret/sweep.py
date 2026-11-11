"""Hourly cleanup of pending statement files past their 7 days."""

import logging
import re
import sqlite3
from pathlib import Path

from ferret.control import load_dek
from ferret.pending import PENDING_TTL_SECONDS, is_expired
from ferret.userdb import USER_ID_RE, open_user_db

logger = logging.getLogger(__name__)

_FILE_RE = re.compile(r"(\d+)\.pdf\.enc")


def _remove_dir(directory: Path) -> int:
    count = 0
    for file in directory.iterdir():
        file.unlink(missing_ok=True)
        count += 1
    directory.rmdir()
    return count


def _sweep_user(user_db, directory: Path, now: int) -> int:
    deleted = 0
    for file in directory.iterdir():
        match = _FILE_RE.fullmatch(file.name)
        row = None
        if match:
            row = user_db.execute(
                "SELECT received_at FROM statements WHERE id = ?", (int(match.group(1)),)
            ).fetchone()
        if row is not None and not is_expired(row["received_at"], now):
            continue
        file.unlink(missing_ok=True)
        deleted += 1
        if row is not None:
            with user_db:
                user_db.execute(
                    "UPDATE statements SET status = 'skipped'"
                    " WHERE id = ? AND status IN ('reading', 'needs_password')",
                    (int(match.group(1)),),
                )
    # A row whose file is already gone must not wait forever.
    with user_db:
        user_db.execute(
            "UPDATE statements SET status = 'skipped'"
            " WHERE status = 'needs_password' AND received_at <= ?",
            (now - PENDING_TTL_SECONDS,),
        )
    return deleted


def sweep_pending(
    control_conn: sqlite3.Connection, kek: bytes, users_dir: Path, pending_dir: Path, *, now: int
) -> int:
    """Delete pending files past received_at + 7 days and mark their rows skipped.

    Returns the number of files deleted.
    """
    if not pending_dir.is_dir():
        return 0
    deleted = 0
    for directory in sorted(pending_dir.iterdir()):
        if not directory.is_dir() or not USER_ID_RE.fullmatch(directory.name):
            continue
        user_id = directory.name
        user_db = None
        try:
            try:
                dek = load_dek(control_conn, kek, user_id)
            except LookupError:
                deleted += _remove_dir(directory)
                continue
            user_db = open_user_db(users_dir, user_id, dek)
            deleted += _sweep_user(user_db, directory, now)
        except Exception as exc:
            # One broken user must not stop the others; type only, no content.
            logger.error("sweep: user dir failed: %s", type(exc).__name__)
        finally:
            if user_db is not None:
                user_db.close()
    logger.info("sweep: %d pending files deleted", deleted)
    return deleted
