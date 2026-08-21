from __future__ import annotations

import csv
import io
import re
import secrets
import time
import zipfile
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Annotated

from argon2 import PasswordHasher
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload
from starlette.middleware.sessions import SessionMiddleware

from .config import get_settings
from .database import SessionLocal, get_db, init_database
from .models import (
    AppSetting,
    AuditEvent,
    Category,
    Expense,
    ExpenseScope,
    Ingestion,
    IngestionStatus,
    MerchantRule,
    PaymentMethod,
    Receipt,
)
from .schemas import (
    CategoryCreate,
    CategoryOut,
    CategoryUpdate,
    DashboardOut,
    ExpenseOut,
    ExpenseUpdate,
    IngestionOut,
    MerchantRuleOut,
    MerchantRuleCreate,
    MerchantRuleUpdate,
    PaymentMethodCreate,
    PaymentMethodOut,
    PaymentMethodUpdate,
    ReimbursementExportRequest,
    SettingsOut,
    SettingsUpdate,
)
from .services.fx import get_eur_rate
from .services.ingestion import ingest_bytes
from .services.presentation import expense_out, merchant_rule_out
from .services.processing import get_setting, normalize_merchant
from .services.storage import InvalidReceiptFile

settings = get_settings()
password_hasher = PasswordHasher()
login_attempts: dict[str, list[float]] = defaultdict(list)


def startup() -> None:
    init_database()
    with SessionLocal.begin() as db:
        if db.get(AppSetting, "password_hash") is None:
            db.add(AppSetting(key="password_hash", value=password_hasher.hash(settings.app_password)))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    startup()
    yield


app = FastAPI(title=settings.app_name, version="0.2.0", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    same_site="strict",
    https_only=settings.cookie_secure,
    max_age=60 * 60 * 24 * 30,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.app_origin, "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def require_auth(request: Request) -> None:
    if not request.session.get("authenticated"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")


Auth = Annotated[None, Depends(require_auth)]
Db = Annotated[Session, Depends(get_db)]


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "version": "0.2.0"}


@app.post("/api/auth/login")
async def login(request: Request, db: Db) -> dict:
    client = request.client.host if request.client else "unknown"
    now = time.monotonic()
    attempts = [stamp for stamp in login_attempts[client] if now - stamp < 300]
    login_attempts[client] = attempts
    if len(attempts) >= 8:
        raise HTTPException(status_code=429, detail="Too many login attempts; try again later")
    body = await request.json()
    password = str(body.get("password", ""))
    stored = db.get(AppSetting, "password_hash")
    try:
        password_hasher.verify(stored.value if stored else "", password)
    except Exception:
        login_attempts[client].append(now)
        raise HTTPException(status_code=401, detail="Invalid password")
    request.session.clear()
    request.session["authenticated"] = True
    request.session["login_at"] = datetime.now(timezone.utc).isoformat()
    login_attempts.pop(client, None)
    return {"authenticated": True}


@app.post("/api/auth/logout")
def logout(request: Request) -> dict:
    request.session.clear()
    return {"authenticated": False}


@app.get("/api/auth/me")
def me(request: Request) -> dict:
    return {"authenticated": bool(request.session.get("authenticated"))}


@app.post("/api/ingestions", response_model=list[IngestionOut])
async def upload_receipts(
    _auth: Auth,
    db: Db,
    files: Annotated[list[UploadFile], File()],
    caption: Annotated[str | None, Form()] = None,
) -> list[Ingestion]:
    output = []
    for upload in files:
        data = await upload.read(settings.max_upload_mb * 1024 * 1024 + 1)
        try:
            ingestion = ingest_bytes(
                db,
                settings,
                data=data,
                filename=upload.filename or "receipt",
                claimed_mime=upload.content_type,
                source="web",
                external_id=secrets.token_urlsafe(18),
                caption=caption,
            )
        except InvalidReceiptFile as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        output.append(ingestion)
    return output


@app.get("/api/ingestions", response_model=list[IngestionOut])
def list_ingestions(
    _auth: Auth,
    db: Db,
    state: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[Ingestion]:
    query = select(Ingestion)
    if state:
        try:
            query = query.where(Ingestion.status == IngestionStatus(state))
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid state")
    return list(db.scalars(query.order_by(Ingestion.received_at.desc()).limit(limit)).all())


def _expense_query(
    state: str | None,
    scope: str | None,
    search: str | None,
    category_id: str | None,
    date_from: date | None,
    date_to: date | None,
):
    query = select(Expense).options(joinedload(Expense.category), joinedload(Expense.payment_method)).where(Expense.deleted_at.is_(None))
    if state:
        if state == "review":
            query = query.where(Expense.status.in_([IngestionStatus.needs_review, IngestionStatus.duplicate]))
        else:
            query = query.where(Expense.status == IngestionStatus(state))
    if scope:
        query = query.where(Expense.scope == ExpenseScope(scope))
    if search:
        needle = f"%{search.strip()}%"
        query = query.where(or_(Expense.merchant.ilike(needle), Expense.memo.ilike(needle)))
    if category_id:
        query = query.where(Expense.category_id == category_id)
    if date_from:
        query = query.where(Expense.expense_date >= date_from)
    if date_to:
        query = query.where(Expense.expense_date <= date_to)
    return query


@app.get("/api/expenses", response_model=list[ExpenseOut])
def list_expenses(
    _auth: Auth,
    db: Db,
    state: str | None = None,
    scope: str | None = None,
    search: str | None = None,
    category_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(default=250, ge=1, le=1000),
) -> list[ExpenseOut]:
    try:
        query = _expense_query(state, scope, search, category_id, date_from, date_to)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid state or scope")
    expenses = db.scalars(query.order_by(Expense.expense_date.desc(), Expense.created_at.desc()).limit(limit)).unique().all()
    return [expense_out(db, settings, expense) for expense in expenses]


@app.get("/api/expenses/{expense_id}", response_model=ExpenseOut)
def get_expense(expense_id: str, _auth: Auth, db: Db) -> ExpenseOut:
    expense = db.scalar(
        select(Expense).options(joinedload(Expense.category), joinedload(Expense.payment_method)).where(Expense.id == expense_id, Expense.deleted_at.is_(None))
    )
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")
    return expense_out(db, settings, expense)


@app.patch("/api/expenses/{expense_id}", response_model=ExpenseOut)
def update_expense(expense_id: str, payload: ExpenseUpdate, _auth: Auth, db: Db) -> ExpenseOut:
    expense = db.scalar(
        select(Expense).options(joinedload(Expense.category), joinedload(Expense.payment_method)).where(Expense.id == expense_id, Expense.deleted_at.is_(None))
    )
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")
    before = {"category_id": expense.category_id, "payment_method_id": expense.payment_method_id, "scope": expense.scope.value}
    changes = payload.model_dump(exclude_unset=True, exclude={"accept", "remember_merchant"})
    for key, value in changes.items():
        setattr(expense, key, value)
    if {"category_id", "payment_method_id", "scope"} & changes.keys():
        expense.categorization_source = "manual"
        if not expense.category_reason:
            expense.category_reason = "Updated manually."
    if "merchant" in changes:
        expense.merchant_normalized = normalize_merchant(expense.merchant)
    if {"expense_date", "original_amount", "original_currency"} & changes.keys():
        expense.original_currency = expense.original_currency.upper() if expense.original_currency else None
        if expense.expense_date and expense.original_amount is not None and expense.original_currency:
            rate, rate_date = get_eur_rate(db, expense.original_currency, expense.expense_date)
            expense.conversion_rate = rate
            expense.fx_rate_date = rate_date
            expense.fx_estimated = bool(rate_date and rate_date != expense.expense_date)
            expense.amount = (Decimal(expense.original_amount) * rate).quantize(Decimal("0.01")) if rate else None
    if payload.accept:
        if not all([expense.expense_date, expense.merchant, expense.original_amount is not None, expense.original_currency, expense.category_id, expense.amount is not None]):
            raise HTTPException(status_code=422, detail="Date, merchant, amount, currency, category, and an available EUR rate are required")
        expense.status = IngestionStatus.accepted
        for ingestion in db.scalars(select(Ingestion).where(Ingestion.expense_id == expense.id)):
            ingestion.status = IngestionStatus.accepted
    if payload.remember_merchant and expense.merchant_normalized:
        rule = db.scalar(select(MerchantRule).where(MerchantRule.merchant_normalized == expense.merchant_normalized))
        desired = (expense.category_id, expense.payment_method_id, expense.scope)
        if not rule:
            db.add(MerchantRule(
                merchant_normalized=expense.merchant_normalized,
                merchant_display=expense.merchant or expense.merchant_normalized,
                category_id=expense.category_id,
                payment_method_id=expense.payment_method_id,
                scope=expense.scope,
            ))
        elif (rule.category_id, rule.payment_method_id, rule.scope) != desired:
            rule.enabled = False
            rule.conflict_count += 1
    if expense.category_id:
        category = db.get(Category, expense.category_id)
        if category and not expense.quickbooks_category:
            expense.quickbooks_category = category.quickbooks_category
    expense.quickbooks_vendor = expense.quickbooks_vendor or expense.merchant
    db.add(AuditEvent(entity_type="expense", entity_id=expense.id, action="updated", details={"before": before, "fields": list(changes)}))
    db.commit()
    db.refresh(expense)
    return expense_out(db, settings, expense)


@app.delete("/api/expenses/{expense_id}", status_code=204)
def delete_expense(expense_id: str, _auth: Auth, db: Db) -> Response:
    expense = db.get(Expense, expense_id)
    if not expense or expense.deleted_at:
        raise HTTPException(status_code=404, detail="Expense not found")
    expense.deleted_at = datetime.now(timezone.utc)
    db.add(AuditEvent(entity_type="expense", entity_id=expense.id, action="soft_deleted"))
    db.commit()
    return Response(status_code=204)


@app.post("/api/expenses/{expense_id}/reprocess", response_model=IngestionOut)
def reprocess_expense(expense_id: str, _auth: Auth, db: Db) -> Ingestion:
    expense = db.get(Expense, expense_id)
    ingestion = db.scalar(select(Ingestion).where(Ingestion.expense_id == expense_id).order_by(Ingestion.received_at.desc()))
    if not expense or not ingestion:
        raise HTTPException(status_code=404, detail="Expense or ingestion not found")
    expense.deleted_at = datetime.now(timezone.utc)
    ingestion.expense_id = None
    ingestion.status = IngestionStatus.queued
    ingestion.attempts = 0
    ingestion.error_code = None
    ingestion.error_message = None
    ingestion.processed_at = None
    db.commit()
    db.refresh(ingestion)
    return ingestion


@app.get("/api/categories", response_model=list[CategoryOut])
def list_categories(_auth: Auth, db: Db, include_archived: bool = False) -> list[Category]:
    query = select(Category)
    if not include_archived:
        query = query.where(Category.archived.is_(False))
    return list(db.scalars(query.order_by(Category.scope, Category.name)).all())


@app.post("/api/categories", response_model=CategoryOut, status_code=201)
def create_category(payload: CategoryCreate, _auth: Auth, db: Db) -> Category:
    if db.scalar(select(Category).where(Category.code == payload.code.upper())):
        raise HTTPException(status_code=409, detail="Category code already exists")
    values = payload.model_dump()
    values["code"] = payload.code.upper()
    category = Category(**values)
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


@app.patch("/api/categories/{category_id}", response_model=CategoryOut)
def update_category(category_id: str, payload: CategoryUpdate, _auth: Auth, db: Db) -> Category:
    category = db.get(Category, category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    values = payload.model_dump(exclude_unset=True)
    if values.get("code") and values["code"].upper() != category.code:
        if db.scalar(select(Category).where(Category.code == values["code"].upper())):
            raise HTTPException(status_code=409, detail="Category code already exists")
        values["code"] = values["code"].upper()
    for key, value in values.items():
        setattr(category, key, value)
    db.commit()
    db.refresh(category)
    return category


@app.get("/api/payment-methods", response_model=list[PaymentMethodOut])
def list_payment_methods(_auth: Auth, db: Db, include_archived: bool = False) -> list[PaymentMethod]:
    query = select(PaymentMethod)
    if not include_archived:
        query = query.where(PaymentMethod.archived.is_(False))
    return list(db.scalars(query.order_by(PaymentMethod.name)).all())


@app.post("/api/payment-methods", response_model=PaymentMethodOut, status_code=201)
def create_payment_method(payload: PaymentMethodCreate, _auth: Auth, db: Db) -> PaymentMethod:
    if db.scalar(select(PaymentMethod).where(PaymentMethod.name == payload.name)):
        raise HTTPException(status_code=409, detail="Payment method name already exists")
    if payload.is_default:
        for item in db.scalars(select(PaymentMethod).where(PaymentMethod.is_default.is_(True))):
            item.is_default = False
    method = PaymentMethod(**payload.model_dump())
    db.add(method)
    db.commit()
    db.refresh(method)
    return method


@app.patch("/api/payment-methods/{method_id}", response_model=PaymentMethodOut)
def update_payment_method(method_id: str, payload: PaymentMethodUpdate, _auth: Auth, db: Db) -> PaymentMethod:
    method = db.get(PaymentMethod, method_id)
    if not method:
        raise HTTPException(status_code=404, detail="Payment method not found")
    values = payload.model_dump(exclude_unset=True)
    if values.get("name") and values["name"] != method.name:
        if db.scalar(select(PaymentMethod).where(PaymentMethod.name == values["name"], PaymentMethod.id != method.id)):
            raise HTTPException(status_code=409, detail="Payment method name already exists")
    if values.get("is_default"):
        for item in db.scalars(select(PaymentMethod).where(PaymentMethod.is_default.is_(True))):
            item.is_default = False
    if values.get("is_default") is False and method.is_default:
        alternate_default = db.scalar(
            select(PaymentMethod).where(
                PaymentMethod.id != method.id,
                PaymentMethod.is_default.is_(True),
                PaymentMethod.archived.is_(False),
            )
        )
        if not alternate_default:
            raise HTTPException(status_code=422, detail="Choose another default payment method first")
    if values.get("archived") and method.is_default:
        alternate_default = db.scalar(
            select(PaymentMethod).where(
                PaymentMethod.id != method.id,
                PaymentMethod.is_default.is_(True),
                PaymentMethod.archived.is_(False),
            )
        )
        if not alternate_default:
            raise HTTPException(status_code=422, detail="Choose another default payment method before archiving this one")
    if values.get("archived") and values.get("is_default"):
        raise HTTPException(status_code=422, detail="An archived payment method cannot be the default")
    for key, value in values.items():
        setattr(method, key, value)
    db.commit()
    db.refresh(method)
    return method


@app.get("/api/merchant-rules", response_model=list[MerchantRuleOut])
def list_merchant_rules(_auth: Auth, db: Db) -> list[MerchantRuleOut]:
    rules = db.scalars(
        select(MerchantRule).options(joinedload(MerchantRule.category), joinedload(MerchantRule.payment_method)).order_by(MerchantRule.merchant_display)
    ).unique().all()
    return [merchant_rule_out(rule) for rule in rules]


@app.post("/api/merchant-rules", response_model=MerchantRuleOut, status_code=201)
def create_merchant_rule(payload: MerchantRuleCreate, _auth: Auth, db: Db) -> MerchantRuleOut:
    normalized = normalize_merchant(payload.merchant_normalized or payload.merchant_display)
    if not normalized:
        raise HTTPException(status_code=422, detail="Merchant is required")
    if db.scalar(select(MerchantRule).where(MerchantRule.merchant_normalized == normalized)):
        raise HTTPException(status_code=409, detail="A rule for this merchant already exists")
    if payload.category_id and not db.get(Category, payload.category_id):
        raise HTTPException(status_code=422, detail="Category not found")
    if payload.payment_method_id and not db.get(PaymentMethod, payload.payment_method_id):
        raise HTTPException(status_code=422, detail="Payment method not found")
    rule = MerchantRule(
        merchant_normalized=normalized,
        merchant_display=payload.merchant_display.strip(),
        category_id=payload.category_id,
        payment_method_id=payload.payment_method_id,
        scope=payload.scope,
        enabled=payload.enabled,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return merchant_rule_out(rule)


@app.patch("/api/merchant-rules/{rule_id}", response_model=MerchantRuleOut)
def update_merchant_rule(rule_id: str, payload: MerchantRuleUpdate, _auth: Auth, db: Db) -> MerchantRuleOut:
    rule = db.get(MerchantRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    values = payload.model_dump(exclude_unset=True)
    if values.get("category_id") and not db.get(Category, values["category_id"]):
        raise HTTPException(status_code=422, detail="Category not found")
    if values.get("payment_method_id") and not db.get(PaymentMethod, values["payment_method_id"]):
        raise HTTPException(status_code=422, detail="Payment method not found")
    if "merchant_display" in values:
        values["merchant_display"] = values["merchant_display"].strip()
    if "merchant_normalized" in values:
        values["merchant_normalized"] = normalize_merchant(values["merchant_normalized"])
    elif "merchant_display" in values:
        values["merchant_normalized"] = normalize_merchant(values["merchant_display"])
    candidate = values.get("merchant_normalized")
    if candidate and candidate != rule.merchant_normalized:
        if db.scalar(select(MerchantRule).where(MerchantRule.merchant_normalized == candidate, MerchantRule.id != rule.id)):
            raise HTTPException(status_code=409, detail="A rule for this merchant already exists")
    for key, value in values.items():
        setattr(rule, key, value)
    db.commit()
    db.refresh(rule)
    return merchant_rule_out(rule)


@app.delete("/api/merchant-rules/{rule_id}", status_code=204)
def delete_merchant_rule(rule_id: str, _auth: Auth, db: Db) -> Response:
    rule = db.get(MerchantRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(rule)
    db.commit()
    return Response(status_code=204)


def _ai_configured() -> bool:
    return bool({
        "openai": settings.openai_api_key,
        "anthropic": settings.anthropic_api_key,
        "gemini": settings.gemini_api_key,
    }.get(settings.ai_provider.lower()))


@app.get("/api/settings", response_model=SettingsOut)
def get_app_settings(_auth: Auth, db: Db) -> SettingsOut:
    values = {item.key: item.value for item in db.scalars(select(AppSetting))}
    return SettingsOut(
        owner_name=values.get("owner_name", "Owner"),
        owner_email=values.get("owner_email", ""),
        review_mode=values.get("review_mode", "uncertain"),
        confidence_threshold=float(values.get("confidence_threshold", settings.confidence_threshold)),
        telegram_claim_code=values.get("telegram_claim_code", ""),
        telegram_claimed=bool(values.get("telegram_owner_id")),
        telegram_allowlist_configured=bool(settings.telegram_allowed_user_id),
        ai_provider=settings.ai_provider,
        ai_model=settings.ai_model,
        ai_configured=_ai_configured(),
        base_currency=settings.base_currency,
    )


@app.patch("/api/settings", response_model=SettingsOut)
def update_app_settings(payload: SettingsUpdate, _auth: Auth, db: Db) -> SettingsOut:
    for key, value in payload.model_dump(exclude_none=True).items():
        item = db.get(AppSetting, key)
        string_value = str(value).lower() if isinstance(value, bool) else str(value)
        if item:
            item.value = string_value
        else:
            db.add(AppSetting(key=key, value=string_value))
    db.commit()
    return get_app_settings(None, db)


@app.post("/api/settings/telegram-claim-code")
def regenerate_claim_code(_auth: Auth, db: Db) -> dict:
    code = secrets.token_hex(3).upper()
    item = db.get(AppSetting, "telegram_claim_code")
    if item:
        item.value = code
    else:
        db.add(AppSetting(key="telegram_claim_code", value=code))
    db.commit()
    return {"telegram_claim_code": code}


def _default_dashboard_range(today: date) -> tuple[date, date]:
    """The active calendar month plus the preceding eleven full months."""
    month_start = today.replace(day=1)
    year = month_start.year - (1 if month_start.month <= 11 else 0)
    month = ((month_start.month - 12) % 12) + 1
    return date(year, month, 1), today


def _next_month(value: date) -> date:
    return (value.replace(day=28) + timedelta(days=4)).replace(day=1)


@app.get("/api/dashboard", response_model=DashboardOut)
def dashboard(
    _auth: Auth,
    db: Db,
    scope: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> DashboardOut:
    default_from, default_to = _default_dashboard_range(date.today())
    date_from = date_from or default_from
    date_to = date_to or default_to
    if date_from > date_to:
        raise HTTPException(status_code=422, detail="date_from must be on or before date_to")
    previous_end = date_from - timedelta(days=1)
    previous_start = date_from - timedelta(days=(date_to - date_from).days + 1)
    base = [Expense.deleted_at.is_(None), Expense.status == IngestionStatus.accepted]
    if scope:
        try:
            base.append(Expense.scope == ExpenseScope(scope))
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid scope")
    range_base = [*base, Expense.expense_date >= date_from, Expense.expense_date <= date_to]
    range_total = db.scalar(select(func.coalesce(func.sum(Expense.amount), 0)).where(*range_base)) or 0
    previous_total = db.scalar(select(func.coalesce(func.sum(Expense.amount), 0)).where(*base, Expense.expense_date >= previous_start, Expense.expense_date <= previous_end)) or 0
    review_base = [Expense.deleted_at.is_(None), Expense.status.in_([IngestionStatus.needs_review, IngestionStatus.duplicate]), Expense.expense_date >= date_from, Expense.expense_date <= date_to]
    if scope:
        review_base.append(Expense.scope == ExpenseScope(scope))
    review_count = db.scalar(select(func.count()).select_from(Expense).where(*review_base)) or 0
    failed_count = db.scalar(select(func.count()).select_from(Ingestion).where(Ingestion.status == IngestionStatus.failed, func.date(Ingestion.received_at) >= date_from, func.date(Ingestion.received_at) <= date_to)) or 0
    receipt_count = db.scalar(select(func.count()).select_from(Receipt).where(func.date(Receipt.created_at) >= date_from, func.date(Receipt.created_at) <= date_to)) or 0
    category_rows = db.execute(
        select(Category.name, Category.color, func.sum(Expense.amount)).join(Expense, Expense.category_id == Category.id).where(*range_base).group_by(Category.id).order_by(func.sum(Expense.amount).desc())
    ).all()
    merchant_rows = db.execute(
        select(Expense.merchant, func.sum(Expense.amount)).where(*range_base).group_by(Expense.merchant).order_by(func.sum(Expense.amount).desc()).limit(8)
    ).all()
    by_month = []
    cursor = date_from.replace(day=1)
    while cursor <= date_to:
        next_month = _next_month(cursor)
        period_start = max(cursor, date_from)
        period_end = min(next_month - timedelta(days=1), date_to)
        total = db.scalar(select(func.coalesce(func.sum(Expense.amount), 0)).where(*base, Expense.expense_date >= period_start, Expense.expense_date <= period_end)) or 0
        by_month.append({"month": cursor.strftime("%Y-%m"), "amount": float(total)})
        cursor = next_month
    return DashboardOut(
        month_total=Decimal(range_total),
        previous_month_total=Decimal(previous_total),
        range_total=Decimal(range_total),
        previous_range_total=Decimal(previous_total),
        date_from=date_from,
        date_to=date_to,
        review_count=review_count,
        failed_count=failed_count,
        receipt_count=receipt_count,
        by_category=[{"name": name, "color": color, "amount": float(total or 0)} for name, color, total in category_rows],
        by_month=by_month,
        top_merchants=[{"merchant": name or "Unknown", "amount": float(total or 0)} for name, total in merchant_rows],
    )


@app.get("/api/receipts/{receipt_id}/file")
def receipt_file(receipt_id: str, _auth: Auth, db: Db) -> FileResponse:
    receipt = db.get(Receipt, receipt_id)
    if not receipt or not Path(receipt.storage_path).is_file():
        raise HTTPException(status_code=404, detail="Receipt not found")
    return FileResponse(receipt.storage_path, media_type=receipt.mime_type, filename=receipt.original_filename)


@app.get("/api/receipts/{receipt_id}/preview")
def receipt_preview(receipt_id: str, _auth: Auth, db: Db) -> FileResponse:
    receipt = db.get(Receipt, receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")
    path = receipt.preview_path or receipt.storage_path
    if not Path(path).is_file():
        raise HTTPException(status_code=404, detail="Preview not found")
    return FileResponse(path, media_type="image/jpeg" if receipt.preview_path else receipt.mime_type)


RAMP_HEADERS = [
    "Date", "Payment Method", "Amount", "Currency", "Original Currency Amount", "Original Currency Code",
    "Conversion Rate", "Merchant", "User", "User Email", "Ramp Category", "Location", "Department", "Trip Name",
    "Refundable", "URL", "Receipt URL", "Memo", "QuickBooks Category", "QuickBooks Class", "QuickBooks Customer/Job",
    "QuickBooks Location", "QuickBooks Subprogram", "QuickBooks Vendor",
]

REIMBURSEMENT_HEADERS = [
    "Archive Filename", "Date", "Merchant", "Original Amount", "Original Currency",
    "EUR Reimbursement Amount", "Category", "Payment Method", "Scope", "Department",
    "Trip", "Memo", "Status",
]


def _safe_receipt_extension(receipt: Receipt) -> str:
    """Return an archive-safe extension while retaining the original file type."""
    suffix = Path(receipt.original_filename).suffix.lower()
    extensions = {
        "application/pdf": ({".pdf"}, ".pdf"),
        "image/jpeg": ({".jpg", ".jpeg", ".jpe"}, ".jpg"),
        "image/png": ({".png"}, ".png"),
        "image/webp": ({".webp"}, ".webp"),
        "image/heic": ({".heic"}, ".heic"),
        "image/heif": ({".heif", ".heic"}, ".heif"),
    }
    allowed, fallback = extensions.get(receipt.mime_type.lower(), (set(), ".bin"))
    return suffix if suffix in allowed else fallback


def _safe_receipt_component(value: str | None, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", (value or "").strip()).strip("-")
    return cleaned[:80] or fallback


@app.post("/api/exports/reimbursement.zip")
def export_reimbursement_zip(payload: ReimbursementExportRequest, _auth: Auth, db: Db) -> Response:
    """Build a temporary reimbursement bundle from database-validated receipts."""
    expense_ids = payload.expense_ids
    if not expense_ids:
        raise HTTPException(status_code=422, detail="Select at least one expense to export")
    if len(set(expense_ids)) != len(expense_ids):
        raise HTTPException(status_code=422, detail="Expense IDs must be unique")

    expenses = db.scalars(
        select(Expense)
        .options(joinedload(Expense.category), joinedload(Expense.payment_method))
        .where(Expense.id.in_(expense_ids), Expense.deleted_at.is_(None))
    ).unique().all()
    expenses_by_id = {expense.id: expense for expense in expenses}
    missing_ids = [expense_id for expense_id in expense_ids if expense_id not in expenses_by_id]
    if missing_ids:
        raise HTTPException(status_code=422, detail="One or more selected expenses do not exist or have been deleted")

    ingestions = db.scalars(
        select(Ingestion)
        .options(joinedload(Ingestion.receipt))
        .where(Ingestion.expense_id.in_(expense_ids))
        .order_by(Ingestion.received_at.desc())
    ).unique().all()
    ingestions_by_expense: dict[str, Ingestion] = {}
    for ingestion in ingestions:
        if ingestion.expense_id and ingestion.expense_id not in ingestions_by_expense:
            ingestions_by_expense[ingestion.expense_id] = ingestion

    selected = [(expenses_by_id[expense_id], ingestions_by_expense.get(expense_id)) for expense_id in expense_ids]
    for expense, ingestion in selected:
        if not ingestion or not ingestion.receipt:
            raise HTTPException(status_code=422, detail=f"Selected expense {expense.id} does not have a receipt")
        if expense.amount is None or expense.currency.upper() != "EUR":
            raise HTTPException(status_code=422, detail=f"Selected expense {expense.id} does not have a normalized EUR amount")
        if not Path(ingestion.receipt.storage_path).is_file():
            raise HTTPException(status_code=422, detail=f"Receipt file for selected expense {expense.id} is missing")

    csv_stream = io.StringIO()
    writer = csv.DictWriter(csv_stream, fieldnames=REIMBURSEMENT_HEADERS)
    writer.writeheader()
    original_totals: defaultdict[str, Decimal] = defaultdict(Decimal)
    eur_total = Decimal("0")

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for sequence, (expense, ingestion) in enumerate(selected, start=1):
            receipt = ingestion.receipt
            archive_filename = (
                f"receipts/{sequence:03d}_{expense.expense_date.isoformat() if expense.expense_date else 'undated'}_"
                f"{_safe_receipt_component(expense.merchant, 'unknown-merchant')}{_safe_receipt_extension(receipt)}"
            )
            bundle.write(receipt.storage_path, archive_filename)
            writer.writerow({
                "Archive Filename": archive_filename,
                "Date": expense.expense_date.isoformat() if expense.expense_date else "",
                "Merchant": expense.merchant or "",
                "Original Amount": str(expense.original_amount) if expense.original_amount is not None else "",
                "Original Currency": expense.original_currency or "",
                "EUR Reimbursement Amount": str(expense.amount),
                "Category": expense.category.name if expense.category else "",
                "Payment Method": expense.payment_method.name if expense.payment_method else "",
                "Scope": expense.scope.value,
                "Department": expense.department or "",
                "Trip": expense.trip_name or "",
                "Memo": expense.memo or "",
                "Status": expense.status.value,
            })
            eur_total += Decimal(expense.amount)
            if expense.original_amount is not None and expense.original_currency:
                original_totals[expense.original_currency.upper()] += Decimal(expense.original_amount)

        summary_lines = [
            "Spendloom reimbursement export",
            f"Created: {date.today().isoformat()}",
            f"Selected receipt count: {len(selected)}",
            f"Total EUR reimbursement amount: {eur_total:.2f} EUR",
            "",
            "Original-currency subtotals:",
        ]
        if original_totals:
            summary_lines.extend(f"{currency}: {total:.2f}" for currency, total in sorted(original_totals.items()))
        else:
            summary_lines.append("No original-currency amounts available.")
        bundle.writestr("reimbursement.csv", csv_stream.getvalue())
        bundle.writestr("summary.txt", "\n".join(summary_lines) + "\n")

    filename = f"spendloom-reimbursement-{date.today().isoformat()}.zip"
    return Response(
        archive.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/exports/expenses.csv")
def export_csv(
    request: Request,
    _auth: Auth,
    db: Db,
    extended: bool = False,
    scope: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> Response:
    query = _expense_query(None, scope, None, None, date_from, date_to).where(Expense.status == IngestionStatus.accepted)
    expenses = db.scalars(query.order_by(Expense.expense_date)).unique().all()
    owner_name = get_setting(db, "owner_name", "Owner")
    owner_email = get_setting(db, "owner_email", "")
    headers = RAMP_HEADERS + (["Expense Scope", "Review Status", "FX Estimated"] if extended else [])
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=headers)
    writer.writeheader()
    for expense in expenses:
        item = expense_out(db, settings, expense)
        base_url = str(request.base_url).rstrip("/")
        row = {
            "Date": expense.expense_date.isoformat() if expense.expense_date else "",
            "Payment Method": item.payment_method_name or "",
            "Amount": str(expense.amount or ""),
            "Currency": expense.currency,
            "Original Currency Amount": str(expense.original_amount or ""),
            "Original Currency Code": expense.original_currency or "",
            "Conversion Rate": str(expense.conversion_rate or ""),
            "Merchant": expense.merchant or "",
            "User": owner_name,
            "User Email": owner_email,
            "Ramp Category": item.category_name or "",
            "Location": expense.location or "",
            "Department": expense.department or "",
            "Trip Name": expense.trip_name or "",
            "Refundable": "Yes" if expense.refundable else "No",
            "URL": f"{base_url}/expenses/{expense.id}",
            "Receipt URL": f"{base_url}{item.receipt_url}" if item.receipt_url else "",
            "Memo": expense.memo or "",
            "QuickBooks Category": expense.quickbooks_category or "",
            "QuickBooks Class": expense.quickbooks_class or "",
            "QuickBooks Customer/Job": expense.quickbooks_customer_job or "",
            "QuickBooks Location": expense.quickbooks_location or "",
            "QuickBooks Subprogram": expense.quickbooks_subprogram or "",
            "QuickBooks Vendor": expense.quickbooks_vendor or "",
        }
        if extended:
            row.update({"Expense Scope": expense.scope.value, "Review Status": expense.status.value, "FX Estimated": "Yes" if expense.fx_estimated else "No"})
        writer.writerow(row)
    filename = f"spendloom-expenses-{date.today().isoformat()}.csv"
    return Response(stream.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if frontend_dist.is_dir():
    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

    @app.get("/{path:path}")
    def frontend(path: str) -> FileResponse:
        candidate = frontend_dist / path
        if path and candidate.is_file() and candidate.resolve().is_relative_to(frontend_dist.resolve()):
            return FileResponse(candidate)
        return FileResponse(frontend_dist / "index.html")
