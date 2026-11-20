import React, { useCallback, useEffect, useState } from "react";
import CaseSelect, { useCaseId } from "../components/CaseSelect.jsx";
import { errorMessage, getReconciliation, listConflicts } from "../api/client.js";

export default function ConflictReview() {
  const caseId = useCaseId();
  const [conflicts, setConflicts] = useState([]);
  const [requirements, setRequirements] = useState([]);
  const [message, setMessage] = useState(null);

  const load = useCallback(async () => {
    if (!caseId) return;
    try {
      const [c, r] = await Promise.all([listConflicts(caseId), getReconciliation(caseId)]);
      setConflicts(c);
      setRequirements(r ? r.requirements : []);
    } catch (err) {
      setMessage(errorMessage(err));
    }
  }, [caseId]);

  useEffect(() => { load(); }, [load]);

  return (
    <section>
      <h2>Conflict Review</h2>
      <CaseSelect />
      {message && <p className="error">{message}</p>}
      {caseId && conflicts.length === 0 && <p className="muted">No conflicts. Run the reconciliation first.</p>}
      {conflicts.map((c) => {
        const req = requirements.find((q) => q.conflict_id === c.id);
        return (
          <div className="card" key={c.id}>
            <p>
              <span className={`badge badge-${c.severity}`}>{c.severity}</span>{" "}
              <strong>{c.rule_id.replaceAll("_", " ")}</strong> · {c.status}
            </p>
            <p>{c.description}</p>
            <p className="muted">Deterministic rule: {c.rule_id}. Involves {c.details.claim_ids?.length || 0} claim(s) and {c.details.fact_ids?.length || 0} fact(s).</p>
            {req && (
              <div>
                <p><strong>Next best evidence ({req.audience.toLowerCase()}-facing, {req.priority}):</strong> {req.request_text}</p>
                <p className="muted">Why: {req.details?.why_needed} · Existing evidence: {(req.details?.existing_evidence || []).join(", ") || "none"}</p>
              </div>
            )}
          </div>
        );
      })}
      <p className="muted">Analyst decision controls (accept, resolve, request evidence) arrive in the next phase.</p>
    </section>
  );
}
