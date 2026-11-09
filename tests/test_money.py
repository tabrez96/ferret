from decimal import Decimal

import pytest

from ferret.money import from_minor, to_minor


def test_to_minor_round_trip():
    minor = to_minor(Decimal("1234.56"), "AED")
    assert minor == 123456
    assert from_minor(minor, "AED") == Decimal("1234.56")


def test_to_minor_accepts_whole_amounts_with_trailing_zeros():
    assert to_minor(Decimal("5.100"), "USD") == 510


def test_to_minor_rejects_float():
    with pytest.raises(TypeError):
        to_minor(12.5, "AED")


def test_to_minor_rejects_extra_precision():
    with pytest.raises(ValueError, match="decimal places"):
        to_minor(Decimal("1.005"), "AED")


def test_unknown_currency():
    with pytest.raises(ValueError, match="unsupported"):
        to_minor(Decimal("1"), "XYZ")


def test_negative_amounts():
    assert to_minor(Decimal("-5.00"), "AED") == -500
