from ferret import sweep as sweep_module
from ferret.pending import PENDING_TTL_SECONDS, pending_path, write_pending
from ferret.sweep import sweep_pending

DAY = 24 * 3600


def add_pending(user, clock, age_days, *, status="needs_password", write=True):
    received = clock.now - age_days * DAY
    cur = user.db.execute(
        "INSERT INTO statements (source, received_at, status) VALUES ('upload', ?, ?)",
        (received, status),
    )
    user.db.commit()
    sid = cur.lastrowid
    if write:
        write_pending(user.pending_dir, user.user_id, sid, user.dek, b"data")
    return sid


def status(user, sid):
    return user.db.execute("SELECT status FROM statements WHERE id = ?", (sid,)).fetchone()[0]


def sweep(conn, kek, user, clock):
    return sweep_pending(conn, kek, user.users_dir, user.pending_dir, now=clock.now)


def test_seven_day_old_file_deleted_and_row_skipped(user, conn, kek, clock):
    sid = add_pending(user, clock, 8)
    assert sweep(conn, kek, user, clock) == 1
    assert not pending_path(user.pending_dir, user.user_id, sid).exists()
    assert status(user, sid) == "skipped"


def test_exactly_seven_days_expires(user, conn, kek, clock):
    sid = add_pending(user, clock, 0)
    clock.advance(PENDING_TTL_SECONDS)
    assert sweep(conn, kek, user, clock) == 1
    assert status(user, sid) == "skipped"


def test_six_day_old_file_kept(user, conn, kek, clock):
    sid = add_pending(user, clock, 6)
    assert sweep(conn, kek, user, clock) == 0
    assert pending_path(user.pending_dir, user.user_id, sid).exists()
    assert status(user, sid) == "needs_password"


def test_orphan_file_and_deleted_user_dir_removed(user, conn, kek, clock):
    write_pending(user.pending_dir, user.user_id, 99, user.dek, b"orphan")
    stray = user.pending_dir / user.user_id / "junk.tmp"
    stray.write_bytes(b"x")
    ghost = user.pending_dir / ("c" * 32)
    ghost.mkdir(parents=True)
    (ghost / "1.pdf.enc").write_bytes(b"x")
    ignored = user.pending_dir / "not-a-user"
    ignored.mkdir()
    (ignored / "keep.txt").write_bytes(b"x")
    assert sweep(conn, kek, user, clock) == 3
    assert not ghost.exists()
    assert not list((user.pending_dir / user.user_id).iterdir())
    assert (ignored / "keep.txt").exists()


def test_expired_row_without_file_skipped(user, conn, kek, clock):
    sid = add_pending(user, clock, 8, write=False)
    fresh = add_pending(user, clock, 1, write=False)
    add_pending(user, clock, 1)  # the user's pending directory exists once a file was written
    sweep(conn, kek, user, clock)
    assert status(user, sid) == "skipped"
    assert status(user, fresh) == "needs_password"


def test_failing_user_does_not_stop_sweep(user, conn, kek, clock, monkeypatch):
    bad = "0" * 32
    (user.pending_dir / bad).mkdir(parents=True)
    (user.pending_dir / bad / "1.pdf.enc").write_bytes(b"x")
    sid = add_pending(user, clock, 8)
    real = sweep_module.load_dek

    def flaky(control_conn, kek_, user_id):
        if user_id == bad:
            raise RuntimeError("cannot open")
        return real(control_conn, kek_, user_id)

    monkeypatch.setattr(sweep_module, "load_dek", flaky)
    assert sweep(conn, kek, user, clock) == 1
    assert not pending_path(user.pending_dir, user.user_id, sid).exists()
    assert status(user, sid) == "skipped"
    assert (user.pending_dir / bad / "1.pdf.enc").exists()


def test_missing_pending_dir(conn, kek, user, clock):
    assert sweep(conn, kek, user, clock) == 0
