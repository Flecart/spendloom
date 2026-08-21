import csv
import io
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path

from PIL import Image
from sqlalchemy import select
from fastapi import HTTPException
from starlette.requests import Request

from receipt_ledger.api import RAMP_HEADERS, export_csv, export_reimbursement_zip, startup, update_expense
from receipt_ledger.config import get_settings
from receipt_ledger.database import SessionLocal
from receipt_ledger.models import Category, Expense, IngestionStatus
from receipt_ledger.schemas import ExpenseUpdate, ReimbursementExportRequest
from receipt_ledger.services.ingestion import ingest_bytes
from receipt_ledger.services.processing import process_next


def jpeg(color: str = "white") -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (80, 120), color).save(output, "JPEG")
    return output.getvalue()


def fake_request() -> Request:
    return Request({"type": "http", "scheme": "http", "server": ("test", 8080), "root_path": "", "path": "/", "headers": []})


def receipt_backed_expense(db, *, external_id: str, color: str, merchant: str, expense_date: date, original_amount: str, original_currency: str, eur_amount: str, status: IngestionStatus = IngestionStatus.accepted):
    ingestion = ingest_bytes(
        db, get_settings(), data=jpeg(color), filename=f"{external_id}.jpg", claimed_mime="image/jpeg",
        source="web", external_id=external_id,
    )
    category = db.scalar(select(Category).order_by(Category.code))
    expense = Expense(
        expense_date=expense_date,
        merchant=merchant,
        original_amount=Decimal(original_amount),
        original_currency=original_currency,
        amount=Decimal(eur_amount),
        currency="EUR",
        category_id=category.id,
        scope="business",
        status=status,
    )
    db.add(expense)
    db.flush()
    ingestion.expense_id = expense.id
    ingestion.status = status
    db.commit()
    db.refresh(expense)
    db.refresh(ingestion)
    return expense, ingestion


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


def test_reimbursement_zip_contains_only_selected_receipts_and_totals() -> None:
    startup()
    with SessionLocal() as db:
        first, first_ingestion = receipt_backed_expense(
            db, external_id="reimbursement-first", color="red", merchant="London Café", expense_date=date(2026, 8, 3),
            original_amount="10.00", original_currency="GBP", eur_amount="11.50",
        )
        second, second_ingestion = receipt_backed_expense(
            db, external_id="reimbursement-second", color="blue", merchant="Paris Taxi", expense_date=date(2026, 8, 4),
            original_amount="8.00", original_currency="EUR", eur_amount="8.00", status=IngestionStatus.needs_review,
        )
        receipt_backed_expense(
            db, external_id="reimbursement-unselected", color="green", merchant="Not Included", expense_date=date(2026, 8, 5),
            original_amount="99.00", original_currency="EUR", eur_amount="99.00",
        )

        response = export_reimbursement_zip(ReimbursementExportRequest(expense_ids=[first.id, second.id]), None, db)
        assert response.media_type == "application/zip"
        assert "spendloom-reimbursement-" in response.headers["content-disposition"]

        with zipfile.ZipFile(io.BytesIO(response.body)) as bundle:
            receipt_names = [name for name in bundle.namelist() if name.startswith("receipts/")]
            assert receipt_names == ["receipts/001_2026-08-03_London-Caf.jpg", "receipts/002_2026-08-04_Paris-Taxi.jpg"]
            assert bundle.read(receipt_names[0]) == Path(first_ingestion.receipt.storage_path).read_bytes()
            assert bundle.read(receipt_names[1]) == Path(second_ingestion.receipt.storage_path).read_bytes()
            rows = list(csv.DictReader(io.StringIO(bundle.read("reimbursement.csv").decode())))
            assert [row["Merchant"] for row in rows] == ["London Café", "Paris Taxi"]
            assert [row["Archive Filename"] for row in rows] == receipt_names
            assert [row["EUR Reimbursement Amount"] for row in rows] == ["11.5000", "8.0000"]
            summary = bundle.read("summary.txt").decode()
            assert "Selected receipt count: 2" in summary
            assert "Total EUR reimbursement amount: 19.50 EUR" in summary
            assert "EUR: 8.00" in summary
            assert "GBP: 10.00" in summary


def test_reimbursement_zip_rejects_empty_invalid_missing_file_and_missing_eur_amount() -> None:
    startup()
    with SessionLocal() as db:
        expense, ingestion = receipt_backed_expense(
            db, external_id="reimbursement-validation", color="purple", merchant="Validation Store", expense_date=date(2026, 8, 6),
            original_amount="6.00", original_currency="EUR", eur_amount="6.00",
        )
        for payload, expected in [
            (ReimbursementExportRequest.model_construct(expense_ids=[]), "Select at least one expense"),
            (ReimbursementExportRequest(expense_ids=["not-an-expense"]), "do not exist or have been deleted"),
        ]:
            try:
                export_reimbursement_zip(payload, None, db)
                assert False, "Expected reimbursement export to be rejected"
            except HTTPException as exc:
                assert expected in exc.detail

        original_storage_path = ingestion.receipt.storage_path
        ingestion.receipt.storage_path = str(get_settings().data_dir / "missing-receipt.jpg")
        db.commit()
        try:
            export_reimbursement_zip(ReimbursementExportRequest(expense_ids=[expense.id]), None, db)
            assert False, "Expected export with a missing file to be rejected"
        except HTTPException as exc:
            assert "Receipt file" in exc.detail

        ingestion.receipt.storage_path = original_storage_path
        expense.amount = None
        db.commit()
        try:
            export_reimbursement_zip(ReimbursementExportRequest(expense_ids=[expense.id]), None, db)
            assert False, "Expected export with no EUR amount to be rejected"
        except HTTPException as exc:
            assert "normalized EUR amount" in exc.detail
