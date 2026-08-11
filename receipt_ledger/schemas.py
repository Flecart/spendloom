from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import ExpenseScope, IngestionStatus


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
    base_currency: str


class SettingsUpdate(BaseModel):
    owner_name: str | None = None
    owner_email: str | None = None
    review_mode: Literal["uncertain", "always", "never"] | None = None
    confidence_threshold: float | None = Field(default=None, ge=0, le=1)


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
    top_merchants: list[dict]
