from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..config import Settings
from ..models import Expense, Ingestion
from ..schemas import ExpenseOut, MerchantRuleOut


def expense_out(db: Session, settings: Settings, expense: Expense) -> ExpenseOut:
    ingestion = db.scalar(
        select(Ingestion)
        .options(joinedload(Ingestion.receipt))
        .where(Ingestion.expense_id == expense.id)
        .order_by(Ingestion.received_at.desc())
        .limit(1)
    )
    return ExpenseOut(
        id=expense.id,
        expense_date=expense.expense_date,
        merchant=expense.merchant,
        original_amount=expense.original_amount,
        original_currency=expense.original_currency,
        amount=expense.amount,
        currency=expense.currency,
        conversion_rate=expense.conversion_rate,
        fx_estimated=expense.fx_estimated,
        fx_rate_date=expense.fx_rate_date,
        category_id=expense.category_id,
        category_name=expense.category.name if expense.category else None,
        payment_method_id=expense.payment_method_id,
        payment_method_name=expense.payment_method.name if expense.payment_method else None,
        scope=expense.scope,
        location=expense.location,
        department=expense.department,
        trip_name=expense.trip_name,
        refundable=expense.refundable,
        memo=expense.memo,
        confidence=float(expense.confidence or 0),
        categorization_source=expense.categorization_source,
        category_reason=expense.category_reason,
        status=expense.status,
        quickbooks_category=expense.quickbooks_category,
        quickbooks_class=expense.quickbooks_class,
        quickbooks_customer_job=expense.quickbooks_customer_job,
        quickbooks_location=expense.quickbooks_location,
        quickbooks_subprogram=expense.quickbooks_subprogram,
        quickbooks_vendor=expense.quickbooks_vendor,
        receipt_id=ingestion.receipt_id if ingestion else None,
        receipt_filename=ingestion.receipt.original_filename if ingestion else None,
        receipt_url=f"/api/receipts/{ingestion.receipt_id}/file" if ingestion else None,
        source=ingestion.source if ingestion else None,
        ingestion_id=ingestion.id if ingestion else None,
        created_at=expense.created_at,
        updated_at=expense.updated_at,
    )


def merchant_rule_out(rule) -> MerchantRuleOut:
    return MerchantRuleOut(
        id=rule.id,
        merchant_display=rule.merchant_display,
        merchant_normalized=rule.merchant_normalized,
        category_id=rule.category_id,
        category_name=rule.category.name if rule.category else None,
        payment_method_id=rule.payment_method_id,
        payment_method_name=rule.payment_method.name if rule.payment_method else None,
        scope=rule.scope,
        enabled=rule.enabled,
        conflict_count=rule.conflict_count,
    )
