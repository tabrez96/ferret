"""Spending figures for S02. Only reconciled statements count; currencies are never mixed."""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from ferret.history import card_label
from ferret.money import MINOR_UNITS, to_minor

SIGNED = "CASE WHEN t.is_credit THEN -t.amount_minor ELSE t.amount_minor END"
FROM_RECONCILED = (
    "FROM transactions t JOIN statements s ON s.id = t.statement_id AND s.status = 'reconciled'"
)
_MONTH = re.compile(r"\d{4}-\d{2}")
_MAX_INT = 2**63 - 1


@dataclass(frozen=True)
class CurrencyTotal:
    currency: str
    spent_minor: int
    previous_minor: int | None
    count: int


@dataclass(frozen=True)
class CardTotal:
    card_id: int
    label: str
    currency: str
    spent_minor: int


@dataclass(frozen=True)
class MonthBar:
    month: str
    spent_minor: int


@dataclass(frozen=True)
class MerchantTotal:
    merchant: str
    currency: str
    spent_minor: int


@dataclass(frozen=True)
class TxRow:
    id: int
    posted_on: str
    merchant: str
    card: str
    currency: str
    amount_minor: int  # signed: negative for credits and refunds
    is_credit: bool


@dataclass(frozen=True)
class StatementCounts:
    reconciled: int
    total: int
    needs_password: int


@dataclass(frozen=True)
class SourceSummary:
    cards: int
    banks: tuple[str, ...]
    latest_period_end: str | None


def month_bounds(month: str) -> tuple[str, str]:
    if not _MONTH.fullmatch(month):
        raise ValueError(f"bad month {month!r}")
    year, mon = int(month[:4]), int(month[5:])
    start = date(year, mon, 1)  # raises ValueError for month 0 or 13
    end = date(year + (mon == 12), mon % 12 + 1, 1)
    return start.isoformat(), end.isoformat()


def previous_month(month: str) -> str:
    start, _ = month_bounds(month)
    year, mon = int(start[:4]), int(start[5:7])
    return f"{year - (mon == 1)}-{(mon - 2) % 12 + 1:02d}"


def last_months(month: str, n: int = 6) -> list[str]:
    month_bounds(month)
    months = [month]
    for _ in range(n - 1):
        months.append(previous_month(months[-1]))
    return months[::-1]


def _where(month: str, card_id: int | None) -> tuple[str, list]:
    start, end = month_bounds(month)
    sql = "t.posted_on >= ? AND t.posted_on < ?"
    params: list = [start, end]
    if card_id is not None:
        sql += " AND t.card_id = ?"
        params.append(card_id)
    return sql, params


def totals(user_db, month: str, card_id: int | None = None) -> list[CurrencyTotal]:
    where, params = _where(month, card_id)
    rows = user_db.execute(
        f"SELECT t.currency, SUM({SIGNED}) AS spent, COUNT(*) AS n {FROM_RECONCILED} "
        f"WHERE {where} GROUP BY t.currency ORDER BY t.currency",
        params,
    ).fetchall()
    where, params = _where(previous_month(month), card_id)
    previous = {
        r["currency"]: r["spent"]
        for r in user_db.execute(
            f"SELECT t.currency, SUM({SIGNED}) AS spent {FROM_RECONCILED} "
            f"WHERE {where} GROUP BY t.currency",
            params,
        )
    }
    return [
        CurrencyTotal(r["currency"], r["spent"], previous.get(r["currency"]), r["n"]) for r in rows
    ]


def card_totals(user_db, month: str, card_id: int | None = None) -> list[CardTotal]:
    where, params = _where(month, card_id)
    rows = user_db.execute(
        f"SELECT t.card_id, c.bank, c.nickname, c.last4, t.currency, SUM({SIGNED}) AS spent "
        f"{FROM_RECONCILED} JOIN cards c ON c.id = t.card_id WHERE {where} "
        "GROUP BY t.card_id, t.currency ORDER BY spent DESC, t.card_id",
        params,
    ).fetchall()
    return [
        CardTotal(
            r["card_id"],
            card_label(r["bank"], r["nickname"], r["last4"]),
            r["currency"],
            r["spent"],
        )
        for r in rows
    ]


def monthly_series(
    user_db, month: str, card_id: int | None = None, n: int = 6
) -> dict[str, list[MonthBar]]:
    months = last_months(month, n)
    where, params = _where(month, card_id)
    params[0] = month_bounds(months[0])[0]
    rows = user_db.execute(
        f"SELECT t.currency, substr(t.posted_on, 1, 7) AS m, SUM({SIGNED}) AS spent "
        f"{FROM_RECONCILED} WHERE {where} GROUP BY t.currency, m",
        params,
    ).fetchall()
    sums = {(r["currency"], r["m"]): r["spent"] for r in rows}
    return {
        currency: [MonthBar(m, sums.get((currency, m), 0)) for m in months]
        for currency in sorted({r["currency"] for r in rows})
    }


def top_merchants(
    user_db, month: str, card_id: int | None = None, limit: int = 5
) -> list[MerchantTotal]:
    where, params = _where(month, card_id)
    rows = user_db.execute(
        "SELECT currency, merchant, spent FROM ("
        f"SELECT t.currency, t.merchant, SUM({SIGNED}) AS spent, "
        f"ROW_NUMBER() OVER (PARTITION BY t.currency ORDER BY SUM({SIGNED}) DESC, t.merchant) "
        f"AS rn {FROM_RECONCILED} WHERE {where} "
        "GROUP BY t.currency, t.merchant HAVING spent > 0"
        ") WHERE rn <= ? ORDER BY currency, spent DESC, merchant",
        [*params, limit],
    ).fetchall()
    return [MerchantTotal(r["merchant"], r["currency"], r["spent"]) for r in rows]


def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _amount_matches(query: str) -> list[tuple[str, int]]:
    try:
        value = Decimal(query.replace(",", ""))
    except InvalidOperation:
        return []
    if not value.is_finite() or not 0 <= value <= _MAX_INT:
        return []
    matches = []
    for currency in MINOR_UNITS:
        try:
            minor = to_minor(value, currency)
        except ValueError:
            continue
        if minor <= _MAX_INT:
            matches.append((currency, minor))
    return matches


def transactions(
    user_db,
    month: str,
    card_id: int | None = None,
    query: str = "",
    limit: int = 50,
    offset: int = 0,
) -> list[TxRow]:
    where, params = _where(month, card_id)
    query = query.strip()
    if query:
        clauses = ["t.merchant LIKE ? ESCAPE '\\'"]
        params.append(_like(query))
        for currency, minor in _amount_matches(query):
            clauses.append("(t.currency = ? AND t.amount_minor = ?)")
            params += [currency, minor]
        where += " AND (" + " OR ".join(clauses) + ")"
    rows = user_db.execute(
        "SELECT t.id, t.posted_on, t.merchant, t.currency, t.amount_minor, t.is_credit, "
        f"c.bank, c.nickname, c.last4 {FROM_RECONCILED} JOIN cards c ON c.id = t.card_id "
        f"WHERE {where} ORDER BY t.posted_on DESC, t.id DESC LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ).fetchall()
    return [_tx_row(r) for r in rows]


def search_transactions(
    user_db,
    query: str = "",
    date_from: str | None = None,
    date_to: str | None = None,
    card_id: int | None = None,
    limit: int = 50,
) -> list[TxRow]:
    where, params = "1 = 1", []
    for bound, op in ((date_from, ">="), (date_to, "<=")):
        if bound is not None:
            try:
                date.fromisoformat(bound)
            except ValueError:
                raise ValueError(f"bad date {bound!r}") from None
            where += f" AND t.posted_on {op} ?"
            params.append(bound)
    if card_id is not None:
        where += " AND t.card_id = ?"
        params.append(card_id)
    query = query.strip()
    if query:
        clauses = ["t.merchant LIKE ? ESCAPE '\\'"]
        params.append(_like(query))
        for currency, minor in _amount_matches(query):
            clauses.append("(t.currency = ? AND t.amount_minor = ?)")
            params += [currency, minor]
        where += " AND (" + " OR ".join(clauses) + ")"
    rows = user_db.execute(
        "SELECT t.id, t.posted_on, t.merchant, t.currency, t.amount_minor, t.is_credit, "
        f"c.bank, c.nickname, c.last4 {FROM_RECONCILED} JOIN cards c ON c.id = t.card_id "
        f"WHERE {where} ORDER BY t.posted_on DESC, t.id DESC LIMIT ?",
        [*params, limit],
    ).fetchall()
    return [_tx_row(r) for r in rows]


def _tx_row(r) -> TxRow:
    return TxRow(
        r["id"],
        r["posted_on"],
        r["merchant"],
        card_label(r["bank"], r["nickname"], r["last4"]),
        r["currency"],
        -r["amount_minor"] if r["is_credit"] else r["amount_minor"],
        bool(r["is_credit"]),
    )


def months_with_data(user_db) -> list[str]:
    rows = user_db.execute(
        f"SELECT DISTINCT substr(t.posted_on, 1, 7) AS m {FROM_RECONCILED} ORDER BY 1 DESC"
    )
    return [r["m"] for r in rows]


def statement_counts(user_db, month: str) -> StatementCounts:
    start, end = month_bounds(month)
    row = user_db.execute(
        "SELECT "
        "COALESCE(SUM(status = 'reconciled' AND period_end >= ? AND period_end < ?), 0) AS rec, "
        "COALESCE(SUM(status IN ('reconciled', 'didnt_add_up') "
        "AND period_end >= ? AND period_end < ?), 0) AS total, "
        "COALESCE(SUM(status = 'needs_password'), 0) AS pw FROM statements",
        (start, end, start, end),
    ).fetchone()
    return StatementCounts(row["rec"], row["total"], row["pw"])


def source_summary(user_db) -> SourceSummary:
    row = user_db.execute(
        "SELECT COUNT(DISTINCT card_id) AS cards, MAX(period_end) AS latest "
        "FROM statements WHERE status = 'reconciled'"
    ).fetchone()
    banks = user_db.execute(
        "SELECT DISTINCT bank FROM statements WHERE status = 'reconciled' AND bank IS NOT NULL "
        "ORDER BY bank"
    )
    return SourceSummary(row["cards"], tuple(r["bank"] for r in banks), row["latest"])


def has_statements(user_db) -> bool:
    return user_db.execute("SELECT 1 FROM statements LIMIT 1").fetchone() is not None
