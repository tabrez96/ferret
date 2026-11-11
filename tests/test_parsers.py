from ferret.parsers import PARSERS, find_parser, supported_banks
from tests.fixtures.fake_parser import FakeParser, statement


def test_registry_empty_by_default_and_find_parser():
    assert PARSERS == ()
    assert supported_banks() == []
    assert find_parser("FAKE BANK STATEMENT") is None
    fake = FakeParser(statement())
    assert find_parser("xx FAKE BANK STATEMENT xx", [fake]) is fake
    assert find_parser("other bank", [fake]) is None
    assert supported_banks([fake]) == ["Fake Bank"]
