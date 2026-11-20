import React, { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getCase, getClaims, listFacts } from "../api/client.js";
import { formatDateTime, formatInr } from "../format.js";

function factValue(f) {
  if (f.amount !== null && f.amount !== undefined) return formatInr(f.amount);
  const n = f.normalized_value || {};
  return n.value ?? n.percent ?? f.original_value;
}

export default function CaseDetail() {
  const { caseId } = useParams();
  const [kase, setCase] = useState(null);
  const [claims, setClaims] = useState([]);
  const [facts, setFacts] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.all([getCase(caseId), getClaims(caseId), listFacts(caseId)])
      .then(([c, cl, fp]) => {
        setCase(c);
        setClaims(cl);
        setFacts(fp.items);
      })
      .catch(() => setError("Could not load case"));
  }, [caseId]);

  if (error) return <p className="error">{error}</p>;
  if (!kase) return <p>Loading…</p>;

  return (
    <section>
      <p><Link to="/">← Dashboard</Link></p>
      <h2>{kase.customer_name}</h2>
      <p>
        Status: <strong>{kase.status}</strong> · Last updated {formatDateTime(kase.updated_at)}
      </p>
      <h3>Declared claims</h3>
      <table>
        <thead>
          <tr><th>Type</th><th>Description</th><th>Declared</th><th>Materiality</th><th>Status</th></tr>
        </thead>
        <tbody>
          {claims.map((c) => (
            <tr key={c.id}>
              <td>{c.claim_type}</td>
              <td>{c.description}</td>
              <td>{formatInr(c.declared_amount)}</td>
              <td>{c.materiality}</td>
              <td>{c.verification_status}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h3>Extracted facts</h3>
      {facts.length === 0 ? (
        <p className="muted">No facts yet. Upload documents and run extraction.</p>
      ) : (
        <table>
          <thead>
            <tr><th>Document</th><th>Page</th><th>Fact</th><th>Value</th><th>Date</th><th>Confidence</th><th>Status</th><th>Source text</th></tr>
          </thead>
          <tbody>
            {facts.map((f) => (
              <tr key={f.id} title={`${f.extraction_method} · ${f.model_id} · ${f.prompt_version}`}>
                <td>{f.document_filename}</td>
                <td>{f.page_number}</td>
                <td>{f.fact_type}</td>
                <td>{factValue(f)}</td>
                <td>{f.effective_date || "—"}</td>
                <td className={f.confidence < 0.7 ? "warn" : ""}>{f.confidence}</td>
                <td>{f.verification_status}</td>
                <td className="muted quote">“{f.source_text}”</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="muted">
        <Link to={`/documents?case=${caseId}`}>Upload, classify and extract documents</Link> ·{" "}
        <Link to={`/reconciliation?case=${caseId}`}>Reconciliation workbench</Link> ·{" "}
        <Link to={`/graph?case=${caseId}`}>Evidence graph</Link>
      </p>
    </section>
  );
}
