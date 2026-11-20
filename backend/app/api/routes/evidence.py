"""Entity matches, evidence links, the evidence graph and the sale-proceeds check."""
from fastapi import APIRouter, Depends

from app.api.deps import get_context, get_evidence_service
from app.api.schemas import (
    EntityMatchOut,
    EvidenceOut,
    FactRefOut,
    GraphEdgeOut,
    GraphNodeOut,
    GraphOut,
    LinkSummaryOut,
    MatchDecisionIn,
    SaleProceedsOut,
)
from app.domain.enums import Role
from app.domain.facts import FactView
from app.services.context import RequestContext, require_role
from app.services.evidence import EvidenceService

router = APIRouter(tags=["evidence"])
_STAFF = (Role.ANALYST.value, Role.ADMIN.value)


def _fact_ref(f: FactView) -> FactRefOut:
    return FactRefOut(
        fact_id=f.id,
        document_id=f.document_id,
        document_filename=f.document_name,
        page_number=f.page,
        amount=f.amount,
        currency=f.currency,
        effective_date=f.effective_date,
        source_text=f.source_text,
        confidence=f.confidence,
    )


@router.post("/cases/{case_id}/link-evidence", response_model=LinkSummaryOut)
def link_evidence(
    case_id: str,
    svc: EvidenceService = Depends(get_evidence_service),
    ctx: RequestContext = Depends(get_context),
):
    """Resolve entities, link claims to evidence and rebuild the graph. Idempotent."""
    require_role(ctx, *_STAFF)
    return svc.run(case_id)


@router.get("/cases/{case_id}/entity-matches", response_model=list[EntityMatchOut])
def list_entity_matches(
    case_id: str,
    svc: EvidenceService = Depends(get_evidence_service),
    ctx: RequestContext = Depends(get_context),
):
    require_role(ctx, *_STAFF)
    return svc.list_matches(case_id)


@router.post("/entity-matches/{match_id}/decision", response_model=EntityMatchOut)
def decide_entity_match(
    match_id: str,
    body: MatchDecisionIn,
    svc: EvidenceService = Depends(get_evidence_service),
    ctx: RequestContext = Depends(get_context),
):
    require_role(ctx, *_STAFF)
    return svc.decide_match(match_id, body.decision, body.reason)


@router.get("/cases/{case_id}/evidence", response_model=list[EvidenceOut])
def list_evidence(
    case_id: str,
    svc: EvidenceService = Depends(get_evidence_service),
    ctx: RequestContext = Depends(get_context),
):
    require_role(ctx, *_STAFF)
    return svc.list_evidence(case_id)


@router.get("/cases/{case_id}/graph", response_model=GraphOut)
def get_graph(
    case_id: str,
    svc: EvidenceService = Depends(get_evidence_service),
    ctx: RequestContext = Depends(get_context),
):
    require_role(ctx, *_STAFF)
    nodes, edges = svc.get_graph(case_id)
    return GraphOut(
        nodes=[GraphNodeOut(id=n.id, label=n.label, properties=n.properties) for n in nodes],
        edges=[GraphEdgeOut(source=e.source, type=e.type, target=e.target, properties=e.properties) for e in edges],
    )


@router.get("/cases/{case_id}/reconciliation/sale-proceeds", response_model=list[SaleProceedsOut])
def sale_proceeds(
    case_id: str,
    svc: EvidenceService = Depends(get_evidence_service),
    ctx: RequestContext = Depends(get_context),
):
    require_role(ctx, *_STAFF)
    return [
        SaleProceedsOut(
            event_id=p.event_id,
            reference=p.reference,
            event_date=p.event_date,
            consideration=_fact_ref(p.consideration),
            observed_credits=[_fact_ref(f) for f in p.credits],
            duplicate_credit_facts=[_fact_ref(f) for f in p.duplicate_credit_facts],
            difference=p.calculation.result,
            currency=p.calculation.currency,
            status=p.status,
            formula=p.calculation.formula,
            input_fact_ids=list(p.calculation.input_fact_ids),
            excluded_fact_ids=list(p.calculation.excluded_fact_ids),
            calculated_at=p.calculation.calculated_at,
            notes=list(p.calculation.notes),
            linked_claim_ids=p.linked_claim_ids,
        )
        for p in svc.sale_proceeds(case_id)
    ]
