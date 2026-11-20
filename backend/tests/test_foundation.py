from decimal import Decimal

import pytest

from app.adapters.graph.in_memory import InMemoryGraphRepository
from app.adapters.persistence.types import DecimalText


def test_live(client):
    r = client.get("/health/live")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_ready_reports_checks_and_correlation_id(client):
    r = client.get("/health/ready", headers={"X-Correlation-ID": "abc-123"})
    assert r.status_code == 200
    body = r.json()
    assert body["checks"] == {"database": "ok", "graph": "ok"}
    assert body["graph_backend"] == "memory"
    assert r.headers["X-Correlation-ID"] == "abc-123"


def test_error_structure_and_generated_correlation_id(client):
    r = client.get("/nope")
    assert r.status_code == 404
    err = r.json()["error"]
    assert err["code"] == "HTTP_404"
    assert err["correlation_id"] == r.headers["X-Correlation-ID"]


def test_in_memory_graph_merge_is_idempotent():
    g = InMemoryGraphRepository()
    g.merge_node("Customer", "c1", {"name": "A"})
    g.merge_node("Customer", "c1", {"name": "B"})
    g.merge_node("Claim", "k1", {})
    g.merge_relationship("c1", "DECLARES", "k1")
    g.merge_relationship("c1", "DECLARES", "k1")
    assert len(g.nodes) == 2 and g.nodes["c1"]["name"] == "B"
    assert len(g.relationships) == 1


def test_decimal_text_round_trips_and_rejects_float():
    t = DecimalText()
    assert t.process_bind_param(Decimal("52000000.00"), None) == "52000000.00"
    assert t.process_result_value("52000000.00", None) == Decimal("52000000.00")
    with pytest.raises(TypeError):
        t.process_bind_param(0.1, None)
