"""Runs the reconciliation engine and persists its results, claim statuses, conflicts and requests."""
from datetime import date
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.persistence.models import (
    ConflictRow,
    CustomerClaimRow,
    DocumentRow,
    EvidenceRequirementRow,
    OnboardingCaseRow,
    ReconciliationRunRow,
    utcnow,
)
from app.domain.case_status import case_status_after_reconciliation
from app.domain.enums import ConflictStatus, VerificationStatus
from app.domain.reconciliation.engine import reconcile
from app.domain.reconciliation.policy import ReconciliationPolicy
from app.domain.reconciliation.state import ReconClaim, ReconciliationResult
from app.ports.graph import GraphRepository
from app.services.audit import AuditService
from app.services.context import RequestContext, authorize_case_access
from app.services.errors import NotFoundError
from app.services.graph_projection import GraphProjectionService
from app.services.reconciliation_codec import result_hash, result_to_dict
from app.services.resolution import compute_resolution, load_fact_views

log = structlog.get_logger()

# Statuses the engine may overwrite. Analyst decisions (ANALYST_*) are never touched.
ENGINE_OWNED = {
    VerificationStatus.DECLARED.value,
    VerificationStatus.UNVERIFIED.value,
    VerificationStatus.PARTIALLY_VERIFIED.value,
    VerificationStatus.VERIFIED.value,
    VerificationStatus.CONTRADICTED.value,
    VerificationStatus.STALE.value,
}
OPEN, RESOLVED = ConflictStatus.OPEN.value, ConflictStatus.RESOLVED.value
REQ_OPEN, REQ_CANCELLED = "OPEN", "CANCELLED"


class ReconciliationService:
    def __init__(
        self,
        session: Session,
        graph: GraphRepository,
        ctx: RequestContext,
        policy: ReconciliationPolicy,
        as_of: date | None = None,
    ) -> None:
        self._s = session
        self._graph = graph
        self._ctx = ctx
        self._policy = policy
        self._as_of = as_of
        self._audit = AuditService(session, ctx)

    # --- run -----------------------------------------------------------------
    def run(self, case_id: str) -> dict[str, Any]:
        case = self._case(case_id)
        claim_rows = list(
            self._s.scalars(
                select(CustomerClaimRow)
                .where(
                    CustomerClaimRow.case_id == case_id,
                    CustomerClaimRow.verification_status != VerificationStatus.SUPERSEDED.value,
                )
                .order_by(CustomerClaimRow.created_at, CustomerClaimRow.id)
            )
        )
        claims = [
            ReconClaim(c.id, c.claim_type, c.declared_amount, c.currency, c.description, c.materiality)
            for c in claim_rows
        ]
        resolution = compute_resolution(self._s, case_id)
        result = reconcile(
            case_id=case_id,
            customer_id=case.customer_id,
            claims=claims,
            facts=load_fact_views(self._s, case_id),
            resolution=resolution,
            policy=self._policy,
            as_of=self._as_of or date.today(),
        )

        self._update_claim_statuses(case_id, claim_rows, result)
        conflicts = self._sync_conflicts(case_id, result)
        self._sync_requirements(case_id, result, conflicts)

        data = result_to_dict(result)
        digest = result_hash(
            data,
            [f"{c.key}|{c.severity}" for c in result.conflicts],
            [r.key for r in result.requirements],
        )
        latest = self._latest_row(case_id)
        if latest is None or latest.result_hash != digest:
            latest = ReconciliationRunRow(
                case_id=case_id, as_of=result.as_of, result_hash=digest, result=data, created_by=self._ctx.actor_id
            )
            self._s.add(latest)
            self._s.flush()
            self._audit.record(
                action="reconciliation.completed",
                entity_type="reconciliation_run",
                entity_id=latest.id,
                case_id=case_id,
                new={
                    "net_worth": result.summary["net_worth"],
                    "net_worth_difference": result.summary["net_worth_difference"],
                    "evidence_coverage_pct": result.summary["evidence_coverage_pct"],
                    "conflicts_by_severity": result.summary["conflicts_by_severity"],
                    "as_of": result.as_of.isoformat(),
                },
            )

        self._update_case_status(case)
        self._s.flush()
        try:
            GraphProjectionService(self._s, self._graph).project_case(case_id, resolution)
        except Exception as exc:
            log.warning("graph_projection_failed", error_type=type(exc).__name__)
        self._s.commit()
        return self._payload(latest)

    # --- persistence steps -------------------------------------------------------
    def _update_claim_statuses(self, case_id: str, rows: list[CustomerClaimRow], result: ReconciliationResult) -> None:
        by_id = {r.claim_id: r for r in result.claims}
        for row in rows:
            r = by_id.get(row.id)
            if r is None or row.verification_status not in ENGINE_OWNED or row.verification_status == r.status:
                continue
            previous = row.verification_status
            row.verification_status = r.status
            self._audit.record(
                action="claim.reconciled",
                entity_type="claim",
                entity_id=row.id,
                case_id=case_id,
                previous={"verification_status": previous},
                new={
                    "verification_status": r.status,
                    "evidence_backed_amount": str(r.evidence_backed_amount),
                    "difference": str(r.difference) if r.difference is not None else None,
                },
                reason=f"{r.rule_id}: {r.explanation}",
            )

    def _sync_conflicts(self, case_id: str, result: ReconciliationResult) -> dict[str, ConflictRow]:
        existing = {
            c.conflict_key: c
            for c in self._s.scalars(select(ConflictRow).where(ConflictRow.case_id == case_id))
            if c.conflict_key
        }
        current: dict[str, ConflictRow] = {}
        wanted = {c.key for c in result.conflicts}
        for draft in result.conflicts:
            details = {**draft.details, "claim_ids": draft.claim_ids, "fact_ids": draft.fact_ids}
            row = existing.get(draft.key)
            if row is None:
                row = ConflictRow(
                    case_id=case_id, conflict_key=draft.key, conflict_type=draft.rule_id, severity=draft.severity,
                    status=OPEN, rule_id=draft.rule_id, description=draft.description, details=details,
                )
                self._s.add(row)
                self._s.flush()
                self._audit.record(
                    action="conflict.created", entity_type="conflict", entity_id=row.id, case_id=case_id,
                    new={"rule_id": draft.rule_id, "severity": draft.severity},
                )
            else:
                reopened = row.status == RESOLVED and row.details.get("auto_resolved")
                changed = (row.severity, row.description) != (draft.severity, draft.description)
                if reopened or (row.status == OPEN and changed):
                    previous = {"severity": row.severity, "status": row.status}
                    row.severity, row.description, row.details = draft.severity, draft.description, details
                    if reopened:
                        row.status = OPEN
                    self._audit.record(
                        action="conflict.reopened" if reopened else "conflict.updated",
                        entity_type="conflict", entity_id=row.id, case_id=case_id,
                        previous=previous, new={"severity": draft.severity, "status": row.status},
                    )
            current[draft.key] = row
        for key, row in existing.items():
            if key not in wanted and row.status == OPEN:
                row.status = RESOLVED
                row.details = {**row.details, "auto_resolved": True}
                self._audit.record(
                    action="conflict.auto_resolved", entity_type="conflict", entity_id=row.id, case_id=case_id,
                    previous={"status": OPEN}, new={"status": RESOLVED},
                    reason="No longer detected after reprocessing",
                )
        self._s.flush()
        return current

    def _sync_requirements(self, case_id: str, result: ReconciliationResult, conflicts: dict[str, ConflictRow]) -> None:
        existing = {
            r.requirement_key: r
            for r in self._s.scalars(select(EvidenceRequirementRow).where(EvidenceRequirementRow.case_id == case_id))
            if r.requirement_key
        }
        wanted = {r.key for r in result.requirements}
        for draft in result.requirements:
            conflict = conflicts.get(draft.conflict_key)
            row = existing.get(draft.key)
            if row is None:
                row = EvidenceRequirementRow(
                    case_id=case_id, requirement_key=draft.key, claim_id=draft.claim_id,
                    conflict_id=conflict.id if conflict else None, audience=draft.audience,
                    priority=draft.priority, status=REQ_OPEN, request_text=draft.request_text, details=draft.details,
                )
                self._s.add(row)
                self._s.flush()
                self._audit.record(
                    action="evidence_requirement.created", entity_type="evidence_requirement", entity_id=row.id,
                    case_id=case_id, new={"audience": draft.audience, "priority": draft.priority},
                )
            elif row.status in (REQ_OPEN, REQ_CANCELLED) and (row.request_text, row.priority) != (draft.request_text, draft.priority):
                row.request_text, row.priority, row.details = draft.request_text, draft.priority, draft.details
                if row.status == REQ_CANCELLED:
                    row.status = REQ_OPEN
            elif row.status == REQ_CANCELLED:
                row.status = REQ_OPEN
        for key, row in existing.items():
            if key not in wanted and row.status == REQ_OPEN:
                row.status = REQ_CANCELLED
                self._audit.record(
                    action="evidence_requirement.cancelled", entity_type="evidence_requirement", entity_id=row.id,
                    case_id=case_id, reason="The underlying conflict is no longer detected",
                )
        self._s.flush()

    def _update_case_status(self, case: OnboardingCaseRow) -> None:
        doc_statuses = self._s.scalars(select(DocumentRow.processing_status).where(DocumentRow.case_id == case.id)).all()
        open_reqs = [
            (r.audience, r.priority)
            for r in self._s.scalars(
                select(EvidenceRequirementRow).where(
                    EvidenceRequirementRow.case_id == case.id, EvidenceRequirementRow.status == REQ_OPEN
                )
            )
        ]
        new_status = case_status_after_reconciliation(case.status, doc_statuses, open_reqs)
        if new_status != case.status:
            self._audit.record(
                action="case.status_changed", entity_type="case", entity_id=case.id, case_id=case.id,
                previous={"status": case.status}, new={"status": new_status},
                reason="Derived from reconciliation results; the onboarding decision remains with the analyst",
            )
            case.status = new_status
        case.updated_at = utcnow()

    # --- reads ---------------------------------------------------------------------
    def latest(self, case_id: str) -> dict[str, Any]:
        self._case(case_id)
        row = self._latest_row(case_id)
        if row is None:
            raise NotFoundError("No reconciliation has been run for this case")
        return self._payload(row)

    def list_conflicts(self, case_id: str, status: str | None = None, severity: str | None = None) -> list[ConflictRow]:
        self._case(case_id)
        query = select(ConflictRow).where(ConflictRow.case_id == case_id)
        if status:
            query = query.where(ConflictRow.status == status)
        if severity:
            query = query.where(ConflictRow.severity == severity)
        rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "INFORMATIONAL": 3}
        rows = list(self._s.scalars(query.order_by(ConflictRow.created_at, ConflictRow.id)))
        return sorted(rows, key=lambda c: (rank.get(c.severity, 9), c.created_at))

    def list_requirements(self, case_id: str, status: str | None = None) -> list[EvidenceRequirementRow]:
        self._case(case_id)
        query = select(EvidenceRequirementRow).where(EvidenceRequirementRow.case_id == case_id)
        if status:
            query = query.where(EvidenceRequirementRow.status == status)
        rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        rows = list(self._s.scalars(query.order_by(EvidenceRequirementRow.created_at, EvidenceRequirementRow.id)))
        return sorted(rows, key=lambda r: (rank.get(r.priority, 9), r.created_at))

    def _payload(self, row: ReconciliationRunRow) -> dict[str, Any]:
        return {"run_id": row.id, "created_by": row.created_by, **row.result}

    def _latest_row(self, case_id: str) -> ReconciliationRunRow | None:
        return self._s.scalars(
            select(ReconciliationRunRow)
            .where(ReconciliationRunRow.case_id == case_id)
            .order_by(ReconciliationRunRow.calculated_at.desc(), ReconciliationRunRow.id)
            .limit(1)
        ).first()

    def _case(self, case_id: str) -> OnboardingCaseRow:
        authorize_case_access(self._ctx, case_id)
        case = self._s.get(OnboardingCaseRow, case_id)
        if case is None:
            raise NotFoundError("Case not found")
        return case
