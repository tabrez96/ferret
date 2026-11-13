import logging

from ferret import jobs, worker
from ferret.gmail.client import GmailError
from ferret.gmail.poll import (
    FIRST_LOOKBACK_SECONDS,
    OVERLAP_SECONDS,
    POLL_INTERVAL_SECONDS,
    poll_gmail,
)
from ferret.keys import FIELD_STATEMENT_PASSWORD, encrypt_field
from ferret.pending import pending_deadline, pending_path
from tests.fixtures.fake_gmail import FakeGmail, connect_gmail
from tests.fixtures.fake_parser import FakeParser, statement
from tests.fixtures.pdfs import make_pdf

TOKEN = "1//refresh-" + "x" * 40


def make_ctx(conn, kek, user, clock, fake):
    return worker.WorkerContext(
        control=conn,
        kek=kek,
        users_dir=user.users_dir,
        pending_dir=user.pending_dir,
        clock=clock,
        parsers=[FakeParser(statement())],
        gmail_factory=lambda token: fake,
    )


def save_password(user, clock, password="pw-1"):
    ciphertext, nonce = encrypt_field(user.dek, password, field=FIELD_STATEMENT_PASSWORD)
    with user.db:
        user.db.execute(
            "INSERT INTO statement_passwords (bank, ciphertext, nonce, created_at)"
            " VALUES ('Fake Bank', ?, ?, ?)",
            (ciphertext, nonce, clock()),
        )


def run_poll(conn, ctx, user, clock):
    jobs.enqueue(conn, "gmail_poll", user_id=user.user_id, now=clock())
    while worker.run_once(ctx):
        pass


def setup(conn, kek, user, clock, *, attachments=None, **account):
    fake = FakeGmail()
    fake.messages["msg-1"] = [make_pdf(["FAKE BANK STATEMENT"], password="pw-1")]
    if attachments is not None:
        fake.messages["msg-1"] = attachments
    connect_gmail(user.db, user.dek, TOKEN, now=clock(), **account)
    return fake, make_ctx(conn, kek, user, clock, fake)


def gmail_polls(conn, status):
    rows = conn.execute(
        "SELECT run_after FROM jobs WHERE kind = 'gmail_poll' AND status = ?", (status,)
    ).fetchall()
    return [r["run_after"] for r in rows]


def test_saved_password_parses_gmail_statement_without_prompt(conn, kek, user, clock):
    fake, ctx = setup(conn, kek, user, clock)
    save_password(user, clock)
    run_poll(conn, ctx, user, clock)
    rows = user.db.execute("SELECT status, source, source_ref FROM statements").fetchall()
    assert [tuple(r) for r in rows] == [("reconciled", "gmail", "msg-1")]
    assert not list((user.pending_dir / user.user_id).glob("*"))


def test_same_message_never_fetched_twice(conn, kek, user, clock):
    fake, ctx = setup(conn, kek, user, clock)
    save_password(user, clock)
    run_poll(conn, ctx, user, clock)
    clock.advance(POLL_INTERVAL_SECONDS)
    while worker.run_once(ctx):
        pass
    assert len(fake.queries) == 2
    assert fake.fetched == ["msg-1"]
    assert user.db.execute("SELECT COUNT(*) FROM statements").fetchone()[0] == 1
    assert user.db.execute("SELECT message_id FROM gmail_seen").fetchall()[0][0] == "msg-1"


def test_message_without_pdf_marked_seen(conn, kek, user, clock):
    fake, ctx = setup(conn, kek, user, clock, attachments=[])
    run_poll(conn, ctx, user, clock)
    clock.advance(POLL_INTERVAL_SECONDS)
    while worker.run_once(ctx):
        pass
    assert user.db.execute("SELECT message_id FROM gmail_seen").fetchall()[0][0] == "msg-1"
    assert user.db.execute("SELECT COUNT(*) FROM statements").fetchone()[0] == 0
    assert fake.fetched == ["msg-1"]


def test_message_with_two_pdfs_submits_two_statements(conn, kek, user, clock):
    pdf = make_pdf(["FAKE BANK STATEMENT"])
    fake, ctx = setup(conn, kek, user, clock, attachments=[pdf, pdf])
    submitted = poll_gmail(
        conn,
        user.db,
        user.dek,
        user.pending_dir,
        user.user_id,
        gmail_factory=ctx.gmail_factory,
        now=clock(),
        parsers=ctx.parsers,
    )
    assert submitted == 2
    refs = user.db.execute("SELECT source_ref FROM statements").fetchall()
    assert [r[0] for r in refs] == ["msg-1", "msg-1"]


def test_failing_saved_password_needs_password_with_7_day_deadline(conn, kek, user, clock):
    fake, ctx = setup(conn, kek, user, clock)
    save_password(user, clock, "wrong")
    received = clock.now
    run_poll(conn, ctx, user, clock)
    row = user.db.execute("SELECT id, status, received_at FROM statements").fetchone()
    assert row["status"] == "needs_password"
    assert row["received_at"] == received
    assert pending_deadline(row["received_at"]) == received + 7 * 24 * 3600
    assert pending_path(user.pending_dir, user.user_id, row["id"]).exists()


def test_revoked_token_sets_stopped_and_stops_polling(conn, kek, user, clock):
    fake, ctx = setup(conn, kek, user, clock, last_checked_at=clock.now - 100)
    fake.revoked = True
    run_poll(conn, ctx, user, clock)
    row = user.db.execute("SELECT status, last_checked_at FROM gmail_account").fetchone()
    assert row["status"] == "stopped"
    assert row["last_checked_at"] == clock.now - 100
    assert gmail_polls(conn, "done") == [clock.now]
    assert gmail_polls(conn, "queued") == []


def test_poll_reschedules_once_in_6_hours(conn, kek, user, clock):
    fake, ctx = setup(conn, kek, user, clock)
    run_poll(conn, ctx, user, clock)
    assert gmail_polls(conn, "queued") == [clock.now + POLL_INTERVAL_SECONDS]
    run_poll(conn, ctx, user, clock)
    assert gmail_polls(conn, "queued") == [clock.now + POLL_INTERVAL_SECONDS]


def test_failed_poll_still_reschedules(conn, kek, user, clock):
    fake, ctx = setup(conn, kek, user, clock, last_checked_at=clock.now - 100)
    fake.error = GmailError("down")
    run_poll(conn, ctx, user, clock)
    assert len(gmail_polls(conn, "failed")) == 1
    assert gmail_polls(conn, "queued") == [clock.now + POLL_INTERVAL_SECONDS]
    last = user.db.execute("SELECT last_checked_at FROM gmail_account").fetchone()[0]
    assert last == clock.now - 100


def test_search_query_uses_since(conn, kek, user, clock):
    checked = clock.now - 5000
    fake, ctx = setup(conn, kek, user, clock, last_checked_at=checked, attachments=[])
    run_poll(conn, ctx, user, clock)
    assert fake.queries == [f"from:statements@fakebank.test after:{checked - OVERLAP_SECONDS}"]


def test_first_search_looks_back_from_connection(conn, kek, user, clock):
    fake, ctx = setup(conn, kek, user, clock, attachments=[])
    run_poll(conn, ctx, user, clock)
    since = clock.now - FIRST_LOOKBACK_SECONDS
    assert fake.queries == [f"from:statements@fakebank.test after:{since}"]


def test_same_query_runs_once(conn, kek, user, clock):
    fake, ctx = setup(conn, kek, user, clock, attachments=[])
    ctx.parsers = [FakeParser(statement()), FakeParser(statement())]
    run_poll(conn, ctx, user, clock)
    assert len(fake.queries) == 1


def test_stopped_account_not_polled(conn, kek, user, clock):
    fake, ctx = setup(conn, kek, user, clock, status="stopped")
    ctx.gmail_factory = lambda token: (_ for _ in ()).throw(AssertionError("called"))
    run_poll(conn, ctx, user, clock)
    assert gmail_polls(conn, "queued") == []
    assert gmail_polls(conn, "done") == [clock.now]


def test_no_account_not_polled(conn, kek, user, clock):
    ctx = make_ctx(conn, kek, user, clock, FakeGmail())
    run_poll(conn, ctx, user, clock)
    assert gmail_polls(conn, "queued") == []


def test_unconfigured_google_skips_poll(conn, kek, user, clock, caplog):
    fake, ctx = setup(conn, kek, user, clock)
    ctx.gmail_factory = None
    run_poll(conn, ctx, user, clock)
    assert gmail_polls(conn, "done") == [clock.now]
    assert gmail_polls(conn, "queued") == []
    assert "not configured" in caplog.text


def test_refresh_token_never_logged(conn, kek, user, clock, caplog):
    caplog.set_level(logging.DEBUG)
    fake, ctx = setup(conn, kek, user, clock, attachments=[])
    run_poll(conn, ctx, user, clock)
    fake.revoked = True
    clock.advance(POLL_INTERVAL_SECONDS)
    while worker.run_once(ctx):
        pass
    user.db.execute("UPDATE gmail_account SET status = 'connected'")
    user.db.commit()
    fake.revoked = False
    fake.error = GmailError("down")
    clock.advance(POLL_INTERVAL_SECONDS)
    jobs.enqueue(conn, "gmail_poll", user_id=user.user_id, now=clock())
    while worker.run_once(ctx):
        pass
    assert "failed" in caplog.text
    assert TOKEN not in caplog.text
    ciphertext = user.db.execute("SELECT refresh_token_ciphertext FROM gmail_account").fetchone()[0]
    assert TOKEN.encode() not in ciphertext
    db_file = user.users_dir / f"{user.user_id}.db"
    assert TOKEN.encode() not in db_file.read_bytes()
