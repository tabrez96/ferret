"""Background worker: reads statements, polls Gmail, sweeps pending files, deletes accounts."""

import logging
import shutil
import sqlite3
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from ferret import control, jobs
from ferret.config import Settings
from ferret.gmail.client import GmailFactory
from ferret.gmail.poll import POLL_INTERVAL_SECONDS, gmail_connected, poll_gmail
from ferret.keys import load_master_key
from ferret.logging import setup_logging
from ferret.parsers import PARSERS, Parser
from ferret.pipeline import run_statement
from ferret.sweep import sweep_pending
from ferret.userdb import open_user_db, user_db_path

logger = logging.getLogger(__name__)

SWEEP_INTERVAL_SECONDS = 3600
IDLE_SLEEP_SECONDS = 2


@dataclass
class WorkerContext:
    control: sqlite3.Connection
    kek: bytes
    users_dir: Path
    pending_dir: Path
    clock: Callable[[], int]
    parsers: Sequence[Parser] = PARSERS
    gmail_factory: GmailFactory | None = None


def _parse_statement(ctx: WorkerContext, job: jobs.Job, now: int) -> None:
    dek = control.load_dek(ctx.control, ctx.kek, job.user_id)
    user_db = open_user_db(ctx.users_dir, job.user_id, dek)
    try:
        run_statement(
            user_db,
            dek,
            ctx.pending_dir,
            job.user_id,
            job.payload["statement_id"],
            now=now,
            parsers=ctx.parsers,
        )
    finally:
        user_db.close()


def _gmail_poll(ctx: WorkerContext, job: jobs.Job, now: int) -> None:
    if ctx.gmail_factory is None:
        logger.warning("gmail_poll: Google client is not configured")
        return
    dek = control.load_dek(ctx.control, ctx.kek, job.user_id)
    user_db = open_user_db(ctx.users_dir, job.user_id, dek)
    try:
        poll_gmail(
            ctx.control,
            user_db,
            dek,
            ctx.pending_dir,
            job.user_id,
            gmail_factory=ctx.gmail_factory,
            now=now,
            parsers=ctx.parsers,
        )
    finally:
        try:
            # Even after a failure the next poll is 6 hours away; a stopped account is not polled.
            if gmail_connected(user_db):
                jobs.schedule_user_job(
                    ctx.control,
                    "gmail_poll",
                    job.user_id,
                    now=now,
                    run_after=now + POLL_INTERVAL_SECONDS,
                )
        finally:
            user_db.close()


def _sweep(ctx: WorkerContext, now: int) -> None:
    try:
        sweep_pending(ctx.control, ctx.kek, ctx.users_dir, ctx.pending_dir, now=now)
    finally:
        # Even after a failure the next sweep waits an hour instead of spinning.
        jobs.enqueue(
            ctx.control,
            "sweep_pending",
            user_id=None,
            now=now,
            run_after=now + SWEEP_INTERVAL_SECONDS,
        )


def _delete_account(ctx: WorkerContext, job: jobs.Job, now: int) -> None:
    # Idempotent: a retried job finds some or all of this already gone.
    db_path = user_db_path(ctx.users_dir, job.user_id)  # validates the id
    for path in (db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm")):
        path.unlink(missing_ok=True)
    pending = ctx.pending_dir / job.user_id
    if pending.exists():
        shutil.rmtree(pending)
    control.delete_user(ctx.control, job.user_id)


def run_once(ctx: WorkerContext) -> bool:
    """Run at most one job. Returns True if a job was claimed."""
    now = ctx.clock()
    jobs.ensure_scheduled(ctx.control, "sweep_pending", now=now, run_after=now)
    job = jobs.claim_next(ctx.control, now=now)
    if job is None:
        return False
    try:
        if job.kind == "parse_statement":
            _parse_statement(ctx, job, now)
        elif job.kind == "gmail_poll":
            _gmail_poll(ctx, job, now)
        elif job.kind == "sweep_pending":
            _sweep(ctx, now)
        elif job.kind == "delete_account":
            _delete_account(ctx, job, now)
            jobs.delete(ctx.control, job.id)
            return True
        else:
            logger.warning("job %d: no handler for %s", job.id, job.kind)
            jobs.fail(ctx.control, job.id)
            return True
    except Exception as exc:
        # Type only: the message could carry statement content.
        jobs.fail(ctx.control, job.id)
        logger.error("job %d (%s) failed: %s", job.id, job.kind, type(exc).__name__)
        return True
    jobs.finish(ctx.control, job.id)
    return True


def main() -> None:
    settings = Settings.from_env()
    setup_logging()
    kek = load_master_key(settings.master_key_file, settings.data_dir)
    conn = control.connect(settings.control_db_path)
    jobs.requeue_stale(conn)
    ctx = WorkerContext(
        control=conn,
        kek=kek,
        users_dir=settings.users_dir,
        pending_dir=settings.pending_dir,
        clock=lambda: int(time.time()),
    )
    while True:
        if not run_once(ctx):
            time.sleep(IDLE_SLEEP_SECONDS)


if __name__ == "__main__":
    main()
