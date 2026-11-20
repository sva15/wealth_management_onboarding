"""Request context: actor identity, role and correlation ID.

Authentication is a placeholder: the actor comes from headers and defaults to a local analyst.
Replace `get_context` with real token validation later.
"""
from dataclasses import dataclass

from app.services.errors import PermissionDeniedError


@dataclass(frozen=True)
class RequestContext:
    actor_id: str
    role: str
    correlation_id: str | None = None


def require_role(ctx: RequestContext, *allowed: str) -> None:
    if ctx.role not in allowed:
        raise PermissionDeniedError(f"Role '{ctx.role}' is not permitted to perform this action")


def authorize_case_access(ctx: RequestContext, case_id: str) -> None:
    """Placeholder for case-level authorization (e.g. customer may only see their own case)."""
    return None
