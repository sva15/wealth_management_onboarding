"""Customer, onboarding-case and declaration use cases."""
from decimal import Decimal

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.persistence.models import (
    CustomerClaimRow,
    CustomerRow,
    DeclarationRow,
    OnboardingCaseRow,
    utcnow,
)
from app.domain.customer import CustomerInput
from app.domain.declaration import DeclarationInput, build_claim_drafts
from app.domain.enums import CaseStatus, VerificationStatus
from app.ports.graph import GraphRepository
from app.services.audit import AuditService
from app.services.context import RequestContext, authorize_case_access
from app.services.errors import NotFoundError
from app.services.graph_projection import GraphProjectionService

log = structlog.get_logger()


class CaseService:
    def __init__(
        self,
        session: Session,
        graph: GraphRepository,
        ctx: RequestContext,
        materiality_threshold_pct: Decimal = Decimal("5"),
    ) -> None:
        self._s = session
        self._graph = graph
        self._ctx = ctx
        self._audit = AuditService(session, ctx)
        self._threshold = materiality_threshold_pct

    # --- customers -------------------------------------------------------
    def create_customer(self, data: CustomerInput, customer_id: str | None = None) -> CustomerRow:
        row = CustomerRow(**data.model_dump())
        if customer_id:
            row.id = customer_id
        self._s.add(row)
        self._s.flush()
        # PAN and other personal data are deliberately not written to the audit payload.
        self._audit.record(action="customer.created", entity_type="customer", entity_id=row.id)
        self._s.commit()
        return row

    def get_customer(self, customer_id: str) -> CustomerRow:
        row = self._s.get(CustomerRow, customer_id)
        if row is None:
            raise NotFoundError("Customer not found")
        return row

    # --- cases -----------------------------------------------------------
    def create_case(self, customer_id: str, case_id: str | None = None) -> OnboardingCaseRow:
        self.get_customer(customer_id)
        case = OnboardingCaseRow(
            customer_id=customer_id, status=CaseStatus.AWAITING_DOCUMENTS.value
        )
        if case_id:
            case.id = case_id
        self._s.add(case)
        self._s.flush()
        self._audit.record(
            action="case.created",
            entity_type="case",
            entity_id=case.id,
            case_id=case.id,
            new={"status": case.status},
        )
        self._s.commit()
        return case

    def get_case(self, case_id: str) -> OnboardingCaseRow:
        authorize_case_access(self._ctx, case_id)
        case = self._s.get(OnboardingCaseRow, case_id)
        if case is None:
            raise NotFoundError("Case not found")
        return case

    def list_cases(
        self, limit: int, offset: int, status: str | None = None
    ) -> tuple[list[tuple[OnboardingCaseRow, str]], int]:
        query = select(OnboardingCaseRow, CustomerRow.full_name).join(
            CustomerRow, CustomerRow.id == OnboardingCaseRow.customer_id
        )
        if status:
            query = query.where(OnboardingCaseRow.status == status)
        total = self._s.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = self._s.execute(
            query.order_by(OnboardingCaseRow.updated_at.desc(), OnboardingCaseRow.id)
            .limit(limit)
            .offset(offset)
        ).all()
        return [(case, name) for case, name in rows], total

    def customer_name(self, case: OnboardingCaseRow) -> str:
        return self.get_customer(case.customer_id).full_name

    def dashboard_summary(self, recent: int = 5) -> dict:
        counts = dict(
            self._s.execute(
                select(OnboardingCaseRow.status, func.count()).group_by(OnboardingCaseRow.status)
            ).all()
        )
        recent_cases, _ = self.list_cases(limit=recent, offset=0)
        return {
            "total_cases": sum(counts.values()),
            "requires_review": counts.get(CaseStatus.REQUIRES_REVIEW.value, 0),
            "awaiting_customer_evidence": counts.get(
                CaseStatus.AWAITING_CUSTOMER_EVIDENCE.value, 0
            ),
            "extraction_failures": counts.get(CaseStatus.EXTRACTION_FAILED.value, 0),
            "by_status": counts,
            "recent_cases": recent_cases,
        }

    # --- declarations and claims ----------------------------------------
    def add_declaration(
        self, case_id: str, decl: DeclarationInput
    ) -> tuple[DeclarationRow, list[CustomerClaimRow]]:
        case = self.get_case(case_id)

        declaration = DeclarationRow(
            case_id=case.id,
            payload=decl.model_dump(mode="json"),
            created_by=self._ctx.actor_id,
        )
        self._s.add(declaration)
        self._s.flush()
        self._audit.record(
            action="declaration.created",
            entity_type="declaration",
            entity_id=declaration.id,
            case_id=case.id,
        )

        self._supersede_active_claims(case.id)

        claims = []
        for draft in build_claim_drafts(decl, self._threshold):
            claim = CustomerClaimRow(
                customer_id=case.customer_id,
                case_id=case.id,
                declaration_id=declaration.id,
                claim_type=draft.claim_type.value,
                declared_amount=draft.declared_amount,
                currency=draft.currency,
                effective_date=draft.effective_date,
                description=draft.description,
                materiality=draft.materiality.value,
                verification_status=VerificationStatus.DECLARED.value,
            )
            self._s.add(claim)
            self._s.flush()
            self._audit.record(
                action="claim.created",
                entity_type="claim",
                entity_id=claim.id,
                case_id=case.id,
                new={
                    "claim_type": claim.claim_type,
                    "declared_amount": str(claim.declared_amount)
                    if claim.declared_amount is not None
                    else None,
                    "verification_status": claim.verification_status,
                },
            )
            claims.append(claim)

        case.updated_at = utcnow()
        self._s.commit()
        self._project_to_graph(case.id)
        return declaration, claims

    def list_claims(
        self, case_id: str, include_superseded: bool = False
    ) -> list[CustomerClaimRow]:
        self.get_case(case_id)
        query = select(CustomerClaimRow).where(CustomerClaimRow.case_id == case_id)
        if not include_superseded:
            query = query.where(
                CustomerClaimRow.verification_status != VerificationStatus.SUPERSEDED.value
            )
        return list(self._s.scalars(query.order_by(CustomerClaimRow.created_at, CustomerClaimRow.id)))

    def latest_declaration(self, case_id: str) -> DeclarationRow | None:
        return self._s.scalars(
            select(DeclarationRow)
            .where(DeclarationRow.case_id == case_id)
            .order_by(DeclarationRow.created_at.desc(), DeclarationRow.id)
            .limit(1)
        ).first()

    def _supersede_active_claims(self, case_id: str) -> list[CustomerClaimRow]:
        active = self.list_claims(case_id)
        for claim in active:
            previous = claim.verification_status
            claim.verification_status = VerificationStatus.SUPERSEDED.value
            self._audit.record(
                action="claim.superseded",
                entity_type="claim",
                entity_id=claim.id,
                case_id=case_id,
                previous={"verification_status": previous},
                new={"verification_status": claim.verification_status},
                reason="Replaced by a newer customer declaration",
            )
        return active

    def _project_to_graph(self, case_id: str) -> None:
        """Best-effort projection; the relational store remains the system of record."""
        try:
            GraphProjectionService(self._s, self._graph).project_case(case_id)
        except Exception as exc:
            log.warning("graph_projection_failed", error_type=type(exc).__name__)
