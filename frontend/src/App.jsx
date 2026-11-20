import React from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import Dashboard from "./pages/Dashboard.jsx";
import CreateCase from "./pages/CreateCase.jsx";
import CaseDetail from "./pages/CaseDetail.jsx";
import DocumentUpload from "./pages/DocumentUpload.jsx";
import EvidenceGraph from "./pages/EvidenceGraph.jsx";
import ReconciliationWorkbench from "./pages/ReconciliationWorkbench.jsx";
import FinancialProfile from "./pages/FinancialProfile.jsx";
import ConflictReview from "./pages/ConflictReview.jsx";
import Placeholder from "./pages/Placeholder.jsx";

const pages = [
  { path: "/audit", label: "Audit Trail" },
];

export default function App() {
  return (
    <div className="layout">
      <nav className="sidebar">
        <h1>Financial Truth Engine</h1>
        <NavLink to="/" end>Dashboard</NavLink>
        <NavLink to="/cases/new">Create Case</NavLink>
        <NavLink to="/documents">Document Upload</NavLink>
        <NavLink to="/graph">Evidence Graph</NavLink>
        <NavLink to="/reconciliation">Reconciliation</NavLink>
        <NavLink to="/profile">Financial Profile</NavLink>
        <NavLink to="/conflicts">Conflict Review</NavLink>
        {pages.map((p) => (
          <NavLink key={p.path} to={p.path}>{p.label}</NavLink>
        ))}
      </nav>
      <main className="content">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/cases/new" element={<CreateCase />} />
          <Route path="/cases/:caseId" element={<CaseDetail />} />
          <Route path="/documents" element={<DocumentUpload />} />
          <Route path="/graph" element={<EvidenceGraph />} />
          <Route path="/reconciliation" element={<ReconciliationWorkbench />} />
          <Route path="/profile" element={<FinancialProfile />} />
          <Route path="/conflicts" element={<ConflictReview />} />
          {pages.map((p) => (
            <Route key={p.path} path={p.path} element={<Placeholder title={p.label} />} />
          ))}
        </Routes>
      </main>
    </div>
  );
}
