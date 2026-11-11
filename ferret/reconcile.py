"""Exact reconciliation of a parsed statement, in integer minor units."""

from dataclasses import dataclass

from ferret.money import to_minor
from ferret.parsers.base import ParsedStatement


@dataclass(frozen=True)
class Reconciliation:
    currency: str
    opening: int  # minor units, as printed
    closing: int  # printed closing balance
    total_debits: int  # printed
    total_credits: int  # printed
    parsed_debits: int  # sum of debit transactions
    parsed_credits: int  # sum of credit transactions
    expected: int  # == closing
    parsed: int  # opening + parsed_debits - parsed_credits
    difference: int  # parsed - expected
    ok: bool


def reconcile(statement: ParsedStatement) -> Reconciliation:
    """Check opening + debits - credits == closing and that sums match the printed totals.

    Raises ValueError when an amount has more decimals than the currency allows.
    """
    cur = statement.currency
    opening = to_minor(statement.opening, cur)
    closing = to_minor(statement.closing, cur)
    total_debits = to_minor(statement.total_debits, cur)
    total_credits = to_minor(statement.total_credits, cur)
    parsed_debits = 0
    parsed_credits = 0
    for txn in statement.transactions:
        minor = to_minor(txn.amount, cur)
        if txn.is_credit:
            parsed_credits += minor
        else:
            parsed_debits += minor
    parsed = opening + parsed_debits - parsed_credits
    difference = parsed - closing
    return Reconciliation(
        currency=cur,
        opening=opening,
        closing=closing,
        total_debits=total_debits,
        total_credits=total_credits,
        parsed_debits=parsed_debits,
        parsed_credits=parsed_credits,
        expected=closing,
        parsed=parsed,
        difference=difference,
        ok=difference == 0 and parsed_debits == total_debits and parsed_credits == total_credits,
    )
