"""Data structures shared by the reconciliation engine, conflict detection and requirements."""
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.domain.entity_resolution import Entity, MatchRecord, Resolution
from app.domain.facts import FactView
from app.domain.reconciliation.calculations import CalculationResult
from app.domain.reconciliation.policy import ReconciliationPolicy


@dataclass(frozen=True)
class ReconClaim:
    id: str
    claim_type: str
    amount: Decimal | None
    currency: str
    description: str
    materiality: str


@dataclass(frozen=True)
class Component:
    """One evidence-backed contribution to a total (bank balance, holding, loan, sale proceeds)."""

    kind: str
    label: str
    amount: Decimal
    currency: str
    value_date: date | None
    age_days: int | None
    fact_ids: tuple[str, ...]
    entity_id: str | None = None


@dataclass(frozen=True)
class Exclusion:
    fact_id: str
    kind: str
    reason: str  # STALE | DUPLICATE_RESOLVED | DUPLICATE_UNRESOLVED | OLDER_VALUE | OWNER_NOT_CUSTOMER | CURRENCY_MISMATCH
    amount: Decimal | None
    detail: str = ""


@dataclass
class ClaimResult:
    claim_id: str
    claim_type: str
    description: str
    materiality: str
    currency: str
    declared_amount: Decimal | None
    evidence_backed_amount: Decimal
    supported_amount: Decimal
    difference: Decimal | None  # declared - evidence_backed; positive means not evidenced
    status: str
    rule_id: str
    explanation: str
    input_fact_ids: list[str] = field(default_factory=list)
    excluded_fact_ids: list[str] = field(default_factory=list)


@dataclass
class SaleCheck:
    event_id: str
    reference: str | None
    event_date: str | None
    consideration: FactView
    credits: list[FactView]
    duplicate_credits: list[FactView]
    calculation: CalculationResult
    status: str


@dataclass
class ConflictDraft:
    key: str
    rule_id: str
    severity: str
    description: str
    claim_ids: list[str] = field(default_factory=list)
    fact_ids: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class RequirementDraft:
    key: str
    conflict_key: str
    claim_id: str | None
    audience: str  # CUSTOMER | ANALYST
    priority: str
    request_text: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReconState:
    """Everything the engine derived; conflict and requirement rules read it."""

    case_id: str
    customer_id: str
    currency: str
    as_of: date
    policy: ReconciliationPolicy
    facts: dict[str, FactView]
    resolution: Resolution
    claims: list[ClaimResult] = field(default_factory=list)
    components: list[Component] = field(default_factory=list)
    exclusions: list[Exclusion] = field(default_factory=list)
    sale_checks: list[SaleCheck] = field(default_factory=list)
    resolved_duplicates: list[tuple[Entity, FactView, list[FactView]]] = field(default_factory=list)
    unresolved_duplicates: list[tuple[Entity, list[FactView]]] = field(default_factory=list)
    different_values: list[tuple[Entity, list[FactView]]] = field(default_factory=list)
    owner_mismatches: list[tuple[Entity, str, list[FactView]]] = field(default_factory=list)
    pending_person_matches: list[MatchRecord] = field(default_factory=list)
    portfolio_mismatches: list[tuple[str, str, FactView, Decimal]] = field(default_factory=list)
    stale_facts: list[tuple[FactView, str, int, int]] = field(default_factory=list)  # fact, kind, age, limit
    stale_entity_values: list[tuple[str, Decimal]] = field(default_factory=list)  # one value per fully stale entity
    unlinked: list[FactView] = field(default_factory=list)
    bank_total: Decimal = Decimal("0")
    investment_total: Decimal = Decimal("0")
    liability_total: Decimal = Decimal("0")
    observed_sale_proceeds: Decimal = Decimal("0")


@dataclass
class ReconciliationResult:
    case_id: str
    as_of: date
    currency: str
    calculated_at: datetime
    calculations: dict[str, CalculationResult]
    components: list[Component]
    exclusions: list[Exclusion]
    claims: list[ClaimResult]
    sale_checks: list[SaleCheck]
    conflicts: list[ConflictDraft]
    requirements: list[RequirementDraft]
    evidence_coverage_pct: Decimal | None
    summary: dict[str, Any]
