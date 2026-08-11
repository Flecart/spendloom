from decimal import Decimal

from receipt_ledger.services.processing import normalize_merchant, parse_decimal


def test_normalize_merchant_removes_company_noise() -> None:
    assert normalize_merchant("  ACME Coffee, Ltd. ") == "acme coffee"


def test_decimal_formats() -> None:
    assert parse_decimal("€1.234,56") == Decimal("1234.56")
    assert parse_decimal("$1,234.56") == Decimal("1234.56")
    assert parse_decimal("-18,20") == Decimal("18.20")
