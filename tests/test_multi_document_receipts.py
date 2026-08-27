import asyncio
import io
import tempfile
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from alembic import command
from alembic.config import Config
from PIL import Image
from sqlalchemy import create_engine, select, text
from starlette.datastructures import Headers, UploadFile

from receipt_ledger.api import export_reimbursement_zip, startup, upload_receipts
from receipt_ledger.config import get_settings
from receipt_ledger.database import SessionLocal
from receipt_ledger.models import (
    Category,
    ConversationMessage,
    Expense,
    ExpenseScope,
    IngestionStatus,
)
from receipt_ledger.schemas import (
    IngestionOut,
    ReceiptExtraction,
    ReimbursementExportRequest,
)
from receipt_ledger.services.chat import anchor_receipt, get_or_create_session
from receipt_ledger.services.ingestion import (
    append_ingestion_document,
    create_receipt_grouping_choice,
    ingest_bytes,
    ingestion_documents,
    resolve_receipt_grouping_choice,
    schedule_ingestion,
)
from receipt_ledger.services.processing import process_ingestion


def jpeg(color: str) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (80, 120), color).save(output, "JPEG")
    return output.getvalue()


def upload_file(filename: str, color: str) -> UploadFile:
    file = tempfile.SpooledTemporaryFile()
    file.write(jpeg(color))
    file.seek(0)
    return UploadFile(
        file=file,
        filename=filename,
        headers=Headers({"content-type": "image/jpeg"}),
    )


def test_migration_backfills_primary_documents(tmp_path: Path) -> None:
    database_path = tmp_path / "migration.db"
    root = Path(__file__).resolve().parent.parent
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "0002_spendloom_chat")
    engine = create_engine(f"sqlite:///{database_path}")
    received_at = "2026-08-01 00:00:00.000000"
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO receipts "
                "(id, sha256, original_filename, mime_type, size_bytes, storage_path, preview_path, page_count, created_at) "
                "VALUES (:id, :sha256, :filename, :mime, :size, :path, NULL, :pages, :created)"
            ),
            {
                "id": "migration-receipt",
                "sha256": "a" * 64,
                "filename": "legacy.jpg",
                "mime": "image/jpeg",
                "size": 12,
                "path": "/tmp/legacy.jpg",
                "pages": 1,
                "created": received_at,
            },
        )
        connection.execute(
            text(
                "INSERT INTO ingestions "
                "(id, receipt_id, expense_id, source, external_id, source_user_id, source_chat_id, caption, status, attempts, error_code, error_message, provider, model, raw_extraction, received_at, processed_at, notification_sent_at) "
                "VALUES (:id, :receipt, NULL, :source, :external, NULL, NULL, :caption, :status, 0, NULL, NULL, NULL, NULL, NULL, :received, NULL, NULL)"
            ),
            {
                "id": "migration-ingestion",
                "receipt": "migration-receipt",
                "source": "web",
                "external": "legacy-upload",
                "caption": "legacy caption",
                "status": "queued",
                "received": received_at,
            },
        )

    command.upgrade(config, "head")

    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT ingestion_id, receipt_id, position, source, external_id, caption "
                "FROM ingestion_documents"
            )
        ).one()
    assert tuple(row) == (
        "migration-ingestion",
        "migration-receipt",
        0,
        "web",
        "legacy-upload",
        "legacy caption",
    )


class RecordingProvider:
    def __init__(self, category_code: str) -> None:
        self.category_code = category_code
        self.image_count = 0
        self.prompt = ""

    def extract(self, prompt, images):
        self.prompt = prompt
        self.image_count = len(images)
        return ReceiptExtraction(
            expense_date="2026-08-20",
            merchant="Grouped Merchant",
            original_amount="12.00",
            original_currency="EUR",
            category_code=self.category_code,
            scope="business",
            location="London",
            memo="Combined documents",
            confidence=0.99,
        )


def test_grouped_documents_are_extracted_into_one_expense(monkeypatch) -> None:
    startup()
    settings = get_settings()
    with SessionLocal() as db:
        category = db.scalar(select(Category).order_by(Category.code))
        provider = RecordingProvider(category.code)
        monkeypatch.setattr(
            "receipt_ledger.services.processing.provider_for",
            lambda _settings: provider,
        )
        first = ingest_bytes(
            db,
            settings,
            data=jpeg("navy"),
            filename="group-front.jpg",
            claimed_mime="image/jpeg",
            source="web",
            external_id="group-document-front",
            group_external_id="grouped-receipt-one",
            caption="Front",
        )
        second = ingest_bytes(
            db,
            settings,
            data=jpeg("orange"),
            filename="group-back.jpg",
            claimed_mime="image/jpeg",
            source="web",
            external_id="group-document-back",
            group_external_id="grouped-receipt-one",
            caption="Back",
        )

        assert second.id == first.id
        assert len(ingestion_documents(db, first.id)) == 2

        result = process_ingestion(db, settings, first.id)

        assert provider.image_count == 2
        assert "Document 1: Front" in provider.prompt
        assert "Document 2: Back" in provider.prompt
        assert result.expense_id is not None
        assert db.get(Expense, result.expense_id).merchant == "Grouped Merchant"


def test_web_upload_can_group_files_or_keep_them_separate() -> None:
    startup()
    with SessionLocal() as db:
        grouped = asyncio.run(
            upload_receipts(
                None,
                db,
                [
                    upload_file("web-group-one.jpg", "gold"),
                    upload_file("web-group-two.jpg", "silver"),
                ],
                "One purchase",
                True,
            )
        )
        separate = asyncio.run(
            upload_receipts(
                None,
                db,
                [
                    upload_file("web-separate-one.jpg", "lime"),
                    upload_file("web-separate-two.jpg", "maroon"),
                ],
                None,
                False,
            )
        )

        assert len(grouped) == 1
        assert len(ingestion_documents(db, grouped[0].id)) == 2
        assert IngestionOut.model_validate(grouped[0]).document_count == 2
        assert len(separate) == 2
        assert separate[0].id != separate[1].id


def test_reprocessing_fills_gaps_without_replacing_existing_values(monkeypatch) -> None:
    startup()
    settings = get_settings()
    with SessionLocal() as db:
        category = db.scalar(select(Category).order_by(Category.code))
        provider = RecordingProvider(category.code)
        monkeypatch.setattr(
            "receipt_ledger.services.processing.provider_for",
            lambda _settings: provider,
        )
        ingestion = ingest_bytes(
            db,
            settings,
            data=jpeg("teal"),
            filename="existing-front.jpg",
            claimed_mime="image/jpeg",
            source="web",
            external_id="existing-front-document",
        )
        expense = Expense(
            expense_date=date(2026, 8, 19),
            merchant="Authoritative Merchant",
            merchant_normalized="authoritative merchant",
            original_amount=Decimal("12.00"),
            original_currency="EUR",
            amount=Decimal("12.00"),
            currency="EUR",
            category_id=category.id,
            scope=ExpenseScope.business,
            confidence=Decimal("0.95"),
            status=IngestionStatus.accepted,
        )
        db.add(expense)
        db.flush()
        ingestion.expense_id = expense.id
        ingestion.status = IngestionStatus.accepted
        db.commit()
        original_expense_id = expense.id

        append_ingestion_document(
            db,
            settings,
            ingestion=ingestion,
            data=jpeg("violet"),
            filename="existing-back.jpg",
            claimed_mime="image/jpeg",
            source="web",
            external_id="existing-back-document",
        )
        schedule_ingestion(db, ingestion, ready_at=datetime.now(timezone.utc))

        process_ingestion(db, settings, ingestion.id)
        db.refresh(expense)

        assert ingestion.expense_id == original_expense_id
        assert expense.merchant == "Authoritative Merchant"
        assert expense.location == "London"
        assert expense.memo == "Combined documents"
        assert expense.status == IngestionStatus.needs_review


def test_receipt_grouping_choice_merges_without_clearing_context() -> None:
    startup()
    settings = get_settings()
    with SessionLocal() as db:
        target = ingest_bytes(
            db,
            settings,
            data=jpeg("black"),
            filename="choice-target.jpg",
            claimed_mime="image/jpeg",
            source="telegram",
            external_id="choice-target",
            source_chat_id="choice-chat",
            source_user_id="choice-user",
        )
        source = ingest_bytes(
            db,
            settings,
            data=jpeg("white"),
            filename="choice-source.jpg",
            claimed_mime="image/jpeg",
            source="telegram",
            external_id="choice-source",
            source_chat_id="choice-chat",
            source_user_id="choice-user",
        )
        anchor_receipt(db, "choice-chat", "choice-user", target.id)
        session = get_or_create_session(db, "choice-chat", "choice-user")
        db.add(
            ConversationMessage(
                session_id=session.id,
                role="user",
                content="keep this context",
                approximate_tokens=4,
            )
        )
        db.commit()
        action = create_receipt_grouping_choice(
            db,
            source_ingestion=source,
            target_ingestion=target,
            chat_id="choice-chat",
            user_id="choice-user",
        )

        merged, start_new, _message = resolve_receipt_grouping_choice(
            db,
            settings,
            token=action.token,
            chat_id="choice-chat",
            user_id="choice-user",
            add_to_current=True,
        )

        assert merged is not None
        assert start_new is False
        assert len(ingestion_documents(db, target.id)) == 2
        db.refresh(source)
        assert source.merged_into_ingestion_id == target.id
        assert db.scalar(
            select(ConversationMessage).where(
                ConversationMessage.session_id == session.id,
                ConversationMessage.content == "keep this context",
            )
        ) is not None


def test_reimbursement_zip_includes_every_grouped_document() -> None:
    startup()
    settings = get_settings()
    with SessionLocal() as db:
        category = db.scalar(select(Category).order_by(Category.code))
        ingestion = ingest_bytes(
            db,
            settings,
            data=jpeg("pink"),
            filename="export-front.jpg",
            claimed_mime="image/jpeg",
            source="web",
            external_id="export-group-front",
        )
        append_ingestion_document(
            db,
            settings,
            ingestion=ingestion,
            data=jpeg("brown"),
            filename="export-back.jpg",
            claimed_mime="image/jpeg",
            source="web",
            external_id="export-group-back",
        )
        expense = Expense(
            expense_date=date(2026, 8, 21),
            merchant="Two Page Shop",
            original_amount=Decimal("7.00"),
            original_currency="EUR",
            amount=Decimal("7.00"),
            currency="EUR",
            category_id=category.id,
            scope=ExpenseScope.business,
            status=IngestionStatus.accepted,
        )
        db.add(expense)
        db.flush()
        ingestion.expense_id = expense.id
        ingestion.status = IngestionStatus.accepted
        db.commit()

        response = export_reimbursement_zip(
            ReimbursementExportRequest(expense_ids=[expense.id]),
            None,
            db,
        )

        with zipfile.ZipFile(io.BytesIO(response.body)) as bundle:
            receipt_names = [
                name
                for name in bundle.namelist()
                if name.startswith("receipts/")
            ]
            assert receipt_names == [
                "receipts/001_01_2026-08-21_Two-Page-Shop.jpg",
                "receipts/001_02_2026-08-21_Two-Page-Shop.jpg",
            ]
            assert "Included document count: 2" in bundle.read("summary.txt").decode()
