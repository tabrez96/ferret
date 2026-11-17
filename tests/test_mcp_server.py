import json

from ferret import control
from ferret.auth.tokens import hash_token, new_token
from ferret.mcp import auth
from ferret.userdb import open_user_db
from tests.test_spending import add_card, add_statement, add_tx


def add_token(conn, user_id, now):
    token = new_token()
    with conn:
        conn.execute(
            "INSERT INTO mcp_tokens (user_id, token_hash, created_at) VALUES (?, ?, ?)",
            (user_id, hash_token(token), now),
        )
    return token


def make_user(app, conn, clock, email, last4, merchant):
    user_id, dek = control.create_user(conn, app.state.kek, email, now=clock())
    db = open_user_db(app.state.settings.users_dir, user_id, dek)
    card = add_card(db, last4)
    add_tx(db, add_statement(db, card), card, "2026-10-05", merchant, 1000)
    db.commit()
    db.close()
    return user_id, add_token(conn, user_id, clock())


def rpc(client, token, method, params=None, headers=None):
    headers = {"Accept": "application/json, text/event-stream", **(headers or {})}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return client.post(
        "/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
    )


def call(client, token, name, arguments=None):
    response = rpc(client, token, "tools/call", {"name": name, "arguments": arguments or {}})
    assert response.status_code == 200
    return response.json()["result"]


def payload(result):
    assert result["isError"] is False
    return json.loads(result["content"][0]["text"])


def merchants(client, token, arguments=None):
    found = payload(call(client, token, "search_transactions", arguments))
    return [t["merchant"] for t in found["transactions"]]


def test_token_reads_only_its_own_users_data(client, app, conn, clock):
    _, token_a = make_user(app, conn, clock, "a@example.com", "1111", "Alpha Mart")
    _, token_b = make_user(app, conn, clock, "b@example.com", "2222", "Bravo Bazaar")
    cards_a = payload(call(client, token_a, "list_cards"))["cards"]
    assert [c["last4"] for c in cards_a] == ["1111"]
    assert merchants(client, token_a) == ["Alpha Mart"]
    assert merchants(client, token_a, {"query": "Bravo"}) == []
    cards_b = payload(call(client, token_b, "list_cards"))["cards"]
    assert [c["last4"] for c in cards_b] == ["2222"]
    assert merchants(client, token_b) == ["Bravo Bazaar"]


def test_tools_take_no_user_argument(client, app, conn, clock):
    _, token = make_user(app, conn, clock, "a@example.com", "1111", "Alpha Mart")
    tools = rpc(client, token, "tools/list").json()["result"]["tools"]
    assert {t["name"] for t in tools} == {
        "list_cards",
        "list_statements",
        "spending_summary",
        "top_merchants",
        "search_transactions",
    }
    for tool in tools:
        for key in tool["inputSchema"].get("properties", {}):
            assert "user" not in key and "ctx" not in key


def test_revoked_token_refused(client, app, conn, clock):
    _, token = make_user(app, conn, clock, "a@example.com", "1111", "Alpha Mart")
    with conn:
        conn.execute("UPDATE mcp_tokens SET revoked_at = ?", (clock(),))
    response = rpc(client, token, "tools/call", {"name": "list_cards", "arguments": {}})
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"].startswith("Bearer")
    assert conn.execute("SELECT last_used_at FROM mcp_tokens").fetchone()[0] is None


def test_missing_or_unknown_token_refused(client, app, conn, clock):
    make_user(app, conn, clock, "a@example.com", "1111", "Alpha Mart")
    assert rpc(client, None, "tools/list").status_code == 401
    assert rpc(client, "not-a-real-token", "tools/list").status_code == 401
    basic = rpc(client, None, "tools/list", headers={"Authorization": "Basic abc"})
    assert basic.status_code == 401
    assert conn.execute("SELECT count(*) FROM rate_events").fetchone()[0] == 0


def test_last_used_at_logged(client, app, conn, clock):
    _, token = make_user(app, conn, clock, "a@example.com", "1111", "Alpha Mart")
    clock.advance(5)
    payload(call(client, token, "list_cards"))
    row = conn.execute("SELECT last_used_at FROM mcp_tokens").fetchone()
    assert row[0] == clock()


def test_rate_limit_per_token(client, app, conn, clock, monkeypatch):
    monkeypatch.setattr(auth, "MCP_LIMIT", 2)
    user_id, token = make_user(app, conn, clock, "a@example.com", "1111", "Alpha Mart")
    other = add_token(conn, user_id, clock())
    payload(call(client, token, "list_cards"))
    payload(call(client, token, "list_cards"))
    limited = rpc(client, token, "tools/call", {"name": "list_cards", "arguments": {}})
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "60"
    payload(call(client, other, "list_cards"))
    clock.advance(auth.MCP_WINDOW_SECONDS)
    payload(call(client, token, "list_cards"))


def test_unknown_card_is_tool_error(client, app, conn, clock):
    _, token = make_user(app, conn, clock, "a@example.com", "1111", "Alpha Mart")
    result = call(client, token, "spending_summary", {"month": "2026-10", "card_id": 999})
    assert result["isError"] is True
