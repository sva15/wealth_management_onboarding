from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.seed import demo_declaration


def _declaration_json() -> dict:
    return demo_declaration().model_dump(mode="json")


def _make_case(client) -> str:
    cust = client.post("/customers", json={"full_name": "Test Person", "pan": "ABCDE1234F"})
    assert cust.status_code == 201
    case = client.post("/cases", json={"customer_id": cust.json()["id"]})
    assert case.status_code == 201
    assert case.json()["status"] == "AWAITING_DOCUMENTS"
    assert case.json()["customer_name"] == "Test Person"
    return case.json()["id"]


def test_declaration_creates_claims_audit_and_graph(client):
    case_id = _make_case(client)
    r = client.post(f"/cases/{case_id}/declarations", json=_declaration_json())
    assert r.status_code == 201
    claims = r.json()["claims"]
    assert len(claims) == 8
    assert {c["verification_status"] for c in claims} == {"DECLARED"}
    nw = next(c for c in claims if c["claim_type"] == "NET_WORTH")
    assert Decimal(nw["declared_amount"]) == Decimal("80000000")

    listed = client.get(f"/cases/{case_id}/claims").json()
    assert len(listed) == 8

    audit = client.get(f"/cases/{case_id}/audit").json()
    actions = [e["action"] for e in audit["items"]]
    assert "declaration.created" in actions and actions.count("claim.created") == 8
    assert "case.created" in actions

    graph = client.app.state.graph
    claim_nodes = [n for n in graph.nodes.values() if n["label"] == "Claim"]
    assert len(claim_nodes) == 8
    assert len(graph.relationships) == 8


def test_new_declaration_supersedes_previous_claims(client):
    case_id = _make_case(client)
    client.post(f"/cases/{case_id}/declarations", json=_declaration_json())
    client.post(f"/cases/{case_id}/declarations", json=_declaration_json())

    active = client.get(f"/cases/{case_id}/claims").json()
    everything = client.get(f"/cases/{case_id}/claims", params={"include_superseded": True}).json()
    assert len(active) == 8
    assert len(everything) == 16
    assert sum(c["verification_status"] == "SUPERSEDED" for c in everything) == 8

    payload = client.get(f"/cases/{case_id}").json()["latest_declaration"]["payload"]
    assert Decimal(payload["declared_net_worth"]) == Decimal("80000000")


def test_dashboard_and_pagination(client):
    for _ in range(3):
        _make_case(client)
    summary = client.get("/dashboard/summary").json()
    assert summary["total_cases"] == 3
    assert summary["by_status"] == {"AWAITING_DOCUMENTS": 3}
    assert summary["requires_review"] == 0

    page = client.get("/cases", params={"limit": 2, "offset": 0}).json()
    assert page["total"] == 3 and len(page["items"]) == 2
    assert client.get("/cases", params={"status": "REQUIRES_REVIEW"}).json()["total"] == 0


def test_errors_and_role_checks(client):
    missing = client.get("/cases/nope")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"

    case_id = _make_case(client)
    bad = _declaration_json()
    bad["declared_net_worth"] = "-1"
    assert client.post(f"/cases/{case_id}/declarations", json=bad).status_code == 422

    forbidden = client.get("/cases", headers={"X-Actor-Role": "customer"})
    assert forbidden.status_code == 403

    bad_pan = client.post("/customers", json={"full_name": "X", "pan": "123"})
    assert bad_pan.status_code == 422


def test_audit_events_are_immutable(client):
    case_id = _make_case(client)
    assert client.get(f"/cases/{case_id}/audit").json()["total"] >= 1
    with client.app.state.engine.begin() as conn:
        with pytest.raises(DBAPIError, match="append-only"):
            conn.execute(text("UPDATE audit_events SET actor = 'tamper'"))
    with client.app.state.engine.begin() as conn:
        with pytest.raises(DBAPIError, match="append-only"):
            conn.execute(text("DELETE FROM audit_events"))
