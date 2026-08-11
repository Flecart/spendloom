from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from receipt_ledger.api import dashboard, startup
from receipt_ledger.config import get_settings
from receipt_ledger.database import SessionLocal
from receipt_ledger.models import Category, ConversationMessage, Expense, ExpenseScope, IngestionStatus
from receipt_ledger.services.chat import (
    MAX_MESSAGES,
    consume_pending_action,
    execute_tool,
    get_or_create_session,
    queue_chat_job,
    trim_history,
)


def _expense(db, when: date, amount: str) -> Expense:
    category = db.scalar(select(Category).limit(1))
    item = Expense(
        expense_date=when,
        merchant=f"Fixture {when}",
        merchant_normalized=f"fixture {when}",
        original_amount=Decimal(amount),
        original_currency="EUR",
        amount=Decimal(amount),
        category_id=category.id,
        scope=ExpenseScope.personal,
        confidence=1,
        status=IngestionStatus.accepted,
        categorization_source="manual",
        category_reason="Fixture",
    )
    db.add(item)
    db.commit()
    return item


def test_dashboard_uses_inclusive_custom_range() -> None:
    startup()
    with SessionLocal() as db:
        _expense(db, date(2025, 7, 1), "10")
        _expense(db, date(2026, 7, 31), "20")
        old = dashboard(None, db, date_from=date(2025, 7, 1), date_to=date(2025, 7, 31))
        recent = dashboard(None, db, date_from=date(2026, 7, 1), date_to=date(2026, 7, 31))
        assert old.range_total == Decimal("10")
        assert recent.range_total == Decimal("20")
        assert old.date_from == date(2025, 7, 1)


def test_chat_history_is_bounded_and_delete_needs_one_use_confirmation() -> None:
    startup()
    with SessionLocal() as db:
        expense = _expense(db, date(2026, 8, 1), "3")
        session = get_or_create_session(db, "123", "456")
        session.active_expense_id = expense.id
        for index in range(MAX_MESSAGES + 4):
            db.add(ConversationMessage(session_id=session.id, role="user", content=f"message {index}", approximate_tokens=2))
        db.commit()
        assert trim_history(db, session.id) == MAX_MESSAGES
        job = queue_chat_job(db, "123", "456", "1", "delete it")
        result = execute_tool(db, session, job, "delete_expense", {"active": True})
        assert result["confirmation_required"] is True
        token = result["confirmation_token"]
        assert consume_pending_action(db, token, "123", "456", True) == "Expense deleted."
        assert consume_pending_action(db, token, "123", "456", True) == "That confirmation has expired."
