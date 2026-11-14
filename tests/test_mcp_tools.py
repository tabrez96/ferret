import pytest

from ferret.mcp import tools
from tests.test_spending import add_card, add_statement, add_tx


def seed(db):
    aed = add_card(db, "4821", nickname="Daily")
    inr = add_card(db, "9911", currency="INR", bank="HDFC")
    s_aed = add_statement(db, aed)
    s_inr = add_statement(db, inr, currency="INR")
    add_tx(db, s_aed, aed, "2026-10-05", "Spinneys", 428675)
    add_tx(db, s_aed, aed, "2026-10-10", "Careem", 10000)
    add_tx(db, s_aed, aed, "2026-10-12", "Spinneys", 5000, credit=1)
    add_tx(db, s_aed, aed, "2026-09-20", "Careem", 2500)
    add_tx(db, s_inr, inr, "2026-10-07", "Swiggy", 150000, currency="INR")
    add_tx(db, s_inr, inr, "2026-10-08", "Zomato", 90000, currency="INR")
    return aed, inr


def test_list_cards(user):
    aed, inr = seed(user.db)
    cards = tools.list_cards(user.db)["cards"]
    assert [c["id"] for c in cards] == [aed, inr]
    assert [c["currency"] for c in cards] == ["AED", "INR"]
    assert cards[0]["label"] == "Daily •• 4821"
    assert cards[1]["bank"] == "HDFC" and cards[1]["last4"] == "9911"


def test_list_statements(user):
    aed, _ = seed(user.db)
    pw = add_statement(user.db, aed, status="needs_password")
    user.db.execute("UPDATE statements SET received_at = 86400 * 2 WHERE id = ?", (pw,))
    user.db.execute("UPDATE statements SET total_debits = 428675 WHERE id = 1")
    items = tools.list_statements(user.db)["statements"]
    assert items[0]["id"] == pw
    assert items[0]["status"] == "needs_password"
    assert items[0]["currency"] is None
    assert items[0]["total_debits"] is None and items[0]["total_credits"] is None
    assert items[0]["received_on"] == "1970-01-03"
    first = next(i for i in items if i["id"] == 1)
    assert first["total_debits"] == "4286.75"
    assert first["total_credits"] == "0.00"
    assert [i["id"] for i in items[1:]] == [2, 1]


def test_spending_summary_per_currency(user):
    aed, _ = seed(user.db)
    out = tools.spending_summary(user.db, "2026-10")
    totals = {t["currency"]: t for t in out["totals"]}
    assert totals["AED"]["spent"] == "4336.75"
    assert totals["AED"]["previous_month_spent"] == "25.00"
    assert totals["AED"]["transactions"] == 3
    assert totals["INR"]["spent"] == "2400.00"
    assert totals["INR"]["previous_month_spent"] is None
    assert len(out["by_card"]) == 2
    narrowed = tools.spending_summary(user.db, "2026-10", aed)
    assert [t["currency"] for t in narrowed["totals"]] == ["AED"]
    assert [c["card_id"] for c in narrowed["by_card"]] == [aed]
    assert narrowed["card_id"] == aed


def test_spending_summary_ignores_unreconciled(user):
    aed, _ = seed(user.db)
    bad = add_statement(user.db, aed, status="didnt_add_up")
    add_tx(user.db, bad, aed, "2026-10-15", "Ghost", 999900)
    out = tools.spending_summary(user.db, "2026-10", aed)
    assert out["totals"][0]["spent"] == "4336.75"
    assert tools.search_transactions(user.db, "Ghost")["transactions"] == []


def test_top_merchants_limit(user):
    seed(user.db)
    out = tools.top_merchants(user.db, "2026-10", limit=5)["merchants"]
    assert [(m["currency"], m["merchant"], m["spent"]) for m in out] == [
        ("AED", "Spinneys", "4236.75"),
        ("AED", "Careem", "100.00"),
        ("INR", "Swiggy", "1500.00"),
        ("INR", "Zomato", "900.00"),
    ]
    one = tools.top_merchants(user.db, "2026-10", limit=1)["merchants"]
    assert [(m["currency"], m["merchant"]) for m in one] == [("AED", "Spinneys"), ("INR", "Swiggy")]
    assert len(tools.top_merchants(user.db, "2026-10", limit=0)["merchants"]) == 2


def test_search_transactions(user):
    aed, inr = seed(user.db)
    search = tools.search_transactions
    assert [t["merchant"] for t in search(user.db, "spin")["transactions"]] == [
        "Spinneys",
        "Spinneys",
    ]
    by_amount = search(user.db, "100.00")["transactions"]
    assert [(t["merchant"], t["amount"]) for t in by_amount] == [("Careem", "100.00")]
    both = search(user.db, date_from="2026-10-05", date_to="2026-10-08")["transactions"]
    assert [t["posted_on"] for t in both] == ["2026-10-08", "2026-10-07", "2026-10-05"]
    assert search(user.db, date_from="2026-10-09", date_to="2026-10-01")["transactions"] == []
    assert {t["currency"] for t in search(user.db, card_id=inr)["transactions"]} == {"INR"}
    credit = search(user.db, "spinneys", date_from="2026-10-12")["transactions"][0]
    assert credit["amount"] == "-50.00" and credit["is_credit"] is True
    assert len(search(user.db, limit=0)["transactions"]) == 1
    assert search(user.db, "%")["transactions"] == []


def test_bad_inputs(user):
    seed(user.db)
    with pytest.raises(ValueError, match="month"):
        tools.spending_summary(user.db, "2026-13")
    with pytest.raises(ValueError, match="month"):
        tools.top_merchants(user.db, "Oct")
    with pytest.raises(ValueError, match="bad date"):
        tools.search_transactions(user.db, date_from="yesterday")
    with pytest.raises(ValueError, match="bad date"):
        tools.search_transactions(user.db, date_to="2026-02-30")
    with pytest.raises(ValueError, match="unknown card 99"):
        tools.spending_summary(user.db, "2026-10", 99)
    with pytest.raises(ValueError, match="unknown card 99"):
        tools.search_transactions(user.db, card_id=99)
