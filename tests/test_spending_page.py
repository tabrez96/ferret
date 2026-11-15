from datetime import date

from ferret import spending as sp
from ferret.web import spending_page as vm
from tests.test_spending import add_card, add_statement, add_tx
from tests.test_statements_page import signed_in  # noqa: F401

TODAY = date(2026, 11, 14)


def seed(db, last4="4821", **kw):
    card = add_card(db, last4, **kw)
    return card, add_statement(db, card, currency=kw.get("currency", "AED"))


def test_resolve_month():
    assert vm.resolve_month("2026-09", ["2026-10"], TODAY) == "2026-09"
    assert vm.resolve_month("2026-13", ["2026-10"], TODAY) == "2026-10"
    assert vm.resolve_month("garbage", [], TODAY) == "2026-11"
    assert vm.resolve_month("2026-١٠", ["2026-10"], TODAY) == "2026-10"
    assert vm.resolve_month(None, ["2026-10"], TODAY) == "2026-10"


def test_parse_card():
    assert vm.parse_card("3") == 3
    assert vm.parse_card("") is None
    assert vm.parse_card("x") is None
    assert vm.parse_card("9" * 20) is None
    assert vm.parse_card("²") is None


def test_source_line():
    two = sp.SourceSummary(2, ("Emirates NBD",), "2026-10-30")
    assert vm.source_line(two) == "From 2 Emirates NBD cards · statements up to 30 Oct 2026"
    one = sp.SourceSummary(1, ("Emirates NBD",), "2026-10-05")
    assert vm.source_line(one) == "From 1 Emirates NBD card · statements up to 5 Oct 2026"
    assert vm.source_line(sp.SourceSummary(0, (), None)) == "No reconciled statements yet"


def test_comparison_wording():
    def t(spent, prev, n=2):
        return sp.CurrencyTotal("AED", spent, prev, n)

    assert (
        vm.comparison(t(1500, 1000), "September") == "AED 5.00 more than September · 2 transactions"
    )
    assert (
        vm.comparison(t(1000, 1500), "September") == "AED 5.00 less than September · 2 transactions"
    )
    assert vm.comparison(t(1000, 1000), "September") == "Same as September · 2 transactions"
    assert vm.comparison(t(1000, None, 1), "September") == (
        "Nothing in September to compare · 1 transaction"
    )


def test_chart_geometry():
    months = ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
    series = [sp.MonthBar(m, v) for m, v in zip(months, [100, 0, -50, 1, 50, 25], strict=True)]
    bars = vm.chart("AED", series, "2026-10").bars
    assert (bars[0].height, bars[0].y) == (96, 0)
    assert bars[1].height == 0
    assert bars[2].height == 0
    assert bars[3].height == 2
    assert [b.current for b in bars] == [False] * 5 + [True]
    label = vm.chart("AED", series, "2026-10").aria_label
    assert label.startswith("Spending per month in AED: May 2026 AED 1.00")
    assert "October 2026 AED 0.25" in label


def test_merchant_widths():
    m = sp.MerchantTotal
    rows = vm.merchant_rows([m("A", "AED", 1000), m("B", "AED", 250), m("C", "INR", 40)])
    assert [r.width for r in rows["AED"]] == [100, 25]
    assert rows["INR"][0].width == 100


def test_first_run_page(client, signed_in):  # noqa: F811
    html = client.get("/").text
    assert "Let's find your spending" in html
    assert 'href="/statements#upload"' in html and "Choose a PDF" in html
    assert "Connect Gmail" not in html
    assert "<select" not in html


def test_main_page(client, signed_in):  # noqa: F811
    card, sept = seed(signed_in)
    octo = add_statement(signed_in, card)
    add_tx(signed_in, sept, card, "2026-09-10", "Noon", 100000)
    add_tx(signed_in, octo, card, "2026-10-10", "<b>Spinneys</b>", 150000)
    add_tx(signed_in, octo, card, "2026-10-12", "Amazon refund", 19900, credit=1)
    signed_in.commit()
    html = client.get("/").text
    assert "Spent in October" in html
    assert "AED 1,301.00" in html
    assert "more than September" in html
    assert "Emirates NBD •• 4821" in html
    assert 'role="img"' in html and 'aria-label="Spending per month in AED' in html
    assert '<ol class="merchant-list">' in html
    assert 'chip chip-ok">Refund' in html
    assert 'amount-refund">-AED 199.00' in html
    assert 'class="num' in html
    assert "&lt;b&gt;Spinneys&lt;/b&gt;" in html and "<b>Spinneys" not in html


def test_currencies_never_added(client, signed_in):  # noqa: F811
    aed, s1 = seed(signed_in)
    inr, s2 = seed(signed_in, "9034", currency="INR")
    add_tx(signed_in, s1, aed, "2026-10-10", "Noon", 10000)
    add_tx(signed_in, s2, inr, "2026-10-11", "Zomato", 50000, currency="INR")
    signed_in.commit()
    html = client.get("/").text
    assert "AED 100.00" in html and "INR 500.00" in html
    assert html.count('class="total-amount') == 2
    assert "600.00" not in html


def test_no_statement_month(client, signed_in):  # noqa: F811
    card, st = seed(signed_in)
    add_tx(signed_in, st, card, "2026-10-10", "Noon", 10000)
    signed_in.commit()
    html = client.get("/?month=2026-11").text
    assert "No statement for November yet" in html
    assert 'href="/statements"' in html
    assert "<table" not in html


def test_needs_password_chip(client, signed_in):  # noqa: F811
    card = add_card(signed_in, "1111")
    add_statement(signed_in, card, status="needs_password")
    signed_in.commit()
    html = client.get("/").text
    assert '<a class="chip chip-warn" href="/statements">1 statement needs a password</a>' in html


def test_filters(client, signed_in):  # noqa: F811
    a, s1 = seed(signed_in)
    b, s2 = seed(signed_in, "9034")
    add_tx(signed_in, s1, a, "2026-10-10", "Noon", 10000)
    add_tx(signed_in, s2, b, "2026-10-11", "Zomato", 20000)
    signed_in.commit()
    html = client.get(f"/?card={b}").text
    assert "Zomato" in html and "Noon" not in html
    assert f'value="{b}" selected' in html
    assert 'value="2026-10" selected' in html
    bad = client.get("/?month=bad&card=x")
    assert bad.status_code == 200
    assert 'value="2026-10" selected' in bad.text
    assert client.get("/?month=2026-13").status_code == 200
    assert client.get("/?month=0001-01&card=%C2%B2").status_code == 200
    assert "No statement for October yet" in client.get("/?card=424242").text


def test_first_50_rows(client, signed_in):  # noqa: F811
    card, st = seed(signed_in)
    for i in range(55):
        add_tx(signed_in, st, card, f"2026-10-{i % 28 + 1:02d}", f"Shop {i}", 100)
    signed_in.commit()
    body = client.get("/").text.split("<tbody>")[1]
    assert body.count("<tr>") == 50


def seed_october(db, n, name="Shop {}"):
    card, st = seed(db)
    for i in range(n):
        add_tx(db, st, card, f"2026-10-{i % 28 + 1:02d}", name.format(i), 100 + i)
    db.commit()
    return card


def test_parse_offset():
    assert vm.parse_offset("50") == 50
    for bad in ("", "x", "-5", "9" * 20, "²"):
        assert vm.parse_offset(bad) == 0


def test_tx_page_more_flag(signed_in):  # noqa: F811
    seed_october(signed_in, 51)
    page = vm.tx_page(signed_in, "2026-10", None, "", 0)
    assert page["more"] and len(page["rows"]) == 50 and page["next_offset"] == 50
    assert not vm.tx_page(signed_in, "2026-10", None, "", 1)["more"]


def test_show_more_appends_and_disappears(client, signed_in):  # noqa: F811
    seed_october(signed_in, 120)
    body = client.get("/").text.split("<tbody>")[1]
    assert body.count("<tr>") == 50 and "offset=50" in body
    second = client.get("/transactions/rows?month=2026-10&offset=50").text
    assert second.count("<tr>") == 50
    assert 'class="tx-more-row"' in second and "offset=100" in second
    last = client.get("/transactions/rows?month=2026-10&offset=100").text
    assert last.count("<tr>") == 20 and "Show more" not in last


def test_exactly_50_rows_no_show_more(client, signed_in):  # noqa: F811
    seed_october(signed_in, 50)
    assert "Show more" not in client.get("/").text


def test_search_by_merchant_and_amount(client, signed_in):  # noqa: F811
    card, st = seed(signed_in)
    add_tx(signed_in, st, card, "2026-10-10", "Noon", 41275)
    add_tx(signed_in, st, card, "2026-10-11", "Spinneys", 5000)
    signed_in.commit()
    html = client.get("/transactions?month=2026-10&q=noon").text
    assert "Noon" in html and "Spinneys" not in html
    html = client.get("/transactions?month=2026-10&q=412.75").text
    assert "Noon" in html and "Spinneys" not in html
    full = client.get("/?month=2026-10&q=noon").text
    assert 'value="noon"' in full and "Spinneys" not in full.split("<tbody>")[1]


def test_search_no_results(client, signed_in):  # noqa: F811
    seed_october(signed_in, 3)
    html = client.get("/transactions?month=2026-10&q=xyz").text
    assert 'No transactions match "xyz" in October.' in html
    assert "<table" not in html
    assert client.get("/transactions?month=2026-10").text.strip() != ""


def test_search_escapes_query(client, signed_in):  # noqa: F811
    seed_october(signed_in, 3)
    html = client.get("/transactions", params={"month": "2026-10", "q": "<b>x"}).text
    assert "&lt;b&gt;x" in html and "<b>x" not in html


def test_search_keeps_query_in_show_more(client, signed_in):  # noqa: F811
    seed_october(signed_in, 60)
    assert "q=shop" in client.get("/transactions?month=2026-10&q=shop").text


def test_page_has_search_and_skeleton(client, signed_in):  # noqa: F811
    seed_october(signed_in, 3)
    html = client.get("/").text
    assert 'placeholder="Search merchant or amount"' in html
    assert 'role="search"' in html and 'class="tx-skeleton"' in html
    assert "spinner" not in html


def test_partials_require_sign_in(client):
    assert client.get("/transactions").status_code == 303
    assert client.get("/transactions/rows").status_code == 303


def test_partials_signed_out_htmx_gets_hx_redirect(client):
    for path in ("/transactions", "/transactions/rows"):
        r = client.get(path, headers={"HX-Request": "true"})
        assert r.status_code == 204
        assert r.headers["HX-Redirect"] == "/signin"
