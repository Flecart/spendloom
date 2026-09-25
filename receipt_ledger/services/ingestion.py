from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import (
    AuditEvent,
    Ingestion,
    IngestionDocument,
    IngestionStatus,
    PendingAction,
    Receipt,
    uuid_str,
)
from .storage import InvalidReceiptFile, compress_receipt_image, save_receipt, sha256_bytes, sniff_mime


class DuplicateReceiptDocument(InvalidReceiptFile):
    pass


RECEIPT_GROUPING_AGE = timedelta(minutes=10)
RECEIPT_SETTLE_AGE = timedelta(seconds=3)


def ingestion_documents(db: Session, ingestion_id: str) -> list[IngestionDocument]:
    return list(
        db.scalars(
            select(IngestionDocument)
            .where(IngestionDocument.ingestion_id == ingestion_id)
            .order_by(IngestionDocument.position, IngestionDocument.received_at)
        ).all()
    )


def ensure_ingestion_documents(
    db: Session,
    ingestion: Ingestion,
) -> list[IngestionDocument]:
    """Repair an ingestion written by a pre-multi-document service instance."""
    documents = ingestion_documents(db, ingestion.id)
    if documents:
        return documents
    if not db.get(Receipt, ingestion.receipt_id):
        return []

    db.add(
        IngestionDocument(
            ingestion_id=ingestion.id,
            receipt_id=ingestion.receipt_id,
            position=0,
            source=ingestion.source,
            external_id=ingestion.external_id,
            caption=ingestion.caption,
            received_at=ingestion.received_at,
        )
    )
    db.add(
        AuditEvent(
            entity_type="ingestion",
            entity_id=ingestion.id,
            action="legacy_document_repaired",
            details={"receipt_id": ingestion.receipt_id},
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        documents = ingestion_documents(db, ingestion.id)
        if documents:
            return documents
        raise
    return ingestion_documents(db, ingestion.id)


def canonical_ingestion(db: Session, ingestion: Ingestion) -> Ingestion:
    current = ingestion
    visited = {current.id}
    while current.merged_into_ingestion_id:
        target = db.get(Ingestion, current.merged_into_ingestion_id)
        if not target or target.id in visited:
            break
        visited.add(target.id)
        current = target
    return current


def _existing_document_ingestion(
    db: Session,
    source: str,
    external_id: str,
) -> Ingestion | None:
    document = db.scalar(
        select(IngestionDocument).where(
            IngestionDocument.source == source,
            IngestionDocument.external_id == external_id,
        )
    )
    ingestion = db.get(Ingestion, document.ingestion_id) if document else None
    return canonical_ingestion(db, ingestion) if ingestion else None


def _validate_group_capacity(
    db: Session,
    settings: Settings,
    ingestion_id: str,
    new_size: int,
) -> None:
    documents = ingestion_documents(db, ingestion_id)
    if len(documents) >= settings.max_receipt_documents:
        raise InvalidReceiptFile(
            f"A receipt can contain at most {settings.max_receipt_documents} documents"
        )
    total_size = sum(document.receipt.size_bytes for document in documents) + new_size
    if total_size > settings.max_receipt_total_mb * 1024 * 1024:
        raise InvalidReceiptFile(
            f"Combined receipt documents exceed {settings.max_receipt_total_mb} MB"
        )


def _receipt_for_bytes(
    db: Session,
    settings: Settings,
    *,
    data: bytes,
    filename: str,
    claimed_mime: str | None,
    trusted_mime: str | None = None,
) -> tuple[Receipt, bool]:
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise InvalidReceiptFile(
            f"File exceeds the {settings.max_upload_mb} MB upload limit"
        )
    if trusted_mime not in {None, "text/plain"}:
        raise InvalidReceiptFile("Unsupported trusted document type")
    mime = trusted_mime or sniff_mime(data, claimed_mime, filename)
    digest = sha256_bytes(data)
    existing = db.scalar(select(Receipt).where(Receipt.sha256 == digest))
    if existing:
        return existing, False

    receipt_id = uuid_str()
    stored_data, stored_mime = compress_receipt_image(data, mime)
    stored_filename = filename if stored_mime == mime else f"{Path(filename).stem[:170]}.webp"
    path, clean_name = save_receipt(settings, receipt_id, stored_filename, stored_data)
    receipt = Receipt(
        id=receipt_id,
        sha256=digest,
        original_filename=clean_name,
        mime_type=stored_mime,
        size_bytes=len(stored_data),
        storage_path=path,
    )
    db.add(receipt)
    return receipt, True


def append_ingestion_document(
    db: Session,
    settings: Settings,
    *,
    ingestion: Ingestion,
    data: bytes,
    filename: str,
    claimed_mime: str | None,
    source: str,
    external_id: str,
    caption: str | None = None,
    trusted_mime: str | None = None,
) -> tuple[Ingestion, bool]:
    existing_ingestion = _existing_document_ingestion(db, source, external_id)
    if existing_ingestion:
        return existing_ingestion, False

    target = canonical_ingestion(db, ingestion)
    _validate_group_capacity(db, settings, target.id, len(data))
    receipt, created = _receipt_for_bytes(
        db,
        settings,
        data=data,
        filename=filename,
        claimed_mime=claimed_mime,
        trusted_mime=trusted_mime,
    )
    already_attached = db.scalar(
        select(IngestionDocument).where(
            IngestionDocument.ingestion_id == target.id,
            IngestionDocument.receipt_id == receipt.id,
        )
    )
    if already_attached:
        if created:
            db.delete(receipt)
        return target, False
    if not created:
        raise DuplicateReceiptDocument("That exact document is already saved")

    next_position = db.scalar(
        select(func.max(IngestionDocument.position)).where(
            IngestionDocument.ingestion_id == target.id
        )
    )
    document = IngestionDocument(
        ingestion_id=target.id,
        receipt_id=receipt.id,
        position=(next_position if next_position is not None else -1) + 1,
        source=source,
        external_id=external_id,
        caption=caption,
    )
    db.add(document)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing_ingestion = _existing_document_ingestion(db, source, external_id)
        if existing_ingestion:
            return existing_ingestion, False
        if created:
            Path(receipt.storage_path).unlink(missing_ok=True)
        raise
    db.refresh(target)
    return target, True


def schedule_ingestion(
    db: Session,
    ingestion: Ingestion,
    *,
    ready_at: datetime,
) -> Ingestion:
    target = canonical_ingestion(db, ingestion)
    if target.status == IngestionStatus.processing:
        target.reprocess_requested = True
    else:
        target.status = IngestionStatus.queued
        target.ready_at = ready_at
        target.processed_at = None
    target.notification_sent_at = None
    db.commit()
    db.refresh(target)
    return target


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
    group_external_id: str | None = None,
    ready_at: datetime | None = None,
    trusted_mime: str | None = None,
) -> Ingestion:
    existing_document_ingestion = _existing_document_ingestion(db, source, external_id)
    if existing_document_ingestion:
        return existing_document_ingestion
    logical_external_id = group_external_id or external_id
    existing_group = db.scalar(
        select(Ingestion).where(
            Ingestion.source == source,
            Ingestion.external_id == logical_external_id,
        )
    )
    if existing_group:
        ingestion, added = append_ingestion_document(
            db,
            settings,
            ingestion=existing_group,
            data=data,
            filename=filename,
            claimed_mime=claimed_mime,
            source=source,
            external_id=external_id,
            caption=caption,
            trusted_mime=trusted_mime,
        )
        if added:
            schedule_ingestion(
                db,
                ingestion,
                ready_at=ready_at or datetime.now(timezone.utc),
            )
        return ingestion

    receipt, created = _receipt_for_bytes(
        db,
        settings,
        data=data,
        filename=filename,
        claimed_mime=claimed_mime,
        trusted_mime=trusted_mime,
    )
    if not created:
        prior = db.scalar(
            select(Ingestion)
            .join(IngestionDocument, IngestionDocument.ingestion_id == Ingestion.id)
            .where(
                IngestionDocument.receipt_id == receipt.id,
                Ingestion.expense_id.is_not(None),
            )
            .order_by(Ingestion.received_at.desc())
        )
        duplicate = Ingestion(
            id=uuid_str(),
            receipt_id=receipt.id,
            expense_id=prior.expense_id if prior else None,
            source=source,
            external_id=logical_external_id,
            source_user_id=source_user_id,
            source_chat_id=source_chat_id,
            caption=caption,
            status=IngestionStatus.duplicate,
            processed_at=datetime.now(timezone.utc),
            ready_at=ready_at,
        )
        document = IngestionDocument(
            ingestion_id=duplicate.id,
            receipt_id=receipt.id,
            position=0,
            source=source,
            external_id=external_id,
            caption=caption,
        )
        db.add_all([duplicate, document])
        db.commit()
        db.refresh(duplicate)
        return duplicate

    ingestion = Ingestion(
        id=uuid_str(),
        receipt_id=receipt.id,
        source=source,
        external_id=logical_external_id,
        source_user_id=source_user_id,
        source_chat_id=source_chat_id,
        caption=caption,
        status=IngestionStatus.queued,
        ready_at=ready_at,
    )
    document = IngestionDocument(
        ingestion_id=ingestion.id,
        receipt_id=receipt.id,
        position=0,
        source=source,
        external_id=external_id,
        caption=caption,
    )
    db.add_all([ingestion, document])
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if created:
            Path(receipt.storage_path).unlink(missing_ok=True)
        existing = _existing_document_ingestion(db, source, external_id)
        if existing:
            return existing
        raise
    db.refresh(ingestion)
    return ingestion


def merge_ingestions(
    db: Session,
    settings: Settings,
    *,
    source_ingestion: Ingestion,
    target_ingestion: Ingestion,
    ready_at: datetime,
) -> Ingestion:
    source = canonical_ingestion(db, source_ingestion)
    target = canonical_ingestion(db, target_ingestion)
    if source.id == target.id:
        return target
    source_documents = ingestion_documents(db, source.id)
    target_documents = ingestion_documents(db, target.id)
    target_receipt_ids = {document.receipt_id for document in target_documents}
    combined_size = sum(document.receipt.size_bytes for document in target_documents)
    combined_size += sum(
        document.receipt.size_bytes
        for document in source_documents
        if document.receipt_id not in target_receipt_ids
    )
    combined_count = len(target_receipt_ids | {item.receipt_id for item in source_documents})
    if combined_count > settings.max_receipt_documents:
        raise InvalidReceiptFile(
            f"A receipt can contain at most {settings.max_receipt_documents} documents"
        )
    if combined_size > settings.max_receipt_total_mb * 1024 * 1024:
        raise InvalidReceiptFile(
            f"Combined receipt documents exceed {settings.max_receipt_total_mb} MB"
        )

    position = max((document.position for document in target_documents), default=-1) + 1
    for document in source_documents:
        if document.receipt_id in target_receipt_ids:
            db.delete(document)
            continue
        document.ingestion_id = target.id
        document.position = position
        target_receipt_ids.add(document.receipt_id)
        position += 1
    source.status = IngestionStatus.cancelled
    source.merged_into_ingestion_id = target.id
    source.processed_at = datetime.now(timezone.utc)
    if target.status == IngestionStatus.processing:
        target.reprocess_requested = True
    else:
        target.status = IngestionStatus.queued
        target.ready_at = ready_at
        target.processed_at = None
    target.notification_sent_at = None
    db.add(
        AuditEvent(
            entity_type="ingestion",
            entity_id=target.id,
            action="documents_merged",
            details={"source_ingestion_id": source.id, "document_count": combined_count},
        )
    )
    db.commit()
    db.refresh(target)
    return target


def create_receipt_grouping_choice(
    db: Session,
    *,
    source_ingestion: Ingestion,
    target_ingestion: Ingestion,
    chat_id: str | int,
    user_id: str | int,
) -> PendingAction:
    existing = db.scalar(
        select(PendingAction).where(
            PendingAction.action_type == "group_receipt_upload",
            PendingAction.telegram_chat_id == str(chat_id),
            PendingAction.used_at.is_(None),
        ).order_by(PendingAction.created_at.desc())
    )
    if existing and existing.payload.get("source_ingestion_id") == source_ingestion.id:
        return existing
    action = PendingAction(
        token=uuid_str().replace("-", ""),
        telegram_chat_id=str(chat_id),
        telegram_user_id=str(user_id),
        action_type="group_receipt_upload",
        payload={
            "source_ingestion_id": source_ingestion.id,
            "target_ingestion_id": target_ingestion.id,
        },
        expires_at=datetime.now(timezone.utc) + RECEIPT_GROUPING_AGE,
    )
    source_ingestion.ready_at = action.expires_at
    db.add(action)
    db.commit()
    db.refresh(action)
    return action


def resolve_receipt_grouping_choice(
    db: Session,
    settings: Settings,
    *,
    token: str,
    chat_id: str | int,
    user_id: str | int,
    add_to_current: bool,
) -> tuple[Ingestion | None, bool, str]:
    action = db.scalar(
        select(PendingAction).where(
            PendingAction.token == token,
            PendingAction.action_type == "group_receipt_upload",
        )
    )
    if (
        not action
        or action.telegram_chat_id != str(chat_id)
        or action.telegram_user_id != str(user_id)
    ):
        return None, False, "That receipt choice is not available."
    expires_at = action.expires_at
    if not expires_at.tzinfo:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if action.used_at or expires_at < datetime.now(timezone.utc):
        return None, False, "That receipt choice has expired; the document remains saved separately."

    source = db.get(Ingestion, action.payload.get("source_ingestion_id"))
    target = db.get(Ingestion, action.payload.get("target_ingestion_id"))
    if target:
        target = canonical_ingestion(db, target)
    action.used_at = datetime.now(timezone.utc)
    if not source:
        db.commit()
        return None, False, "That uploaded receipt is no longer available."

    if add_to_current and target and target.status != IngestionStatus.cancelled:
        merged = merge_ingestions(
            db,
            settings,
            source_ingestion=source,
            target_ingestion=target,
            ready_at=datetime.now(timezone.utc) + RECEIPT_SETTLE_AGE,
        )
        count = len(ingestion_documents(db, merged.id))
        return merged, False, f"Added to the current receipt. It now has {count} documents."

    source.status = IngestionStatus.queued
    source.ready_at = datetime.now(timezone.utc) + RECEIPT_SETTLE_AGE
    source.processed_at = None
    db.commit()
    if add_to_current:
        return source, True, "The previous receipt was no longer available, so this was saved as a new receipt."
    return source, True, "Started a new receipt with this upload."
