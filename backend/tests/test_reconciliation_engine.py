from datetime import date, datetime, timezone
from decimal import Decimal

from app.domain.entity_resolution import CustomerAnchor, resolve_entities
from app.domain.reconciliation.engine import reconcile
from app.domain.reconciliation.policy import ReconciliationPolicy
from app.domain.reconciliation.state import ReconClaim
from tests.factories import (
    bank_facts,
    demo_facts,
    fact,
    holding,
    loan_facts,
    person,
    portfolio_facts,
    sale_facts,
    tax_facts,
)

D = Decimal
CUSTOMER = CustomerAnchor("cust-1", "Aarav Mehta", "ABCDE1234F")
NOW = datetime(2026, 4, 15, tzinfo=timezone.utc)
AS_OF = date(2026, 4, 15)


def claims(**override):
    base = {
        "NET_WORTH": ("80000000", "Declared total net worth"),
        "ANNUAL_INCOME": ("12000000", "Declared annual income"),
        "SOURCE_OF_WEALTH": ("52000000", "Sale of a technology company"),
        "SOURCE_OF_FUNDS": ("30000000", "Proceeds from the sale of a technology company"),
        "INVESTMENTS": ("17000000", "Mutual fund and equity portfolio"),
        "BANK_BALANCE": ("11000000", "Bank deposits"),
        "PROPERTY_OWNERSHIP": ("61000000", "Residential property"),
        "LIABILITY": ("9000000", "Outstanding loan"),
    }
    base.update(override)
    return [
        ReconClaim(f"c-{t}", t, D(a) if a is not None else None, "INR", d, "MATERIAL")
        for t, (a, d) in base.items() if a != "SKIP"
    ]


def run(facts=None, claim_list=None, policy=None, as_of=AS_OF):
    facts = facts if facts is not None else demo_facts()
    res = resolve_entities("case1", facts, CUSTOMER)
    return reconcile(case_id="case1", customer_id="cust-1", claims=claim_list or claims(), facts=facts,
                     resolution=res, policy=policy, as_of=as_of, now=NOW)


def by_claim(result):
    return {c.claim_type: c for c in result.claims}


def rules(result):
    return {c.rule_id: c for c in result.conflicts}


def test_demo_totals_and_net_worth():
    r = run()
    calc = r.calculations
    assert calc["gross_assets"].result == D("28000000.00")
    assert calc["liabilities"].result == D("9000000.00")
    assert calc["net_worth"].result == D("19000000.00")
    assert calc["net_worth_difference"].result == D("61000000.00")
    assert calc["duplicate_asset_adjustment"].result == D("10000000.00")
    assert "INR 2,80,00,000.00" in calc["gross_assets"].formula
    assert calc["net_worth"].calculated_at == NOW and calc["net_worth"].currency == "INR"
    # the duplicate holding is excluded by rule and traced
    dup = [e for e in r.exclusions if e.reason == "DUPLICATE_RESOLVED"]
    assert [e.fact_id for e in dup] == ["cn-h1"] and "cn-h1" in calc["duplicate_asset_adjustment"].excluded_fact_ids
    assert set(calc["net_worth"].input_fact_ids) >= {"bank-close", "pf-h1", "pf-h2", "ln-out"}
    assert "cn-h1" in calc["net_worth"].excluded_fact_ids and "pf-h1" in calc["net_worth"].input_fact_ids


def test_each_material_claim_gets_a_status():
    c = by_claim(run())
    assert c["BANK_BALANCE"].status == "VERIFIED" and c["INVESTMENTS"].status == "VERIFIED"
    assert c["LIABILITY"].status == "VERIFIED" and c["ANNUAL_INCOME"].status == "VERIFIED"
    assert c["SOURCE_OF_FUNDS"].status == "VERIFIED" and c["SOURCE_OF_FUNDS"].supported_amount == D("30000000")
    assert c["SOURCE_OF_WEALTH"].status == "PARTIALLY_VERIFIED"
    assert c["SOURCE_OF_WEALTH"].supported_amount == D("50400000.00") and c["SOURCE_OF_WEALTH"].difference == D("1600000.00")
    assert c["PROPERTY_OWNERSHIP"].status == "UNVERIFIED" and c["PROPERTY_OWNERSHIP"].difference == D("61000000")
    nw = c["NET_WORTH"]
    assert nw.status == "PARTIALLY_VERIFIED" and nw.evidence_backed_amount == D("19000000.00") and nw.difference == D("61000000.00")
    assert "INR 6,10,00,000.00 is not evidenced" in nw.explanation


def test_evidence_coverage_and_funds_coverage():
    calc = run().calculations
    assert calc["evidence_coverage"].result == D("61.36") and calc["evidence_coverage"].unit == "percent"
    assert calc["source_of_funds_coverage"].result == D("168.00")
    assert calc["liquid_funds_coverage"].result == D("36.67")
    assert calc["sale_proceeds_difference:SPA-2026-0112"].result == D("1600000.00")


def test_conflicts_and_severities_for_the_demo_case():
    r = run()
    rule = rules(r)
    assert rule["SALE_VS_BANK_RECEIPT"].severity == "MEDIUM"  # 3.08% of the declared sale value
    assert rule["MATERIAL_CLAIM_WITHOUT_EVIDENCE"].severity == "HIGH"
    assert rule["DECLARED_VS_EVIDENCE_DIFFERENCE"].claim_ids == ["c-NET_WORTH"]
    assert rule["DUPLICATE_ASSET_RESOLVED"].severity == "INFORMATIONAL"
    assert rule["LIQUIDITY_SHORTFALL"].severity == "INFORMATIONAL"
    assert "OWNER_MISMATCH" not in rule and "STALE_EVIDENCE" not in rule
    # the sale shortfall is reported once, not again as a generic claim difference
    assert not [c for c in r.conflicts if c.rule_id == "DECLARED_VS_EVIDENCE_DIFFERENCE" and "c-SOURCE_OF_WEALTH" in c.claim_ids]
    assert set(rule["SALE_VS_BANK_RECEIPT"].fact_ids) == {"sale-amt", "bank-t1"}


def test_next_best_evidence_is_specific():
    r = run()
    req = {q.conflict_key.split(":")[0]: q for q in r.requirements}
    sale = req["SALE_VS_BANK_RECEIPT"]
    assert sale.audience == "CUSTOMER" and sale.priority == "MEDIUM"
    assert "INR 16,00,000.00 difference between the sale agreement (SPA-2026-0112" in sale.request_text
    assert "taxes, advisory fees or transaction expenses deducted from the sale proceeds" in sale.request_text
    assert sale.details["existing_evidence"] == ["d-bank p.2", "d-sale p.2"]
    assert set(sale.details) == {"unresolved_claim", "observed_discrepancy", "existing_evidence", "required_evidence", "why_needed"}
    prop = req["MATERIAL_CLAIM_WITHOUT_EVIDENCE"]
    assert prop.priority == "HIGH" and "title deed" in prop.request_text and "INR 6,10,00,000.00" in prop.request_text
    assert req["LIQUIDITY_SHORTFALL"].audience == "ANALYST"
    assert "DUPLICATE_ASSET_RESOLVED" not in req and "EVIDENCE_EXCEEDS_DECLARED" not in req


def test_stale_evidence_is_excluded_with_its_age_shown():
    r = run(as_of=date(2027, 6, 30))  # 456 days after the statements
    assert r.calculations["gross_assets"].result == D("0")
    assert by_claim(r)["BANK_BALANCE"].status == "STALE" and by_claim(r)["LIABILITY"].status == "STALE"
    stale = [c for c in r.conflicts if c.rule_id == "STALE_EVIDENCE"]
    assert {c.details["age_days"] for c in stale} >= {456} and all(c.severity == "LOW" for c in stale)
    assert all(e.reason == "STALE" for e in r.exclusions if e.fact_id in {"bank-close", "pf-h1"})
    assert r.calculations["stale_evidence_net_worth_impact"].result == D("19000000.00")
    req = next(q for q in r.requirements if q.conflict_key.startswith("STALE_EVIDENCE") and "bank statement" in q.request_text)
    assert "within the last 365 days" in req.request_text


def test_staleness_policy_is_configurable():
    strict = ReconciliationPolicy.from_dict({"staleness_days": {"BANK_CLOSING_BALANCE": 10}, "severity_overrides": {"STALE_EVIDENCE": "HIGH"}})
    r = run(policy=strict)
    assert by_claim(r)["BANK_BALANCE"].status == "STALE"
    assert next(c for c in r.conflicts if c.rule_id == "STALE_EVIDENCE").severity == "HIGH"
    assert by_claim(r)["INVESTMENTS"].status == "VERIFIED"  # other kinds keep their defaults


def test_unresolved_duplicates_are_excluded_from_verified_totals():
    facts = portfolio_facts() + [holding("x-h1", "d-x", "INF000Z01AB1", None, "10000000.00")] + bank_facts() + sale_facts() + loan_facts()
    r = run(facts)
    assert r.calculations["gross_assets"].result == D("28000000.00")  # pending holding not added
    assert rules(r)["DUPLICATE_ASSET_UNRESOLVED"].fact_ids == ["x-h1"]
    assert any(e.fact_id == "x-h1" and e.reason == "DUPLICATE_UNRESOLVED" for e in r.exclusions)
    assert [q for q in r.requirements if q.conflict_key.startswith("DUPLICATE_ASSET_UNRESOLVED")][0].audience == "ANALYST"


def test_same_asset_with_different_values_is_excluded_and_flagged():
    facts = portfolio_facts() + [holding("x-h1", "d-x", "INF000Z01AB1", "11223344/01", "9000000.00")] + bank_facts() + sale_facts()
    r = run(facts)
    assert r.calculations["investment_total" if False else "gross_assets"].result == D("18000000.00")  # bank 11M + 7M debt fund
    assert "SAME_ASSET_DIFFERENT_VALUE" in rules(r)


def test_liability_understated_and_omitted():
    low = run(claim_list=claims(LIABILITY=("5000000", "Outstanding loan")))
    assert by_claim(low)["LIABILITY"].status == "CONTRADICTED"
    assert rules(low)["LIABILITY_UNDERSTATED"].severity == "HIGH"

    omitted = run(claim_list=claims(LIABILITY=("SKIP", "")))
    assert rules(omitted)["LIABILITY_OMITTED"].severity == "HIGH"
    assert "not declared" in [q for q in omitted.requirements if q.conflict_key.startswith("LIABILITY_OMITTED")][0].request_text


def test_documents_of_another_owner_do_not_count():
    other = person("ln-b2", "d-loan", "borrower", "Rohan Gupta", "ZZZZZ9999Z")
    facts = [f for f in loan_facts() if f.id not in {"ln-b-n", "ln-b-p"}] + other
    r = run(sale_facts() + bank_facts() + portfolio_facts() + facts)
    assert r.calculations["liabilities"].result == D("0")
    assert rules(r)["OWNER_MISMATCH"].severity == "HIGH"
    assert any(e.reason == "OWNER_NOT_CUSTOMER" for e in r.exclusions)


def test_unconfirmed_identity_is_flagged():
    r = run(sale_facts() + bank_facts(holder="Aarav Kumar Mehta"))
    assert rules(r)["OWNER_UNCONFIRMED"].severity == "MEDIUM"


def test_currencies_are_never_mixed():
    usd = fact("usd-h", "d-usd", "PORTFOLIO_HOLDING", amount="100.00", currency="USD", on=date(2026, 3, 31),
               normalized={"instrument_name": "US Fund", "isin": "US0000000001", "folio": "1/1"})
    r = run(demo_facts() + [usd])
    assert r.calculations["gross_assets"].result == D("28000000.00")
    assert rules(r)["CURRENCY_MISMATCH"].fact_ids == ["usd-h"]


def test_facts_without_an_entity_are_reported_not_dropped():
    orphan = fact("orphan", "d-o", "BANK_CLOSING_BALANCE", amount="500.00", on=date(2026, 3, 31))
    r = run(demo_facts() + [orphan])
    assert r.calculations["gross_assets"].result == D("28000000.00")
    c = rules(r)["UNLINKED_EVIDENCE"]
    assert c.fact_ids == ["orphan"] and c.severity == "LOW"
    assert any(e.fact_id == "orphan" and e.reason == "UNLINKED" for e in r.exclusions)


def test_no_sale_proceeds_found_is_a_high_conflict():
    facts = [f for f in demo_facts() if f.id != "bank-t1"]
    r = run(facts)
    c = rules(r)["SALE_VS_BANK_RECEIPT"]
    assert c.severity == "HIGH" and "no bank credit" in c.description
    assert by_claim(r)["SOURCE_OF_WEALTH"].status == "PARTIALLY_VERIFIED"  # agreement only; receipt unverified
    assert by_claim(r)["SOURCE_OF_WEALTH"].supported_amount == D("0")


def test_portfolio_total_mismatch():
    facts = [f for f in demo_facts() if f.id != "pf-h2"]
    assert "PORTFOLIO_TOTAL_MISMATCH" in rules(run(facts))


def test_severity_thresholds_are_configurable():
    p = ReconciliationPolicy.from_dict({"difference_pct_medium": 5, "difference_pct_high": 50})
    assert rules(run(policy=p))["SALE_VS_BANK_RECEIPT"].severity == "LOW"
    assert p.difference_severity("X", D("0"), D("100")) == "INFORMATIONAL"
    try:
        ReconciliationPolicy.from_dict({"severity_overrides": {"STALE_EVIDENCE": "SEVERE"}})
    except ValueError:
        pass
    else:
        raise AssertionError("invalid severity accepted")


def test_reconciliation_is_deterministic():
    a, b = run(), run(list(reversed(demo_facts())))
    assert {k: v.result for k, v in a.calculations.items()} == {k: v.result for k, v in b.calculations.items()}
    assert sorted(c.key for c in a.conflicts) == sorted(c.key for c in b.conflicts)
    assert [(c.claim_id, c.status) for c in a.claims] == [(c.claim_id, c.status) for c in b.claims]
    assert tax_facts()
