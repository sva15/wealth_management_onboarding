"""Customer declaration input and its translation into claims. Pure domain logic."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from app.domain.enums import AssetType, ClaimType, Materiality

Money = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=2)]
Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]

ALWAYS_MATERIAL = frozenset(
    {ClaimType.NET_WORTH, ClaimType.SOURCE_OF_WEALTH, ClaimType.SOURCE_OF_FUNDS}
)

_ASSET_CLAIM_TYPE = {
    AssetType.INVESTMENT: ClaimType.INVESTMENTS,
    AssetType.BANK_DEPOSIT: ClaimType.BANK_BALANCE,
    AssetType.PROPERTY: ClaimType.PROPERTY_OWNERSHIP,
    AssetType.BUSINESS: ClaimType.BUSINESS_OWNERSHIP,
    AssetType.OTHER: ClaimType.OTHER_ASSET,
}


class DeclaredAsset(BaseModel):
    asset_type: AssetType
    description: Text
    value: Money


class DeclaredLiability(BaseModel):
    description: Text
    amount: Money


class DeclarationInput(BaseModel):
    currency: Currency = "INR"
    effective_date: date = Field(default_factory=date.today)
    declared_net_worth: Money
    annual_income: Money | None = None
    source_of_wealth: Text
    source_of_wealth_amount: Money | None = None
    source_of_funds: Text
    intended_investment_amount: Money
    assets: list[DeclaredAsset] = Field(default_factory=list)
    liabilities: list[DeclaredLiability] = Field(default_factory=list)


@dataclass(frozen=True)
class ClaimDraft:
    claim_type: ClaimType
    declared_amount: Decimal | None
    currency: str
    effective_date: date
    description: str
    materiality: Materiality


def _materiality(
    claim_type: ClaimType, amount: Decimal | None, net_worth: Decimal, threshold_pct: Decimal
) -> Materiality:
    if claim_type in ALWAYS_MATERIAL:
        return Materiality.MATERIAL
    if amount is not None and net_worth > 0 and amount * 100 >= net_worth * threshold_pct:
        return Materiality.MATERIAL
    return Materiality.NON_MATERIAL


def build_claim_drafts(
    decl: DeclarationInput, materiality_threshold_pct: Decimal = Decimal("5")
) -> list[ClaimDraft]:
    """Turn a declaration into one claim per declared statement, without judging truth."""
    drafts: list[ClaimDraft] = []

    def add(claim_type: ClaimType, amount: Decimal | None, description: str) -> None:
        drafts.append(
            ClaimDraft(
                claim_type=claim_type,
                declared_amount=amount,
                currency=decl.currency,
                effective_date=decl.effective_date,
                description=description,
                materiality=_materiality(
                    claim_type, amount, decl.declared_net_worth, materiality_threshold_pct
                ),
            )
        )

    add(ClaimType.NET_WORTH, decl.declared_net_worth, "Declared total net worth")
    if decl.annual_income is not None:
        add(ClaimType.ANNUAL_INCOME, decl.annual_income, "Declared annual income")
    add(ClaimType.SOURCE_OF_WEALTH, decl.source_of_wealth_amount, decl.source_of_wealth)
    add(ClaimType.SOURCE_OF_FUNDS, decl.intended_investment_amount, decl.source_of_funds)
    for asset in decl.assets:
        add(_ASSET_CLAIM_TYPE[asset.asset_type], asset.value, asset.description)
    for liability in decl.liabilities:
        add(ClaimType.LIABILITY, liability.amount, liability.description)
    return drafts
