"""Initial schema.

Revision ID: 0001
Revises:
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_ID = sa.String(36)


def _pk() -> sa.Column:
    return sa.Column("id", _ID, primary_key=True)


def _created(name: str = "created_at") -> sa.Column:
    return sa.Column(name, sa.DateTime, nullable=False)


def _fk(name: str, target: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, _ID, sa.ForeignKey(target), nullable=nullable)


def _index(table: str, column: str) -> None:
    op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    op.create_table(
        "customers",
        _pk(),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("pan", sa.String(10)),
        sa.Column("date_of_birth", sa.Date),
        sa.Column("email", sa.String(254)),
        _created(),
    )
    op.create_table(
        "onboarding_cases",
        _pk(),
        _fk("customer_id", "customers.id"),
        sa.Column("status", sa.String(40), nullable=False),
        _created(),
        _created("updated_at"),
    )
    _index("onboarding_cases", "customer_id")
    _index("onboarding_cases", "status")

    op.create_table(
        "declarations",
        _pk(),
        _fk("case_id", "onboarding_cases.id"),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("created_by", sa.String(100), nullable=False),
        _created(),
    )
    _index("declarations", "case_id")

    op.create_table(
        "customer_claims",
        _pk(),
        _fk("customer_id", "customers.id"),
        _fk("case_id", "onboarding_cases.id"),
        _fk("declaration_id", "declarations.id"),
        sa.Column("claim_type", sa.String(40), nullable=False),
        sa.Column("declared_amount", sa.String(40)),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("effective_date", sa.Date, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("materiality", sa.String(20), nullable=False),
        sa.Column("verification_status", sa.String(30), nullable=False),
        _created(),
        _created("updated_at"),
    )
    for col in ("customer_id", "case_id", "declaration_id"):
        _index("customer_claims", col)

    op.create_table(
        "documents",
        _pk(),
        _fk("case_id", "onboarding_cases.id"),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("media_type", sa.String(100), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("document_type", sa.String(40)),
        sa.Column("classification_confidence", sa.Float),
        sa.Column("processing_status", sa.String(30), nullable=False),
        sa.Column("error_message", sa.Text),
        _created("uploaded_at"),
        sa.UniqueConstraint("case_id", "sha256", name="uq_documents_case_sha256"),
    )
    _index("documents", "case_id")

    op.create_table(
        "document_pages",
        _pk(),
        _fk("document_id", "documents.id"),
        sa.Column("page_number", sa.Integer, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        _created(),
        sa.UniqueConstraint("document_id", "page_number", name="uq_pages_doc_page"),
    )
    _index("document_pages", "document_id")

    op.create_table(
        "extracted_facts",
        _pk(),
        _fk("case_id", "onboarding_cases.id"),
        _fk("document_id", "documents.id"),
        sa.Column("page_number", sa.Integer, nullable=False),
        sa.Column("fact_type", sa.String(60), nullable=False),
        sa.Column("amount", sa.String(40)),
        sa.Column("normalized_value", sa.JSON),
        sa.Column("original_value", sa.Text, nullable=False),
        sa.Column("currency", sa.String(3)),
        sa.Column("effective_date", sa.Date),
        sa.Column("valid_from", sa.Date),
        sa.Column("valid_to", sa.Date),
        sa.Column("source_text", sa.Text, nullable=False),
        sa.Column("bounding_box", sa.JSON),
        sa.Column("extraction_method", sa.String(20), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("verification_status", sa.String(30), nullable=False),
        sa.Column("model_id", sa.String(200)),
        sa.Column("prompt_version", sa.String(50)),
        _fk("supersedes_fact_id", "extracted_facts.id", nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        _created(),
        sa.UniqueConstraint("idempotency_key"),
    )
    _index("extracted_facts", "case_id")
    _index("extracted_facts", "document_id")

    op.create_table(
        "evidences",
        _pk(),
        _fk("case_id", "onboarding_cases.id"),
        _fk("claim_id", "customer_claims.id"),
        _fk("fact_id", "extracted_facts.id"),
        sa.Column("relation", sa.String(30), nullable=False),
        sa.Column("rationale", sa.Text, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        _created(),
        sa.UniqueConstraint("claim_id", "fact_id", name="uq_evidence_claim_fact"),
    )
    for col in ("case_id", "claim_id", "fact_id"):
        _index("evidences", col)

    op.create_table(
        "conflicts",
        _pk(),
        _fk("case_id", "onboarding_cases.id"),
        sa.Column("conflict_type", sa.String(60), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("rule_id", sa.String(60), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("details", sa.JSON, nullable=False),
        _created(),
        _created("updated_at"),
    )
    _index("conflicts", "case_id")

    op.create_table(
        "evidence_requirements",
        _pk(),
        _fk("case_id", "onboarding_cases.id"),
        _fk("claim_id", "customer_claims.id", nullable=True),
        _fk("conflict_id", "conflicts.id", nullable=True),
        sa.Column("audience", sa.String(20), nullable=False),
        sa.Column("priority", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("request_text", sa.Text, nullable=False),
        _created(),
    )
    _index("evidence_requirements", "case_id")

    op.create_table(
        "analyst_decisions",
        _pk(),
        _fk("case_id", "onboarding_cases.id"),
        _fk("conflict_id", "conflicts.id", nullable=True),
        _fk("claim_id", "customer_claims.id", nullable=True),
        sa.Column("decision_type", sa.String(40), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("analyst_id", sa.String(100), nullable=False),
        _created(),
    )
    _index("analyst_decisions", "case_id")

    op.create_table(
        "workflow_runs",
        _pk(),
        _fk("case_id", "onboarding_cases.id"),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("error_message", sa.Text),
        _created("started_at"),
        sa.Column("finished_at", sa.DateTime),
    )
    _index("workflow_runs", "case_id")

    op.create_table(
        "audit_events",
        _pk(),
        sa.Column("case_id", _ID),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("entity_type", sa.String(60), nullable=False),
        sa.Column("entity_id", _ID, nullable=False),
        sa.Column("previous_value", sa.JSON),
        sa.Column("new_value", sa.JSON),
        sa.Column("reason", sa.Text),
        sa.Column("workflow_run_id", _ID),
        sa.Column("model_version", sa.String(200)),
        sa.Column("correlation_id", sa.String(64)),
        _created(),
    )
    _index("audit_events", "case_id")

    op.execute(
        "CREATE TRIGGER audit_events_no_update BEFORE UPDATE ON audit_events "
        "BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER audit_events_no_delete BEFORE DELETE ON audit_events "
        "BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_events_no_update")
    op.execute("DROP TRIGGER IF EXISTS audit_events_no_delete")
    for table in (
        "audit_events",
        "workflow_runs",
        "analyst_decisions",
        "evidence_requirements",
        "conflicts",
        "evidences",
        "extracted_facts",
        "document_pages",
        "documents",
        "customer_claims",
        "declarations",
        "onboarding_cases",
        "customers",
    ):
        op.drop_table(table)
