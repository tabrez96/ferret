"""View model for S02: turns ferret.spending figures into what spending.html renders."""

from dataclasses import dataclass
from datetime import date

from ferret import spending as sp
from ferret.history import card_label
from ferret.money import format_amount

CHART_H, BAR_W, BAR_GAP = 96, 28, 14
CHART_PAD = (252 - (6 * BAR_W + 5 * BAR_GAP)) // 2  # 7: centres six bars in the 252-wide viewBox


@dataclass(frozen=True)
class ChartBar:
    label: str  # "Oct"
    x: int
    y: int
    height: int
    current: bool


@dataclass(frozen=True)
class Chart:
    currency: str
    aria_label: str
    bars: list[ChartBar]


@dataclass(frozen=True)
class MerchantRow:
    merchant: str
    amount: str  # format_amount(...)
    width: int  # 2..100, bar length relative to the top merchant in the same currency


def month_label(month: str) -> str:
    return f"{date.fromisoformat(month + '-01'):%B %Y}"


def month_name(month: str) -> str:
    return f"{date.fromisoformat(month + '-01'):%B}"


def short_day(iso: str) -> str:
    return f"{(d := date.fromisoformat(iso)).day} {d:%b}"


def parse_card(raw: str) -> int | None:
    # The length cap keeps huge numbers away from SQLite.
    return int(raw) if raw.isdecimal() and len(raw) <= 9 else None


def resolve_month(raw: str | None, available: list[str], today: date) -> str:
    if raw is not None:
        try:
            sp.month_bounds(raw)
            month_name(raw)
            month_name(sp.previous_month(raw))
            return raw
        except ValueError:
            pass
    return available[0] if available else f"{today:%Y-%m}"


def month_options(available: list[str], today: date, selected: str) -> list[tuple[str, str]]:
    # The current month is always offered so "no statement yet" is reachable.
    values = sorted(set(available) | {f"{today:%Y-%m}", selected}, reverse=True)
    return [(v, month_label(v)) for v in values]


def source_line(summary: sp.SourceSummary) -> str:
    if summary.cards == 0:
        return "No reconciled statements yet"
    n = summary.cards
    d = date.fromisoformat(summary.latest_period_end)
    banks = ", ".join(summary.banks)
    return f"From {n} {banks} card{'' if n == 1 else 's'} · statements up to {d.day} {d:%b %Y}"


def comparison(total: sp.CurrencyTotal, previous_name: str) -> str:
    cur = total.currency
    if total.previous_minor is None:
        text = f"Nothing in {previous_name} to compare"
    else:
        diff = total.spent_minor - total.previous_minor
        if diff > 0:
            text = f"{format_amount(diff, cur)} more than {previous_name}"
        elif diff < 0:
            text = f"{format_amount(-diff, cur)} less than {previous_name}"
        else:
            text = f"Same as {previous_name}"
    n = total.count
    return f"{text} · {n} transaction{'' if n == 1 else 's'}"


def chart(currency: str, series: list[sp.MonthBar], current: str) -> Chart:
    top = max([b.spent_minor for b in series] + [1])
    bars = []
    for i, b in enumerate(series):
        h = max(0, round(b.spent_minor * CHART_H / top))
        if b.spent_minor > 0:
            h = max(h, 2)
        x = CHART_PAD + i * (BAR_W + BAR_GAP)
        bars.append(ChartBar(month_label(b.month)[:3], x, CHART_H - h, h, b.month == current))
    values = ", ".join(
        f"{month_label(b.month)} {format_amount(b.spent_minor, currency)}" for b in series
    )
    return Chart(currency, f"Spending per month in {currency}: {values}", bars)


def merchant_rows(merchants: list[sp.MerchantTotal]) -> dict[str, list[MerchantRow]]:
    tops: dict[str, int] = {}
    grouped: dict[str, list[MerchantRow]] = {}
    for m in merchants:
        top = tops.setdefault(m.currency, max(m.spent_minor, 1))
        width = min(100, max(2, round(m.spent_minor * 100 / top)))
        grouped.setdefault(m.currency, []).append(
            MerchantRow(m.merchant, format_amount(m.spent_minor, m.currency), width)
        )
    return grouped


def card_options(user_db) -> list[tuple[int, str]]:
    rows = user_db.execute("SELECT id, bank, nickname, last4 FROM cards ORDER BY id")
    return [(r["id"], card_label(r["bank"], r["nickname"], r["last4"])) for r in rows]


def build_page(user_db, raw_month: str | None, raw_card: str, today: date) -> dict:
    if not sp.has_statements(user_db):
        return {"state": "first_run"}
    available = sp.months_with_data(user_db)
    month = resolve_month(raw_month, available, today)
    card_id = parse_card(raw_card)
    previous_name = month_name(sp.previous_month(month))
    totals = sp.totals(user_db, month, card_id)
    ctx = {
        "month": month,
        "month_name": month_name(month),
        "months": month_options(available, today, month),
        "cards": card_options(user_db),
        "card_id": card_id,
        "source_line": source_line(sp.source_summary(user_db)),
        "counts": sp.statement_counts(user_db, month),
        "totals": [(t, comparison(t, previous_name)) for t in totals],
    }
    if not totals:
        return {**ctx, "state": "no_statement"}
    return {
        **ctx,
        "state": "main",
        "card_totals": sp.card_totals(user_db, month, card_id),
        "charts": [
            chart(c, s, month) for c, s in sp.monthly_series(user_db, month, card_id).items()
        ],
        "merchants": merchant_rows(sp.top_merchants(user_db, month, card_id)),
        "rows": sp.transactions(user_db, month, card_id),
    }
