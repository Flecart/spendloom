from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import (
    ContractStatus,
    ExpenseScope,
    IncomeKind,
    IngestionStatus,
    OccurrenceStatus,
    RecurrenceFrequency,
    RecurringEntryType,
)


class ReceiptExtraction(BaseModel):
    expense_date: str | None = Field(description="Receipt date in YYYY-MM-DD format")
    merchant: str | None
    original_amount: str | None = Field(description="Final paid total as a decimal string")
    original_currency: str | None = Field(description="Three-letter ISO 4217 currency code")
    category_code: str | None = Field(description="One code from the supplied category list")
    scope: Literal["personal", "business", "unknown"] = "unknown"
    payment_last_four: str | None = None
    payment_method_text: str | None = None
    location: str | None = None
    memo: str | None = None
    category_reason: str | None = Field(default=None, max_length=600, description="Short evidence-based reason for the selected category")
    confidence: float = Field(default=0, ge=0, le=1)

    @field_validator("original_currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.upper().strip() if value else None


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    code: str
    name: str
    scope: ExpenseScope
    color: str
    icon: str
    quickbooks_category: str | None
    archived: bool


class CategoryCreate(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=120)
    scope: ExpenseScope = ExpenseScope.unknown
    color: str = "#7A365D"
    icon: str = "category"
    quickbooks_category: str | None = None


class CategoryUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=32)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    scope: ExpenseScope | None = None
    color: str | None = Field(default=None, max_length=16)
    icon: str | None = Field(default=None, max_length=32)
    quickbooks_category: str | None = Field(default=None, max_length=180)
    archived: bool | None = None


class PaymentMethodOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    method_type: str
    last_four: str | None
    is_default: bool
    archived: bool


class PaymentMethodCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    method_type: str = "card"
    last_four: str | None = Field(default=None, pattern=r"^\d{4}$")
    is_default: bool = False


class PaymentMethodUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    method_type: str | None = Field(default=None, min_length=1, max_length=40)
    last_four: str | None = Field(default=None, pattern=r"^\d{4}$")
    is_default: bool | None = None
    archived: bool | None = None


class ReceiptDocumentOut(BaseModel):
    receipt_id: str
    filename: str
    mime_type: str
    size_bytes: int
    page_count: int
    position: int
    file_url: str
    preview_url: str | None


class ExpenseOut(BaseModel):
    id: str
    expense_date: date | None
    merchant: str | None
    original_amount: Decimal | None
    original_currency: str | None
    amount: Decimal | None
    currency: str
    conversion_rate: Decimal | None
    fx_estimated: bool
    fx_rate_date: date | None
    category_id: str | None
    category_name: str | None
    payment_method_id: str | None
    payment_method_name: str | None
    scope: ExpenseScope
    location: str | None
    department: str | None
    trip_name: str | None
    refundable: bool
    memo: str | None
    confidence: float
    categorization_source: str
    category_reason: str | None
    status: IngestionStatus
    quickbooks_category: str | None
    quickbooks_class: str | None
    quickbooks_customer_job: str | None
    quickbooks_location: str | None
    quickbooks_subprogram: str | None
    quickbooks_vendor: str | None
    receipt_id: str | None
    receipt_filename: str | None
    receipt_url: str | None
    source: str | None
    ingestion_id: str | None
    document_count: int
    documents: list[ReceiptDocumentOut]
    supporting_documents: list["SupportingDocumentOut"] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ExpenseUpdate(BaseModel):
    expense_date: date | None = None
    merchant: str | None = None
    original_amount: Decimal | None = None
    original_currency: str | None = Field(default=None, min_length=3, max_length=3)
    category_id: str | None = None
    payment_method_id: str | None = None
    scope: ExpenseScope | None = None
    location: str | None = None
    department: str | None = None
    trip_name: str | None = None
    refundable: bool | None = None
    memo: str | None = None
    category_reason: str | None = Field(default=None, max_length=600)
    quickbooks_category: str | None = None
    quickbooks_class: str | None = None
    quickbooks_customer_job: str | None = None
    quickbooks_location: str | None = None
    quickbooks_subprogram: str | None = None
    quickbooks_vendor: str | None = None
    accept: bool = False
    remember_merchant: bool = False


class ReimbursementExportRequest(BaseModel):
    expense_ids: list[str] = Field(min_length=1, max_length=1000)


class IngestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    expense_id: str | None
    source: str
    external_id: str
    status: IngestionStatus
    attempts: int
    error_code: str | None
    error_message: str | None
    received_at: datetime
    processed_at: datetime | None
    document_count: int
    merged_into_ingestion_id: str | None


class MerchantRuleOut(BaseModel):
    id: str
    merchant_display: str
    merchant_normalized: str
    category_id: str | None
    category_name: str | None
    payment_method_id: str | None
    payment_method_name: str | None
    scope: ExpenseScope | None
    enabled: bool
    conflict_count: int


class MerchantRuleCreate(BaseModel):
    merchant_display: str = Field(min_length=1, max_length=180)
    merchant_normalized: str | None = Field(default=None, max_length=180)
    category_id: str | None = None
    payment_method_id: str | None = None
    scope: ExpenseScope | None = None
    enabled: bool = True


class MerchantRuleUpdate(BaseModel):
    merchant_display: str | None = Field(default=None, min_length=1, max_length=180)
    merchant_normalized: str | None = Field(default=None, min_length=1, max_length=180)
    category_id: str | None = None
    payment_method_id: str | None = None
    scope: ExpenseScope | None = None
    enabled: bool | None = None


class SettingsOut(BaseModel):
    owner_name: str
    owner_email: str
    review_mode: str
    confidence_threshold: float
    telegram_claim_code: str
    telegram_claimed: bool
    telegram_allowlist_configured: bool
    ai_provider: str
    ai_model: str
    ai_configured: bool
    ai_auth_label: str
    base_currency: str
    timezone: str
    reminder_time: str
    gmail_configured: bool
    gmail_connected: bool


class SettingsUpdate(BaseModel):
    owner_name: str | None = None
    owner_email: str | None = None
    review_mode: Literal["uncertain", "always", "never"] | None = None
    confidence_threshold: float | None = Field(default=None, ge=0, le=1)
    reminder_time: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class DashboardOut(BaseModel):
    # Legacy aliases remain for existing clients.  New clients should use the
    # range names so a label never implies a calendar-month-only calculation.
    month_total: Decimal
    previous_month_total: Decimal
    range_total: Decimal
    previous_range_total: Decimal
    date_from: date
    date_to: date
    review_count: int
    failed_count: int
    receipt_count: int
    by_category: list[dict]
    by_month: list[dict]
    by_period: list[dict]
    trend_granularity: Literal["day", "week"]
    top_merchants: list[dict]


class SupportingDocumentOut(BaseModel):
    id: str
    filename: str
    mime_type: str
    size_bytes: int
    file_url: str


class ContractCreate(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    counterparty: str = Field(min_length=1, max_length=180)
    reference: str | None = Field(default=None, max_length=120)
    start_date: date | None = None
    end_date: date | None = None
    status: ContractStatus = ContractStatus.active
    notes: str | None = Field(default=None, max_length=10_000)

    @model_validator(mode="after")
    def validate_dates(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("Contract end date cannot be before its start date")
        return self


class ContractUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=180)
    counterparty: str | None = Field(default=None, min_length=1, max_length=180)
    reference: str | None = Field(default=None, max_length=120)
    start_date: date | None = None
    end_date: date | None = None
    status: ContractStatus | None = None
    notes: str | None = Field(default=None, max_length=10_000)


class ContractOut(BaseModel):
    id: str
    title: str
    counterparty: str
    reference: str | None
    start_date: date | None
    end_date: date | None
    status: ContractStatus
    notes: str | None
    document_count: int
    documents: list[SupportingDocumentOut]
    created_at: datetime
    updated_at: datetime


class IncomeCreate(BaseModel):
    received_date: date
    payer: str = Field(min_length=1, max_length=180)
    kind: IncomeKind = IncomeKind.other
    original_amount: Decimal = Field(gt=0)
    original_currency: str = Field(min_length=3, max_length=3)
    contract_id: str | None = None
    memo: str | None = Field(default=None, max_length=10_000)
    occurrence_id: str | None = None

    @field_validator("original_currency")
    @classmethod
    def normalize_income_currency(cls, value: str) -> str:
        return value.strip().upper()


class IncomeUpdate(BaseModel):
    received_date: date | None = None
    payer: str | None = Field(default=None, min_length=1, max_length=180)
    kind: IncomeKind | None = None
    original_amount: Decimal | None = Field(default=None, gt=0)
    original_currency: str | None = Field(default=None, min_length=3, max_length=3)
    contract_id: str | None = None
    memo: str | None = Field(default=None, max_length=10_000)

    @field_validator("original_currency")
    @classmethod
    def normalize_optional_income_currency(cls, value: str | None) -> str | None:
        return value.strip().upper() if value else None


class IncomeOut(BaseModel):
    id: str
    received_date: date
    payer: str
    kind: IncomeKind
    original_amount: Decimal
    original_currency: str
    amount: Decimal | None
    currency: str
    conversion_rate: Decimal | None
    fx_estimated: bool
    fx_rate_date: date | None
    contract_id: str | None
    contract_title: str | None
    memo: str | None
    allocated_amount: Decimal
    document_count: int
    documents: list[SupportingDocumentOut]
    created_at: datetime
    updated_at: datetime


class InvoiceCreate(BaseModel):
    reference: str = Field(min_length=1, max_length=120)
    client: str = Field(min_length=1, max_length=180)
    contract_id: str | None = None
    issue_date: date
    due_date: date
    currency: str = Field(min_length=3, max_length=3)
    subtotal: Decimal = Field(ge=0)
    tax_amount: Decimal = Field(default=Decimal("0"), ge=0)
    total: Decimal = Field(gt=0)
    memo: str | None = Field(default=None, max_length=10_000)

    @field_validator("currency")
    @classmethod
    def normalize_invoice_currency(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def validate_invoice(self):
        if self.due_date < self.issue_date:
            raise ValueError("Invoice due date cannot be before its issue date")
        if abs((self.subtotal + self.tax_amount) - self.total) > Decimal("0.01"):
            raise ValueError("Invoice subtotal plus tax must equal its total")
        return self


class InvoiceUpdate(BaseModel):
    reference: str | None = Field(default=None, min_length=1, max_length=120)
    client: str | None = Field(default=None, min_length=1, max_length=180)
    contract_id: str | None = None
    issue_date: date | None = None
    due_date: date | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    subtotal: Decimal | None = Field(default=None, ge=0)
    tax_amount: Decimal | None = Field(default=None, ge=0)
    total: Decimal | None = Field(default=None, gt=0)
    memo: str | None = Field(default=None, max_length=10_000)
    voided: bool | None = None

    @field_validator("currency")
    @classmethod
    def normalize_optional_invoice_currency(cls, value: str | None) -> str | None:
        return value.strip().upper() if value else None


class InvoiceAllocationCreate(BaseModel):
    income_id: str
    amount: Decimal = Field(gt=0)


class InvoiceOut(BaseModel):
    id: str
    reference: str
    client: str
    contract_id: str | None
    contract_title: str | None
    issue_date: date
    due_date: date
    currency: str
    subtotal: Decimal
    tax_amount: Decimal
    total: Decimal
    paid_amount: Decimal
    outstanding_amount: Decimal
    status: Literal["unpaid", "partial", "paid", "overdue", "void"]
    memo: str | None
    document_count: int
    documents: list[SupportingDocumentOut]
    created_at: datetime
    updated_at: datetime


class RecurringItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    entry_type: RecurringEntryType
    counterparty: str = Field(min_length=1, max_length=180)
    expected_amount: Decimal | None = Field(default=None, gt=0)
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    frequency: RecurrenceFrequency
    start_date: date
    end_date: date | None = None
    reminder_days_before: int = Field(default=0, ge=0, le=365)
    category_id: str | None = None
    payment_method_id: str | None = None
    scope: ExpenseScope = ExpenseScope.unknown
    income_kind: IncomeKind | None = None
    contract_id: str | None = None

    @field_validator("currency")
    @classmethod
    def normalize_recurring_currency(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def validate_recurring(self):
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("Recurring end date cannot be before its start date")
        if self.entry_type == RecurringEntryType.income and (
            self.category_id or self.payment_method_id
        ):
            raise ValueError(
                "Income schedules cannot use expense categories or payment methods"
            )
        return self


class RecurringItemUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=180)
    counterparty: str | None = Field(default=None, min_length=1, max_length=180)
    expected_amount: Decimal | None = Field(default=None, gt=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    frequency: RecurrenceFrequency | None = None
    start_date: date | None = None
    end_date: date | None = None
    reminder_days_before: int | None = Field(default=None, ge=0, le=365)
    category_id: str | None = None
    payment_method_id: str | None = None
    scope: ExpenseScope | None = None
    income_kind: IncomeKind | None = None
    contract_id: str | None = None
    active: bool | None = None

    @field_validator("currency")
    @classmethod
    def normalize_optional_recurring_currency(cls, value: str | None) -> str | None:
        return value.strip().upper() if value else None


class RecurringItemOut(BaseModel):
    id: str
    name: str
    entry_type: RecurringEntryType
    counterparty: str
    expected_amount: Decimal | None
    currency: str
    frequency: RecurrenceFrequency
    start_date: date
    end_date: date | None
    reminder_days_before: int
    category_id: str | None
    payment_method_id: str | None
    scope: ExpenseScope
    income_kind: IncomeKind | None
    contract_id: str | None
    active: bool
    next_due_date: date | None


class RecurringOccurrenceOut(BaseModel):
    id: str
    recurring_item_id: str
    recurring_item_name: str
    entry_type: RecurringEntryType
    counterparty: str
    due_date: date
    expected_amount: Decimal | None
    currency: str
    status: OccurrenceStatus
    timing: Literal["upcoming", "due", "overdue", "completed", "skipped"]
    actual_expense_id: str | None
    actual_income_id: str | None
    snoozed_until: date | None


class OccurrenceComplete(BaseModel):
    amount: Decimal | None = Field(default=None, gt=0)
    occurred_on: date | None = None


class OccurrenceSnooze(BaseModel):
    days: int = Field(default=7, ge=1, le=90)


class FinancialOverviewOut(BaseModel):
    date_from: date
    date_to: date
    expense_total: Decimal
    income_total: Decimal
    net_cash_flow: Decimal
    outstanding_receivables: Decimal
    due_count: int
    overdue_count: int
    by_month: list[dict]


class GmailSenderRuleCreate(BaseModel):
    sender_address: str = Field(min_length=3, max_length=320)
    recurring_item_id: str | None = None
    category_id: str | None = None
    scope: ExpenseScope | None = None
    match_window_days: int = Field(default=45, ge=1, le=365)

    @field_validator("sender_address")
    @classmethod
    def normalize_sender(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized:
            raise ValueError("Enter a complete sender email address")
        return normalized


class GmailSenderRuleUpdate(BaseModel):
    recurring_item_id: str | None = None
    category_id: str | None = None
    scope: ExpenseScope | None = None
    match_window_days: int | None = Field(default=None, ge=1, le=365)
    enabled: bool | None = None


class GmailSenderRuleOut(BaseModel):
    id: str
    sender_address: str
    recurring_item_id: str | None
    recurring_item_name: str | None
    category_id: str | None
    scope: ExpenseScope | None
    match_window_days: int
    enabled: bool


class GmailStatusOut(BaseModel):
    configured: bool
    connected: bool
    email_address: str | None
    status: str
    last_synced_at: datetime | None
    error_message: str | None
    sender_rules: list[GmailSenderRuleOut]
