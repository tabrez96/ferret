from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from ferret.parsers.base import ParsedTransaction
from ferret.reconcile import reconcile
from tests.fixtures.fake_parser import statement


def test_balanced_statement_ok():
    rec = reconcile(statement())
    assert rec.ok and rec.difference == 0
    assert rec.parsed_debits == 30049
    assert rec.parsed_credits == 10000
    assert rec.expected == rec.closing == 120049
    assert rec.parsed == 120049


def test_closing_off_by_one_fil_fails():
    low = reconcile(statement(closing=Decimal("1200.48")))
    assert not low.ok and low.difference == 1
    high = reconcile(statement(closing=Decimal("1200.50")))
    assert not high.ok and high.difference == -1


def test_debit_total_off_by_one_fil_fails():
    rec = reconcile(statement(total_debits=Decimal("300.50")))
    assert rec.difference == 0
    assert not rec.ok


def test_credit_total_off_by_one_fil_fails():
    rec = reconcile(statement(total_credits=Decimal("100.01")))
    assert rec.difference == 0
    assert not rec.ok


def test_many_small_amounts_exact():
    txns = tuple(
        ParsedTransaction(date(2026, 9, 1), "Cafe Example", Decimal("0.10"), False)
        for _ in range(1000)
    )
    rec = reconcile(
        statement(
            opening=Decimal("0"),
            closing=Decimal("100.00"),
            total_debits=Decimal("100.00"),
            total_credits=Decimal("0"),
            transactions=txns,
        )
    )
    assert rec.ok and rec.parsed_debits == 10000


def test_sub_minor_amount_raises():
    base = statement()
    bad = replace(
        base,
        transactions=(
            ParsedTransaction(date(2026, 9, 1), "Cafe Example", Decimal("1.005"), False),
        ),
    )
    with pytest.raises(ValueError):
        reconcile(bad)


def test_no_transactions():
    rec = reconcile(
        statement(
            opening=Decimal("50.00"),
            closing=Decimal("50.00"),
            total_debits=Decimal("0"),
            total_credits=Decimal("0"),
            transactions=(),
        )
    )
    assert rec.ok
