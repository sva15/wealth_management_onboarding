"""Graph persistence port. Domain/application code depends only on this interface."""
from dataclasses import dataclass, field
from typing import Any, Protocol

# Node labels from the financial evidence graph model.
NODE_LABELS = (
    "Customer",
    "Person",
    "Claim",
    "Document",
    "Evidence",
    "ExtractedFact",
    "Account",
    "Asset",
    "Liability",
    "Transaction",
    "Organization",
    "FinancialEvent",
    "Conflict",
    "AnalystDecision",
)


@dataclass(frozen=True)
class GraphNode:
    id: str
    label: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphEdge:
    source: str
    type: str
    target: str
    properties: dict[str, Any] = field(default_factory=dict)


class GraphRepository(Protocol):
    def ping(self) -> bool:
        """Return True when the graph store is reachable."""

    def ensure_schema(self) -> None:
        """Create constraints/indexes idempotently."""

    def merge_node(self, label: str, node_id: str, properties: dict[str, Any]) -> None:
        """Idempotently create or update a node keyed by its id."""

    def merge_relationship(
        self, from_id: str, rel_type: str, to_id: str, properties: dict[str, Any] | None = None
    ) -> None:
        """Idempotently create or update a relationship between two existing nodes."""

    def clear_case(self, case_id: str) -> None:
        """Delete every node tagged with this case id (and its relationships). Customers are kept."""

    def get_case_subgraph(self, case_id: str) -> tuple[list[GraphNode], list[GraphEdge]]:
        """Nodes tagged with the case id, their customer(s), and the edges among them."""

    def close(self) -> None:
        """Release resources."""
