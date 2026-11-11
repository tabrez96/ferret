"""Bank statement parsers."""

from collections.abc import Sequence

from ferret.parsers.base import ParsedStatement, ParsedTransaction, ParseError, Parser
from ferret.parsers.emirates_nbd import PARSER as EMIRATES_NBD

PARSERS: tuple[Parser, ...] = (EMIRATES_NBD,)  # one instance per supported bank


def supported_banks(parsers: Sequence[Parser] = PARSERS) -> list[str]:
    return [p.bank for p in parsers]


def find_parser(first_page_text: str, parsers: Sequence[Parser] = PARSERS) -> Parser | None:
    for parser in parsers:
        if parser.detect(first_page_text):
            return parser
    return None


__all__ = [
    "PARSERS",
    "ParseError",
    "ParsedStatement",
    "ParsedTransaction",
    "Parser",
    "find_parser",
    "supported_banks",
]
