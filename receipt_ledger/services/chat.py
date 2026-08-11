"""Provider-neutral, bounded Telegram conversation service.

The language model is never given a database connection or SQL.  It can only
ask for one of the JSON-schema tools below; every read, calculation and write
is validated and performed here.  This also leaves the persisted conversation
portable between OpenAI, Anthropic and Gemini.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from ..config import Settings
from ..models import (
    Category,
    ChatJob,
    ConversationMessage,
    ConversationSession,
    Expense,
    ExpenseScope,
    Ingestion,
    IngestionStatus,
    MerchantRule,
    PaymentMethod,
    PendingAction,
)
from .fx import get_eur_rate
from .processing import normalize_merchant, parse_date, parse_decimal

logger = logging.getLogger(__name__)

MAX_MESSAGES = 16  # eight user/assistant exchanges
MAX_CONTEXT_TOKENS = 6_000
CONTEXT_AGE = timedelta(hours=24)
PENDING_ACTION_AGE = timedelta(minutes=10)


# This canonical contract is adapted at the edge for each provider. Keep its
# names intentionally boring: tools describe validated ledger operations, not
# provider-specific prompt tricks.
def _tool(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    parameters: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        parameters["required"] = required
    return {"name": name, "description": description, "parameters": parameters}


_scope_schema = {"type": "string", "enum": ["personal", "business", "unknown"]}
CHAT_TOOL_CONTRACT: list[dict[str, Any]] = [
    _tool("search_expenses", "Search non-deleted expenses; never guess a record id.", {"query": {"type": "string"}, "date_from": {"type": "string"}, "date_to": {"type": "string"}, "scope": _scope_schema, "limit": {"type": "integer", "minimum": 1, "maximum": 50}}),
    _tool("inspect_expense", "Read one expense by id, or the active receipt expense using active=true.", {"expense_id": {"type": "string"}, "active": {"type": "boolean"}}),
    _tool("summarize_spending", "Calculate spending on the server for an inclusive date range and optional scope.", {"date_from": {"type": "string"}, "date_to": {"type": "string"}, "scope": _scope_schema, "group_by": {"type": "string", "enum": ["category", "merchant", "month"]}}),
    _tool("create_expense", "Create one ordinary manual expense immediately; server tools calculate amounts.", {"expense_date": {"type": "string"}, "merchant": {"type": "string"}, "original_amount": {"type": "string"}, "original_currency": {"type": "string"}, "category_id": {"type": "string"}, "category_code": {"type": "string"}, "payment_method_id": {"type": "string"}, "scope": _scope_schema, "memo": {"type": "string"}}, ["expense_date", "merchant", "original_amount", "original_currency"]),
    _tool("edit_expense", "Correct one existing expense immediately; use a specific id or active=true.", {"expense_id": {"type": "string"}, "active": {"type": "boolean"}, "changes": {"type": "object"}}, ["changes"]),
    _tool("manage_category", "Create or edit a category. Archiving requires confirmation.", {"action": {"type": "string", "enum": ["create", "edit", "archive"]}, "category_id": {"type": "string"}, "values": {"type": "object"}}, ["action"]),
    _tool("manage_payment_method", "Create or edit a payment method. Archiving requires confirmation.", {"action": {"type": "string", "enum": ["create", "edit", "archive"]}, "method_id": {"type": "string"}, "values": {"type": "object"}}, ["action"]),
    _tool("manage_merchant_rule", "Create or edit a merchant rule. Deleting it requires confirmation.", {"action": {"type": "string", "enum": ["create", "edit", "delete"]}, "rule_id": {"type": "string"}, "values": {"type": "object"}}, ["action"]),
    _tool("export_expenses", "Generate a CSV export and send it to the Telegram owner.", {"date_from": {"type": "string"}, "date_to": {"type": "string"}, "scope": _scope_schema}),
    _tool("delete_expense", "Request deletion of one expense; confirmation is always required.", {"expense_id": {"type": "string"}, "active": {"type": "boolean"}}),
    _tool("bulk_edit_expenses", "Request the same change for several explicit ids; confirmation is always required.", {"expense_ids": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 50}, "changes": {"type": "object"}}, ["expense_ids", "changes"]),
]


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass
class ChatCompletion:
    text: str = ""
    tool_calls: list[ToolCall] | None = None


class ChatProvider:
    def __init__(self, settings: Settings):
        self.settings = settings

    def complete(self, messages: list[dict[str, str]], tools: list[dict[str, Any]]) -> ChatCompletion:
        raise NotImplementedError


class OpenAIChatProvider(ChatProvider):
    def complete(self, messages: list[dict[str, str]], tools: list[dict[str, Any]]) -> ChatCompletion:
        if not self.settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        from openai import OpenAI

        response = OpenAI(api_key=self.settings.openai_api_key).responses.create(
            model=self.settings.resolved_chat_model,
            input=[{"role": item["role"], "content": item["content"]} for item in messages],
            tools=[{"type": "function", "name": tool["name"], "description": tool["description"], "parameters": tool["parameters"]} for tool in tools],
        )
        calls: list[ToolCall] = []
        for item in getattr(response, "output", []) or []:
            if getattr(item, "type", None) == "function_call":
                calls.append(ToolCall(item.name, _arguments(getattr(item, "arguments", "{}"))))
        return ChatCompletion(text=(getattr(response, "output_text", "") or "").strip(), tool_calls=calls)


class AnthropicChatProvider(ChatProvider):
    def complete(self, messages: list[dict[str, str]], tools: list[dict[str, Any]]) -> ChatCompletion:
        if not self.settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not configured")
        from anthropic import Anthropic

        system = messages[0]["content"] if messages and messages[0]["role"] == "system" else ""
        body = messages[1:] if system else messages
        response = Anthropic(api_key=self.settings.anthropic_api_key).messages.create(
            model=self.settings.resolved_chat_model,
            max_tokens=1_200,
            system=system,
            messages=[{"role": item["role"], "content": item["content"]} for item in body],
            tools=[{"name": tool["name"], "description": tool["description"], "input_schema": tool["parameters"]} for tool in tools],
        )
        calls = [ToolCall(block.name, dict(block.input or {})) for block in response.content if getattr(block, "type", None) == "tool_use"]
        text = "\n".join(block.text for block in response.content if getattr(block, "type", None) == "text")
        return ChatCompletion(text=text.strip(), tool_calls=calls)


class GeminiChatProvider(ChatProvider):
    def complete(self, messages: list[dict[str, str]], tools: list[dict[str, Any]]) -> ChatCompletion:
        if not self.settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        from google import genai
        from google.genai import types

        declarations = [types.FunctionDeclaration(name=tool["name"], description=tool["description"], parameters=tool["parameters"]) for tool in tools]
        # Gemini accepts a regular text transcript.  Tool results are retained
        # locally and returned as text in the next turn, never as database data
        # hidden in a provider-side session.
        transcript = "\n\n".join(f"{item['role'].upper()}: {item['content']}" for item in messages)
        response = genai.Client(api_key=self.settings.gemini_api_key).models.generate_content(
            model=self.settings.resolved_chat_model,
            contents=transcript,
            config=types.GenerateContentConfig(tools=[types.Tool(function_declarations=declarations)]),
        )
        calls: list[ToolCall] = []
        for candidate in getattr(response, "candidates", []) or []:
            for part in getattr(getattr(candidate, "content", None), "parts", []) or []:
                call = getattr(part, "function_call", None)
                if call:
                    calls.append(ToolCall(call.name, dict(call.args or {})))
        return ChatCompletion(text=(getattr(response, "text", "") or "").strip(), tool_calls=calls)


def _arguments(value: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        decoded = json.loads(value or "{}")
        return decoded if isinstance(decoded, dict) else {}
    except json.JSONDecodeError:
        return {}


def chat_provider_for(settings: Settings) -> ChatProvider:
    providers = {"openai": OpenAIChatProvider, "anthropic": AnthropicChatProvider, "gemini": GeminiChatProvider}
    provider = providers.get(settings.ai_provider.lower())
    if not provider:
        raise RuntimeError(f"Unsupported AI provider: {settings.ai_provider}")
    return provider(settings)


def _tokens(value: str) -> int:
    return max(1, (len(value) + 3) // 4)


def get_or_create_session(db: Session, chat_id: str | int, user_id: str | int) -> ConversationSession:
    chat_key, user_key = str(chat_id), str(user_id)
    session = db.scalar(select(ConversationSession).where(ConversationSession.telegram_chat_id == chat_key))
    if session:
        # A private Telegram chat is one person, but preserving the observed id
        # makes accidental reassignment obvious in audit/database inspection.
        session.telegram_user_id = user_key
        return session
    session = ConversationSession(telegram_chat_id=chat_key, telegram_user_id=user_key)
    db.add(session)
    db.flush()
    return session


def trim_history(db: Session, session_id: str) -> int:
    now = datetime.now(timezone.utc)
    messages = list(db.scalars(select(ConversationMessage).where(ConversationMessage.session_id == session_id).order_by(ConversationMessage.created_at)).all())
    for message in messages:
        stamp = message.created_at if message.created_at.tzinfo else message.created_at.replace(tzinfo=timezone.utc)
        if stamp < now - CONTEXT_AGE:
            db.delete(message)
    db.flush()
    messages = list(db.scalars(select(ConversationMessage).where(ConversationMessage.session_id == session_id).order_by(ConversationMessage.created_at)).all())
    while len(messages) > MAX_MESSAGES or sum(item.approximate_tokens for item in messages) > MAX_CONTEXT_TOKENS:
        db.delete(messages.pop(0))
    db.flush()
    return len(messages)


def reset_context(db: Session, chat_id: str | int, user_id: str | int) -> ConversationSession:
    session = get_or_create_session(db, chat_id, user_id)
    for item in db.scalars(select(ConversationMessage).where(ConversationMessage.session_id == session.id)):
        db.delete(item)
    session.active_ingestion_id = None
    session.active_expense_id = None
    db.commit()
    return session


def anchor_receipt(db: Session, chat_id: str | int, user_id: str | int, ingestion_id: str, expense_id: str | None = None) -> ConversationSession:
    session = get_or_create_session(db, chat_id, user_id)
    for item in db.scalars(select(ConversationMessage).where(ConversationMessage.session_id == session.id)):
        db.delete(item)
    session.active_ingestion_id = ingestion_id
    session.active_expense_id = expense_id
    db.commit()
    return session


def attach_processed_expense(db: Session, ingestion: Ingestion) -> None:
    if not ingestion.source_chat_id:
        return
    session = db.scalar(select(ConversationSession).where(ConversationSession.telegram_chat_id == str(ingestion.source_chat_id)))
    if session and session.active_ingestion_id == ingestion.id:
        session.active_expense_id = ingestion.expense_id
        db.commit()


def queue_chat_job(db: Session, chat_id: str | int, user_id: str | int, message_id: str | int, text: str) -> ChatJob:
    existing = db.scalar(select(ChatJob).where(ChatJob.telegram_chat_id == str(chat_id), ChatJob.telegram_message_id == str(message_id)))
    if existing:
        return existing
    session = get_or_create_session(db, chat_id, user_id)
    job = ChatJob(session_id=session.id, telegram_chat_id=str(chat_id), telegram_user_id=str(user_id), telegram_message_id=str(message_id), text=text.strip())
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return db.scalar(select(ChatJob).where(ChatJob.telegram_chat_id == str(chat_id), ChatJob.telegram_message_id == str(message_id)))
    db.refresh(job)
    return job


def context_status(db: Session, chat_id: str | int, user_id: str | int) -> dict[str, Any]:
    session = get_or_create_session(db, chat_id, user_id)
    retained = trim_history(db, session.id)
    db.commit()
    return {"ingestion_id": session.active_ingestion_id, "expense_id": session.active_expense_id, "retained_messages": retained}


def _expense_dict(expense: Expense) -> dict[str, Any]:
    return {
        "id": expense.id, "date": expense.expense_date.isoformat() if expense.expense_date else None,
        "merchant": expense.merchant, "original_amount": str(expense.original_amount) if expense.original_amount is not None else None,
        "original_currency": expense.original_currency, "amount_eur": str(expense.amount) if expense.amount is not None else None,
        "category": expense.category.name if expense.category else None,
        "category_id": expense.category_id, "payment_method": expense.payment_method.name if expense.payment_method else None,
        "scope": expense.scope.value, "memo": expense.memo, "status": expense.status.value,
        "categorization_source": expense.categorization_source, "category_reason": expense.category_reason,
    }


def _active_expense(db: Session, session: ConversationSession) -> Expense | None:
    if not session.active_expense_id:
        return None
    return db.scalar(select(Expense).options(joinedload(Expense.category), joinedload(Expense.payment_method)).where(Expense.id == session.active_expense_id, Expense.deleted_at.is_(None)))


def _expense_by_ref(db: Session, session: ConversationSession, values: dict[str, Any]) -> Expense | None:
    if values.get("active"):
        return _active_expense(db, session)
    expense_id = str(values.get("expense_id") or "").strip()
    if not expense_id:
        return None
    return db.scalar(select(Expense).options(joinedload(Expense.category), joinedload(Expense.payment_method)).where(Expense.id == expense_id, Expense.deleted_at.is_(None)))


def _scope(value: Any, *, nullable: bool = False) -> ExpenseScope | None:
    if value is None and nullable:
        return None
    try:
        return ExpenseScope(str(value or "unknown"))
    except ValueError as exc:
        raise ValueError("scope must be personal, business, or unknown") from exc


def _category(db: Session, values: dict[str, Any]) -> Category | None:
    category_id = values.get("category_id")
    if category_id:
        category = db.get(Category, str(category_id))
        if not category or category.archived:
            raise ValueError("category_id is not an active category")
        return category
    category_code = values.get("category_code")
    if category_code:
        category = db.scalar(select(Category).where(Category.code == str(category_code).upper(), Category.archived.is_(False)))
        if not category:
            raise ValueError("category_code is not an active category")
        return category
    return None


def _payment(db: Session, method_id: Any) -> PaymentMethod | None:
    if not method_id:
        return None
    method = db.get(PaymentMethod, str(method_id))
    if not method or method.archived:
        raise ValueError("payment_method_id is not active")
    return method


def _parse_range(values: dict[str, Any]) -> tuple[date | None, date | None]:
    start = parse_date(str(values["date_from"])) if values.get("date_from") else None
    end = parse_date(str(values["date_to"])) if values.get("date_to") else None
    if values.get("date_from") and not start or values.get("date_to") and not end:
        raise ValueError("dates must use YYYY-MM-DD")
    if start and end and start > end:
        raise ValueError("date_from must be on or before date_to")
    return start, end


def _create_expense(db: Session, values: dict[str, Any]) -> dict[str, Any]:
    expense_date = parse_date(str(values.get("expense_date") or ""))
    amount = parse_decimal(str(values.get("original_amount") or ""))
    merchant = str(values.get("merchant") or "").strip()[:180]
    currency = str(values.get("original_currency") or "").upper().strip()
    if not expense_date or not amount or not merchant or len(currency) != 3:
        raise ValueError("date, merchant, amount, and a three-letter currency are required")
    category = _category(db, values)
    payment = _payment(db, values.get("payment_method_id"))
    rate, rate_date = get_eur_rate(db, currency, expense_date)
    normalized_amount = (amount * rate).quantize(Decimal("0.01")) if rate is not None else None
    expense = Expense(
        expense_date=expense_date, merchant=merchant, merchant_normalized=normalize_merchant(merchant),
        original_amount=amount, original_currency=currency, amount=normalized_amount, currency="EUR",
        conversion_rate=rate, fx_rate_date=rate_date, fx_estimated=bool(rate_date and rate_date != expense_date),
        category_id=category.id if category else None, payment_method_id=payment.id if payment else None,
        scope=_scope(values.get("scope")), memo=str(values.get("memo") or "")[:2_000] or None,
        confidence=1, status=IngestionStatus.accepted, categorization_source="manual", category_reason="Created manually in Telegram.",
        quickbooks_category=category.quickbooks_category if category else None, quickbooks_vendor=merchant,
    )
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return _expense_dict(expense)


def _edit_expense(db: Session, session: ConversationSession, values: dict[str, Any]) -> dict[str, Any]:
    expense = _expense_by_ref(db, session, values)
    if not expense:
        raise ValueError("expense not found; use an explicit id or an active receipt")
    changes = values.get("changes")
    if not isinstance(changes, dict):
        raise ValueError("changes must be an object")
    allowed = {"expense_date", "merchant", "original_amount", "original_currency", "scope", "memo", "location", "category_id", "category_code", "payment_method_id", "category_reason"}
    unknown = set(changes) - allowed
    if unknown:
        raise ValueError("unsupported expense fields: " + ", ".join(sorted(unknown)))
    if "expense_date" in changes:
        parsed = parse_date(str(changes["expense_date"]))
        if not parsed:
            raise ValueError("expense_date must use YYYY-MM-DD")
        expense.expense_date = parsed
    if "merchant" in changes:
        expense.merchant = str(changes["merchant"] or "").strip()[:180] or None
        expense.merchant_normalized = normalize_merchant(expense.merchant)
    if "original_amount" in changes:
        parsed_amount = parse_decimal(str(changes["original_amount"]))
        if parsed_amount is None:
            raise ValueError("original_amount must be a number")
        expense.original_amount = parsed_amount
    if "original_currency" in changes:
        currency = str(changes["original_currency"] or "").upper().strip()
        if len(currency) != 3:
            raise ValueError("original_currency must be three letters")
        expense.original_currency = currency
    if "scope" in changes:
        expense.scope = _scope(changes["scope"]) or ExpenseScope.unknown
    if "memo" in changes:
        expense.memo = str(changes["memo"] or "")[:2_000] or None
    if "location" in changes:
        expense.location = str(changes["location"] or "")[:180] or None
    if "category_id" in changes or "category_code" in changes:
        category = _category(db, changes)
        expense.category_id = category.id if category else None
        expense.quickbooks_category = category.quickbooks_category if category else None
    if "payment_method_id" in changes:
        method = _payment(db, changes["payment_method_id"])
        expense.payment_method_id = method.id if method else None
    if "category_reason" in changes:
        expense.category_reason = str(changes["category_reason"] or "")[:600] or None
    if {"expense_date", "original_amount", "original_currency"} & set(changes) and expense.expense_date and expense.original_amount is not None and expense.original_currency:
        rate, rate_date = get_eur_rate(db, expense.original_currency, expense.expense_date)
        expense.conversion_rate, expense.fx_rate_date = rate, rate_date
        expense.fx_estimated = bool(rate_date and rate_date != expense.expense_date)
        expense.amount = (Decimal(expense.original_amount) * rate).quantize(Decimal("0.01")) if rate else None
    if {"category_id", "category_code", "payment_method_id", "scope", "category_reason"} & set(changes):
        expense.categorization_source = "manual"
        expense.category_reason = expense.category_reason or "Updated manually in Telegram."
    db.commit()
    db.refresh(expense)
    return _expense_dict(expense)


def _search_expenses(db: Session, values: dict[str, Any]) -> list[dict[str, Any]]:
    start, end = _parse_range(values)
    query = select(Expense).options(joinedload(Expense.category), joinedload(Expense.payment_method)).where(Expense.deleted_at.is_(None))
    if values.get("query"):
        needle = f"%{str(values['query']).strip()}%"
        query = query.where((Expense.merchant.ilike(needle)) | (Expense.memo.ilike(needle)))
    if start:
        query = query.where(Expense.expense_date >= start)
    if end:
        query = query.where(Expense.expense_date <= end)
    if values.get("scope"):
        query = query.where(Expense.scope == _scope(values["scope"]))
    limit = int(values.get("limit") or 10)
    if not 1 <= limit <= 50:
        raise ValueError("limit must be from 1 to 50")
    return [_expense_dict(item) for item in db.scalars(query.order_by(Expense.expense_date.desc(), Expense.created_at.desc()).limit(limit)).unique().all()]


def _summarize(db: Session, values: dict[str, Any]) -> dict[str, Any]:
    start, end = _parse_range(values)
    clauses = [Expense.deleted_at.is_(None), Expense.status == IngestionStatus.accepted]
    if start:
        clauses.append(Expense.expense_date >= start)
    if end:
        clauses.append(Expense.expense_date <= end)
    if values.get("scope"):
        clauses.append(Expense.scope == _scope(values["scope"]))
    total = db.scalar(select(func.coalesce(func.sum(Expense.amount), 0)).where(*clauses)) or 0
    group_by = values.get("group_by") or "category"
    if group_by == "category":
        rows = db.execute(select(Category.name, func.sum(Expense.amount)).join(Expense).where(*clauses).group_by(Category.name).order_by(func.sum(Expense.amount).desc())).all()
        groups = [{"name": name, "amount_eur": str(amount or 0)} for name, amount in rows]
    elif group_by == "merchant":
        rows = db.execute(select(Expense.merchant, func.sum(Expense.amount)).where(*clauses).group_by(Expense.merchant).order_by(func.sum(Expense.amount).desc())).all()
        groups = [{"name": name or "Unknown", "amount_eur": str(amount or 0)} for name, amount in rows]
    elif group_by == "month":
        rows = db.execute(select(func.strftime("%Y-%m", Expense.expense_date), func.sum(Expense.amount)).where(*clauses).group_by(func.strftime("%Y-%m", Expense.expense_date)).order_by(func.strftime("%Y-%m", Expense.expense_date))).all()
        groups = [{"name": name, "amount_eur": str(amount or 0)} for name, amount in rows]
    else:
        raise ValueError("group_by must be category, merchant, or month")
    return {"total_eur": str(total), "date_from": start.isoformat() if start else None, "date_to": end.isoformat() if end else None, "groups": groups}


def _set_default_method(db: Session, method: PaymentMethod) -> None:
    for item in db.scalars(select(PaymentMethod).where(PaymentMethod.is_default.is_(True), PaymentMethod.id != method.id)):
        item.is_default = False
    method.is_default = True


def _manage_category(db: Session, values: dict[str, Any]) -> dict[str, Any]:
    action, data = values.get("action"), values.get("values") or {}
    if not isinstance(data, dict):
        raise ValueError("values must be an object")
    if action == "create":
        code, name = str(data.get("code") or "").upper().strip(), str(data.get("name") or "").strip()
        if not code or not name or db.scalar(select(Category).where(Category.code == code)):
            raise ValueError("a unique category code and name are required")
        category = Category(code=code, name=name, scope=_scope(data.get("scope")), color=str(data.get("color") or "#7A365D")[:16], icon=str(data.get("icon") or "category")[:32], quickbooks_category=data.get("quickbooks_category"))
        db.add(category); db.commit()
        return {"id": category.id, "name": category.name, "action": "created"}
    category = db.get(Category, str(values.get("category_id") or ""))
    if not category:
        raise ValueError("category not found")
    if action == "edit":
        for key in {"name", "color", "icon", "quickbooks_category"} & set(data):
            setattr(category, key, data[key])
        if "code" in data:
            candidate = str(data["code"]).upper().strip()
            if not candidate or db.scalar(select(Category).where(Category.code == candidate, Category.id != category.id)):
                raise ValueError("category code must be unique")
            category.code = candidate
        if "scope" in data:
            category.scope = _scope(data["scope"]) or ExpenseScope.unknown
        db.commit(); return {"id": category.id, "name": category.name, "action": "updated"}
    raise ValueError("category action must be create, edit, or archive")


def _manage_payment(db: Session, values: dict[str, Any]) -> dict[str, Any]:
    action, data = values.get("action"), values.get("values") or {}
    if not isinstance(data, dict):
        raise ValueError("values must be an object")
    if action == "create":
        name = str(data.get("name") or "").strip()
        if not name or db.scalar(select(PaymentMethod).where(PaymentMethod.name == name)):
            raise ValueError("a unique payment method name is required")
        method = PaymentMethod(name=name, method_type=str(data.get("method_type") or "card")[:40], last_four=str(data["last_four"])[-4:] if data.get("last_four") else None, is_default=False)
        db.add(method)
        if data.get("is_default"):
            _set_default_method(db, method)
        db.commit(); return {"id": method.id, "name": method.name, "action": "created"}
    method = db.get(PaymentMethod, str(values.get("method_id") or ""))
    if not method:
        raise ValueError("payment method not found")
    if action == "edit":
        for key in {"name", "method_type"} & set(data):
            setattr(method, key, str(data[key]).strip())
        if "last_four" in data:
            last_four = str(data["last_four"] or "")
            if last_four and (len(last_four) != 4 or not last_four.isdigit()):
                raise ValueError("last_four must be four digits")
            method.last_four = last_four or None
        if data.get("is_default"):
            _set_default_method(db, method)
        db.commit(); return {"id": method.id, "name": method.name, "action": "updated"}
    raise ValueError("payment action must be create, edit, or archive")


def _manage_rule(db: Session, values: dict[str, Any]) -> dict[str, Any]:
    action, data = values.get("action"), values.get("values") or {}
    if not isinstance(data, dict):
        raise ValueError("values must be an object")
    if action == "create":
        display = str(data.get("merchant_display") or "").strip()
        normalized = normalize_merchant(str(data.get("merchant_normalized") or display))
        if not display or not normalized or db.scalar(select(MerchantRule).where(MerchantRule.merchant_normalized == normalized)):
            raise ValueError("a unique merchant display is required")
        category = _category(db, data); method = _payment(db, data.get("payment_method_id"))
        rule = MerchantRule(merchant_display=display, merchant_normalized=normalized, category_id=category.id if category else None, payment_method_id=method.id if method else None, scope=_scope(data.get("scope"), nullable=True), enabled=bool(data.get("enabled", True)))
        db.add(rule); db.commit(); return {"id": rule.id, "merchant": rule.merchant_display, "action": "created"}
    rule = db.get(MerchantRule, str(values.get("rule_id") or ""))
    if not rule:
        raise ValueError("merchant rule not found")
    if action == "edit":
        if "merchant_display" in data:
            rule.merchant_display = str(data["merchant_display"]).strip()
            rule.merchant_normalized = normalize_merchant(str(data.get("merchant_normalized") or rule.merchant_display)) or rule.merchant_normalized
        if "category_id" in data or "category_code" in data:
            category = _category(db, data); rule.category_id = category.id if category else None
        if "payment_method_id" in data:
            method = _payment(db, data["payment_method_id"]); rule.payment_method_id = method.id if method else None
        if "scope" in data: rule.scope = _scope(data["scope"], nullable=True)
        if "enabled" in data: rule.enabled = bool(data["enabled"])
        db.commit(); return {"id": rule.id, "merchant": rule.merchant_display, "action": "updated"}
    raise ValueError("merchant rule action must be create, edit, or delete")


def _request_confirmation(db: Session, session: ConversationSession, job: ChatJob, action_type: str, payload: dict[str, Any], label: str) -> dict[str, Any]:
    action = PendingAction(token=secrets.token_urlsafe(24), telegram_chat_id=job.telegram_chat_id, telegram_user_id=job.telegram_user_id, action_type=action_type, payload={**payload, "session_id": session.id}, expires_at=datetime.now(timezone.utc) + PENDING_ACTION_AGE)
    db.add(action); db.flush()
    job.pending_action_token = action.token
    return {"confirmation_required": True, "confirmation_token": action.token, "message": f"{label} needs your confirmation. It expires in 10 minutes."}


def execute_tool(db: Session, session: ConversationSession, job: ChatJob, name: str, values: dict[str, Any]) -> dict[str, Any]:
    """Execute one whitelisted tool and return JSON-safe results to the model."""
    if not isinstance(values, dict):
        raise ValueError("tool arguments must be an object")
    if name == "search_expenses": return {"expenses": _search_expenses(db, values)}
    if name == "inspect_expense":
        expense = _expense_by_ref(db, session, values)
        if not expense: raise ValueError("expense not found")
        return {"expense": _expense_dict(expense)}
    if name == "summarize_spending": return _summarize(db, values)
    if name == "create_expense": return {"expense": _create_expense(db, values)}
    if name == "edit_expense": return {"expense": _edit_expense(db, session, values)}
    if name == "manage_category":
        if values.get("action") == "archive":
            category = db.get(Category, str(values.get("category_id") or ""))
            if not category: raise ValueError("category not found")
            return _request_confirmation(db, session, job, "archive_category", {"category_id": category.id}, f"Archive category {category.name}")
        return {"category": _manage_category(db, values)}
    if name == "manage_payment_method":
        if values.get("action") == "archive":
            method = db.get(PaymentMethod, str(values.get("method_id") or ""))
            if not method: raise ValueError("payment method not found")
            return _request_confirmation(db, session, job, "archive_payment_method", {"method_id": method.id}, f"Archive payment method {method.name}")
        return {"payment_method": _manage_payment(db, values)}
    if name == "manage_merchant_rule":
        if values.get("action") == "delete":
            rule = db.get(MerchantRule, str(values.get("rule_id") or ""))
            if not rule: raise ValueError("merchant rule not found")
            return _request_confirmation(db, session, job, "delete_merchant_rule", {"rule_id": rule.id}, f"Delete merchant rule {rule.merchant_display}")
        return {"merchant_rule": _manage_rule(db, values)}
    if name == "export_expenses":
        start, end = _parse_range(values)
        scope = _scope(values["scope"]) if values.get("scope") else None
        job.export_request = {"date_from": start.isoformat() if start else None, "date_to": end.isoformat() if end else None, "scope": scope.value if scope else None}  # type: ignore[attr-defined]
        return {"export": "CSV prepared for Telegram delivery"}
    if name == "delete_expense":
        expense = _expense_by_ref(db, session, values)
        if not expense: raise ValueError("expense not found")
        return _request_confirmation(db, session, job, "delete_expense", {"expense_id": expense.id}, f"Delete {expense.merchant or 'this expense'}")
    if name == "bulk_edit_expenses":
        ids, changes = values.get("expense_ids"), values.get("changes")
        if not isinstance(ids, list) or not 2 <= len(ids) <= 50 or not isinstance(changes, dict):
            raise ValueError("bulk edits need 2–50 expense_ids and a changes object")
        matches = list(db.scalars(
            select(Expense).where(Expense.id.in_([str(item) for item in ids]), Expense.deleted_at.is_(None))
        ).all())
        if len(matches) != len(set(str(item) for item in ids)):
            raise ValueError("one or more expense IDs were not found")
        return _request_confirmation(db, session, job, "bulk_edit_expenses", {"expense_ids": [item.id for item in matches], "changes": changes}, f"Update {len(matches)} expenses")
    raise ValueError("unsupported tool")


def _perform_pending_action(db: Session, action: PendingAction) -> str:
    if action.action_type == "delete_expense":
        expense = db.get(Expense, action.payload["expense_id"])
        if not expense or expense.deleted_at: return "That expense no longer exists."
        expense.deleted_at = datetime.now(timezone.utc); db.commit(); return "Expense deleted."
    if action.action_type == "archive_category":
        category = db.get(Category, action.payload["category_id"])
        if not category: return "That category no longer exists."
        category.archived = True; db.commit(); return f"Archived {category.name}."
    if action.action_type == "archive_payment_method":
        method = db.get(PaymentMethod, action.payload["method_id"])
        if not method: return "That payment method no longer exists."
        if method.is_default and not db.scalar(select(PaymentMethod).where(PaymentMethod.id != method.id, PaymentMethod.is_default.is_(True), PaymentMethod.archived.is_(False))):
            return "Choose another default payment method before archiving this one."
        method.archived = True; db.commit(); return f"Archived {method.name}."
    if action.action_type == "delete_merchant_rule":
        rule = db.get(MerchantRule, action.payload["rule_id"])
        if not rule: return "That merchant rule no longer exists."
        db.delete(rule); db.commit(); return "Merchant rule deleted."
    if action.action_type == "bulk_edit_expenses":
        changes = action.payload["changes"]
        # Run through the same field validator one record at a time.
        session = db.get(ConversationSession, action.payload.get("session_id"))
        if not session: raise ValueError("the confirmation no longer has a conversation session")
        for expense_id in action.payload["expense_ids"]:
            _edit_expense(db, session, {"expense_id": expense_id, "changes": changes})
        return f"Updated {len(action.payload['expense_ids'])} expenses."
    raise ValueError("unsupported pending action")


def consume_pending_action(db: Session, token: str, chat_id: str | int, user_id: str | int, confirmed: bool) -> str:
    action = db.scalar(select(PendingAction).where(PendingAction.token == token))
    if not action or action.telegram_chat_id != str(chat_id) or action.telegram_user_id != str(user_id):
        return "That confirmation is not available."
    stamp = action.expires_at if action.expires_at.tzinfo else action.expires_at.replace(tzinfo=timezone.utc)
    if action.used_at or stamp < datetime.now(timezone.utc):
        return "That confirmation has expired."
    action.used_at = datetime.now(timezone.utc)
    if not confirmed:
        db.commit(); return "Cancelled. Nothing changed."
    result = _perform_pending_action(db, action)
    db.commit()
    return result


def _system_prompt(session: ConversationSession) -> str:
    anchor = f"Active receipt ingestion: {session.active_ingestion_id or 'none'}; active expense: {session.active_expense_id or 'none'}."
    return (
        "You are Spendloom, a warm single-user personal finance assistant. "
        "Use tools for any ledger fact, arithmetic, or change; never invent amounts, ids, or records. "
        "Ordinary one-record corrections can be completed through tools. Destructive, archive, replacement, and bulk actions must use their confirmation tool result. "
        "Keep Telegram replies concise and state what changed. " + anchor
    )


def _retained_provider_messages(db: Session, session: ConversationSession) -> list[dict[str, str]]:
    history = db.scalars(select(ConversationMessage).where(ConversationMessage.session_id == session.id).order_by(ConversationMessage.created_at)).all()
    return [{"role": item.role, "content": item.content} for item in history]


def process_chat_job(db: Session, settings: Settings, job_id: str) -> ChatJob | None:
    job = db.get(ChatJob, job_id)
    if not job or job.status not in {"queued", "processing"}:
        return job
    job.status = "processing"; job.attempts += 1; job.error_message = None; job.pending_action_token = None; job.export_request = None
    prior_user_message = db.scalar(select(ConversationMessage).where(ConversationMessage.session_id == job.session_id, ConversationMessage.role == "user", ConversationMessage.telegram_message_id == job.telegram_message_id))
    if not prior_user_message:
        db.add(ConversationMessage(session_id=job.session_id, role="user", content=job.text, approximate_tokens=_tokens(job.text), telegram_message_id=job.telegram_message_id))
    trim_history(db, job.session_id); db.commit()
    session = db.get(ConversationSession, job.session_id)
    try:
        provider = chat_provider_for(settings)
        messages = [{"role": "system", "content": _system_prompt(session)}, *_retained_provider_messages(db, session)]
        completion = provider.complete(messages, CHAT_TOOL_CONTRACT)
        tool_results: list[dict[str, Any]] = []
        for call in (completion.tool_calls or [])[:6]:
            try:
                tool_results.append({"tool": call.name, "result": execute_tool(db, session, job, call.name, call.arguments)})
            except (ValueError, TypeError) as exc:
                tool_results.append({"tool": call.name, "error": str(exc)})
        if tool_results and not job.pending_action_token:
            followup = [*messages, {"role": "assistant", "content": completion.text or "I checked the ledger."}, {"role": "user", "content": "Tool results (trusted server data):\n" + json.dumps(tool_results, default=str) + "\nReply concisely to the user."}]
            completion = provider.complete(followup, CHAT_TOOL_CONTRACT)
        if job.pending_action_token:
            response_text = next((result["result"].get("message") for result in tool_results if isinstance(result.get("result"), dict) and result["result"].get("confirmation_required")), "Confirmation required.")
        else:
            response_text = completion.text or _tool_fallback_text(tool_results)
        job.response_text = response_text[:12_000]
        job.status = "completed"; job.processed_at = datetime.now(timezone.utc)
        db.add(ConversationMessage(session_id=job.session_id, role="assistant", content=job.response_text, approximate_tokens=_tokens(job.response_text)))
        trim_history(db, job.session_id); db.commit(); db.refresh(job)
    except Exception as exc:
        logger.exception("Chat job %s failed", job.id)
        job.error_message = str(exc)[:500]
        if job.attempts >= 3:
            job.status = "failed"; job.response_text = "I couldn’t complete that request. Please try again later."
            job.processed_at = datetime.now(timezone.utc)
        else:
            job.status = "queued"
        db.commit()
    return job


def _tool_fallback_text(results: list[dict[str, Any]]) -> str:
    if not results: return "I’m here to help with your spending and receipts."
    errors = [item["error"] for item in results if "error" in item]
    if errors: return "I couldn’t complete that: " + errors[0]
    return "Done."


def process_next_chat(db: Session, settings: Settings) -> ChatJob | None:
    job = db.scalar(select(ChatJob).where(ChatJob.status == "queued").order_by(ChatJob.created_at).limit(1))
    return process_chat_job(db, settings, job.id) if job else None


def export_csv_bytes(db: Session, request: dict[str, Any]) -> tuple[bytes, str]:
    values = dict(request or {})
    start, end = _parse_range(values)
    query = select(Expense).options(joinedload(Expense.category), joinedload(Expense.payment_method)).where(Expense.deleted_at.is_(None), Expense.status == IngestionStatus.accepted)
    if start: query = query.where(Expense.expense_date >= start)
    if end: query = query.where(Expense.expense_date <= end)
    if values.get("scope"): query = query.where(Expense.scope == _scope(values["scope"]))
    stream = io.StringIO(); writer = csv.writer(stream)
    writer.writerow(["Date", "Merchant", "Amount EUR", "Original amount", "Original currency", "Category", "Payment method", "Scope", "Memo"])
    for expense in db.scalars(query.order_by(Expense.expense_date)).unique().all():
        writer.writerow([expense.expense_date.isoformat() if expense.expense_date else "", expense.merchant or "", expense.amount or "", expense.original_amount or "", expense.original_currency or "", expense.category.name if expense.category else "", expense.payment_method.name if expense.payment_method else "", expense.scope.value, expense.memo or ""])
    suffix = f"{start.isoformat() if start else 'all'}-{end.isoformat() if end else 'time'}"
    return stream.getvalue().encode("utf-8"), f"spendloom-expenses-{suffix}.csv"
