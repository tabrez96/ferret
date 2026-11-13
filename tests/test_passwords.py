from datetime import UTC, datetime

from ferret.history import DASH
from ferret.passwords import load_password_rows, replace_password
from ferret.pipeline.locked import save_password

T0 = int(datetime(2026, 10, 29, 12, tzinfo=UTC).timestamp())


def add_card(db, bank, last4):
    with db:
        return db.execute(
            "INSERT INTO cards (bank, last4, currency) VALUES (?, ?, 'AED')", (bank, last4)
        ).lastrowid


def stored(db, password_id):
    return db.execute(
        "SELECT ciphertext, nonce, last_used_at FROM statement_passwords WHERE id = ?",
        (password_id,),
    ).fetchone()


def test_rows_one_per_card_saved_and_not_saved(user):
    a, b, c = (add_card(user.db, "Emirates NBD", n) for n in ("4821", "9034", "1177"))
    save_password(user.db, user.dek, bank="Emirates NBD", card_id=a, password="a", now=T0)
    save_password(user.db, user.dek, bank="Emirates NBD", card_id=b, password="b", now=T0)
    rows = load_password_rows(user.db)
    assert [r.card for r in rows] == [f"Emirates NBD •• {n}" for n in ("1177", "4821", "9034")]
    assert [r.saved for r in rows] == [False, True, True]
    assert [r.last_used for r in rows] == [DASH, "29 Oct 2026", "29 Oct 2026"]
    assert rows[0].password_id is None


def test_bank_level_password_listed(user):
    save_password(user.db, user.dek, bank="Emirates NBD", card_id=None, password="x", now=T0)
    (row,) = load_password_rows(user.db)
    assert row.card == "Emirates NBD" and row.saved


def test_no_cards_no_rows(user):
    assert load_password_rows(user.db) == []


def test_replace_clears_last_used_and_rejects_unknown_id(user):
    card = add_card(user.db, "Emirates NBD", "4821")
    save_password(user.db, user.dek, bank="Emirates NBD", card_id=card, password="old", now=T0)
    pid = load_password_rows(user.db)[0].password_id
    assert replace_password(user.db, user.dek, pid, "New-Secret", now=T0 + 5) is True
    assert stored(user.db, pid)["last_used_at"] is None
    assert replace_password(user.db, user.dek, 999, "x", now=T0) is False
