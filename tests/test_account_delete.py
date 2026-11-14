import pytest

from ferret import control, jobs, ratelimit, worker
from ferret.auth import links
from ferret.auth.sessions import create_session, get_session_user
from ferret.auth.tokens import hash_token
from ferret.pending import write_pending
from ferret.pipeline.locked import save_password
from ferret.userdb import open_user_db
from ferret.web.security import CSRF_COOKIE, SESSION_COOKIE

HX = {"HX-Request": "true"}
DELETED = "Your account and all its data were deleted."


class Account:
    def __init__(self, app, conn, clock, email):
        self.app, self.conn, self.email = app, conn, email
        self.id, self.dek = control.create_user(conn, app.state.kek, email, now=clock())
        self.token = create_session(conn, self.id, now=clock())
        settings = app.state.settings
        db = open_user_db(settings.users_dir, self.id, self.dek)
        with db:
            card = db.execute(
                "INSERT INTO cards (bank, last4, currency) VALUES ('Emirates NBD', '4821', 'AED')"
            ).lastrowid
            stmt = db.execute(
                "INSERT INTO statements (card_id, source, received_at, status)"
                " VALUES (?, 'upload', 1, 'reading')",
                (card,),
            ).lastrowid
            for merchant in ("Cafe", "Bakery"):
                db.execute(
                    "INSERT INTO transactions (statement_id, card_id, posted_on, merchant,"
                    " amount_minor, currency, is_credit)"
                    " VALUES (?, ?, '2026-01-01', ?, 500, 'AED', 0)",
                    (stmt, card, merchant),
                )
        save_password(db, self.dek, bank="Emirates NBD", card_id=card, password="pw", now=1)
        db.close()
        write_pending(settings.pending_dir, self.id, stmt, self.dek, b"%PDF fake")
        ratelimit.allow(conn, f"upload:{self.id}", now=clock(), limit=5, window=60)
        with conn:
            conn.execute(
                "INSERT INTO mcp_tokens (user_id, token_hash, created_at) VALUES (?, ?, 1)",
                (self.id, hash_token("mcp-" + self.id)),
            )
        links.issue_link(conn, email, now=clock())
        jobs.enqueue(conn, "gmail_poll", user_id=self.id, now=clock(), run_after=clock() + 999)

    def files(self):
        settings = self.app.state.settings
        return [p for p in settings.users_dir.iterdir() if p.name.startswith(self.id)] + [
            p for p in settings.pending_dir.iterdir() if p.name == self.id
        ]


@pytest.fixture
def make(client, app, conn, clock):
    return lambda email: Account(app, conn, clock, email)


@pytest.fixture
def acct(make, client):
    account = make("del@example.com")
    client.cookies.set(SESSION_COOKIE, account.token)
    client.get("/signin")
    return account


@pytest.fixture
def ctx(client, app, conn, clock):
    settings = app.state.settings
    return worker.WorkerContext(
        control=conn,
        kek=app.state.kek,
        users_dir=settings.users_dir,
        pending_dir=settings.pending_dir,
        clock=clock,
    )


def confirm(client, word="DELETE", headers=HX):
    return client.post(
        "/settings/account/delete",
        data={"csrf_token": client.cookies[CSRF_COOKIE], "confirm": word},
        headers=headers,
    )


def delete_jobs(conn):
    return conn.execute("SELECT * FROM jobs WHERE kind = 'delete_account'").fetchall()


def test_delete_dialog_shows_counts(client, acct):
    text = client.get("/settings/account/delete", headers=HX).text
    for part in (
        "Delete your Ferret account?",
        "1 statement and 2 transactions",
        "1 saved statement password",
        "Type DELETE to confirm",
        "Delete everything",
        "Keep my account",
    ):
        assert part in text
    full = client.get("/settings/account/delete").text
    assert "<h1" in full and " open>" in full


def test_settings_delete_button_enabled(client, acct):
    text = client.get("/settings").text
    assert 'href="/settings/account/delete"' in text
    assert "disabled" not in text


def test_wrong_confirm_word_keeps_account(client, conn, acct):
    r = confirm(client, "delete")
    assert r.status_code == 200 and "Type DELETE to confirm." in r.text
    assert delete_jobs(conn) == []
    assert client.get("/settings").status_code == 200


def test_delete_requires_csrf(client, conn, acct):
    r = client.post("/settings/account/delete", data={"confirm": "DELETE"})
    assert r.status_code == 403
    assert delete_jobs(conn) == []


def test_old_session_rejected_before_worker(client, conn, acct):
    r = confirm(client)
    assert r.status_code == 204 and r.headers["HX-Redirect"] == "/signin?deleted=1"
    client.cookies.set(SESSION_COOKIE, acct.token)
    r = client.get("/settings")
    assert r.status_code == 303 and r.headers["location"].startswith("/signin")
    for table in ("sessions", "mcp_tokens"):
        assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    assert len(delete_jobs(conn)) == 1


def test_delete_without_htmx_redirects(client, conn, acct):
    r = confirm(client, headers={})
    assert r.status_code == 303 and r.headers["location"] == "/signin?deleted=1"
    assert len(delete_jobs(conn)) == 1


def test_signin_shows_deleted_notice(client):
    assert DELETED in client.get("/signin?deleted=1").text
    assert DELETED not in client.get("/signin").text


def test_worker_removes_every_trace(client, app, conn, ctx, acct):
    assert acct.files()
    confirm(client)
    assert worker.run_once(ctx)
    assert acct.files() == []
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall():
        for row in conn.execute(f"SELECT * FROM {name}").fetchall():
            text = str(tuple(row))
            assert acct.id not in text and acct.email not in text


def test_other_user_untouched(client, conn, ctx, make, acct):
    other = make("keep@example.com")
    before = other.files()
    confirm(client)
    while worker.run_once(ctx):
        pass
    assert other.files() == before and len(before) == 2
    mine = "WHERE user_id = ?"
    assert conn.execute(f"SELECT count(*) FROM sessions {mine}", (other.id,)).fetchone()[0] == 1
    assert conn.execute(f"SELECT count(*) FROM mcp_tokens {mine}", (other.id,)).fetchone()[0] == 1
    assert conn.execute(f"SELECT count(*) FROM jobs {mine}", (other.id,)).fetchone()[0] == 1
    bucket = f"upload:{other.id}"
    assert (
        conn.execute("SELECT count(*) FROM rate_events WHERE bucket = ?", (bucket,)).fetchone()[0]
        == 1
    )
    assert (
        conn.execute("SELECT count(*) FROM login_links WHERE email = ?", (other.email,)).fetchone()[
            0
        ]
        == 1
    )
    client.cookies.set(SESSION_COOKIE, other.token)
    assert client.get("/settings").status_code == 200


def test_delete_job_twice(conn, ctx, clock, acct):
    job = jobs.Job(id=1, user_id=acct.id, kind="delete_account", payload={}, attempts=1)
    worker._delete_account(ctx, job, clock())
    worker._delete_account(ctx, job, clock())
    jobs.enqueue(conn, "delete_account", user_id=acct.id, now=clock())
    assert worker.run_once(ctx)
    assert conn.execute("SELECT count(*) FROM jobs WHERE status = 'failed'").fetchone()[0] == 0
    assert delete_jobs(conn) == []


def test_malformed_user_id_fails_job(conn, ctx, clock):
    jobs.enqueue(conn, "delete_account", user_id="../x", now=clock())
    assert worker.run_once(ctx)
    assert (
        conn.execute("SELECT status FROM jobs WHERE kind = 'delete_account'").fetchone()[0]
        == "failed"
    )


def test_resignin_blocked_while_delete_queued(client, conn, clock, acct):
    confirm(client)
    token = create_session(conn, acct.id, now=clock())
    assert get_session_user(conn, token, now=clock()) is None


def test_delete_user_missing_user(conn):
    control.delete_user(conn, "0" * 32)
