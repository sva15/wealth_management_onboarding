"""Entity resolution, claim-to-evidence linking, graph projection and the sale-proceeds check."""
from dataclasses import dataclass
from decimal import Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.persistence.models import (
    CustomerClaimRow,
    DocumentRow,
    EntityMatchRow,
    EvidenceRow,
    ExtractedFactRow,
    OnboardingCaseRow,
    utcnow,
)
from app.domain.entity_resolution import (
    AUTO,
    CONFIRMED,
    EVENT,
    PENDING,
    REJECTED,
    TRANSACTION,
    Resolution,
)
from app.domain.enums import VerificationStatus
from app.domain.evidence_linking import ClaimView, propose_links
from app.domain.facts import FactView
from app.domain.reconciliation.calculations import CalculationResult, sale_proceeds_difference
from app.ports.graph import GraphEdge, GraphNode, GraphRepository
from app.services.audit import AuditService
from app.services.context import RequestContext, authorize_case_access
from app.services.errors import ConflictError, NotFoundError
from app.services.graph_projection import GraphProjectionService
from app.services.resolution import compute_resolution, load_fact_views, mark_decision, sync_matches

log = structlog.get_logger()


@dataclass
class LinkSummary:
    entities: int
    matches_auto_accepted: int
    matches_pending: int
    evidence_created: int
    evidence_updated: int
    evidence_removed: int
    graph: dict[str, int]


@dataclass
class SaleProceeds:
    event_id: str
    reference: str | None
    event_date: str | None
    consideration: FactView
    credits: list[FactView]
    duplicate_credit_facts: list[FactView]
    calculation: CalculationResult
    status: str
    linked_claim_ids: list[str]


class EvidenceService:
    def __init__(self, session: Session, graph: GraphRepository, ctx: RequestContext) -> None:
        self._s = session
        self._graph = graph
        self._ctx = ctx
        self._audit = AuditService(session, ctx)

    # --- orchestration ---------------------------------------------------------
    def run(self, case_id: str) -> LinkSummary:
        """Resolve entities, link claims to evidence and rebuild the graph. Safe to repeat."""
        self._case(case_id)
        resolution = compute_resolution(self._s, case_id)
        sync_matches(self._s, self._audit, case_id, resolution)

        facts = load_fact_views(self._s, case_id)
        claims = self._active_claims(case_id)
        proposals = propose_links(
            [ClaimView(c.id, c.claim_type, c.declared_amount, c.currency, c.description) for c in claims],
            facts,
            resolution,
        )
        created, updated, removed = self._persist_links(case_id, proposals, {c.id for c in claims})
        self._s.flush()

        graph_counts: dict[str, int] = {}
        try:
            graph_counts = GraphProjectionService(self._s, self._graph).project_case(case_id, resolution)
            self._audit.record(
                action="graph.updated", entity_type="case", entity_id=case_id, case_id=case_id, new=graph_counts
            )
        except Exception as exc:
            # The relational store stays authoritative; the graph is rebuilt on the next run.
            log.warning("graph_projection_failed", error_type=type(exc).__name__)

        matches = list(self._s.scalars(select(EntityMatchRow).where(EntityMatchRow.case_id == case_id)))
        case = self._s.get(OnboardingCaseRow, case_id)
        case.updated_at = utcnow()
        self._s.commit()
        return LinkSummary(
            entities=len(resolution.entities),
            matches_auto_accepted=sum(m.status == AUTO for m in matches),
            matches_pending=sum(m.status == PENDING for m in matches),
            evidence_created=created,
            evidence_updated=updated,
            evidence_removed=removed,
            graph=graph_counts,
        )

    def _persist_links(self, case_id: str, proposals, active_claim_ids: set[str]) -> tuple[int, int, int]:
        existing = {
            (e.claim_id, e.fact_id): e
            for e in self._s.scalars(select(EvidenceRow).where(EvidenceRow.case_id == case_id))
        }
        wanted = {(p.claim_id, p.fact_id): p for p in proposals}
        created = updated = removed = 0
        for key, p in wanted.items():
            row = existing.get(key)
            if row is None:
                row = EvidenceRow(
                    case_id=case_id, claim_id=p.claim_id, fact_id=p.fact_id, relation=p.relation,
                    rationale=p.rationale, confidence=p.confidence, link_method="RULE",
                )
                self._s.add(row)
                self._s.flush()
                created += 1
                self._audit.record(
                    action="evidence.linked", entity_type="evidence", entity_id=row.id, case_id=case_id,
                    new={"claim_id": p.claim_id, "fact_id": p.fact_id, "relation": p.relation},
                )
            elif row.link_method == "RULE" and (row.relation, row.rationale) != (p.relation, p.rationale):
                previous = {"relation": row.relation}
                row.relation, row.rationale, row.confidence = p.relation, p.rationale, p.confidence
                updated += 1
                self._audit.record(
                    action="evidence.relinked", entity_type="evidence", entity_id=row.id, case_id=case_id,
                    previous=previous, new={"relation": p.relation},
                )
        for key, row in existing.items():
            if key not in wanted and row.link_method == "RULE" and row.claim_id in active_claim_ids:
                self._audit.record(
                    action="evidence.unlinked", entity_type="evidence", entity_id=row.id, case_id=case_id,
                    previous={"claim_id": row.claim_id, "fact_id": row.fact_id, "relation": row.relation},
                    reason="No longer supported by the current facts and rules",
                )
                self._s.delete(row)
                removed += 1
        return created, updated, removed

    # --- analyst decisions on entity matches ---------------------------------------
    def list_matches(self, case_id: str) -> list[EntityMatchRow]:
        self._case(case_id)
        return list(
            self._s.scalars(
                select(EntityMatchRow)
                .where(EntityMatchRow.case_id == case_id)
                .order_by(EntityMatchRow.status.desc(), EntityMatchRow.entity_kind, EntityMatchRow.created_at)
            )
        )

    def decide_match(self, match_id: str, decision: str, reason: str) -> EntityMatchRow:
        row = self._s.get(EntityMatchRow, match_id)
        if row is None:
            raise NotFoundError("Entity match not found")
        authorize_case_access(self._ctx, row.case_id)
        if row.status == AUTO:
            raise ConflictError("Automatic matches are decided by rule and cannot be overridden here")
        status = CONFIRMED if decision == "CONFIRM" else REJECTED
        previous = row.status
        mark_decision(row, status, self._ctx.actor_id, reason)
        self._audit.record(
            action="entity_match.decided", entity_type="entity_match", entity_id=row.id, case_id=row.case_id,
            previous={"status": previous}, new={"status": status}, reason=reason,
        )
        self._s.commit()
        self.run(row.case_id)
        self._s.refresh(row)
        return row

    # --- reads ---------------------------------------------------------------------------
    def list_evidence(self, case_id: str) -> list[dict]:
        self._case(case_id)
        rows = self._s.execute(
            select(EvidenceRow, CustomerClaimRow, ExtractedFactRow, DocumentRow.filename)
            .join(CustomerClaimRow, CustomerClaimRow.id == EvidenceRow.claim_id)
            .join(ExtractedFactRow, ExtractedFactRow.id == EvidenceRow.fact_id)
            .join(DocumentRow, DocumentRow.id == ExtractedFactRow.document_id)
            .where(
                EvidenceRow.case_id == case_id,
                CustomerClaimRow.verification_status != VerificationStatus.SUPERSEDED.value,
            )
            .order_by(CustomerClaimRow.claim_type, EvidenceRow.relation, ExtractedFactRow.page_number)
        ).all()
        return [
            {
                "id": e.id,
                "claim_id": c.id,
                "claim_type": c.claim_type,
                "claim_description": c.description,
                "claim_declared_amount": c.declared_amount,
                "currency": c.currency,
                "fact_id": f.id,
                "fact_type": f.fact_type,
                "fact_amount": f.amount,
                "fact_verification_status": f.verification_status,
                "document_id": f.document_id,
                "document_filename": name,
                "page_number": f.page_number,
                "source_text": f.source_text,
                "relation": e.relation,
                "rationale": e.rationale,
                "confidence": e.confidence,
                "link_method": e.link_method,
            }
            for e, c, f, name in rows
        ]

    def get_graph(self, case_id: str) -> tuple[list[GraphNode], list[GraphEdge]]:
        self._case(case_id)
        return self._graph.get_case_subgraph(case_id)

    def sale_proceeds(self, case_id: str) -> list[SaleProceeds]:
        """Sale consideration vs observed bank credits tied to the sale (first reconciliation check)."""
        self._case(case_id)
        resolution: Resolution = compute_resolution(self._s, case_id)
        facts = {f.id: f for f in load_fact_views(self._s, case_id)}
        transactions = {e.id: e for e in resolution.of_kind(TRANSACTION)}
        linked_claims = self._claims_linked_to_events(case_id)
        results = []
        for event in resolution.of_kind(EVENT):
            if event.attrs.get("event_type") != "COMPANY_SALE":
                continue
            considerations = sorted(
                (facts[i] for i in event.fact_ids if i in facts and facts[i].fact_type == "SALE_CONSIDERATION"),
                key=lambda f: -f.confidence,
            )
            if not considerations:
                continue
            credits, duplicates = [], []
            for rel in resolution.relations:
                txn = transactions.get(rel.target)
                if rel.source != event.id or rel.type != "GENERATED" or txn is None:
                    continue
                if txn.attrs.get("direction") != "CREDIT":
                    continue
                txn_facts = sorted((facts[i] for i in txn.fact_ids if i in facts), key=lambda f: -f.confidence)
                if txn_facts:  # one fact per transaction: the same credit in two statements counts once
                    credits.append(txn_facts[0])
                    duplicates.extend(txn_facts[1:])
            try:
                calc = sale_proceeds_difference(
                    considerations[0], credits, excluded=tuple(f.id for f in duplicates)
                )
            except ValueError as exc:  # e.g. mixed currencies: surface as needing review, never guess
                log.warning("sale_proceeds_unavailable", reason=str(exc))
                continue
            results.append(
                SaleProceeds(
                    event_id=event.id,
                    reference=event.attrs.get("reference"),
                    event_date=event.attrs.get("date"),
                    consideration=considerations[0],
                    credits=credits,
                    duplicate_credit_facts=duplicates,
                    calculation=calc,
                    status=self._proceeds_status(calc.result, bool(credits)),
                    linked_claim_ids=linked_claims,
                )
            )
        return results

    @staticmethod
    def _proceeds_status(difference: Decimal, has_credits: bool) -> str:
        if not has_credits:
            return "NO_PROCEEDS_OBSERVED"
        if difference == 0:
            return "RECONCILED"
        return "UNEXPLAINED_DIFFERENCE" if difference > 0 else "EXCESS_RECEIVED"

    def _claims_linked_to_events(self, case_id: str) -> list[str]:
        return sorted(
            {
                e["claim_id"]
                for e in self.list_evidence(case_id)
                if e["claim_type"] in ("SOURCE_OF_WEALTH", "SOURCE_OF_FUNDS")
            }
        )

    # --- helpers -----------------------------------------------------------------------------
    def _active_claims(self, case_id: str) -> list[CustomerClaimRow]:
        return list(
            self._s.scalars(
                select(CustomerClaimRow).where(
                    CustomerClaimRow.case_id == case_id,
                    CustomerClaimRow.verification_status != VerificationStatus.SUPERSEDED.value,
                )
            )
        )

    def _case(self, case_id: str) -> OnboardingCaseRow:
        authorize_case_access(self._ctx, case_id)
        case = self._s.get(OnboardingCaseRow, case_id)
        if case is None:
            raise NotFoundError("Case not found")
        return case
