import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { createCaseWithDeclaration, errorMessage } from "../api/client.js";

const ASSET_TYPES = ["INVESTMENT", "BANK_DEPOSIT", "PROPERTY", "BUSINESS", "OTHER"];
const emptyAsset = { asset_type: "INVESTMENT", description: "", value: "" };
const emptyLiability = { description: "", amount: "" };

const orNull = (v) => (v === "" ? null : v);

export default function CreateCase() {
  const navigate = useNavigate();
  const [customer, setCustomer] = useState({ full_name: "", pan: "", date_of_birth: "", email: "" });
  const [decl, setDecl] = useState({
    declared_net_worth: "",
    annual_income: "",
    source_of_wealth: "",
    source_of_wealth_amount: "",
    source_of_funds: "",
    intended_investment_amount: "",
  });
  const [assets, setAssets] = useState([{ ...emptyAsset }]);
  const [liabilities, setLiabilities] = useState([]);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const setField = (setter) => (e) => setter((s) => ({ ...s, [e.target.name]: e.target.value }));
  const updateRow = (setter, i) => (e) =>
    setter((rows) => rows.map((r, j) => (j === i ? { ...r, [e.target.name]: e.target.value } : r)));

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const kase = await createCaseWithDeclaration(
        {
          full_name: customer.full_name,
          pan: orNull(customer.pan.toUpperCase()),
          date_of_birth: orNull(customer.date_of_birth),
          email: orNull(customer.email),
        },
        {
          currency: "INR",
          declared_net_worth: decl.declared_net_worth,
          annual_income: orNull(decl.annual_income),
          source_of_wealth: decl.source_of_wealth,
          source_of_wealth_amount: orNull(decl.source_of_wealth_amount),
          source_of_funds: decl.source_of_funds,
          intended_investment_amount: decl.intended_investment_amount,
          assets: assets.filter((a) => a.description || a.value),
          liabilities: liabilities.filter((l) => l.description || l.amount),
        }
      );
      navigate(`/cases/${kase.id}`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <h2>Create Case</h2>
      <p className="muted">Fictional customers only. Amounts are in rupees.</p>
      <form onSubmit={submit} className="form">
        <h3>Customer</h3>
        <label>Full name<input name="full_name" required value={customer.full_name} onChange={setField(setCustomer)} /></label>
        <label>PAN<input name="pan" placeholder="ABCDE1234F" value={customer.pan} onChange={setField(setCustomer)} /></label>
        <label>Date of birth<input type="date" name="date_of_birth" value={customer.date_of_birth} onChange={setField(setCustomer)} /></label>
        <label>Email<input name="email" value={customer.email} onChange={setField(setCustomer)} /></label>

        <h3>Declaration</h3>
        <label>Declared net worth<input name="declared_net_worth" required inputMode="decimal" value={decl.declared_net_worth} onChange={setField(setDecl)} /></label>
        <label>Annual income<input name="annual_income" inputMode="decimal" value={decl.annual_income} onChange={setField(setDecl)} /></label>
        <label>Source of wealth<input name="source_of_wealth" required value={decl.source_of_wealth} onChange={setField(setDecl)} /></label>
        <label>Declared value tied to source of wealth (e.g. sale value)<input name="source_of_wealth_amount" inputMode="decimal" value={decl.source_of_wealth_amount} onChange={setField(setDecl)} /></label>
        <label>Source of funds<input name="source_of_funds" required value={decl.source_of_funds} onChange={setField(setDecl)} /></label>
        <label>Intended investment amount<input name="intended_investment_amount" required inputMode="decimal" value={decl.intended_investment_amount} onChange={setField(setDecl)} /></label>

        <h3>Major assets</h3>
        {assets.map((a, i) => (
          <div className="row" key={i}>
            <select name="asset_type" value={a.asset_type} onChange={updateRow(setAssets, i)}>
              {ASSET_TYPES.map((t) => <option key={t}>{t}</option>)}
            </select>
            <input name="description" placeholder="Description" value={a.description} onChange={updateRow(setAssets, i)} />
            <input name="value" placeholder="Value" inputMode="decimal" value={a.value} onChange={updateRow(setAssets, i)} />
            <button type="button" onClick={() => setAssets((r) => r.filter((_, j) => j !== i))}>Remove</button>
          </div>
        ))}
        <button type="button" onClick={() => setAssets((r) => [...r, { ...emptyAsset }])}>Add asset</button>

        <h3>Liabilities</h3>
        {liabilities.map((l, i) => (
          <div className="row" key={i}>
            <input name="description" placeholder="Description" value={l.description} onChange={updateRow(setLiabilities, i)} />
            <input name="amount" placeholder="Amount" inputMode="decimal" value={l.amount} onChange={updateRow(setLiabilities, i)} />
            <button type="button" onClick={() => setLiabilities((r) => r.filter((_, j) => j !== i))}>Remove</button>
          </div>
        ))}
        <button type="button" onClick={() => setLiabilities((r) => [...r, { ...emptyLiability }])}>Add liability</button>

        {error && <p className="error">{error}</p>}
        <div><button type="submit" disabled={busy}>{busy ? "Saving…" : "Create case"}</button></div>
      </form>
    </section>
  );
}
