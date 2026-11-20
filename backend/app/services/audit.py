"""Append-only audit trail writer."""
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.persistence.models import AuditEventRow
from app.services.context import RequestContext


class AuditService:
    def __init__(self, session: Session, ctx: RequestContext) -> None:
        self._session = session
        self._ctx = ctx

    def record(
        self,
        *,
        action: str,
        entity_type: str,
        entity_id: str,
        case_id: str | None = None,
        previous: dict[str, Any] | None = None,
        new: dict[str, Any] | None = None,
        reason: str | None = None,
        workflow_run_id: str | None = None,
        model_version: str | None = None,
    ) -> AuditEventRow:
        event = AuditEventRow(
            case_id=case_id,
            actor=self._ctx.actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            previous_value=previous,
            new_value=new,
            reason=reason,
            workflow_run_id=workflow_run_id,
            model_version=model_version,
            correlation_id=self._ctx.correlation_id,
        )
        self._session.add(event)
        return event


def list_audit_events(
    session: Session, case_id: str, limit: int, offset: int
) -> tuple[list[AuditEventRow], int]:
    base = select(AuditEventRow).where(AuditEventRow.case_id == case_id)
    total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = session.scalars(
        base.order_by(AuditEventRow.created_at.desc(), AuditEventRow.id).limit(limit).offset(offset)
    ).all()
    return list(rows), total
