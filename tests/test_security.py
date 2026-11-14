"""End-to-end security promises: files deleted, nothing leaked, users isolated, real wipes."""

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ferret import control, worker
from ferret.userdb import UserDbKeyError, open_user_db
from tests.conftest import csrf_token, link_token

A, B = "a@example.com", "b@example.com"


def sign_in(client, mailer, email):
    client.post(
        "/signin/email", data={"email": email}, headers={"x-csrf-token": csrf_token(client)}
    )
    client.get(f"/signin/link?token={link_token(mailer)}")


def upload(client, path: Path):
    return client.post(
        "/statements/upload",
        files={"file": (path.name, path.read_bytes(), "application/pdf")},
        headers={"x-csrf-token": csrf_token(client)},
    )


def drain(client, clock):
    settings = client.app.state.settings
    ctx = worker.WorkerContext(
        control=control.connect(settings.control_db_path),
        kek=client.app.state.kek,
        users_dir=settings.users_dir,
        pending_dir=settings.pending_dir,
        clock=clock,
    )
    while worker.run_once(ctx):
        pass
    ctx.control.close()


def pending_files(data_dir):
    return [p for p in (data_dir / "pending").rglob("*") if p.is_file()]


def user_of(client, email):
    conn = control.connect(client.app.state.settings.control_db_path)
    try:
        return control.get_user_by_email(conn, email)["id"]
    finally:
        conn.close()


def statement_id(client, user_id):
    settings = client.app.state.settings
    conn = control.connect(settings.control_db_path)
    db = open_user_db(
        settings.users_dir, user_id, control.load_dek(conn, client.app.state.kek, user_id)
    )
    try:
        return db.execute("SELECT id FROM statements").fetchone()[0]
    finally:
        db.close()
        conn.close()


def statement_status(client, user_id):
    settings = client.app.state.settings
    conn = control.connect(settings.control_db_path)
    db = open_user_db(
        settings.users_dir, user_id, control.load_dek(conn, client.app.state.kek, user_id)
    )
    try:
        return db.execute("SELECT status FROM statements").fetchone()[0]
    finally:
        db.close()
        conn.close()


def merchants(fixture):
    return {t.merchant for t in fixture.expected.transactions}


@pytest.fixture
def second_client(app):
    with TestClient(app, base_url="https://testserver", follow_redirects=False) as c:
        yield c


@pytest.mark.parametrize("kind", ["sep_2026", "unbalanced", "not_a_statement", "unsupported_bank"])
def test_files_deleted_after_every_outcome(client, mailer, clock, data_dir, statements, kind):
    sign_in(client, mailer, A)
    assert upload(client, statements[kind].path).status_code == 200
    assert len(pending_files(data_dir)) == 1
    drain(client, clock)
    assert pending_files(data_dir) == []


def test_locked_file_expires(client, mailer, clock, data_dir, statements):
    sign_in(client, mailer, A)
    upload(client, statements["locked"].path)
    drain(client, clock)
    assert len(pending_files(data_dir)) == 1
    clock.advance(8 * 86400)
    drain(client, clock)
    assert pending_files(data_dir) == []


def test_logs_carry_no_secrets_or_statement_text(client, mailer, clock, statements, caplog):
    caplog.set_level(logging.DEBUG)
    locked = statements["locked"]
    sign_in(client, mailer, A)
    upload(client, locked.path)
    drain(client, clock)
    sid = statement_id(client, user_of(client, A))
    client.post(
        f"/statements/{sid}/password",
        data={"password": locked.password},
        headers={"x-csrf-token": csrf_token(client)},
    )
    drain(client, clock)
    assert statement_status(client, user_of(client, A)) == "reconciled"
    assert merchants(locked)
    for secret in (locked.password, A, *merchants(locked)):
        assert secret not in caplog.text


def test_cross_user_isolation(client, second_client, mailer, clock, statements):
    sign_in(client, mailer, A)
    upload(client, statements["sep_2026"].path)
    drain(client, clock)
    sid = statement_id(client, user_of(client, A))
    sign_in(second_client, mailer, B)
    for path in ("/", "/statements"):
        page = second_client.get(path)
        for merchant in merchants(statements["sep_2026"]):
            assert merchant not in page.text
    assert sid == 1  # B has no statements, so B's database has no row for A's id
    assert (
        second_client.get(f"/statements/{sid}/password").status_code == 303
    )  # no such statement for B


def test_user_db_needs_its_own_key(client, second_client, mailer, kek, data_dir):
    sign_in(client, mailer, A)
    sign_in(second_client, mailer, B)
    settings = client.app.state.settings
    conn = control.connect(settings.control_db_path)
    b_dek = control.load_dek(conn, client.app.state.kek, user_of(client, B))
    conn.close()
    with pytest.raises(UserDbKeyError):
        open_user_db(settings.users_dir, user_of(client, A), b_dek)


def test_account_wipe(client, second_client, mailer, clock, data_dir, statements):
    sign_in(client, mailer, A)
    sign_in(second_client, mailer, B)
    for c in (client, second_client):
        upload(c, statements["sep_2026"].path)
    drain(client, clock)
    a_id = user_of(client, A)
    response = client.post(
        "/settings/account/delete",
        data={"confirm": "DELETE"},
        headers={"x-csrf-token": csrf_token(client)},
    )
    assert response.status_code == 303
    drain(client, clock)
    for path in [*(data_dir / "users").rglob("*"), *(data_dir / "pending").rglob("*")]:
        assert a_id not in str(path.relative_to(data_dir))
    conn = control.connect(data_dir / "control.db")
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    for table in tables:
        for row in conn.execute(f"SELECT * FROM {table}"):
            text = " ".join(str(v) for v in row)
            assert a_id not in text and A not in text
    conn.close()
    b_page = second_client.get("/statements")
    assert b_page.status_code == 200
    assert "Reconciled" in b_page.text
