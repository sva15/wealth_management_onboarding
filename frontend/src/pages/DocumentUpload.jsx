import React, { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  errorMessage,
  extractCase,
  extractDocument,
  listCases,
  listDocuments,
  reprocessDocument,
  uploadDocuments,
} from "../api/client.js";
import { formatDateTime } from "../format.js";

export default function DocumentUpload() {
  const [params, setParams] = useSearchParams();
  const caseId = params.get("case") || "";
  const [cases, setCases] = useState([]);
  const [documents, setDocuments] = useState([]);
  const [messages, setMessages] = useState([]);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    listCases({ limit: 100 }).then((p) => setCases(p.items)).catch(() => {});
  }, []);

  const refresh = useCallback(() => {
    if (!caseId) return setDocuments([]);
    listDocuments(caseId).then(setDocuments).catch((e) => setMessages([{ level: "error", text: errorMessage(e) }]));
  }, [caseId]);

  useEffect(refresh, [refresh]);

  async function upload(fileList) {
    const files = Array.from(fileList);
    if (!caseId || files.length === 0) return;
    setBusy(true);
    try {
      const results = await uploadDocuments(caseId, files);
      setMessages(
        results
          .filter((r) => r.outcome !== "ACCEPTED")
          .map((r) => ({
            level: r.outcome === "DUPLICATE" ? "warn" : "error",
            text: `${r.filename}: ${r.outcome === "DUPLICATE" ? "duplicate file, already uploaded" : r.error_message}`,
          }))
      );
      refresh();
    } catch (e) {
      setMessages([{ level: "error", text: errorMessage(e) }]);
    } finally {
      setBusy(false);
    }
  }

  async function reprocess(id) {
    try {
      await reprocessDocument(id);
      refresh();
    } catch (e) {
      setMessages([{ level: "error", text: errorMessage(e) }]);
    }
  }

  async function extract(id) {
    setBusy(true);
    try {
      const result = id ? await extractDocument(id) : await extractCase(caseId);
      const outcomes = id ? [result] : result;
      setMessages(
        outcomes
          .filter((o) => o.issues.length > 0 || o.status !== "EXTRACTED")
          .map((o) => ({
            level: "warn",
            text: `${o.document.filename}: ${o.status}${o.issues.length ? ` (${o.issues.join("; ")})` : ""}`,
          }))
      );
      refresh();
    } catch (e) {
      setMessages([{ level: "error", text: errorMessage(e) }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <h2>Document Upload</h2>
      <label className="inline">
        Case{" "}
        <select value={caseId} onChange={(e) => setParams(e.target.value ? { case: e.target.value } : {})}>
          <option value="">Select a case…</option>
          {cases.map((c) => (
            <option key={c.id} value={c.id}>{c.customer_name} ({c.status})</option>
          ))}
        </select>
      </label>
      {caseId && <> · <Link to={`/cases/${caseId}`}>Open case</Link></>}

      <div
        className={`dropzone${dragging ? " dragging" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); upload(e.dataTransfer.files); }}
      >
        <p>{busy ? "Uploading…" : "Drag PDF or text files here, or"}</p>
        <input type="file" multiple accept=".pdf,.txt" disabled={!caseId || busy}
               onChange={(e) => { upload(e.target.files); e.target.value = ""; }} />
        {!caseId && <p className="muted">Select a case first.</p>}
      </div>

      {messages.map((m, i) => (
        <p key={i} className={m.level === "error" ? "error" : "warn"}>{m.text}</p>
      ))}

      <h3>Uploaded documents</h3>
      {documents.length > 0 && (
        <p><button disabled={busy} onClick={() => extract(null)}>Extract facts from all classified documents</button></p>
      )}
      {documents.length === 0 ? (
        <p className="muted">No documents yet.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>File</th><th>Type</th><th>Confidence</th><th>Status</th><th>Pages</th>
              <th>Uploaded</th><th>Details</th><th />
            </tr>
          </thead>
          <tbody>
            {documents.map((d) => (
              <tr key={d.id}>
                <td title={`SHA-256 ${d.sha256}`}>{d.filename}</td>
                <td>{d.document_type || "—"}</td>
                <td>{d.classification_confidence ?? "—"}</td>
                <td className={`status-${d.processing_status}`}>{d.processing_status}</td>
                <td>{d.page_count ?? "—"}</td>
                <td>{formatDateTime(d.uploaded_at)}</td>
                <td className={d.error_message ? "error" : "muted"}>
                  {d.error_message || d.classification_explanation || ""}
                </td>
                <td>
                  <button onClick={() => reprocess(d.id)}>Reprocess</button>{" "}
                  <button disabled={busy} onClick={() => extract(d.id)}>Extract</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
