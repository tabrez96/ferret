import sqlite3

import pytest

from ferret import jobs

A, B = "a" * 32, "b" * 32


def status(conn, job_id):
    return conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()["status"]


def test_enqueue_and_claim_order(conn):
    late = jobs.enqueue(conn, "gmail_poll", user_id=A, now=100, run_after=200)
    first = jobs.enqueue(conn, "parse_statement", user_id=A, payload={"statement_id": 1}, now=100)
    future = jobs.enqueue(conn, "gmail_poll", user_id=B, now=100, run_after=10_000)
    job = jobs.claim_next(conn, now=300)
    assert job.id == first and job.payload == {"statement_id": 1} and job.attempts == 1
    jobs.finish(conn, first)
    assert jobs.claim_next(conn, now=300).id == late
    jobs.finish(conn, late)
    assert jobs.claim_next(conn, now=300) is None
    assert status(conn, future) == "queued"


def test_one_running_job_per_user(conn):
    a1 = jobs.enqueue(conn, "parse_statement", user_id=A, now=1)
    a2 = jobs.enqueue(conn, "parse_statement", user_id=A, now=1)
    b1 = jobs.enqueue(conn, "parse_statement", user_id=B, now=1)
    assert jobs.claim_next(conn, now=5).id == a1
    assert jobs.claim_next(conn, now=5).id == b1
    assert jobs.claim_next(conn, now=5) is None
    jobs.finish(conn, a1)
    assert jobs.claim_next(conn, now=5).id == a2


def test_global_jobs_not_blocked(conn):
    a1 = jobs.enqueue(conn, "parse_statement", user_id=A, now=1)
    sweep = jobs.enqueue(conn, "sweep_pending", user_id=None, now=1)
    assert jobs.claim_next(conn, now=5).id == a1
    assert jobs.claim_next(conn, now=5).id == sweep


def test_finish_fail_requeue_stale(conn):
    one = jobs.enqueue(conn, "gmail_poll", user_id=A, now=1)
    two = jobs.enqueue(conn, "gmail_poll", user_id=B, now=1)
    three = jobs.enqueue(conn, "sweep_pending", user_id=None, now=1)
    for _ in range(3):
        jobs.claim_next(conn, now=5)
    jobs.finish(conn, one)
    jobs.fail(conn, two)
    assert (status(conn, one), status(conn, two), status(conn, three)) == (
        "done",
        "failed",
        "running",
    )
    assert jobs.requeue_stale(conn) == 1
    assert status(conn, three) == "queued"


def test_ensure_scheduled_idempotent(conn):
    jobs.ensure_scheduled(conn, "sweep_pending", now=1, run_after=1)
    jobs.ensure_scheduled(conn, "sweep_pending", now=2, run_after=2)
    assert conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1
    jobs.claim_next(conn, now=5)
    jobs.ensure_scheduled(conn, "sweep_pending", now=6, run_after=6)
    assert conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1


def test_schedule_user_job_once_per_user(conn):
    assert jobs.schedule_user_job(conn, "gmail_poll", A, now=1, run_after=10) is True
    assert jobs.schedule_user_job(conn, "gmail_poll", A, now=1, run_after=10) is False
    assert jobs.schedule_user_job(conn, "gmail_poll", B, now=1, run_after=10) is True


def queued(conn, kind="gmail_poll", user_id=A):
    rows = conn.execute(
        "SELECT run_after FROM jobs WHERE kind = ? AND user_id = ? AND status = 'queued'",
        (kind, user_id),
    ).fetchall()
    return [r["run_after"] for r in rows]


def test_run_user_job_now(conn):
    jobs.run_user_job_now(conn, "gmail_poll", A, now=100)
    assert queued(conn) == [100]
    jobs.run_user_job_now(conn, "gmail_poll", A, now=150)
    assert queued(conn) == [100]


def test_run_user_job_now_pulls_forward(conn):
    jobs.enqueue(conn, "gmail_poll", user_id=A, now=1, run_after=9_000)
    jobs.enqueue(conn, "gmail_poll", user_id=B, now=1, run_after=9_000)
    jobs.run_user_job_now(conn, "gmail_poll", A, now=200)
    assert queued(conn) == [200]
    assert queued(conn, user_id=B) == [9_000]


def test_run_user_job_now_new_job_is_committed(conn):
    jobs.run_user_job_now(conn, "gmail_poll", A, now=0)

    path = conn.execute("PRAGMA database_list").fetchone()["file"]
    with sqlite3.connect(path) as observer:
        observer.row_factory = sqlite3.Row
        row = observer.execute("SELECT * FROM jobs").fetchone()
    assert dict(row) == {
        "id": 1,
        "user_id": A,
        "kind": "gmail_poll",
        "payload_json": "{}",
        "status": "queued",
        "attempts": 0,
        "run_after": 0,
        "created_at": 0,
    }
    assert not conn.in_transaction
    assert jobs.claim_next(conn, now=0).id == row["id"]


def test_run_user_job_now_updates_all_queued_jobs_preserving_metadata(conn):
    job_ids = [
        jobs.enqueue(
            conn,
            "gmail_poll",
            user_id=A,
            payload={"cursor": "saved"},
            now=1,
            run_after=run_after,
        )
        for run_after in (50, 100, 9_000)
    ]
    with conn:
        conn.execute("UPDATE jobs SET attempts = 2")
    before = [dict(row) for row in conn.execute("SELECT * FROM jobs ORDER BY id")]

    jobs.run_user_job_now(conn, "gmail_poll", A, now=100)

    path = conn.execute("PRAGMA database_list").fetchone()["file"]
    with sqlite3.connect(path) as observer:
        observer.row_factory = sqlite3.Row
        after = [dict(row) for row in observer.execute("SELECT * FROM jobs ORDER BY id")]
    assert after == [dict(row, run_after=min(row["run_after"], 100)) for row in before]
    assert [row["id"] for row in after] == job_ids
    assert not conn.in_transaction


@pytest.mark.parametrize("existing_status", ["running", "done", "failed"])
def test_run_user_job_now_keeps_existing_nonqueued_job(conn, existing_status):
    original = jobs.enqueue(conn, "gmail_poll", user_id=A, now=1)
    with conn:
        conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (existing_status, original))
    before = dict(conn.execute("SELECT * FROM jobs WHERE id = ?", (original,)).fetchone())
    jobs.enqueue(conn, "parse_statement", user_id=A, now=1, run_after=9_000)
    jobs.enqueue(conn, "gmail_poll", user_id=B, now=1, run_after=9_000)
    jobs.enqueue(conn, "gmail_poll", user_id=None, now=1, run_after=9_000)

    jobs.run_user_job_now(conn, "gmail_poll", A, now=100)

    assert dict(conn.execute("SELECT * FROM jobs WHERE id = ?", (original,)).fetchone()) == before
    assert queued(conn) == [100]
    assert queued(conn, "parse_statement") == [9_000]
    assert queued(conn, user_id=B) == [9_000]
    assert conn.execute("SELECT run_after FROM jobs WHERE user_id IS NULL").fetchone()[0] == 9_000
    assert conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == 5
    if existing_status == "running":
        # Check now queues a follow-up without violating one running job per user.
        assert jobs.claim_next(conn, now=100) is None
        jobs.finish(conn, original)
    assert jobs.claim_next(conn, now=100).user_id == A


@pytest.mark.parametrize("operation", ["INSERT", "UPDATE"])
def test_run_user_job_now_rolls_back_write_failure(conn, operation):
    if operation == "UPDATE":
        jobs.enqueue(conn, "gmail_poll", user_id=A, now=1, run_after=9_000)
    before = [dict(row) for row in conn.execute("SELECT * FROM jobs ORDER BY id")]
    # FAIL leaves the trigger's preceding row change in the transaction. The caller
    # must roll it back, including an INSERT that has already created a row.
    conn.execute(
        f"CREATE TEMP TRIGGER reject_job_write AFTER {operation} ON jobs "
        "BEGIN SELECT RAISE(FAIL, 'job write rejected'); END"
    )

    with pytest.raises(sqlite3.IntegrityError, match="job write rejected"):
        jobs.run_user_job_now(conn, "gmail_poll", A, now=100)

    assert not conn.in_transaction
    assert [dict(row) for row in conn.execute("SELECT * FROM jobs ORDER BY id")] == before
    conn.execute("DROP TRIGGER reject_job_write")
    jobs.run_user_job_now(conn, "gmail_poll", A, now=100)
    assert queued(conn) == [100]


@pytest.mark.parametrize("has_queued_job", [False, True])
@pytest.mark.parametrize("error_type", [sqlite3.OperationalError, KeyboardInterrupt])
def test_run_user_job_now_rolls_back_commit_failure(conn, has_queued_job, error_type):
    class FailingCommitConnection(sqlite3.Connection):
        def commit(self):
            raise error_type("commit interrupted")

    if has_queued_job:
        jobs.enqueue(conn, "gmail_poll", user_id=A, now=1, run_after=9_000)
    failing = sqlite3.connect(":memory:", factory=FailingCommitConnection)
    failing.row_factory = sqlite3.Row
    try:
        conn.backup(failing)
        before = [dict(row) for row in failing.execute("SELECT * FROM jobs ORDER BY id")]

        with pytest.raises(error_type, match="commit interrupted"):
            jobs.run_user_job_now(failing, "gmail_poll", A, now=100)

        assert not failing.in_transaction
        assert [dict(row) for row in failing.execute("SELECT * FROM jobs ORDER BY id")] == before
    finally:
        failing.close()


def test_cancel_user_jobs(conn):
    running = jobs.enqueue(conn, "gmail_poll", user_id=A, now=1)
    assert jobs.claim_next(conn, now=2).id == running
    jobs.enqueue(conn, "gmail_poll", user_id=A, now=1, run_after=500)
    jobs.enqueue(conn, "parse_statement", user_id=A, now=1, run_after=500)
    jobs.enqueue(conn, "gmail_poll", user_id=B, now=1, run_after=500)
    assert jobs.cancel_user_jobs(conn, "gmail_poll", A) == 1
    assert queued(conn) == []
    assert queued(conn, "parse_statement") == [500]
    assert queued(conn, user_id=B) == [500]
    assert status(conn, running) == "running"
