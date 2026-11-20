"""Optional LLM fallback for documents the deterministic rules cannot classify confidently."""
import structlog
from pydantic import BaseModel, Field

from app.domain.classification import ClassificationResult
from app.domain.enums import DocumentType
from app.extraction import tasks
from app.extraction.parsing import ExtractionParseError, parse_model_output
from app.extraction.prompts import build_request
from app.ports.llm import LlmClient, LlmError, LlmResponse

log = structlog.get_logger()

LLM_ACCEPT_CONFIDENCE = 0.8
_MAX_CHARS = 6000


class LlmClassificationOutput(BaseModel):
    document_type: DocumentType
    confidence: float = Field(ge=0, le=1)
    explanation: str = Field(max_length=300)


def classify_with_llm(
    llm: LlmClient, text: str
) -> tuple[ClassificationResult, LlmResponse] | None:
    """Return None when the model fails or produces unusable output; the caller keeps the rules result."""
    request = build_request(
        tasks.CLASSIFY, LlmClassificationOutput, {1: text[:_MAX_CHARS]}, tasks.PROMPT_VERSION
    )
    try:
        response = llm.invoke(request)
        parsed = parse_model_output(LlmClassificationOutput, response.text)
    except (LlmError, ExtractionParseError) as exc:
        log.warning("llm_classification_failed", error_type=type(exc).__name__)
        return None

    needs_review = (
        parsed.document_type is DocumentType.UNKNOWN or parsed.confidence < LLM_ACCEPT_CONFIDENCE
    )
    result = ClassificationResult(
        document_type=parsed.document_type,
        confidence=round(parsed.confidence, 2),
        explanation=f"[LLM {response.model_id}] {parsed.explanation}",
        requires_human_review=needs_review,
        method="LLM",
    )
    return result, response
