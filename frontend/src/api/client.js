import axios from "axios";

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "http://localhost:8000",
  // Placeholder identity until real authentication is added.
  headers: { "X-Actor-Id": "local-analyst", "X-Actor-Role": "analyst" },
});

export const getReadiness = () => api.get("/health/ready", { validateStatus: () => true });
export const getDashboard = () => api.get("/dashboard/summary").then((r) => r.data);
export const listCases = (params) => api.get("/cases", { params }).then((r) => r.data);
export const getCase = (id) => api.get(`/cases/${id}`).then((r) => r.data);
export const getClaims = (id) => api.get(`/cases/${id}/claims`).then((r) => r.data);
export const listDocuments = (id) => api.get(`/cases/${id}/documents`).then((r) => r.data);
export const reprocessDocument = (id) => api.post(`/documents/${id}/process`).then((r) => r.data);
export const extractDocument = (id) => api.post(`/documents/${id}/extract`).then((r) => r.data);
export const extractCase = (id) => api.post(`/cases/${id}/extract`).then((r) => r.data);
export const listFacts = (id, params) =>
  api.get(`/cases/${id}/facts`, { params: { limit: 500, ...params } }).then((r) => r.data);
export const linkEvidence = (id) => api.post(`/cases/${id}/link-evidence`).then((r) => r.data);
export const getGraph = (id) => api.get(`/cases/${id}/graph`).then((r) => r.data);
export const listEvidence = (id) => api.get(`/cases/${id}/evidence`).then((r) => r.data);
export const listMatches = (id) => api.get(`/cases/${id}/entity-matches`).then((r) => r.data);
export const decideMatch = (matchId, decision, reason) =>
  api.post(`/entity-matches/${matchId}/decision`, { decision, reason }).then((r) => r.data);
export const getSaleProceeds = (id) =>
  api.get(`/cases/${id}/reconciliation/sale-proceeds`).then((r) => r.data);
export const runReconciliation = (id) => api.post(`/cases/${id}/reconciliation/run`).then((r) => r.data);
export const getReconciliation = (id) =>
  api.get(`/cases/${id}/reconciliation`, { validateStatus: (s) => s === 200 || s === 404 }).then((r) => (r.status === 200 ? r.data : null));
export const listConflicts = (id, params) => api.get(`/cases/${id}/conflicts`, { params }).then((r) => r.data);

export async function uploadDocuments(caseId, files) {
  const form = new FormData();
  files.forEach((f) => form.append("files", f));
  const { data } = await api.post(`/cases/${caseId}/documents`, form);
  return data.results;
}

export async function createCaseWithDeclaration(customer, declaration) {
  const { data: cust } = await api.post("/customers", customer);
  const { data: kase } = await api.post("/cases", { customer_id: cust.id });
  await api.post(`/cases/${kase.id}/declarations`, declaration);
  return kase;
}

export function errorMessage(err) {
  const e = err?.response?.data?.error;
  if (!e) return err?.message || "Request failed";
  if (e.details?.length) {
    return `${e.message}: ${e.details.map((d) => `${d.loc.slice(1).join(".")} ${d.msg}`).join("; ")}`;
  }
  return e.message;
}
