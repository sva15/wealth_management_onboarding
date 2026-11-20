"""Seed the fictional demo case. Idempotent. Run: python -m app.seed"""
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import sessionmaker

from app.adapters.graph.factory import build_graph_repository
from app.adapters.persistence.database import build_engine, build_session_factory
from app.adapters.persistence.migrate import run_migrations
from app.adapters.persistence.models import OnboardingCaseRow
from app.config import Settings, get_settings
from app.domain.customer import CustomerInput
from app.domain.declaration import (
    DeclarationInput,
    DeclaredAsset,
    DeclaredLiability,
)
from app.domain.enums import AssetType
from app.ports.graph import GraphRepository
from app.services.cases import CaseService
from app.services.context import RequestContext

DEMO_CUSTOMER_ID = "demo-customer-001"
DEMO_CASE_ID = "demo-case-001"

CRORE = Decimal("10000000")
LAKH = Decimal("100000")


def demo_declaration() -> DeclarationInput:
    """Synthetic declaration. The undocumented property is sized so declared figures tie to ₹8 Cr."""
    return DeclarationInput(
        currency="INR",
        effective_date=date(2026, 3, 31),
        declared_net_worth=8 * CRORE,
        annual_income=Decimal("12000000"),
        source_of_wealth="Sale of a technology company",
        source_of_wealth_amount=Decimal("5.20") * CRORE,
        source_of_funds="Proceeds from the sale of a technology company",
        intended_investment_amount=3 * CRORE,
        assets=[
            DeclaredAsset(
                asset_type=AssetType.INVESTMENT,
                description="Mutual fund and equity portfolio",
                value=Decimal("1.70") * CRORE,
            ),
            DeclaredAsset(
                asset_type=AssetType.BANK_DEPOSIT,
                description="Bank deposits",
                value=Decimal("1.10") * CRORE,
            ),
            DeclaredAsset(
                asset_type=AssetType.PROPERTY,
                description="Residential property (no document submitted)",
                value=Decimal("6.10") * CRORE,
            ),
        ],
        liabilities=[
            DeclaredLiability(description="Outstanding loan", amount=90 * LAKH),
        ],
    )


def seed_demo(
    session_factory: sessionmaker, graph: GraphRepository, settings: Settings
) -> bool:
    """Create the demo customer, case and declaration. Returns False if already seeded."""
    with session_factory() as session:
        if session.get(OnboardingCaseRow, DEMO_CASE_ID) is not None:
            return False
        svc = CaseService(
            session,
            graph,
            RequestContext(actor_id="seed-script", role="admin"),
            settings.materiality_threshold_pct,
        )
        svc.create_customer(
            CustomerInput(full_name="Aarav Mehta", pan="ABCDE1234F", date_of_birth=date(1985, 6, 15)),
            customer_id=DEMO_CUSTOMER_ID,
        )
        svc.create_case(DEMO_CUSTOMER_ID, case_id=DEMO_CASE_ID)
        svc.add_declaration(DEMO_CASE_ID, demo_declaration())
        return True


def main() -> None:
    settings = get_settings()
    run_migrations(settings.database_url)
    engine = build_engine(settings.database_url)
    graph = build_graph_repository(settings)
    try:
        graph.ensure_schema()
        created = seed_demo(build_session_factory(engine), graph, settings)
    finally:
        graph.close()
        engine.dispose()
    print("Demo case seeded." if created else "Demo case already present; nothing to do.")


if __name__ == "__main__":
    main()
