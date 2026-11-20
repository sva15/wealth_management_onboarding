"""Deterministic document classification from filename and text signals.

An LLM fallback (Phase 4) is only consulted when these rules cannot decide.
"""
import re
from dataclasses import dataclass

from app.domain.enums import DocumentType

DEFAULT_REVIEW_THRESHOLD = 0.6
_MIN_TOP_SCORE = 3

# (phrase, weight). Phrases are matched on word boundaries, case-insensitively.
_TEXT_SIGNALS: dict[DocumentType, list[tuple[str, int]]] = {
    DocumentType.CUSTOMER_DECLARATION: [
        ("financial declaration", 3),
        ("declared net worth", 2),
        ("source of wealth", 1),
        ("source of funds", 1),
        ("intended investment", 1),
    ],
    DocumentType.BANK_STATEMENT: [
        ("bank statement", 3),
        ("account statement", 2),
        ("opening balance", 1),
        ("closing balance", 1),
        ("narration", 1),
        ("withdrawal", 1),
        ("ifsc", 1),
    ],
    DocumentType.PORTFOLIO_STATEMENT: [
        ("portfolio statement", 3),
        ("holdings statement", 3),
        ("isin", 1),
        ("folio", 1),
        ("units", 1),
        ("market value", 1),
        ("nav", 1),
    ],
    DocumentType.COMPANY_SALE_AGREEMENT: [
        ("share purchase agreement", 3),
        ("sale agreement", 3),
        ("consideration", 2),
        ("purchaser", 1),
        ("seller", 1),
        ("shares", 1),
    ],
    DocumentType.TAX_SUMMARY: [
        ("tax return summary", 3),
        ("income tax", 2),
        ("assessment year", 2),
        ("total income", 1),
        ("tax paid", 1),
    ],
    DocumentType.LIABILITY_STATEMENT: [
        ("loan account statement", 3),
        ("outstanding principal", 2),
        ("sanctioned amount", 1),
        ("emi", 1),
        ("interest rate", 1),
    ],
}

_FILENAME_SIGNALS: dict[DocumentType, str] = {
    DocumentType.CUSTOMER_DECLARATION: r"declaration",
    DocumentType.BANK_STATEMENT: r"bank|account[-_ ]?statement",
    DocumentType.PORTFOLIO_STATEMENT: r"portfolio|holdings|demat|mutual",
    DocumentType.COMPANY_SALE_AGREEMENT: r"sale|spa|purchase",
    DocumentType.TAX_SUMMARY: r"tax|itr",
    DocumentType.LIABILITY_STATEMENT: r"loan|liabilit",
}
_FILENAME_WEIGHT = 2


@dataclass(frozen=True)
class ClassificationResult:
    document_type: DocumentType
    confidence: float
    explanation: str
    requires_human_review: bool
    method: str = "RULES"


def _contains(text: str, phrase: str) -> bool:
    return re.search(rf"\b{re.escape(phrase)}\b", text) is not None


def classify_document(
    filename: str, text: str, review_threshold: float = DEFAULT_REVIEW_THRESHOLD
) -> ClassificationResult:
    lowered = text.lower()
    name = filename.lower()
    scores: dict[DocumentType, int] = {}
    signals: dict[DocumentType, list[str]] = {}

    for doc_type, phrases in _TEXT_SIGNALS.items():
        hit = [(p, w) for p, w in phrases if _contains(lowered, p)]
        score = sum(w for _, w in hit)
        matched = [p for p, _ in hit]
        if re.search(_FILENAME_SIGNALS[doc_type], name):
            score += _FILENAME_WEIGHT
            matched.append("filename")
        scores[doc_type] = score
        signals[doc_type] = matched

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    (top_type, top), (_, second) = ranked[0], ranked[1]

    if top == 0:
        return ClassificationResult(
            DocumentType.UNKNOWN, 0.0, "No known document signals were found.", True
        )

    confidence = round((top / (top + second + 1)) * min(1.0, top / 4), 2)
    needs_review = top < _MIN_TOP_SCORE or confidence < review_threshold
    explanation = f"Matched signals: {', '.join(signals[top_type])}."
    if second:
        explanation += f" Runner-up score {second} vs {top}."
    return ClassificationResult(top_type, confidence, explanation, needs_review)
