from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from receipt_ledger.api import dashboard, startup
from receipt_ledger.config import get_settings
from receipt_ledger.database import SessionLocal
from receipt_ledger.models import (
    Category,
    ConversationMessage,
    Expense,
    ExpenseScope,
    IngestionStatus,
    PaymentMethod,
)
from receipt_ledger.services.chat import (
    CHAT_TOOL_CONTRACT,
    MAX_MESSAGES,
    consume_pending_action,
    execute_tool,
    get_or_create_session,
    process_chat_job,
    queue_chat_job,
    trim_history,
)
from receipt_ledger.services.codex_cli import CodexNotConfigured


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


def test_missing_codex_runtime_fails_chat_job_once(monkeypatch) -> None:
    class MissingCodexProvider:
        def complete(self, messages, tools):
            raise CodexNotConfigured("Codex CLI is not installed")

    monkeypatch.setattr(
        "receipt_ledger.services.chat.chat_provider_for",
        lambda settings: MissingCodexProvider(),
    )
    startup()
    with SessionLocal() as db:
        job = queue_chat_job(db, "missing-codex-chat", "owner", "message-1", "hello")

        result = process_chat_job(db, get_settings(), job.id)

        assert result is not None
        assert result.status == "failed"
        assert result.attempts == 1
        assert result.response_text == "AI access is not configured on the worker. Please check the server setup."


def test_followup_can_change_active_expense_payment_method_by_name() -> None:
    edit_contract = next(
        tool for tool in CHAT_TOOL_CONTRACT if tool["name"] == "edit_expense"
    )
    change_properties = edit_contract["parameters"]["properties"]["changes"][
        "properties"
    ]
    assert "payment_method" in change_properties

    startup()
    with SessionLocal() as db:
        expense = _expense(db, date(2026, 8, 27), "4")
        session = get_or_create_session(db, "payment-chat", "payment-owner")
        session.active_expense_id = expense.id
        db.commit()
        job = queue_chat_job(
            db,
            "payment-chat",
            "payment-owner",
            "payment-message",
            "change the payment method to cash",
        )

        result = execute_tool(
            db,
            session,
            job,
            "edit_expense",
            {"active": True, "changes": {"payment_method": "cash"}},
        )

        cash = db.scalar(select(PaymentMethod).where(PaymentMethod.name == "Cash"))
        db.refresh(expense)
        assert cash is not None
        assert expense.payment_method_id == cash.id
        assert result["expense"]["payment_method"] == "Cash"
        assert result["expense"]["payment_method_id"] == cash.id
        assert expense.categorization_source == "manual"


def test_payment_method_name_error_lists_active_choices() -> None:
    startup()
    with SessionLocal() as db:
        expense = _expense(db, date(2026, 8, 27), "5")
        session = get_or_create_session(db, "bad-payment-chat", "payment-owner")
        session.active_expense_id = expense.id
        db.commit()
        job = queue_chat_job(
            db,
            "bad-payment-chat",
            "payment-owner",
            "bad-payment-message",
            "change the payment method",
        )

        with pytest.raises(ValueError, match="available:.*Cash"):
            execute_tool(
                db,
                session,
                job,
                "edit_expense",
                {"active": True, "changes": {"payment_method": "Not a method"}},
            )
