from app.adapters.graph.in_memory import InMemoryGraphRepository
from app.adapters.persistence.database import build_engine, build_session_factory
from app.adapters.persistence.migrate import run_migrations
from app.adapters.persistence.models import CustomerClaimRow
from app.seed import DEMO_CASE_ID, seed_demo


def test_seed_is_idempotent(settings):
    run_migrations(settings.database_url)
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    graph = InMemoryGraphRepository()

    assert seed_demo(factory, graph, settings) is True
    assert seed_demo(factory, graph, settings) is False

    with factory() as session:
        claims = session.query(CustomerClaimRow).filter_by(case_id=DEMO_CASE_ID).all()
    assert len(claims) == 8
    engine.dispose()
