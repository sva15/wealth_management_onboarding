"""Conflict detection and next-best-evidence requests. Pure rules; severities come from the policy."""
from decimal import Decimal

from app.domain.enums import ClaimType
from app.domain.evidence_linking import SALE_WORDS
from app.domain.money import format_inr
from app.domain.reconciliation.state import ClaimResult, ConflictDraft, ReconState, RequirementDraft

SOW, SOF = ClaimType.SOURCE_OF_WEALTH.value, ClaimType.SOURCE_OF_FUNDS.value
NW, LIAB = ClaimType.NET_WORTH.value, ClaimType.LIABILITY.value

_CLAIM_LABEL = {
    ClaimType.NET_WORTH.value: "net worth",
    ClaimType.ANNUAL_INCOME.value: "annual income",
    SOW: "source of wealth",
    SOF: "source of funds",
    ClaimType.INVESTMENTS.value: "investments",
    ClaimType.BANK_BALANCE.value: "bank deposits",
    ClaimType.PROPERTY_OWNERSHIP.value: "property",
    ClaimType.BUSINESS_OWNERSHIP.value: "business interest",
    ClaimType.OTHER_ASSET.value: "other asset",
    LIAB: "liability",
}
_EVIDENCE_FOR_CLAIM = {
    ClaimType.PROPERTY_OWNERSHIP.value: "the registered title deed or sale deed, and a recent valuation report or property tax receipt",
    ClaimType.BUSINESS_OWNERSHIP.value: "a shareholding certificate or company registry extract and the latest financial statements",
    ClaimType.OTHER_ASSET.value: "documentary proof of ownership and a recent valuation",
    ClaimType.INVESTMENTS.value: "a recent portfolio or demat statement",
    ClaimType.BANK_BALANCE.value: "a recent bank statement",
    LIAB: "the latest loan account statement",
    ClaimType.ANNUAL_INCOME.value: "the latest income tax return summary",
    SOW: "documents showing how the wealth arose",
}
_KIND_DOC = {
    "BANK_BALANCE": "bank statement",
    "INVESTMENT": "portfolio or demat statement",
    "LIABILITY": "loan statement",
    "INCOME": "income tax return summary",
    "SALE_PROCEEDS": "bank statement",
}


def _fmt(st: ReconState, amount: Decimal | None) -> str:
    return format_inr(amount, st.currency) if amount is not None else "n/a"


def _sale_based_sow(st: ReconState, r: ClaimResult) -> bool:
    return r.claim_type == SOW and bool(st.sale_checks) and bool(SALE_WORDS.search(r.description))


# --- conflicts ---------------------------------------------------------------------------------
def detect_conflicts(st: ReconState) -> list[ConflictDraft]:
    pol, tol = st.policy, st.policy.tolerance
    out: list[ConflictDraft] = []

    def add(rule_id: str, subject: str, severity: str, description: str, claim_ids=(), fact_ids=(), **details) -> None:
        out.append(ConflictDraft(f"{rule_id}:{subject}", rule_id, severity, description, list(claim_ids), list(fact_ids), details))

    sale_claim_ids = [r.claim_id for r in st.claims if r.claim_type in (SOW, SOF) and SALE_WORDS.search(r.description)]

    # sale agreement vs bank receipt
    for check in st.sale_checks:
        diff = check.calculation.result
        if check.credits and abs(diff) <= tol:
            continue
        cons = check.consideration
        observed = sum((c.amount for c in check.credits), Decimal("0"))
        ref = f" {check.reference}" if check.reference else ""
        if not check.credits:
            text = f"Sale agreement{ref} states {_fmt(st, cons.amount)} but no bank credit tied to the sale was found."
        elif diff > 0:
            text = (f"Sale agreement{ref} states {_fmt(st, cons.amount)} but bank credits tied to the sale total "
                    f"{_fmt(st, observed)}; {_fmt(st, diff)} is unexplained.")
        else:
            text = (f"Bank credits tied to the sale ({_fmt(st, observed)}) exceed the agreed consideration "
                    f"({_fmt(st, cons.amount)}) by {_fmt(st, -diff)}.")
        add("SALE_VS_BANK_RECEIPT", check.event_id, pol.difference_severity("SALE_VS_BANK_RECEIPT", abs(diff), cons.amount),
            text, sale_claim_ids, [cons.id, *[c.id for c in check.credits]],
            consideration=str(cons.amount), observed=str(observed), difference=str(diff), reference=check.reference)

    # claims
    for r in st.claims:
        if r.declared_amount is None or r.difference is None:
            continue
        declared, backed, diff = r.declared_amount, r.evidence_backed_amount, r.difference
        label = _CLAIM_LABEL.get(r.claim_type, r.claim_type)
        if r.claim_type == LIAB and backed > declared + tol:
            add("LIABILITY_UNDERSTATED", r.claim_id, pol.rule_severity("LIABILITY_UNDERSTATED"),
                f"Evidence shows {_fmt(st, backed)} outstanding but {_fmt(st, declared)} was declared.",
                [r.claim_id], r.input_fact_ids, declared=str(declared), evidence_backed=str(backed))
        elif r.status == "UNVERIFIED" and r.materiality == "MATERIAL" and declared > 0:
            add("MATERIAL_CLAIM_WITHOUT_EVIDENCE", r.claim_id,
                pol.difference_severity("MATERIAL_CLAIM_WITHOUT_EVIDENCE", declared, declared),
                f"The declared {label} of {_fmt(st, declared)} ({r.description}) has no supporting evidence.",
                [r.claim_id], [], declared=str(declared))
        elif r.status in ("PARTIALLY_VERIFIED", "CONTRADICTED") and diff > tol and not _sale_based_sow(st, r):
            add("DECLARED_VS_EVIDENCE_DIFFERENCE", r.claim_id, pol.difference_severity("DECLARED_VS_EVIDENCE_DIFFERENCE", diff, declared),
                f"Declared {label} is {_fmt(st, declared)} but only {_fmt(st, backed)} is evidence-backed; {_fmt(st, diff)} is not evidenced.",
                [r.claim_id], r.input_fact_ids, declared=str(declared), evidence_backed=str(backed), difference=str(diff))
        if diff < -tol and r.claim_type not in (LIAB, SOF):
            add("EVIDENCE_EXCEEDS_DECLARED", r.claim_id, pol.rule_severity("EVIDENCE_EXCEEDS_DECLARED"),
                f"Evidence for {label} ({_fmt(st, backed)}) exceeds the declared {_fmt(st, declared)}.",
                [r.claim_id], r.input_fact_ids, declared=str(declared), evidence_backed=str(backed))
        if r.claim_type == SOF and st.bank_total < declared - tol:
            add("LIQUIDITY_SHORTFALL", r.claim_id, pol.rule_severity("LIQUIDITY_SHORTFALL"),
                f"The verified bank balance ({_fmt(st, st.bank_total)}) is below the intended investment ({_fmt(st, declared)}).",
                [r.claim_id], r.input_fact_ids, bank_total=str(st.bank_total), intended=str(declared))

    # liabilities evidenced but never declared
    if not any(r.claim_type == LIAB for r in st.claims):
        for c in (c for c in st.components if c.kind == "LIABILITY"):
            add("LIABILITY_OMITTED", c.entity_id or c.fact_ids[0], pol.rule_severity("LIABILITY_OMITTED"),
                f"A liability of {_fmt(st, c.amount)} ({c.label}) is evidenced but was not declared.",
                [], c.fact_ids, amount=str(c.amount), label=c.label)

    # duplicates and value conflicts
    for asset, chosen, dups in st.resolved_duplicates:
        add("DUPLICATE_ASSET_RESOLVED", asset.id, pol.rule_severity("DUPLICATE_ASSET_RESOLVED"),
            f"{asset.label} appears in {len(dups) + 1} documents with the same value and date; it is counted once.",
            [], [chosen.id, *[d.id for d in dups]], label=asset.label, amount=str(chosen.amount))
    for asset, facts in st.unresolved_duplicates:
        add("DUPLICATE_ASSET_UNRESOLVED", asset.id, pol.rule_severity("DUPLICATE_ASSET_UNRESOLVED"),
            f"{asset.label} may duplicate another holding (same ISIN, folio missing); it is excluded from verified totals until an analyst decides.",
            [], [f.id for f in facts], label=asset.label)
    for entity, facts in st.different_values:
        values = ", ".join(sorted({_fmt(st, f.amount) for f in facts}))
        add("SAME_ASSET_DIFFERENT_VALUE", entity.id, pol.rule_severity("SAME_ASSET_DIFFERENT_VALUE"),
            f"{entity.label} has different values on the same date ({values}); it is excluded from verified totals.",
            [], [f.id for f in facts], label=entity.label)
    for doc_id, doc_name, total_fact, summed in st.portfolio_mismatches:
        add("PORTFOLIO_TOTAL_MISMATCH", total_fact.id, pol.rule_severity("PORTFOLIO_TOTAL_MISMATCH"),
            f"{doc_name} states a total of {_fmt(st, total_fact.amount)} but its holdings add up to {_fmt(st, summed)}.",
            [], [total_fact.id], document=doc_name, stated=str(total_fact.amount), computed=str(summed))

    # ownership
    for entity, owner_id, facts in st.owner_mismatches:
        owner = st.resolution.entities.get(owner_id)
        add("OWNER_MISMATCH", entity.id, pol.rule_severity("OWNER_MISMATCH"),
            f"{entity.label} is documented under a different owner ({owner.label if owner else 'unknown'}) and is excluded from verified totals.",
            [], [f.id for f in facts], label=entity.label)
    for m in st.pending_person_matches:
        add("OWNER_UNCONFIRMED", m.key, pol.rule_severity("OWNER_UNCONFIRMED"),
            f"'{m.left_label}' and '{m.right_label}' may be the same person; ownership of linked evidence is unconfirmed.",
            [], [], left=m.left_label, right=m.right_label, score=m.score)

    # staleness and currency
    for fact, kind, age, limit in st.stale_facts:
        add("STALE_EVIDENCE", fact.id, pol.rule_severity("STALE_EVIDENCE"),
            f"{_KIND_DOC.get(kind, kind)} evidence ({fact.document_name} p.{fact.page}) is {age} days old; the policy limit is {limit} days.",
            [], [fact.id], kind=kind, age_days=age, limit_days=limit)
    for e in (e for e in st.exclusions if e.reason == "CURRENCY_MISMATCH"):
        add("CURRENCY_MISMATCH", e.fact_id, pol.rule_severity("CURRENCY_MISMATCH"),
            f"A {e.kind} value is in a different currency ({e.detail}) and cannot be combined without an exchange rate.",
            [], [e.fact_id])
    for f in st.unlinked:
        add("UNLINKED_EVIDENCE", f.id, pol.rule_severity("UNLINKED_EVIDENCE"),
            f"{f.fact_type} {_fmt(st, f.amount)} ({f.document_name} p.{f.page}) could not be linked to an account, holding or loan and is not counted.",
            [], [f.id], fact_type=f.fact_type)
    return out


# --- next best evidence ------------------------------------------------------------------------
def build_requirements(st: ReconState, conflicts: list[ConflictDraft]) -> list[RequirementDraft]:
    results = {r.claim_id: r for r in st.claims}
    out: list[RequirementDraft] = []

    def cites(fact_ids) -> list[str]:
        return sorted({f"{st.facts[i].document_name} p.{st.facts[i].page}" for i in fact_ids if i in st.facts})[:5]

    def add(c: ConflictDraft, audience: str, text: str, required: str, why: str) -> None:
        claim_id = c.claim_ids[0] if c.claim_ids else None
        r = results.get(claim_id) if claim_id else None
        claim_text = f"{_CLAIM_LABEL.get(r.claim_type, r.claim_type)}: {r.description} ({_fmt(st, r.declared_amount)})" if r else None
        out.append(
            RequirementDraft(
                f"REQ:{c.key}", c.key, claim_id, audience,
                "LOW" if c.severity == "INFORMATIONAL" else c.severity, text,
                {"unresolved_claim": claim_text, "observed_discrepancy": c.description,
                 "existing_evidence": cites(c.fact_ids), "required_evidence": required, "why_needed": why},
            )
        )

    sale_by_event = {s.event_id: s for s in st.sale_checks}
    for c in conflicts:
        d = c.details
        if c.rule_id == "SALE_VS_BANK_RECEIPT":
            check = sale_by_event.get(c.key.split(":", 1)[1])
            if check is None:
                continue
            cons, ref = _fmt(st, check.consideration.amount), check.reference or "the agreement"
            diff = check.calculation.result
            if not check.credits:
                add(c, "CUSTOMER",
                    f"To verify receipt of the sale proceeds ({cons} under {ref}), provide the statement of the bank account that received the consideration.",
                    "Bank statement showing the credit of the sale consideration", "The sale agreement alone does not show that the money was received.")
            elif diff > 0:
                add(c, "CUSTOMER",
                    f"To reconcile the {_fmt(st, diff)} difference between the sale agreement ({ref}; consideration {cons}, "
                    f"{', '.join(cites([check.consideration.id]))}) and the observed bank credit ({_fmt(st, Decimal(d['observed']))}, "
                    f"{', '.join(cites([x.id for x in check.credits]))}), provide the transaction settlement statement or documentation "
                    "showing taxes, advisory fees or transaction expenses deducted from the sale proceeds.",
                    "Settlement statement or documentation of deductions from the sale proceeds",
                    f"Only {_fmt(st, Decimal(d['observed']))} of the {cons} sale value is evidenced as received.")
            else:
                add(c, "ANALYST",
                    f"Confirm why bank credits ({_fmt(st, Decimal(d['observed']))}) exceed the agreed consideration ({cons}); check for another transaction or a price adjustment.",
                    "Analyst review of the extra credit", "More money was received than the agreement states.")
        elif c.rule_id == "MATERIAL_CLAIM_WITHOUT_EVIDENCE":
            r = results[c.claim_ids[0]]
            label = _CLAIM_LABEL.get(r.claim_type, r.claim_type)
            docs = _EVIDENCE_FOR_CLAIM.get(r.claim_type, "supporting documents")
            add(c, "CUSTOMER",
                f"To verify the declared {label} of {_fmt(st, r.declared_amount)} ({r.description}), provide {docs}. "
                "The document should show ownership by the customer and a value as at a recent date.",
                docs[0].upper() + docs[1:], f"The declared {label} is {_fmt(st, r.declared_amount)} but nothing in the submitted documents supports it.")
        elif c.rule_id == "DECLARED_VS_EVIDENCE_DIFFERENCE":
            r = results[c.claim_ids[0]]
            label = _CLAIM_LABEL.get(r.claim_type, r.claim_type)
            if r.claim_type == NW:
                unverified = [x for x in st.claims if x.status == "UNVERIFIED" and x.claim_type != NW]
                names = ", ".join(sorted({_CLAIM_LABEL.get(x.claim_type, x.claim_type) for x in unverified})) or "each declared asset"
                text = (f"Evidence supports {_fmt(st, r.evidence_backed_amount)} of the declared net worth of {_fmt(st, r.declared_amount)}. "
                        f"To account for the remaining {_fmt(st, r.difference)}, provide documents for the unevidenced items ({names}) or revise the declaration.")
                add(c, "CUSTOMER", text, f"Documents for: {names}", "Declared net worth is not fully supported by evidenced assets and liabilities.")
            else:
                docs = _EVIDENCE_FOR_CLAIM.get(r.claim_type, "supporting documents")
                add(c, "CUSTOMER",
                    f"Provide {docs} covering the remaining {_fmt(st, r.difference)} of the declared {label}, or revise the declaration.",
                    docs[0].upper() + docs[1:], f"Only {_fmt(st, r.evidence_backed_amount)} of {_fmt(st, r.declared_amount)} is evidenced.")
        elif c.rule_id == "LIABILITY_UNDERSTATED":
            add(c, "CUSTOMER",
                f"The evidence shows {_fmt(st, Decimal(d['evidence_backed']))} outstanding but {_fmt(st, Decimal(d['declared']))} was declared. "
                "Please explain the difference or correct the declaration.",
                "Corrected declaration or an explanation with the loan statement", "Liabilities reduce net worth and must not be understated.")
        elif c.rule_id == "LIABILITY_OMITTED":
            add(c, "CUSTOMER",
                f"A liability of {_fmt(st, Decimal(d['amount']))} ({d['label']}) appears in the documents but was not declared. Please confirm and update the declaration.",
                "Updated declaration listing the liability", "An evidenced liability is missing from the declaration.")
        elif c.rule_id == "STALE_EVIDENCE":
            add(c, "CUSTOMER",
                f"Provide an updated {_KIND_DOC.get(d['kind'], 'document')} dated within the last {d['limit_days']} days; the evidence on file "
                f"({', '.join(cites(c.fact_ids))}) is {d['age_days']} days old.",
                f"Updated {_KIND_DOC.get(d['kind'], 'document')}", "Old values cannot be treated as current.")
        elif c.rule_id in ("DUPLICATE_ASSET_UNRESOLVED", "SAME_ASSET_DIFFERENT_VALUE"):
            add(c, "ANALYST",
                f"{c.description} Review the documents ({', '.join(cites(c.fact_ids))}) and confirm whether they describe the same holding and which value is correct.",
                "Analyst decision on the holding", "Unresolved duplicates are excluded from verified totals.")
        elif c.rule_id == "PORTFOLIO_TOTAL_MISMATCH":
            add(c, "ANALYST", f"{c.description} Check the statement for missing or extra holdings.",
                "Analyst review of the statement", "The statement is internally inconsistent.")
        elif c.rule_id == "OWNER_MISMATCH":
            add(c, "ANALYST", f"{c.description} Confirm whether the customer has a documented interest, or exclude the item.",
                "Evidence of the customer's ownership", "Assets owned by someone else cannot count towards the customer's net worth.")
        elif c.rule_id == "OWNER_UNCONFIRMED":
            add(c, "ANALYST", f"Confirm whether '{d['left']}' and '{d['right']}' are the same person on the Evidence Graph page.",
                "Analyst confirmation of the entity match", "Until confirmed, linked evidence may not be attributed to the customer.")
        elif c.rule_id == "CURRENCY_MISMATCH":
            add(c, "ANALYST", f"{c.description} Provide an exchange rate and its date, or exclude the value.",
                "Exchange rate and rate date", "Values in different currencies are never combined implicitly.")
        elif c.rule_id == "UNLINKED_EVIDENCE":
            add(c, "ANALYST", f"{c.description} Confirm which account, holding or loan it belongs to.",
                "Analyst confirmation of the account or holding", "Unlinked values cannot be attributed to the customer.")
        elif c.rule_id == "LIQUIDITY_SHORTFALL":
            add(c, "ANALYST",
                f"Confirm where the intended investment of {_fmt(st, Decimal(d['intended']))} will be funded from: the verified bank balance is {_fmt(st, Decimal(d['bank_total']))}.",
                "Customer explanation of the funding plan", "The source of funds is evidenced, but current liquid funds are lower than the intended amount.")
    return out
