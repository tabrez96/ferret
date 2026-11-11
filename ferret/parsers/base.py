"""Types shared by all bank parsers."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import pdfplumber


@dataclass(frozen=True)
class ParsedTransaction:
    posted_on: date
    merchant: str
    amount: Decimal  # always >= 0; direction is is_credit
    is_credit: bool


@dataclass(frozen=True)
class ParsedStatement:
    bank: str
    card_last4: str
    currency: str
    period_start: date
    period_end: date
    opening: Decimal
    closing: Decimal
    total_debits: Decimal
    total_credits: Decimal
    transactions: tuple[ParsedTransaction, ...]


class ParseError(Exception):
    """The bank was detected but the document could not be read as its statement."""


class Parser(Protocol):
    bank: str  # display name, e.g. "Emirates NBD"
    gmail_query: str

    def detect(self, first_page_text: str) -> bool: ...

    def parse(self, pdf: pdfplumber.PDF) -> ParsedStatement: ...
