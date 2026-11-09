import sqlite3

import pytest
from sqlcipher3 import dbapi2 as sqlcipher

from ferret import keys
from ferret.userdb import UserDbKeyError, open_user_db, user_db_path

UID = "c" * 32


@pytest.fixture
def users_dir(tmp_path):
    return tmp_path / "users"


@pytest.fixture
def db(users_dir, dek):
    conn = open_user_db(users_dir, UID, dek)
    yield conn
    conn.close()


def add_card(conn):
    conn.execute("INSERT INTO cards (id, bank, last4, currency) VALUES (1, 'enbd', '1234', 'AED')")
    conn.execute(
        "INSERT INTO statements (id, source, received_at, status)"
        " VALUES (1, 'upload', 1, 'reading')"
    )


def insert_txn(conn, amount, currency="AED"):
    conn.execute(
        "INSERT INTO transactions (statement_id, card_id, posted_on, merchant, amount_minor,"
        " currency, is_credit) VALUES (1, 1, '2026-01-01', 'm', ?, ?, 0)",
        (amount, currency),
    )


def test_sqlcipher_is_real(db):
    assert db.execute("PRAGMA cipher_version").fetchone()[0]


def test_open_creates_schema(db):
    names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert names == {
        "cards",
        "statement_passwords",
        "statements",
        "transactions",
        "gmail_account",
        "gmail_seen",
    }
    assert db.execute("PRAGMA user_version").fetchone()[0] == 1


def test_file_is_encrypted(users_dir, dek):
    conn = open_user_db(users_dir, UID, dek)
    conn.execute(
        "INSERT INTO cards (bank, last4, currency, nickname)"
        " VALUES ('enbd', '1234', 'AED', 'Findable Nickname')"
    )
    conn.commit()
    conn.close()
    data = user_db_path(users_dir, UID).read_bytes()
    assert data[:16] != b"SQLite format 3\x00"
    assert b"Findable Nickname" not in data


def test_wrong_dek_cannot_open(users_dir, dek):
    open_user_db(users_dir, UID, dek).close()
    with pytest.raises(UserDbKeyError):
        open_user_db(users_dir, UID, keys.new_dek())


def test_plain_sqlite_cannot_open(users_dir, dek):
    open_user_db(users_dir, UID, dek).close()
    plain = sqlite3.connect(user_db_path(users_dir, UID))
    with pytest.raises(sqlite3.DatabaseError):
        plain.execute("SELECT count(*) FROM sqlite_master").fetchone()
    plain.close()


def test_right_dek_reopens_and_reads(users_dir, dek):
    conn = open_user_db(users_dir, UID, dek)
    conn.execute("INSERT INTO cards (bank, last4, currency) VALUES ('enbd', '1234', 'AED')")
    conn.commit()
    conn.close()
    conn = open_user_db(users_dir, UID, dek)
    assert conn.execute("SELECT bank FROM cards").fetchone()["bank"] == "enbd"
    conn.close()


@pytest.mark.parametrize("user_id", ["../etc", "ABC", "a" * 31, "a" * 33, "A" * 32])
def test_invalid_user_id_rejected(users_dir, dek, user_id):
    with pytest.raises(ValueError):
        open_user_db(users_dir, user_id, dek)


def test_transaction_amount_must_be_integer(db):
    add_card(db)
    insert_txn(db, 1250)
    for bad in (12.5, "12.50"):
        with pytest.raises(sqlcipher.IntegrityError):
            insert_txn(db, bad)
    with pytest.raises(sqlcipher.IntegrityError):
        insert_txn(db, -1)
    with pytest.raises(sqlcipher.IntegrityError):
        insert_txn(db, 100, None)
    with pytest.raises(sqlcipher.IntegrityError):
        insert_txn(db, 100, "aed")


def test_statement_amounts_require_currency(db):
    sql = (
        "INSERT INTO statements (source, received_at, status, currency, opening)"
        " VALUES ('upload', 1, 'reconciled', ?, 100)"
    )
    with pytest.raises(sqlcipher.IntegrityError):
        db.execute(sql, (None,))
    db.execute(sql, ("AED",))


def test_statement_password_stored_encrypted(db, dek):
    field = keys.FIELD_STATEMENT_PASSWORD
    ciphertext, nonce = keys.encrypt_field(dek, "hunter2", field=field)
    db.execute(
        "INSERT INTO statement_passwords (bank, ciphertext, nonce, created_at)"
        " VALUES ('enbd', ?, ?, 1)",
        (ciphertext, nonce),
    )
    row = db.execute("SELECT ciphertext, nonce FROM statement_passwords").fetchone()
    assert keys.decrypt_field(dek, row["ciphertext"], row["nonce"], field=field) == "hunter2"


def test_gmail_account_single_row(db):
    sql = (
        "INSERT INTO gmail_account (id, email, refresh_token_ciphertext, nonce, connected_at,"
        " status) VALUES (?, 'a@example.com', x'00', x'00', 1, 'connected')"
    )
    db.execute(sql, (1,))
    with pytest.raises(sqlcipher.IntegrityError):
        db.execute(sql, (2,))
