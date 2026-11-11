import logging
import sqlite3
from datetime import date
from decimal import Decimal

import pytest
from sqlcipher3 import dbapi2 as sqlcipher

from ferret import jobs, worker
from ferret.keys import FIELD_STATEMENT_PASSWORD, encrypt_field
from ferret.parsers.base import ParsedTransaction, ParseError
from ferret.pending import pending_path
from ferret.pipeline import STATUS_DUPLICATE, fingerprint, run_statement, submit_statement
from tests.fixtures.fake_parser import FakeParser, statement
from tests.fixtures.pdfs import make_pdf

NOW = 1_800_000_000
FAKE_LINES = ["FAKE BANK STATEMENT"]


def submit(user, conn, data, *, now=NOW):
    return submit_statement(
        conn,
        user.db,
        user.dek,
        user.pending_dir,
        user.user_id,
        data,
        source="upload",
        source_ref=None,
        now=now,
    )


def run(user, statement_id, parsers):
    return run_statement(
        user.db,
        user.dek,
        user.pending_dir,
        user.user_id,
        statement_id,
        now=NOW,
        parsers=parsers,
    )


def file_exists(user, statement_id):
    return pending_path(user.pending_dir, user.user_id, statement_id).exists()


def row(user, statement_id):
    return user.db.execute("SELECT * FROM statements WHERE id = ?", (statement_id,)).fetchone()


def txn_count(user):
    return user.db.execute("SELECT count(*) FROM transactions").fetchone()[0]


def save_password(user, password, *, bank="Fake Bank"):
    ct, nonce = encrypt_field(user.dek, password, field=FIELD_STATEMENT_PASSWORD)
    user.db.execute(
        "INSERT INTO statement_passwords (bank, ciphertext, nonce, created_at) VALUES (?, ?, ?, ?)",
        (bank, ct, nonce, NOW),
    )
    user.db.commit()


def test_submit_statement_writes_row_file_and_job(user, conn):
    sid = submit(user, conn, make_pdf(FAKE_LINES))
    assert row(user, sid)["status"] == "reading"
    assert row(user, sid)["received_at"] == NOW
    assert file_exists(user, sid)
    job = jobs.claim_next(conn, now=NOW)
    assert job.kind == "parse_statement" and job.payload == {"statement_id": sid}
    assert job.user_id == user.user_id


def test_submit_statement_cleans_up_when_enqueue_fails(user, conn):
    conn.execute("DROP TABLE jobs")
    with pytest.raises(sqlite3.OperationalError):
        submit(user, conn, make_pdf(FAKE_LINES))
    assert user.db.execute("SELECT count(*) FROM statements").fetchone()[0] == 0
    assert not list(user.pending_dir.rglob("*.enc"))


def test_reconciled_saves_transactions_and_deletes_file(user, conn):
    sid = submit(user, conn, make_pdf(FAKE_LINES))
    result = run(user, sid, [FakeParser(statement())])
    assert result.status == "reconciled" and result.reconciliation.ok
    r = row(user, sid)
    assert r["status"] == "reconciled"
    assert r["fingerprint"] == fingerprint("Fake Bank", "1234", date(2026, 9, 30), 120049)
    assert r["closing"] == 120049 and r["period_end"] == "2026-09-30"
    assert txn_count(user) == 3
    card = user.db.execute("SELECT * FROM cards").fetchone()
    assert (card["bank"], card["last4"], r["card_id"]) == ("Fake Bank", "1234", card["id"])
    assert not file_exists(user, sid)


def test_second_statement_reuses_card(user, conn):
    parsers = [FakeParser(statement())]
    run(user, submit(user, conn, make_pdf(FAKE_LINES)), parsers)
    later = statement(period_end=date(2026, 10, 31))
    run(user, submit(user, conn, make_pdf(FAKE_LINES)), [FakeParser(later)])
    assert user.db.execute("SELECT count(*) FROM cards").fetchone()[0] == 1


def test_didnt_add_up_writes_no_transactions_and_deletes_file(user, conn):
    sid = submit(user, conn, make_pdf(FAKE_LINES))
    result = run(user, sid, [FakeParser(statement(closing=Decimal("1200.48")))])
    assert result.status == "didnt_add_up" and result.reconciliation.difference == 1
    r = row(user, sid)
    assert r["status"] == "didnt_add_up"
    assert (r["closing"], r["parsed_debits"], r["parsed_credits"]) == (120048, 30049, 10000)
    assert r["card_id"] is None and r["fingerprint"] is None
    assert txn_count(user) == 0
    assert user.db.execute("SELECT count(*) FROM cards").fetchone()[0] == 0
    assert not file_exists(user, sid)


def test_unsupported_deletes_file(user, conn):
    sid = submit(user, conn, make_pdf(["SOME OTHER BANK"]))
    assert run(user, sid, [FakeParser(statement())]).status == "unsupported"
    assert row(user, sid)["status"] == "unsupported"
    assert not file_exists(user, sid)


def test_not_a_statement_deletes_file(user, conn):
    sid = submit(user, conn, b"garbage bytes")
    assert run(user, sid, [FakeParser(statement())]).status == "not_a_statement"
    assert row(user, sid)["status"] == "not_a_statement"
    assert not file_exists(user, sid)


def test_parse_error_deletes_file(user, conn):
    sid = submit(user, conn, make_pdf(FAKE_LINES))
    assert run(user, sid, [FakeParser(ParseError())]).status == "not_a_statement"
    assert not file_exists(user, sid)


def test_exception_deletes_file_and_reraises(user, conn):
    sid = submit(user, conn, make_pdf(FAKE_LINES))
    with pytest.raises(RuntimeError):
        run(user, sid, [FakeParser(RuntimeError("boom"))])
    assert row(user, sid)["status"] == "not_a_statement"
    assert not file_exists(user, sid)


def test_missing_file_marks_row_failed(user, conn):
    sid = submit(user, conn, make_pdf(FAKE_LINES))
    pending_path(user.pending_dir, user.user_id, sid).unlink()
    with pytest.raises(FileNotFoundError):
        run(user, sid, [FakeParser(statement())])
    assert row(user, sid)["status"] == "not_a_statement"


def test_sub_minor_amount_is_exception_path(user, conn):
    bad = statement(
        transactions=(ParsedTransaction(date(2026, 9, 1), "Cafe Example", Decimal("1.005"), False),)
    )
    sid = submit(user, conn, make_pdf(FAKE_LINES))
    with pytest.raises(ValueError):
        run(user, sid, [FakeParser(bad)])
    assert row(user, sid)["status"] == "not_a_statement"
    assert not file_exists(user, sid)


def test_failed_insert_rolls_back(user, conn):
    negative = statement(
        opening=Decimal("0"),
        closing=Decimal("-5.00"),
        total_debits=Decimal("-5.00"),
        total_credits=Decimal("0"),
        transactions=(
            ParsedTransaction(date(2026, 9, 1), "Cafe Example", Decimal("-5.00"), False),
        ),
    )
    sid = submit(user, conn, make_pdf(FAKE_LINES))
    with pytest.raises(sqlcipher.IntegrityError):
        run(user, sid, [FakeParser(negative)])
    assert txn_count(user) == 0
    r = row(user, sid)
    assert r["status"] == "not_a_statement" and r["fingerprint"] is None
    assert user.db.execute("SELECT count(*) FROM cards").fetchone()[0] == 0
    assert not file_exists(user, sid)


def test_locked_without_password_keeps_file(user, conn):
    sid = submit(user, conn, make_pdf(FAKE_LINES, password="pw"))
    result = run(user, sid, [FakeParser(statement())])
    assert result.status == "needs_password"
    assert row(user, sid)["status"] == "needs_password"
    assert file_exists(user, sid)
    save_password(user, "wrong-one")
    assert run(user, sid, [FakeParser(statement())]).status == "needs_password"
    assert file_exists(user, sid)


def test_locked_with_saved_password_reconciles(user, conn):
    save_password(user, "nope")
    save_password(user, "pw", bank="Other Bank")
    user.db.execute(
        "INSERT INTO statement_passwords (bank, ciphertext, nonce, created_at)"
        " VALUES ('Corrupt', x'00', x'000000000000000000000000', 1)"
    )
    user.db.commit()
    sid = submit(user, conn, make_pdf(FAKE_LINES, password="pw"))
    assert run(user, sid, [FakeParser(statement())]).status == "reconciled"
    used = user.db.execute(
        "SELECT bank FROM statement_passwords WHERE last_used_at = ?", (NOW,)
    ).fetchall()
    assert [r["bank"] for r in used] == ["Other Bank"]
    assert not file_exists(user, sid)


def test_needs_password_then_saved_password_later(user, conn):
    sid = submit(user, conn, make_pdf(FAKE_LINES, password="pw"))
    assert run(user, sid, [FakeParser(statement())]).status == "needs_password"
    save_password(user, "pw")
    assert run(user, sid, [FakeParser(statement())]).status == "reconciled"
    assert not file_exists(user, sid)


def test_duplicate_fingerprint_detected(user, conn):
    parsers = [FakeParser(statement())]
    first = submit(user, conn, make_pdf(FAKE_LINES))
    run(user, first, parsers)
    second = submit(user, conn, make_pdf(FAKE_LINES))
    result = run(user, second, parsers)
    assert result.status == STATUS_DUPLICATE and result.duplicate_of == first
    assert row(user, second) is None
    assert txn_count(user) == 3
    assert not file_exists(user, second)


def test_duplicate_that_wouldnt_add_up_is_still_duplicate(user, conn):
    first = submit(user, conn, make_pdf(FAKE_LINES))
    run(user, first, [FakeParser(statement())])
    broken = statement(total_debits=Decimal("1.00"))
    second = submit(user, conn, make_pdf(FAKE_LINES))
    result = run(user, second, [FakeParser(broken)])
    assert result.status == STATUS_DUPLICATE and result.duplicate_of == first


def test_finished_row_is_noop(user, conn):
    sid = submit(user, conn, make_pdf(FAKE_LINES))
    run(user, sid, [FakeParser(statement())])
    from ferret.pending import write_pending

    write_pending(user.pending_dir, user.user_id, sid, user.dek, b"stray")
    result = run(user, sid, [FakeParser(ParseError())])
    assert result.status == "reconciled"
    assert row(user, sid)["status"] == "reconciled"
    assert not file_exists(user, sid)
    assert run(user, 999, []).status == "missing"


def test_no_secrets_in_logs(user, conn, kek, clock, caplog):
    # Root at INFO like production; third-party debug logs (pdfminer dumps content) stay off.
    caplog.set_level(logging.INFO)
    caplog.set_level(logging.DEBUG, logger="ferret")
    save_password(user, "Sup3r-Secret-pw")
    good = statement(
        transactions=(
            ParsedTransaction(date(2026, 9, 3), "XYZZY-MERCHANT", Decimal("250.50"), False),
            ParsedTransaction(date(2026, 9, 10), "Bookshop Test", Decimal("49.99"), False),
            ParsedTransaction(date(2026, 9, 15), "Payment Thank You", Decimal("100.00"), True),
        )
    )
    ctx = worker.WorkerContext(
        control=conn,
        kek=kek,
        users_dir=user.users_dir,
        pending_dir=user.pending_dir,
        clock=clock,
        parsers=[FakeParser(good)],
    )
    submit(
        user, conn, make_pdf(FAKE_LINES + ["PLUGH-TEXT"], password="Sup3r-Secret-pw"), now=clock()
    )
    submit(user, conn, make_pdf(FAKE_LINES + ["PLUGH-TEXT"], password="not-saved"), now=clock())
    while worker.run_once(ctx):
        pass
    ctx.parsers = [FakeParser(RuntimeError("XYZZY-MERCHANT"))]
    submit(user, conn, make_pdf(FAKE_LINES + ["PLUGH-TEXT"]), now=clock())
    while worker.run_once(ctx):
        pass
    failed = conn.execute("SELECT count(*) FROM jobs WHERE status = 'failed'").fetchone()[0]
    assert failed == 1
    assert "RuntimeError" in caplog.text
    for secret in ("Sup3r-Secret-pw", "XYZZY-MERCHANT", "PLUGH-TEXT", "%PDF"):
        assert secret not in caplog.text
