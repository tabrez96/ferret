from datetime import UTC, datetime

from ferret.history import CHIPS, DASH, SKIPPED_NOTE, load_history, month_label, short_date, to_row

STATUSES = set(
    "reading needs_password reconciled didnt_add_up unsupported not_a_statement skipped".split()
)


def ts(y, m, d, h=12):
    return int(datetime(y, m, d, h, tzinfo=UTC).timestamp())


def add(db, status="reconciled", received_at=None, source="gmail", card_id=None, **cols):
    cols.update(status=status, source=source, received_at=received_at or ts(2026, 10, 29))
    cols["card_id"] = card_id
    names = ", ".join(cols)
    marks = ", ".join("?" for _ in cols)
    cur = db.execute(f"INSERT INTO statements ({names}) VALUES ({marks})", tuple(cols.values()))
    db.commit()
    return cur.lastrowid


def add_card(db, last4="4821", nickname=None):
    cur = db.execute(
        "INSERT INTO cards (bank, last4, currency, nickname) VALUES (?, ?, ?, ?)",
        ("Emirates NBD", last4, "AED", nickname),
    )
    return cur.lastrowid


def test_short_date_and_month_label():
    assert short_date(ts(2026, 11, 7)) == "7 Nov"
    assert month_label("2026-10-31") == "Oct 2026"
    assert month_label(None) == DASH


def test_every_status_has_a_word():
    assert set(CHIPS) == STATUSES
    for word, tone in CHIPS.values():
        assert word
        assert tone in {"ok", "warn", "danger", "neutral"}


def test_unknown_status_falls_back(user):
    row = dict(id=1, status="weird", source="upload", received_at=ts(2026, 10, 1))
    row.update(bank=None, period_end=None, currency=None, nickname=None, last4=None)
    out = to_row(row)
    assert (out.chip_label, out.chip_tone) == ("weird", "neutral")


def test_needs_password_waiting_until(user):
    add(user.db, "needs_password", received_at=ts(2026, 10, 31))
    (row,) = load_history(user.db)
    assert (row.note, row.spent, row.month, row.card) == ("Waiting until 7 Nov", DASH, DASH, DASH)


def test_reconciled_row(user):
    card = add_card(user.db)
    add(
        user.db,
        card_id=card,
        bank="Emirates NBD",
        period_end="2026-10-31",
        currency="AED",
        total_debits=428675,
    )
    (row,) = load_history(user.db)
    assert row.card == "Emirates NBD •• 4821"
    assert row.spent == "AED 4,286.75"
    assert row.month == "Oct 2026"
    assert row.source == "Gmail · 29 Oct"


def test_nickname_replaces_bank(user):
    card = add_card(user.db, nickname="Travel")
    add(user.db, card_id=card, bank="Emirates NBD")
    assert load_history(user.db)[0].card == "Travel •• 4821"


def test_didnt_add_up_row(user):
    add(user.db, "didnt_add_up", bank="Emirates NBD")
    row = load_history(user.db)[0]
    assert (row.spent, row.card) == ("Not saved", "Emirates NBD")


def test_skipped_note(user):
    add(user.db, "skipped")
    assert load_history(user.db)[0].note == SKIPPED_NOTE


def test_order_newest_first(user):
    old = add(user.db, received_at=ts(2026, 9, 1))
    new = add(user.db, received_at=ts(2026, 11, 1))
    mid = add(user.db, received_at=ts(2026, 10, 1))
    assert [r.id for r in load_history(user.db)] == [new, mid, old]
