"""Read-only tool functions for the MCP server. Amounts are decimal strings next to a currency."""

from datetime import UTC, datetime

from ferret import spending
from ferret.history import card_label
from ferret.money import from_minor


def _amount(minor: int, currency: str) -> str:
    return str(from_minor(minor, currency))


def _check_card(db, card_id: int | None) -> None:
    if card_id is None:
        return
    if db.execute("SELECT 1 FROM cards WHERE id = ?", (card_id,)).fetchone() is None:
        raise ValueError(f"unknown card {card_id}")


def list_cards(db) -> dict:
    rows = db.execute(
        "SELECT id, bank, last4, nickname, currency FROM cards ORDER BY id"
    ).fetchall()
    return {
        "cards": [
            {
                "id": r["id"],
                "bank": r["bank"],
                "last4": r["last4"],
                "nickname": r["nickname"],
                "currency": r["currency"],
                "label": card_label(r["bank"], r["nickname"], r["last4"]),
            }
            for r in rows
        ]
    }


def list_statements(db) -> dict:
    rows = db.execute(
        "SELECT s.id, s.card_id, s.bank, s.status, s.source, s.received_at, s.period_start, "
        "s.period_end, s.currency, s.total_debits, s.total_credits, "
        "c.bank AS card_bank, c.nickname, c.last4 "
        "FROM statements s JOIN cards c ON c.id = s.card_id "
        "ORDER BY s.received_at DESC, s.id DESC"
    ).fetchall()

    def money(minor, currency):
        return None if currency is None or minor is None else _amount(minor, currency)

    return {
        "statements": [
            {
                "id": r["id"],
                "card_id": r["card_id"],
                "card": card_label(r["card_bank"], r["nickname"], r["last4"]),
                "bank": r["bank"],
                "status": r["status"],
                "source": r["source"],
                "received_on": datetime.fromtimestamp(r["received_at"], UTC).date().isoformat(),
                "period_start": r["period_start"],
                "period_end": r["period_end"],
                "currency": r["currency"],
                "total_debits": money(r["total_debits"], r["currency"]),
                "total_credits": money(r["total_credits"], r["currency"]),
            }
            for r in rows
        ]
    }


def spending_summary(db, month: str, card_id: int | None = None) -> dict:
    spending.month_bounds(month)
    _check_card(db, card_id)
    return {
        "month": month,
        "card_id": card_id,
        "totals": [
            {
                "currency": t.currency,
                "spent": _amount(t.spent_minor, t.currency),
                "previous_month_spent": (
                    None if t.previous_minor is None else _amount(t.previous_minor, t.currency)
                ),
                "transactions": t.count,
            }
            for t in spending.totals(db, month, card_id)
        ],
        "by_card": [
            {
                "card_id": c.card_id,
                "label": c.label,
                "currency": c.currency,
                "spent": _amount(c.spent_minor, c.currency),
            }
            for c in spending.card_totals(db, month, card_id)
        ],
        "note": "Only reconciled statements are counted.",
    }


def top_merchants(db, month: str, card_id: int | None = None, limit: int = 5) -> dict:
    spending.month_bounds(month)
    _check_card(db, card_id)
    limit = max(1, min(limit, 50))
    return {
        "month": month,
        "card_id": card_id,
        "merchants": [
            {
                "merchant": m.merchant,
                "currency": m.currency,
                "spent": _amount(m.spent_minor, m.currency),
            }
            for m in spending.top_merchants(db, month, card_id, limit)
        ],
    }


def search_transactions(
    db,
    query: str = "",
    date_from: str | None = None,
    date_to: str | None = None,
    card_id: int | None = None,
    limit: int = 50,
) -> dict:
    _check_card(db, card_id)
    limit = max(1, min(limit, 200))
    rows = spending.search_transactions(db, query, date_from, date_to, card_id, limit)
    return {
        "transactions": [
            {
                "id": t.id,
                "posted_on": t.posted_on,
                "merchant": t.merchant,
                "card": t.card,
                "currency": t.currency,
                "amount": _amount(t.amount_minor, t.currency),
                "is_credit": t.is_credit,
            }
            for t in rows
        ]
    }
