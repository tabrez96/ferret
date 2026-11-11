"""Emirates NBD credit card statements, read from pdfplumber word coordinates."""

import re
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from ferret.parsers.base import ParsedStatement, ParsedTransaction, ParseError

if TYPE_CHECKING:
    import pdfplumber

BANK = "Emirates NBD"
GMAIL_QUERY = "from:emiratesnbd.com has:attachment filename:pdf"
DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
AMOUNT_RE = re.compile(r"^\d{1,3}(,\d{3})*\.\d{2}$")
CARD_RE = re.compile(r"Card number: X{4} X{4} X{4} (\d{4})")
PERIOD_RE = re.compile(r"Statement period: (\d{2}/\d{2}/\d{4}) to (\d{2}/\d{2}/\d{4})")
CURRENCY_RE = re.compile(r"Currency: ([A-Z]{3})")
SUMMARY = {
    "opening": "Previous balance",
    "total_debits": "Purchases and charges",
    "total_credits": "Payments and credits",
    "closing": "Closing balance",
}
LINE_TOLERANCE = 3  # points; words on one printed line share a top within this


def _date(text: str) -> date:
    try:
        return datetime.strptime(text, "%d/%m/%Y").date()
    except ValueError:
        raise ParseError("bad date") from None


def _amount(text: str) -> Decimal:
    if not AMOUNT_RE.match(text):
        raise ParseError("bad amount")
    return Decimal(text.replace(",", ""))


def _lines(page) -> list[list[dict]]:
    words = sorted(page.extract_words(), key=lambda w: (w["top"], w["x0"]))
    lines: list[list[dict]] = []
    first_top = 0.0
    for word in words:
        if not lines or word["top"] - first_top > LINE_TOLERANCE:
            lines.append([])
            first_top = word["top"]
        lines[-1].append(word)
    return [sorted(line, key=lambda w: w["x0"]) for line in lines]


def _text(line: list[dict]) -> str:
    return " ".join(w["text"] for w in line)


def _is_header(line: list[dict]) -> bool:
    return _text(line).startswith("Transaction date Posting date Description Amount")


def _row(line: list[dict], desc_x0: float) -> ParsedTransaction | None:
    if len(line) < 4 or not (DATE_RE.match(line[0]["text"]) and DATE_RE.match(line[1]["text"])):
        return None
    credit = line[-1]["text"] == "CR"
    amount_word = line[-2] if credit else line[-1]
    middle = line[2 : len(line) - (2 if credit else 1)]
    description = [w["text"] for w in middle if w["x0"] >= desc_x0 - 1]
    if not description:
        raise ParseError("row without description")
    _date(line[0]["text"])
    return ParsedTransaction(
        _date(line[1]["text"]), " ".join(description), _amount(amount_word["text"]), credit
    )


class EmiratesNBDParser:
    bank = BANK
    gmail_query = GMAIL_QUERY

    def detect(self, first_page_text: str) -> bool:
        return BANK in first_page_text and "Credit Card Statement" in first_page_text

    def parse(self, pdf: pdfplumber.PDF) -> ParsedStatement:
        if not pdf.pages:
            raise ParseError("empty document")
        first_lines = _lines(pdf.pages[0])
        first_text = "\n".join(_text(line) for line in first_lines)
        card = CARD_RE.search(first_text)
        if not card:
            raise ParseError("missing card number")
        period = PERIOD_RE.search(first_text)
        if not period:
            raise ParseError("missing period")
        currency = CURRENCY_RE.search(first_text)
        if not currency:
            raise ParseError("missing currency")

        summary: dict[str, Decimal] = {}
        for key, label in SUMMARY.items():
            line = next((ln for ln in first_lines if _text(ln).startswith(label)), None)
            if line is None:
                raise ParseError(f"missing {label.lower()}")
            summary[key] = _amount(line[-1]["text"])

        rows: list[ParsedTransaction] = []
        found_table = False
        for page in pdf.pages:
            lines = _lines(page)
            start = next((i for i, ln in enumerate(lines) if _is_header(ln)), None)
            if start is None:
                continue
            found_table = True
            desc_x0 = next(w["x0"] for w in lines[start] if w["text"] == "Description")
            for line in lines[start + 1 :]:
                parsed = _row(line, desc_x0)
                if parsed is not None:
                    rows.append(parsed)
        if not found_table:
            raise ParseError("no transaction table")
        return ParsedStatement(
            bank=BANK,
            card_last4=card.group(1),
            currency=currency.group(1),
            period_start=_date(period.group(1)),
            period_end=_date(period.group(2)),
            opening=summary["opening"],
            closing=summary["closing"],
            total_debits=summary["total_debits"],
            total_credits=summary["total_credits"],
            transactions=tuple(rows),
        )


PARSER = EmiratesNBDParser()
