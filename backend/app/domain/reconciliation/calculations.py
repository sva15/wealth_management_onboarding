"""Deterministic monetary calculations. Decimal only; every result states its formula and inputs."""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from app.domain.facts import FactView
from app.domain.money import format_inr


@dataclass(frozen=True)
class CalculationResult:
    name: str
    formula: str
    result: Decimal
    currency: str
    input_fact_ids: tuple[str, ...]
    excluded_fact_ids: tuple[str, ...]
    calculated_at: datetime
    notes: tuple[str, ...] = ()
    unit: str = "currency"  # "currency" or "percent"


def sale_proceeds_difference(
    consideration: FactView,
    credits: list[FactView],
    excluded: tuple[str, ...] = (),
    now: datetime | None = None,
) -> CalculationResult:
    """Sale consideration minus observed bank credits. Positive means proceeds are not accounted for."""
    if consideration.amount is None or any(c.amount is None for c in credits):
        raise ValueError("All inputs must carry an amount")
    currencies = {consideration.currency, *(c.currency for c in credits)}
    if len(currencies) != 1:
        raise ValueError("Amounts in different currencies cannot be combined without an exchange rate")
    currency = consideration.currency or "INR"

    observed = sum((c.amount for c in credits), Decimal("0"))
    difference = consideration.amount - observed
    parts = " + ".join(format_inr(c.amount, currency) for c in credits) or format_inr(Decimal("0"), currency)
    notes = []
    if not credits:
        notes.append("No bank credit was linked to the sale agreement.")
    return CalculationResult(
        name="sale_proceeds_difference",
        formula=f"consideration - sum(observed credits) = {format_inr(consideration.amount, currency)} - ({parts}) = {format_inr(difference, currency)}",
        result=difference,
        currency=currency,
        input_fact_ids=(consideration.id, *(c.id for c in credits)),
        excluded_fact_ids=tuple(excluded),
        calculated_at=now or datetime.now(timezone.utc),
        notes=tuple(notes),
    )
