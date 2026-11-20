import React, { useCallback, useEffect, useState } from "react";
import CaseSelect, { useCaseId } from "../components/CaseSelect.jsx";
import {
  errorMessage, getReconciliation, getSaleProceeds, linkEvidence, listEvidence, runReconciliation,
} from "../api/client.js";
import { formatInr } from "../format.js";

const SEVERITY_ORDER = ["HIGH", "MEDIUM", "LOW", "INFORMATIONAL"];
const STATUS_TEXT = {
  RECONCILED: "Reconciled",
  UNEXPLAINED_DIFFERENCE: "Unexplained difference",
  EXCESS_RECEIVED: "More received than agreed",
  NO_PROCEEDS_OBSERVED: "No proceeds observed",
};

function Badge({ value }) {
  return <span className={`badge badge-${value}`}>{value.replaceAll("_", " ")}</span>;
}

function SourceRow({ label, fact }) {
  return (
    <tr>
      <td>{label}</td>
      <td>{formatInr(fact.amount)}</td>
      <td>{fact.document_filename}</td>
      <td>{fact.page_number}</td>
      <td className="muted quote">“{fact.source_text}”</td>
    </tr>
  );
}

export default function ReconciliationWorkbench() {
  const caseId = useCaseId();
  const [recon, setRecon] = useState(null);
  const [evidence, setEvidence] = useState([]);
  const [proceeds, setProceeds] = useState([]);
  const [message, setMessage] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!caseId) return;
    try {
      const [r, e, p] = await Promise.all([getReconciliation(caseId), listEvidence(caseId), getSaleProceeds(caseId)]);
      setRecon(r); setEvidence(e); setProceeds(p);
    } catch (err) {
      setMessage(errorMessage(err));
    }
  }, [caseId]);

  useEffect(() => { load(); }, [load]);

  async function run() {
    setBusy(true);
    try {
      await linkEvidence(caseId);
      await runReconciliation(caseId);
      setMessage(null);
      await load();
    } catch (err) {
      setMessage(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const conflictsByClaim = (claimId) => (recon ? recon.conflicts.filter((c) => c.details.claim_ids?.includes(claimId) && c.status === "OPEN") : []);
  const requirementFor = (conflict) => recon.requirements.find((q) => q.conflict_id === conflict.id && q.status === "OPEN");
  const openConflicts = recon ? recon.conflicts.filter((c) => c.status === "OPEN") : [];

  return (
    <section>
      <h2>Reconciliation Workbench</h2>
      <CaseSelect />
      {caseId && <> <button disabled={busy} onClick={run}>{busy ? "Working…" : "Link evidence & reconcile"}</button></>}
      {message && <p className="error">{message}</p>}
      {caseId && !recon && !message && <p className="muted">No reconciliation yet. Extract documents, then run it.</p>}

      {recon && <p className="muted">Calculated {new Date(recon.calculated_at).toLocaleString()} as of {recon.as_of}. Amounts are deterministic (Decimal) and every figure lists its source facts.</p>}

      {proceeds.map((p) => (
        <div className="card" key={p.event_id}>
          <h3>Sale consideration vs observed proceeds {p.reference ? `(${p.reference})` : ""}</h3>
          <div className="stats">
            <div className="stat"><div className="stat-value">{formatInr(p.consideration.amount)}</div><div className="stat-label">Agreed consideration</div></div>
            <div className="stat"><div className="stat-value">{formatInr(p.observed_credits.reduce((s, c) => s + Number(c.amount), 0))}</div><div className="stat-label">Observed bank credits</div></div>
            <div className={`stat ${p.status === "RECONCILED" ? "" : "stat-alert"}`}><div className="stat-value">{formatInr(p.difference)}</div><div className="stat-label">{STATUS_TEXT[p.status] || p.status}</div></div>
          </div>
          <p className="muted">{p.formula}</p>
          <table>
            <thead><tr><th /><th>Amount</th><th>Document</th><th>Page</th><th>Source text</th></tr></thead>
            <tbody>
              <SourceRow label="Agreement" fact={p.consideration} />
              {p.observed_credits.map((c) => <SourceRow key={c.fact_id} label="Bank credit" fact={c} />)}
            </tbody>
          </table>
        </div>
      ))}

      {recon && (
        <>
          <h3>Material claims</h3>
          <table>
            <thead><tr><th>Claim</th><th>Declared</th><th>Evidence-backed</th><th>Difference</th><th>Status</th><th>Severity</th><th>Required action</th></tr></thead>
            <tbody>
              {recon.claims.map((c) => {
                const conflicts = conflictsByClaim(c.claim_id);
                const top = SEVERITY_ORDER.find((s) => conflicts.some((x) => x.severity === s));
                const sources = evidence.filter((e) => e.claim_id === c.claim_id);
                return (
                  <tr key={c.claim_id}>
                    <td>{c.claim_type}<div className="muted">{c.description}</div><div className="muted">{c.materiality}</div></td>
                    <td>{formatInr(c.declared_amount)}</td>
                    <td>{formatInr(c.evidence_backed_amount)}</td>
                    <td className={c.difference && Number(c.difference) > 0 ? "warn" : ""}>{c.difference === null ? "—" : formatInr(c.difference)}</td>
                    <td><Badge value={c.status} /><div className="muted">{c.explanation}</div></td>
                    <td>{top ? <Badge value={top} /> : "—"}</td>
                    <td>
                      {conflicts.map((x) => {
                        const q = requirementFor(x);
                        return q ? <div key={x.id} className="evidence-row">{q.request_text}</div> : null;
                      })}
                      {sources.slice(0, 3).map((s) => (
                        <div key={s.id} className="muted evidence-row">{s.document_filename}, p.{s.page_number} · {s.relation}</div>
                      ))}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          <h3>Open conflicts ({openConflicts.length})</h3>
          {openConflicts.length === 0 ? <p className="muted">None.</p> : (
            <ul className="plain">
              {openConflicts.map((c) => (
                <li key={c.id}><Badge value={c.severity} /> {c.description}</li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
