from decimal import Decimal

import pytest

from app.seed import demo_declaration
from tests.test_extraction_service import BANK_TXT, SALE_TXT, upload


def _demo_case(client, bank_text=BANK_TXT) -> str:
    cust = client.post("/customers", json={"full_name": "Aarav Mehta", "pan": "ABCDE1234F"}).json()
    case_id = client.post("/cases", json={"customer_id": cust["id"]}).json()["id"]
    client.post(f"/cases/{case_id}/declarations", json=demo_declaration().model_dump(mode="json"))
    upload(client, case_id, "sale_agreement.txt", SALE_TXT)
    upload(client, case_id, "bank_statement.txt", bank_text)
    client.post(f"/cases/{case_id}/extract")
    return case_id


def _evidence(client, case_id):
    return client.get(f"/cases/{case_id}/evidence").json()


def _by(items, claim_type, fact_type):
    return [e for e in items if e["claim_type"] == claim_type and e["fact_type"] == fact_type]


def test_linking_creates_evidence_with_provenance(client):
    case_id = _demo_case(client)
    summary = client.post(f"/cases/{case_id}/link-evidence")
    assert summary.status_code == 200
    body = summary.json()
    assert body["matches_pending"] == 0 and body["evidence_created"] > 0 and body["graph"]["claims"] == 8

    items = _evidence(client, case_id)
    sale = _by(items, "SOURCE_OF_WEALTH", "SALE_CONSIDERATION")[0]
    credit = _by(items, "SOURCE_OF_WEALTH", "BANK_TRANSACTION")[0]
    assert sale["relation"] == "SUPPORTS" and sale["document_filename"] == "sale_agreement.txt" and sale["page_number"] == 2
    assert credit["relation"] == "PARTIALLY_SUPPORTS" and credit["document_filename"] == "bank_statement.txt"
    assert "INR 16,00,000.00 is not evidenced" in credit["rationale"]
    assert "5,20,00,000.00" in sale["source_text"]
    assert _by(items, "SOURCE_OF_FUNDS", "BANK_TRANSACTION")[0]["relation"] == "SUPPORTS"
    assert _by(items, "BANK_BALANCE", "BANK_CLOSING_BALANCE")[0]["relation"] == "SUPPORTS"
    assert all(e["link_method"] == "RULE" and e["source_text"] for e in items)
    assert not [e for e in items if e["claim_type"] in ("PROPERTY_OWNERSHIP", "NET_WORTH")]


def test_sale_proceeds_check_shows_the_unexplained_difference(client):
    case_id = _demo_case(client)
    client.post(f"/cases/{case_id}/link-evidence")
    [check] = client.get(f"/cases/{case_id}/reconciliation/sale-proceeds").json()

    assert Decimal(check["difference"]) == Decimal("1600000") and check["status"] == "UNEXPLAINED_DIFFERENCE"
    assert check["reference"] == "SPA-2026-0112" and check["currency"] == "INR"
    assert check["consideration"]["document_filename"] == "sale_agreement.txt"
    assert check["consideration"]["page_number"] == 2
    [credit] = check["observed_credits"]
    assert credit["document_filename"] == "bank_statement.txt" and credit["page_number"] == 2
    assert "INR 5,20,00,000.00 - (INR 5,04,00,000.00) = INR 16,00,000.00" in check["formula"]
    assert check["input_fact_ids"] == [check["consideration"]["fact_id"], credit["fact_id"]]
    assert len(check["linked_claim_ids"]) == 2


def test_graph_contains_entities_relationships_and_evidence(client):
    case_id = _demo_case(client)
    client.post(f"/cases/{case_id}/link-evidence")
    graph = client.get(f"/cases/{case_id}/graph").json()

    labels = [n["label"] for n in graph["nodes"]]
    for label, count in {"Customer": 1, "Claim": 8, "Document": 2, "FinancialEvent": 1, "Account": 1, "Transaction": 4}.items():
        assert labels.count(label) == count, label
    assert labels.count("Organization") == 3 and labels.count("Evidence") > 0

    edge_types = {e["type"] for e in graph["edges"]}
    assert {"DECLARES", "CONTAINS", "DESCRIBES", "OWNS", "GENERATED", "CREDITED_TO", "DEBITED_FROM",
            "SUPPORTED_BY", "REFERENCES", "PARTICIPATED_IN", "INVOLVES"} <= edge_types
    claim_nodes = {n["id"]: n for n in graph["nodes"] if n["label"] == "Claim"}
    assert all("case_id" in n["properties"] for n in claim_nodes.values())
    # no document text or customer name is stored in the graph
    assert not any("Aarav" in str(n["properties"]) for n in graph["nodes"] if n["label"] in ("Customer", "ExtractedFact"))


def test_linking_is_idempotent(client):
    case_id = _demo_case(client)
    client.post(f"/cases/{case_id}/link-evidence")
    first = client.get(f"/cases/{case_id}/graph").json()
    again = client.post(f"/cases/{case_id}/link-evidence").json()
    second = client.get(f"/cases/{case_id}/graph").json()

    assert (again["evidence_created"], again["evidence_updated"], again["evidence_removed"]) == (0, 0, 0)
    assert len(first["nodes"]) == len(second["nodes"]) and len(first["edges"]) == len(second["edges"])
    actions = [e["action"] for e in client.get(f"/cases/{case_id}/audit", params={"limit": 200}).json()["items"]]
    assert "evidence.linked" in actions and "graph.updated" in actions


def test_weaker_name_match_waits_for_analyst_then_merges_accounts(client):
    case_id = _demo_case(client, BANK_TXT.replace("Account holder: Aarav Mehta", "Account holder: Aarav Kumar Mehta"))
    body = client.post(f"/cases/{case_id}/link-evidence").json()
    assert body["matches_pending"] == 1

    matches = client.get(f"/cases/{case_id}/entity-matches").json()
    pending = next(m for m in matches if m["status"] == "PENDING")
    assert pending["entity_kind"] == "person" and pending["score"] == 0.85 and "similarity" in pending["explanation"]
    accounts = [n for n in client.get(f"/cases/{case_id}/graph").json()["nodes"] if n["label"] == "Account"]
    assert len(accounts) == 2  # not merged without confirmation

    r = client.post(f"/entity-matches/{pending['id']}/decision", json={"decision": "CONFIRM", "reason": "Same person, middle name omitted"})
    assert r.status_code == 200 and r.json()["status"] == "CONFIRMED" and r.json()["decided_by"] == "local-analyst"
    after = client.get(f"/cases/{case_id}/graph").json()
    assert len([n for n in after["nodes"] if n["label"] == "Account"]) == 1
    assert not [m for m in client.get(f"/cases/{case_id}/entity-matches").json() if m["status"] == "PENDING"]
    actions = [e["action"] for e in client.get(f"/cases/{case_id}/audit", params={"limit": 200}).json()["items"]]
    assert "entity_match.decided" in actions


def test_rejected_match_is_not_raised_again(client):
    case_id = _demo_case(client, BANK_TXT.replace("Account holder: Aarav Mehta", "Account holder: Aarav Kumar Mehta"))
    client.post(f"/cases/{case_id}/link-evidence")
    pending = next(m for m in client.get(f"/cases/{case_id}/entity-matches").json() if m["status"] == "PENDING")
    client.post(f"/entity-matches/{pending['id']}/decision", json={"decision": "REJECT", "reason": "Different person"})
    again = client.post(f"/cases/{case_id}/link-evidence").json()
    assert again["matches_pending"] == 0
    assert next(m for m in client.get(f"/cases/{case_id}/entity-matches").json() if m["id"] == pending["id"])["status"] == "REJECTED"


def test_automatic_matches_cannot_be_overridden_and_endpoints_are_staff_only(client):
    case_id = _demo_case(client)
    client.post(f"/cases/{case_id}/link-evidence")
    auto = next(m for m in client.get(f"/cases/{case_id}/entity-matches").json() if m["status"] == "AUTO_ACCEPTED")
    body = {"decision": "REJECT", "reason": "No thanks"}
    assert client.post(f"/entity-matches/{auto['id']}/decision", json=body).status_code == 409

    customer = {"X-Actor-Role": "customer"}
    for path in ("entity-matches", "evidence", "graph", "reconciliation/sale-proceeds"):
        assert client.get(f"/cases/{case_id}/{path}", headers=customer).status_code == 403
    assert client.post(f"/cases/{case_id}/link-evidence", headers=customer).status_code == 403
    assert client.post(f"/entity-matches/{auto['id']}/decision", json=body, headers=customer).status_code == 403


@pytest.mark.parametrize("body", [{"decision": "MAYBE", "reason": "unsure"}, {"decision": "CONFIRM", "reason": ""}])
def test_decision_requires_valid_input(client, body):
    case_id = _demo_case(client, BANK_TXT.replace("Account holder: Aarav Mehta", "Account holder: Aarav Kumar Mehta"))
    client.post(f"/cases/{case_id}/link-evidence")
    pending = next(m for m in client.get(f"/cases/{case_id}/entity-matches").json() if m["status"] == "PENDING")
    assert client.post(f"/entity-matches/{pending['id']}/decision", json=body).status_code == 422


def test_superseded_facts_drop_out_of_evidence(client):
    case_id = _demo_case(client)
    client.post(f"/cases/{case_id}/link-evidence")
    assert _by(_evidence(client, case_id), "SOURCE_OF_WEALTH", "SALE_CONSIDERATION")

    from tests.test_extraction_service import ScriptedLlm

    doc = next(d for d in client.get(f"/cases/{case_id}/documents").json() if d["filename"].startswith("sale"))
    client.app.state.llm = ScriptedLlm(["{}"])  # a later extraction finds nothing
    client.post(f"/documents/{doc['id']}/extract")
    summary = client.post(f"/cases/{case_id}/link-evidence").json()
    assert summary["evidence_removed"] > 0
    assert not _by(_evidence(client, case_id), "SOURCE_OF_WEALTH", "SALE_CONSIDERATION")
