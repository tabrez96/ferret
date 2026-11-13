"""Saved statement passwords as S05 shows them: listed and replaced."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from ferret.history import DASH, card_label
from ferret.keys import FIELD_STATEMENT_PASSWORD, encrypt_field

logger = logging.getLogger(__name__)

ROWS_QUERY = """
SELECT p.id AS password_id, c.bank, c.nickname, c.last4, p.last_used_at
FROM cards c LEFT JOIN statement_passwords p ON p.card_id = c.id
UNION ALL
SELECT p.id, p.bank, NULL, NULL, p.last_used_at
FROM statement_passwords p WHERE p.card_id IS NULL
ORDER BY 2, 4
"""
LABEL_QUERY = """
SELECT COALESCE(c.bank, p.bank) AS bank, c.nickname, c.last4
FROM statement_passwords p LEFT JOIN cards c ON c.id = p.card_id
WHERE p.id = ?
"""


@dataclass(frozen=True)
class PasswordRow:
    password_id: int | None  # None: the card has no saved password
    card: str
    saved: bool
    last_used: str


def long_date(ts: int | None) -> str:
    if ts is None:
        return DASH
    d = datetime.fromtimestamp(ts, UTC)
    return f"{d.day} {d:%b %Y}"


def load_password_rows(user_db) -> list[PasswordRow]:
    rows = []
    for r in user_db.execute(ROWS_QUERY):
        saved = r["password_id"] is not None
        rows.append(
            PasswordRow(
                password_id=r["password_id"],
                card=card_label(r["bank"], r["nickname"], r["last4"]),
                saved=saved,
                last_used=long_date(r["last_used_at"]) if saved else DASH,
            )
        )
    return rows


def password_label(user_db, password_id: int) -> str | None:
    r = user_db.execute(LABEL_QUERY, (password_id,)).fetchone()
    if r is None:
        return None
    return card_label(r["bank"], r["nickname"], r["last4"])


def replace_password(user_db, dek: bytes, password_id: int, password: str, *, now: int) -> bool:
    ciphertext, nonce = encrypt_field(dek, password, field=FIELD_STATEMENT_PASSWORD)
    with user_db:
        cur = user_db.execute(
            "UPDATE statement_passwords SET ciphertext = ?, nonce = ?, created_at = ?,"
            " last_used_at = NULL WHERE id = ?",
            (ciphertext, nonce, now, password_id),
        )
    if cur.rowcount == 1:
        logger.info("saved password %d: replaced", password_id)
    return cur.rowcount == 1
