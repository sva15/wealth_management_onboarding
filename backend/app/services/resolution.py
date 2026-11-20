"""Loads case facts, runs entity resolution and keeps entity-match rows in step with it."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.persistence.models import (
    CustomerRow,
    DocumentRow,
    EntityMatchRow,
    ExtractedFactRow,
    OnboardingCaseRow,
    utcnow,
)
from app.domain.entity_resolution import (
    AUTO,
    CONFIRMED,
    PENDING,
    REJECTED,
    CustomerAnchor,
    Resolution,
    resolve_entities,
)
from app.domain.enums import VerificationStatus
from app.domain.facts import FactView
from app.services.audit import AuditService
from app.services.errors import NotFoundError

_EXCLUDED = (VerificationStatus.SUPERSEDED.value, VerificationStatus.ANALYST_REJECTED.value)


def load_fact_views(session: Session, case_id: str) -> list[FactView]:
    rows = session.execute(
        select(ExtractedFactRow, DocumentRow.filename)
        .join(DocumentRow, DocumentRow.id == ExtractedFactRow.document_id)
        .where(ExtractedFactRow.case_id == case_id, ExtractedFactRow.verification_status.notin_(_EXCLUDED))
        .order_by(ExtractedFactRow.created_at, ExtractedFactRow.id)
    ).all()
    return [
        FactView(
            id=f.id,
            document_id=f.document_id,
            document_name=name,
            fact_type=f.fact_type,
            page=f.page_number,
            confidence=f.confidence,
            amount=f.amount,
            currency=f.currency,
            effective_date=f.effective_date,
            normalized=f.normalized_value or {},
            source_text=f.source_text,
        )
        for f, name in rows
    ]


def compute_resolution(session: Session, case_id: str) -> Resolution:
    case = session.get(OnboardingCaseRow, case_id)
    if case is None:
        raise NotFoundError("Case not found")
    customer = session.get(CustomerRow, case.customer_id)
    anchor = CustomerAnchor(customer.id, customer.full_name, customer.pan) if customer else None
    decisions = {
        m.match_key: m.status
        for m in session.scalars(
            select(EntityMatchRow).where(
                EntityMatchRow.case_id == case_id, EntityMatchRow.status.in_((CONFIRMED, REJECTED))
            )
        )
    }
    return resolve_entities(case_id, load_fact_views(session, case_id), anchor, decisions)


def sync_matches(session: Session, audit: AuditService, case_id: str, resolution: Resolution) -> None:
    """Upsert derived matches. Analyst decisions are never overwritten; stale derived rows are removed."""
    existing = {
        m.match_key: m
        for m in session.scalars(select(EntityMatchRow).where(EntityMatchRow.case_id == case_id))
    }
    produced: set[str] = set()
    for rec in resolution.matches:
        if rec.key in produced:
            continue
        produced.add(rec.key)
        row = existing.get(rec.key)
        if row is None:
            row = EntityMatchRow(
                case_id=case_id,
                match_key=rec.key,
                entity_kind=rec.kind,
                left_ref=rec.left_ref,
                right_ref=rec.right_ref,
                left_label=rec.left_label[:300],
                right_label=rec.right_label[:300],
                score=rec.score,
                method=rec.method,
                explanation=rec.explanation,
                status=rec.status,
            )
            session.add(row)
            session.flush()
            audit.record(
                action="entity_match.auto_accepted" if rec.status == AUTO else "entity_match.candidate_created",
                entity_type="entity_match",
                entity_id=row.id,
                case_id=case_id,
                new={"kind": rec.kind, "score": rec.score, "method": rec.method, "status": rec.status},
            )
        elif row.status in (AUTO, PENDING):
            row.score, row.method, row.explanation, row.status = rec.score, rec.method, rec.explanation, rec.status
            row.left_label, row.right_label = rec.left_label[:300], rec.right_label[:300]
    for key, row in existing.items():
        if key not in produced and row.status in (AUTO, PENDING):
            session.delete(row)
    session.flush()


def mark_decision(row: EntityMatchRow, status: str, actor: str, reason: str) -> None:
    row.status = status
    row.decided_by = actor
    row.decision_reason = reason
    row.decided_at = utcnow()
