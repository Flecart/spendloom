"""Baseline for Receipt Ledger v0.1 installations.

This is intentionally a hand-written snapshot: it lets already deployed
``create_all`` databases be stamped before v0.2 alters them.
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def _id() -> sa.Column:
    return sa.Column("id", sa.String(length=36), primary_key=True)


def upgrade() -> None:
    scope = sa.Enum("personal", "business", "unknown", name="expensescope")
    ingestion_status = sa.Enum("queued", "processing", "needs_review", "accepted", "duplicate", "failed", "cancelled", name="ingestionstatus")
    op.create_table("categories", _id(), sa.Column("code", sa.String(32), nullable=False, unique=True), sa.Column("name", sa.String(120), nullable=False), sa.Column("scope", scope, nullable=False), sa.Column("parent_id", sa.String(36), nullable=True), sa.Column("color", sa.String(16), nullable=False), sa.Column("icon", sa.String(32), nullable=False), sa.Column("quickbooks_category", sa.String(180), nullable=True), sa.Column("archived", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_categories_code", "categories", ["code"])
    op.create_index("ix_categories_name", "categories", ["name"])
    op.create_table("payment_methods", _id(), sa.Column("name", sa.String(120), nullable=False, unique=True), sa.Column("method_type", sa.String(40), nullable=False), sa.Column("last_four", sa.String(4), nullable=True), sa.Column("is_default", sa.Boolean(), nullable=False), sa.Column("archived", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("receipts", _id(), sa.Column("sha256", sa.String(64), nullable=False, unique=True), sa.Column("original_filename", sa.String(255), nullable=False), sa.Column("mime_type", sa.String(120), nullable=False), sa.Column("size_bytes", sa.Integer(), nullable=False), sa.Column("storage_path", sa.Text(), nullable=False), sa.Column("preview_path", sa.Text(), nullable=True), sa.Column("page_count", sa.Integer(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_receipts_sha256", "receipts", ["sha256"])
    op.create_table("expenses", _id(), sa.Column("expense_date", sa.Date(), nullable=True), sa.Column("merchant", sa.String(180), nullable=True), sa.Column("merchant_normalized", sa.String(180), nullable=True), sa.Column("original_amount", sa.Numeric(18, 4), nullable=True), sa.Column("original_currency", sa.String(3), nullable=True), sa.Column("amount", sa.Numeric(18, 4), nullable=True), sa.Column("currency", sa.String(3), nullable=False), sa.Column("conversion_rate", sa.Numeric(18, 8), nullable=True), sa.Column("fx_estimated", sa.Boolean(), nullable=False), sa.Column("fx_rate_date", sa.Date(), nullable=True), sa.Column("category_id", sa.String(36), sa.ForeignKey("categories.id"), nullable=True), sa.Column("payment_method_id", sa.String(36), sa.ForeignKey("payment_methods.id"), nullable=True), sa.Column("scope", scope, nullable=False), sa.Column("location", sa.String(180), nullable=True), sa.Column("department", sa.String(180), nullable=True), sa.Column("trip_name", sa.String(180), nullable=True), sa.Column("refundable", sa.Boolean(), nullable=False), sa.Column("memo", sa.Text(), nullable=True), sa.Column("confidence", sa.Numeric(5, 4), nullable=False), sa.Column("status", ingestion_status, nullable=False), sa.Column("quickbooks_category", sa.String(180), nullable=True), sa.Column("quickbooks_class", sa.String(180), nullable=True), sa.Column("quickbooks_customer_job", sa.String(180), nullable=True), sa.Column("quickbooks_location", sa.String(180), nullable=True), sa.Column("quickbooks_subprogram", sa.String(180), nullable=True), sa.Column("quickbooks_vendor", sa.String(180), nullable=True), sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    for name in ("expense_date", "merchant", "merchant_normalized", "category_id", "scope", "status"):
        op.create_index(f"ix_expenses_{name}", "expenses", [name])
    op.create_table("ingestions", _id(), sa.Column("receipt_id", sa.String(36), sa.ForeignKey("receipts.id"), nullable=False), sa.Column("expense_id", sa.String(36), sa.ForeignKey("expenses.id"), nullable=True), sa.Column("source", sa.String(32), nullable=False), sa.Column("external_id", sa.String(180), nullable=False), sa.Column("source_user_id", sa.String(120), nullable=True), sa.Column("source_chat_id", sa.String(120), nullable=True), sa.Column("caption", sa.Text(), nullable=True), sa.Column("status", ingestion_status, nullable=False), sa.Column("attempts", sa.Integer(), nullable=False), sa.Column("error_code", sa.String(80), nullable=True), sa.Column("error_message", sa.Text(), nullable=True), sa.Column("provider", sa.String(40), nullable=True), sa.Column("model", sa.String(120), nullable=True), sa.Column("raw_extraction", sa.JSON(), nullable=True), sa.Column("received_at", sa.DateTime(timezone=True), nullable=False), sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True), sa.Column("notification_sent_at", sa.DateTime(timezone=True), nullable=True), sa.UniqueConstraint("source", "external_id", name="uq_ingestion_source_external"))
    for name in ("receipt_id", "expense_id", "source", "status"):
        op.create_index(f"ix_ingestions_{name}", "ingestions", [name])
    op.create_table("merchant_rules", _id(), sa.Column("merchant_normalized", sa.String(180), nullable=False, unique=True), sa.Column("merchant_display", sa.String(180), nullable=False), sa.Column("category_id", sa.String(36), sa.ForeignKey("categories.id"), nullable=True), sa.Column("payment_method_id", sa.String(36), sa.ForeignKey("payment_methods.id"), nullable=True), sa.Column("scope", scope, nullable=True), sa.Column("enabled", sa.Boolean(), nullable=False), sa.Column("conflict_count", sa.Integer(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_merchant_rules_merchant_normalized", "merchant_rules", ["merchant_normalized"])
    op.create_table("fx_rates", _id(), sa.Column("currency", sa.String(3), nullable=False), sa.Column("rate_date", sa.Date(), nullable=False), sa.Column("eur_per_unit", sa.Numeric(18, 10), nullable=False), sa.Column("source", sa.String(40), nullable=False), sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("currency", "rate_date", name="uq_fx_currency_date"))
    op.create_index("ix_fx_rates_currency", "fx_rates", ["currency"])
    op.create_index("ix_fx_rates_rate_date", "fx_rates", ["rate_date"])
    op.create_table("app_settings", sa.Column("key", sa.String(80), primary_key=True), sa.Column("value", sa.Text(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("audit_events", _id(), sa.Column("entity_type", sa.String(40), nullable=False), sa.Column("entity_id", sa.String(36), nullable=False), sa.Column("action", sa.String(80), nullable=False), sa.Column("details", sa.JSON(), nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_audit_events_entity_type", "audit_events", ["entity_type"])
    op.create_index("ix_audit_events_entity_id", "audit_events", ["entity_id"])


def downgrade() -> None:
    for name in ("audit_events", "app_settings", "fx_rates", "merchant_rules", "ingestions", "expenses", "receipts", "payment_methods", "categories"):
        op.drop_table(name)
