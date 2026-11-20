"""SQLAlchemy table definitions. Mirrors alembic/versions/0001_initial_schema.py."""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Date, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.adapters.persistence.database import Base
from app.adapters.persistence.types import DecimalText, UtcDateTime


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _id_col() -> Mapped[str]:
    return mapped_column(String(36), primary_key=True, default=new_id)


def _created() -> Mapped[datetime]:
    return mapped_column(UtcDateTime, default=utcnow)


class CustomerRow(Base):
    __tablename__ = "customers"
    id: Mapped[str] = _id_col()
    full_name: Mapped[str] = mapped_column(String(200))
    pan: Mapped[str | None] = mapped_column(String(10))
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    email: Mapped[str | None] = mapped_column(String(254))
    created_at: Mapped[datetime] = _created()


class OnboardingCaseRow(Base):
    __tablename__ = "onboarding_cases"
    id: Mapped[str] = _id_col()
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)


class DeclarationRow(Base):
    __tablename__ = "declarations"
    id: Mapped[str] = _id_col()
    case_id: Mapped[str] = mapped_column(ForeignKey("onboarding_cases.id"), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = _created()


class CustomerClaimRow(Base):
    __tablename__ = "customer_claims"
    id: Mapped[str] = _id_col()
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("onboarding_cases.id"), index=True)
    declaration_id: Mapped[str] = mapped_column(ForeignKey("declarations.id"), index=True)
    claim_type: Mapped[str] = mapped_column(String(40))
    declared_amount: Mapped[Decimal | None] = mapped_column(DecimalText(40))
    currency: Mapped[str] = mapped_column(String(3))
    effective_date: Mapped[date] = mapped_column(Date)
    description: Mapped[str] = mapped_column(Text)
    materiality: Mapped[str] = mapped_column(String(20))
    verification_status: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)


class DocumentRow(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("case_id", "sha256", name="uq_documents_case_sha256"),)
    id: Mapped[str] = _id_col()
    case_id: Mapped[str] = mapped_column(ForeignKey("onboarding_cases.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    media_type: Mapped[str] = mapped_column(String(100))
    storage_key: Mapped[str] = mapped_column(String(500))
    document_type: Mapped[str | None] = mapped_column(String(40))
    classification_confidence: Mapped[float | None] = mapped_column(Float)
    classification_explanation: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer)
    processing_status: Mapped[str] = mapped_column(String(30))
    error_message: Mapped[str | None] = mapped_column(Text)
    uploaded_at: Mapped[datetime] = _created()


class DocumentPageRow(Base):
    __tablename__ = "document_pages"
    __table_args__ = (UniqueConstraint("document_id", "page_number", name="uq_pages_doc_page"),)
    id: Mapped[str] = _id_col()
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    page_number: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


class ExtractedFactRow(Base):
    __tablename__ = "extracted_facts"
    id: Mapped[str] = _id_col()
    case_id: Mapped[str] = mapped_column(ForeignKey("onboarding_cases.id"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    page_number: Mapped[int] = mapped_column(Integer)
    fact_type: Mapped[str] = mapped_column(String(60))
    amount: Mapped[Decimal | None] = mapped_column(DecimalText(40))
    normalized_value: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    original_value: Mapped[str] = mapped_column(Text)
    currency: Mapped[str | None] = mapped_column(String(3))
    effective_date: Mapped[date | None] = mapped_column(Date)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    source_text: Mapped[str] = mapped_column(Text)
    bounding_box: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    extraction_method: Mapped[str] = mapped_column(String(20))
    confidence: Mapped[float] = mapped_column(Float)
    verification_status: Mapped[str] = mapped_column(String(30))
    model_id: Mapped[str | None] = mapped_column(String(200))
    prompt_version: Mapped[str | None] = mapped_column(String(50))
    supersedes_fact_id: Mapped[str | None] = mapped_column(ForeignKey("extracted_facts.id"))
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = _created()


class ExtractionDiagnosticRow(Base):
    """Failed or rejected model output, kept for diagnosis. raw_response may contain document text."""

    __tablename__ = "extraction_diagnostics"
    id: Mapped[str] = _id_col()
    case_id: Mapped[str] = mapped_column(ForeignKey("onboarding_cases.id"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    task: Mapped[str] = mapped_column(String(60))
    prompt_version: Mapped[str] = mapped_column(String(50))
    model_id: Mapped[str] = mapped_column(String(200))
    stage: Mapped[str] = mapped_column(String(20))
    error_type: Mapped[str] = mapped_column(String(60))
    error_summary: Mapped[str] = mapped_column(Text)
    raw_response: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


class EvidenceRow(Base):
    __tablename__ = "evidences"
    __table_args__ = (UniqueConstraint("claim_id", "fact_id", name="uq_evidence_claim_fact"),)
    id: Mapped[str] = _id_col()
    case_id: Mapped[str] = mapped_column(ForeignKey("onboarding_cases.id"), index=True)
    claim_id: Mapped[str] = mapped_column(ForeignKey("customer_claims.id"), index=True)
    fact_id: Mapped[str] = mapped_column(ForeignKey("extracted_facts.id"), index=True)
    relation: Mapped[str] = mapped_column(String(30))
    rationale: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    link_method: Mapped[str] = mapped_column(String(20), default="RULE", server_default="RULE")
    created_at: Mapped[datetime] = _created()


class EntityMatchRow(Base):
    """A merge decision between two mentions: auto-accepted by rule, pending, or decided by an analyst."""

    __tablename__ = "entity_matches"
    __table_args__ = (UniqueConstraint("case_id", "match_key", name="uq_entity_match_key"),)
    id: Mapped[str] = _id_col()
    case_id: Mapped[str] = mapped_column(ForeignKey("onboarding_cases.id"), index=True)
    match_key: Mapped[str] = mapped_column(String(160))
    entity_kind: Mapped[str] = mapped_column(String(30))
    left_ref: Mapped[str] = mapped_column(String(64))
    right_ref: Mapped[str] = mapped_column(String(64))
    left_label: Mapped[str] = mapped_column(String(300))
    right_label: Mapped[str] = mapped_column(String(300))
    score: Mapped[float] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String(40))
    explanation: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))
    decided_by: Mapped[str | None] = mapped_column(String(100))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)


class ConflictRow(Base):
    __tablename__ = "conflicts"
    id: Mapped[str] = _id_col()
    case_id: Mapped[str] = mapped_column(ForeignKey("onboarding_cases.id"), index=True)
    conflict_key: Mapped[str | None] = mapped_column(String(200), index=True)
    conflict_type: Mapped[str] = mapped_column(String(60))
    severity: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    rule_id: Mapped[str] = mapped_column(String(60))
    description: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)


class EvidenceRequirementRow(Base):
    __tablename__ = "evidence_requirements"
    id: Mapped[str] = _id_col()
    case_id: Mapped[str] = mapped_column(ForeignKey("onboarding_cases.id"), index=True)
    requirement_key: Mapped[str | None] = mapped_column(String(220), index=True)
    claim_id: Mapped[str | None] = mapped_column(ForeignKey("customer_claims.id"))
    conflict_id: Mapped[str | None] = mapped_column(ForeignKey("conflicts.id"))
    audience: Mapped[str] = mapped_column(String(20))
    priority: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    request_text: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = _created()


class ReconciliationRunRow(Base):
    """A stored reconciliation result: calculations with formulas, inputs and timestamps."""

    __tablename__ = "reconciliation_runs"
    id: Mapped[str] = _id_col()
    case_id: Mapped[str] = mapped_column(ForeignKey("onboarding_cases.id"), index=True)
    as_of: Mapped[date] = mapped_column(Date)
    result_hash: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(100))
    calculated_at: Mapped[datetime] = _created()


class AnalystDecisionRow(Base):
    __tablename__ = "analyst_decisions"
    id: Mapped[str] = _id_col()
    case_id: Mapped[str] = mapped_column(ForeignKey("onboarding_cases.id"), index=True)
    conflict_id: Mapped[str | None] = mapped_column(ForeignKey("conflicts.id"))
    claim_id: Mapped[str | None] = mapped_column(ForeignKey("customer_claims.id"))
    decision_type: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(Text)
    analyst_id: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = _created()


class WorkflowRunRow(Base):
    __tablename__ = "workflow_runs"
    id: Mapped[str] = _id_col()
    case_id: Mapped[str] = mapped_column(ForeignKey("onboarding_cases.id"), index=True)
    status: Mapped[str] = mapped_column(String(30))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = _created()
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime)


class AuditEventRow(Base):
    """Append-only; UPDATE and DELETE are blocked by database triggers."""

    __tablename__ = "audit_events"
    id: Mapped[str] = _id_col()
    case_id: Mapped[str | None] = mapped_column(String(36), index=True)
    actor: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(80))
    entity_type: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str] = mapped_column(String(36))
    previous_value: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    new_value: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(Text)
    workflow_run_id: Mapped[str | None] = mapped_column(String(36))
    model_version: Mapped[str | None] = mapped_column(String(200))
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _created()
