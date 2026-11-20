"""Grounding checks and fact drafts.

Every value the model returns must be backed by a quote that really appears on the cited page, and
numbers must appear in that quote. Ungrounded items are dropped and reported, never persisted.
"""
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.extraction.schemas import Sourced

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_CENT = Decimal("0.01")


def normalise(text: str) -> str:
    return " ".join(text.lower().split())


def numbers_in(text: str) -> set[Decimal]:
    found: set[Decimal] = set()
    for raw in _NUMBER.findall(text):
        try:
            found.add(Decimal(raw.replace(",", "")))
        except InvalidOperation:
            continue
    return found


@dataclass
class FactDraft:
    fact_type: str
    page: int
    source_text: str
    original_value: str
    confidence: float
    amount: Decimal | None = None
    currency: str | None = None
    normalized: dict[str, Any] = field(default_factory=dict)
    effective_date: date | None = None

    def idempotency_key(self, document_id: str) -> str:
        payload = json.dumps(
            [
                document_id,
                self.fact_type,
                self.page,
                str(self.amount) if self.amount is not None else None,
                self.currency,
                self.effective_date.isoformat() if self.effective_date else None,
                self.normalized,
                self.original_value,
            ],
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(payload.encode()).hexdigest()


class FactBuilder:
    def __init__(self, pages: dict[int, str]) -> None:
        self._pages = {n: normalise(t) for n, t in pages.items()}
        self.drafts: list[FactDraft] = []
        self.issues: list[str] = []

    def _reject(self, fact_type: str, page: int, reason: str) -> None:
        # Issue text deliberately contains no document content.
        self.issues.append(f"{fact_type} (page {page}): {reason}")

    def verify(
        self,
        fact_type: str,
        src: Sourced,
        *,
        amount: Decimal | None = None,
        numbers: tuple[Decimal, ...] = (),
        texts: tuple[str, ...] = (),
    ) -> bool:
        """Check the citation without creating a fact."""
        page_text = self._pages.get(src.source_page)
        if page_text is None:
            self._reject(fact_type, src.source_page, "cited page does not exist")
            return False
        quote = normalise(src.source_text)
        if quote not in page_text:
            self._reject(fact_type, src.source_page, "quoted text not found on the cited page")
            return False

        required = ([amount] if amount is not None else []) + list(numbers)
        available = numbers_in(src.source_text)
        if any(n not in available for n in required):
            self._reject(fact_type, src.source_page, "number not present in the quoted text")
            return False
        if any(normalise(t) not in quote for t in texts):
            self._reject(fact_type, src.source_page, "value not present in the quoted text")
            return False
        return True

    def add(
        self,
        fact_type: str,
        src: Sourced,
        *,
        original: str,
        amount: Decimal | None = None,
        currency: str | None = None,
        normalized: dict[str, Any] | None = None,
        effective_date: date | None = None,
        numbers: tuple[Decimal, ...] = (),
        texts: tuple[str, ...] = (),
    ) -> bool:
        if not self.verify(fact_type, src, amount=amount, numbers=numbers, texts=texts):
            return False
        self.drafts.append(
            FactDraft(
                fact_type=fact_type,
                page=src.source_page,
                source_text=src.source_text,
                original_value=original,
                confidence=src.confidence,
                amount=amount.quantize(_CENT) if amount is not None else None,
                currency=currency,
                normalized=normalized or {},
                effective_date=effective_date,
            )
        )
        return True
