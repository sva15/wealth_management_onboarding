from decimal import Decimal

from app.domain.declaration import DeclarationInput, DeclaredAsset, build_claim_drafts
from app.domain.enums import AssetType, ClaimType, Materiality
from app.seed import demo_declaration


def test_demo_declaration_produces_expected_claims():
    drafts = build_claim_drafts(demo_declaration())
    types = [d.claim_type for d in drafts]
    assert types == [
        ClaimType.NET_WORTH,
        ClaimType.ANNUAL_INCOME,
        ClaimType.SOURCE_OF_WEALTH,
        ClaimType.SOURCE_OF_FUNDS,
        ClaimType.INVESTMENTS,
        ClaimType.BANK_BALANCE,
        ClaimType.PROPERTY_OWNERSHIP,
        ClaimType.LIABILITY,
    ]
    by_type = {d.claim_type: d for d in drafts}
    assert by_type[ClaimType.NET_WORTH].declared_amount == Decimal("80000000")
    assert by_type[ClaimType.SOURCE_OF_WEALTH].declared_amount == Decimal("52000000")
    assert by_type[ClaimType.LIABILITY].declared_amount == Decimal("9000000")


def test_materiality_threshold_and_always_material():
    decl = DeclarationInput(
        declared_net_worth=Decimal("80000000"),
        source_of_wealth="Salary",
        source_of_funds="Savings",
        intended_investment_amount=Decimal("1"),
        assets=[
            DeclaredAsset(asset_type=AssetType.OTHER, description="Watch", value=Decimal("100000")),
            DeclaredAsset(asset_type=AssetType.OTHER, description="Art", value=Decimal("4000000")),
        ],
    )
    drafts = build_claim_drafts(decl, Decimal("5"))
    by_desc = {d.description: d for d in drafts}
    assert by_desc["Watch"].materiality == Materiality.NON_MATERIAL
    assert by_desc["Art"].materiality == Materiality.MATERIAL  # exactly 5% of net worth
    assert by_desc["Savings"].materiality == Materiality.MATERIAL  # source of funds, any amount
