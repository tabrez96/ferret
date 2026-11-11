"""Statement pipeline: unlock, detect, parse, reconcile, delete."""

import hashlib
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlcipher3 import dbapi2 as sqlcipher

from ferret import jobs
from ferret.keys import FIELD_STATEMENT_PASSWORD, DecryptionError, decrypt_field
from ferret.money import to_minor
from ferret.parsers import PARSERS, ParsedStatement, ParseError, Parser, find_parser
from ferret.pending import delete_pending, read_pending, write_pending
from ferret.pipeline.pdf import NotAPdf, PasswordRequired, first_page_text, open_pdf, unlock
from ferret.reconcile import Reconciliation, reconcile

logger = logging.getLogger(__name__)

STATUS_DUPLICATE = "duplicate"  # result-only status; no row keeps it (the new row is deleted)


@dataclass(frozen=True)
class PipelineResult:
    statement_id: int
    status: str  # final statements.status, or "duplicate"
    duplicate_of: int | None = None
    reconciliation: Reconciliation | None = None


def fingerprint(bank: str, card_last4: str, period_end: date, closing_minor: int) -> str:
    raw = f"{bank}\x1f{card_last4}\x1f{period_end.isoformat()}\x1f{closing_minor}"
    return hashlib.sha256(raw.encode()).hexdigest()


def submit_statement(
    control_conn,
    user_db,
    dek: bytes,
    pending_dir: Path,
    user_id: str,
    data: bytes,
    *,
    source: str,
    source_ref: str | None,
    now: int,
) -> int:
    """Record a statement, store its file encrypted and queue a job to read it."""
    with user_db:
        cur = user_db.execute(
            "INSERT INTO statements (source, source_ref, received_at, status)"
            " VALUES (?, ?, ?, 'reading')",
            (source, source_ref, now),
        )
        statement_id = cur.lastrowid
    try:
        write_pending(pending_dir, user_id, statement_id, dek, data)
        jobs.enqueue(
            control_conn,
            "parse_statement",
            user_id=user_id,
            payload={"statement_id": statement_id},
            now=now,
        )
    except BaseException:
        delete_pending(pending_dir, user_id, statement_id)
        with user_db:
            user_db.execute("DELETE FROM statements WHERE id = ?", (statement_id,))
        raise
    return statement_id


def _saved_passwords(user_db, dek: bytes) -> list[tuple[int, str]]:
    rows = user_db.execute(
        "SELECT id, ciphertext, nonce FROM statement_passwords"
        " ORDER BY last_used_at IS NULL, last_used_at DESC, id"
    ).fetchall()
    found = []
    for row in rows:
        try:
            password = decrypt_field(
                dek, row["ciphertext"], row["nonce"], field=FIELD_STATEMENT_PASSWORD
            )
        except DecryptionError:
            continue
        found.append((row["id"], password))
    return found


def _set_status(user_db, statement_id: int, status: str) -> PipelineResult:
    with user_db:
        user_db.execute("UPDATE statements SET status = ? WHERE id = ?", (status, statement_id))
    logger.info("statement %d: %s", statement_id, status)
    return PipelineResult(statement_id, status)


def _find_duplicate(user_db, fingerprint_: str, statement_id: int) -> int | None:
    row = user_db.execute(
        "SELECT id FROM statements WHERE fingerprint = ? AND id != ?",
        (fingerprint_, statement_id),
    ).fetchone()
    return row["id"] if row else None


def _drop_duplicate(
    user_db, statement_id: int, duplicate_of: int, rec: Reconciliation
) -> PipelineResult:
    with user_db:
        user_db.execute("DELETE FROM statements WHERE id = ?", (statement_id,))
    logger.info("statement %d duplicates %d", statement_id, duplicate_of)
    return PipelineResult(statement_id, STATUS_DUPLICATE, duplicate_of, rec)


def _save_didnt_add_up(
    user_db, statement_id: int, parsed: ParsedStatement, rec: Reconciliation
) -> None:
    # card_id and fingerprint stay NULL so a re-upload after a parser fix isn't blocked.
    with user_db:
        user_db.execute(
            "UPDATE statements SET status = 'didnt_add_up', bank = ?, period_start = ?,"
            " period_end = ?, currency = ?, opening = ?, closing = ?, total_debits = ?,"
            " total_credits = ?, parsed_debits = ?, parsed_credits = ? WHERE id = ?",
            (
                parsed.bank,
                parsed.period_start.isoformat(),
                parsed.period_end.isoformat(),
                rec.currency,
                rec.opening,
                rec.closing,
                rec.total_debits,
                rec.total_credits,
                rec.parsed_debits,
                rec.parsed_credits,
                statement_id,
            ),
        )


def _save_reconciled(
    user_db, statement_id: int, parsed: ParsedStatement, rec: Reconciliation, fp: str
) -> None:
    # One SQL transaction: the card, the reconciled row and every transaction, or nothing.
    with user_db:
        user_db.execute(
            "INSERT INTO cards (bank, last4, currency) VALUES (?, ?, ?)"
            " ON CONFLICT (bank, last4) DO NOTHING",
            (parsed.bank, parsed.card_last4, rec.currency),
        )
        card_id = user_db.execute(
            "SELECT id FROM cards WHERE bank = ? AND last4 = ?",
            (parsed.bank, parsed.card_last4),
        ).fetchone()["id"]
        user_db.execute(
            "UPDATE statements SET status = 'reconciled', card_id = ?, bank = ?,"
            " period_start = ?, period_end = ?, currency = ?, opening = ?, closing = ?,"
            " total_debits = ?, total_credits = ?, parsed_debits = ?, parsed_credits = ?,"
            " fingerprint = ? WHERE id = ?",
            (
                card_id,
                parsed.bank,
                parsed.period_start.isoformat(),
                parsed.period_end.isoformat(),
                rec.currency,
                rec.opening,
                rec.closing,
                rec.total_debits,
                rec.total_credits,
                rec.parsed_debits,
                rec.parsed_credits,
                fp,
                statement_id,
            ),
        )
        user_db.executemany(
            "INSERT INTO transactions"
            " (statement_id, card_id, posted_on, merchant, amount_minor, currency, is_credit)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    statement_id,
                    card_id,
                    t.posted_on.isoformat(),
                    t.merchant,
                    to_minor(t.amount, rec.currency),
                    rec.currency,
                    int(t.is_credit),
                )
                for t in parsed.transactions
            ],
        )


def _mark_failed(user_db, statement_id: int) -> None:
    try:
        user_db.rollback()
        with user_db:
            user_db.execute(
                "UPDATE statements SET status = 'not_a_statement' WHERE id = ?", (statement_id,)
            )
    except Exception:  # best effort; the original error is what matters
        pass


def run_statement(
    user_db,
    dek: bytes,
    pending_dir: Path,
    user_id: str,
    statement_id: int,
    *,
    now: int,
    parsers: Sequence[Parser] = PARSERS,
) -> PipelineResult:
    """Read one submitted statement; the file is deleted unless it is locked with no password."""
    row = user_db.execute("SELECT status FROM statements WHERE id = ?", (statement_id,)).fetchone()
    if row is None or row["status"] not in ("reading", "needs_password"):
        delete_pending(pending_dir, user_id, statement_id)  # never leave a stray file
        return PipelineResult(statement_id, row["status"] if row else "missing")
    keep_file = False
    try:
        data = read_pending(pending_dir, user_id, statement_id, dek)
        candidates = _saved_passwords(user_db, dek)
        try:
            unlocked, used = unlock(data, [password for _, password in candidates])
        except PasswordRequired:
            keep_file = True
            return _set_status(user_db, statement_id, "needs_password")
        except NotAPdf:
            return _set_status(user_db, statement_id, "not_a_statement")
        if used is not None:
            with user_db:
                user_db.execute(
                    "UPDATE statement_passwords SET last_used_at = ? WHERE id = ?",
                    (now, candidates[used][0]),
                )
        try:
            with open_pdf(unlocked) as pdf:
                parser = find_parser(first_page_text(pdf), parsers)
                if parser is None:
                    return _set_status(user_db, statement_id, "unsupported")
                try:
                    parsed = parser.parse(pdf)
                except ParseError:
                    return _set_status(user_db, statement_id, "not_a_statement")
        except NotAPdf:
            return _set_status(user_db, statement_id, "not_a_statement")
        rec = reconcile(parsed)
        fp = fingerprint(parsed.bank, parsed.card_last4, parsed.period_end, rec.closing)
        dup = _find_duplicate(user_db, fp, statement_id)
        if dup is not None:
            return _drop_duplicate(user_db, statement_id, dup, rec)
        if not rec.ok:
            _save_didnt_add_up(user_db, statement_id, parsed, rec)
            logger.info("statement %d: %s", statement_id, "didnt_add_up")
            return PipelineResult(statement_id, "didnt_add_up", reconciliation=rec)
        try:
            _save_reconciled(user_db, statement_id, parsed, rec, fp)
        except sqlcipher.IntegrityError:
            dup = _find_duplicate(user_db, fp, statement_id)
            if dup is None:
                raise
            return _drop_duplicate(user_db, statement_id, dup, rec)
        logger.info("statement %d: %s", statement_id, "reconciled")
        logger.info("statement %d: %d transactions", statement_id, len(parsed.transactions))
        return PipelineResult(statement_id, "reconciled", reconciliation=rec)
    except Exception:
        _mark_failed(user_db, statement_id)
        raise
    finally:
        if not keep_file:
            delete_pending(pending_dir, user_id, statement_id)
