"""Deterministic reconciliation engine.

Evidence-backed totals are built only from extracted facts through resolved entities, using Decimal.
Stale evidence, resolved or unresolved duplicates, other owners and foreign currencies are excluded
from verified totals and reported. No model is involved.
"""
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from decimal import Decimal

from app.domain.entity_resolution import ACCOUNT, ASSET, EVENT, LIABILITY, PENDING, TRANSACTION, Resolution
from app.domain.enums import ClaimType, VerificationStatus
from app.domain.evidence_linking import SALE_WORDS
from app.domain.facts import FactView
from app.domain.money import format_inr
from app.domain.reconciliation.calculations import CalculationResult, sale_proceeds_difference
from app.domain.reconciliation.conflicts import build_requirements, detect_conflicts
from app.domain.reconciliation.policy import ReconciliationPolicy
from app.domain.reconciliation.state import (
    ClaimResult,
    Component,
    Exclusion,
    ReconClaim,
    ReconciliationResult,
    ReconState,
    SaleCheck,
)

ZERO = Decimal("0")
CENT = Decimal("0.01")
VERIFIED = VerificationStatus.VERIFIED.value
PARTIAL = VerificationStatus.PARTIALLY_VERIFIED.value
CONTRADICTED = VerificationStatus.CONTRADICTED.value
UNVERIFIED = VerificationStatus.UNVERIFIED.value
STALE = VerificationStatus.STALE.value

BANK, INVESTMENT, LIABILITY_KIND, INCOME, PROCEEDS = "BANK_BALANCE", "INVESTMENT", "LIABILITY", "INCOME", "SALE_PROCEEDS"


def _cite(f: FactView) -> str:
    return f"{f.document_name} p.{f.page}"


def _age(f: FactView, as_of: date) -> int | None:
    return (as_of - f.effective_date).days if f.effective_date else None


@dataclass
class _Chosen:
    fact: FactView | None = None
    duplicates: list[FactView] = field(default_factory=list)
    unresolved: list[FactView] = field(default_factory=list)
    stale: list[FactView] = field(default_factory=list)


def _choose(st: ReconState, facts: list[FactView], kind: str) -> _Chosen:
    """Pick the single value to rely on for one entity, recording every exclusion with its reason."""
    out = _Chosen()
    usable: list[FactView] = []
    for f in facts:
        if f.amount is None:
            continue
        if f.currency != st.currency:
            st.exclusions.append(Exclusion(f.id, kind, "CURRENCY_MISMATCH", f.amount, f"{f.currency} vs {st.currency}"))
            continue
        limit, age = st.policy.staleness_for(f.fact_type), _age(f, st.as_of)
        if limit is not None and age is not None and age > limit:
            st.exclusions.append(Exclusion(f.id, kind, "STALE", f.amount, f"{age} days old; limit {limit}"))
            st.stale_facts.append((f, kind, age, limit))
            out.stale.append(f)
            continue
        usable.append(f)
    if not usable:
        if out.stale:
            newest = max(out.stale, key=lambda f: (f.effective_date or date.min, f.confidence))
            st.stale_entity_values.append((kind, newest.amount))
        return out

    latest = max((f.effective_date for f in usable if f.effective_date), default=None)
    top = [f for f in usable if f.effective_date == latest]
    for f in usable:
        if f not in top:
            st.exclusions.append(Exclusion(f.id, kind, "OLDER_VALUE", f.amount, "A newer value is available"))
    if len({f.amount for f in top}) == 1:
        out.fact = max(top, key=lambda f: f.confidence)
        out.duplicates = [f for f in top if f is not out.fact]
        for f in out.duplicates:
            st.exclusions.append(Exclusion(f.id, kind, "DUPLICATE_RESOLVED", f.amount, "Same value on the same date; counted once"))
    else:
        out.unresolved = top
        for f in top:
            st.exclusions.append(Exclusion(f.id, kind, "DUPLICATE_UNRESOLVED", f.amount, "Same item with different values on the same date"))
    return out


def _entity_facts(st: ReconState, entity_fact_ids: list[str], fact_type: str) -> list[FactView]:
    return [st.facts[i] for i in entity_fact_ids if i in st.facts and st.facts[i].fact_type == fact_type]


def _owner_mismatch(st: ReconState, entity, facts: list[FactView], kind: str) -> bool:
    owner = entity.attrs.get("owner_id")
    if owner and owner != st.customer_id:
        st.owner_mismatches.append((entity, owner, facts))
        for f in facts:
            st.exclusions.append(Exclusion(f.id, kind, "OWNER_NOT_CUSTOMER", f.amount, "Documented owner is not the customer"))
        return True
    return False


def _add_component(st: ReconState, kind: str, label: str, fact: FactView, entity_id: str | None) -> None:
    st.components.append(
        Component(kind, label, fact.amount, fact.currency, fact.effective_date, _age(fact, st.as_of), (fact.id,), entity_id)
    )


def _collect_bank(st: ReconState) -> None:
    for acct in st.resolution.of_kind(ACCOUNT):
        facts = _entity_facts(st, acct.fact_ids, "BANK_CLOSING_BALANCE")
        if not facts or _owner_mismatch(st, acct, facts, BANK):
            continue
        ch = _choose(st, facts, BANK)
        if ch.fact:
            _add_component(st, BANK, acct.label, ch.fact, acct.id)


def _pending_asset_entities(st: ReconState) -> set[str]:
    """Holdings that may duplicate another (same ISIN, folio missing) stay out of totals until decided."""
    pending: set[str] = set()
    for m in st.resolution.matches:
        if m.kind != "asset" or m.status != PENDING:
            continue
        ents = [e for ref in (m.left_ref, m.right_ref) for e in st.resolution.fact_entities.get(ref, [])[:1]]
        folioless = [e for e in ents if not st.resolution.entities[e].attrs.get("folio")]
        pending.update(folioless or ents)
    return pending


def _collect_investments(st: ReconState) -> None:
    pending = _pending_asset_entities(st)
    for asset in st.resolution.of_kind(ASSET):
        facts = _entity_facts(st, asset.fact_ids, "PORTFOLIO_HOLDING")
        if not facts or _owner_mismatch(st, asset, facts, INVESTMENT):
            continue
        if asset.id in pending:
            st.unresolved_duplicates.append((asset, facts))
            for f in facts:
                st.exclusions.append(Exclusion(f.id, INVESTMENT, "DUPLICATE_UNRESOLVED", f.amount, "Possible duplicate awaiting analyst confirmation"))
            continue
        ch = _choose(st, facts, INVESTMENT)
        if ch.fact:
            _add_component(st, INVESTMENT, asset.label, ch.fact, asset.id)
            if ch.duplicates:
                st.resolved_duplicates.append((asset, ch.fact, ch.duplicates))
        if ch.unresolved:
            st.different_values.append((asset, ch.unresolved))

    holdings_by_doc: dict[str, list[FactView]] = {}
    for f in st.facts.values():
        if f.fact_type == "PORTFOLIO_HOLDING" and f.amount is not None:
            holdings_by_doc.setdefault(f.document_id, []).append(f)
    for f in st.facts.values():
        if f.fact_type == "PORTFOLIO_TOTAL_VALUE" and f.amount is not None and f.document_id in holdings_by_doc:
            total = sum((h.amount for h in holdings_by_doc[f.document_id]), ZERO)
            if abs(total - f.amount) > st.policy.tolerance:
                st.portfolio_mismatches.append((f.document_id, f.document_name, f, total))


def _collect_liabilities(st: ReconState) -> None:
    for loan in st.resolution.of_kind(LIABILITY):
        facts = _entity_facts(st, loan.fact_ids, "LIABILITY_OUTSTANDING")
        if not facts or _owner_mismatch(st, loan, facts, LIABILITY_KIND):
            continue
        ch = _choose(st, facts, LIABILITY_KIND)
        if ch.fact:
            _add_component(st, LIABILITY_KIND, loan.label, ch.fact, loan.id)
        if ch.unresolved:
            st.different_values.append((loan, ch.unresolved))


def _collect_income(st: ReconState) -> Decimal:
    facts = [f for f in st.facts.values() if f.fact_type == "TAX_TOTAL_INCOME"]
    ch = _choose(st, facts, INCOME)
    if ch.fact:
        _add_component(st, INCOME, "Total income per tax summary", ch.fact, None)
        return ch.fact.amount
    return ZERO


def _collect_sales(st: ReconState) -> None:
    transactions = {e.id: e for e in st.resolution.of_kind(TRANSACTION)}
    for event in st.resolution.of_kind(EVENT):
        if event.attrs.get("event_type") != "COMPANY_SALE":
            continue
        considerations = sorted(
            _entity_facts(st, event.fact_ids, "SALE_CONSIDERATION"), key=lambda f: -f.confidence
        )
        if not considerations or considerations[0].amount is None:
            continue
        consideration = considerations[0]
        credits: list[FactView] = []
        duplicates: list[FactView] = []
        for rel in st.resolution.relations:
            txn = transactions.get(rel.target)
            if rel.source != event.id or rel.type != "GENERATED" or txn is None or txn.attrs.get("direction") != "CREDIT":
                continue
            txn_facts = sorted((st.facts[i] for i in txn.fact_ids if i in st.facts), key=lambda f: -f.confidence)
            if not txn_facts:
                continue
            best = txn_facts[0]
            if best.currency != consideration.currency:
                st.exclusions.append(Exclusion(best.id, PROCEEDS, "CURRENCY_MISMATCH", best.amount, f"{best.currency} vs {consideration.currency}"))
                continue
            credits.append(best)
            for dup in txn_facts[1:]:
                duplicates.append(dup)
                st.exclusions.append(Exclusion(dup.id, PROCEEDS, "DUPLICATE_RESOLVED", dup.amount, "Same credit in another statement; counted once"))
        calc = sale_proceeds_difference(consideration, credits, tuple(f.id for f in duplicates))
        status = (
            "NO_PROCEEDS_OBSERVED" if not credits
            else "RECONCILED" if calc.result == 0
            else "UNEXPLAINED_DIFFERENCE" if calc.result > 0 else "EXCESS_RECEIVED"
        )
        st.sale_checks.append(
            SaleCheck(event.id, event.attrs.get("reference"), event.attrs.get("date"), consideration, credits, duplicates, calc, status)
        )
        for c in credits:
            _add_component(st, PROCEEDS, c.normalized.get("narration") or "Bank credit", c, None)
        st.observed_sale_proceeds += sum((c.amount for c in credits), ZERO)


_BALANCE_FACT_KINDS = {
    "BANK_CLOSING_BALANCE": BANK,
    "PORTFOLIO_HOLDING": INVESTMENT,
    "LIABILITY_OUTSTANDING": LIABILITY_KIND,
}


def _collect_unlinked(st: ReconState) -> None:
    """Balance-type facts that no entity claimed are reported, never silently dropped."""
    handled = {i for c in st.components for i in c.fact_ids} | {e.fact_id for e in st.exclusions}
    for f in st.facts.values():
        kind = _BALANCE_FACT_KINDS.get(f.fact_type)
        if kind and f.amount is not None and f.id not in handled:
            st.unlinked.append(f)
            st.exclusions.append(Exclusion(f.id, kind, "UNLINKED", f.amount, "Not linked to a resolved account, holding or loan"))


# --- totals ----------------------------------------------------------------------------------
def _sum(st: ReconState, kind: str) -> Decimal:
    return sum((c.amount for c in st.components if c.kind == kind), ZERO)


def _ids(st: ReconState, *kinds: str) -> tuple[str, ...]:
    return tuple(i for c in st.components if c.kind in kinds for i in c.fact_ids)


def _excluded_ids(st: ReconState, *kinds: str, reasons: tuple[str, ...] | None = None) -> tuple[str, ...]:
    return tuple(e.fact_id for e in st.exclusions if e.kind in kinds and (reasons is None or e.reason in reasons))


def _base_currency(claims: list[ReconClaim]) -> str:
    for c in claims:
        if c.claim_type == ClaimType.NET_WORTH.value:
            return c.currency
    return claims[0].currency if claims else "INR"


def _calculations(st: ReconState, claims: list[ReconClaim], now: datetime) -> dict[str, CalculationResult]:
    fmt = lambda x: format_inr(x, st.currency)  # noqa: E731
    st.bank_total, st.investment_total = _sum(st, BANK), _sum(st, INVESTMENT)
    st.liability_total = _sum(st, LIABILITY_KIND)
    gross = st.bank_total + st.investment_total
    net = gross - st.liability_total
    calcs: dict[str, CalculationResult] = {}

    def add(name, formula, result, inputs=(), excluded=(), notes=(), unit="currency"):
        calcs[name] = CalculationResult(name, formula, result, st.currency, tuple(inputs), tuple(excluded), now, tuple(notes), unit)

    add("gross_assets", f"bank deposits + investments = {fmt(st.bank_total)} + {fmt(st.investment_total)} = {fmt(gross)}",
        gross, _ids(st, BANK, INVESTMENT), _excluded_ids(st, BANK, INVESTMENT),
        ["Declared assets without supporting evidence (for example property) are not included."])
    add("liabilities", f"sum of evidenced outstanding liabilities = {fmt(st.liability_total)}",
        st.liability_total, _ids(st, LIABILITY_KIND), _excluded_ids(st, LIABILITY_KIND))
    add("net_worth", f"gross assets - liabilities = {fmt(gross)} - {fmt(st.liability_total)} = {fmt(net)}",
        net, _ids(st, BANK, INVESTMENT, LIABILITY_KIND), _excluded_ids(st, BANK, INVESTMENT, LIABILITY_KIND))

    declared_nw = sum((c.amount for c in claims if c.claim_type == ClaimType.NET_WORTH.value and c.amount is not None), ZERO)
    if any(c.claim_type == ClaimType.NET_WORTH.value for c in claims):
        add("net_worth_difference",
            f"declared net worth - evidence-backed net worth = {fmt(declared_nw)} - {fmt(net)} = {fmt(declared_nw - net)}",
            declared_nw - net, _ids(st, BANK, INVESTMENT, LIABILITY_KIND), _excluded_ids(st, BANK, INVESTMENT, LIABILITY_KIND))

    resolved = [e for e in st.exclusions if e.reason == "DUPLICATE_RESOLVED" and e.kind == INVESTMENT]
    unresolved = [e for e in st.exclusions if e.reason == "DUPLICATE_UNRESOLVED" and e.kind == INVESTMENT]
    removed = sum((e.amount for e in resolved), ZERO)
    add("duplicate_asset_adjustment",
        f"sum of duplicate holding values counted once = {fmt(removed)}", removed, (), [e.fact_id for e in resolved],
        [f"{len(unresolved)} possible duplicate holding(s) are excluded from verified totals until an analyst decides."]
        if unresolved else [])

    stale_assets = sum((a for k, a in st.stale_entity_values if k in (BANK, INVESTMENT)), ZERO)
    stale_liabs = sum((a for k, a in st.stale_entity_values if k == LIABILITY_KIND), ZERO)
    add("stale_evidence_net_worth_impact",
        f"stale assets excluded - stale liabilities excluded = {fmt(stale_assets)} - {fmt(stale_liabs)} = {fmt(stale_assets - stale_liabs)}",
        stale_assets - stale_liabs, (), _excluded_ids(st, BANK, INVESTMENT, LIABILITY_KIND, INCOME, reasons=("STALE",)))

    for check in st.sale_checks:
        key = f"sale_proceeds_difference:{check.reference or check.event_id}"
        calcs[key] = replace(check.calculation, name=key)

    intended = sum((c.amount for c in claims if c.claim_type == ClaimType.SOURCE_OF_FUNDS.value and c.amount is not None), ZERO)
    if intended > 0:
        src = (st.observed_sale_proceeds * 100 / intended).quantize(CENT)
        liq = (st.bank_total * 100 / intended).quantize(CENT)
        add("source_of_funds_coverage",
            f"observed sale proceeds / intended investment = {fmt(st.observed_sale_proceeds)} / {fmt(intended)} = {src}%",
            src, _ids(st, PROCEEDS), (), unit="percent")
        add("liquid_funds_coverage",
            f"verified bank balance / intended investment = {fmt(st.bank_total)} / {fmt(intended)} = {liq}%",
            liq, _ids(st, BANK), (), unit="percent")
    return calcs


# --- claims -------------------------------------------------------------------------------------
def _sale_based(st: ReconState, claim: ReconClaim) -> bool:
    return bool(st.sale_checks) and bool(SALE_WORDS.search(claim.description))


def _status(claim_type: str, declared: Decimal | None, backed: Decimal, tol: Decimal, doc_support: bool, all_stale: bool) -> str:
    if claim_type == ClaimType.LIABILITY.value:
        if declared is None:
            return VERIFIED if backed > 0 else UNVERIFIED
        if abs(backed - declared) <= tol:
            return VERIFIED
        if backed > declared:
            return CONTRADICTED  # evidence shows a larger liability than declared
        return PARTIAL if backed > 0 else (STALE if all_stale else UNVERIFIED)
    if declared is None:
        return VERIFIED if backed > 0 else (PARTIAL if doc_support else (STALE if all_stale else UNVERIFIED))
    if backed >= declared - tol:
        return VERIFIED
    if backed > 0 or doc_support:
        return PARTIAL
    return STALE if all_stale else UNVERIFIED


def _reconcile_claims(st: ReconState, claims: list[ReconClaim], income: Decimal, calcs: dict[str, CalculationResult]) -> list[ClaimResult]:
    fmt = lambda x: format_inr(x, st.currency)  # noqa: E731
    net = calcs["net_worth"].result
    stale_kinds = {k for _, k, _, _ in st.stale_facts}
    results: list[ClaimResult] = []

    groups: dict[str, list[ReconClaim]] = {}
    for c in claims:
        groups.setdefault(c.claim_type, []).append(c)

    for claim_type, group in groups.items():
        doc_support = False
        all_stale = False
        if claim_type == ClaimType.BANK_BALANCE.value:
            backed, ids, kinds, rule = st.bank_total, _ids(st, BANK), (BANK,), "BANK_CLOSING_BALANCE_TOTAL"
            all_stale = BANK in stale_kinds and backed == 0
        elif claim_type == ClaimType.INVESTMENTS.value:
            backed, ids, kinds, rule = st.investment_total, _ids(st, INVESTMENT), (INVESTMENT,), "DEDUPLICATED_HOLDINGS_TOTAL"
            all_stale = INVESTMENT in stale_kinds and backed == 0
        elif claim_type == ClaimType.LIABILITY.value:
            backed, ids, kinds, rule = st.liability_total, _ids(st, LIABILITY_KIND), (LIABILITY_KIND,), "OUTSTANDING_PRINCIPAL_TOTAL"
            all_stale = LIABILITY_KIND in stale_kinds and backed == 0
        elif claim_type == ClaimType.ANNUAL_INCOME.value:
            backed, ids, kinds, rule = income, _ids(st, INCOME), (INCOME,), "TAX_TOTAL_INCOME"
            all_stale = INCOME in stale_kinds and backed == 0
        elif claim_type == ClaimType.NET_WORTH.value:
            backed, ids, kinds, rule = net, _ids(st, BANK, INVESTMENT, LIABILITY_KIND), (BANK, INVESTMENT, LIABILITY_KIND), "EVIDENCE_BACKED_NET_WORTH"
        elif claim_type in (ClaimType.SOURCE_OF_WEALTH.value, ClaimType.SOURCE_OF_FUNDS.value):
            sale = any(_sale_based(st, c) for c in group)
            if sale:
                backed, ids, kinds, rule = st.observed_sale_proceeds, _ids(st, PROCEEDS), (PROCEEDS,), "OBSERVED_SALE_PROCEEDS"
                doc_support = True
            elif claim_type == ClaimType.SOURCE_OF_FUNDS.value:
                backed, ids, kinds, rule = st.bank_total, _ids(st, BANK), (BANK,), "VERIFIED_BANK_BALANCE"
            else:
                backed, ids, kinds, rule = ZERO, (), (), "NO_EVIDENCE_RULE"
        else:  # property, business and other assets have no evidence type yet
            backed, ids, kinds, rule = ZERO, (), (), "NO_EVIDENCE_TYPE"

        remaining = max(backed, ZERO)
        ordered = sorted(group, key=lambda c: (c.amount is None, c.amount or ZERO))
        for idx, claim in enumerate(ordered):
            if claim.amount is None:
                alloc = remaining
            else:
                alloc = min(remaining, claim.amount)
            remaining -= alloc
            is_last = idx == len(ordered) - 1
            claim_backed = alloc + (remaining if is_last else ZERO)
            if claim_type == ClaimType.NET_WORTH.value:
                claim_backed = backed
            status = _status(claim_type, claim.amount, claim_backed, st.policy.tolerance, doc_support and claim_backed == 0, all_stale)
            declared = claim.amount
            supported = max(min(claim_backed, declared), ZERO) if declared is not None else max(claim_backed, ZERO)
            diff = (declared - claim_backed) if declared is not None else None
            cites = sorted({_cite(st.facts[i]) for i in ids if i in st.facts})[:4]
            if status == UNVERIFIED:
                explanation = "No evidence supports this claim."
            elif status == STALE:
                explanation = "Evidence exists but is older than the staleness policy allows, so it is not counted."
            else:
                explanation = f"Declared {fmt(declared) if declared is not None else 'n/a'}; evidence-backed {fmt(claim_backed)}"
                explanation += f" ({'; '.join(cites)})." if cites else "."
                if diff is not None and diff > st.policy.tolerance:
                    explanation += f" {fmt(diff)} is not evidenced."
                elif diff is not None and diff < -st.policy.tolerance:
                    explanation += f" Evidence exceeds the declared amount by {fmt(-diff)}."
            results.append(
                ClaimResult(
                    claim.id, claim_type, claim.description, claim.materiality, claim.currency, declared,
                    claim_backed, supported, diff, status, rule, explanation, list(ids), list(_excluded_ids(st, *kinds)),
                )
            )
    by_id = {c.id: i for i, c in enumerate(claims)}
    return sorted(results, key=lambda r: by_id[r.claim_id])


def _coverage(st: ReconState, results: list[ClaimResult], now: datetime) -> CalculationResult | None:
    types = set(st.policy.coverage_claim_types)
    rows = [
        r for r in results
        if r.claim_type in types and r.materiality == "MATERIAL" and r.declared_amount is not None and r.currency == st.currency
    ]
    denominator = sum((r.declared_amount for r in rows), ZERO)
    if denominator <= 0:
        return None
    numerator = sum((r.supported_amount for r in rows), ZERO)
    pct = (numerator * 100 / denominator).quantize(CENT)
    fmt = lambda x: format_inr(x, st.currency)  # noqa: E731
    return CalculationResult(
        "evidence_coverage",
        f"sum(supported) / sum(declared) over {len(rows)} material claim(s) = {fmt(numerator)} / {fmt(denominator)} = {pct}%",
        pct, st.currency, tuple(i for r in rows for i in r.input_fact_ids), (), now,
        ("Net worth and intended source of funds are excluded: net worth is derived, the intended amount is not a holding.",), "percent",
    )


def reconcile(
    *,
    case_id: str,
    customer_id: str,
    claims: list[ReconClaim],
    facts: list[FactView],
    resolution: Resolution,
    policy: ReconciliationPolicy | None = None,
    as_of: date | None = None,
    now: datetime | None = None,
) -> ReconciliationResult:
    policy = policy or ReconciliationPolicy()
    as_of = as_of or date.today()
    now = now or datetime.now(timezone.utc)
    st = ReconState(case_id, customer_id, _base_currency(claims), as_of, policy, {f.id: f for f in facts}, resolution)
    st.pending_person_matches = [m for m in resolution.matches if m.kind == "person" and m.status == PENDING]

    _collect_bank(st)
    _collect_investments(st)
    _collect_liabilities(st)
    income = _collect_income(st)
    _collect_sales(st)
    _collect_unlinked(st)
    calcs = _calculations(st, claims, now)
    st.claims = _reconcile_claims(st, claims, income, calcs)
    coverage = _coverage(st, st.claims, now)
    if coverage:
        calcs["evidence_coverage"] = coverage

    conflicts = detect_conflicts(st)
    requirements = build_requirements(st, conflicts)
    statuses: dict[str, int] = {}
    for r in st.claims:
        statuses[r.status] = statuses.get(r.status, 0) + 1
    severities: dict[str, int] = {}
    for c in conflicts:
        severities[c.severity] = severities.get(c.severity, 0) + 1
    summary = {
        "gross_assets": str(calcs["gross_assets"].result),
        "liabilities": str(calcs["liabilities"].result),
        "net_worth": str(calcs["net_worth"].result),
        "declared_net_worth": str(sum((c.amount for c in claims if c.claim_type == ClaimType.NET_WORTH.value and c.amount is not None), ZERO)),
        "net_worth_difference": str(calcs["net_worth_difference"].result) if "net_worth_difference" in calcs else None,
        "evidence_coverage_pct": str(coverage.result) if coverage else None,
        "claim_statuses": statuses,
        "conflicts_by_severity": severities,
    }
    return ReconciliationResult(
        case_id, as_of, st.currency, now, calcs, st.components, st.exclusions, st.claims,
        st.sale_checks, conflicts, requirements, coverage.result if coverage else None, summary,
    )
