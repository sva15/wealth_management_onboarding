import json
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.seed import demo_declaration
from tests.test_extraction_service import BANK_TXT, SALE_TXT, upload

PORTFOLIO_TXT = (
    "PORTFOLIO STATEMENT\nZenith Wealth Services (fictional)\nInvestor: Aarav Kumar Mehta PAN: ABCDE1234F\n"
    "Valuation date: 31 March 2026\nInstrument ISIN Folio Units NAV Market value\n"
    "Zenith Bluechip Fund - Growth INF000Z01AB1 11223344/01 25000.000 400.00 INR 1,00,00,000.00\n"
    "Zenith Debt Fund - Growth INF000Z01CD2 55667788/02 50000.000 140.00 INR 70,00,000.00\n"
    "Total market value: INR 1,70,00,000.00"
)
CONSOLIDATED_TXT = (
    "CONSOLIDATED HOLDINGS STATEMENT\nNova Registrar and Transfer Agents (fictional)\n"
    "Holder: Mehta Aarav Kumar PAN: ABCDE1234F\nValuation date: 31 March 2026\n"
    "Instrument ISIN Folio Units NAV Market value\n"
    "Zenith Bluechip Fund - Growth INF000Z01AB1 11223344/01 25000.000 400.00 INR 1,00,00,000.00"
)
LOAN_TXT = (
    "LOAN ACCOUNT STATEMENT\nMeridian Finance Limited (fictional)\nBorrower: Aarav Kumar Mehta PAN: ABCDE1234F\n"
    "Loan account number: LN-77881234\nSanctioned amount: INR 1,50,00,000.00\n"
    "Outstanding principal: INR 90,00,000.00 as at 31 March 2026\nInterest rate: 9.25% per annum EMI: INR 2,40,000.00"
)
TAX_TXT = (
    "INCOME TAX RETURN SUMMARY\nName: Aarav Mehta PAN: ABCDE1234F\nAssessment Year: 2025-26 (Financial Year 2024-25)\n"
    "Head Amount\nSalary income INR 80,00,000.00\nInterest income INR 15,00,000.00\n"
    "Dividend income INR 25,00,000.00\nTotal income INR 1,20,00,000.00\nTax paid INR 36,00,000.00"
)
DOCS = {
    "sale_agreement.txt": SALE_TXT,
    "bank_statement.txt": BANK_TXT,
    "portfolio_statement.txt": PORTFOLIO_TXT,
    "consolidated_holdings_statement.txt": CONSOLIDATED_TXT,
    "loan_statement.txt": LOAN_TXT,
    "tax_return_summary.txt": TAX_TXT,
}


def build_case(client) -> str:
    cust = client.post("/customers", json={"full_name": "Aarav Mehta", "pan": "ABCDE1234F"}).json()
    case_id = client.post("/cases", json={"customer_id": cust["id"]}).json()["id"]
    client.post(f"/cases/{case_id}/declarations", json=demo_declaration().model_dump(mode="json"))
    for name, text in DOCS.items():
        upload(client, case_id, name, text)
    client.post(f"/cases/{case_id}/extract")
    return case_id


@pytest.fixture
def full_case(client) -> str:
    return build_case(client)


def _claims(client, case_id):
    return {c["claim_type"]: c for c in client.get(f"/cases/{case_id}/claims").json()}


def test_reconciliation_of_the_demo_case(client, full_case):
    r = client.post(f"/cases/{full_case}/reconciliation/run")
    assert r.status_code == 200
    body = r.json()
    summary = body["summary"]
    assert Decimal(summary["gross_assets"]) == Decimal("28000000")
    assert Decimal(summary["liabilities"]) == Decimal("9000000")
    assert Decimal(summary["net_worth"]) == Decimal("19000000")
    assert Decimal(summary["net_worth_difference"]) == Decimal("61000000")
    assert Decimal(summary["evidence_coverage_pct"]) == Decimal("61.36")

    calcs = {c["name"]: c for c in body["calculations"]}
    nw = calcs["net_worth"]
    assert nw["currency"] == "INR" and nw["calculated_at"] and "INR 1,90,00,000.00" in nw["formula"]
    facts = {f["id"]: f for f in client.get(f"/cases/{full_case}/facts", params={"limit": 500}).json()["items"]}
    assert nw["input_fact_ids"] and all(i in facts for i in nw["input_fact_ids"])
    assert Decimal(calcs["sale_proceeds_difference:SPA-2026-0112"]["result"]) == Decimal("1600000")

    # the duplicate holding is excluded from the verified total, not deleted
    dup = [e for e in body["exclusions"] if e["reason"] == "DUPLICATE_RESOLVED"]
    assert len(dup) == 1 and dup[0]["fact_id"] in facts and dup[0]["fact_id"] in calcs["duplicate_asset_adjustment"]["excluded_fact_ids"]
    # asset values show their date and age
    bank = next(c for c in body["components"] if c["kind"] == "BANK_BALANCE")
    assert bank["value_date"] == "2026-03-31" and bank["age_days"] == 15

    rows = {c["claim_type"]: c for c in body["claims"]}
    assert rows["SOURCE_OF_WEALTH"]["status"] == "PARTIALLY_VERIFIED" and Decimal(rows["SOURCE_OF_WEALTH"]["difference"]) == Decimal("1600000")
    assert rows["PROPERTY_OWNERSHIP"]["status"] == "UNVERIFIED"
    assert rows["BANK_BALANCE"]["status"] == "VERIFIED" and rows["INVESTMENTS"]["status"] == "VERIFIED"

    rules = {c["rule_id"]: c for c in body["conflicts"]}
    assert rules["SALE_VS_BANK_RECEIPT"]["severity"] == "MEDIUM"
    assert rules["MATERIAL_CLAIM_WITHOUT_EVIDENCE"]["severity"] == "HIGH" and rules["DECLARED_VS_EVIDENCE_DIFFERENCE"]["severity"] == "HIGH"
    assert all(c["status"] == "OPEN" for c in body["conflicts"])

    reqs = {q["details"]["observed_discrepancy"]: q for q in body["requirements"]}
    sale_req = next(q for q in body["requirements"] if "settlement statement" in q["request_text"])
    assert sale_req["audience"] == "CUSTOMER" and sale_req["priority"] == "MEDIUM" and sale_req["status"] == "OPEN"
    assert "INR 16,00,000.00" in sale_req["request_text"] and sale_req["details"]["existing_evidence"]
    assert len(reqs) == len(body["requirements"])


def test_claim_statuses_and_case_status_are_updated_with_audit(client, full_case):
    client.post(f"/cases/{full_case}/reconciliation/run")
    claims = _claims(client, full_case)
    assert claims["SOURCE_OF_WEALTH"]["verification_status"] == "PARTIALLY_VERIFIED"
    assert claims["PROPERTY_OWNERSHIP"]["verification_status"] == "UNVERIFIED"
    assert claims["NET_WORTH"]["verification_status"] == "PARTIALLY_VERIFIED"
    assert claims["LIABILITY"]["verification_status"] == "VERIFIED"
    assert client.get(f"/cases/{full_case}").json()["status"] == "AWAITING_CUSTOMER_EVIDENCE"

    actions = [e["action"] for e in client.get(f"/cases/{full_case}/audit", params={"limit": 200}).json()["items"]]
    for expected in ("claim.reconciled", "conflict.created", "evidence_requirement.created", "reconciliation.completed"):
        assert expected in actions


def test_rerunning_creates_no_duplicates(client, full_case):
    first = client.post(f"/cases/{full_case}/reconciliation/run").json()
    second = client.post(f"/cases/{full_case}/reconciliation/run").json()
    assert first["run_id"] == second["run_id"]  # unchanged inputs: no new run
    assert len(first["conflicts"]) == len(second["conflicts"]) and len(first["requirements"]) == len(second["requirements"])
    actions = [e["action"] for e in client.get(f"/cases/{full_case}/audit", params={"limit": 200}).json()["items"]]
    assert actions.count("reconciliation.completed") == 1
    assert client.get(f"/cases/{full_case}/reconciliation").json()["run_id"] == first["run_id"]


def test_reading_before_a_run_is_a_clear_404(client, full_case):
    r = client.get(f"/cases/{full_case}/reconciliation")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"


def test_stale_evidence_is_excluded_and_old_conflicts_close(client, full_case):
    client.post(f"/cases/{full_case}/reconciliation/run")
    client.app.state.settings.reconciliation_as_of_date = date(2027, 6, 30)
    body = client.post(f"/cases/{full_case}/reconciliation/run").json()

    assert Decimal(body["summary"]["gross_assets"]) == Decimal("0")
    assert any(c["rule_id"] == "STALE_EVIDENCE" and c["status"] == "OPEN" for c in body["conflicts"])
    assert _claims(client, full_case)["BANK_BALANCE"]["verification_status"] == "STALE"
    closed = client.get(f"/cases/{full_case}/conflicts", params={"status": "RESOLVED"}).json()
    assert any(c["rule_id"] == "DUPLICATE_ASSET_RESOLVED" and c["details"].get("auto_resolved") for c in closed)
    assert any(q["status"] == "CANCELLED" for q in client.get(f"/cases/{full_case}/evidence-requirements").json())
    stale_req = next(q for q in body["requirements"] if q["details"]["observed_discrepancy"].startswith("bank statement evidence"))
    assert "within the last 365 days" in stale_req["request_text"]


def test_analyst_decisions_on_claims_are_not_overwritten(client, full_case):
    client.post(f"/cases/{full_case}/reconciliation/run")
    from app.adapters.persistence.models import CustomerClaimRow

    with client.app.state.session_factory() as session:
        row = session.query(CustomerClaimRow).filter_by(case_id=full_case, claim_type="PROPERTY_OWNERSHIP").one()
        row.verification_status = "ANALYST_ACCEPTED"
        session.commit()
    client.post(f"/cases/{full_case}/reconciliation/run")
    assert _claims(client, full_case)["PROPERTY_OWNERSHIP"]["verification_status"] == "ANALYST_ACCEPTED"


def test_conflicts_appear_in_the_graph(client, full_case):
    client.post(f"/cases/{full_case}/reconciliation/run")
    graph = client.get(f"/cases/{full_case}/graph").json()
    conflicts = [n for n in graph["nodes"] if n["label"] == "Conflict"]
    assert conflicts and {n["properties"]["severity"] for n in conflicts} >= {"HIGH", "MEDIUM"}
    assert any(e["type"] == "INVOLVES" and e["source"] in {n["id"] for n in conflicts} for e in graph["edges"])


def test_conflict_and_requirement_filters(client, full_case):
    client.post(f"/cases/{full_case}/reconciliation/run")
    high = client.get(f"/cases/{full_case}/conflicts", params={"severity": "HIGH"}).json()
    assert high and {c["severity"] for c in high} == {"HIGH"}
    ordered = [c["severity"] for c in client.get(f"/cases/{full_case}/conflicts").json()]
    assert ordered == sorted(ordered, key=["HIGH", "MEDIUM", "LOW", "INFORMATIONAL"].index)
    assert all(q["status"] == "OPEN" for q in client.get(f"/cases/{full_case}/evidence-requirements", params={"status": "OPEN"}).json())


def test_reconciliation_endpoints_are_staff_only(client, full_case):
    customer = {"X-Actor-Role": "customer"}
    assert client.post(f"/cases/{full_case}/reconciliation/run", headers=customer).status_code == 403
    for path in ("reconciliation", "conflicts", "evidence-requirements"):
        assert client.get(f"/cases/{full_case}/{path}", headers=customer).status_code == 403


def test_policy_file_changes_severity_and_staleness(settings, tmp_path):
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({"difference_pct_medium": 5, "severity_overrides": {"DUPLICATE_ASSET_RESOLVED": "LOW"}}))
    custom = settings.model_copy(update={"reconciliation_policy_path": str(policy)})
    with TestClient(create_app(custom)) as c:
        body = c.post(f"/cases/{build_case(c)}/reconciliation/run").json()
    rules = {x["rule_id"]: x for x in body["conflicts"]}
    assert rules["SALE_VS_BANK_RECEIPT"]["severity"] == "LOW" and rules["DUPLICATE_ASSET_RESOLVED"]["severity"] == "LOW"


def test_blank_as_of_date_means_today():
    from app.config import Settings

    assert Settings(reconciliation_as_of_date="").reconciliation_as_of_date is None
