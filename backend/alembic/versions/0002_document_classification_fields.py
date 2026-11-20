"""Add classification explanation and page count to documents.

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.add_column(sa.Column("classification_explanation", sa.Text))
        batch.add_column(sa.Column("page_count", sa.Integer))


def downgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.drop_column("page_count")
        batch.drop_column("classification_explanation")
