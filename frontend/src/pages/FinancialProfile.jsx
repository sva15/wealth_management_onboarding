import React, { useCallback, useEffect, useState } from "react";
import CaseSelect, { useCaseId } from "../components/CaseSelect.jsx";
import { errorMessage, getReconciliation, linkEvidence, runReconciliation } from "../api/client.js";
import { formatInr } from "../format.js";

function Stat({ label, value, alert }) {
  return (
    <div className={`stat ${alert ? "stat-alert" : ""}`}>
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

export default function FinancialProfile() {
  const caseId = useCaseId();
  const [recon, setRecon] = useState(null);
  const [message, setMessage] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!caseId) return;
    try {
      setRecon(await getReconciliation(caseId));
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

  const s = recon?.summary;
  const calc = (name) => recon?.calculations.find((c) => c.name === name);
  const sow = recon?.claims.find((c) => c.claim_type === "SOURCE_OF_WEALTH");

  return (
    <section>
      <h2>Customer Financial Profile</h2>
      <CaseSelect />
      {caseId && <> <button disabled={busy} onClick={run}>{busy ? "Working…" : "Link evidence & reconcile"}</button></>}
      {message && <p className="error">{message}</p>}
      {caseId && !recon && !message && <p className="muted">No reconciliation yet.</p>}

      {recon && (
        <>
          <p className="muted">As of {recon.as_of}, calculated {new Date(recon.calculated_at).toLocaleString()}. Net worth is a calculated result, not a stored attribute.</p>
          <div className="stats">
            <Stat label="Declared net worth" value={formatInr(s.declared_net_worth)} />
            <Stat label="Evidence-backed gross assets" value={formatInr(s.gross_assets)} />
            <Stat label="Evidence-backed liabilities" value={formatInr(s.liabilities)} />
            <Stat label="Evidence-backed net worth" value={formatInr(s.net_worth)} />
          </div>
          <div className="stats">
            <Stat label="Supported amount" value={formatInr(s.net_worth)} />
            <Stat label="Unsupported amount" value={formatInr(s.net_worth_difference)} alert={Number(s.net_worth_difference) > 0} />
            <Stat label="Evidence coverage" value={s.evidence_coverage_pct ? `${s.evidence_coverage_pct}%` : "—"} />
            {sow && <Stat label={`Main wealth source: ${sow.description}`} value={`${sow.status.replaceAll("_", " ")}`} />}
          </div>

          <h3>What is counted</h3>
          <table>
            <thead><tr><th>Kind</th><th>Item</th><th>Amount</th><th>Value date</th><th>Age</th></tr></thead>
            <tbody>
              {recon.components.filter((c) => c.kind !== "SALE_PROCEEDS" && c.kind !== "INCOME").map((c, i) => (
                <tr key={i}>
                  <td>{c.kind.replaceAll("_", " ")}</td><td>{c.label}</td><td>{formatInr(c.amount)}</td>
                  <td>{c.value_date || "undated"}</td><td>{c.age_days === null ? "—" : `${c.age_days} days`}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <h3>What is not counted</h3>
          {recon.exclusions.filter((e) => e.reason !== "OLDER_VALUE").length === 0 ? <p className="muted">Nothing excluded.</p> : (
            <table>
              <thead><tr><th>Reason</th><th>Kind</th><th>Amount</th><th>Detail</th></tr></thead>
              <tbody>
                {recon.exclusions.filter((e) => e.reason !== "OLDER_VALUE").map((e, i) => (
                  <tr key={i}><td>{e.reason.replaceAll("_", " ")}</td><td>{e.kind}</td><td>{formatInr(e.amount)}</td><td className="muted">{e.detail}</td></tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="muted">Declared assets with no evidence (for example property) are not counted until a supporting document is provided.</p>

          <h3>Calculations</h3>
          <table>
            <thead><tr><th>Name</th><th>Result</th><th>Formula</th><th>Inputs</th></tr></thead>
            <tbody>
              {recon.calculations.map((c) => (
                <tr key={c.name}>
                  <td>{c.name.replaceAll("_", " ")}</td>
                  <td>{c.unit === "percent" ? `${c.result}%` : formatInr(c.result)}</td>
                  <td className="muted">{c.formula}</td>
                  <td className="muted">{c.input_fact_ids.length} fact(s), {c.excluded_fact_ids.length} excluded</td>
                </tr>
              ))}
            </tbody>
          </table>
          {calc("source_of_funds_coverage") && (
            <p className="muted">
              Intended investment: sale proceeds cover {calc("source_of_funds_coverage").result}% of it, but the verified bank balance covers {calc("liquid_funds_coverage").result}%.
            </p>
          )}
        </>
      )}
    </section>
  );
}
