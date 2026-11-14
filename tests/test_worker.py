from ferret import jobs, worker
from ferret.pipeline import submit_statement
from tests.fixtures.fake_parser import FakeParser, statement
from tests.fixtures.pdfs import make_pdf


def make_ctx(conn, kek, user, clock, parsers=()):
    return worker.WorkerContext(
        control=conn,
        kek=kek,
        users_dir=user.users_dir,
        pending_dir=user.pending_dir,
        clock=clock,
        parsers=parsers,
    )


def submit(conn, user, clock):
    return submit_statement(
        conn,
        user.db,
        user.dek,
        user.pending_dir,
        user.user_id,
        make_pdf(["FAKE BANK STATEMENT"]),
        source="upload",
        source_ref=None,
        now=clock(),
    )


def job_statuses(conn, kind):
    rows = conn.execute("SELECT status FROM jobs WHERE kind = ? ORDER BY id", (kind,)).fetchall()
    return [r["status"] for r in rows]


def test_run_once_parse_statement(conn, kek, user, clock):
    sid = submit(conn, user, clock)
    ctx = make_ctx(conn, kek, user, clock, [FakeParser(statement())])
    while worker.run_once(ctx):
        pass
    assert job_statuses(conn, "parse_statement") == ["done"]
    status = user.db.execute("SELECT status FROM statements WHERE id = ?", (sid,)).fetchone()[0]
    assert status == "reconciled"


def test_run_once_failure_marks_failed_and_continues(conn, kek, user, clock):
    submit(conn, user, clock)
    ctx = make_ctx(conn, kek, user, clock, [FakeParser(RuntimeError("boom"))])
    assert worker.run_once(ctx) is True  # sweep job is claimed first (same run_after, lower id)
    assert worker.run_once(ctx) is True
    assert job_statuses(conn, "parse_statement") == ["failed"]


def test_sweep_reschedules_hourly(conn, kek, user, clock):
    ctx = make_ctx(conn, kek, user, clock)
    assert worker.run_once(ctx) is True
    assert job_statuses(conn, "sweep_pending") == ["done", "queued"]
    row = conn.execute(
        "SELECT run_after FROM jobs WHERE kind = 'sweep_pending' AND status = 'queued'"
    ).fetchone()
    assert row["run_after"] == clock.now + worker.SWEEP_INTERVAL_SECONDS
    assert worker.run_once(ctx) is False


def test_failed_sweep_still_schedules_next_hour(conn, kek, user, clock, monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("disk")

    monkeypatch.setattr(worker, "sweep_pending", boom)
    ctx = make_ctx(conn, kek, user, clock)
    assert worker.run_once(ctx) is True
    assert job_statuses(conn, "sweep_pending") == ["failed", "queued"]
    row = conn.execute(
        "SELECT run_after FROM jobs WHERE kind = 'sweep_pending' AND status = 'queued'"
    ).fetchone()
    assert row["run_after"] == clock.now + worker.SWEEP_INTERVAL_SECONDS
    assert worker.run_once(ctx) is False


def test_delete_account_job_leaves_no_row(conn, kek, user, clock):
    jobs.enqueue(conn, "delete_account", user_id=user.user_id, now=clock())
    ctx = make_ctx(conn, kek, user, clock)
    while worker.run_once(ctx):
        pass
    assert job_statuses(conn, "delete_account") == []
