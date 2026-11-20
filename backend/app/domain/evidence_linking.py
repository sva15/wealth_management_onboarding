"""Rule-based claim-to-evidence linking.

Declaration-form facts (DECLARED_*) are the customer's own statements and are never evidence.
Totals (balances, outstanding principal, portfolio total, tax total) are compared with the claim;
components (single holdings) can only partially support an aggregate claim. Anything ambiguous is
left unlinked or flagged for review instead of guessed. Candidate generation by a model can be added
later; links created here are tagged as RULE links.
"""
import re
from dataclasses import dataclass
from decimal import Decimal

from app.domain.entity_resolution import EVENT, TRANSACTION, Resolution
from app.domain.enums import ClaimType, EvidenceRelation
from app.domain.facts import FactView
from app.domain.money import format_inr

_TOTAL_FACT = {
    ClaimType.BANK_BALANCE.value: ("BANK_CLOSING_BALANCE", "Closing balance"),
    ClaimType.LIABILITY.value: ("LIABILITY_OUTSTANDING", "Outstanding principal"),
    ClaimType.INVESTMENTS.value: ("PORTFOLIO_TOTAL_VALUE", "Portfolio total"),
    ClaimType.ANNUAL_INCOME.value: ("TAX_TOTAL_INCOME", "Total income per tax summary"),
}
_COMPONENT_FACT = {ClaimType.INVESTMENTS.value: "PORTFOLIO_HOLDING"}
SALE_WORDS = re.compile(r"\b(sale|sold|sell|divest\w*|exit)\b", re.IGNORECASE)
_SOURCE_CLAIMS = {ClaimType.SOURCE_OF_WEALTH.value, ClaimType.SOURCE_OF_FUNDS.value}

SUPPORTS = EvidenceRelation.SUPPORTS.value
PARTIAL = EvidenceRelation.PARTIALLY_SUPPORTS.value
CONTRADICTS = EvidenceRelation.CONTRADICTS.value
REVIEW = EvidenceRelation.REQUIRES_REVIEW.value


@dataclass(frozen=True)
class ClaimView:
    id: str
    claim_type: str
    amount: Decimal | None
    currency: str
    description: str


@dataclass(frozen=True)
class LinkProposal:
    claim_id: str
    fact_id: str
    relation: str
    rationale: str
    confidence: float


def propose_links(
    claims: list[ClaimView],
    facts: list[FactView],
    resolution: Resolution,
    tolerance: Decimal = Decimal("0"),
) -> list[LinkProposal]:
    proposals: dict[tuple[str, str], LinkProposal] = {}
    by_id = {f.id: f for f in facts}

    def add(claim: ClaimView, fact: FactView, relation: str, rationale: str) -> None:
        proposals.setdefault(
            (claim.id, fact.id), LinkProposal(claim.id, fact.id, relation, rationale, fact.confidence)
        )

    def money(amount: Decimal, currency: str) -> str:
        return format_inr(amount, currency)

    # 1. totals compared with the declared amount
    for claim_type, (fact_type, label) in _TOTAL_FACT.items():
        typed = [c for c in claims if c.claim_type == claim_type and c.amount is not None]
        if not typed:
            continue
        for fact in (f for f in facts if f.fact_type == fact_type and f.amount is not None):
            claim = min(typed, key=lambda c: abs(c.amount - fact.amount))
            if fact.currency != claim.currency:
                add(claim, fact, REVIEW, f"{label} is in {fact.currency} but the claim is in {claim.currency}.")
                continue
            diff = abs(claim.amount - fact.amount)
            if diff <= tolerance:
                add(claim, fact, SUPPORTS, f"{label} {money(fact.amount, fact.currency)} matches the declared amount.")
            elif len(typed) == 1:
                add(claim, fact, CONTRADICTS,
                    f"{label} {money(fact.amount, fact.currency)} differs from the declared "
                    f"{money(claim.amount, claim.currency)} by {money(diff, fact.currency)}.")
            else:
                add(claim, fact, REVIEW,
                    f"{label} {money(fact.amount, fact.currency)} is closest to this claim but does not match; "
                    "several claims of this type exist.")

    # 2. components can only partially support an aggregate claim
    for claim_type, fact_type in _COMPONENT_FACT.items():
        typed = [c for c in claims if c.claim_type == claim_type and c.amount is not None]
        if len(typed) != 1:
            continue
        claim = typed[0]
        for fact in (f for f in facts if f.fact_type == fact_type and f.amount is not None):
            if fact.currency != claim.currency:
                add(claim, fact, REVIEW, "Currency differs from the claim.")
            elif fact.amount == claim.amount:
                add(claim, fact, SUPPORTS, f"Holding {money(fact.amount, fact.currency)} equals the declared amount.")
            elif fact.amount < claim.amount:
                add(claim, fact, PARTIAL,
                    f"Holding {money(fact.amount, fact.currency)} is one component of the declared "
                    f"{money(claim.amount, claim.currency)}.")
            else:
                add(claim, fact, CONTRADICTS,
                    f"Holding {money(fact.amount, fact.currency)} exceeds the declared {money(claim.amount, claim.currency)}.")

    # 3. company-sale events support sale-based source-of-wealth / source-of-funds claims
    sale_claims = [c for c in claims if c.claim_type in _SOURCE_CLAIMS and SALE_WORDS.search(c.description)]
    transactions = {e.id: e for e in resolution.of_kind(TRANSACTION)}
    for event in (e for e in resolution.of_kind(EVENT) if e.attrs.get("event_type") == "COMPANY_SALE"):
        considerations = [by_id[i] for i in event.fact_ids if i in by_id and by_id[i].fact_type == "SALE_CONSIDERATION"]
        credits = [
            transactions[r.target]
            for r in resolution.relations
            if r.source == event.id and r.type == "GENERATED" and r.target in transactions
            and transactions[r.target].attrs.get("direction") == "CREDIT"
        ]
        observed = sum((Decimal(t.attrs["amount"]) for t in credits), Decimal("0"))
        credit_currency = credits[0].attrs.get("currency") if credits else None

        for claim in sale_claims:
            declared = claim.amount
            for fact in considerations:
                if declared is None:
                    add(claim, fact, SUPPORTS, "The sale agreement documents the declared source.")
                elif fact.currency != claim.currency:
                    add(claim, fact, REVIEW, "Agreement currency differs from the claim.")
                elif claim.claim_type == ClaimType.SOURCE_OF_WEALTH.value:
                    if fact.amount == declared:
                        add(claim, fact, SUPPORTS, f"Agreement consideration {money(fact.amount, fact.currency)} matches the declared sale value.")
                    else:
                        add(claim, fact, CONTRADICTS,
                            f"Agreement consideration {money(fact.amount, fact.currency)} differs from the declared "
                            f"{money(declared, claim.currency)}.")
                elif fact.amount >= declared:
                    add(claim, fact, SUPPORTS, f"Agreement consideration {money(fact.amount, fact.currency)} covers the intended amount.")
                else:
                    add(claim, fact, PARTIAL, f"Agreement consideration {money(fact.amount, fact.currency)} is below the intended amount.")

            for txn in credits:
                for fact_id in txn.fact_ids:
                    fact = by_id.get(fact_id)
                    if fact is None:
                        continue
                    if declared is None:
                        add(claim, fact, SUPPORTS, "A bank credit referencing the sale agreement was received.")
                    elif credit_currency != claim.currency:
                        add(claim, fact, REVIEW, "Bank credit currency differs from the claim.")
                    elif observed >= declared:
                        add(claim, fact, SUPPORTS,
                            f"Bank credits tied to the sale total {money(observed, claim.currency)}, covering {money(declared, claim.currency)}.")
                    else:
                        add(claim, fact, PARTIAL,
                            f"Bank credits tied to the sale total {money(observed, claim.currency)} against "
                            f"{money(declared, claim.currency)}; {money(declared - observed, claim.currency)} is not evidenced.")
    return list(proposals.values())
