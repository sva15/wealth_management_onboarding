"""FastAPI dependencies: request context, DB session, services."""
from collections.abc import Iterator

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from app.domain.enums import Role
from app.services.cases import CaseService
from app.services.context import RequestContext
from app.services.documents import DocumentService
from app.services.evidence import EvidenceService
from app.services.extraction import ExtractionService
from app.services.reconciliation import ReconciliationService

VALID_ROLES = {r.value for r in Role}


def get_context(
    request: Request,
    x_actor_id: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
) -> RequestContext:
    """Placeholder identity from headers; defaults to a local analyst."""
    role = (x_actor_role or Role.ANALYST.value).lower()
    if role not in VALID_ROLES:
        role = Role.CUSTOMER.value
    return RequestContext(
        actor_id=x_actor_id or "local-analyst",
        role=role,
        correlation_id=getattr(request.state, "correlation_id", None),
    )


def get_session(request: Request) -> Iterator[Session]:
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def get_case_service(
    request: Request,
    session: Session = Depends(get_session),
    ctx: RequestContext = Depends(get_context),
) -> CaseService:
    return CaseService(
        session,
        request.app.state.graph,
        ctx,
        request.app.state.settings.materiality_threshold_pct,
    )


def get_document_service(
    request: Request,
    session: Session = Depends(get_session),
    ctx: RequestContext = Depends(get_context),
) -> DocumentService:
    settings = request.app.state.settings
    return DocumentService(
        session,
        ctx,
        request.app.state.document_store,
        request.app.state.document_parser,
        settings.max_upload_mb * 1024 * 1024,
        settings.classification_review_threshold,
        request.app.state.llm,
    )


def get_evidence_service(
    request: Request,
    session: Session = Depends(get_session),
    ctx: RequestContext = Depends(get_context),
) -> EvidenceService:
    return EvidenceService(session, request.app.state.graph, ctx)


def get_reconciliation_service(
    request: Request,
    session: Session = Depends(get_session),
    ctx: RequestContext = Depends(get_context),
) -> ReconciliationService:
    state = request.app.state
    return ReconciliationService(
        session, state.graph, ctx, state.reconciliation_policy, state.settings.reconciliation_as_of_date
    )


def get_extraction_service(
    request: Request,
    session: Session = Depends(get_session),
    ctx: RequestContext = Depends(get_context),
) -> ExtractionService:
    return ExtractionService(
        session,
        ctx,
        request.app.state.llm,
        request.app.state.settings.extraction_confidence_threshold,
    )
