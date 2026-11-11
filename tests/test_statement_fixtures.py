import subprocess
from pathlib import Path

import pytest

from ferret.pipeline.pdf import PasswordRequired, open_pdf, unlock
from ferret.reconcile import reconcile
from tests.fixtures.make_statements import (
    CASES,
    LOCKED_PASSWORD,
    MERCHANTS,
    PAYMENT,
    SEP_2026,
    StatementFixture,
    _dmy,
    _money,
    make_statements,
)

REPO = Path(__file__).resolve().parent.parent


def text_of(fixture: StatementFixture) -> str:
    unlocked, _ = unlock(fixture.path.read_bytes(), [fixture.password] if fixture.password else [])
    with open_pdf(unlocked) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def with_expected(statements):
    return [f for f in statements.values() if f.expected is not None]


def test_all_cases_generated(statements, tmp_path):
    assert tuple(statements) == CASES
    for fixture in statements.values():
        assert fixture.path.is_file()
        assert tmp_path in fixture.path.parents
        assert fixture.path.read_bytes().startswith(b"%PDF")


def test_balanced_fixtures_reconcile(statements):
    for fixture in with_expected(statements):
        assert reconcile(fixture.expected).ok == fixture.reconciles, fixture.name


def test_unbalanced_is_off_by_ten(statements):
    expected = statements["unbalanced"].expected
    assert reconcile(expected).difference == -1000
    assert expected.total_debits == sum(t.amount for t in expected.transactions if not t.is_credit)
    assert expected.total_credits == sum(t.amount for t in expected.transactions if t.is_credit)


def line_with(text: str, label: str) -> str:
    return next(line for line in text.splitlines() if line.startswith(label))


def test_every_line_is_printed(statements):
    for fixture in with_expected(statements):
        s = fixture.expected
        text = text_of(fixture)
        lines = text.splitlines()
        assert "Emirates NBD" in text
        assert f"XXXX XXXX XXXX {s.card_last4}" in text
        assert f"Statement period: {_dmy(s.period_start)} to {_dmy(s.period_end)}" in text
        summary = {
            "Previous balance": s.opening,
            "Purchases and charges": s.total_debits,
            "Payments and credits": s.total_credits,
            "Closing balance": s.closing,
        }
        for label, value in summary.items():
            assert line_with(text, label).endswith(_money(value)), (fixture.name, label)
        for txn in s.transactions:
            suffix = _money(txn.amount) + (" CR" if txn.is_credit else "")
            assert any(
                txn.merchant in line and line.endswith(suffix) and _dmy(txn.posted_on) in line
                for line in lines
            ), (fixture.name, txn)


def test_multipage_has_two_pages(statements):
    fixture = statements["oct_2026_multipage"]
    unlocked, _ = unlock(fixture.path.read_bytes(), [])
    with open_pdf(unlocked) as pdf:
        assert len(pdf.pages) == 2
    assert len(fixture.expected.transactions) == 45
    text = text_of(fixture)
    assert "Page 2 of 2" in text
    assert "(continued)" in text


def test_sep_has_refund_fee_and_payment(statements):
    txns = statements["sep_2026"].expected.transactions
    assert any(t.is_credit and t.merchant.startswith("Refund - ") for t in txns)
    assert any("fee" in t.merchant for t in txns)
    assert any(t.is_credit and t.merchant == PAYMENT for t in txns)


def test_locked_needs_the_password(statements):
    fixture = statements["locked"]
    data = fixture.path.read_bytes()
    with pytest.raises(PasswordRequired):
        unlock(data, [])
    _, index = unlock(data, ["wrong", LOCKED_PASSWORD])
    assert index == 1
    assert fixture.password == LOCKED_PASSWORD
    assert fixture.expected == SEP_2026


def test_non_statement_and_unsupported_bank(statements):
    other = statements["unsupported_bank"]
    plain = statements["not_a_statement"]
    assert other.expected is None and plain.expected is None
    other_text, plain_text = text_of(other), text_of(plain)
    assert "Emirates NBD" not in other_text
    assert "Emirates NBD" not in plain_text
    assert "Northwind Bank" in other_text
    assert "Credit Card Statement" in other_text
    assert "Community Garden Newsletter" in plain_text


def test_generation_is_deterministic(tmp_path):
    first = make_statements(tmp_path / "a")
    second = make_statements(tmp_path / "b")
    for name in CASES:
        assert first[name].expected == second[name].expected
    assert first["aug_2026"].path.read_bytes() == second["aug_2026"].path.read_bytes()


def test_merchants_are_invented(statements):
    for fixture in with_expected(statements):
        for txn in fixture.expected.transactions:
            if txn.merchant == PAYMENT or "fee" in txn.merchant:
                continue
            assert txn.merchant.removeprefix("Refund - ") in MERCHANTS, txn


def test_no_pdfs_tracked():
    try:
        result = subprocess.run(
            ["git", "ls-files", "*.pdf"], cwd=REPO, capture_output=True, text=True
        )
    except FileNotFoundError:
        pytest.skip("git not available")
    if result.returncode != 0:
        pytest.skip("git ls-files failed")
    assert result.stdout == ""
