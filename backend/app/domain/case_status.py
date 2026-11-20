"""Derive an onboarding case's status from its documents."""
from collections.abc import Iterable

from app.domain.enums import CaseStatus, ProcessingStatus

# Statuses owned by document processing; later workflow states are never overwritten here.
DOCUMENT_DRIVEN = frozenset(
    {
        CaseStatus.AWAITING_DOCUMENTS.value,
        CaseStatus.PROCESSING.value,
        CaseStatus.REQUIRES_REVIEW.value,
        CaseStatus.EXTRACTION_FAILED.value,
    }
)


def derive_case_status(current: str, document_statuses: Iterable[str]) -> str:
    if current not in DOCUMENT_DRIVEN:
        return current
    statuses = list(document_statuses)
    if ProcessingStatus.FAILED.value in statuses:
        return CaseStatus.EXTRACTION_FAILED.value
    if ProcessingStatus.REQUIRES_REVIEW.value in statuses:
        return CaseStatus.REQUIRES_REVIEW.value
    if statuses:
        return CaseStatus.PROCESSING.value
    return CaseStatus.AWAITING_DOCUMENTS.value


RECONCILIATION_DRIVEN = DOCUMENT_DRIVEN | {
    CaseStatus.AWAITING_CUSTOMER_EVIDENCE.value,
    CaseStatus.READY_FOR_ANALYST_DECISION.value,
}


def case_status_after_reconciliation(
    current: str,
    document_statuses: Iterable[str],
    open_requirements: Iterable[tuple[str, str]],
) -> str:
    """Queue state for analysts. It never approves or rejects: that stays a human decision.

    `open_requirements` holds (audience, priority) for evidence requests that are still open.
    """
    if current not in RECONCILIATION_DRIVEN:
        return current
    statuses = list(document_statuses)
    if ProcessingStatus.FAILED.value in statuses:
        return CaseStatus.EXTRACTION_FAILED.value
    if ProcessingStatus.REQUIRES_REVIEW.value in statuses:
        return CaseStatus.REQUIRES_REVIEW.value
    reqs = list(open_requirements)
    if any(a == "CUSTOMER" and p in ("MEDIUM", "HIGH") for a, p in reqs):
        return CaseStatus.AWAITING_CUSTOMER_EVIDENCE.value
    if any(a == "ANALYST" and p in ("MEDIUM", "HIGH") for a, p in reqs):
        return CaseStatus.REQUIRES_REVIEW.value
    return CaseStatus.READY_FOR_ANALYST_DECISION.value
