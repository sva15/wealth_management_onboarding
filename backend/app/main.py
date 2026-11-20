"""FastAPI application factory."""
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.adapters.documents.local_parser import build_parser
from app.adapters.documents.local_store import LocalDocumentStore
from app.adapters.graph.factory import build_graph_repository
from app.adapters.llm.factory import build_llm_client
from app.adapters.persistence.database import build_engine, build_session_factory
from app.adapters.persistence.migrate import run_migrations
from app.api.errors import install_http_plumbing
from app.api.routes import cases, documents, evidence, extraction, health, reconciliation
from app.config import Settings, get_settings
from app.logging_config import configure_logging
from app.services.policy import load_policy


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    log = structlog.get_logger()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        if settings.auto_migrate:
            run_migrations(settings.database_url)
        app.state.engine = build_engine(settings.database_url)
        app.state.session_factory = build_session_factory(app.state.engine)
        app.state.graph = build_graph_repository(settings)
        app.state.document_store = LocalDocumentStore(settings.document_storage_dir)
        app.state.document_parser = build_parser(settings.document_processor_mode)
        app.state.llm = build_llm_client(settings)
        app.state.reconciliation_policy = load_policy(settings)
        try:
            app.state.graph.ensure_schema()
        except Exception as exc:
            # The server may be down at startup; /health/ready reports it.
            log.warning("graph_schema_init_failed", error_type=type(exc).__name__)
        yield
        app.state.graph.close()
        app.state.engine.dispose()

    app = FastAPI(title="Financial Truth Engine", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Correlation-ID"],
    )
    install_http_plumbing(app)
    app.include_router(health.router)
    app.include_router(cases.router)
    app.include_router(documents.router)
    app.include_router(extraction.router)
    app.include_router(evidence.router)
    app.include_router(reconciliation.router)
    return app


app = create_app()
