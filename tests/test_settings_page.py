import pytest

from ferret import control
from ferret.auth.sessions import create_session
from ferret.keys import FIELD_STATEMENT_PASSWORD, decrypt_field
from ferret.pipeline.locked import save_password
from ferret.userdb import open_user_db
from ferret.web.security import CSRF_COOKIE, SESSION_COOKIE

HX = {"HX-Request": "true"}
SECRET = "Sup3r-Secret"


@pytest.fixture
def env(client, app, conn, clock):
    user_id, dek = control.create_user(conn, app.state.kek, "p@example.com", now=clock())
    client.cookies.set(SESSION_COOKIE, create_session(conn, user_id, now=clock()))
    db = open_user_db(app.state.settings.users_dir, user_id, dek)
    client.get("/signin")
    yield db, dek
    db.close()


def add_card(db, dek, last4, *, password=None):
    with db:
        card = db.execute(
            "INSERT INTO cards (bank, last4, currency) VALUES ('Emirates NBD', ?, 'AED')", (last4,)
        ).lastrowid
    if password:
        save_password(db, dek, bank="Emirates NBD", card_id=card, password=password, now=1)
    return card


def password_id(db):
    return db.execute("SELECT id FROM statement_passwords").fetchone()["id"]


def stored(db, pid):
    return db.execute("SELECT * FROM statement_passwords WHERE id = ?", (pid,)).fetchone()


def post(client, path, **data):
    return client.post(
        path,
        data={"csrf_token": client.cookies[CSRF_COOKIE], **data},
        headers=HX,
        follow_redirects=False,
    )


def test_settings_requires_sign_in(client):
    r = client.get("/settings", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/signin")


def test_settings_page_sections(client, env):
    r = client.get("/settings")
    assert r.status_code == 200
    for part in (
        "Settings",
        'aria-current="page"',
        "Gmail",
        "AI chatbots (MCP)",
        "Statement passwords",
        "Delete account",
        "Not connected",
    ):
        assert part in r.text
    assert "Passwords appear here after your first locked statement." in r.text
    assert "passwords-table" not in r.text


def test_rows_and_password_never_rendered(client, env):
    db, dek = env
    add_card(db, dek, "4821", password=SECRET)
    add_card(db, dek, "1177")
    pid = password_id(db)
    page = client.get("/settings").text
    for part in ("Saved", "Not saved", "Asked for on the next statement"):
        assert part in page
    assert page.count(f"/settings/passwords/{pid}/replace") == 2
    assert page.count("Replace</a>") == 1 and "Remove</a>" not in page
    dialog = client.get(f"/settings/passwords/{pid}/replace", headers=HX).text
    assert SECRET not in page and SECRET not in dialog


def test_gmail_connected_status(client, env):
    db, _ = env
    with db:
        db.execute(
            "INSERT INTO gmail_account (id, email, refresh_token_ciphertext, nonce, connected_at,"
            " status) VALUES (1, 'g@example.com', x'00', x'00', 1, 'connected')"
        )
    text = client.get("/settings").text
    assert "Connected" in text and "g@example.com" in text
    with db:
        db.execute("UPDATE gmail_account SET status = 'stopped'")
    assert "Stopped" in client.get("/settings").text


def test_replace_dialog_fragment_and_full_page(client, env):
    db, dek = env
    add_card(db, dek, "4821", password=SECRET)
    path = f"/settings/passwords/{password_id(db)}/replace"
    fragment = client.get(path, headers=HX).text
    assert '<dialog class="password-dialog"' in fragment
    assert "Replace saved password" in fragment and "<h1" not in fragment
    full = client.get(path).text
    assert "<h1" in full and "password-dialog" in full and "Replace saved password" in full
    assert "</dialog>" in full and " open>" in full


def test_replace_saves_new_password(client, env):
    db, dek = env
    add_card(db, dek, "4821", password=SECRET)
    pid = password_id(db)
    r = post(client, f"/settings/passwords/{pid}/replace", password=" New-One ")
    assert r.status_code == 204 and r.headers["HX-Redirect"] == "/settings"
    row = stored(db, pid)
    new = decrypt_field(dek, row["ciphertext"], row["nonce"], field=FIELD_STATEMENT_PASSWORD)
    assert new == " New-One "


def test_replace_empty_shows_error(client, env):
    db, dek = env
    add_card(db, dek, "4821", password=SECRET)
    pid = password_id(db)
    before = stored(db, pid)["ciphertext"]
    r = post(client, f"/settings/passwords/{pid}/replace", password="   ")
    assert r.status_code == 200 and 'role="alert"' in r.text
    assert stored(db, pid)["ciphertext"] == before


def test_unknown_password_id_redirects(client, env):
    path = "/settings/passwords/999/replace"
    r = client.get(path, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/settings"
    r = client.post(
        path,
        data={"csrf_token": client.cookies[CSRF_COOKIE], "password": "x"},
        follow_redirects=False,
    )
    assert r.status_code == 303 and r.headers["location"] == "/settings"


def test_post_without_csrf_is_403(client, env):
    db, dek = env
    add_card(db, dek, "4821", password=SECRET)
    pid = password_id(db)
    before = stored(db, pid)["ciphertext"]
    r = client.post(f"/settings/passwords/{pid}/replace", data={"password": "x"})
    assert r.status_code == 403
    assert stored(db, pid)["ciphertext"] == before
