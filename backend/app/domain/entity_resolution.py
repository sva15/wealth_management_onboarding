"""Deterministic entity resolution over extracted facts.

Merges happen automatically only on strong evidence (same PAN, registration id, ISIN + folio, or
the same account suffix with the same owner, or an exactly equal normalised name). Weaker matches
become PENDING candidates for an analyst. A PAN conflict always blocks a merge. Analyst decisions
(keyed by match key) override the rules. No model is involved.
"""
import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.domain.facts import FactView

AUTO_THRESHOLD = 0.95
CANDIDATE_THRESHOLD = 0.7
_JACCARD_CANDIDATE = 0.6

AUTO = "AUTO_ACCEPTED"
PENDING = "PENDING"
CONFIRMED = "CONFIRMED"
REJECTED = "REJECTED"

PERSON, ORGANIZATION, ACCOUNT = "PERSON", "ORGANIZATION", "ACCOUNT"
ASSET, LIABILITY, TRANSACTION, EVENT = "ASSET", "LIABILITY", "TRANSACTION", "FINANCIAL_EVENT"

_TITLES = {"mr", "mrs", "ms", "miss", "dr", "shri", "smt", "mx"}
_ORG_NOISE = {"private", "pvt", "limited", "ltd", "llp", "inc", "the", "fictional"}


# --- data ------------------------------------------------------------------
@dataclass(frozen=True)
class CustomerAnchor:
    id: str
    name: str
    pan: str | None = None


@dataclass
class Entity:
    id: str
    kind: str
    label: str
    attrs: dict[str, Any] = field(default_factory=dict)
    fact_ids: list[str] = field(default_factory=list)
    is_customer: bool = False


@dataclass(frozen=True)
class Relation:
    source: str
    type: str
    target: str
    props: dict[str, Any] = field(default_factory=dict)


@dataclass
class MatchRecord:
    key: str
    kind: str
    left_ref: str
    right_ref: str
    left_label: str
    right_label: str
    score: float
    method: str
    explanation: str
    status: str


@dataclass
class Resolution:
    entities: dict[str, Entity] = field(default_factory=dict)
    relations: list[Relation] = field(default_factory=list)
    matches: list[MatchRecord] = field(default_factory=list)
    fact_entities: dict[str, list[str]] = field(default_factory=dict)

    def of_kind(self, kind: str) -> list[Entity]:
        return [e for e in self.entities.values() if e.kind == kind]


# --- name and text helpers ------------------------------------------------------
def name_tokens(name: str) -> list[str]:
    cleaned = re.sub(r"[^a-z0-9 ]", " ", name.lower().replace(".", " "))
    return [t for t in cleaned.split() if t not in _TITLES]


def name_similarity(a: str, b: str) -> float:
    """1.0 same token set; 0.85 strict subset with equal tokens; 0.75 when initials are involved."""
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return 0.0
    if set(ta) == set(tb):
        return 1.0
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    remaining = list(long_)
    unmatched = []
    for token in short:
        if token in remaining:
            remaining.remove(token)
        else:
            unmatched.append(token)
    used_initial = False
    for token in unmatched:
        match = next(
            (r for r in remaining if (len(token) == 1 and r.startswith(token)) or (len(r) == 1 and token.startswith(r))),
            None,
        )
        if match is None:
            return 0.0
        remaining.remove(match)
        used_initial = True
    return 0.75 if used_initial else 0.85


def normalise_org(name: str) -> str:
    tokens = [t for t in re.sub(r"[^a-z0-9 ]", " ", name.lower()).split() if t not in _ORG_NOISE]
    return " ".join(tokens)


def org_similarity(a: str, b: str) -> float:
    na, nb = normalise_org(a), normalise_org(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    sa, sb = set(na.split()), set(nb.split())
    return len(sa & sb) / len(sa | sb)


def _alnum(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _digest(*parts: Any) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


class _UnionFind:
    def __init__(self, items: list[str]) -> None:
        self._parent = {i: i for i in items}

    def find(self, x: str) -> str:
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        self._parent[self.find(a)] = self.find(b)


def _pair_key(kind: str, a: str, b: str) -> str:
    left, right = sorted((a, b))
    return f"{kind}:{left}:{right}"


@dataclass
class _Mention:
    ref: str
    doc_id: str
    role: str
    label: str
    ident: str | None = None  # PAN / registration id / account suffix
    fact_ids: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


class _Ctx:
    def __init__(self, case_id: str, facts: list[FactView], decisions: dict[str, str]) -> None:
        self.case_id = case_id
        self.facts = facts
        self.decisions = decisions
        self.by_doc: dict[str, list[FactView]] = {}
        for f in facts:
            self.by_doc.setdefault(f.document_id, []).append(f)
        self.res = Resolution()
        self.person_of: dict[tuple[str, str], str] = {}
        self.org_of: dict[tuple[str, str], str] = {}
        self.account_of_doc: dict[str, str] = {}
        self.settlement_account_of_doc: dict[str, str] = {}

    def describe(self, fact_id: str, entity_id: str) -> None:
        ids = self.res.fact_entities.setdefault(fact_id, [])
        if entity_id not in ids:
            ids.append(entity_id)
        entity = self.res.entities[entity_id]
        if fact_id not in entity.fact_ids:
            entity.fact_ids.append(fact_id)

    def relate(self, source: str, rel: str, target: str, **props: Any) -> None:
        relation = Relation(source, rel, target, props)
        if relation not in self.res.relations:
            self.res.relations.append(relation)


def _role(f: FactView) -> str | None:
    return f.normalized.get("role")


def _value(f: FactView) -> str:
    return str(f.normalized.get("value", ""))


# --- clustering with decisions -----------------------------------------------------
def _cluster(
    ctx: _Ctx,
    kind: str,
    mentions: list[_Mention],
    score_fn,
    *,
    ident_conflict: bool = False,
) -> dict[str, list[_Mention]]:
    """Union mentions by rule or decision and queue weaker pairs as candidates. Returns root -> members."""
    uf = _UnionFind([m.ref for m in mentions])
    by_ref = {m.ref: m for m in mentions}

    def idents(root: str) -> set[str]:
        return {m.ident for m in mentions if m.ident and uf.find(m.ref) == root}

    def can_merge(a: _Mention, b: _Mention) -> bool:
        ra, rb = uf.find(a.ref), uf.find(b.ref)
        return not (ident_conflict and len(idents(ra) | idents(rb)) > 1)

    def merge(a: _Mention, b: _Mention, score: float, method: str, explanation: str, status: str) -> None:
        if uf.find(a.ref) == uf.find(b.ref) or not can_merge(a, b):
            return
        uf.union(a.ref, b.ref)
        ctx.res.matches.append(
            MatchRecord(_pair_key(kind, a.ref, b.ref), kind, a.ref, b.ref, a.label, b.label, score, method, explanation, status)
        )

    pairs = [(a, b) for i, a in enumerate(mentions) for b in mentions[i + 1 :]]
    scored = []
    rejected: list[tuple[_Mention, _Mention]] = []
    for a, b in pairs:
        key = _pair_key(kind, a.ref, b.ref)
        decision = ctx.decisions.get(key)
        score, method, explanation = score_fn(a, b)
        if decision == REJECTED:
            rejected.append((a, b))
            continue
        if decision == CONFIRMED:
            merge(a, b, max(score, CANDIDATE_THRESHOLD), "ANALYST", "Confirmed by an analyst", CONFIRMED)
        elif score >= AUTO_THRESHOLD:
            scored.append((0, a, b, score, method, explanation))
        elif score >= CANDIDATE_THRESHOLD:
            scored.append((1, a, b, score, method, explanation))
    # Strong rules first so that candidates are only raised between clusters that remain separate.
    for _, a, b, score, method, explanation in (s for s in scored if s[0] == 0):
        merge(a, b, score, method, explanation, AUTO)

    # An analyst rejection covers the whole pair of clusters, not just the two mentions.
    rejected_clusters = {tuple(sorted((uf.find(a.ref), uf.find(b.ref)))) for a, b in rejected}
    seen_cluster_pairs: dict[tuple[str, str], tuple] = {}
    for _, a, b, score, method, explanation in (s for s in scored if s[0] == 1):
        ra, rb = uf.find(a.ref), uf.find(b.ref)
        if ra == rb or not can_merge(a, b) or tuple(sorted((ra, rb))) in rejected_clusters:
            continue
        cp = tuple(sorted((ra, rb)))
        if cp not in seen_cluster_pairs or score > seen_cluster_pairs[cp][2]:
            seen_cluster_pairs[cp] = (a, b, score, method, explanation)
    for a, b, score, method, explanation in seen_cluster_pairs.values():
        ctx.res.matches.append(
            MatchRecord(_pair_key(kind, a.ref, b.ref), kind, a.ref, b.ref, a.label, b.label, score, method, explanation, PENDING)
        )

    clusters: dict[str, list[_Mention]] = {}
    for m in mentions:
        clusters.setdefault(uf.find(m.ref), []).append(by_ref[m.ref])
    return clusters


# --- persons -----------------------------------------------------------------------
def _resolve_persons(ctx: _Ctx, customer: CustomerAnchor | None) -> None:
    mentions: list[_Mention] = []
    if customer:
        mentions.append(_Mention(customer.id, "", "customer", customer.name, customer.pan, []))
    for doc_id, facts in ctx.by_doc.items():
        pans = {_role(f): f for f in facts if f.fact_type == "PARTY_PAN"}
        for f in facts:
            if f.fact_type != "PARTY_NAME":
                continue
            pan_fact = pans.get(_role(f))
            ids = [f.id] + ([pan_fact.id] if pan_fact else [])
            mentions.append(
                _Mention(f.id, doc_id, _role(f) or "", _value(f), _value(pan_fact).upper() if pan_fact else None, ids)
            )

    def score(a: _Mention, b: _Mention):
        if a.ident and b.ident:
            if a.ident == b.ident:
                return 1.0, "PAN", "Same PAN"
            return 0.0, "PAN", "Different PAN"
        s = name_similarity(a.label, b.label)
        return s, "NAME", f"Name similarity {s:.2f} ('{a.label}' vs '{b.label}')"

    clusters = _cluster(ctx, "person", mentions, score, ident_conflict=True)
    for root, members in clusters.items():
        anchor = next((m for m in members if customer and m.ref == customer.id), None)
        entity_id = customer.id if anchor else f"person:{ctx.case_id}:{min(m.ref for m in members)}"
        names = sorted({m.label for m in members})
        pans = sorted({m.ident for m in members if m.ident})
        ctx.res.entities[entity_id] = Entity(
            entity_id, PERSON, names[0] if not anchor else anchor.label, {"names": names, "pans": pans}, [], bool(anchor)
        )
        for m in members:
            for fid in m.fact_ids:
                ctx.describe(fid, entity_id)
            if m.doc_id:
                ctx.person_of[(m.doc_id, m.role)] = entity_id


# --- organizations --------------------------------------------------------------------
def _resolve_orgs(ctx: _Ctx) -> None:
    mentions: list[_Mention] = []
    for doc_id, facts in ctx.by_doc.items():
        regs = {_role(f): f for f in facts if f.fact_type == "REGISTRATION_ID"}
        for f in facts:
            if f.fact_type != "ORGANIZATION_NAME":
                continue
            reg = regs.get(_role(f))
            mentions.append(
                _Mention(f.id, doc_id, _role(f) or "", _value(f), _value(reg).upper() if reg else None,
                         [f.id] + ([reg.id] if reg else []))
            )

    def score(a: _Mention, b: _Mention):
        if a.ident and b.ident and a.ident == b.ident:
            return 1.0, "REGISTRATION_ID", "Same registration id"
        s = org_similarity(a.label, b.label)
        if s >= 1.0:
            return 1.0, "NAME_EXACT", "Same normalised name"
        if s >= _JACCARD_CANDIDATE:
            return CANDIDATE_THRESHOLD, "NAME_SIMILAR", f"Organisation name overlap {s:.2f}"
        return 0.0, "NAME", "No match"

    for members in _cluster(ctx, "organization", mentions, score, ident_conflict=True).values():
        reg = next((m.ident for m in members if m.ident), None)
        key = reg or _digest(normalise_org(members[0].label))
        entity_id = f"org:{ctx.case_id}:{key}"
        label = max((m.label for m in members), key=len)
        ctx.res.entities[entity_id] = Entity(entity_id, ORGANIZATION, label, {"registration_id": reg})
        for m in members:
            for fid in m.fact_ids:
                ctx.describe(fid, entity_id)
            ctx.org_of[(m.doc_id, m.role)] = entity_id


# --- accounts --------------------------------------------------------------------------
_ACCOUNT_OWNER_ROLE = {"account_suffix": "account_holder", "settlement_account_suffix": "seller"}


def _resolve_accounts(ctx: _Ctx) -> None:
    mentions: list[_Mention] = []
    for doc_id, facts in ctx.by_doc.items():
        for f in facts:
            kind = f.normalized.get("kind")
            if f.fact_type == "ACCOUNT_IDENTIFIER" and kind in _ACCOUNT_OWNER_ROLE:
                owner = ctx.person_of.get((doc_id, _ACCOUNT_OWNER_ROLE[kind]))
                mentions.append(
                    _Mention(f.id, doc_id, kind, _value(f), _value(f), [f.id], {"owner": owner})
                )

    def score(a: _Mention, b: _Mention):
        if a.ident != b.ident:
            return 0.0, "ACCOUNT_SUFFIX", "Different suffix"
        oa, ob = a.extra["owner"], b.extra["owner"]
        if oa and ob:
            if oa == ob:
                return AUTO_THRESHOLD, "ACCOUNT_SUFFIX_OWNER", "Same account suffix and same resolved owner"
            return 0.0, "ACCOUNT_SUFFIX_OWNER", "Same suffix but different owners"
        return CANDIDATE_THRESHOLD, "ACCOUNT_SUFFIX", "Same account suffix; owner unknown"

    for members in _cluster(ctx, "account", mentions, score).values():
        owner = next((m.extra["owner"] for m in members if m.extra["owner"]), None)
        suffix = members[0].ident
        entity_id = f"account:{ctx.case_id}:{suffix}:{_digest(owner)}"
        bank = next(
            (ctx.org_of.get((m.doc_id, "bank")) for m in members if ctx.org_of.get((m.doc_id, "bank"))), None
        )
        ctx.res.entities[entity_id] = Entity(
            entity_id, ACCOUNT, f"Account ending {suffix}", {"suffix": suffix, "owner_id": owner, "bank_id": bank}
        )
        for m in members:
            ctx.describe(m.ref, entity_id)
            if m.role == "account_suffix":
                ctx.account_of_doc[m.doc_id] = entity_id
            else:
                ctx.settlement_account_of_doc[m.doc_id] = entity_id
        if owner:
            ctx.relate(owner, "OWNS", entity_id)
        if bank:
            ctx.relate(entity_id, "HELD_AT", bank)


# --- liabilities --------------------------------------------------------------------------
_LIABILITY_FACTS = {"LIABILITY_SANCTIONED", "LIABILITY_OUTSTANDING", "LIABILITY_INTEREST_RATE", "LIABILITY_EMI"}


def _resolve_liabilities(ctx: _Ctx) -> None:
    for doc_id, facts in ctx.by_doc.items():
        liability_facts = [f for f in facts if f.fact_type in _LIABILITY_FACTS]
        if not liability_facts:
            continue
        loan_fact = next(
            (f for f in facts if f.fact_type == "ACCOUNT_IDENTIFIER" and f.normalized.get("kind") == "loan_account"),
            None,
        )
        key = _alnum(_value(loan_fact)) if loan_fact else f"doc{doc_id[:8]}"
        entity_id = f"liability:{ctx.case_id}:{key}"
        owner = ctx.person_of.get((doc_id, "borrower"))
        lender = ctx.org_of.get((doc_id, "lender"))
        label = f"Loan {_value(loan_fact)}" if loan_fact else "Loan"
        existing = ctx.res.entities.get(entity_id)
        if existing is None:
            ctx.res.entities[entity_id] = Entity(
                entity_id, LIABILITY, label, {"owner_id": owner, "lender_id": lender, "loan_account": _value(loan_fact) if loan_fact else None}
            )
        else:
            first = existing.fact_ids[0] if existing.fact_ids else entity_id
            ctx.res.matches.append(
                MatchRecord(_pair_key("liability", first, (loan_fact or liability_facts[0]).id), "liability", first,
                            (loan_fact or liability_facts[0]).id, existing.label, label, 1.0, "LOAN_ACCOUNT_NUMBER",
                            "Same loan account number", AUTO)
            )
        for f in liability_facts + ([loan_fact] if loan_fact else []):
            ctx.describe(f.id, entity_id)
        if owner:
            ctx.relate(owner, "OWES", entity_id)
        if lender:
            ctx.relate(entity_id, "OWED_TO", lender)


# --- assets ---------------------------------------------------------------------------------
def _resolve_assets(ctx: _Ctx) -> None:
    holdings = [f for f in ctx.facts if f.fact_type == "PORTFOLIO_HOLDING"]
    mentions = [
        _Mention(
            f.id, f.document_id, "holding", f.normalized.get("instrument_name") or "holding",
            None, [f.id],
            {"isin": f.normalized.get("isin"), "folio": _alnum(f.normalized.get("folio") or "")},
        )
        for f in holdings
    ]

    def score(a: _Mention, b: _Mention):
        ia, ib = a.extra["isin"], b.extra["isin"]
        if not ia or ia != ib:
            return 0.0, "ISIN", "Different or missing ISIN"
        fa, fb = a.extra["folio"], b.extra["folio"]
        if fa and fb:
            if fa == fb:
                return 1.0, "ISIN_FOLIO", "Same ISIN and folio"
            return 0.0, "ISIN_FOLIO", "Same ISIN, different folio"
        return CANDIDATE_THRESHOLD, "ISIN", "Same ISIN; folio missing on one side"

    for members in _cluster(ctx, "asset", mentions, score).values():
        first = members[0]
        isin, folio = first.extra["isin"], next((m.extra["folio"] for m in members if m.extra["folio"]), "")
        entity_id = f"asset:{ctx.case_id}:{isin}:{folio}" if isin else f"asset:{ctx.case_id}:{first.ref}"
        docs = sorted({m.doc_id for m in members})
        owners = sorted({o for d in docs if (o := ctx.person_of.get((d, "investor")))})
        reporters = sorted({o for d in docs if (o := ctx.org_of.get((d, "institution")))})
        label = sorted(m.label for m in members)[0]
        ctx.res.entities[entity_id] = Entity(
            entity_id, ASSET, label,
            {"isin": isin, "folio": folio, "owner_id": owners[0] if owners else None,
             "reporting_institution_ids": reporters, "asset_type": "INVESTMENT"},
        )
        for m in members:
            ctx.describe(m.ref, entity_id)
        for owner in owners:
            ctx.relate(owner, "OWNS", entity_id)
        for reporter in reporters:
            ctx.relate(entity_id, "REPORTED_BY", reporter)


# --- transactions and events ------------------------------------------------------------------------
def _resolve_transactions(ctx: _Ctx) -> None:
    for f in ctx.facts:
        if f.fact_type != "BANK_TRANSACTION":
            continue
        account = ctx.account_of_doc.get(f.document_id)
        direction = f.normalized.get("direction", "")
        key = _digest(account, f.normalized.get("reference") or f.normalized.get("narration"),
                      f.effective_date, f.amount, direction)
        entity_id = f"txn:{ctx.case_id}:{key}"
        if entity_id not in ctx.res.entities:
            ctx.res.entities[entity_id] = Entity(
                entity_id, TRANSACTION, f.normalized.get("narration") or "Transaction",
                {
                    "direction": direction,
                    "amount": str(f.amount),
                    "currency": f.currency,
                    "date": f.effective_date.isoformat() if f.effective_date else None,
                    "reference": f.normalized.get("reference"),
                    "account_id": account,
                },
            )
            if account:
                ctx.relate(entity_id, "CREDITED_TO" if direction == "CREDIT" else "DEBITED_FROM", account)
        ctx.describe(f.id, entity_id)


def _resolve_events(ctx: _Ctx, customer: CustomerAnchor | None) -> None:
    for doc_id, facts in ctx.by_doc.items():
        sale_facts = [f for f in facts if f.fact_type in {"SALE_CONSIDERATION", "SALE_AGREEMENT_DATE", "SALE_PAYMENT_DATE"}]
        if not sale_facts:
            continue
        ref_fact = next((f for f in facts if f.fact_type == "DOCUMENT_REFERENCE"), None)
        reference = _value(ref_fact) if ref_fact else None
        consideration = next((f for f in sale_facts if f.fact_type == "SALE_CONSIDERATION"), None)
        agreed = next((f for f in sale_facts if f.fact_type == "SALE_AGREEMENT_DATE"), None)
        entity_id = f"event:{ctx.case_id}:{_alnum(reference) if reference else doc_id[:8]}"
        seller = ctx.person_of.get((doc_id, "seller"))
        purchaser = ctx.org_of.get((doc_id, "purchaser"))
        target = ctx.org_of.get((doc_id, "target_company"))
        ctx.res.entities[entity_id] = Entity(
            entity_id, EVENT, f"Company sale {reference}" if reference else "Company sale",
            {
                "event_type": "COMPANY_SALE",
                "reference": reference,
                "date": agreed.effective_date.isoformat() if agreed and agreed.effective_date else None,
                "consideration": str(consideration.amount) if consideration and consideration.amount is not None else None,
                "currency": consideration.currency if consideration else None,
                "seller_id": seller,
                "purchaser_id": purchaser,
                "target_id": target,
                "settlement_account_id": ctx.settlement_account_of_doc.get(doc_id),
            },
        )
        for f in sale_facts + ([ref_fact] if ref_fact else []):
            ctx.describe(f.id, entity_id)
        if seller:
            ctx.relate(seller, "PARTICIPATED_IN", entity_id, role="SELLER")
        for org, role in ((purchaser, "PURCHASER"), (target, "TARGET")):
            if org:
                ctx.relate(entity_id, "INVOLVES", org, role=role)
        # An event generated a transaction when the transaction carries the agreement reference.
        token = _alnum(reference) if reference else ""
        if len(token) >= 6:
            for txn in ctx.res.of_kind(TRANSACTION):
                text = _alnum(f"{txn.label} {txn.attrs.get('reference') or ''}")
                if token in text:
                    ctx.relate(entity_id, "GENERATED", txn.id, method="REFERENCE_MATCH")


# --- fact-level descriptions that depend on resolved entities ---------------------------------------
def _describe_statement_facts(ctx: _Ctx) -> None:
    role_for = {
        "TAX_ASSESSMENT_YEAR": "taxpayer", "TAX_INCOME_ITEM": "taxpayer", "TAX_TOTAL_INCOME": "taxpayer",
        "TAX_PAID": "taxpayer", "PORTFOLIO_TOTAL_VALUE": "investor",
        "DECLARATION_DATE": "customer", "DECLARED_NET_WORTH": "customer", "DECLARED_SALE_VALUE": "customer",
        "DECLARED_INTENDED_INVESTMENT": "customer", "DECLARED_INVESTMENTS": "customer",
        "DECLARED_BANK_DEPOSITS": "customer", "DECLARED_LOAN": "customer", "DECLARED_PROPERTY": "customer",
        "DECLARED_SOURCE_OF_WEALTH": "customer", "DECLARED_SOURCE_OF_FUNDS": "customer",
    }
    for f in ctx.facts:
        if f.fact_type in role_for:
            person = ctx.person_of.get((f.document_id, role_for[f.fact_type]))
            if person:
                ctx.describe(f.id, person)
        elif f.fact_type in {"BANK_OPENING_BALANCE", "BANK_CLOSING_BALANCE"}:
            account = ctx.account_of_doc.get(f.document_id)
            if account:
                ctx.describe(f.id, account)


def resolve_entities(
    case_id: str,
    facts: list[FactView],
    customer: CustomerAnchor | None,
    decisions: dict[str, str] | None = None,
) -> Resolution:
    """Resolve entities for one case. `decisions` maps match key -> CONFIRMED | REJECTED."""
    ctx = _Ctx(case_id, facts, decisions or {})
    _resolve_persons(ctx, customer)
    _resolve_orgs(ctx)
    _resolve_accounts(ctx)
    _resolve_liabilities(ctx)
    _resolve_assets(ctx)
    _resolve_transactions(ctx)
    _resolve_events(ctx, customer)
    _describe_statement_facts(ctx)
    return ctx.res
