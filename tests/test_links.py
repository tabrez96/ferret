from ferret.auth.links import (
    LINK_TTL_SECONDS,
    LinkResult,
    consume_link,
    issue_link,
    normalize_email,
)
from ferret.auth.tokens import hash_token

NOW = 1_800_000_000


def test_normalize_email():
    assert normalize_email("  A@Example.COM ") == "a@example.com"
    assert normalize_email("") is None
    assert normalize_email("no-at") is None
    assert normalize_email("a@b") is None
    assert normalize_email("a b@example.com") is None
    assert normalize_email("a" * 243 + "@example.com") is None  # 255 chars


def test_link_works_once(conn):
    token = issue_link(conn, "a@example.com", now=NOW)
    assert consume_link(conn, token, now=NOW + 1) == LinkResult(True, "a@example.com")
    assert consume_link(conn, token, now=NOW + 2) == LinkResult(False, "a@example.com")


def test_link_expires_after_15_minutes(conn):
    assert LINK_TTL_SECONDS == 900
    token = issue_link(conn, "a@example.com", now=NOW)
    assert consume_link(conn, token, now=NOW + 899).ok
    token = issue_link(conn, "a@example.com", now=NOW)
    result = consume_link(conn, token, now=NOW + 900)
    assert result == LinkResult(False, "a@example.com")


def test_unknown_and_oversized_tokens(conn):
    assert consume_link(conn, "", now=NOW) == LinkResult(False, None)
    assert consume_link(conn, "nope", now=NOW) == LinkResult(False, None)
    assert consume_link(conn, "x" * 1_000_000, now=NOW) == LinkResult(False, None)


def test_only_hash_stored(conn, data_dir):
    token = issue_link(conn, "a@example.com", now=NOW)
    row = conn.execute("SELECT token_hash FROM login_links").fetchone()
    assert row["token_hash"] == hash_token(token)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    assert token.encode() not in (data_dir / "control.db").read_bytes()


def test_old_links_purged(conn):
    issue_link(conn, "old@example.com", now=NOW)
    issue_link(conn, "new@example.com", now=NOW + 2 * 24 * 60 * 60)
    emails = [r["email"] for r in conn.execute("SELECT email FROM login_links")]
    assert emails == ["new@example.com"]
