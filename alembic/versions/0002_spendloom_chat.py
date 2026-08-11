"""Add Spendloom conversational state and categorisation provenance."""
from alembic import op
import sqlalchemy as sa

revision = "0002_spendloom_chat"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("expenses") as batch:
        batch.add_column(sa.Column("categorization_source", sa.String(32), nullable=False, server_default="ai"))
        batch.add_column(sa.Column("category_reason", sa.Text(), nullable=True))
    op.create_table("conversation_sessions", sa.Column("id", sa.String(36), primary_key=True), sa.Column("telegram_chat_id", sa.String(120), nullable=False), sa.Column("telegram_user_id", sa.String(120), nullable=False), sa.Column("active_ingestion_id", sa.String(36), sa.ForeignKey("ingestions.id"), nullable=True), sa.Column("active_expense_id", sa.String(36), sa.ForeignKey("expenses.id"), nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("telegram_chat_id", name="uq_conversation_session_chat"))
    op.create_index("ix_conversation_sessions_telegram_chat_id", "conversation_sessions", ["telegram_chat_id"])
    op.create_index("ix_conversation_sessions_telegram_user_id", "conversation_sessions", ["telegram_user_id"])
    op.create_table("conversation_messages", sa.Column("id", sa.String(36), primary_key=True), sa.Column("session_id", sa.String(36), sa.ForeignKey("conversation_sessions.id"), nullable=False), sa.Column("role", sa.String(16), nullable=False), sa.Column("content", sa.Text(), nullable=False), sa.Column("approximate_tokens", sa.Integer(), nullable=False), sa.Column("telegram_message_id", sa.String(120), nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_conversation_messages_session_id", "conversation_messages", ["session_id"])
    op.create_index("ix_conversation_messages_session_created", "conversation_messages", ["session_id", "created_at"])
    op.create_table("chat_jobs", sa.Column("id", sa.String(36), primary_key=True), sa.Column("session_id", sa.String(36), sa.ForeignKey("conversation_sessions.id"), nullable=False), sa.Column("telegram_chat_id", sa.String(120), nullable=False), sa.Column("telegram_user_id", sa.String(120), nullable=False), sa.Column("telegram_message_id", sa.String(120), nullable=False), sa.Column("text", sa.Text(), nullable=False), sa.Column("status", sa.String(24), nullable=False), sa.Column("attempts", sa.Integer(), nullable=False), sa.Column("response_text", sa.Text(), nullable=True), sa.Column("pending_action_token", sa.String(64), nullable=True), sa.Column("export_request", sa.JSON(), nullable=True), sa.Column("error_message", sa.Text(), nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True), sa.Column("response_sent_at", sa.DateTime(timezone=True), nullable=True), sa.UniqueConstraint("telegram_chat_id", "telegram_message_id", name="uq_chat_job_telegram_message"))
    op.create_index("ix_chat_jobs_session_id", "chat_jobs", ["session_id"])
    op.create_index("ix_chat_jobs_telegram_chat_id", "chat_jobs", ["telegram_chat_id"])
    op.create_index("ix_chat_jobs_status", "chat_jobs", ["status"])
    op.create_index("ix_chat_jobs_status_created", "chat_jobs", ["status", "created_at"])
    op.create_table("pending_actions", sa.Column("id", sa.String(36), primary_key=True), sa.Column("token", sa.String(64), nullable=False, unique=True), sa.Column("telegram_chat_id", sa.String(120), nullable=False), sa.Column("telegram_user_id", sa.String(120), nullable=False), sa.Column("action_type", sa.String(80), nullable=False), sa.Column("payload", sa.JSON(), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False), sa.Column("used_at", sa.DateTime(timezone=True), nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    for name in ("token", "telegram_chat_id", "telegram_user_id", "expires_at"):
        op.create_index(f"ix_pending_actions_{name}", "pending_actions", [name])


def downgrade() -> None:
    op.drop_table("pending_actions")
    op.drop_table("chat_jobs")
    op.drop_table("conversation_messages")
    op.drop_table("conversation_sessions")
    with op.batch_alter_table("expenses") as batch:
        batch.drop_column("category_reason")
        batch.drop_column("categorization_source")
