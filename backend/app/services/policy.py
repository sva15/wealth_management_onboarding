"""Policy loading for the reconciliation engine (JSON file, validated at startup)."""
import json
from pathlib import Path

from app.config import Settings
from app.domain.reconciliation.policy import ReconciliationPolicy


def load_policy(settings: Settings) -> ReconciliationPolicy:
    if not settings.reconciliation_policy_path:
        return ReconciliationPolicy()
    data = json.loads(Path(settings.reconciliation_policy_path).read_text(encoding="utf-8"))
    return ReconciliationPolicy.from_dict(data)
