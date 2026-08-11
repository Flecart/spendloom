from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import Ingestion, IngestionStatus, Receipt, uuid_str
from .storage import InvalidReceiptFile, save_original, sha256_bytes, sniff_mime


def ingest_bytes(
    db: Session,
    settings: Settings,
    *,
    data: bytes,
    filename: str,
    claimed_mime: str | None,
    source: str,
    external_id: str,
    caption: str | None = None,
    source_user_id: str | None = None,
    source_chat_id: str | None = None,
) -> Ingestion:
    existing_source = db.scalar(
        select(Ingestion).where(Ingestion.source == source, Ingestion.external_id == external_id)
    )
    if existing_source:
        return existing_source
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise InvalidReceiptFile(f"File exceeds the {settings.max_upload_mb} MB web upload limit")

    mime = sniff_mime(data, claimed_mime, filename)
    digest = sha256_bytes(data)
    existing_receipt = db.scalar(select(Receipt).where(Receipt.sha256 == digest))
    if existing_receipt:
        prior = db.scalar(
            select(Ingestion)
            .where(Ingestion.receipt_id == existing_receipt.id, Ingestion.expense_id.is_not(None))
            .order_by(Ingestion.received_at.desc())
        )
        duplicate = Ingestion(
            receipt_id=existing_receipt.id,
            expense_id=prior.expense_id if prior else None,
            source=source,
            external_id=external_id,
            source_user_id=source_user_id,
            source_chat_id=source_chat_id,
            caption=caption,
            status=IngestionStatus.duplicate,
            processed_at=datetime.now(timezone.utc),
        )
        db.add(duplicate)
        db.commit()
        db.refresh(duplicate)
        return duplicate

    receipt_id = uuid_str()
    path, clean_name = save_original(settings, receipt_id, filename, data)
    receipt = Receipt(
        id=receipt_id,
        sha256=digest,
        original_filename=clean_name,
        mime_type=mime,
        size_bytes=len(data),
        storage_path=path,
    )
    ingestion = Ingestion(
        receipt_id=receipt_id,
        source=source,
        external_id=external_id,
        source_user_id=source_user_id,
        source_chat_id=source_chat_id,
        caption=caption,
        status=IngestionStatus.queued,
    )
    db.add_all([receipt, ingestion])
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return db.scalar(select(Ingestion).where(Ingestion.source == source, Ingestion.external_id == external_id))
    db.refresh(ingestion)
    return ingestion
