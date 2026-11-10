import sqlite3

from ferret import control
from ferret.auth.sessions import SESSION_TTL_SECONDS
from ferret.keys import load_master_key
from ferret.userdb import open_user_db
from tests.conftest import csrf_token, link_token

EMAIL = "a@example.com"


def request_link(client, email=EMAIL):
    return client.post("/signin/email", data={"email": email, "csrf_token": csrf_token(client)})


def sign_in(client, mailer, email=EMAIL):
    request_link(client, email)
    return client.get("/signin/link", params={"token": link_token(mailer)})


class db:
    """Short-lived read connection to control.db; use `db(data_dir).one(sql)` / `.all(sql)`."""

    def __init__(self, data_dir):
        self.path = data_dir / "control.db"

    def _run(self, sql):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute(sql).fetchall()
        finally:
            conn.close()

    def execute(self, sql):
        rows = self._run(sql)

        class Result:
            def fetchone(self):
                return rows[0] if rows else None

            def fetchall(self):
                return rows

        return Result()


def test_signin_page_renders(client):
    r = client.get("/signin")
    assert r.status_code == 200
    assert "Sign in to Ferret" in r.text


def test_request_link_sends_email_and_shows_sent_state(client, mailer):
    r = request_link(client, " A@Example.com ")
    assert r.status_code == 200
    assert "Check your inbox" in r.text and EMAIL in r.text
    to, _, body = mailer.sent[0]
    assert to == EMAIL
    assert "https://ferret.test/signin/link?token=" in body


def test_link_uses_base_url_not_host_header(client, mailer):
    client.get("/signin")
    client.post(
        "/signin/email",
        data={"email": EMAIL, "csrf_token": client.cookies["ferret_csrf"]},
        headers={"host": "evil.test"},
    )
    assert "evil.test" not in mailer.sent[0][2]


def test_link_signs_in_and_redirects(client, mailer):
    r = sign_in(client, mailer)
    assert r.status_code == 303 and r.headers["location"] == "/"
    cookie = next(c for c in r.headers.get_list("set-cookie") if c.startswith("ferret_session="))
    for flag in ("HttpOnly", "Secure", "SameSite=lax", "Path=/"):
        assert flag in cookie
    home = client.get("/")
    assert home.status_code == 200
    assert EMAIL in home.text and "Sign out" in home.text


def test_link_fails_after_use(client, mailer):
    sign_in(client, mailer)
    r = client.get("/signin/link", params={"token": link_token(mailer)})
    assert "That sign-in link has expired." in r.text
    assert f'value="{EMAIL}"' in r.text


def test_link_fails_after_15_minutes(client, mailer, clock):
    request_link(client)
    clock.advance(900)
    r = client.get("/signin/link", params={"token": link_token(mailer)})
    assert "That sign-in link has expired." in r.text
    assert "ferret_session" not in client.cookies


def test_garbage_tokens_show_expired_state(client):
    for token in ("", "garbage", "x" * 60_000):
        r = client.get("/signin/link", params={"token": token})
        assert r.status_code == 200 and "That sign-in link has expired." in r.text
    assert "That sign-in link has expired." in client.get("/signin/link").text


def test_first_sign_in_creates_user_dek_and_db(client, mailer, app, data_dir):
    sign_in(client, mailer)
    row = db(data_dir).execute("SELECT * FROM users").fetchone()
    assert row["email"] == EMAIL and row["wrapped_dek"]
    kek = load_master_key(app.state.settings.master_key_file, data_dir)
    conn = control.connect(data_dir / "control.db")
    dek = control.load_dek(conn, kek, row["id"])
    conn.close()
    assert (data_dir / "users" / f"{row['id']}.db").exists()
    open_user_db(data_dir / "users", row["id"], dek).close()


def test_second_sign_in_reuses_account(client, mailer, data_dir):
    sign_in(client, mailer)
    first = db(data_dir).execute("SELECT id FROM users").fetchone()["id"]
    sign_in(client, mailer, "A@EXAMPLE.com")
    rows = db(data_dir).execute("SELECT id FROM users").fetchall()
    assert [r["id"] for r in rows] == [first]


def test_racing_first_sign_in_reuses_existing_account(client, mailer, monkeypatch, data_dir):
    request_link(client)
    real = control.get_user_by_email
    seen = []

    def lookup(conn, email):
        # The first lookup misses; the other request creates the account just after it.
        if not seen:
            seen.append(email)
            control.create_user(conn, client.app.state.kek, email, now=1)
            return None
        return real(conn, email)

    monkeypatch.setattr(control, "get_user_by_email", lookup)
    r = client.get("/signin/link", params={"token": link_token(mailer)})
    assert r.status_code == 303
    assert db(data_dir).execute("SELECT count(*) FROM users").fetchone()[0] == 1


def test_invalid_email_shows_error(client, mailer, data_dir):
    r = request_link(client, "nope")
    assert 'role="alert"' in r.text
    assert "Enter your email address, like you@example.com." in r.text
    assert mailer.sent == []
    assert db(data_dir).execute("SELECT count(*) FROM login_links").fetchone()[0] == 0


def test_send_failure_shows_error(client, mailer):
    mailer.fail = True
    r = request_link(client)
    assert "We couldn&#39;t send the link. Try again in a minute." in r.text


def test_protected_route_redirects_when_signed_out(client):
    r = client.get("/")
    assert r.status_code == 303 and r.headers["location"] == "/signin"


def test_forged_session_cookie_redirects_and_clears(client):
    client.cookies.set("ferret_session", "x")
    r = client.get("/")
    assert r.status_code == 303
    cleared = next(c for c in r.headers.get_list("set-cookie") if c.startswith("ferret_session="))
    assert "Max-Age=0" in cleared


def test_signed_in_user_visiting_signin_goes_home(client, mailer):
    sign_in(client, mailer)
    r = client.get("/signin")
    assert r.status_code == 303 and r.headers["location"] == "/"


def test_sign_out_ends_session(client, mailer, data_dir):
    sign_in(client, mailer)
    r = client.post("/signout", data={"csrf_token": client.cookies["ferret_csrf"]})
    assert r.status_code == 303 and r.headers["location"] == "/signin"
    assert client.get("/").status_code == 303
    assert db(data_dir).execute("SELECT count(*) FROM sessions").fetchone()[0] == 0


def test_old_session_deleted_on_new_sign_in(client, mailer, data_dir):
    sign_in(client, mailer)
    old = client.cookies["ferret_session"]
    sign_in(client, mailer)
    assert client.cookies["ferret_session"] != old
    assert db(data_dir).execute("SELECT count(*) FROM sessions").fetchone()[0] == 1


def test_session_expires(client, mailer, clock):
    sign_in(client, mailer)
    clock.advance(SESSION_TTL_SECONDS)
    assert client.get("/").status_code == 303
