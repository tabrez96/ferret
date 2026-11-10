from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from ferret import control
from ferret.auth.google import GoogleIdentity
from ferret.web.app import create_app
from tests.conftest import google_sign_in, link_token
from tests.test_signin import db, request_link

FAILED = "We couldn't sign you in with Google."
UNVERIFIED = "Google hasn't confirmed this email address."
UNAVAILABLE = "Google sign-in isn't set up here."


def email_sign_in(client, mailer, email="a@example.com"):
    request_link(client, email)
    return client.get("/signin/link", params={"token": link_token(mailer)})


def start(client):
    r = client.get("/signin/google")
    return r, parse_qs(urlparse(r.headers["location"]).query)


def users(data_dir):
    return db(data_dir).execute("SELECT * FROM users").fetchall()


def sign_out_locally(client):
    client.cookies.delete("ferret_session")


def test_start_redirects_to_google_and_sets_state_cookie(client):
    r, query = start(client)
    assert r.status_code == 303
    assert r.headers["location"].startswith("https://accounts.google.test/auth?")
    assert query["redirect_uri"] == ["https://ferret.test/signin/google/callback"]
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("ferret_google=")
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie


def test_start_ignores_host_header(client):
    r = client.get("/signin/google", headers={"host": "evil.test"})
    assert "ferret.test" in r.headers["location"]
    assert "evil.test" not in r.headers["location"]


def test_new_google_user_creates_account(client, data_dir):
    r = google_sign_in(client)
    assert r.status_code == 303 and r.headers["location"] == "/"
    (row,) = users(data_dir)
    assert row["email"] == "a@example.com" and row["google_sub"] == "google-sub-1"
    assert (data_dir / "users" / f"{row['id']}.db").exists() or list((data_dir / "users").iterdir())
    method = db(data_dir).execute("SELECT method FROM sessions").fetchone()["method"]
    assert method == "google"
    assert "a@example.com" in client.get("/").text


def test_google_links_existing_email_account(client, mailer, data_dir):
    email_sign_in(client, mailer)
    sign_out_locally(client)
    (before,) = users(data_dir)
    google_sign_in(client)
    (after,) = users(data_dir)
    assert after["id"] == before["id"] and after["google_sub"] == "google-sub-1"


def test_google_returning_user_by_sub(client, google, data_dir):
    google_sign_in(client)
    sign_out_locally(client)
    google.identity = GoogleIdentity("google-sub-1", "changed@example.com", True)
    r = google_sign_in(client)
    assert r.status_code == 303
    (row,) = users(data_dir)
    assert row["email"] == "a@example.com"


def test_google_email_is_lowercased(client, mailer, google, data_dir):
    email_sign_in(client, mailer)
    sign_out_locally(client)
    google.identity = GoogleIdentity("google-sub-1", "A@Example.COM", True)
    google_sign_in(client)
    assert len(users(data_dir)) == 1
    assert users(data_dir)[0]["google_sub"] == "google-sub-1"


def test_unverified_email_refused(client, google, data_dir):
    google.identity = GoogleIdentity("google-sub-1", "a@example.com", False)
    r = google_sign_in(client)
    assert r.status_code == 200
    assert UNVERIFIED in r.text and 'role="alert"' in r.text
    assert 'value="a@example.com"' in r.text
    assert users(data_dir) == []
    assert "ferret_session" not in r.headers.get("set-cookie", "")
    assert db(data_dir).execute("SELECT count(*) FROM sessions").fetchone()[0] == 0


def test_unverified_refused_even_when_linked(client, google, data_dir):
    google_sign_in(client)
    client.cookies.clear()
    google.identity = GoogleIdentity("google-sub-1", "a@example.com", False)
    r = google_sign_in(client)
    assert UNVERIFIED in r.text
    assert db(data_dir).execute("SELECT count(*) FROM sessions").fetchone()[0] == 1


def test_account_linked_to_other_google_refused(client, mailer, data_dir):
    email_sign_in(client, mailer)
    conn = control.connect(data_dir / "control.db")
    with conn:
        conn.execute("UPDATE users SET google_sub = 'other'")
    conn.close()
    client.cookies.clear()
    r = google_sign_in(client)
    assert FAILED in r.text
    assert users(data_dir)[0]["google_sub"] == "other"


def test_state_mismatch_refused(client, google):
    client.get("/signin/google")
    r = client.get("/signin/google/callback", params={"state": "wrong", "code": "c"})
    assert FAILED in r.text and google.calls == []


def test_missing_cookie_refused(client, google):
    r = client.get("/signin/google/callback", params={"state": "s", "code": "c"})
    assert FAILED in r.text and google.calls == []


def test_malformed_cookie_refused(client, google):
    for value in ("nodot", "a.b.c", "x" * 400):
        client.cookies.clear()
        client.cookies.set("ferret_google", value)
        r = client.get("/signin/google/callback", params={"state": "a", "code": "c"})
        assert FAILED in r.text
    assert google.calls == []


def test_missing_code_and_state_refused(client, google):
    _, query = start(client)
    state = query["state"][0]
    assert FAILED in client.get("/signin/google/callback", params={"state": state}).text
    assert FAILED in client.get("/signin/google/callback", params={"code": "c"}).text
    assert google.calls == []


def test_google_error_param_refused(client, google):
    _, query = start(client)
    r = client.get(
        "/signin/google/callback", params={"state": query["state"][0], "error": "server_error"}
    )
    assert FAILED in r.text and google.calls == []


def test_cancel_returns_to_signin(client):
    start(client)
    r = client.get("/signin/google/callback", params={"error": "access_denied"})
    assert r.status_code == 303 and r.headers["location"] == "/signin"
    assert "Max-Age=0" in r.headers["set-cookie"]


def test_fetch_failure_shows_notice(client, google):
    google.fail = True
    assert FAILED in google_sign_in(client).text


def test_missing_email_refused(client, google, data_dir):
    google.identity = GoogleIdentity("google-sub-1", None, True)
    assert FAILED in google_sign_in(client).text
    assert users(data_dir) == []


def test_state_cookie_cleared_after_callback(client, google):
    assert "Max-Age=0" in google_sign_in(client).headers["set-cookie"].split("ferret_google")[1]
    client.cookies.clear()
    google.fail = True
    r = google_sign_in(client)
    assert "ferret_google" in r.headers["set-cookie"] and "Max-Age=0" in r.headers["set-cookie"]


def test_state_cookie_single_use(client):
    _, query = start(client)
    params = {"state": query["state"][0], "code": "c"}
    assert client.get("/signin/google/callback", params=params).status_code == 303
    client.cookies.delete("ferret_session")
    assert FAILED in client.get("/signin/google/callback", params=params).text


def test_unconfigured_google_shows_notice(monkeypatch, master_key_file, data_dir):
    monkeypatch.setenv("FERRET_MASTER_KEY_FILE", str(master_key_file))
    monkeypatch.setenv("FERRET_DATA_DIR", str(data_dir))
    monkeypatch.delenv("FERRET_GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("FERRET_GOOGLE_CLIENT_SECRET", raising=False)
    with TestClient(create_app(), base_url="https://testserver", follow_redirects=False) as c:
        assert UNAVAILABLE in c.get("/signin/google").text
        assert UNAVAILABLE in c.get("/signin/google/callback", params={"code": "c"}).text


def test_signed_in_user_start_goes_home(client):
    google_sign_in(client)
    r = client.get("/signin/google")
    assert r.status_code == 303 and r.headers["location"] == "/"


def test_old_session_replaced_on_google_sign_in(client, mailer, data_dir):
    email_sign_in(client, mailer)
    session = client.cookies["ferret_session"]
    sign_out_locally(client)
    _, query = start(client)
    client.cookies.set("ferret_session", session)
    client.get("/signin/google/callback", params={"state": query["state"][0], "code": "c"})
    assert db(data_dir).execute("SELECT count(*) FROM sessions").fetchone()[0] == 1


def test_racing_google_first_sign_in_reuses_account(client, monkeypatch, data_dir):
    real = control.get_user_by_email
    seen = []

    def lookup(conn, email):
        if not seen:
            seen.append(email)
            control.create_user(
                conn, client.app.state.kek, "other@example.com", now=1, google_sub="google-sub-1"
            )
            return None
        return real(conn, email)

    monkeypatch.setattr(control, "get_user_by_email", lookup)
    r = google_sign_in(client)
    assert r.status_code == 303
    assert len(users(data_dir)) == 1
