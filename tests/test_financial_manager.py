import base64
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select, update

from receipt_ledger.api import startup
from receipt_ledger.config import get_settings
from receipt_ledger.database import SessionLocal
from receipt_ledger.models import (
    Category,
    Contract,
    IncomeEntry,
    IncomeKind,
    Invoice,
    Ingestion,
    GmailConnection,
    GmailSenderRule,
    OccurrenceStatus,
    RecurrenceFrequency,
    RecurringEntryType,
    RecurringItem,
    RecurringOccurrence,
    Receipt,
)
from receipt_ledger.schemas import IncomeCreate
from receipt_ledger.services.finance import (
    allocate_income,
    complete_occurrence,
    create_income_entry,
    invoice_out,
    materialize_occurrences,
    next_reminder_occurrence,
)
from receipt_ledger.services.gmail import _import_message, decrypt_token, encrypt_token


def test_monthly_recurrence_preserves_anchor_and_clamps_short_months() -> None:
    startup()
    with SessionLocal() as db:
        item = RecurringItem(
            name="Month-end rent",
            entry_type=RecurringEntryType.expense,
            counterparty="Landlord",
            expected_amount=Decimal("1000"),
            currency="EUR",
            frequency=RecurrenceFrequency.monthly,
            start_date=date(2027, 1, 31),
            reminder_days_before=3,
            scope="personal",
        )
        db.add(item)
        db.commit()

        materialize_occurrences(
            db,
            today=date(2027, 1, 31),
            horizon_days=100,
        )

        dates = list(
            db.scalars(
                select(RecurringOccurrence.due_date)
                .where(RecurringOccurrence.recurring_item_id == item.id)
                .order_by(RecurringOccurrence.due_date)
            ).all()
        )
        assert dates[:4] == [
            date(2027, 1, 31),
            date(2027, 2, 28),
            date(2027, 3, 31),
            date(2027, 4, 30),
        ]


def test_completing_recurring_expense_posts_only_after_confirmation() -> None:
    startup()
    with SessionLocal() as db:
        category = db.scalar(select(Category).limit(1))
        item = RecurringItem(
            name="Electricity",
            entry_type=RecurringEntryType.expense,
            counterparty="Energy Company",
            expected_amount=None,
            currency="EUR",
            frequency=RecurrenceFrequency.monthly,
            start_date=date(2027, 5, 10),
            reminder_days_before=2,
            category_id=category.id,
            scope="personal",
        )
        db.add(item)
        db.flush()
        occurrence = RecurringOccurrence(
            recurring_item_id=item.id,
            due_date=date(2027, 5, 10),
            expected_amount=None,
            currency="EUR",
        )
        db.add(occurrence)
        db.commit()

        result = complete_occurrence(
            db,
            get_settings(),
            occurrence,
            amount=Decimal("73.42"),
            occurred_on=date(2027, 5, 9),
        )

        db.refresh(occurrence)
        assert result == "Expense recorded: 73.42 EUR."
        assert occurrence.status == OccurrenceStatus.completed
        assert occurrence.actual_expense_id is not None


def test_invoice_partial_and_full_allocations_are_derived() -> None:
    startup()
    with SessionLocal() as db:
        contract = Contract(
            title="Consulting agreement",
            counterparty="Client",
            status="active",
        )
        db.add(contract)
        db.commit()
        first = create_income_entry(
            db,
            get_settings(),
            IncomeCreate(
                received_date=date(2027, 6, 1),
                payer="Client",
                kind=IncomeKind.contract,
                original_amount=Decimal("40"),
                original_currency="EUR",
                contract_id=contract.id,
            ),
        )
        second = create_income_entry(
            db,
            get_settings(),
            IncomeCreate(
                received_date=date(2027, 6, 2),
                payer="Client",
                kind=IncomeKind.contract,
                original_amount=Decimal("60"),
                original_currency="EUR",
                contract_id=contract.id,
            ),
        )
        invoice = Invoice(
            reference="TEST-ALLOC-2027",
            client="Client",
            contract_id=contract.id,
            issue_date=date(2027, 5, 1),
            due_date=date(2027, 6, 30),
            currency="EUR",
            subtotal=Decimal("80"),
            tax_amount=Decimal("20"),
            total=Decimal("100"),
        )
        db.add(invoice)
        db.commit()

        allocate_income(db, invoice, first, Decimal("40"))
        partial = invoice_out(db, invoice, today=date(2027, 6, 10))
        assert partial.status == "partial"
        assert partial.outstanding_amount == Decimal("60")

        allocate_income(db, invoice, second, Decimal("60"))
        paid = invoice_out(db, invoice, today=date(2027, 7, 1))
        assert paid.status == "paid"
        assert paid.outstanding_amount == Decimal("0")


def test_gmail_refresh_tokens_are_encrypted_at_rest() -> None:
    settings = get_settings().model_copy(
        update={"gmail_token_encryption_key": "test-only-encryption-key"}
    )
    ciphertext = encrypt_token(settings, "refresh-token-value")
    assert "refresh-token-value" not in ciphertext
    assert decrypt_token(settings, ciphertext) == "refresh-token-value"


def test_gmail_import_checks_exact_sender_and_sanitizes_body(monkeypatch) -> None:
    startup()
    html_body = (
        "<html><body><p>Invoice total: 22 EUR</p>"
        "<script>stealMailbox()</script>"
        "<a href='https://unsafe.example/receipt'>View invoice</a>"
        "</body></html>"
    )
    encoded_body = base64.urlsafe_b64encode(html_body.encode()).decode().rstrip("=")
    payload = {
        "headers": [
            {"name": "From", "value": "Utility <bills@example.test>"},
            {"name": "Subject", "value": "Your monthly bill"},
        ],
        "mimeType": "text/html",
        "body": {"data": encoded_body},
    }
    message = {
        "id": "gmail-safe-body-message",
        "threadId": "gmail-safe-body-thread",
        "internalDate": str(int(datetime(2027, 7, 2, tzinfo=timezone.utc).timestamp() * 1000)),
        "payload": payload,
    }
    blocked_message = {
        **message,
        "id": "gmail-similar-sender-message",
        "payload": {
            **payload,
            "headers": [
                {
                    "name": "From",
                    "value": "Utility <bills+alias@example.test>",
                },
                {"name": "Subject", "value": "Should not be imported"},
            ],
        },
    }
    requests: list[tuple[str, object]] = []

    def fake_get(_token, path, *, params=None):
        requests.append((path, params))
        if path == "messages/gmail-safe-body-message":
            return message
        if path == "messages/gmail-similar-sender-message":
            return blocked_message
        raise AssertionError(f"Unexpected Gmail request: {path}")

    monkeypatch.setattr("receipt_ledger.services.gmail._gmail_get", fake_get)
    with SessionLocal() as db:
        connection = GmailConnection(
            email_address="owner@example.test",
            encrypted_refresh_token="not-used-by-this-test",
            history_id="100",
            status="connected",
        )
        db.add(connection)
        db.flush()
        rule = GmailSenderRule(
            connection_id=connection.id,
            sender_address="bills@example.test",
            match_window_days=45,
        )
        db.add(rule)
        db.commit()

        imported = _import_message(
            db,
            get_settings(),
            connection,
            "access-token",
            "gmail-safe-body-message",
        )

        assert imported is not None
        assert imported.ingestion_id is not None
        ingestion = db.get(Ingestion, imported.ingestion_id)
        receipt = db.get(Receipt, ingestion.receipt_id)
        stored = Path(receipt.storage_path).read_text(encoding="utf-8")
        assert "Invoice total: 22 EUR" in stored
        assert "stealMailbox" not in stored
        assert "unsafe.example" not in stored

        blocked = _import_message(
            db,
            get_settings(),
            connection,
            "access-token",
            "gmail-similar-sender-message",
        )

        assert blocked is None
        blocked_requests = [
            params
            for path, params in requests
            if path == "messages/gmail-similar-sender-message"
        ]
        assert len(blocked_requests) == 1
        assert blocked_requests[0] != {"format": "full"}


def test_recurring_reminder_waits_for_configured_local_time() -> None:
    startup()
    with SessionLocal() as db:
        db.execute(update(RecurringItem).values(active=False))
        item = RecurringItem(
            name="Rent reminder",
            entry_type=RecurringEntryType.expense,
            counterparty="Landlord",
            expected_amount=Decimal("1200"),
            currency="EUR",
            frequency=RecurrenceFrequency.monthly,
            start_date=date(2030, 1, 12),
            reminder_days_before=0,
            scope="personal",
        )
        db.add(item)
        db.flush()
        occurrence = RecurringOccurrence(
            recurring_item_id=item.id,
            due_date=date(2030, 1, 12),
            expected_amount=item.expected_amount,
            currency=item.currency,
        )
        db.add(occurrence)
        db.commit()
        settings = get_settings().model_copy(update={"timezone": "UTC"})

        before = next_reminder_occurrence(
            db,
            settings,
            now=datetime(2030, 1, 12, 8, 59, tzinfo=timezone.utc),
        )
        due = next_reminder_occurrence(
            db,
            settings,
            now=datetime(2030, 1, 12, 9, 0, tzinfo=timezone.utc),
        )

        assert before is None
        assert due is not None
        assert due[0].id == occurrence.id
        assert due[1] == "due"
