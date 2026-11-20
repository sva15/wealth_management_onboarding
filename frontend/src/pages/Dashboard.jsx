import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getDashboard, getReadiness } from "../api/client.js";
import { formatDateTime } from "../format.js";

function Stat({ label, value }) {
  return (
    <div className="stat">
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

export default function Dashboard() {
  const [summary, setSummary] = useState(null);
  const [health, setHealth] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    getDashboard().then(setSummary).catch(() => setError("Could not load dashboard"));
    getReadiness()
      .then((r) => setHealth(r.data))
      .catch(() => setHealth({ status: "unreachable", checks: {} }));
  }, []);

  return (
    <section>
      <h2>Dashboard</h2>
      {error && <p className="error">{error}</p>}
      {summary && (
        <>
          <div className="stats">
            <Stat label="Onboarding cases" value={summary.total_cases} />
            <Stat label="Requiring review" value={summary.requires_review} />
            <Stat label="Awaiting customer evidence" value={summary.awaiting_customer_evidence} />
            <Stat label="Extraction failures" value={summary.extraction_failures} />
          </div>
          <h3>Recently updated cases</h3>
          {summary.recent_cases.length === 0 ? (
            <p>No cases yet. <Link to="/cases/new">Create one</Link>.</p>
          ) : (
            <table>
              <thead>
                <tr><th>Customer</th><th>Status</th><th>Last updated</th></tr>
              </thead>
              <tbody>
                {summary.recent_cases.map((c) => (
                  <tr key={c.id}>
                    <td><Link to={`/cases/${c.id}`}>{c.customer_name}</Link></td>
                    <td>{c.status}</td>
                    <td>{formatDateTime(c.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
      <h3>Backend status</h3>
      {health ? <pre>{JSON.stringify(health, null, 2)}</pre> : <p>Checking…</p>}
    </section>
  );
}
