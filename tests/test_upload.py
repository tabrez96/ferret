import json

import pytest

from ferret import control, worker
from ferret.auth.sessions import create_session
from ferret.pending import read_pending
from ferret.userdb import open_user_db
from ferret.web.security import CSRF_COOKIE, SESSION_COOKIE
from ferret.web.upload import MAX_BODY_BYTES, MAX_UPLOAD_BYTES, UPLOAD_LIMIT, UPLOAD_WINDOW_SECONDS
from tests.fixtures.fake_parser import FakeParser, statement
from tests.fixtures.pdfs import make_pdf


@pytest.fixture
def signed_in(client, app, conn, clock):
    user_id, dek = control.create_user(conn, app.state.kek, "p@example.com", now=clock())
    client.cookies.set(SESSION_COOKIE, create_session(conn, user_id, now=clock()))
    db = open_user_db(app.state.settings.users_dir, user_id, dek)
    client.get("/statements")
    yield user_id, dek, db
    db.close()


def post(client, *files, csrf=True):
    headers = {"x-csrf-token": client.cookies[CSRF_COOKIE]} if csrf else {}
    return client.post(
        "/statements/upload",
        files=[("file", (name, data, "application/pdf")) for name, data in files],
        headers=headers,
    )


def pending_files(app):
    return list(app.state.settings.pending_dir.rglob("*.enc"))


def counts(db, conn):
    return (
        db.execute("SELECT count(*) FROM statements").fetchone()[0],
        conn.execute("SELECT count(*) FROM jobs").fetchone()[0],
        conn.execute("SELECT count(*) FROM rate_events").fetchone()[0],
    )


PDF = make_pdf(["hello"])


def test_upload_pdf_creates_row_file_and_job(client, app, conn, signed_in):
    user_id, dek, db = signed_in
    response = post(client, ("a.pdf", PDF))
    assert response.status_code == 200
    assert "Reading" in response.text
    row = db.execute("SELECT id, source, status FROM statements").fetchone()
    assert (row["source"], row["status"]) == ("upload", "reading")
    path = app.state.settings.pending_dir / user_id / f"{row['id']}.pdf.enc"
    assert path.exists()
    assert path.read_bytes() != PDF
    assert read_pending(app.state.settings.pending_dir, user_id, row["id"], dek) == PDF
    jobs = conn.execute("SELECT kind, payload_json FROM jobs WHERE status = 'queued'").fetchall()
    assert len(jobs) == 1
    assert jobs[0][0] == "parse_statement"
    assert json.loads(jobs[0][1]) == {"statement_id": row["id"]}


def test_worker_reads_upload_and_deletes_file(client, app, conn, clock, signed_in):
    _, _, db = signed_in
    settings = app.state.settings
    post(client, ("a.pdf", make_pdf(["FAKE BANK STATEMENT"])))
    ctx = worker.WorkerContext(
        control=conn,
        kek=app.state.kek,
        users_dir=settings.users_dir,
        pending_dir=settings.pending_dir,
        clock=clock,
        parsers=[FakeParser(statement())],
    )
    while worker.run_once(ctx):
        pass
    assert db.execute("SELECT status FROM statements").fetchone()[0] == "reconciled"
    assert pending_files(app) == []
    assert conn.execute("SELECT status FROM jobs").fetchone()[0] == "done"


def test_non_pdf_rejected(client, app, conn, signed_in):
    response = post(client, ("notes.txt", b"hello"))
    assert response.status_code == 400
    assert "This doesn't look like a credit card statement." in response.text.replace("&#39;", "'")
    assert "notes.txt" in response.text
    assert counts(signed_in[2], conn) == (0, 0, 0)
    assert pending_files(app) == []


def test_oversized_rejected(client, app, conn, signed_in):
    response = post(client, ("big.pdf", b"%PDF-" + b"0" * MAX_UPLOAD_BYTES))
    assert response.status_code == 400
    assert "That file is too big." in response.text
    assert counts(signed_in[2], conn) == (0, 0, 0)
    assert pending_files(app) == []


def test_exact_limit_size_accepted(client, signed_in):
    response = post(client, ("max.pdf", b"%PDF-" + b"0" * (MAX_UPLOAD_BYTES - 5)))
    assert response.status_code == 200
    assert signed_in[2].execute("SELECT count(*) FROM statements").fetchone()[0] == 1


def test_mixed_batch(client, signed_in):
    response = post(client, ("a.pdf", PDF), ("b.txt", b"nope"))
    assert response.status_code == 200
    assert response.text.count('role="alert"') == 1
    assert signed_in[2].execute("SELECT count(*) FROM statements").fetchone()[0] == 1


def test_rate_limit_and_window(client, app, conn, clock, signed_in):
    db = signed_in[2]
    for _ in range(UPLOAD_LIMIT):
        assert post(client, ("a.pdf", PDF)).status_code == 200
    response = post(client, ("a.pdf", PDF))
    assert response.status_code == 429
    assert "That's a lot of statements in one hour." in response.text.replace("&#39;", "'")
    assert "Nothing from this upload was saved" not in response.text
    assert counts(db, conn) == (30, 30, 30)
    assert len(pending_files(app)) == 30
    clock.advance(UPLOAD_WINDOW_SECONDS)
    assert post(client, ("a.pdf", PDF)).status_code == 200
    assert counts(db, conn)[0] == 31


def test_batch_crossing_limit_keeps_first(client, conn, signed_in):
    for _ in range(UPLOAD_LIMIT - 1):
        post(client, ("a.pdf", PDF))
    response = post(client, ("a.pdf", PDF), ("b.pdf", PDF), ("c.pdf", PDF))
    assert response.status_code == 429
    assert counts(signed_in[2], conn)[0] == 30


def test_requires_csrf(client, app, conn, signed_in):
    assert post(client, ("a.pdf", PDF), csrf=False).status_code == 403
    assert counts(signed_in[2], conn) == (0, 0, 0)
    assert pending_files(app) == []


def test_signed_out_redirects(client):
    client.get("/signin")
    response = post(client, ("a.pdf", PDF))
    assert response.status_code == 303
    assert response.headers["location"] == "/signin"


def test_filename_escaped(client, signed_in):
    response = post(client, ("<b>x</b>.pdf", b"nope"))
    assert "&lt;b&gt;" in response.text
    assert "<b>x</b>" not in response.text


def test_oversized_body_refused_before_parsing(client, app, conn, signed_in):
    big = b"%PDF-" + b"0" * (MAX_BODY_BYTES + 1)
    assert post(client, ("big.pdf", big)).status_code == 413
    assert counts(signed_in[2], conn) == (0, 0, 0)
    assert pending_files(app) == []
