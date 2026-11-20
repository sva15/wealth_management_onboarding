"""API response models and shared pagination types."""
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.domain.declaration import DeclarationInput

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class _ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CustomerOut(_ORM):
    id: str
    full_name: str
    pan: str | None
    date_of_birth: date | None
    email: str | None
    created_at: datetime


class CaseCreate(BaseModel):
    customer_id: str


class CaseOut(_ORM):
    id: str
    customer_id: str
    customer_name: str
    status: str
    created_at: datetime
    updated_at: datetime


class ClaimOut(_ORM):
    id: str
    customer_id: str
    case_id: str
    declaration_id: str
    claim_type: str
    declared_amount: Decimal | None
    currency: str
    effective_date: date
    description: str
    materiality: str
    verification_status: str
    created_at: datetime
    updated_at: datetime


class DeclarationOut(_ORM):
    id: str
    case_id: str
    payload: DeclarationInput
    created_by: str
    created_at: datetime


class DeclarationResult(BaseModel):
    declaration: DeclarationOut
    claims: list[ClaimOut]


class CaseDetailOut(CaseOut):
    latest_declaration: DeclarationOut | None = None


class DashboardSummary(BaseModel):
    total_cases: int
    requires_review: int
    awaiting_customer_evidence: int
    extraction_failures: int
    by_status: dict[str, int]
    recent_cases: list[CaseOut]


class DocumentOut(_ORM):
    id: str
    case_id: str
    filename: str
    sha256: str
    size_bytes: int
    media_type: str
    document_type: str | None
    classification_confidence: float | None
    classification_explanation: str | None
    processing_status: str
    error_message: str | None
    page_count: int | None
    uploaded_at: datetime


class DocumentPageOut(_ORM):
    page_number: int
    text: str


class UploadOutcomeOut(BaseModel):
    filename: str
    outcome: str  # ACCEPTED | DUPLICATE | REJECTED
    document: DocumentOut | None = None
    error_code: str | None = None
    error_message: str | None = None


class UploadResponse(BaseModel):
    results: list[UploadOutcomeOut]


class ExtractedFactOut(BaseModel):
    id: str
    case_id: str
    document_id: str
    document_filename: str
    page_number: int
    fact_type: str
    amount: Decimal | None
    currency: str | None
    effective_date: date | None
    normalized_value: dict[str, Any] | None
    original_value: str
    source_text: str
    extraction_method: str
    confidence: float
    verification_status: str
    model_id: str | None
    prompt_version: str | None
    created_at: datetime


class ExtractionOutcomeOut(BaseModel):
    document: DocumentOut
    status: str
    facts_created: int
    facts_total: int
    issues: list[str]


class DiagnosticOut(_ORM):
    id: str
    document_id: str
    task: str
    prompt_version: str
    model_id: str
    stage: str
    error_type: str
    error_summary: str
    created_at: datetime


class EntityMatchOut(_ORM):
    id: str
    case_id: str
    entity_kind: str
    left_label: str
    right_label: str
    score: float
    method: str
    explanation: str
    status: str
    decided_by: str | None
    decision_reason: str | None
    decided_at: datetime | None
    created_at: datetime


class MatchDecisionIn(BaseModel):
    decision: Literal["CONFIRM", "REJECT"]
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)]


class LinkSummaryOut(BaseModel):
    entities: int
    matches_auto_accepted: int
    matches_pending: int
    evidence_created: int
    evidence_updated: int
    evidence_removed: int
    graph: dict[str, int]


class EvidenceOut(BaseModel):
    id: str
    claim_id: str
    claim_type: str
    claim_description: str
    claim_declared_amount: Decimal | None
    currency: str
    fact_id: str
    fact_type: str
    fact_amount: Decimal | None
    fact_verification_status: str
    document_id: str
    document_filename: str
    page_number: int
    source_text: str
    relation: str
    rationale: str
    confidence: float
    link_method: str


class GraphNodeOut(BaseModel):
    id: str
    label: str
    properties: dict[str, Any]


class GraphEdgeOut(BaseModel):
    source: str
    type: str
    target: str
    properties: dict[str, Any]


class GraphOut(BaseModel):
    nodes: list[GraphNodeOut]
    edges: list[GraphEdgeOut]


class FactRefOut(BaseModel):
    fact_id: str
    document_id: str
    document_filename: str
    page_number: int
    amount: Decimal | None
    currency: str | None
    effective_date: date | None
    source_text: str
    confidence: float


class SaleProceedsOut(BaseModel):
    event_id: str
    reference: str | None
    event_date: str | None
    consideration: FactRefOut
    observed_credits: list[FactRefOut]
    duplicate_credit_facts: list[FactRefOut]
    difference: Decimal
    currency: str
    status: str
    formula: str
    input_fact_ids: list[str]
    excluded_fact_ids: list[str]
    calculated_at: datetime
    notes: list[str]
    linked_claim_ids: list[str]


class ConflictOut(_ORM):
    id: str
    case_id: str
    rule_id: str
    severity: str
    status: str
    description: str
    details: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class RequirementOut(_ORM):
    id: str
    case_id: str
    claim_id: str | None
    conflict_id: str | None
    audience: str
    priority: str
    status: str
    request_text: str
    details: dict[str, Any] | None
    created_at: datetime


class CalculationOut(BaseModel):
    name: str
    formula: str
    result: Decimal
    currency: str
    unit: str
    input_fact_ids: list[str]
    excluded_fact_ids: list[str]
    calculated_at: datetime
    notes: list[str]


class ComponentOut(BaseModel):
    kind: str
    label: str
    amount: Decimal
    currency: str
    value_date: date | None
    age_days: int | None
    fact_ids: list[str]
    entity_id: str | None


class ExclusionOut(BaseModel):
    fact_id: str
    kind: str
    reason: str
    amount: Decimal | None
    detail: str


class ClaimReconciliationOut(BaseModel):
    claim_id: str
    claim_type: str
    description: str
    materiality: str
    currency: str
    declared_amount: Decimal | None
    evidence_backed_amount: Decimal
    supported_amount: Decimal
    difference: Decimal | None
    status: str
    rule_id: str
    explanation: str
    input_fact_ids: list[str]
    excluded_fact_ids: list[str]


class ReconciliationOut(BaseModel):
    run_id: str
    case_id: str
    as_of: date
    currency: str
    calculated_at: datetime
    summary: dict[str, Any]
    calculations: list[CalculationOut]
    components: list[ComponentOut]
    exclusions: list[ExclusionOut]
    claims: list[ClaimReconciliationOut]
    conflicts: list[ConflictOut]
    requirements: list[RequirementOut]


class AuditEventOut(_ORM):
    id: str
    case_id: str | None
    actor: str
    action: str
    entity_type: str
    entity_id: str
    previous_value: dict[str, Any] | None
    new_value: dict[str, Any] | None
    reason: str | None
    workflow_run_id: str | None
    model_version: str | None
    correlation_id: str | None
    created_at: datetime
