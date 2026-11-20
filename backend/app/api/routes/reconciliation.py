"""Reconciliation, conflicts and evidence requests."""
from fastapi import APIRouter, Depends

from app.api.deps import get_context, get_reconciliation_service
from app.api.schemas import ConflictOut, ReconciliationOut, RequirementOut
from app.domain.enums import Role
from app.services.context import RequestContext, require_role
from app.services.reconciliation import ReconciliationService

router = APIRouter(tags=["reconciliation"])
_STAFF = (Role.ANALYST.value, Role.ADMIN.value)


def _full(svc: ReconciliationService, case_id: str, payload: dict) -> ReconciliationOut:
    return ReconciliationOut(
        **payload,
        conflicts=[ConflictOut.model_validate(c) for c in svc.list_conflicts(case_id)],
        requirements=[RequirementOut.model_validate(r) for r in svc.list_requirements(case_id)],
    )


@router.post("/cases/{case_id}/reconciliation/run", response_model=ReconciliationOut)
def run_reconciliation(
    case_id: str,
    svc: ReconciliationService = Depends(get_reconciliation_service),
    ctx: RequestContext = Depends(get_context),
):
    """Deterministic reconciliation. Safe to repeat: unchanged results create no new run."""
    require_role(ctx, *_STAFF)
    return _full(svc, case_id, svc.run(case_id))


@router.get("/cases/{case_id}/reconciliation", response_model=ReconciliationOut)
def get_reconciliation(
    case_id: str,
    svc: ReconciliationService = Depends(get_reconciliation_service),
    ctx: RequestContext = Depends(get_context),
):
    require_role(ctx, *_STAFF)
    return _full(svc, case_id, svc.latest(case_id))


@router.get("/cases/{case_id}/conflicts", response_model=list[ConflictOut])
def list_conflicts(
    case_id: str,
    status: str | None = None,
    severity: str | None = None,
    svc: ReconciliationService = Depends(get_reconciliation_service),
    ctx: RequestContext = Depends(get_context),
):
    require_role(ctx, *_STAFF)
    return svc.list_conflicts(case_id, status, severity)


@router.get("/cases/{case_id}/evidence-requirements", response_model=list[RequirementOut])
def list_requirements(
    case_id: str,
    status: str | None = None,
    svc: ReconciliationService = Depends(get_reconciliation_service),
    ctx: RequestContext = Depends(get_context),
):
    require_role(ctx, *_STAFF)
    return svc.list_requirements(case_id, status)
