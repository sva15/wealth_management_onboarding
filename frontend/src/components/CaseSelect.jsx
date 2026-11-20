import React, { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { listCases } from "../api/client.js";

// Picks the active case; the choice lives in the URL (?case=ID) so pages are linkable.
export default function CaseSelect() {
  const [params, setParams] = useSearchParams();
  const [cases, setCases] = useState([]);
  const caseId = params.get("case") || "";

  useEffect(() => {
    listCases({ limit: 100 }).then((p) => setCases(p.items)).catch(() => {});
  }, []);

  return (
    <label className="inline">
      Case{" "}
      <select value={caseId} onChange={(e) => setParams(e.target.value ? { case: e.target.value } : {})}>
        <option value="">Select a case…</option>
        {cases.map((c) => (
          <option key={c.id} value={c.id}>{c.customer_name} ({c.status})</option>
        ))}
      </select>
    </label>
  );
}

export function useCaseId() {
  const [params] = useSearchParams();
  return params.get("case") || "";
}
