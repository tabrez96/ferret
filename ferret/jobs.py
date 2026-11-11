"""Background jobs in control.db. Payloads hold ids only."""

import json
import sqlite3
from dataclasses import dataclass

KINDS = ("parse_statement", "gmail_poll", "sweep_pending", "delete_account")


@dataclass(frozen=True)
class Job:
    id: int
    user_id: str | None
    kind: str
    payload: dict
    attempts: int


def enqueue(
    conn: sqlite3.Connection,
    kind: str,
    *,
    user_id: str | None,
    payload: dict | None = None,
    now: int,
    run_after: int | None = None,
) -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO jobs (user_id, kind, payload_json, run_after, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                user_id,
                kind,
                json.dumps(payload or {}),
                now if run_after is None else run_after,
                now,
            ),
        )
    return cur.lastrowid


_CLAIM = """
SELECT * FROM jobs j
WHERE j.status = 'queued' AND j.run_after <= :now
  AND (j.user_id IS NULL OR NOT EXISTS (
       SELECT 1 FROM jobs r WHERE r.user_id = j.user_id AND r.status = 'running'))
ORDER BY j.run_after, j.id LIMIT 1
"""


def claim_next(conn: sqlite3.Connection, *, now: int) -> Job | None:
    """Claim the next ready job, never two running jobs for one user."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(_CLAIM, {"now": now}).fetchone()
        if row is None:
            conn.commit()
            return None
        conn.execute(
            "UPDATE jobs SET status = 'running', attempts = attempts + 1 WHERE id = ?",
            (row["id"],),
        )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return Job(
        id=row["id"],
        user_id=row["user_id"],
        kind=row["kind"],
        payload=json.loads(row["payload_json"]),
        attempts=row["attempts"] + 1,
    )


def _set_status(conn: sqlite3.Connection, job_id: int, status: str) -> None:
    with conn:
        conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))


def finish(conn: sqlite3.Connection, job_id: int) -> None:
    _set_status(conn, job_id, "done")


def fail(conn: sqlite3.Connection, job_id: int) -> None:
    """Mark a job failed. There is no automatic retry yet."""
    _set_status(conn, job_id, "failed")


def requeue_stale(conn: sqlite3.Connection) -> int:
    """Put running jobs back in the queue. Call once at worker start (one worker process)."""
    with conn:
        cur = conn.execute("UPDATE jobs SET status = 'queued' WHERE status = 'running'")
    return cur.rowcount


def ensure_scheduled(conn: sqlite3.Connection, kind: str, *, now: int, run_after: int) -> None:
    """Enqueue a global job unless one of that kind is already queued or running."""
    row = conn.execute(
        "SELECT 1 FROM jobs WHERE kind = ? AND status IN ('queued', 'running') LIMIT 1", (kind,)
    ).fetchone()
    if row is None:
        enqueue(conn, kind, user_id=None, now=now, run_after=run_after)
