"""Add extraction diagnostics.

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "extraction_diagnostics",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("case_id", sa.String(36), sa.ForeignKey("onboarding_cases.id"), nullable=False),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("task", sa.String(60), nullable=False),
        sa.Column("prompt_version", sa.String(50), nullable=False),
        sa.Column("model_id", sa.String(200), nullable=False),
        sa.Column("stage", sa.String(20), nullable=False),
        sa.Column("error_type", sa.String(60), nullable=False),
        sa.Column("error_summary", sa.Text, nullable=False),
        sa.Column("raw_response", sa.Text),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_extraction_diagnostics_case_id", "extraction_diagnostics", ["case_id"])
    op.create_index("ix_extraction_diagnostics_document_id", "extraction_diagnostics", ["document_id"])


def downgrade() -> None:
    op.drop_table("extraction_diagnostics")
