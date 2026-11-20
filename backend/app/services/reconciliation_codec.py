"""Serialise reconciliation results to JSON-safe dicts and hash them without volatile timestamps."""
import hashlib
import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.domain.reconciliation.state import ReconciliationResult

_VOLATILE = {"calculated_at"}


def _plain(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _plain(asdict(value))
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def result_to_dict(result: ReconciliationResult) -> dict[str, Any]:
    data = _plain(result)
    # Conflict and requirement drafts are persisted in their own tables.
    data.pop("conflicts", None)
    data.pop("requirements", None)
    data["calculations"] = list(data["calculations"].values())
    return data


def _strip(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k not in _VOLATILE}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def result_hash(data: dict[str, Any], conflict_keys: list[str], requirement_keys: list[str]) -> str:
    payload = {"result": _strip(data), "conflicts": sorted(conflict_keys), "requirements": sorted(requirement_keys)}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
