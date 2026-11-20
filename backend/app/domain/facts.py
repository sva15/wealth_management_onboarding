"""Read model of an extracted fact, as seen by pure domain logic."""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class FactView:
    id: str
    document_id: str
    document_name: str
    fact_type: str
    page: int
    confidence: float
    amount: Decimal | None = None
    currency: str | None = None
    effective_date: date | None = None
    normalized: dict[str, Any] = field(default_factory=dict)
    source_text: str = ""
