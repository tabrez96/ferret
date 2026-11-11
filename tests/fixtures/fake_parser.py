"""A parser for tests."""

from datetime import date
from decimal import Decimal

from ferret.parsers.base import ParsedStatement, ParsedTransaction


class FakeParser:
    bank = "Fake Bank"
    gmail_query = "from:statements@fakebank.test"

    def __init__(self, result: ParsedStatement | Exception, marker: str = "FAKE BANK STATEMENT"):
        self.result = result
        self.marker = marker

    def detect(self, first_page_text: str) -> bool:
        return self.marker in first_page_text

    def parse(self, pdf) -> ParsedStatement:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def statement(**overrides) -> ParsedStatement:
    """A balanced AED statement: 1000.00 + 300.49 - 100.00 = 1200.49."""
    fields = {
        "bank": "Fake Bank",
        "card_last4": "1234",
        "currency": "AED",
        "period_start": date(2026, 9, 1),
        "period_end": date(2026, 9, 30),
        "opening": Decimal("1000.00"),
        "closing": Decimal("1200.49"),
        "total_debits": Decimal("300.49"),
        "total_credits": Decimal("100.00"),
        "transactions": (
            ParsedTransaction(date(2026, 9, 3), "Cafe Example", Decimal("250.50"), False),
            ParsedTransaction(date(2026, 9, 10), "Bookshop Test", Decimal("49.99"), False),
            ParsedTransaction(date(2026, 9, 15), "Payment Thank You", Decimal("100.00"), True),
        ),
    }
    fields.update(overrides)
    return ParsedStatement(**fields)
