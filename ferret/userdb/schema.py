"""User database schema. Money is integer minor units next to a currency code."""

_CURRENCY = "length(currency) = 3 AND currency = upper(currency)"

_V1 = f"""
CREATE TABLE cards (
    id INTEGER PRIMARY KEY,
    bank TEXT NOT NULL,
    last4 TEXT NOT NULL CHECK (length(last4) = 4),
    currency TEXT NOT NULL CHECK ({_CURRENCY}),
    nickname TEXT,
    UNIQUE (bank, last4)
) STRICT;
CREATE TABLE statement_passwords (
    id INTEGER PRIMARY KEY,
    card_id INTEGER REFERENCES cards(id) ON DELETE CASCADE,
    bank TEXT NOT NULL,
    ciphertext BLOB NOT NULL,
    nonce BLOB NOT NULL,
    created_at INTEGER NOT NULL,
    last_used_at INTEGER
) STRICT;
CREATE UNIQUE INDEX statement_passwords_card ON statement_passwords(card_id)
    WHERE card_id IS NOT NULL;
CREATE UNIQUE INDEX statement_passwords_bank ON statement_passwords(bank)
    WHERE card_id IS NULL;
CREATE TABLE statements (
    id INTEGER PRIMARY KEY,
    card_id INTEGER REFERENCES cards(id),
    bank TEXT,
    period_start TEXT,
    period_end TEXT,
    source TEXT NOT NULL CHECK (source IN ('upload', 'gmail')),
    source_ref TEXT,
    received_at INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('reading', 'needs_password', 'reconciled',
                                           'didnt_add_up', 'unsupported', 'not_a_statement',
                                           'skipped')),
    currency TEXT CHECK (currency IS NULL OR ({_CURRENCY})),
    opening INTEGER,
    closing INTEGER,
    total_debits INTEGER,
    total_credits INTEGER,
    parsed_debits INTEGER,
    parsed_credits INTEGER,
    fingerprint TEXT UNIQUE,
    CHECK (currency IS NOT NULL OR (opening IS NULL AND closing IS NULL AND total_debits IS NULL
           AND total_credits IS NULL AND parsed_debits IS NULL AND parsed_credits IS NULL))
) STRICT;
CREATE TABLE transactions (
    id INTEGER PRIMARY KEY,
    statement_id INTEGER NOT NULL REFERENCES statements(id) ON DELETE CASCADE,
    card_id INTEGER NOT NULL REFERENCES cards(id),
    posted_on TEXT NOT NULL,
    merchant TEXT NOT NULL,
    amount_minor INTEGER NOT NULL CHECK (amount_minor >= 0),
    currency TEXT NOT NULL CHECK ({_CURRENCY}),
    is_credit INTEGER NOT NULL CHECK (is_credit IN (0, 1))
) STRICT;
CREATE INDEX transactions_card_posted ON transactions(card_id, posted_on);
CREATE INDEX transactions_posted ON transactions(posted_on);
CREATE TABLE gmail_account (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    email TEXT NOT NULL,
    refresh_token_ciphertext BLOB NOT NULL,
    nonce BLOB NOT NULL,
    connected_at INTEGER NOT NULL,
    last_checked_at INTEGER,
    status TEXT NOT NULL CHECK (status IN ('connected', 'stopped'))
) STRICT;
CREATE TABLE gmail_seen (
    message_id TEXT PRIMARY KEY,
    seen_at INTEGER NOT NULL
) STRICT;
"""

# Dates (period_start, period_end, posted_on) are TEXT YYYY-MM-DD; timestamps are Unix seconds.
# A statement's currency is NULL only while no amounts are known. Transaction amounts are always
# non-negative; direction is is_credit. gmail_account holds at most one row (id = 1).
MIGRATIONS: list[str] = [_V1]
