"""Rebuilds a case's financial evidence graph from the relational store (the system of record).

Projection is idempotent: the case's nodes are cleared and re-merged, so retries and reprocessing
never leave duplicates. Raw document text, names of the customer and source quotes are not written
to the graph.
"""
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.persistence.models import (
    ConflictRow,
    CustomerClaimRow,
    DocumentRow,
    EvidenceRow,
    ExtractedFactRow,
    OnboardingCaseRow,
)
from app.domain.entity_resolution import (
    ACCOUNT,
    ASSET,
    EVENT,
    LIABILITY,
    ORGANIZATION,
    PERSON,
    TRANSACTION,
    Resolution,
)
from app.domain.enums import EvidenceRelation, VerificationStatus
from app.ports.graph import GraphRepository
from app.services.errors import NotFoundError
from app.services.resolution import compute_resolution

_KIND_LABEL = {
    ORGANIZATION: "Organization",
    ACCOUNT: "Account",
    ASSET: "Asset",
    LIABILITY: "Liability",
    TRANSACTION: "Transaction",
    EVENT: "FinancialEvent",
}
_EVIDENCE_EDGE = {
    EvidenceRelation.SUPPORTS.value: "SUPPORTED_BY",
    EvidenceRelation.PARTIALLY_SUPPORTS.value: "SUPPORTED_BY",
    EvidenceRelation.CONTRADICTS.value: "CONTRADICTED_BY",
    EvidenceRelation.REQUIRES_REVIEW.value: "REVIEW_PENDING",
}


def _scalar_attrs(attrs: dict[str, Any]) -> dict[str, Any]:
    """Keep primitive display attributes; ids are expressed as relationships instead."""
    return {
        k: v
        for k, v in attrs.items()
        if not k.endswith("_id") and not k.endswith("_ids") and isinstance(v, (str, int, float, bool))
    }


class GraphProjectionService:
    def __init__(self, session: Session, graph: GraphRepository) -> None:
        self._s = session
        self._graph = graph

    def project_case(self, case_id: str, resolution: Resolution | None = None) -> dict[str, int]:
        case = self._s.get(OnboardingCaseRow, case_id)
        if case is None:
            raise NotFoundError("Case not found")
        resolution = resolution or compute_resolution(self._s, case_id)
        g = self._graph
        g.clear_case(case_id)

        g.merge_node("Customer", case.customer_id, {})
        claims = list(self._s.scalars(select(CustomerClaimRow).where(CustomerClaimRow.case_id == case_id)))
        for c in claims:
            g.merge_node(
                "Claim",
                c.id,
                {
                    "case_id": case_id,
                    "claim_type": c.claim_type,
                    "declared_amount": str(c.declared_amount) if c.declared_amount is not None else None,
                    "currency": c.currency,
                    "materiality": c.materiality,
                    "verification_status": c.verification_status,
                },
            )
            g.merge_relationship(case.customer_id, "DECLARES", c.id)

        docs = list(self._s.scalars(select(DocumentRow).where(DocumentRow.case_id == case_id)))
        for d in docs:
            g.merge_node(
                "Document",
                d.id,
                {
                    "case_id": case_id,
                    "name": d.filename,
                    "document_type": d.document_type,
                    "processing_status": d.processing_status,
                },
            )

        facts = list(
            self._s.scalars(
                select(ExtractedFactRow).where(
                    ExtractedFactRow.case_id == case_id,
                    ExtractedFactRow.verification_status.notin_(
                        (VerificationStatus.SUPERSEDED.value, VerificationStatus.ANALYST_REJECTED.value)
                    ),
                )
            )
        )
        fact_ids = set()
        for f in facts:
            fact_ids.add(f.id)
            g.merge_node(
                "ExtractedFact",
                f.id,
                {
                    "case_id": case_id,
                    "fact_type": f.fact_type,
                    "amount": str(f.amount) if f.amount is not None else None,
                    "currency": f.currency,
                    "page": f.page_number,
                    "confidence": f.confidence,
                    "verification_status": f.verification_status,
                    "effective_date": f.effective_date.isoformat() if f.effective_date else None,
                },
            )
            g.merge_relationship(f.document_id, "CONTAINS", f.id)

        entity_nodes = 0
        for entity in resolution.entities.values():
            if entity.kind == PERSON:
                if entity.is_customer:
                    continue  # already merged above, deliberately without a case tag
                label, props = "Person", {"name": entity.label}
            else:
                label, props = _KIND_LABEL[entity.kind], {"name": entity.label, **_scalar_attrs(entity.attrs)}
            g.merge_node(label, entity.id, {"case_id": case_id, **props})
            entity_nodes += 1
        for rel in resolution.relations:
            g.merge_relationship(rel.source, rel.type, rel.target, rel.props)
        for fact_id, entity_ids in resolution.fact_entities.items():
            if fact_id in fact_ids:
                for entity_id in entity_ids:
                    g.merge_relationship(fact_id, "DESCRIBES", entity_id)

        evidence = list(self._s.scalars(select(EvidenceRow).where(EvidenceRow.case_id == case_id)))
        for e in evidence:
            if e.fact_id not in fact_ids:
                continue
            g.merge_node(
                "Evidence",
                e.id,
                {
                    "case_id": case_id,
                    "relation": e.relation,
                    "confidence": e.confidence,
                    "link_method": e.link_method,
                    "rationale": e.rationale,
                },
            )
            g.merge_relationship(e.claim_id, _EVIDENCE_EDGE[e.relation], e.id, {"relation": e.relation})
            g.merge_relationship(e.id, "REFERENCES", e.fact_id)

        claim_ids = {c.id for c in claims}
        for conflict in self._s.scalars(select(ConflictRow).where(ConflictRow.case_id == case_id)):
            g.merge_node(
                "Conflict",
                conflict.id,
                {
                    "case_id": case_id,
                    "rule_id": conflict.rule_id,
                    "severity": conflict.severity,
                    "status": conflict.status,
                    "name": conflict.rule_id,
                },
            )
            for cid in conflict.details.get("claim_ids", []):
                if cid in claim_ids:
                    g.merge_relationship(conflict.id, "INVOLVES", cid)
            for fid in conflict.details.get("fact_ids", []):
                if fid in fact_ids:
                    g.merge_relationship(conflict.id, "INVOLVES", fid)

        return {
            "claims": len(claims),
            "documents": len(docs),
            "facts": len(facts),
            "entities": entity_nodes,
            "evidence": len(evidence),
        }
