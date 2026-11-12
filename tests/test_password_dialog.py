import logging
import re
from pathlib import Path

import pytest

from ferret import control, jobs
from ferret.auth.sessions import create_session
from ferret.keys import FIELD_STATEMENT_PASSWORD, decrypt_field
from ferret.pending import pending_path
from ferret.pipeline import run_statement, submit_statement
from ferret.userdb import open_user_db
from ferret.web.security import CSRF_COOKIE, SESSION_COOKIE
from tests.fixtures.make_statements import LOCKED_PASSWORD

HX = {"HX-Request": "true"}
WRONG = "Wr0ng-Secret"


@pytest.fixture
def env(client, app, conn, clock, statements):
    user_id, dek = control.create_user(conn, app.state.kek, "p@example.com", now=clock())
    client.cookies.set(SESSION_COOKIE, create_session(conn, user_id, now=clock()))
    db = open_user_db(app.state.settings.users_dir, user_id, dek)
    pending_dir = app.state.settings.pending_dir
    sid = submit_statement(
        conn,
        db,
        dek,
        pending_dir,
        user_id,
        statements["locked"].path.read_bytes(),
        source="upload",
        source_ref=None,
        now=clock(),
    )
    run_statement(db, dek, pending_dir, user_id, sid, now=clock())
    jobs.finish(conn, jobs.claim_next(conn, now=clock()).id)
    client.get("/signin")
    yield sid, db, dek, pending_dir, user_id
    db.close()


def post(client, path, **data):
    return client.post(path, data={"csrf_token": client.cookies[CSRF_COOKIE], **data}, headers=HX)


def status(db, sid):
    return db.execute("SELECT status FROM statements WHERE id = ?", (sid,)).fetchone()["status"]


def test_dialog_fragment(client, env):
    sid = env[0]
    html = client.get(f"/statements/{sid}/password", headers=HX).text
    for part in (
        '<dialog class="password-dialog"',
        "This statement is locked",
        'type="password"',
        'aria-describedby="pw-hint"',
        "Skip this statement",
        "Open and save",
        'href="/settings"',
    ):
        assert part in html


def test_plain_get_renders_page_with_dialog(client, env):
    html = client.get(f"/statements/{env[0]}/password").text
    assert 'id="dialog-root"' in html and '<dialog class="password-dialog"' in html
    assert "History" in html


def test_wrong_password_alert(client, env):
    sid, db, _, pending_dir, user_id = env
    response = post(client, f"/statements/{sid}/password", password=WRONG)
    html = response.text.replace("&#39;", "'")
    assert response.status_code == 200
    for part in (
        'role="alert"',
        'id="pw-error"',
        'aria-describedby="pw-error pw-hint"',
        'aria-invalid="true"',
        "That password didn't work",
        "Try again",
    ):
        assert part in html
    assert pending_path(pending_dir, user_id, sid).exists()
    assert status(db, sid) == "needs_password"


def test_wrong_password_after_saved_one_says_bank_changed_it(client, env):
    sid, db, dek, *_ = env
    db.execute(
        "INSERT INTO statement_passwords (bank, ciphertext, nonce, created_at)"
        " VALUES ('X', x'00', x'00', 1)"
    )
    db.commit()
    html = post(client, f"/statements/{sid}/password", password=WRONG).text
    assert "Banks sometimes change it" in html


def test_correct_password_redirects_and_stores_encrypted(client, env):
    sid, db, dek, *_ = env
    response = post(client, f"/statements/{sid}/password", password=LOCKED_PASSWORD)
    assert response.status_code == 204
    assert response.headers["HX-Redirect"] == "/statements"
    assert status(db, sid) == "reading"
    saved = db.execute("SELECT ciphertext, nonce FROM statement_passwords").fetchone()
    assert LOCKED_PASSWORD.encode() not in saved["ciphertext"]
    got = decrypt_field(dek, saved["ciphertext"], saved["nonce"], field=FIELD_STATEMENT_PASSWORD)
    assert got == LOCKED_PASSWORD


def test_skip_route(client, env):
    sid, db, _, pending_dir, user_id = env
    response = client.post(
        f"/statements/{sid}/skip", data={"csrf_token": client.cookies[CSRF_COOKIE]}
    )
    assert response.status_code == 303 and response.headers["location"] == "/statements"
    assert not pending_path(pending_dir, user_id, sid).exists()
    assert status(db, sid) == "skipped"


def test_esc_close_changes_nothing(client, env):
    sid, db, _, pending_dir, user_id = env
    client.get(f"/statements/{sid}/password", headers=HX)
    html = client.get(f"/statements/{sid}/password", headers=HX).text
    assert pending_path(pending_dir, user_id, sid).exists()
    assert status(db, sid) == "needs_password"
    assert jobs.claim_next(control.connect(Path(pending_dir).parent / "control.db"), now=1) is None
    assert sorted(re.findall(r'hx-post="([^"]+)"', html)) == [
        f"/statements/{sid}/password",
        f"/statements/{sid}/skip",
    ]
    assert "hx-trigger" not in html
    js = (Path(__file__).parent.parent / "ferret/web/static/js/statements.js").read_text()
    assert "fetch(" not in js and "htmx.ajax" not in js


def test_password_never_logged_or_queued(client, env, caplog, data_dir):
    sid = env[0]
    caplog.set_level(logging.DEBUG)
    bodies = [
        post(client, f"/statements/{sid}/password", password=WRONG).text,
        post(client, f"/statements/{sid}/password", password=LOCKED_PASSWORD).text,
    ]
    payloads = (
        control.connect(data_dir / "control.db").execute("SELECT payload_json FROM jobs").fetchall()
    )
    for secret in (WRONG, LOCKED_PASSWORD):
        assert secret not in caplog.text
        assert all(secret not in b for b in bodies)
        assert all(secret not in p[0] for p in payloads)


def test_csrf_required(client, env):
    assert client.post(f"/statements/{env[0]}/password", data={"password": "x"}).status_code == 403


def test_not_waiting_redirects(client, env):
    sid, db, *_ = env
    db.execute("UPDATE statements SET status = 'reconciled'")
    db.commit()
    response = client.get(f"/statements/{sid}/password")
    assert response.status_code == 303 and response.headers["location"] == "/statements"
