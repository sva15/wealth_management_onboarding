"""Configurable reconciliation policy: staleness, tolerances and conflict severity rules."""
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

SEVERITIES = ("INFORMATIONAL", "LOW", "MEDIUM", "HIGH")

# Fixed severities per rule; override any of them through the policy.
DEFAULT_RULE_SEVERITY = {
    "LIABILITY_UNDERSTATED": "HIGH",
    "LIABILITY_OMITTED": "HIGH",
    "OWNER_MISMATCH": "HIGH",
    "OWNER_UNCONFIRMED": "MEDIUM",
    "DUPLICATE_ASSET_UNRESOLVED": "MEDIUM",
    "SAME_ASSET_DIFFERENT_VALUE": "MEDIUM",
    "PORTFOLIO_TOTAL_MISMATCH": "MEDIUM",
    "CURRENCY_MISMATCH": "MEDIUM",
    "STALE_EVIDENCE": "LOW",
    "UNLINKED_EVIDENCE": "LOW",
    "DUPLICATE_ASSET_RESOLVED": "INFORMATIONAL",
    "EVIDENCE_EXCEEDS_DECLARED": "INFORMATIONAL",
    "LIQUIDITY_SHORTFALL": "INFORMATIONAL",
}

# Days after which a fact is considered stale. None means evidence of this kind does not expire.
DEFAULT_STALENESS_DAYS: dict[str, int | None] = {
    "BANK_CLOSING_BALANCE": 365,
    "PORTFOLIO_HOLDING": 365,
    "PORTFOLIO_TOTAL_VALUE": 365,
    "LIABILITY_OUTSTANDING": 365,
    "TAX_TOTAL_INCOME": 730,
}

DEFAULT_COVERAGE_TYPES = (
    "SOURCE_OF_WEALTH",
    "INVESTMENTS",
    "BANK_BALANCE",
    "PROPERTY_OWNERSHIP",
    "BUSINESS_OWNERSHIP",
    "OTHER_ASSET",
    "LIABILITY",
    "ANNUAL_INCOME",
)


@dataclass(frozen=True)
class ReconciliationPolicy:
    tolerance: Decimal = Decimal("0")
    staleness_days: dict[str, int | None] = field(default_factory=lambda: dict(DEFAULT_STALENESS_DAYS))
    difference_pct_high: Decimal = Decimal("20")
    difference_pct_medium: Decimal = Decimal("2")
    high_absolute_difference: Decimal | None = Decimal("10000000")
    severity_overrides: dict[str, str] = field(default_factory=dict)
    coverage_claim_types: tuple[str, ...] = DEFAULT_COVERAGE_TYPES

    def __post_init__(self) -> None:
        for sev in self.severity_overrides.values():
            if sev not in SEVERITIES:
                raise ValueError(f"Unknown severity: {sev}")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReconciliationPolicy":
        base = cls()
        return cls(
            tolerance=Decimal(str(data.get("tolerance", base.tolerance))),
            staleness_days={**base.staleness_days, **data.get("staleness_days", {})},
            difference_pct_high=Decimal(str(data.get("difference_pct_high", base.difference_pct_high))),
            difference_pct_medium=Decimal(str(data.get("difference_pct_medium", base.difference_pct_medium))),
            high_absolute_difference=(
                Decimal(str(data["high_absolute_difference"]))
                if data.get("high_absolute_difference") is not None
                else (None if "high_absolute_difference" in data else base.high_absolute_difference)
            ),
            severity_overrides=dict(data.get("severity_overrides", {})),
            coverage_claim_types=tuple(data.get("coverage_claim_types", base.coverage_claim_types)),
        )

    def staleness_for(self, fact_type: str) -> int | None:
        return self.staleness_days.get(fact_type)

    def rule_severity(self, rule_id: str) -> str:
        return self.severity_overrides.get(rule_id) or DEFAULT_RULE_SEVERITY.get(rule_id, "MEDIUM")

    def difference_severity(self, rule_id: str, difference: Decimal, declared: Decimal | None) -> str:
        """Severity for an unexplained difference, from its size relative to the declared amount."""
        if rule_id in self.severity_overrides:
            return self.severity_overrides[rule_id]
        if difference <= self.tolerance:
            return "INFORMATIONAL"
        if self.high_absolute_difference is not None and difference >= self.high_absolute_difference:
            return "HIGH"
        if declared and declared > 0:
            pct = difference * 100 / declared
            if pct >= self.difference_pct_high:
                return "HIGH"
            if pct >= self.difference_pct_medium:
                return "MEDIUM"
        return "LOW"
