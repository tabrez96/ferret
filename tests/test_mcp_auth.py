import pytest

from ferret import control
from ferret.auth.tokens import hash_token, new_token
from ferret.mcp import auth
from ferret.mcp.auth import McpCaller, admit, bearer_token, find_token, rate_bucket


def add_token(conn, user_id, now):
    token = new_token()
    with conn:
        cur = conn.execute(
            "INSERT INTO mcp_tokens (user_id, token_hash, created_at) VALUES (?, ?, ?)",
            (user_id, hash_token(token), now),
        )
    return token, cur.lastrowid


@pytest.fixture
def user_id(conn, kek, clock):
    return control.create_user(conn, kek, "a@example.com", now=clock())[0]


def last_used(conn, token_id):
    row = conn.execute("SELECT last_used_at FROM mcp_tokens WHERE id = ?", (token_id,)).fetchone()
    return row["last_used_at"]


def test_bearer_token_parsing():
    assert bearer_token("Bearer abc") == "abc"
    assert bearer_token("bearer abc") == "abc"
    for bad in (None, "", "Basic abc", "Bearer ", "Bearer " + "x" * 129):
        assert bearer_token(bad) is None


def test_find_token_active_unknown_revoked(conn, user_id, clock):
    token, token_id = add_token(conn, user_id, clock())
    assert find_token(conn, token) == McpCaller(user_id, token_id)
    assert find_token(conn, "not-a-real-token") is None
    assert find_token(conn, None) is None
    with conn:
        conn.execute("UPDATE mcp_tokens SET revoked_at = 1")
    assert find_token(conn, token) is None


def test_admit_logs_last_used_and_limits(conn, user_id, clock, monkeypatch):
    monkeypatch.setattr(auth, "MCP_LIMIT", 2)
    _, token_id = add_token(conn, user_id, clock())
    caller = McpCaller(user_id, token_id)
    now = clock()
    assert admit(conn, caller, now=now)
    assert admit(conn, caller, now=now)
    assert last_used(conn, token_id) == now
    assert not admit(conn, caller, now=now + 1)
    assert last_used(conn, token_id) == now
    assert admit(conn, caller, now=now + auth.MCP_WINDOW_SECONDS)


def test_rate_bucket_cleared_on_account_delete(conn, user_id, clock):
    _, token_id = add_token(conn, user_id, clock())
    caller = McpCaller(user_id, token_id)
    assert admit(conn, caller, now=clock())
    assert rate_bucket(caller).endswith(f":{user_id}")
    control.delete_user(conn, user_id)
    assert conn.execute("SELECT count(*) FROM rate_events").fetchone()[0] == 0
