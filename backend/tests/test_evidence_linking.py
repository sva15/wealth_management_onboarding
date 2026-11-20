from decimal import Decimal

from app.domain.entity_resolution import CustomerAnchor, resolve_entities
from app.domain.evidence_linking import ClaimView, propose_links
from app.domain.money import format_inr
from app.domain.reconciliation.calculations import sale_proceeds_difference
from tests.factories import demo_facts

CUSTOMER = CustomerAnchor("cust-1", "Aarav Mehta", "ABCDE1234F")
D = Decimal


def claims():
    return [
        ClaimView("c-nw", "NET_WORTH", D("80000000"), "INR", "Declared total net worth"),
        ClaimView("c-sow", "SOURCE_OF_WEALTH", D("52000000"), "INR", "Sale of a technology company"),
        ClaimView("c-sof", "SOURCE_OF_FUNDS", D("30000000"), "INR", "Proceeds from the sale of a technology company"),
        ClaimView("c-inv", "INVESTMENTS", D("17000000"), "INR", "Mutual fund and equity portfolio"),
        ClaimView("c-bank", "BANK_BALANCE", D("11000000"), "INR", "Bank deposits"),
        ClaimView("c-prop", "PROPERTY_OWNERSHIP", D("61000000"), "INR", "Residential property"),
        ClaimView("c-loan", "LIABILITY", D("9000000"), "INR", "Outstanding loan"),
        ClaimView("c-inc", "ANNUAL_INCOME", D("12000000"), "INR", "Declared annual income"),
    ]


def links(claim_list=None, facts=None):
    facts = facts or demo_facts()
    res = resolve_entities("case1", facts, CUSTOMER)
    return {(p.claim_id, p.fact_id): p for p in propose_links(claim_list or claims(), facts, res)}


def test_format_inr_uses_indian_grouping():
    assert format_inr(D("52000000")) == "INR 5,20,00,000.00"
    assert format_inr(D("1600000")) == "INR 16,00,000.00"
    assert format_inr(D("-1234.5")) == "-INR 1,234.50"


def test_demo_claims_link_to_expected_evidence():
    p = links()
    assert p[("c-sow", "sale-amt")].relation == "SUPPORTS"
    sow_credit = p[("c-sow", "bank-t1")]
    assert sow_credit.relation == "PARTIALLY_SUPPORTS" and "INR 16,00,000.00 is not evidenced" in sow_credit.rationale
    assert p[("c-sof", "bank-t1")].relation == "SUPPORTS" and p[("c-sof", "sale-amt")].relation == "SUPPORTS"
    assert p[("c-bank", "bank-close")].relation == "SUPPORTS"
    assert p[("c-loan", "ln-out")].relation == "SUPPORTS"
    assert p[("c-inc", "tax-total")].relation == "SUPPORTS"
    assert p[("c-inv", "pf-total")].relation == "SUPPORTS"
    assert p[("c-inv", "pf-h1")].relation == "PARTIALLY_SUPPORTS"


def test_unrelated_and_unsupported_claims_get_no_links():
    p = links()
    assert not [k for k in p if k[0] in {"c-prop", "c-nw"}]  # no property evidence; net worth is calculated
    assert not [k for k in p if k[1] in {"bank-t2", "bank-t3", "bank-t4"}]  # debits are not sale proceeds


def test_mismatching_totals_contradict_or_need_review():
    wrong = [ClaimView("c-loan", "LIABILITY", D("12000000"), "INR", "Outstanding loan")]
    assert links(wrong)[("c-loan", "ln-out")].relation == "CONTRADICTS"
    two = wrong + [ClaimView("c-loan2", "LIABILITY", D("2000000"), "INR", "Car loan")]
    assert links(two)[("c-loan", "ln-out")].relation == "REQUIRES_REVIEW"


def test_non_sale_source_of_wealth_is_not_linked_to_the_sale():
    other = [ClaimView("c-sow", "SOURCE_OF_WEALTH", D("52000000"), "INR", "Inheritance from family")]
    assert links(other) == {}


def test_declaration_form_facts_are_never_evidence():
    from tests.factories import fact

    extra = demo_facts() + [fact("decl-nw", "d-decl", "DECLARED_NET_WORTH", amount="80000000.00")]
    assert not [k for k in links(facts=extra) if k[1] == "decl-nw"]


def test_sale_proceeds_difference_with_formula_and_inputs():
    facts = {f.id: f for f in demo_facts()}
    result = sale_proceeds_difference(facts["sale-amt"], [facts["bank-t1"]])
    assert result.result == D("1600000.00") and result.currency == "INR"
    assert result.input_fact_ids == ("sale-amt", "bank-t1")
    assert "INR 5,20,00,000.00 - (INR 5,04,00,000.00) = INR 16,00,000.00" in result.formula


def test_sale_proceeds_rejects_mixed_currencies():
    from tests.factories import fact

    usd = fact("x", "d", "BANK_TRANSACTION", amount="100.00", currency="USD")
    try:
        sale_proceeds_difference({f.id: f for f in demo_facts()}["sale-amt"], [usd])
    except ValueError as exc:
        assert "different currencies" in str(exc)
    else:
        raise AssertionError("expected ValueError")
