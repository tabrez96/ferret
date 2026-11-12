"""Opening a locked statement with a typed password, or skipping it."""

import logging
from collections.abc import Sequence
from pathlib import Path

from ferret import jobs
from ferret.keys import FIELD_STATEMENT_PASSWORD, encrypt_field
from ferret.parsers import PARSERS, ParseError, Parser, find_parser
from ferret.pending import delete_pending, read_pending, write_pending
from ferret.pipeline.pdf import NotAPdf, PasswordRequired, first_page_text, open_pdf, unlock

logger = logging.getLogger(__name__)


class WrongPassword(Exception):
    """The typed password did not open the file."""


class NotWaiting(Exception):
    """The statement is not waiting for a password (or its file is gone)."""


def has_saved_passwords(user_db) -> bool:
    return user_db.execute("SELECT 1 FROM statement_passwords LIMIT 1").fetchone() is not None


def save_password(
    user_db, dek: bytes, *, bank: str, card_id: int | None, password: str, now: int
) -> None:
    """Store the password encrypted, replacing the one saved for this card (or bank)."""
    ciphertext, nonce = encrypt_field(dek, password, field=FIELD_STATEMENT_PASSWORD)
    with user_db:
        if card_id is not None:
            user_db.execute("DELETE FROM statement_passwords WHERE card_id = ?", (card_id,))
        else:
            user_db.execute(
                "DELETE FROM statement_passwords WHERE bank = ? AND card_id IS NULL", (bank,)
            )
        user_db.execute(
            "INSERT INTO statement_passwords"
            " (card_id, bank, ciphertext, nonce, created_at, last_used_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (card_id, bank, ciphertext, nonce, now, now),
        )


def _waiting(user_db, statement_id: int) -> None:
    row = user_db.execute("SELECT status FROM statements WHERE id = ?", (statement_id,)).fetchone()
    if row is None or row["status"] != "needs_password":
        raise NotWaiting


def _claim(user_db, statement_id: int, status: str) -> None:
    """Move the row out of needs_password, or raise NotWaiting if someone else already did."""
    with user_db:
        claimed = user_db.execute(
            "UPDATE statements SET status = ? WHERE id = ? AND status = 'needs_password'",
            (status, statement_id),
        )
    if claimed.rowcount == 0:
        raise NotWaiting


def _identify(user_db, unlocked: bytes, parsers: Sequence[Parser]) -> tuple[str, int | None] | None:
    """The bank and, when already known, the card this statement belongs to."""
    try:
        with open_pdf(unlocked) as pdf:
            parser = find_parser(first_page_text(pdf), parsers)
            if parser is None:
                return None
            try:
                parsed = parser.parse(pdf)
            except ParseError:
                return parser.bank, None
    except NotAPdf:
        return None
    card = user_db.execute(
        "SELECT id FROM cards WHERE bank = ? AND last4 = ?", (parsed.bank, parsed.card_last4)
    ).fetchone()
    return parser.bank, (card["id"] if card else None)


def open_with_password(
    control_conn,
    user_db,
    dek: bytes,
    pending_dir: Path,
    user_id: str,
    statement_id: int,
    password: str,
    *,
    now: int,
    parsers: Sequence[Parser] = PARSERS,
) -> None:
    """Unlock in memory, save the password, keep an unlocked copy and queue the statement.

    The password is never put in a job payload or a log line: the worker reads the unlocked copy.
    """
    _waiting(user_db, statement_id)
    try:
        data = read_pending(pending_dir, user_id, statement_id, dek)
    except FileNotFoundError:
        raise NotWaiting from None
    try:
        unlocked, _ = unlock(data, [password])
    except PasswordRequired:
        raise WrongPassword from None
    who = _identify(user_db, unlocked, parsers)
    _claim(user_db, statement_id, "reading")
    if who:
        save_password(user_db, dek, bank=who[0], card_id=who[1], password=password, now=now)
    write_pending(pending_dir, user_id, statement_id, dek, unlocked)
    jobs.enqueue(
        control_conn,
        "parse_statement",
        user_id=user_id,
        payload={"statement_id": statement_id},
        now=now,
    )
    logger.info("statement %d: password accepted", statement_id)


def skip_statement(user_db, pending_dir: Path, user_id: str, statement_id: int) -> None:
    _claim(user_db, statement_id, "skipped")
    delete_pending(pending_dir, user_id, statement_id)
    logger.info("statement %d: skipped", statement_id)
