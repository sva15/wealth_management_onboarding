"""Evidence link method and entity matches.

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("evidences") as batch:
        batch.add_column(sa.Column("link_method", sa.String(20), nullable=False, server_default="RULE"))

    op.create_table(
        "entity_matches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("case_id", sa.String(36), sa.ForeignKey("onboarding_cases.id"), nullable=False),
        sa.Column("match_key", sa.String(160), nullable=False),
        sa.Column("entity_kind", sa.String(30), nullable=False),
        sa.Column("left_ref", sa.String(64), nullable=False),
        sa.Column("right_ref", sa.String(64), nullable=False),
        sa.Column("left_label", sa.String(300), nullable=False),
        sa.Column("right_label", sa.String(300), nullable=False),
        sa.Column("score", sa.Float, nullable=False),
        sa.Column("method", sa.String(40), nullable=False),
        sa.Column("explanation", sa.Text, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("decided_by", sa.String(100)),
        sa.Column("decision_reason", sa.Text),
        sa.Column("decided_at", sa.DateTime),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("case_id", "match_key", name="uq_entity_match_key"),
    )
    op.create_index("ix_entity_matches_case_id", "entity_matches", ["case_id"])


def downgrade() -> None:
    op.drop_table("entity_matches")
    with op.batch_alter_table("evidences") as batch:
        batch.drop_column("link_method")
