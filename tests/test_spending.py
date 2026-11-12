import pytest

from ferret.spending import (
    CurrencyTotal,
    MonthBar,
    SourceSummary,
    StatementCounts,
    card_totals,
    has_statements,
    last_months,
    month_bounds,
    monthly_series,
    months_with_data,
    previous_month,
    source_summary,
    statement_counts,
    top_merchants,
    totals,
    transactions,
)

OCT = "2026-10"


def add_card(db, last4, currency="AED", bank="Emirates NBD", nickname=None):
    cur = db.execute(
        "INSERT INTO cards (bank, last4, currency, nickname) VALUES (?, ?, ?, ?)",
        (bank, last4, currency, nickname),
    )
    return cur.lastrowid


def add_statement(db, card_id, status="reconciled", currency="AED", period_end="2026-10-30"):
    cols = dict(card_id=card_id, bank="Emirates NBD", source="upload", received_at=1, status=status)
    cols["period_end"] = period_end
    if status in ("reconciled", "didnt_add_up"):
        cols.update(currency=currency, opening=0, closing=0)
        cols.update(total_debits=0, total_credits=0, parsed_debits=0, parsed_credits=0)
    names = ", ".join(cols)
    marks = ", ".join("?" for _ in cols)
    cur = db.execute(f"INSERT INTO statements ({names}) VALUES ({marks})", tuple(cols.values()))
    return cur.lastrowid


def add_tx(db, statement_id, card_id, posted_on, merchant, amount_minor, currency="AED", credit=0):
    cur = db.execute(
        "INSERT INTO transactions (statement_id, card_id, posted_on, merchant, amount_minor,"
        " currency, is_credit) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (statement_id, card_id, posted_on, merchant, amount_minor, currency, int(credit)),
    )
    return cur.lastrowid


def simple(db, last4="4821", **kw):
    card = add_card(db, last4, **kw)
    return card, add_statement(db, card)


def test_month_helpers():
    assert month_bounds("2026-10") == ("2026-10-01", "2026-11-01")
    assert month_bounds("2026-12") == ("2026-12-01", "2027-01-01")
    assert previous_month("2026-01") == "2025-12"
    months = last_months("2026-02")
    assert (months[0], months[-1], len(months)) == ("2025-09", "2026-02", 6)
    for bad in ("2026-13", "2026-1"):
        with pytest.raises(ValueError):
            month_bounds(bad)


def test_currencies_are_never_added_together(user):
    db = user.db
    aed, s1 = simple(db)
    inr, s2 = simple(db, "1111", currency="INR")
    add_tx(db, s1, aed, "2026-10-05", "Spinneys", 10000)
    add_tx(db, s2, inr, "2026-10-06", "Big Bazaar", 500000, "INR")
    rows = totals(db, OCT)
    assert [(r.currency, r.spent_minor) for r in rows] == [("AED", 10000), ("INR", 500000)]
    assert all(r.spent_minor != 510000 for r in rows)
    assert list(monthly_series(db, OCT)) == ["AED", "INR"]
    assert [(m.merchant, m.currency) for m in top_merchants(db, OCT)] == [
        ("Spinneys", "AED"),
        ("Big Bazaar", "INR"),
    ]


@pytest.mark.parametrize("status", ["didnt_add_up", "needs_password"])
def test_didnt_add_up_contributes_nothing(user, status):
    db = user.db
    card, good = simple(db)
    bad = add_statement(db, card, status)
    add_tx(db, good, card, "2026-10-05", "Spinneys", 5000)
    add_tx(db, bad, card, "2026-09-05", "Bad Shop", 99900)
    add_tx(db, bad, card, "2026-10-06", "Bad Shop", 99900)
    assert totals(db, OCT) == [CurrencyTotal("AED", 5000, None, 1)]
    assert [c.spent_minor for c in card_totals(db, OCT)] == [5000]
    assert [b.spent_minor for b in monthly_series(db, OCT)["AED"]] == [0, 0, 0, 0, 0, 5000]
    assert [m.merchant for m in top_merchants(db, OCT)] == ["Spinneys"]
    assert [t.merchant for t in transactions(db, OCT)] == ["Spinneys"]
    assert months_with_data(db) == [OCT]


def test_refunds_are_subtracted(user):
    db = user.db
    card, st = simple(db)
    add_tx(db, st, card, "2026-10-05", "Noon", 41275)
    add_tx(db, st, card, "2026-10-07", "Noon", 19900, credit=True)
    (total,) = totals(db, OCT)
    assert (total.spent_minor, total.count) == (21375, 2)
    refund = transactions(db, OCT)[0]
    assert (refund.amount_minor, refund.is_credit) == (-19900, True)
    add_tx(db, st, card, "2026-10-08", "Noon", 50000, credit=True)
    assert totals(db, OCT)[0].spent_minor == -28625


def test_previous_month_comparison(user):
    db = user.db
    aed, s1 = simple(db)
    inr, s2 = simple(db, "1111", currency="INR")
    add_tx(db, s1, aed, "2026-09-10", "A", 689025)
    add_tx(db, s1, aed, "2026-10-10", "A", 734225)
    add_tx(db, s2, inr, "2026-10-10", "B", 1000, "INR")
    by = {t.currency: t for t in totals(db, OCT)}
    assert by["AED"].previous_minor == 689025
    assert by["INR"].previous_minor is None


def test_card_filter_applies_to_every_query(user):
    db = user.db
    a, s1 = simple(db, "1111")
    b, s2 = simple(db, "2222", nickname="Travel")
    add_tx(db, s1, a, "2026-10-05", "One", 100)
    add_tx(db, s2, b, "2026-10-05", "Two", 200)
    assert [t.spent_minor for t in totals(db, OCT, b)] == [200]
    assert [c.card_id for c in card_totals(db, OCT, b)] == [b]
    assert [c.label for c in card_totals(db, OCT)] == ["Travel •• 2222", "Emirates NBD •• 1111"]
    assert monthly_series(db, OCT, b)["AED"][-1] == MonthBar(OCT, 200)
    assert [m.merchant for m in top_merchants(db, OCT, b)] == ["Two"]
    assert [t.merchant for t in transactions(db, OCT, b)] == ["Two"]


def test_monthly_series_fills_zeros(user):
    db = user.db
    card, st = simple(db)
    add_tx(db, st, card, "2026-08-05", "A", 100)
    add_tx(db, st, card, "2026-10-05", "A", 300)
    bars = monthly_series(db, OCT)["AED"]
    assert [b.month for b in bars] == ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09", OCT]
    assert [b.spent_minor for b in bars] == [0, 0, 0, 100, 0, 300]
    assert months_with_data(db) == [OCT, "2026-08"]
    assert monthly_series(db, "2030-01") == {}
    assert totals(db, "2030-01") == card_totals(db, "2030-01") == transactions(db, "2030-01") == []
    assert top_merchants(db, "2030-01") == []


def test_top_merchants_limit_and_net(user):
    db = user.db
    card, st = simple(db)
    for i in range(7):
        add_tx(db, st, card, "2026-10-05", f"M{i}", 1000 * (i + 1))
    add_tx(db, st, card, "2026-10-06", "Refunded", 500)
    add_tx(db, st, card, "2026-10-07", "Refunded", 500, credit=True)
    names = [m.merchant for m in top_merchants(db, OCT)]
    assert names == ["M6", "M5", "M4", "M3", "M2"]


def test_transactions_order_and_paging(user):
    db = user.db
    card, st = simple(db)
    ids = [
        add_tx(db, st, card, "2026-10-01", "a", 1),
        add_tx(db, st, card, "2026-10-09", "b", 1),
        add_tx(db, st, card, "2026-10-09", "c", 1),
        add_tx(db, st, card, "2026-10-03", "d", 1),
        add_tx(db, st, card, "2026-10-02", "e", 1),
    ]
    rows = transactions(db, OCT)
    assert [r.id for r in rows] == [ids[2], ids[1], ids[3], ids[4], ids[0]]
    assert [r.id for r in transactions(db, OCT, limit=2, offset=2)] == [ids[3], ids[4]]


def test_search_by_merchant(user):
    db = user.db
    card, st = simple(db)
    add_tx(db, st, card, "2026-10-05", "Spinneys Jumeirah", 100)
    add_tx(db, st, card, "2026-10-05", "Shop 50 Off", 100)
    assert [t.merchant for t in transactions(db, OCT, query=" spinn ")] == ["Spinneys Jumeirah"]
    assert transactions(db, OCT, query="50%") == []
    assert transactions(db, OCT, query="_") == []
    assert transactions(db, OCT, query="\\") == []


def test_search_by_amount(user):
    db = user.db
    card, st = simple(db)
    add_tx(db, st, card, "2026-10-05", "Noon", 124900)
    add_tx(db, st, card, "2026-10-05", "Other", 41270)
    for q in ("1,249", "1249", "1249.00"):
        assert [t.merchant for t in transactions(db, OCT, query=q)] == ["Noon"]
    assert [t.merchant for t in transactions(db, OCT, query="412.7")] == ["Other"]
    for q in ("1249.5", "1249.555", "-5", "NaN", "1e30", "1e1000000", "abc"):
        assert transactions(db, OCT, query=q) == []


def test_statement_counts(user):
    db = user.db
    assert statement_counts(db, OCT) == StatementCounts(0, 0, 0)
    card = add_card(db, "4821")
    add_statement(db, card)
    add_statement(db, card)
    add_statement(db, card, "didnt_add_up")
    add_statement(db, card, "reconciled", period_end="2026-09-30")
    add_statement(db, card, "needs_password", period_end=None)
    assert statement_counts(db, OCT) == StatementCounts(2, 3, 1)


def test_source_summary_and_has_statements(user):
    db = user.db
    assert not has_statements(db)
    assert source_summary(db) == SourceSummary(0, (), None)
    add_statement(db, None, "needs_password", period_end=None)
    assert has_statements(db)
    a = add_card(db, "1111")
    b = add_card(db, "2222")
    add_statement(db, a)
    add_statement(db, b, period_end="2026-09-30")
    assert source_summary(db) == SourceSummary(2, ("Emirates NBD",), "2026-10-30")
