"""Represent one logical receipt with multiple source documents."""

from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa


revision = "0003_multi_document_receipts"
down_revision = "0002_spendloom_chat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ingestions") as batch:
        batch.add_column(sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(
            sa.Column(
                "reprocess_requested",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(
            sa.Column("merged_into_ingestion_id", sa.String(length=36), nullable=True)
        )
        batch.create_foreign_key(
            "fk_ingestions_merged_into",
            "ingestions",
            ["merged_into_ingestion_id"],
            ["id"],
        )
        batch.create_index("ix_ingestions_ready_at", ["ready_at"])
        batch.create_index(
            "ix_ingestions_merged_into_ingestion_id",
            ["merged_into_ingestion_id"],
        )

    op.create_table(
        "ingestion_documents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "ingestion_id",
            sa.String(length=36),
            sa.ForeignKey("ingestions.id"),
            nullable=False,
        ),
        sa.Column(
            "receipt_id",
            sa.String(length=36),
            sa.ForeignKey("receipts.id"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=180), nullable=False),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "source",
            "external_id",
            name="uq_ingestion_document_source_external",
        ),
        sa.UniqueConstraint(
            "ingestion_id",
            "receipt_id",
            name="uq_ingestion_document_receipt",
        ),
    )
    op.create_index(
        "ix_ingestion_documents_ingestion_id",
        "ingestion_documents",
        ["ingestion_id"],
    )
    op.create_index(
        "ix_ingestion_documents_receipt_id",
        "ingestion_documents",
        ["receipt_id"],
    )
    op.create_index(
        "ix_ingestion_documents_source",
        "ingestion_documents",
        ["source"],
    )
    op.create_index(
        "ix_ingestion_documents_ingestion_position",
        "ingestion_documents",
        ["ingestion_id", "position"],
    )

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
    rows = connection.execute(
        sa.select(
            ingestions.c.id,
            ingestions.c.receipt_id,
            ingestions.c.source,
            ingestions.c.external_id,
            ingestions.c.caption,
            ingestions.c.received_at,
        )
    ).all()
    if rows:
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
                for row in rows
            ],
        )


def downgrade() -> None:
    op.drop_table("ingestion_documents")
    with op.batch_alter_table("ingestions") as batch:
        batch.drop_index("ix_ingestions_merged_into_ingestion_id")
        batch.drop_index("ix_ingestions_ready_at")
        batch.drop_constraint("fk_ingestions_merged_into", type_="foreignkey")
        batch.drop_column("merged_into_ingestion_id")
        batch.drop_column("reprocess_requested")
        batch.drop_column("ready_at")
