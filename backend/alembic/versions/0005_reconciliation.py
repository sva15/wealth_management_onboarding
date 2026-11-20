"""Reconciliation runs, conflict keys and structured evidence requirements.

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("conflicts") as batch:
        batch.add_column(sa.Column("conflict_key", sa.String(200)))
    op.create_index("ix_conflicts_conflict_key", "conflicts", ["conflict_key"])

    with op.batch_alter_table("evidence_requirements") as batch:
        batch.add_column(sa.Column("requirement_key", sa.String(220)))
        batch.add_column(sa.Column("details", sa.JSON))
    op.create_index("ix_evidence_requirements_requirement_key", "evidence_requirements", ["requirement_key"])

    op.create_table(
        "reconciliation_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("case_id", sa.String(36), sa.ForeignKey("onboarding_cases.id"), nullable=False),
        sa.Column("as_of", sa.Date, nullable=False),
        sa.Column("result_hash", sa.String(64), nullable=False),
        sa.Column("result", sa.JSON, nullable=False),
        sa.Column("created_by", sa.String(100), nullable=False),
        sa.Column("calculated_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_reconciliation_runs_case_id", "reconciliation_runs", ["case_id"])


def downgrade() -> None:
    op.drop_table("reconciliation_runs")
    op.drop_index("ix_evidence_requirements_requirement_key", "evidence_requirements")
    with op.batch_alter_table("evidence_requirements") as batch:
        batch.drop_column("details")
        batch.drop_column("requirement_key")
    op.drop_index("ix_conflicts_conflict_key", "conflicts")
    with op.batch_alter_table("conflicts") as batch:
        batch.drop_column("conflict_key")
