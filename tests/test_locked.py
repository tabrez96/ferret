import pytest

from ferret import jobs
from ferret.keys import FIELD_STATEMENT_PASSWORD, decrypt_field
from ferret.pending import pending_path
from ferret.pipeline import run_statement, submit_statement
from ferret.pipeline.locked import NotWaiting, WrongPassword, open_with_password, skip_statement
from tests.fixtures.fake_parser import FakeParser, statement
from tests.fixtures.pdfs import make_pdf
from tests.test_pipeline import FAKE_LINES, NOW, file_exists, row, save_password

PARSERS = [FakeParser(statement())]


@pytest.fixture
def locked(user, conn):
    sid = submit_statement(
        conn,
        user.db,
        user.dek,
        user.pending_dir,
        user.user_id,
        make_pdf(FAKE_LINES, password="pw"),
        source="upload",
        source_ref=None,
        now=NOW,
    )
    assert (
        run_statement(
            user.db, user.dek, user.pending_dir, user.user_id, sid, now=NOW, parsers=PARSERS
        ).status
        == "needs_password"
    )
    job = jobs.claim_next(conn, now=NOW)
    jobs.finish(conn, job.id)
    return sid


def open_it(user, conn, sid, password="pw", parsers=PARSERS):
    open_with_password(
        conn, user.db, user.dek, user.pending_dir, user.user_id, sid, password,
        now=NOW, parsers=parsers,
    )  # fmt: skip


def saved(user):
    return user.db.execute("SELECT * FROM statement_passwords").fetchall()


def test_correct_password_saves_and_requeues(user, conn, locked):
    open_it(user, conn, locked)
    assert row(user, locked)["status"] == "reading"
    (saved_row,) = saved(user)
    assert saved_row["bank"] == "Fake Bank" and saved_row["card_id"] is None
    plain = decrypt_field(
        user.dek, saved_row["ciphertext"], saved_row["nonce"], field=FIELD_STATEMENT_PASSWORD
    )
    assert plain == "pw"
    job = jobs.claim_next(conn, now=NOW)
    assert job.kind == "parse_statement" and job.payload == {"statement_id": locked}
    result = run_statement(
        user.db, user.dek, user.pending_dir, user.user_id, locked, now=NOW, parsers=PARSERS
    )
    assert result.status == "reconciled"


def test_password_saved_for_known_card(user, conn, locked):
    cur = user.db.execute(
        "INSERT INTO cards (bank, last4, currency) VALUES ('Fake Bank', '1234', 'AED')"
    )
    user.db.commit()
    open_it(user, conn, locked)
    assert saved(user)[0]["card_id"] == cur.lastrowid


def test_new_password_replaces_old(user, conn, locked):
    cur = user.db.execute(
        "INSERT INTO cards (bank, last4, currency) VALUES ('Fake Bank', '1234', 'AED')"
    )
    user.db.commit()
    save_password(user, "old")
    user.db.execute("UPDATE statement_passwords SET card_id = ?", (cur.lastrowid,))
    user.db.commit()
    open_it(user, conn, locked)
    (saved_row,) = saved(user)
    assert (
        decrypt_field(
            user.dek, saved_row["ciphertext"], saved_row["nonce"], field=FIELD_STATEMENT_PASSWORD
        )
        == "pw"
    )


def test_wrong_password_keeps_file(user, conn, locked):
    with pytest.raises(WrongPassword):
        open_it(user, conn, locked, "nope")
    assert file_exists(user, locked)
    assert row(user, locked)["status"] == "needs_password"
    assert saved(user) == []
    assert jobs.claim_next(conn, now=NOW) is None


def test_unknown_bank_not_saved(user, conn, locked):
    open_it(user, conn, locked, parsers=[])
    assert saved(user) == []
    assert row(user, locked)["status"] == "reading"


def test_skip_deletes_file_and_marks_skipped(user, locked):
    skip_statement(user.db, user.pending_dir, user.user_id, locked)
    assert not file_exists(user, locked)
    assert row(user, locked)["status"] == "skipped"


def test_not_waiting(user, conn, locked):
    pending_path(user.pending_dir, user.user_id, locked).unlink()
    with pytest.raises(NotWaiting):
        open_it(user, conn, locked)
    user.db.execute("UPDATE statements SET status = 'reconciled'")
    user.db.commit()
    with pytest.raises(NotWaiting):
        open_it(user, conn, locked)
    with pytest.raises(NotWaiting):
        skip_statement(user.db, user.pending_dir, user.user_id, locked)


def test_skip_after_open_is_refused(user, conn, locked):
    open_it(user, conn, locked)
    with pytest.raises(NotWaiting):
        skip_statement(user.db, user.pending_dir, user.user_id, locked)
    assert row(user, locked)["status"] == "reading"
    assert file_exists(user, locked)


def test_open_after_skip_is_refused(user, conn, locked):
    skip_statement(user.db, user.pending_dir, user.user_id, locked)
    with pytest.raises(NotWaiting):
        open_it(user, conn, locked)
    assert row(user, locked)["status"] == "skipped"
    assert not saved(user) and jobs.claim_next(conn, now=NOW) is None


def test_open_does_not_overwrite_a_reconciled_row(user, conn, locked, monkeypatch):
    # The worker finishes the statement between the unlock and the claim.
    import ferret.pipeline.locked as mod

    real = mod._identify

    def identify_then_reconcile(*args):
        result = real(*args)
        user.db.execute("UPDATE statements SET status = 'reconciled'")
        user.db.commit()
        return result

    monkeypatch.setattr(mod, "_identify", identify_then_reconcile)
    with pytest.raises(NotWaiting):
        open_it(user, conn, locked)
    assert row(user, locked)["status"] == "reconciled"
    assert not saved(user) and jobs.claim_next(conn, now=NOW) is None
