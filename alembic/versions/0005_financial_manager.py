"""Add recurring finance, income, receivables, documents, and Gmail state."""

from alembic import op
import sqlalchemy as sa


revision = "0005_financial_manager"
down_revision = "0004_repair_missing_documents"
branch_labels = None
depends_on = None


def timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "contracts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("counterparty", sa.String(180), nullable=False),
        sa.Column("reference", sa.String(120), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
    )
    for name in ("title", "counterparty", "reference", "status"):
        op.create_index(f"ix_contracts_{name}", "contracts", [name])

    op.create_table(
        "income_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("received_date", sa.Date(), nullable=False),
        sa.Column("payer", sa.String(180), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("original_amount", sa.Numeric(18, 4), nullable=False),
        sa.Column("original_currency", sa.String(3), nullable=False),
        sa.Column("amount", sa.Numeric(18, 4), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("conversion_rate", sa.Numeric(18, 8), nullable=True),
        sa.Column("fx_estimated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("fx_rate_date", sa.Date(), nullable=True),
        sa.Column("contract_id", sa.String(36), sa.ForeignKey("contracts.id"), nullable=True),
        sa.Column("memo", sa.Text(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
    )
    for name in ("received_date", "payer", "kind", "contract_id"):
        op.create_index(f"ix_income_entries_{name}", "income_entries", [name])

    op.create_table(
        "invoices",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("reference", sa.String(120), nullable=False, unique=True),
        sa.Column("client", sa.String(180), nullable=False),
        sa.Column("contract_id", sa.String(36), sa.ForeignKey("contracts.id"), nullable=True),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("subtotal", sa.Numeric(18, 4), nullable=False),
        sa.Column("tax_amount", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("total", sa.Numeric(18, 4), nullable=False),
        sa.Column("memo", sa.Text(), nullable=True),
        sa.Column("voided", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
    )
    for name in ("reference", "client", "contract_id", "issue_date", "due_date", "voided"):
        op.create_index(f"ix_invoices_{name}", "invoices", [name])

    op.create_table(
        "invoice_allocations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("invoice_id", sa.String(36), sa.ForeignKey("invoices.id"), nullable=False),
        sa.Column("income_id", sa.String(36), sa.ForeignKey("income_entries.id"), nullable=False),
        sa.Column("amount", sa.Numeric(18, 4), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("invoice_id", "income_id", name="uq_invoice_allocation_pair"),
    )
    op.create_index("ix_invoice_allocations_invoice_id", "invoice_allocations", ["invoice_id"])
    op.create_index("ix_invoice_allocations_income_id", "invoice_allocations", ["income_id"])

    op.create_table(
        "recurring_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("entry_type", sa.String(24), nullable=False),
        sa.Column("counterparty", sa.String(180), nullable=False),
        sa.Column("expected_amount", sa.Numeric(18, 4), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("frequency", sa.String(24), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("reminder_days_before", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("category_id", sa.String(36), sa.ForeignKey("categories.id"), nullable=True),
        sa.Column("payment_method_id", sa.String(36), sa.ForeignKey("payment_methods.id"), nullable=True),
        sa.Column("scope", sa.String(24), nullable=False),
        sa.Column("income_kind", sa.String(24), nullable=True),
        sa.Column("contract_id", sa.String(36), sa.ForeignKey("contracts.id"), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *timestamps(),
    )
    for name in ("name", "entry_type", "start_date", "active"):
        op.create_index(f"ix_recurring_items_{name}", "recurring_items", [name])

    op.create_table(
        "recurring_occurrences",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("recurring_item_id", sa.String(36), sa.ForeignKey("recurring_items.id"), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("expected_amount", sa.Numeric(18, 4), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("actual_expense_id", sa.String(36), sa.ForeignKey("expenses.id"), nullable=True),
        sa.Column("actual_income_id", sa.String(36), sa.ForeignKey("income_entries.id"), nullable=True),
        sa.Column("lead_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_overdue_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("snoozed_until", sa.Date(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("recurring_item_id", "due_date", name="uq_recurring_occurrence_due"),
    )
    for name in ("recurring_item_id", "due_date", "status", "actual_expense_id", "actual_income_id"):
        op.create_index(f"ix_recurring_occurrences_{name}", "recurring_occurrences", [name])

    op.create_table(
        "supporting_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(120), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_supporting_documents_sha256", "supporting_documents", ["sha256"])

    op.create_table(
        "document_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("supporting_documents.id"), nullable=False),
        sa.Column("expense_id", sa.String(36), sa.ForeignKey("expenses.id"), nullable=True),
        sa.Column("income_id", sa.String(36), sa.ForeignKey("income_entries.id"), nullable=True),
        sa.Column("contract_id", sa.String(36), sa.ForeignKey("contracts.id"), nullable=True),
        sa.Column("invoice_id", sa.String(36), sa.ForeignKey("invoices.id"), nullable=True),
        sa.Column("recurring_occurrence_id", sa.String(36), sa.ForeignKey("recurring_occurrences.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(expense_id IS NOT NULL) + (income_id IS NOT NULL) + "
            "(contract_id IS NOT NULL) + (invoice_id IS NOT NULL) + "
            "(recurring_occurrence_id IS NOT NULL) = 1",
            name="ck_document_link_one_target",
        ),
        sa.UniqueConstraint(
            "document_id", "expense_id", "income_id", "contract_id", "invoice_id", "recurring_occurrence_id",
            name="uq_document_link_target",
        ),
    )
    for name in ("document_id", "expense_id", "income_id", "contract_id", "invoice_id", "recurring_occurrence_id"):
        op.create_index(f"ix_document_links_{name}", "document_links", [name])

    op.create_table(
        "gmail_connections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email_address", sa.String(320), nullable=False, unique=True),
        sa.Column("encrypted_refresh_token", sa.Text(), nullable=False),
        sa.Column("history_id", sa.String(80), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        *timestamps(),
    )
    for name in ("status", "next_sync_at"):
        op.create_index(f"ix_gmail_connections_{name}", "gmail_connections", [name])

    op.create_table(
        "gmail_sender_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("connection_id", sa.String(36), sa.ForeignKey("gmail_connections.id"), nullable=False),
        sa.Column("sender_address", sa.String(320), nullable=False),
        sa.Column("recurring_item_id", sa.String(36), sa.ForeignKey("recurring_items.id"), nullable=True),
        sa.Column("category_id", sa.String(36), sa.ForeignKey("categories.id"), nullable=True),
        sa.Column("scope", sa.String(24), nullable=True),
        sa.Column("match_window_days", sa.Integer(), nullable=False, server_default="45"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("connection_id", "sender_address", name="uq_gmail_sender_rule_address"),
    )
    for name in ("connection_id", "sender_address", "enabled"):
        op.create_index(f"ix_gmail_sender_rules_{name}", "gmail_sender_rules", [name])

    op.create_table(
        "gmail_message_imports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("connection_id", sa.String(36), sa.ForeignKey("gmail_connections.id"), nullable=False),
        sa.Column("sender_rule_id", sa.String(36), sa.ForeignKey("gmail_sender_rules.id"), nullable=False),
        sa.Column("gmail_message_id", sa.String(180), nullable=False),
        sa.Column("gmail_thread_id", sa.String(180), nullable=True),
        sa.Column("subject", sa.String(500), nullable=False),
        sa.Column("sender_address", sa.String(320), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("ingestion_id", sa.String(36), sa.ForeignKey("ingestions.id"), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("connection_id", "gmail_message_id", name="uq_gmail_message_import"),
    )
    for name in ("connection_id", "sender_rule_id", "gmail_message_id", "status"):
        op.create_index(f"ix_gmail_message_imports_{name}", "gmail_message_imports", [name])

    with op.batch_alter_table("ingestions") as batch:
        batch.add_column(sa.Column("recurring_occurrence_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("gmail_message_import_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_ingestions_recurring_occurrence",
            "recurring_occurrences",
            ["recurring_occurrence_id"],
            ["id"],
        )
        batch.create_foreign_key(
            "fk_ingestions_gmail_message_import",
            "gmail_message_imports",
            ["gmail_message_import_id"],
            ["id"],
        )
        batch.create_index("ix_ingestions_recurring_occurrence_id", ["recurring_occurrence_id"])
        batch.create_index("ix_ingestions_gmail_message_import_id", ["gmail_message_import_id"])

    with op.batch_alter_table("conversation_sessions") as batch:
        batch.add_column(sa.Column("active_occurrence_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("attachment_target_type", sa.String(32), nullable=True))
        batch.add_column(sa.Column("attachment_target_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_conversation_sessions_active_occurrence",
            "recurring_occurrences",
            ["active_occurrence_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("conversation_sessions") as batch:
        batch.drop_constraint("fk_conversation_sessions_active_occurrence", type_="foreignkey")
        batch.drop_column("attachment_target_id")
        batch.drop_column("attachment_target_type")
        batch.drop_column("active_occurrence_id")
    with op.batch_alter_table("ingestions") as batch:
        batch.drop_index("ix_ingestions_gmail_message_import_id")
        batch.drop_index("ix_ingestions_recurring_occurrence_id")
        batch.drop_constraint("fk_ingestions_gmail_message_import", type_="foreignkey")
        batch.drop_constraint("fk_ingestions_recurring_occurrence", type_="foreignkey")
        batch.drop_column("gmail_message_import_id")
        batch.drop_column("recurring_occurrence_id")
    for table in (
        "gmail_message_imports",
        "gmail_sender_rules",
        "gmail_connections",
        "document_links",
        "supporting_documents",
        "recurring_occurrences",
        "recurring_items",
        "invoice_allocations",
        "invoices",
        "income_entries",
        "contracts",
    ):
        op.drop_table(table)
