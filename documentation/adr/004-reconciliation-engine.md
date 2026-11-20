# ADR 004: Deterministic reconciliation engine, configurable policy, human-owned decisions

**Status:** Accepted

**Context:** Monetary conclusions must be reproducible, explainable and safe from model error. A stale balance, a duplicated holding or a foreign-currency amount must never quietly change a total.

**Decision**
- The engine is pure Python on `Decimal`, over extracted facts reached through resolved entities. No model touches a number.
- Every calculation records its formula, input fact ids, excluded fact ids, currency, unit and timestamp.
- **Evidence-backed assets** are bank closing balances (latest per account) plus de-duplicated holdings. **Liabilities** are the latest outstanding principal per loan. **Net worth** is assets minus liabilities. A declared item with no evidence, such as property, contributes nothing.
- **Exclusions are explicit** and reported with a reason: stale, resolved duplicate (same value and date, counted once), unresolved duplicate (a possible duplicate awaiting an analyst, or the same item with different values on the same date), older value, owner is not the customer, foreign currency, or not linked to any entity. Amounts in different currencies are never combined.
- **Claim status** uses the allowed verification statuses: VERIFIED, PARTIALLY_VERIFIED, CONTRADICTED, UNVERIFIED or STALE. Evidence above the declared amount does not contradict an asset claim. A liability above the declared amount does. The engine only overwrites engine-owned statuses and never an analyst's decision.
- **Staleness and severity are policy**, not code: per fact type age limits, difference thresholds (percentage and absolute), per-rule severity overrides and the claim types counted in coverage. The policy is a JSON file validated at startup. A pinned evaluation date can be set for demos. The default is 365 days for balances, holdings and loans and 730 days for tax data. A production policy would be stricter, see `documentation/reconciliation-policy.example.json`.
- **Conflicts and next-best-evidence requests** are produced by rules with deterministic, specific templates that name the claim, the discrepancy, the existing evidence, the required evidence and why it is needed. They are keyed, so re-running is idempotent: unchanged results create no new run, vanished conflicts close automatically, and analyst-resolved ones stay resolved.
- The engine moves a case only between queue states (awaiting customer evidence, requires review, ready for analyst decision). It never approves or rejects a customer.

**Consequences:** The sale-proceeds shortfall is reported once, on the sale rule, not again on the claim. Evidence coverage is defined over material amount-bearing claims and its formula is shown. A model may later polish the wording of requests, but never the figures.
