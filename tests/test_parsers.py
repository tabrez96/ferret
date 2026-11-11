from ferret.parsers import PARSERS, find_parser, supported_banks
from ferret.parsers.emirates_nbd import PARSER as EMIRATES_NBD
from tests.fixtures.fake_parser import FakeParser, statement


def test_registry_and_find_parser():
    assert PARSERS == (EMIRATES_NBD,)
    assert supported_banks() == ["Emirates NBD"]
    assert find_parser("FAKE BANK STATEMENT") is None
    fake = FakeParser(statement())
    assert find_parser("xx FAKE BANK STATEMENT xx", [fake]) is fake
    assert find_parser("other bank", [fake]) is None
    assert supported_banks([fake]) == ["Fake Bank"]
