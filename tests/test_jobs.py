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
