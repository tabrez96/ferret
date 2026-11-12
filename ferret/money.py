"""Conversion between Decimal amounts and integer minor units."""

from decimal import Decimal

MINOR_UNITS: dict[str, int] = {"AED": 2, "INR": 2, "USD": 2, "EUR": 2, "GBP": 2}


def minor_exponent(currency: str) -> int:
    try:
        return MINOR_UNITS[currency]
    except KeyError:
        raise ValueError(f"unsupported currency {currency!r}") from None


def to_minor(amount: Decimal, currency: str) -> int:
    if not isinstance(amount, Decimal):
        raise TypeError("amount must be a Decimal")
    scaled = amount.scaleb(minor_exponent(currency))
    if scaled != scaled.to_integral_value():
        raise ValueError("too many decimal places")
    return int(scaled)


def from_minor(minor: int, currency: str) -> Decimal:
    return Decimal(minor).scaleb(-minor_exponent(currency))


def format_amount(minor: int, currency: str) -> str:
    """Currency code before the number: format_amount(428675, "AED") == "AED 4,286.75".

    Negative amounts get a leading minus: "-AED 12.50".
    """
    exp = minor_exponent(currency)
    text = f"{currency} {from_minor(abs(minor), currency):,.{exp}f}"
    return f"-{text}" if minor < 0 else text
