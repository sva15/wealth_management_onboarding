"""Fact extraction endpoints."""
from fastapi import APIRouter, Depends, Query

from app.api.deps import get_context, get_extraction_service
from app.api.schemas import (
    DiagnosticOut,
    DocumentOut,
    ExtractedFactOut,
    ExtractionOutcomeOut,
    Page,
)
from app.domain.enums import Role
from app.services.context import RequestContext, require_role
from app.services.extraction import ExtractionOutcome, ExtractionService

router = APIRouter(tags=["extraction"])
_STAFF = (Role.ANALYST.value, Role.ADMIN.value)


def _outcome_out(o: ExtractionOutcome) -> ExtractionOutcomeOut:
    return ExtractionOutcomeOut(
        document=DocumentOut.model_validate(o.document),
        status=o.status,
        facts_created=o.facts_created,
        facts_total=o.facts_total,
        issues=o.issues,
    )


@router.post("/documents/{document_id}/extract", response_model=ExtractionOutcomeOut)
def extract_document(
    document_id: str,
    svc: ExtractionService = Depends(get_extraction_service),
    ctx: RequestContext = Depends(get_context),
):
    require_role(ctx, *_STAFF)
    return _outcome_out(svc.extract_document(document_id))


@router.post("/cases/{case_id}/extract", response_model=list[ExtractionOutcomeOut])
def extract_case(
    case_id: str,
    svc: ExtractionService = Depends(get_extraction_service),
    ctx: RequestContext = Depends(get_context),
):
    """Extract every classified document in the case that has a supported type."""
    require_role(ctx, *_STAFF)
    return [_outcome_out(o) for o in svc.extract_case(case_id)]


@router.get("/cases/{case_id}/facts", response_model=Page[ExtractedFactOut])
def list_facts(
    case_id: str,
    document_id: str | None = None,
    fact_type: str | None = None,
    include_superseded: bool = False,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    svc: ExtractionService = Depends(get_extraction_service),
    ctx: RequestContext = Depends(get_context),
):
    require_role(ctx, *_STAFF)
    rows, total = svc.list_facts(case_id, limit, offset, document_id, fact_type, include_superseded)
    items = [
        ExtractedFactOut(
            **{c: getattr(f, c) for c in ExtractedFactOut.model_fields if c != "document_filename"},
            document_filename=name,
        )
        for f, name in rows
    ]
    return Page[ExtractedFactOut](items=items, total=total, limit=limit, offset=offset)


@router.get("/documents/{document_id}/diagnostics", response_model=list[DiagnosticOut])
def list_diagnostics(
    document_id: str,
    svc: ExtractionService = Depends(get_extraction_service),
    ctx: RequestContext = Depends(get_context),
):
    """Error summaries only. Raw model responses stay in the database."""
    require_role(ctx, *_STAFF)
    return svc.list_diagnostics(document_id)
