"""Sliding-window rate limits, stored in control.db and shared by every process."""

import sqlite3


def allow(conn: sqlite3.Connection, bucket: str, *, now: int, limit: int, window: int) -> bool:
    """Record one event in `bucket` and return True, unless `limit` events are in the window."""
    with conn:
        conn.execute("DELETE FROM rate_events WHERE bucket = ? AND at <= ?", (bucket, now - window))
        (count,) = conn.execute(
            "SELECT count(*) FROM rate_events WHERE bucket = ?", (bucket,)
        ).fetchone()
        if count >= limit:
            return False
        conn.execute("INSERT INTO rate_events (bucket, at) VALUES (?, ?)", (bucket, now))
        return True
