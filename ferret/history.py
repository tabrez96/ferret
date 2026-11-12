"""Statement history rows for S03, ready to render."""

from dataclasses import dataclass
from datetime import UTC, date, datetime

from ferret.money import format_amount
from ferret.pending import pending_deadline

# status -> (chip word, tone). Tone maps to CSS class chip-<tone>.
CHIPS: dict[str, tuple[str, str]] = {
    "reconciled": ("Reconciled", "ok"),
    "needs_password": ("Needs password", "warn"),
    "reading": ("Reading…", "neutral"),
    "didnt_add_up": ("Didn't add up", "danger"),
    "unsupported": ("Bank not supported yet", "neutral"),
    "not_a_statement": ("Not a statement", "neutral"),
    "skipped": ("Skipped", "neutral"),
}
SKIPPED_NOTE = "Skipped: upload or re-fetch from Gmail to try again"
DASH = "—"

QUERY = """
SELECT s.id, s.status, s.source, s.received_at, s.bank, s.period_end, s.currency,
       s.total_debits, c.last4, c.nickname
FROM statements s LEFT JOIN cards c ON c.id = s.card_id
ORDER BY s.received_at DESC, s.id DESC
"""


@dataclass(frozen=True)
class HistoryRow:
    id: int
    status: str
    month: str
    card: str
    source: str
    chip_label: str
    chip_tone: str
    note: str | None
    spent: str


def short_date(ts: int) -> str:
    d = datetime.fromtimestamp(ts, UTC)
    return f"{d.day} {d:%b}"


def month_label(period_end: str | None) -> str:
    if period_end is None:
        return DASH
    return f"{date.fromisoformat(period_end):%b %Y}"


def card_label(bank: str | None, nickname: str | None, last4: str | None) -> str:
    if last4:
        return f"{nickname or bank} •• {last4}"
    return bank or DASH


def to_row(row) -> HistoryRow:
    status = row["status"]
    label, tone = CHIPS.get(status, (status, "neutral"))
    note = None
    if status == "needs_password":
        note = f"Waiting until {short_date(pending_deadline(row['received_at']))}"
    elif status == "skipped":
        note = SKIPPED_NOTE
    if status == "reconciled" and row["currency"] is not None:
        spent = format_amount(row["total_debits"], row["currency"])
    elif status == "didnt_add_up":
        spent = "Not saved"
    else:
        spent = DASH
    origin = "Gmail" if row["source"] == "gmail" else "Upload"
    return HistoryRow(
        id=row["id"],
        status=status,
        month=month_label(row["period_end"]),
        card=card_label(row["bank"], row["nickname"], row["last4"]),
        source=f"{origin} · {short_date(row['received_at'])}",
        chip_label=label,
        chip_tone=tone,
        note=note,
        spent=spent,
    )


def load_history(user_db) -> list[HistoryRow]:
    return [to_row(r) for r in user_db.execute(QUERY).fetchall()]
