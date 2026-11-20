"""Parse and validate raw model output against a Pydantic schema."""
import json
import re
from decimal import Decimal
from typing import TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


class ExtractionParseError(Exception):
    """Output was not valid JSON or did not match the schema. The summary never includes values."""

    def __init__(self, error_type: str, summary: str) -> None:
        super().__init__(error_type)
        self.error_type = error_type
        self.summary = summary


def _load(text: str):
    candidate = text.strip()
    fenced = _FENCE.match(candidate)
    if fenced:
        candidate = fenced.group(1)
    try:
        # Floats become Decimal so monetary values never pass through binary floating point.
        return json.loads(candidate, parse_float=Decimal)
    except json.JSONDecodeError:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start == -1 or end <= start:
            raise ExtractionParseError("INVALID_JSON", "Output is not valid JSON") from None
        try:
            return json.loads(candidate[start : end + 1], parse_float=Decimal)
        except json.JSONDecodeError as exc:
            raise ExtractionParseError(
                "INVALID_JSON", f"Output is not valid JSON (error at position {exc.pos})"
            ) from None


def parse_model_output(schema: type[T], text: str) -> T:
    data = _load(text)
    if not isinstance(data, dict):
        raise ExtractionParseError("INVALID_JSON", "Output must be a JSON object")
    try:
        return schema.model_validate(data)
    except ValidationError as exc:
        problems = [f"{'.'.join(str(p) for p in e['loc'])}: {e['type']}" for e in exc.errors()[:20]]
        raise ExtractionParseError("SCHEMA_VALIDATION", "; ".join(problems)) from None
