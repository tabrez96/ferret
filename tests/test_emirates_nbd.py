from decimal import Decimal

import pytest

from ferret.keys import FIELD_STATEMENT_PASSWORD, encrypt_field
from ferret.parsers import PARSERS, ParseError, supported_banks
from ferret.parsers.emirates_nbd import PARSER, _amount, _date
from ferret.pipeline import run_statement, submit_statement
from ferret.pipeline.pdf import first_page_text, open_pdf, unlock
from tests.fixtures.make_statements import LOCKED_PASSWORD
from tests.fixtures.pdfs import make_pdf

NOW = 1_800_000_000
BALANCED = ("aug_2026", "sep_2026", "oct_2026_multipage")


def parse_fixture(fixture):
    unlocked, _ = unlock(fixture.path.read_bytes(), [fixture.password] if fixture.password else [])
    with open_pdf(unlocked) as pdf:
        return PARSER.parse(pdf), first_page_text(pdf)


def submit(user, conn, fixture):
    return submit_statement(
        conn,
        user.db,
        user.dek,
        user.pending_dir,
        user.user_id,
        fixture.path.read_bytes(),
        source="upload",
        source_ref=None,
        now=NOW,
    )


def run(user, statement_id):
    return run_statement(user.db, user.dek, user.pending_dir, user.user_id, statement_id, now=NOW)


def save_password(user, password):
    ct, nonce = encrypt_field(user.dek, password, field=FIELD_STATEMENT_PASSWORD)
    user.db.execute(
        "INSERT INTO statement_passwords (bank, ciphertext, nonce, created_at) VALUES (?, ?, ?, ?)",
        ("Emirates NBD", ct, nonce, NOW),
    )
    user.db.commit()


def txn_count(user):
    return user.db.execute("SELECT count(*) FROM transactions").fetchone()[0]


def test_parses_every_fixture_exactly(statements):
    checked = 0
    for fixture in statements.values():
        if fixture.expected is None:
            continue
        parsed, _ = parse_fixture(fixture)
        assert len(parsed.transactions) == len(fixture.expected.transactions)
        assert parsed == fixture.expected
        checked += 1
    assert checked == 5


def test_refunds_and_payments_are_credits(statements):
    parsed, _ = parse_fixture(statements["sep_2026"])
    by_name = {t.merchant: t for t in parsed.transactions}
    assert by_name["Refund - Marina Bookhouse"].is_credit
    assert by_name["Payment received, thank you"].is_credit
    for fee in ("Late payment fee", "VAT on late payment fee", "Foreign transaction fee"):
        assert not by_name[fee].is_credit


def test_multipage_reads_both_pages(statements):
    fixture = statements["oct_2026_multipage"]
    parsed, _ = parse_fixture(fixture)
    assert len(parsed.transactions) == 45
    assert parsed.transactions[-1] == fixture.expected.transactions[-1]


def test_detect(statements):
    _, text = parse_fixture(statements["aug_2026"])
    assert PARSER.detect(text)
    for name in ("unsupported_bank", "not_a_statement"):
        unlocked, _ = unlock(statements[name].path.read_bytes(), [])
        with open_pdf(unlocked) as pdf:
            assert not PARSER.detect(first_page_text(pdf))
    assert not PARSER.detect("FAKE BANK STATEMENT")
    assert not PARSER.detect("")


@pytest.mark.parametrize(
    "lines",
    [
        ["Emirates NBD", "Credit Card Statement"],
        [
            "Emirates NBD",
            "Credit Card Statement",
            "Card number: XXXX XXXX XXXX 4821",
            "Statement period: 01/08/2026 to 31/08/2026",
            "Currency: AED",
        ],
    ],
)
def test_parse_errors(lines):
    with open_pdf(make_pdf(lines)) as pdf, pytest.raises(ParseError):
        PARSER.parse(pdf)


def test_amount_parsing():
    assert _amount("1,250.00") == Decimal("1250.00")
    for bad in ("12.5", "abc"):
        with pytest.raises(ParseError):
            _amount(bad)
    with pytest.raises(ParseError):
        _date("31/02/2026")


def test_registry_and_gmail_query():
    assert PARSER in PARSERS
    assert supported_banks() == ["Emirates NBD"]
    assert PARSER.gmail_query == "from:emiratesnbd.com has:attachment filename:pdf"


def test_pipeline_reconciles_balanced_fixtures(user, conn, statements):
    for name in BALANCED:
        assert run(user, submit(user, conn, statements[name])).status == "reconciled"
    assert txn_count(user) == 6 + 8 + 45


def test_pipeline_unbalanced_didnt_add_up(user, conn, statements):
    result = run(user, submit(user, conn, statements["unbalanced"]))
    assert result.status == "didnt_add_up"
    assert result.reconciliation.difference == -1000
    assert txn_count(user) == 0


def test_pipeline_locked_with_saved_password(user, conn, statements):
    save_password(user, LOCKED_PASSWORD)
    assert run(user, submit(user, conn, statements["locked"])).status == "reconciled"


def test_pipeline_non_enbd_unsupported(user, conn, statements):
    for name in ("unsupported_bank", "not_a_statement"):
        assert run(user, submit(user, conn, statements[name])).status == "unsupported"
