"""Background worker: reads statements and sweeps expired pending files."""

import logging
import sqlite3
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from ferret import control, jobs
from ferret.config import Settings
from ferret.keys import load_master_key
from ferret.logging import setup_logging
from ferret.parsers import PARSERS, Parser
from ferret.pipeline import run_statement
from ferret.sweep import sweep_pending
from ferret.userdb import open_user_db

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
        elif job.kind == "sweep_pending":
            _sweep(ctx, now)
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
