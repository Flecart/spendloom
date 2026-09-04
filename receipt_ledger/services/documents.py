from __future__ import annotations

import os
import tempfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..config import Settings
from ..models import (
    Contract,
    DocumentLink,
    Expense,
    IncomeEntry,
    Invoice,
    RecurringOccurrence,
    SupportingDocument,
    uuid_str,
)
from ..schemas import SupportingDocumentOut
from .storage import InvalidReceiptFile, safe_filename, sha256_bytes, sniff_mime


TARGET_MODELS = {
    "expense": Expense,
    "income": IncomeEntry,
    "contract": Contract,
    "invoice": Invoice,
    "occurrence": RecurringOccurrence,
}

TARGET_COLUMNS = {
    "expense": "expense_id",
    "income": "income_id",
    "contract": "contract_id",
    "invoice": "invoice_id",
    "occurrence": "recurring_occurrence_id",
}


def _validate_target(db: Session, target_type: str, target_id: str) -> None:
    model = TARGET_MODELS.get(target_type)
    if model is None:
        raise ValueError("Unsupported document target")
    target = db.get(model, target_id)
    if target is None or getattr(target, "deleted_at", None) is not None:
        raise ValueError(f"{target_type.capitalize()} not found")


def attach_document(
    db: Session,
    settings: Settings,
    *,
    data: bytes,
    filename: str,
    claimed_mime: str | None,
    target_type: str,
    target_id: str,
) -> SupportingDocument:
    _validate_target(db, target_type, target_id)
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise InvalidReceiptFile(f"File exceeds the {settings.max_upload_mb} MB upload limit")
    mime_type = sniff_mime(data, claimed_mime, filename)
    digest = sha256_bytes(data)
    document = db.scalar(
        select(SupportingDocument).where(SupportingDocument.sha256 == digest)
    )
    created_path: Path | None = None
    if document is None:
        document_id = uuid_str()
        folder = settings.documents_dir / document_id
        folder.mkdir(parents=True, exist_ok=True)
        clean_name = safe_filename(filename)
        destination = folder / clean_name
        descriptor, temporary = tempfile.mkstemp(prefix=".upload-", dir=folder)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        created_path = destination
        document = SupportingDocument(
            id=document_id,
            sha256=digest,
            original_filename=clean_name,
            mime_type=mime_type,
            size_bytes=len(data),
            storage_path=str(destination.resolve()),
        )
        db.add(document)
        db.flush()

    target_column = TARGET_COLUMNS[target_type]
    existing = db.scalar(
        select(DocumentLink).where(
            DocumentLink.document_id == document.id,
            getattr(DocumentLink, target_column) == target_id,
        )
    )
    if existing is None:
        db.add(
            DocumentLink(
                document_id=document.id,
                **{target_column: target_id},
            )
        )
    try:
        db.commit()
    except Exception:
        db.rollback()
        if created_path:
            created_path.unlink(missing_ok=True)
            created_path.parent.rmdir()
        raise
    db.refresh(document)
    return document


def documents_for(db: Session, target_type: str, target_id: str) -> list[SupportingDocumentOut]:
    target_column = TARGET_COLUMNS.get(target_type)
    if target_column is None:
        raise ValueError("Unsupported document target")
    links = db.scalars(
        select(DocumentLink)
        .options(joinedload(DocumentLink.document))
        .where(getattr(DocumentLink, target_column) == target_id)
        .order_by(DocumentLink.created_at)
    ).all()
    return [document_out(link.document) for link in links]


def document_out(document: SupportingDocument) -> SupportingDocumentOut:
    return SupportingDocumentOut(
        id=document.id,
        filename=document.original_filename,
        mime_type=document.mime_type,
        size_bytes=document.size_bytes,
        file_url=f"/api/documents/{document.id}/file",
    )


def move_occurrence_documents(
    db: Session,
    occurrence_id: str,
    target_type: str,
    target_id: str,
) -> None:
    target_column = TARGET_COLUMNS[target_type]
    links = db.scalars(
        select(DocumentLink).where(
            DocumentLink.recurring_occurrence_id == occurrence_id
        )
    ).all()
    for link in links:
        link.recurring_occurrence_id = None
        setattr(link, target_column, target_id)
