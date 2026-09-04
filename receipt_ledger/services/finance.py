from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload
from zoneinfo import ZoneInfo

from ..config import Settings
from ..models import (
    AuditEvent,
    Contract,
    Expense,
    GmailSenderRule,
    IncomeEntry,
    IncomeKind,
    IngestionStatus,
    Invoice,
    InvoiceAllocation,
    OccurrenceStatus,
    RecurrenceFrequency,
    RecurringEntryType,
    RecurringItem,
    RecurringOccurrence,
)
from ..schemas import (
    ContractOut,
    FinancialOverviewOut,
    IncomeCreate,
    IncomeOut,
    InvoiceOut,
    RecurringItemOut,
    RecurringOccurrenceOut,
)
from .documents import documents_for, move_occurrence_documents
from .fx import get_eur_rate
from .processing import normalize_merchant


def _month_date(anchor: date, months: int) -> date:
    month_index = anchor.month - 1 + months
    year = anchor.year + month_index // 12
    month = month_index % 12 + 1
    day = min(anchor.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def occurrence_date(item: RecurringItem, index: int) -> date:
    if item.frequency == RecurrenceFrequency.weekly:
        return item.start_date + timedelta(days=7 * index)
    if item.frequency == RecurrenceFrequency.monthly:
        return _month_date(item.start_date, index)
    if item.frequency == RecurrenceFrequency.quarterly:
        return _month_date(item.start_date, index * 3)
    return _month_date(item.start_date, index * 12)


def materialize_occurrences(
    db: Session,
    *,
    today: date | None = None,
    horizon_days: int = 90,
    backfill_days: int = 0,
) -> int:
    local_today = today or date.today()
    horizon = local_today + timedelta(days=horizon_days)
    created = 0
    items = db.scalars(
        select(RecurringItem).where(RecurringItem.active.is_(True))
    ).all()
    for item in items:
        existing_dates = set(
            db.scalars(
                select(RecurringOccurrence.due_date).where(
                    RecurringOccurrence.recurring_item_id == item.id
                )
            ).all()
        )
        index = 0
        while index < 10_000:
            due = occurrence_date(item, index)
            if due > horizon:
                break
            if item.end_date and due > item.end_date:
                break
            if due >= local_today - timedelta(days=backfill_days) and due not in existing_dates:
                db.add(
                    RecurringOccurrence(
                        recurring_item_id=item.id,
                        due_date=due,
                        expected_amount=item.expected_amount,
                        currency=item.currency,
                    )
                )
                created += 1
            index += 1
    if created:
        db.commit()
    return created


def occurrence_timing(occurrence: RecurringOccurrence, today: date | None = None) -> str:
    if occurrence.status == OccurrenceStatus.completed:
        return "completed"
    if occurrence.status == OccurrenceStatus.skipped:
        return "skipped"
    current = today or date.today()
    if occurrence.due_date < current:
        return "overdue"
    if occurrence.due_date == current:
        return "due"
    return "upcoming"


def recurring_item_out(db: Session, item: RecurringItem) -> RecurringItemOut:
    next_due = db.scalar(
        select(RecurringOccurrence.due_date)
        .where(
            RecurringOccurrence.recurring_item_id == item.id,
            RecurringOccurrence.status == OccurrenceStatus.pending,
        )
        .order_by(RecurringOccurrence.due_date)
        .limit(1)
    )
    return RecurringItemOut(
        id=item.id,
        name=item.name,
        entry_type=item.entry_type,
        counterparty=item.counterparty,
        expected_amount=item.expected_amount,
        currency=item.currency,
        frequency=item.frequency,
        start_date=item.start_date,
        end_date=item.end_date,
        reminder_days_before=item.reminder_days_before,
        category_id=item.category_id,
        payment_method_id=item.payment_method_id,
        scope=item.scope,
        income_kind=item.income_kind,
        contract_id=item.contract_id,
        active=item.active,
        next_due_date=next_due,
    )


def occurrence_out(occurrence: RecurringOccurrence) -> RecurringOccurrenceOut:
    item = occurrence.recurring_item
    return RecurringOccurrenceOut(
        id=occurrence.id,
        recurring_item_id=item.id,
        recurring_item_name=item.name,
        entry_type=item.entry_type,
        counterparty=item.counterparty,
        due_date=occurrence.due_date,
        expected_amount=occurrence.expected_amount,
        currency=occurrence.currency,
        status=occurrence.status,
        timing=occurrence_timing(occurrence),
        actual_expense_id=occurrence.actual_expense_id,
        actual_income_id=occurrence.actual_income_id,
        snoozed_until=occurrence.snoozed_until,
    )


def create_income_entry(
    db: Session,
    settings: Settings,
    payload: IncomeCreate,
) -> IncomeEntry:
    if payload.contract_id:
        contract = db.get(Contract, payload.contract_id)
        if not contract or contract.deleted_at:
            raise ValueError("Contract not found")
    conversion_rate, rate_date = get_eur_rate(
        db,
        payload.original_currency,
        payload.received_date,
    )
    normalized_amount = None
    if conversion_rate is not None:
        normalized_amount = (payload.original_amount * conversion_rate).quantize(
            Decimal("0.01")
        )
    income = IncomeEntry(
        received_date=payload.received_date,
        payer=payload.payer.strip(),
        kind=payload.kind,
        original_amount=payload.original_amount,
        original_currency=payload.original_currency,
        amount=normalized_amount,
        currency=settings.base_currency,
        conversion_rate=conversion_rate,
        fx_rate_date=rate_date,
        fx_estimated=bool(rate_date and rate_date != payload.received_date),
        contract_id=payload.contract_id,
        memo=payload.memo,
    )
    db.add(income)
    db.flush()
    if payload.occurrence_id:
        occurrence = db.get(RecurringOccurrence, payload.occurrence_id)
        if not occurrence or occurrence.status != OccurrenceStatus.pending:
            raise ValueError("Pending recurring occurrence not found")
        if occurrence.recurring_item.entry_type != RecurringEntryType.income:
            raise ValueError("The recurring occurrence is not income")
        occurrence.actual_income_id = income.id
        occurrence.status = OccurrenceStatus.completed
        occurrence.completed_at = datetime.now(timezone.utc)
        move_occurrence_documents(db, occurrence.id, "income", income.id)
    db.add(
        AuditEvent(
            entity_type="income",
            entity_id=income.id,
            action="created",
            details={"source": "manual"},
        )
    )
    db.commit()
    db.refresh(income)
    return income


def complete_occurrence(
    db: Session,
    settings: Settings,
    occurrence: RecurringOccurrence,
    *,
    amount: Decimal | None,
    occurred_on: date | None,
) -> str:
    if occurrence.status != OccurrenceStatus.pending:
        raise ValueError("This occurrence is already resolved")
    actual_amount = amount or occurrence.expected_amount
    if actual_amount is None:
        raise ValueError("Enter the actual amount for this variable occurrence")
    item = occurrence.recurring_item
    actual_date = occurred_on or occurrence.due_date
    if item.entry_type == RecurringEntryType.income:
        income = create_income_entry(
            db,
            settings,
            IncomeCreate(
                received_date=actual_date,
                payer=item.counterparty,
                kind=item.income_kind or IncomeKind.other,
                original_amount=actual_amount,
                original_currency=occurrence.currency,
                contract_id=item.contract_id,
                occurrence_id=occurrence.id,
                memo=f"Recorded from recurring item {item.name}",
            ),
        )
        return f"Income recorded: {income.original_amount} {income.original_currency}."

    conversion_rate, rate_date = get_eur_rate(db, occurrence.currency, actual_date)
    normalized_amount = None
    if conversion_rate is not None:
        normalized_amount = (actual_amount * conversion_rate).quantize(Decimal("0.01"))
    expense = Expense(
        expense_date=actual_date,
        merchant=item.counterparty,
        merchant_normalized=normalize_merchant(item.counterparty),
        original_amount=actual_amount,
        original_currency=occurrence.currency,
        amount=normalized_amount,
        currency=settings.base_currency,
        conversion_rate=conversion_rate,
        fx_rate_date=rate_date,
        fx_estimated=bool(rate_date and rate_date != actual_date),
        category_id=item.category_id,
        payment_method_id=item.payment_method_id,
        scope=item.scope,
        confidence=1,
        categorization_source="manual",
        category_reason=f"Recurring item: {item.name}",
        status=IngestionStatus.accepted,
        memo=f"Recorded from recurring item {item.name}",
    )
    db.add(expense)
    db.flush()
    occurrence.actual_expense_id = expense.id
    occurrence.status = OccurrenceStatus.completed
    occurrence.completed_at = datetime.now(timezone.utc)
    move_occurrence_documents(db, occurrence.id, "expense", expense.id)
    db.add(
        AuditEvent(
            entity_type="expense",
            entity_id=expense.id,
            action="created",
            details={"source": "recurring", "occurrence_id": occurrence.id},
        )
    )
    db.commit()
    return f"Expense recorded: {actual_amount} {occurrence.currency}."


def contract_out(db: Session, contract: Contract) -> ContractOut:
    documents = documents_for(db, "contract", contract.id)
    return ContractOut(
        id=contract.id,
        title=contract.title,
        counterparty=contract.counterparty,
        reference=contract.reference,
        start_date=contract.start_date,
        end_date=contract.end_date,
        status=contract.status,
        notes=contract.notes,
        document_count=len(documents),
        documents=documents,
        created_at=contract.created_at,
        updated_at=contract.updated_at,
    )


def income_out(db: Session, income: IncomeEntry) -> IncomeOut:
    documents = documents_for(db, "income", income.id)
    allocated = db.scalar(
        select(func.coalesce(func.sum(InvoiceAllocation.amount), 0)).where(
            InvoiceAllocation.income_id == income.id
        )
    )
    return IncomeOut(
        id=income.id,
        received_date=income.received_date,
        payer=income.payer,
        kind=income.kind,
        original_amount=income.original_amount,
        original_currency=income.original_currency,
        amount=income.amount,
        currency=income.currency,
        conversion_rate=income.conversion_rate,
        fx_estimated=income.fx_estimated,
        fx_rate_date=income.fx_rate_date,
        contract_id=income.contract_id,
        contract_title=income.contract.title if income.contract else None,
        memo=income.memo,
        allocated_amount=Decimal(allocated or 0),
        document_count=len(documents),
        documents=documents,
        created_at=income.created_at,
        updated_at=income.updated_at,
    )


def invoice_out(db: Session, invoice: Invoice, today: date | None = None) -> InvoiceOut:
    documents = documents_for(db, "invoice", invoice.id)
    paid = Decimal(
        db.scalar(
            select(func.coalesce(func.sum(InvoiceAllocation.amount), 0)).where(
                InvoiceAllocation.invoice_id == invoice.id
            )
        )
        or 0
    )
    outstanding = max(Decimal("0"), Decimal(invoice.total) - paid)
    if invoice.voided:
        invoice_status = "void"
    elif outstanding == 0:
        invoice_status = "paid"
    elif invoice.due_date < (today or date.today()):
        invoice_status = "overdue"
    elif paid > 0:
        invoice_status = "partial"
    else:
        invoice_status = "unpaid"
    return InvoiceOut(
        id=invoice.id,
        reference=invoice.reference,
        client=invoice.client,
        contract_id=invoice.contract_id,
        contract_title=invoice.contract.title if invoice.contract else None,
        issue_date=invoice.issue_date,
        due_date=invoice.due_date,
        currency=invoice.currency,
        subtotal=invoice.subtotal,
        tax_amount=invoice.tax_amount,
        total=invoice.total,
        paid_amount=paid,
        outstanding_amount=outstanding,
        status=invoice_status,
        memo=invoice.memo,
        document_count=len(documents),
        documents=documents,
        created_at=invoice.created_at,
        updated_at=invoice.updated_at,
    )


def allocate_income(
    db: Session,
    invoice: Invoice,
    income: IncomeEntry,
    amount: Decimal,
) -> InvoiceAllocation:
    if invoice.voided or invoice.deleted_at:
        raise ValueError("Cannot allocate payment to a void or deleted invoice")
    if income.deleted_at:
        raise ValueError("Income entry not found")
    if invoice.currency != income.original_currency:
        raise ValueError("Invoice and income currencies must match")
    invoice_paid = Decimal(
        db.scalar(
            select(func.coalesce(func.sum(InvoiceAllocation.amount), 0)).where(
                InvoiceAllocation.invoice_id == invoice.id
            )
        )
        or 0
    )
    income_used = Decimal(
        db.scalar(
            select(func.coalesce(func.sum(InvoiceAllocation.amount), 0)).where(
                InvoiceAllocation.income_id == income.id
            )
        )
        or 0
    )
    if invoice_paid + amount > invoice.total:
        raise ValueError("Allocation exceeds the invoice outstanding balance")
    if income_used + amount > income.original_amount:
        raise ValueError("Allocation exceeds the available income amount")
    existing = db.scalar(
        select(InvoiceAllocation).where(
            InvoiceAllocation.invoice_id == invoice.id,
            InvoiceAllocation.income_id == income.id,
        )
    )
    if existing:
        existing.amount += amount
        allocation = existing
    else:
        allocation = InvoiceAllocation(
            invoice_id=invoice.id,
            income_id=income.id,
            amount=amount,
        )
        db.add(allocation)
    db.add(
        AuditEvent(
            entity_type="invoice",
            entity_id=invoice.id,
            action="payment_allocated",
            details={"income_id": income.id, "amount": str(amount)},
        )
    )
    db.commit()
    db.refresh(allocation)
    return allocation


def nearest_occurrence_for_sender(
    db: Session,
    rule: GmailSenderRule,
    received_on: date,
) -> RecurringOccurrence | None:
    if not rule.recurring_item_id:
        return None
    earliest = received_on - timedelta(days=rule.match_window_days)
    latest = received_on + timedelta(days=rule.match_window_days)
    candidates = db.scalars(
        select(RecurringOccurrence)
        .where(
            RecurringOccurrence.recurring_item_id == rule.recurring_item_id,
            RecurringOccurrence.status == OccurrenceStatus.pending,
            RecurringOccurrence.due_date >= earliest,
            RecurringOccurrence.due_date <= latest,
        )
    ).all()
    return min(
        candidates,
        key=lambda occurrence: abs((occurrence.due_date - received_on).days),
        default=None,
    )


def financial_overview(
    db: Session,
    *,
    date_from: date,
    date_to: date,
) -> FinancialOverviewOut:
    expense_total = Decimal(
        db.scalar(
            select(func.coalesce(func.sum(Expense.amount), 0)).where(
                Expense.deleted_at.is_(None),
                Expense.status == IngestionStatus.accepted,
                Expense.expense_date >= date_from,
                Expense.expense_date <= date_to,
            )
        )
        or 0
    )
    income_total = Decimal(
        db.scalar(
            select(func.coalesce(func.sum(IncomeEntry.amount), 0)).where(
                IncomeEntry.deleted_at.is_(None),
                IncomeEntry.received_date >= date_from,
                IncomeEntry.received_date <= date_to,
            )
        )
        or 0
    )
    invoices = db.scalars(
        select(Invoice)
        .options(joinedload(Invoice.contract))
        .where(Invoice.deleted_at.is_(None), Invoice.voided.is_(False))
    ).unique().all()
    outstanding = Decimal("0")
    for invoice in invoices:
        original_outstanding = invoice_out(db, invoice).outstanding_amount
        rate, _rate_date = get_eur_rate(db, invoice.currency, invoice.issue_date)
        if rate is not None:
            outstanding += (original_outstanding * rate).quantize(Decimal("0.01"))
    occurrences = db.scalars(
        select(RecurringOccurrence)
        .options(joinedload(RecurringOccurrence.recurring_item))
        .where(RecurringOccurrence.status == OccurrenceStatus.pending)
    ).unique().all()
    due_count = sum(1 for item in occurrences if occurrence_timing(item) == "due")
    overdue_count = sum(1 for item in occurrences if occurrence_timing(item) == "overdue")
    months: dict[str, dict[str, Decimal]] = {}
    expense_rows = db.execute(
        select(Expense.expense_date, Expense.amount).where(
            Expense.deleted_at.is_(None),
            Expense.status == IngestionStatus.accepted,
            Expense.expense_date >= date_from,
            Expense.expense_date <= date_to,
        )
    ).all()
    income_rows = db.execute(
        select(IncomeEntry.received_date, IncomeEntry.amount).where(
            IncomeEntry.deleted_at.is_(None),
            IncomeEntry.received_date >= date_from,
            IncomeEntry.received_date <= date_to,
        )
    ).all()
    for when, amount in expense_rows:
        key = when.strftime("%Y-%m")
        months.setdefault(key, {"income": Decimal("0"), "expense": Decimal("0")})
        months[key]["expense"] += Decimal(amount or 0)
    for when, amount in income_rows:
        key = when.strftime("%Y-%m")
        months.setdefault(key, {"income": Decimal("0"), "expense": Decimal("0")})
        months[key]["income"] += Decimal(amount or 0)
    by_month = [
        {
            "month": key,
            "income": values["income"],
            "expense": values["expense"],
        }
        for key, values in sorted(months.items())
    ]
    return FinancialOverviewOut(
        date_from=date_from,
        date_to=date_to,
        expense_total=expense_total,
        income_total=income_total,
        net_cash_flow=income_total - expense_total,
        outstanding_receivables=outstanding,
        due_count=due_count,
        overdue_count=overdue_count,
        by_month=by_month,
    )


def next_reminder_occurrence(
    db: Session,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> tuple[RecurringOccurrence, str] | None:
    zone = ZoneInfo(settings.timezone)
    current = (now or datetime.now(timezone.utc)).astimezone(zone)
    reminder_text = get_setting_value(db, "reminder_time", "09:00")
    hour, minute = (int(value) for value in reminder_text.split(":"))
    if (current.hour, current.minute) < (hour, minute):
        return None
    materialize_occurrences(db, today=current.date())
    occurrences = db.scalars(
        select(RecurringOccurrence)
        .join(RecurringItem)
        .options(joinedload(RecurringOccurrence.recurring_item))
        .where(
            RecurringOccurrence.status == OccurrenceStatus.pending,
            RecurringItem.active.is_(True),
        )
        .order_by(RecurringOccurrence.due_date)
    ).unique().all()
    notified_item_ids: set[str] = set()
    for occurrence in occurrences:
        stamps = (
            occurrence.lead_notified_at,
            occurrence.due_notified_at,
            occurrence.last_overdue_notified_at,
        )
        if any(
            stamp
            and (stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc))
            .astimezone(zone)
            .date()
            == current.date()
            for stamp in stamps
        ):
            notified_item_ids.add(occurrence.recurring_item_id)
    for occurrence in occurrences:
        if occurrence.recurring_item_id in notified_item_ids:
            continue
        if occurrence.snoozed_until and occurrence.snoozed_until > current.date():
            continue
        lead_date = occurrence.due_date - timedelta(
            days=occurrence.recurring_item.reminder_days_before
        )
        if (
            occurrence.recurring_item.reminder_days_before > 0
            and current.date() == lead_date
            and occurrence.lead_notified_at is None
        ):
            return occurrence, "lead"
        if current.date() == occurrence.due_date and occurrence.due_notified_at is None:
            return occurrence, "due"
        if current.date() > occurrence.due_date:
            previous = occurrence.last_overdue_notified_at
            previous_date = None
            if previous:
                aware = previous if previous.tzinfo else previous.replace(tzinfo=timezone.utc)
                previous_date = aware.astimezone(zone).date()
            if previous_date is None or previous_date <= current.date() - timedelta(days=7):
                return occurrence, "overdue"
    return None


def get_setting_value(db: Session, key: str, default: str) -> str:
    from ..models import AppSetting

    item = db.get(AppSetting, key)
    return item.value if item else default


def mark_reminder_sent(
    db: Session,
    occurrence: RecurringOccurrence,
    reminder_type: str,
) -> None:
    stamp = datetime.now(timezone.utc)
    if reminder_type == "lead":
        occurrence.lead_notified_at = stamp
    elif reminder_type == "due":
        occurrence.due_notified_at = stamp
    else:
        occurrence.last_overdue_notified_at = stamp
    db.commit()
