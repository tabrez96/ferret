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


def allow_all(
    conn: sqlite3.Connection, buckets: list[tuple[str, int]], *, now: int, window: int
) -> bool:
    """Record one event in every `(bucket, limit)` and return True, unless any bucket is full.

    A refused request records nothing, so it never uses up a bucket's allowance.
    """
    with conn:
        for bucket, _ in buckets:
            conn.execute(
                "DELETE FROM rate_events WHERE bucket = ? AND at <= ?", (bucket, now - window)
            )
        for bucket, limit in buckets:
            (count,) = conn.execute(
                "SELECT count(*) FROM rate_events WHERE bucket = ?", (bucket,)
            ).fetchone()
            if count >= limit:
                return False
        for bucket, _ in buckets:
            conn.execute("INSERT INTO rate_events (bucket, at) VALUES (?, ?)", (bucket, now))
        return True
