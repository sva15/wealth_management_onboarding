# ADR 003: Deterministic entity resolution, rule-based evidence links, graph as a rebuildable projection

**Status:** Accepted

**Context:** Names, accounts and holdings appear in several documents in different forms. A wrong merge changes financial conclusions, so merges must be explainable and reversible.

**Decision**
- Entity resolution is pure Python over extracted facts. A merge is automatic only on strong evidence: the same PAN, registration id, ISIN with folio, the same account suffix with the same resolved owner, or an exactly equal normalised name. A conflicting PAN always blocks a merge.
- Weaker matches, such as `Aarav Mehta` and `Aarav Kumar Mehta` (0.85) or initials (0.75), become PENDING candidates in `entity_matches`. An analyst confirms or rejects them with a reason, and every decision is audited. A rejection covers the whole pair of clusters. Automatic matches are listed for transparency but cannot be overridden.
- Resolution is recomputed from facts and analyst decisions each time, so it is idempotent and needs no extra state.
- Claim-to-evidence links are rule-based and tagged `RULE`. Declaration-form facts are the customer's own statements and never count as evidence. Totals are compared with the claim (support or contradict), single holdings only partially support an aggregate claim, and ambiguous cases are left for review. Bank credits are tied to a company sale only when the transaction carries the agreement reference. Analyst-created links are never touched by recomputation.
- The graph is a projection of the relational store. Each projection clears the case's nodes and re-merges them, so reprocessing never duplicates anything. Customer names, source quotes and document text are not written to the graph.
- The sale-proceeds check (consideration minus observed credits) is the first deterministic calculation. It reports its formula, input fact ids and excluded duplicate facts, and counts a credit that appears in two statements once.

**Consequences:** Name similarity ignores token order and handles initials, but it is not a general fuzzy matcher. Model-assisted candidate generation and match explanations can plug in later without changing the thresholds or the decision flow.
