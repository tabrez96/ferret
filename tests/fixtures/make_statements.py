"""Invented Emirates NBD-layout statements for tests. Nothing here is real data."""

import io
import random
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from ferret.parsers.base import ParsedStatement, ParsedTransaction
from tests.fixtures.pdfs import encrypt_pdf, make_pdf

BANK = "Emirates NBD"
OTHER_BANK = "Northwind Bank"  # invented; no parser will ever detect it
LOCKED_PASSWORD = "fixture-pass-0062"  # invented
CASES = (
    "aug_2026",
    "sep_2026",
    "oct_2026_multipage",
    "locked",
    "unbalanced",
    "not_a_statement",
    "unsupported_bank",
)
MERCHANTS = (
    "Palm Grove Grocers",
    "Blue Dune Cafe",
    "Marina Bookhouse",
    "Falcon Fuel Station",
    "Cedar Pharmacy",
    "Harbor Cinema",
    "Saffron Lane Bistro",
    "Coral Gym",
    "Oasis Mobile Recharge",
    "Pearl Laundry",
)
PAYMENT = "Payment received, thank you"
FIRST_PAGE_ROWS = 30
NEXT_PAGE_ROWS = 40
LEFT = 72
RIGHT = 523


@dataclass(frozen=True)
class StatementFixture:
    name: str
    path: Path
    password: str | None  # needed to open the file; None when not encrypted
    expected: ParsedStatement | None  # what a correct Emirates NBD parser returns; None if not one
    reconciles: bool  # reconcile(expected).ok


def _t(day: date, merchant: str, amount: str, credit: bool = False) -> ParsedTransaction:
    return ParsedTransaction(day, merchant, Decimal(amount), credit)


def _statement(
    card_last4: str, start: date, end: date, opening: str, txns, *, bank: str = BANK
) -> ParsedStatement:
    total_debits = sum((t.amount for t in txns if not t.is_credit), Decimal("0.00"))
    total_credits = sum((t.amount for t in txns if t.is_credit), Decimal("0.00"))
    return ParsedStatement(
        bank=bank,
        card_last4=card_last4,
        currency="AED",
        period_start=start,
        period_end=end,
        opening=Decimal(opening),
        closing=Decimal(opening) + total_debits - total_credits,
        total_debits=total_debits,
        total_credits=total_credits,
        transactions=tuple(txns),
    )


def _money(amount: Decimal) -> str:
    return f"{amount:,.2f}"


def _dmy(d: date) -> str:
    return d.strftime("%d/%m/%Y")


AUG_2026 = _statement(
    "4821",
    date(2026, 8, 1),
    date(2026, 8, 31),
    "1250.00",
    [
        _t(date(2026, 8, 3), "Palm Grove Grocers", "312.45"),
        _t(date(2026, 8, 5), "Blue Dune Cafe", "38.00"),
        _t(date(2026, 8, 9), "Marina Bookhouse", "129.99"),
        _t(date(2026, 8, 12), PAYMENT, "1250.00", True),
        _t(date(2026, 8, 18), "Falcon Fuel Station", "95.20"),
        _t(date(2026, 8, 25), "Cedar Pharmacy", "64.75"),
    ],
)

SEP_2026 = _statement(
    "4821",
    date(2026, 9, 1),
    date(2026, 9, 30),
    str(AUG_2026.closing),
    [
        _t(date(2026, 9, 2), "Harbor Cinema", "90.00"),
        _t(date(2026, 9, 4), "Saffron Lane Bistro", "245.60"),
        _t(date(2026, 9, 7), "Refund - Marina Bookhouse", "129.99", True),
        _t(date(2026, 9, 11), "Coral Gym", "1050.00"),
        _t(date(2026, 9, 15), PAYMENT, "640.39", True),
        _t(date(2026, 9, 20), "Late payment fee", "230.00"),
        _t(date(2026, 9, 20), "VAT on late payment fee", "11.50"),
        _t(date(2026, 9, 27), "Foreign transaction fee", "4.48"),
    ],
)


def _multipage() -> ParsedStatement:
    rng = random.Random(62)
    days = sorted(rng.randint(1, 31) for _ in range(45))
    txns = []
    for i, day in enumerate(days):
        merchant = rng.choice(MERCHANTS)
        amount = Decimal(rng.randint(500, 99_999)).scaleb(-2)  # 5.00 .. 999.99, two decimals
        if i % 9 == 8:
            txns.append(
                ParsedTransaction(date(2026, 10, day), f"Refund - {merchant}", amount, True)
            )
        else:
            txns.append(ParsedTransaction(date(2026, 10, day), merchant, amount, False))
    return _statement("7305", date(2026, 10, 1), date(2026, 10, 31), "0.00", txns)


OCT_2026 = _multipage()

JUL_2026_TRUE = _statement(
    "4821",
    date(2026, 7, 1),
    date(2026, 7, 31),
    "1000.00",
    [
        _t(date(2026, 7, 6), "Oasis Mobile Recharge", "50.00"),
        _t(date(2026, 7, 14), "Pearl Laundry", "42.25"),
        _t(date(2026, 7, 22), PAYMENT, "500.00", True),
    ],
)
# The printed closing balance is 10.00 too high; printed totals still match the rows.
UNBALANCED = replace(JUL_2026_TRUE, closing=JUL_2026_TRUE.closing + Decimal("10.00"))

LAYLA = "Layla Example"
OMAR = "Omar Sample"


def _pages(rows: tuple[ParsedTransaction, ...]) -> list[tuple[ParsedTransaction, ...]]:
    pages = [rows[:FIRST_PAGE_ROWS]]
    rest = rows[FIRST_PAGE_ROWS:]
    pages += [rest[i : i + NEXT_PAGE_ROWS] for i in range(0, len(rest), NEXT_PAGE_ROWS)]
    return pages


def draw_statement(statement: ParsedStatement, holder: str) -> bytes:
    buf = io.BytesIO()
    page = canvas.Canvas(buf, pagesize=A4, invariant=1)
    pages = _pages(statement.transactions)
    currency = statement.currency

    def header(y: int) -> None:
        page.setFont("Helvetica-Bold", 10)
        page.drawString(LEFT, y, "Transaction date")
        page.drawString(162, y, "Posting date")
        page.drawString(252, y, "Description")
        page.drawRightString(RIGHT, y, f"Amount ({currency})")
        page.setFont("Helvetica", 10)

    for number, rows in enumerate(pages, start=1):
        page.setFont("Helvetica-Bold", 16)
        page.drawString(LEFT, 800, statement.bank)
        page.setFont("Helvetica", 11)
        if number == 1:
            page.drawString(LEFT, 780, "Credit Card Statement")
            page.setFont("Helvetica", 10)
            page.drawString(LEFT, 752, f"Card holder: {holder}")
            page.drawString(LEFT, 738, f"Card number: XXXX XXXX XXXX {statement.card_last4}")
            period = f"{_dmy(statement.period_start)} to {_dmy(statement.period_end)}"
            page.drawString(LEFT, 724, f"Statement period: {period}")
            page.drawString(LEFT, 710, f"Currency: {currency}")
            summary = (
                (682, "Previous balance", statement.opening),
                (668, "Purchases and charges", statement.total_debits),
                (654, "Payments and credits", statement.total_credits),
                (640, "Closing balance", statement.closing),
            )
            for y, label, value in summary:
                page.drawString(LEFT, y, label)
                page.drawRightString(RIGHT, y, _money(value))
            header(610)
            y = 592
        else:
            page.drawString(LEFT, 780, "Credit Card Statement (continued)")
            page.setFont("Helvetica", 10)
            header(750)
            y = 732
        for txn in rows:
            page.drawString(LEFT, y, _dmy(txn.posted_on - timedelta(days=1)))
            page.drawString(162, y, _dmy(txn.posted_on))
            page.drawString(252, y, txn.merchant)
            page.drawRightString(RIGHT, y, _money(txn.amount) + (" CR" if txn.is_credit else ""))
            y -= 16
        page.setFont("Helvetica", 9)
        page.drawString(LEFT, 40, f"Page {number} of {len(pages)}")
        page.showPage()
    page.save()
    return buf.getvalue()


def make_statements(directory: Path) -> dict[str, StatementFixture]:
    directory.mkdir(parents=True, exist_ok=True)
    sep = draw_statement(SEP_2026, LAYLA)
    garden = [
        "Community Garden Newsletter",
        "Planting day is Saturday at 9:00.",
        "Bring gloves and water.",
    ]
    # name -> (bytes, password, expected, reconciles)
    spec = {
        "aug_2026": (draw_statement(AUG_2026, LAYLA), None, AUG_2026, True),
        "sep_2026": (sep, None, SEP_2026, True),
        "oct_2026_multipage": (draw_statement(OCT_2026, OMAR), None, OCT_2026, True),
        "locked": (encrypt_pdf(sep, LOCKED_PASSWORD), LOCKED_PASSWORD, SEP_2026, True),
        "unbalanced": (draw_statement(UNBALANCED, LAYLA), None, UNBALANCED, False),
        "not_a_statement": (make_pdf(garden), None, None, False),
        "unsupported_bank": (
            draw_statement(replace(AUG_2026, bank=OTHER_BANK), OMAR),
            None,
            None,
            False,
        ),
    }
    result = {}
    for name in CASES:
        data, password, expected, reconciles = spec[name]
        path = directory / f"{name}.pdf"
        path.write_bytes(data)
        result[name] = StatementFixture(name, path, password, expected, reconciles)
    return result
