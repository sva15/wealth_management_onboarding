"""Customer, case, declaration, claim, dashboard and audit endpoints."""
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_case_service, get_context, get_session
from app.api.schemas import (
    AuditEventOut,
    CaseCreate,
    CaseDetailOut,
    CaseOut,
    ClaimOut,
    CustomerOut,
    DashboardSummary,
    DeclarationOut,
    DeclarationResult,
    Page,
)
from app.domain.customer import CustomerInput
from app.domain.declaration import DeclarationInput
from app.domain.enums import Role
from app.services.audit import list_audit_events
from app.services.cases import CaseService
from app.services.context import RequestContext, require_role

router = APIRouter(tags=["cases"])

_CAN_WRITE = (Role.ANALYST.value, Role.CUSTOMER.value, Role.ADMIN.value)
_STAFF = (Role.ANALYST.value, Role.ADMIN.value)


def _case_out(case, name: str) -> CaseOut:
    return CaseOut(
        id=case.id,
        customer_id=case.customer_id,
        customer_name=name,
        status=case.status,
        created_at=case.created_at,
        updated_at=case.updated_at,
    )


@router.post("/customers", response_model=CustomerOut, status_code=status.HTTP_201_CREATED)
def create_customer(
    body: CustomerInput,
    svc: CaseService = Depends(get_case_service),
    ctx: RequestContext = Depends(get_context),
):
    require_role(ctx, *_CAN_WRITE)
    return svc.create_customer(body)


@router.get("/customers/{customer_id}", response_model=CustomerOut)
def get_customer(
    customer_id: str,
    svc: CaseService = Depends(get_case_service),
    ctx: RequestContext = Depends(get_context),
):
    require_role(ctx, *_STAFF)
    return svc.get_customer(customer_id)


@router.post("/cases", response_model=CaseOut, status_code=status.HTTP_201_CREATED)
def create_case(
    body: CaseCreate,
    svc: CaseService = Depends(get_case_service),
    ctx: RequestContext = Depends(get_context),
):
    require_role(ctx, *_CAN_WRITE)
    case = svc.create_case(body.customer_id)
    return _case_out(case, svc.customer_name(case))


@router.get("/cases", response_model=Page[CaseOut])
def list_cases(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status_filter: str | None = Query(None, alias="status"),
    svc: CaseService = Depends(get_case_service),
    ctx: RequestContext = Depends(get_context),
):
    require_role(ctx, *_STAFF)
    rows, total = svc.list_cases(limit, offset, status_filter)
    return Page[CaseOut](
        items=[_case_out(c, n) for c, n in rows], total=total, limit=limit, offset=offset
    )


@router.get("/cases/{case_id}", response_model=CaseDetailOut)
def get_case(case_id: str, svc: CaseService = Depends(get_case_service)):
    case = svc.get_case(case_id)
    base = _case_out(case, svc.customer_name(case))
    latest = svc.latest_declaration(case_id)
    return CaseDetailOut(
        **base.model_dump(),
        latest_declaration=DeclarationOut.model_validate(latest) if latest else None,
    )


@router.post(
    "/cases/{case_id}/declarations",
    response_model=DeclarationResult,
    status_code=status.HTTP_201_CREATED,
)
def add_declaration(
    case_id: str,
    body: DeclarationInput,
    svc: CaseService = Depends(get_case_service),
    ctx: RequestContext = Depends(get_context),
):
    require_role(ctx, *_CAN_WRITE)
    declaration, claims = svc.add_declaration(case_id, body)
    return DeclarationResult(
        declaration=DeclarationOut.model_validate(declaration),
        claims=[ClaimOut.model_validate(c) for c in claims],
    )


@router.get("/cases/{case_id}/claims", response_model=list[ClaimOut])
def list_claims(
    case_id: str,
    include_superseded: bool = False,
    svc: CaseService = Depends(get_case_service),
):
    return svc.list_claims(case_id, include_superseded)


@router.get("/cases/{case_id}/audit", response_model=Page[AuditEventOut])
def case_audit(
    case_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    svc: CaseService = Depends(get_case_service),
    session: Session = Depends(get_session),
    ctx: RequestContext = Depends(get_context),
):
    require_role(ctx, *_STAFF)
    svc.get_case(case_id)
    rows, total = list_audit_events(session, case_id, limit, offset)
    return Page[AuditEventOut](
        items=[AuditEventOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/dashboard/summary", response_model=DashboardSummary)
def dashboard_summary(
    svc: CaseService = Depends(get_case_service),
    ctx: RequestContext = Depends(get_context),
):
    require_role(ctx, *_STAFF)
    summary = svc.dashboard_summary()
    summary["recent_cases"] = [_case_out(c, n) for c, n in summary["recent_cases"]]
    return summary
