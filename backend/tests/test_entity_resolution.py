from app.domain.entity_resolution import (
    ACCOUNT,
    ASSET,
    CONFIRMED,
    EVENT,
    LIABILITY,
    ORGANIZATION,
    PERSON,
    REJECTED,
    TRANSACTION,
    CustomerAnchor,
    name_similarity,
    resolve_entities,
)
from tests.factories import (
    bank_facts,
    demo_facts,
    fact,
    holding,
    portfolio_facts,
    sale_facts,
)

CASE = "case1"
CUSTOMER = CustomerAnchor("cust-1", "Aarav Mehta", "ABCDE1234F")


def test_name_similarity_rules():
    assert name_similarity("Rahul Sharma", "Rahul Sharma") == 1.0
    assert name_similarity("Mehta Aarav Kumar", "Aarav Kumar Mehta") == 1.0
    assert name_similarity("Mr. Rahul Sharma", "Rahul Sharma") == 1.0
    assert name_similarity("Rahul Sharma", "Rahul Kumar Sharma") == 0.85
    assert name_similarity("Rahul K. Sharma", "Rahul Kumar Sharma") == 0.75
    assert name_similarity("Rahul Sharma", "Rohit Sharma") == 0.0
    assert name_similarity("", "Rahul") == 0.0


def test_demo_case_resolves_to_one_customer_and_shared_entities():
    res = resolve_entities(CASE, demo_facts(), CUSTOMER)

    persons = res.of_kind(PERSON)
    assert len(persons) == 1 and persons[0].is_customer and persons[0].id == "cust-1"
    assert set(persons[0].attrs["names"]) >= {"Aarav Mehta", "Aarav K. Mehta", "Aarav Kumar Mehta", "Mehta Aarav Kumar"}

    accounts = res.of_kind(ACCOUNT)
    assert len(accounts) == 1 and accounts[0].attrs["owner_id"] == "cust-1"
    assert {"sale-acct", "bank-acct"} <= set(accounts[0].fact_ids)

    assets = res.of_kind(ASSET)
    assert len(assets) == 2
    bluechip = next(a for a in assets if a.attrs["isin"] == "INF000Z01AB1")
    assert set(bluechip.fact_ids) == {"pf-h1", "cn-h1"}  # same ISIN and folio in two documents

    assert len(res.of_kind(LIABILITY)) == 1 and len(res.of_kind(TRANSACTION)) == 4
    assert len(res.of_kind(ORGANIZATION)) == 6
    assert not [m for m in res.matches if m.status == "PENDING"]


def test_relations_link_customer_event_and_credit():
    res = resolve_entities(CASE, demo_facts(), CUSTOMER)
    rels = {(r.source, r.type): r for r in res.relations}
    event = res.of_kind(EVENT)[0]
    account = res.of_kind(ACCOUNT)[0]
    credit = next(t for t in res.of_kind(TRANSACTION) if t.attrs["direction"] == "CREDIT")

    assert ("cust-1", "OWNS") in rels and ("cust-1", "OWES") in rels
    assert any(r.source == event.id and r.type == "GENERATED" and r.target == credit.id for r in res.relations)
    assert not any(r.type == "GENERATED" and r.target != credit.id for r in res.relations)
    assert any(r.source == credit.id and r.type == "CREDITED_TO" and r.target == account.id for r in res.relations)
    assert event.attrs["consideration"] == "52000000.00" and event.attrs["seller_id"] == "cust-1"


def test_every_fact_describes_its_entity():
    res = resolve_entities(CASE, demo_facts(), CUSTOMER)
    assert "sale-amt" in res.entities[res.of_kind(EVENT)[0].id].fact_ids
    assert res.fact_entities["bank-close"] == [res.of_kind(ACCOUNT)[0].id]
    assert res.fact_entities["tax-total"] == ["cust-1"]


def test_weaker_name_match_becomes_pending_candidate_and_blocks_account_merge():
    facts = sale_facts() + bank_facts(holder="Aarav Kumar Mehta")  # holder has no PAN
    res = resolve_entities(CASE, facts, CUSTOMER)

    pending = [m for m in res.matches if m.status == "PENDING"]
    assert len(pending) == 1 and pending[0].kind == "person" and pending[0].score == 0.85
    assert len(res.of_kind(PERSON)) == 2
    assert len(res.of_kind(ACCOUNT)) == 2  # owners differ until the analyst decides

    after = resolve_entities(CASE, facts, CUSTOMER, {pending[0].key: CONFIRMED})
    assert len(after.of_kind(PERSON)) == 1 and len(after.of_kind(ACCOUNT)) == 1
    assert [m.status for m in after.matches if m.kind == "person" and m.method == "ANALYST"] == [CONFIRMED]


def test_rejected_candidate_is_not_raised_again():
    facts = sale_facts() + bank_facts(holder="Aarav Kumar Mehta")
    key = next(m.key for m in resolve_entities(CASE, facts, CUSTOMER).matches if m.status == "PENDING")
    res = resolve_entities(CASE, facts, CUSTOMER, {key: REJECTED})
    assert not [m for m in res.matches if m.status == "PENDING"] and len(res.of_kind(PERSON)) == 2


def test_different_pans_never_merge_even_with_the_same_name():
    facts = (
        [fact("a-n", "d1", "PARTY_NAME", normalized={"value": "Aarav Mehta", "role": "seller"}),
         fact("a-p", "d1", "PARTY_PAN", normalized={"value": "ZZZZZ9999Z", "role": "seller"})]
    )
    res = resolve_entities(CASE, facts, CUSTOMER)
    persons = res.of_kind(PERSON)
    assert len(persons) == 2 and not res.matches


def test_same_isin_without_folio_is_a_candidate_not_a_merge():
    facts = [
        holding("h1", "d1", "INF000Z01AB1", "11223344/01", "10000000.00"),
        holding("h2", "d2", "INF000Z01AB1", None, "10000000.00"),
        holding("h3", "d3", "INF000Z01AB1", "99999999/09", "5000000.00"),
    ]
    res = resolve_entities(CASE, facts, None)
    assert len(res.of_kind(ASSET)) == 3  # different folio is a different holding
    assert {m.status for m in res.matches} == {"PENDING"}


def test_resolution_is_deterministic_and_idempotent():
    a = resolve_entities(CASE, demo_facts(), CUSTOMER)
    b = resolve_entities(CASE, list(reversed(demo_facts())), CUSTOMER)
    assert set(a.entities) == set(b.entities)
    assert {(r.source, r.type, r.target) for r in a.relations} == {(r.source, r.type, r.target) for r in b.relations}
    assert len(portfolio_facts()) > 0
