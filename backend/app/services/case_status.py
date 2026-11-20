"""Keep an onboarding case's status in step with its documents."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.persistence.models import DocumentRow, OnboardingCaseRow, utcnow
from app.domain.case_status import derive_case_status
from app.services.audit import AuditService


def refresh_case_status(session: Session, audit: AuditService, case_id: str) -> None:
    case = session.get(OnboardingCaseRow, case_id)
    statuses = session.scalars(
        select(DocumentRow.processing_status).where(DocumentRow.case_id == case_id)
    ).all()
    new_status = derive_case_status(case.status, statuses)
    if new_status != case.status:
        audit.record(
            action="case.status_changed",
            entity_type="case",
            entity_id=case.id,
            case_id=case.id,
            previous={"status": case.status},
            new={"status": new_status},
            reason="Derived from document processing results",
        )
        case.status = new_status
    case.updated_at = utcnow()
