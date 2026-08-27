"""Repair ingestions written by older service containers after migration."""

from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa


revision = "0004_repair_missing_documents"
down_revision = "0003_multi_document_receipts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    ingestions = sa.table(
        "ingestions",
        sa.column("id", sa.String),
        sa.column("receipt_id", sa.String),
        sa.column("source", sa.String),
        sa.column("external_id", sa.String),
        sa.column("caption", sa.Text),
        sa.column("received_at", sa.DateTime(timezone=True)),
    )
    documents = sa.table(
        "ingestion_documents",
        sa.column("id", sa.String),
        sa.column("ingestion_id", sa.String),
        sa.column("receipt_id", sa.String),
        sa.column("position", sa.Integer),
        sa.column("source", sa.String),
        sa.column("external_id", sa.String),
        sa.column("caption", sa.Text),
        sa.column("received_at", sa.DateTime(timezone=True)),
    )
    linked_ingestions = sa.select(documents.c.ingestion_id)
    missing_rows = connection.execute(
        sa.select(
            ingestions.c.id,
            ingestions.c.receipt_id,
            ingestions.c.source,
            ingestions.c.external_id,
            ingestions.c.caption,
            ingestions.c.received_at,
        ).where(ingestions.c.id.not_in(linked_ingestions))
    ).all()
    if missing_rows:
        connection.execute(
            documents.insert(),
            [
                {
                    "id": str(uuid.uuid4()),
                    "ingestion_id": row.id,
                    "receipt_id": row.receipt_id,
                    "position": 0,
                    "source": row.source,
                    "external_id": row.external_id,
                    "caption": row.caption,
                    "received_at": row.received_at,
                }
                for row in missing_rows
            ],
        )

    connection.execute(
        sa.text(
            "UPDATE ingestions "
            "SET status = 'queued', attempts = 0, error_code = NULL, "
            "error_message = NULL, processed_at = NULL, ready_at = NULL "
            "WHERE error_code = 'invalid_document' "
            "AND error_message = 'Receipt has no stored documents'"
        )
    )


def downgrade() -> None:
    pass
