from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import (
    AppSetting,
    AuditEvent,
    Category,
    Expense,
    ExpenseScope,
    Ingestion,
    IngestionStatus,
    MerchantRule,
    PaymentMethod,
)
from ..schemas import ReceiptExtraction
from .extraction import ProviderNotConfigured, build_prompt, provider_for
from .fx import get_eur_rate
from .storage import InvalidReceiptFile, prepare_visuals

logger = logging.getLogger(__name__)


def normalize_merchant(value: str | None) -> str | None:
    if not value:
        return None
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    suffixes = {"ltd", "limited", "inc", "llc", "plc", "gmbh", "sa", "srl"}
    tokens = [token for token in normalized.split() if token not in suffixes]
    return " ".join(tokens)[:180] or normalized[:180]


def parse_decimal(value: str | None) -> Decimal | None:
    if not value:
        return None
    text = re.sub(r"[^0-9,.-]", "", value.strip())
    if not text:
        return None
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        tail = text.rsplit(",", 1)[-1]
        text = text.replace(",", ".") if len(tail) in {1, 2} else text.replace(",", "")
    try:
        return abs(Decimal(text))
    except InvalidOperation:
        return None


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def get_setting(db: Session, key: str, default: str = "") -> str:
    item = db.get(AppSetting, key)
    return item.value if item else default


def _default_payment(db: Session) -> PaymentMethod | None:
    return db.scalar(select(PaymentMethod).where(PaymentMethod.is_default.is_(True), PaymentMethod.archived.is_(False))) or db.scalar(
        select(PaymentMethod).where(PaymentMethod.archived.is_(False)).limit(1)
    )


def _payment_from_extraction(db: Session, extracted: ReceiptExtraction) -> PaymentMethod | None:
    if extracted.payment_last_four:
        match = db.scalar(
            select(PaymentMethod).where(
                PaymentMethod.last_four == extracted.payment_last_four[-4:], PaymentMethod.archived.is_(False)
            )
        )
        if match:
            return match
    if extracted.payment_method_text:
        needle = extracted.payment_method_text.lower().strip()
        methods = db.scalars(select(PaymentMethod).where(PaymentMethod.archived.is_(False))).all()
        for method in methods:
            if method.name.lower() in needle or needle in method.name.lower():
                return method
    return _default_payment(db)


def process_ingestion(db: Session, settings: Settings, ingestion_id: str) -> Ingestion:
    ingestion = db.get(Ingestion, ingestion_id)
    if not ingestion or ingestion.status not in {IngestionStatus.queued, IngestionStatus.processing}:
        return ingestion

    ingestion.status = IngestionStatus.processing
    ingestion.attempts += 1
    ingestion.provider = settings.ai_provider
    ingestion.model = settings.ai_model
    ingestion.error_code = None
    ingestion.error_message = None
    db.commit()

    try:
        receipt = ingestion.receipt
        images, preview_path, page_count, embedded_text = prepare_visuals(
            settings, receipt.id, receipt.storage_path, receipt.mime_type
        )
        receipt.preview_path = preview_path
        receipt.page_count = page_count
        categories = db.scalars(select(Category).where(Category.archived.is_(False))).all()
        prompt_categories = [(item.code, item.name, item.scope.value) for item in categories]
        prompt = build_prompt(prompt_categories, ingestion.caption, embedded_text)
        extracted = provider_for(settings).extract(prompt, images)
        ingestion.raw_extraction = extracted.model_dump(mode="json")
        _create_expense(db, settings, ingestion, extracted, categories)
    except ProviderNotConfigured as exc:
        logger.warning("AI provider is not configured; creating manual-review expense")
        ingestion.error_code = "ai_not_configured"
        ingestion.error_message = str(exc)
        _create_expense(db, settings, ingestion, ReceiptExtraction(
            expense_date=None,
            merchant=None,
            original_amount=None,
            original_currency=None,
            category_code=None,
            scope="unknown",
            memo=ingestion.caption,
            confidence=0,
        ), [])
    except InvalidReceiptFile as exc:
        ingestion.status = IngestionStatus.failed
        ingestion.error_code = "invalid_document"
        ingestion.error_message = str(exc)
        ingestion.processed_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:  # worker boundary: retain the job and a sanitized error
        logger.exception("Receipt processing failed for ingestion %s", ingestion.id)
        ingestion.error_code = "processing_error"
        ingestion.error_message = str(exc)[:500]
        if ingestion.attempts >= 3:
            ingestion.status = IngestionStatus.failed
            ingestion.processed_at = datetime.now(timezone.utc)
        else:
            ingestion.status = IngestionStatus.queued
        db.commit()
    return ingestion


def _create_expense(
    db: Session,
    settings: Settings,
    ingestion: Ingestion,
    extracted: ReceiptExtraction,
    categories: list[Category],
) -> None:
    merchant = extracted.merchant.strip()[:180] if extracted.merchant else None
    merchant_normalized = normalize_merchant(merchant)
    amount_original = parse_decimal(extracted.original_amount)
    expense_date = parse_date(extracted.expense_date)
    currency = extracted.original_currency.upper() if extracted.original_currency else None
    category = next((item for item in categories if item.code == extracted.category_code), None)
    payment = _payment_from_extraction(db, extracted)
    try:
        scope = ExpenseScope(extracted.scope)
    except ValueError:
        scope = ExpenseScope.unknown

    rule = None
    categorization_source = "ai"
    category_reason = extracted.category_reason
    if merchant_normalized:
        rule = db.scalar(
            select(MerchantRule).where(
                MerchantRule.merchant_normalized == merchant_normalized, MerchantRule.enabled.is_(True)
            )
        )
    if rule:
        categorization_source = "merchant_rule"
        category_reason = f"Matched the enabled merchant rule for {rule.merchant_display}."
        if rule.category_id:
            category = db.get(Category, rule.category_id)
        if rule.payment_method_id:
            payment = db.get(PaymentMethod, rule.payment_method_id)
        if rule.scope:
            scope = rule.scope

    normalized_amount = None
    conversion_rate = None
    fx_date = None
    if amount_original is not None and currency and expense_date:
        conversion_rate, fx_date = get_eur_rate(db, currency, expense_date)
        if conversion_rate is not None:
            normalized_amount = (amount_original * conversion_rate).quantize(Decimal("0.01"))

    threshold = float(get_setting(db, "confidence_threshold", str(settings.confidence_threshold)))
    review_mode = get_setting(db, "review_mode", "uncertain")
    required_complete = all([expense_date, merchant, amount_original is not None, currency, category, normalized_amount is not None])
    if review_mode == "always":
        status = IngestionStatus.needs_review
    elif review_mode == "never" and required_complete:
        status = IngestionStatus.accepted
    else:
        status = IngestionStatus.accepted if required_complete and extracted.confidence >= threshold else IngestionStatus.needs_review

    duplicate_match = None
    if expense_date and merchant_normalized and amount_original is not None and currency:
        duplicate_match = db.scalar(
            select(Expense).where(
                Expense.deleted_at.is_(None),
                Expense.expense_date == expense_date,
                Expense.merchant_normalized == merchant_normalized,
                Expense.original_amount == amount_original,
                Expense.original_currency == currency,
            ).limit(1)
        )
    if duplicate_match:
        status = IngestionStatus.duplicate

    expense = Expense(
        expense_date=expense_date,
        merchant=merchant,
        merchant_normalized=merchant_normalized,
        original_amount=amount_original,
        original_currency=currency,
        amount=normalized_amount,
        currency=settings.base_currency,
        conversion_rate=conversion_rate,
        fx_estimated=bool(fx_date and expense_date and fx_date != expense_date),
        fx_rate_date=fx_date,
        category_id=category.id if category else None,
        payment_method_id=payment.id if payment else None,
        scope=scope,
        location=extracted.location,
        memo=extracted.memo or ingestion.caption,
        confidence=extracted.confidence,
        categorization_source=categorization_source,
        category_reason=category_reason,
        status=status,
        quickbooks_category=category.quickbooks_category if category else None,
        quickbooks_vendor=merchant,
    )
    db.add(expense)
    db.flush()
    ingestion.expense_id = expense.id
    ingestion.status = status
    ingestion.processed_at = datetime.now(timezone.utc)
    db.add(AuditEvent(entity_type="expense", entity_id=expense.id, action="created", details={"source": ingestion.source}))
    db.commit()


def process_next(db: Session, settings: Settings) -> Ingestion | None:
    ingestion = db.scalar(
        select(Ingestion).where(Ingestion.status == IngestionStatus.queued).order_by(Ingestion.received_at).limit(1)
    )
    if not ingestion:
        return None
    return process_ingestion(db, settings, ingestion.id)
