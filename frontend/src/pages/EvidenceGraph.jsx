import React, { useCallback, useEffect, useRef, useState } from "react";
import cytoscape from "cytoscape";
import CaseSelect, { useCaseId } from "../components/CaseSelect.jsx";
import { decideMatch, errorMessage, getGraph, linkEvidence, listEvidence, listMatches } from "../api/client.js";
import { formatInr } from "../format.js";

const COLORS = {
  Customer: "#2563eb", Person: "#60a5fa", Claim: "#7c3aed", Document: "#64748b", ExtractedFact: "#94a3b8",
  Evidence: "#0d9488", Account: "#16a34a", Asset: "#65a30d", Liability: "#dc2626", Transaction: "#d97706",
  Organization: "#0891b2", FinancialEvent: "#c026d3",
};
const EDGE_COLORS = { SUPPORTED_BY: "#16a34a", CONTRADICTED_BY: "#dc2626", REVIEW_PENDING: "#d97706" };

function nodeLabel(n) {
  const p = n.properties;
  if (n.label === "Claim") return p.claim_type;
  if (n.label === "ExtractedFact") return `${p.fact_type}${p.amount ? ` ${formatInr(p.amount)}` : ""}`;
  if (n.label === "Evidence") return p.relation;
  if (n.label === "Customer") return "Customer";
  return p.name || n.label;
}

export default function EvidenceGraph() {
  const caseId = useCaseId();
  const container = useRef(null);
  const cy = useRef(null);
  const [graph, setGraph] = useState(null);
  const [evidence, setEvidence] = useState([]);
  const [matches, setMatches] = useState([]);
  const [hidden, setHidden] = useState(new Set());
  const [claimId, setClaimId] = useState("");
  const [selected, setSelected] = useState(null);
  const [reason, setReason] = useState("");
  const [message, setMessage] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!caseId) return;
    try {
      const [g, e, m] = await Promise.all([getGraph(caseId), listEvidence(caseId), listMatches(caseId)]);
      setGraph(g); setEvidence(e); setMatches(m);
    } catch (err) {
      setMessage(errorMessage(err));
    }
  }, [caseId]);

  useEffect(() => { load(); }, [load]);

  async function run() {
    setBusy(true);
    try {
      const s = await linkEvidence(caseId);
      setMessage(`Linked: ${s.evidence_created} new, ${s.evidence_updated} updated, ${s.evidence_removed} removed; ${s.matches_pending} match(es) awaiting review.`);
      await load();
    } catch (err) {
      setMessage(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function decide(id, decision) {
    if (reason.trim().length < 3) return setMessage("Enter a reason (at least 3 characters) for the decision.");
    try {
      await decideMatch(id, decision, reason.trim());
      setReason("");
      await load();
    } catch (err) {
      setMessage(errorMessage(err));
    }
  }

  const labels = graph ? [...new Set(graph.nodes.map((n) => n.label))].sort() : [];

  useEffect(() => {
    if (!graph || !container.current) return undefined;
    const visible = new Set(graph.nodes.filter((n) => !hidden.has(n.label)).map((n) => n.id));
    const elements = [
      ...graph.nodes.filter((n) => visible.has(n.id)).map((n) => ({
        data: { id: n.id, label: nodeLabel(n), type: n.label, color: COLORS[n.label] || "#475569" },
      })),
      ...graph.edges.filter((e) => visible.has(e.source) && visible.has(e.target)).map((e, i) => ({
        data: { id: `e${i}`, source: e.source, target: e.target, label: e.type, color: EDGE_COLORS[e.type] || "#94a3b8" },
      })),
    ];
    cy.current = cytoscape({
      container: container.current,
      elements,
      layout: { name: "cose", animate: false, nodeRepulsion: 9000 },
      style: [
        { selector: "node", style: { "background-color": "data(color)", label: "data(label)", "font-size": 9, "text-wrap": "ellipsis", "text-max-width": 90, color: "#111827" } },
        { selector: "edge", style: { width: 1.5, "line-color": "data(color)", "target-arrow-color": "data(color)", "target-arrow-shape": "triangle", "curve-style": "bezier", label: "data(label)", "font-size": 7 } },
        { selector: ".dim", style: { opacity: 0.12 } },
        { selector: "node:selected", style: { "border-width": 3, "border-color": "#111827" } },
      ],
    });
    cy.current.on("tap", "node", (evt) => setSelected(graph.nodes.find((n) => n.id === evt.target.id())));
    return () => cy.current && cy.current.destroy();
  }, [graph, hidden]);

  // Highlight the chosen claim, its evidence and the facts they reference.
  useEffect(() => {
    const c = cy.current;
    if (!c) return;
    c.elements().removeClass("dim");
    if (!claimId) return;
    const claim = c.getElementById(claimId);
    if (claim.empty()) return;
    const evidenceNodes = claim.outgoers("node");
    const facts = evidenceNodes.outgoers("node");
    c.elements().not(claim.union(evidenceNodes).union(facts).union(claim.connectedEdges()).union(evidenceNodes.connectedEdges())).addClass("dim");
  }, [claimId, graph, hidden]);

  const claims = graph ? graph.nodes.filter((n) => n.label === "Claim" && n.properties.verification_status !== "SUPERSEDED") : [];
  const unresolved = new Set(evidence.filter((e) => e.relation === "CONTRADICTS" || e.relation === "REQUIRES_REVIEW").map((e) => e.claim_id));
  const selectedEvidence = selected && selected.label === "Evidence" ? evidence.find((e) => e.id === selected.id) : null;

  return (
    <section>
      <h2>Evidence Graph</h2>
      <CaseSelect />
      {caseId && <> <button disabled={busy} onClick={run}>{busy ? "Working…" : "Resolve entities & link evidence"}</button></>}
      {message && <p className="warn">{message}</p>}

      {graph && (
        <>
          <div className="toolbar">
            {labels.map((l) => (
              <label key={l} className="chip" style={{ borderColor: COLORS[l] }}>
                <input type="checkbox" checked={!hidden.has(l)}
                  onChange={() => setHidden((h) => { const n = new Set(h); n.has(l) ? n.delete(l) : n.add(l); return n; })} />
                {l}
              </label>
            ))}
            <select value={claimId} onChange={(e) => setClaimId(e.target.value)}>
              <option value="">Highlight a claim…</option>
              {claims.map((c) => (
                <option key={c.id} value={c.id}>
                  {unresolved.has(c.id) ? "⚠ " : ""}{c.properties.claim_type} {formatInr(c.properties.declared_amount)}
                </option>
              ))}
            </select>
          </div>
          <div className="graph-layout">
            <div ref={container} className="graph-canvas" />
            <aside className="graph-detail">
              <h4>Details</h4>
              {!selected && <p className="muted">Select a node.</p>}
              {selected && (
                <>
                  <p><strong>{selected.label}</strong></p>
                  <pre>{JSON.stringify(selected.properties, null, 2)}</pre>
                </>
              )}
              {selectedEvidence && (
                <div>
                  <p><strong>{selectedEvidence.document_filename}</strong>, page {selectedEvidence.page_number}</p>
                  <p className="quote">“{selectedEvidence.source_text}”</p>
                  <p>{selectedEvidence.rationale}</p>
                  <p className="muted">confidence {selectedEvidence.confidence} · {selectedEvidence.fact_verification_status}</p>
                </div>
              )}
            </aside>
          </div>
        </>
      )}

      {caseId && (
        <>
          <h3>Entity matches</h3>
          {matches.length === 0 ? <p className="muted">None yet. Run the resolution first.</p> : (
            <>
              <input className="wide" placeholder="Reason for the decision (required)" value={reason} onChange={(e) => setReason(e.target.value)} />
              <table>
                <thead><tr><th>Kind</th><th>Left</th><th>Right</th><th>Score</th><th>Method</th><th>Status</th><th /></tr></thead>
                <tbody>
                  {matches.map((m) => (
                    <tr key={m.id} title={m.explanation}>
                      <td>{m.entity_kind}</td><td>{m.left_label}</td><td>{m.right_label}</td>
                      <td>{m.score}</td><td>{m.method}</td>
                      <td className={m.status === "PENDING" ? "warn" : ""}>{m.status}</td>
                      <td>
                        {m.status !== "AUTO_ACCEPTED" && (
                          <>
                            <button onClick={() => decide(m.id, "CONFIRM")}>Confirm</button>{" "}
                            <button onClick={() => decide(m.id, "REJECT")}>Reject</button>
                          </>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </>
      )}
    </section>
  );
}
