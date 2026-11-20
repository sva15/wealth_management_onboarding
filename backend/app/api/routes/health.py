"""Health endpoints: liveness and readiness (SQLite + graph)."""
from fastapi import APIRouter, Request, Response
from sqlalchemy import text

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready(request: Request, response: Response) -> dict:
    checks: dict[str, str] = {}

    try:
        with request.app.state.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unavailable"

    checks["graph"] = "ok" if request.app.state.graph.ping() else "unavailable"

    all_ok = all(v == "ok" for v in checks.values())
    if not all_ok:
        response.status_code = 503
    return {
        "status": "ok" if all_ok else "degraded",
        "checks": checks,
        "graph_backend": request.app.state.settings.graph_backend,
        "llm_mode": "mock" if request.app.state.settings.use_mock_bedrock else "bedrock",
    }
