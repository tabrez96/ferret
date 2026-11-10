import re
import sqlite3

import pytest

from ferret import control
from ferret.keys import DecryptionError


@pytest.fixture
def conn(data_dir):
    c = control.connect(data_dir / "control.db")
    yield c
    c.close()


def test_connect_creates_all_tables(conn):
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert names == {"users", "sessions", "login_links", "mcp_tokens", "jobs", "problem_reports"}


def test_create_user_stores_only_wrapped_dek(conn, kek, data_dir):
    user_id, dek = control.create_user(conn, kek, "a@example.com", now=1)
    row = conn.execute("SELECT wrapped_dek FROM users WHERE id = ?", (user_id,)).fetchone()
    assert row["wrapped_dek"] != dek
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.commit()
    assert dek not in (data_dir / "control.db").read_bytes()
    assert control.load_dek(conn, kek, user_id) == dek


def test_load_dek_with_wrong_kek_fails(conn, kek):
    user_id, _ = control.create_user(conn, kek, "a@example.com", now=1)
    with pytest.raises(DecryptionError):
        control.load_dek(conn, b"\x01" * 32, user_id)


def test_load_dek_unknown_user(conn, kek):
    with pytest.raises(LookupError):
        control.load_dek(conn, kek, "f" * 32)


def test_user_id_format(conn, kek):
    user_id, _ = control.create_user(conn, kek, "a@example.com", now=1)
    assert re.fullmatch(r"[0-9a-f]{32}", user_id)


def test_problem_report_amounts_are_integers(conn):
    sql = (
        "INSERT INTO problem_reports (bank, statement_month, currency, opening, closing,"
        " expected, parsed, created_at) VALUES ('b', '2026-01', 'AED', ?, 2, 3, 4, 5)"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, ("12.50",))
    conn.execute(sql, (1250,))


def test_deleting_user_cascades_sessions_and_tokens(conn, kek):
    user_id, _ = control.create_user(conn, kek, "a@example.com", now=1)
    conn.execute(
        "INSERT INTO sessions (id_hash, user_id, created_at, expires_at) VALUES (?, ?, 1, 2)",
        (b"h", user_id),
    )
    conn.execute(
        "INSERT INTO mcp_tokens (user_id, token_hash, created_at) VALUES (?, ?, 1)",
        (user_id, b"t"),
    )
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    assert conn.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM mcp_tokens").fetchone()[0] == 0
