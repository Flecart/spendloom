import csv
import io

from PIL import Image
from sqlalchemy import select
from starlette.requests import Request

from receipt_ledger.api import RAMP_HEADERS, export_csv, startup, update_expense
from receipt_ledger.config import get_settings
from receipt_ledger.database import SessionLocal
from receipt_ledger.models import Category, IngestionStatus
from receipt_ledger.schemas import ExpenseUpdate
from receipt_ledger.services.ingestion import ingest_bytes
from receipt_ledger.services.processing import process_next


def jpeg(color: str = "white") -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (80, 120), color).save(output, "JPEG")
    return output.getvalue()


def fake_request() -> Request:
    return Request({"type": "http", "scheme": "http", "server": ("test", 8080), "root_path": "", "path": "/", "headers": []})


def test_ingest_manual_review_accept_and_export() -> None:
    startup()
    with SessionLocal() as db:
        ingestion = ingest_bytes(
            db, get_settings(), data=jpeg(), filename="shop.jpg", claimed_mime="image/jpeg",
            source="web", external_id="first-upload",
        )
        assert ingestion.status == IngestionStatus.queued
        process_next(db, get_settings())
        db.refresh(ingestion)
        assert ingestion.status == IngestionStatus.needs_review
        category = db.scalar(select(Category).order_by(Category.code))
        expense = update_expense(ingestion.expense_id, ExpenseUpdate(
            expense_date="2026-08-10", merchant="Corner Shop", original_amount="12.50",
            original_currency="EUR", category_id=category.id, scope="personal", accept=True,
        ), None, db)
        assert expense.status == IngestionStatus.accepted
        response = export_csv(fake_request(), None, db, extended=True)
        rows = list(csv.DictReader(io.StringIO(response.body.decode())))
        assert rows[0]["Merchant"] == "Corner Shop"
        assert list(rows[0])[:len(RAMP_HEADERS)] == RAMP_HEADERS
        assert rows[0]["Expense Scope"] == "personal"


def test_duplicate_file_is_flagged() -> None:
    startup()
    payload = jpeg("gray")
    with SessionLocal() as db:
        first = ingest_bytes(db, get_settings(), data=payload, filename="one.jpg", claimed_mime="image/jpeg", source="web", external_id="duplicate-a")
        second = ingest_bytes(db, get_settings(), data=payload, filename="two.jpg", claimed_mime="image/jpeg", source="web", external_id="duplicate-b")
        assert first.status == IngestionStatus.queued
        assert second.status == IngestionStatus.duplicate
