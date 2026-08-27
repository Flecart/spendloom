from datetime import date, datetime, timezone
from decimal import Decimal

from receipt_ledger.services.processing import (
    normalize_merchant,
    parse_date,
    parse_decimal,
    receipt_is_older_than_review_window,
)


def test_normalize_merchant_removes_company_noise() -> None:
    assert normalize_merchant("  ACME Coffee, Ltd. ") == "acme coffee"


def test_decimal_formats() -> None:
    assert parse_decimal("€1.234,56") == Decimal("1234.56")
    assert parse_decimal("$1,234.56") == Decimal("1234.56")
    assert parse_decimal("-18,20") == Decimal("18.20")


def test_parse_date_accepts_iso_dates() -> None:
    assert parse_date("2026-08-12") == date(2026, 8, 12)
    assert parse_date("not-a-date") is None


def test_receipt_exactly_two_weeks_old_stays_in_normal_review_flow() -> None:
    received_at = datetime(2026, 8, 27, 23, 30, tzinfo=timezone.utc)

    assert receipt_is_older_than_review_window(date(2026, 8, 13), received_at) is False


def test_receipt_more_than_two_weeks_old_requires_review() -> None:
    received_at = datetime(2026, 8, 27, 1, 30, tzinfo=timezone.utc)

    assert receipt_is_older_than_review_window(date(2026, 8, 12), received_at) is True
