from __future__ import annotations

import enum
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Enum, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def uuid_str() -> str:
    return str(uuid.uuid4())


class IngestionStatus(str, enum.Enum):
    queued = "queued"
    processing = "processing"
    needs_review = "needs_review"
    accepted = "accepted"
    duplicate = "duplicate"
    failed = "failed"
    cancelled = "cancelled"


class ExpenseScope(str, enum.Enum):
    personal = "personal"
    business = "business"
    unknown = "unknown"


class IncomeKind(str, enum.Enum):
    salary = "salary"
    contract = "contract"
    rental = "rental"
    interest = "interest"
    refund = "refund"
    other = "other"


class ContractStatus(str, enum.Enum):
    draft = "draft"
    active = "active"
    ended = "ended"
    cancelled = "cancelled"


class RecurringEntryType(str, enum.Enum):
    expense = "expense"
    income = "income"


class RecurrenceFrequency(str, enum.Enum):
    weekly = "weekly"
    monthly = "monthly"
    quarterly = "quarterly"
    yearly = "yearly"


class OccurrenceStatus(str, enum.Enum):
    pending = "pending"
    completed = "completed"
    skipped = "skipped"


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    scope: Mapped[ExpenseScope] = mapped_column(Enum(ExpenseScope), default=ExpenseScope.unknown)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    color: Mapped[str] = mapped_column(String(16), default="#7A365D")
    icon: Mapped[str] = mapped_column(String(32), default="category")
    quickbooks_category: Mapped[str | None] = mapped_column(String(180), nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PaymentMethod(Base):
    __tablename__ = "payment_methods"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    method_type: Mapped[str] = mapped_column(String(40), default="card")
    last_four: Mapped[str | None] = mapped_column(String(4), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Receipt(Base):
    __tablename__ = "receipts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_path: Mapped[str] = mapped_column(Text)
    preview_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_count: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Ingestion(Base):
    __tablename__ = "ingestions"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_ingestion_source_external"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    receipt_id: Mapped[str] = mapped_column(ForeignKey("receipts.id"), index=True)
    expense_id: Mapped[str | None] = mapped_column(ForeignKey("expenses.id"), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
    external_id: Mapped[str] = mapped_column(String(180))
    source_user_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_chat_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[IngestionStatus] = mapped_column(Enum(IngestionStatus), default=IngestionStatus.queued, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    raw_extraction: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notification_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    reprocess_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    merged_into_ingestion_id: Mapped[str | None] = mapped_column(
        ForeignKey("ingestions.id"),
        nullable=True,
        index=True,
    )
    recurring_occurrence_id: Mapped[str | None] = mapped_column(
        ForeignKey("recurring_occurrences.id"),
        nullable=True,
        index=True,
    )
    gmail_message_import_id: Mapped[str | None] = mapped_column(
        ForeignKey("gmail_message_imports.id"),
        nullable=True,
        index=True,
    )

    receipt: Mapped[Receipt] = relationship()
    documents: Mapped[list[IngestionDocument]] = relationship(
        back_populates="ingestion",
        cascade="all, delete-orphan",
        order_by="IngestionDocument.position",
    )

    @property
    def document_count(self) -> int:
        return len(self.documents)


class IngestionDocument(Base):
    __tablename__ = "ingestion_documents"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_ingestion_document_source_external"),
        UniqueConstraint("ingestion_id", "receipt_id", name="uq_ingestion_document_receipt"),
        Index("ix_ingestion_documents_ingestion_position", "ingestion_id", "position"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    ingestion_id: Mapped[str] = mapped_column(ForeignKey("ingestions.id"), index=True)
    receipt_id: Mapped[str] = mapped_column(ForeignKey("receipts.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(32), index=True)
    external_id: Mapped[str] = mapped_column(String(180))
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    ingestion: Mapped[Ingestion] = relationship(back_populates="documents")
    receipt: Mapped[Receipt] = relationship()


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    expense_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    merchant: Mapped[str | None] = mapped_column(String(180), nullable=True, index=True)
    merchant_normalized: Mapped[str | None] = mapped_column(String(180), nullable=True, index=True)
    original_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    original_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    conversion_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    fx_estimated: Mapped[bool] = mapped_column(Boolean, default=False)
    fx_rate_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    category_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id"), nullable=True, index=True)
    payment_method_id: Mapped[str | None] = mapped_column(ForeignKey("payment_methods.id"), nullable=True)
    scope: Mapped[ExpenseScope] = mapped_column(Enum(ExpenseScope), default=ExpenseScope.unknown, index=True)
    location: Mapped[str | None] = mapped_column(String(180), nullable=True)
    department: Mapped[str | None] = mapped_column(String(180), nullable=True)
    trip_name: Mapped[str | None] = mapped_column(String(180), nullable=True)
    refundable: Mapped[bool] = mapped_column(Boolean, default=False)
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Numeric(5, 4), default=0)
    # These fields deliberately describe *how* a category was chosen.  They are
    # not part of the category itself, so a later rule/category edit cannot
    # rewrite the provenance of an already recorded expense.
    categorization_source: Mapped[str] = mapped_column(String(32), default="ai")
    category_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[IngestionStatus] = mapped_column(Enum(IngestionStatus), default=IngestionStatus.needs_review, index=True)
    quickbooks_category: Mapped[str | None] = mapped_column(String(180), nullable=True)
    quickbooks_class: Mapped[str | None] = mapped_column(String(180), nullable=True)
    quickbooks_customer_job: Mapped[str | None] = mapped_column(String(180), nullable=True)
    quickbooks_location: Mapped[str | None] = mapped_column(String(180), nullable=True)
    quickbooks_subprogram: Mapped[str | None] = mapped_column(String(180), nullable=True)
    quickbooks_vendor: Mapped[str | None] = mapped_column(String(180), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    category: Mapped[Category | None] = relationship()
    payment_method: Mapped[PaymentMethod | None] = relationship()


class Contract(Base):
    __tablename__ = "contracts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    title: Mapped[str] = mapped_column(String(180), index=True)
    counterparty: Mapped[str] = mapped_column(String(180), index=True)
    reference: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[ContractStatus] = mapped_column(Enum(ContractStatus), default=ContractStatus.active, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class IncomeEntry(Base):
    __tablename__ = "income_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    received_date: Mapped[date] = mapped_column(Date, index=True)
    payer: Mapped[str] = mapped_column(String(180), index=True)
    kind: Mapped[IncomeKind] = mapped_column(Enum(IncomeKind), default=IncomeKind.other, index=True)
    original_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    original_currency: Mapped[str] = mapped_column(String(3))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    conversion_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    fx_estimated: Mapped[bool] = mapped_column(Boolean, default=False)
    fx_rate_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    contract_id: Mapped[str | None] = mapped_column(ForeignKey("contracts.id"), nullable=True, index=True)
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    contract: Mapped[Contract | None] = relationship()


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    reference: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    client: Mapped[str] = mapped_column(String(180), index=True)
    contract_id: Mapped[str | None] = mapped_column(ForeignKey("contracts.id"), nullable=True, index=True)
    issue_date: Mapped[date] = mapped_column(Date, index=True)
    due_date: Mapped[date] = mapped_column(Date, index=True)
    currency: Mapped[str] = mapped_column(String(3))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    total: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    voided: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    contract: Mapped[Contract | None] = relationship()


class InvoiceAllocation(Base):
    __tablename__ = "invoice_allocations"
    __table_args__ = (
        UniqueConstraint("invoice_id", "income_id", name="uq_invoice_allocation_pair"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoices.id"), index=True)
    income_id: Mapped[str] = mapped_column(ForeignKey("income_entries.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RecurringItem(Base):
    __tablename__ = "recurring_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String(180), index=True)
    entry_type: Mapped[RecurringEntryType] = mapped_column(Enum(RecurringEntryType), index=True)
    counterparty: Mapped[str] = mapped_column(String(180))
    expected_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    frequency: Mapped[RecurrenceFrequency] = mapped_column(Enum(RecurrenceFrequency))
    start_date: Mapped[date] = mapped_column(Date, index=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    reminder_days_before: Mapped[int] = mapped_column(Integer, default=0)
    category_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    payment_method_id: Mapped[str | None] = mapped_column(ForeignKey("payment_methods.id"), nullable=True)
    scope: Mapped[ExpenseScope] = mapped_column(Enum(ExpenseScope), default=ExpenseScope.unknown)
    income_kind: Mapped[IncomeKind | None] = mapped_column(Enum(IncomeKind), nullable=True)
    contract_id: Mapped[str | None] = mapped_column(ForeignKey("contracts.id"), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    category: Mapped[Category | None] = relationship()
    payment_method: Mapped[PaymentMethod | None] = relationship()
    contract: Mapped[Contract | None] = relationship()


class RecurringOccurrence(Base):
    __tablename__ = "recurring_occurrences"
    __table_args__ = (
        UniqueConstraint("recurring_item_id", "due_date", name="uq_recurring_occurrence_due"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    recurring_item_id: Mapped[str] = mapped_column(ForeignKey("recurring_items.id"), index=True)
    due_date: Mapped[date] = mapped_column(Date, index=True)
    expected_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[OccurrenceStatus] = mapped_column(Enum(OccurrenceStatus), default=OccurrenceStatus.pending, index=True)
    actual_expense_id: Mapped[str | None] = mapped_column(ForeignKey("expenses.id"), nullable=True, index=True)
    actual_income_id: Mapped[str | None] = mapped_column(ForeignKey("income_entries.id"), nullable=True, index=True)
    lead_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    due_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_overdue_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    snoozed_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    recurring_item: Mapped[RecurringItem] = relationship()


class SupportingDocument(Base):
    __tablename__ = "supporting_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_path: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DocumentLink(Base):
    __tablename__ = "document_links"
    __table_args__ = (
        CheckConstraint(
            "(expense_id IS NOT NULL) + (income_id IS NOT NULL) + "
            "(contract_id IS NOT NULL) + (invoice_id IS NOT NULL) + "
            "(recurring_occurrence_id IS NOT NULL) = 1",
            name="ck_document_link_one_target",
        ),
        UniqueConstraint(
            "document_id",
            "expense_id",
            "income_id",
            "contract_id",
            "invoice_id",
            "recurring_occurrence_id",
            name="uq_document_link_target",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    document_id: Mapped[str] = mapped_column(ForeignKey("supporting_documents.id"), index=True)
    expense_id: Mapped[str | None] = mapped_column(ForeignKey("expenses.id"), nullable=True, index=True)
    income_id: Mapped[str | None] = mapped_column(ForeignKey("income_entries.id"), nullable=True, index=True)
    contract_id: Mapped[str | None] = mapped_column(ForeignKey("contracts.id"), nullable=True, index=True)
    invoice_id: Mapped[str | None] = mapped_column(ForeignKey("invoices.id"), nullable=True, index=True)
    recurring_occurrence_id: Mapped[str | None] = mapped_column(ForeignKey("recurring_occurrences.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    document: Mapped[SupportingDocument] = relationship()


class GmailConnection(Base):
    __tablename__ = "gmail_connections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    email_address: Mapped[str] = mapped_column(String(320), unique=True)
    encrypted_refresh_token: Mapped[str] = mapped_column(Text)
    history_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="connected", index=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class GmailSenderRule(Base):
    __tablename__ = "gmail_sender_rules"
    __table_args__ = (
        UniqueConstraint("connection_id", "sender_address", name="uq_gmail_sender_rule_address"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    connection_id: Mapped[str] = mapped_column(ForeignKey("gmail_connections.id"), index=True)
    sender_address: Mapped[str] = mapped_column(String(320), index=True)
    recurring_item_id: Mapped[str | None] = mapped_column(ForeignKey("recurring_items.id"), nullable=True)
    category_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    scope: Mapped[ExpenseScope | None] = mapped_column(Enum(ExpenseScope), nullable=True)
    match_window_days: Mapped[int] = mapped_column(Integer, default=45)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GmailMessageImport(Base):
    __tablename__ = "gmail_message_imports"
    __table_args__ = (
        UniqueConstraint("connection_id", "gmail_message_id", name="uq_gmail_message_import"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    connection_id: Mapped[str] = mapped_column(ForeignKey("gmail_connections.id"), index=True)
    sender_rule_id: Mapped[str] = mapped_column(ForeignKey("gmail_sender_rules.id"), index=True)
    gmail_message_id: Mapped[str] = mapped_column(String(180), index=True)
    gmail_thread_id: Mapped[str | None] = mapped_column(String(180), nullable=True)
    subject: Mapped[str] = mapped_column(String(500), default="")
    sender_address: Mapped[str] = mapped_column(String(320))
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    ingestion_id: Mapped[str | None] = mapped_column(ForeignKey("ingestions.id"), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MerchantRule(Base):
    __tablename__ = "merchant_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    merchant_normalized: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    merchant_display: Mapped[str] = mapped_column(String(180))
    category_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    payment_method_id: Mapped[str | None] = mapped_column(ForeignKey("payment_methods.id"), nullable=True)
    scope: Mapped[ExpenseScope | None] = mapped_column(Enum(ExpenseScope), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    conflict_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    category: Mapped[Category | None] = relationship()
    payment_method: Mapped[PaymentMethod | None] = relationship()


class FxRate(Base):
    __tablename__ = "fx_rates"
    __table_args__ = (UniqueConstraint("currency", "rate_date", name="uq_fx_currency_date"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    currency: Mapped[str] = mapped_column(String(3), index=True)
    rate_date: Mapped[date] = mapped_column(Date, index=True)
    eur_per_unit: Mapped[Decimal] = mapped_column(Numeric(18, 10))
    source: Mapped[str] = mapped_column(String(40), default="ECB")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    entity_type: Mapped[str] = mapped_column(String(40), index=True)
    entity_id: Mapped[str] = mapped_column(String(36), index=True)
    action: Mapped[str] = mapped_column(String(80))
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ConversationSession(Base):
    """Canonical, provider-independent Telegram chat state.

    A user can change AI providers without losing the useful local receipt
    anchor or bounded message history.  There is one session per private chat.
    """

    __tablename__ = "conversation_sessions"
    __table_args__ = (UniqueConstraint("telegram_chat_id", name="uq_conversation_session_chat"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    telegram_chat_id: Mapped[str] = mapped_column(String(120), index=True)
    telegram_user_id: Mapped[str] = mapped_column(String(120), index=True)
    active_ingestion_id: Mapped[str | None] = mapped_column(ForeignKey("ingestions.id"), nullable=True)
    active_expense_id: Mapped[str | None] = mapped_column(ForeignKey("expenses.id"), nullable=True)
    active_occurrence_id: Mapped[str | None] = mapped_column(
        ForeignKey("recurring_occurrences.id"),
        nullable=True,
    )
    attachment_target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    attachment_target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"
    __table_args__ = (Index("ix_conversation_messages_session_created", "session_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    session_id: Mapped[str] = mapped_column(ForeignKey("conversation_sessions.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user or assistant
    content: Mapped[str] = mapped_column(Text)
    approximate_tokens: Mapped[int] = mapped_column(Integer, default=0)
    telegram_message_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChatJob(Base):
    """Durable plain-text Telegram work item.

    The unique Telegram message key makes long polling retries harmless.
    """

    __tablename__ = "chat_jobs"
    __table_args__ = (
        UniqueConstraint("telegram_chat_id", "telegram_message_id", name="uq_chat_job_telegram_message"),
        Index("ix_chat_jobs_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    session_id: Mapped[str] = mapped_column(ForeignKey("conversation_sessions.id"), index=True)
    telegram_chat_id: Mapped[str] = mapped_column(String(120), index=True)
    telegram_user_id: Mapped[str] = mapped_column(String(120))
    telegram_message_id: Mapped[str] = mapped_column(String(120))
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    pending_action_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    export_request: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    response_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PendingAction(Base):
    """A one-use, owner-bound confirmation for destructive/bulk chat actions."""

    __tablename__ = "pending_actions"
    __table_args__ = (Index("ix_pending_actions_expiry", "expires_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    telegram_chat_id: Mapped[str] = mapped_column(String(120), index=True)
    telegram_user_id: Mapped[str] = mapped_column(String(120), index=True)
    action_type: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
