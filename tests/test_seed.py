from sqlalchemy import select

from receipt_ledger.api import startup
from receipt_ledger.database import SessionLocal
from receipt_ledger.models import PaymentMethod


def test_cash_payment_method_is_seeded_without_becoming_the_fallback() -> None:
    startup()

    with SessionLocal() as db:
        cash = db.scalar(select(PaymentMethod).where(PaymentMethod.name == "Cash"))
        default_method = db.scalar(
            select(PaymentMethod).where(PaymentMethod.is_default.is_(True))
        )

    assert cash is not None
    assert cash.method_type == "cash"
    assert cash.is_default is False
    assert default_method is not None
    assert default_method.name == "Unknown / default"
