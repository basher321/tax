// Thin fetch wrapper. All endpoints live under /api (proxied to FastAPI).
const BASE = "/api";

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: options.body instanceof FormData
      ? undefined
      : { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let detail;
    try { detail = (await res.json()).detail; } catch { detail = res.statusText; }
    const err = new Error(typeof detail === "string" ? detail : "Request failed");
    err.detail = detail; // may carry {blocked, anomalies} for dispatch blocks
    err.status = res.status;
    throw err;
  }
  return res.json();
}

const dropBlank = (params) =>
  Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ""));

const qs = (params) => new URLSearchParams(dropBlank(params)).toString();

export const api = {
  dashboard: () => request("/dashboard"),

  // ---- Companies (multi-company foundation) ----
  listCompanies: () => request("/companies"),
  createCompany: (body) =>
    request("/companies", { method: "POST", body: JSON.stringify(body) }),
  updateCompany: (id, body) =>
    request(`/companies/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  uploadCompanySeal: (id, file) => {
    const fd = new FormData(); fd.append("file", file);
    return request(`/companies/${id}/seal`, { method: "POST", body: fd });
  },
  uploadLetterheadHeader: (id, file) => {
    const fd = new FormData(); fd.append("file", file);
    return request(`/companies/${id}/letterhead/header`, { method: "POST", body: fd });
  },
  uploadLetterheadFooter: (id, file) => {
    const fd = new FormData(); fd.append("file", file);
    return request(`/companies/${id}/letterhead/footer`, { method: "POST", body: fd });
  },
  companySealUrl: (id) => `${BASE}/companies/${id}/seal`,
  letterheadHeaderUrl: (id) => `${BASE}/companies/${id}/letterhead/header`,
  letterheadFooterUrl: (id) => `${BASE}/companies/${id}/letterhead/footer`,

  // ---- Named signatures: every one flagged enabled renders on every
  // certificate generated for the company (no per-certificate choice) ----
  listSignatures: (companyId) => request(`/companies/${companyId}/signatures`),
  createSignature: (companyId, name, designation, email, file) => {
    const fd = new FormData();
    fd.append("name", name);
    if (designation) fd.append("designation", designation);
    if (email) fd.append("email", email);
    fd.append("file", file);
    return request(`/companies/${companyId}/signatures`, { method: "POST", body: fd });
  },
  updateSignature: (companyId, sigId, body) =>
    request(`/companies/${companyId}/signatures/${sigId}`, {
      method: "PATCH", body: JSON.stringify(body),
    }),
  deleteSignature: (companyId, sigId) =>
    request(`/companies/${companyId}/signatures/${sigId}`, { method: "DELETE" }),
  signatureImageUrl: (companyId, sigId) =>
    `${BASE}/companies/${companyId}/signatures/${sigId}/image`,

  // ---- Numbering (per-company) ----
  getNumbering: (companyId) => request(`/companies/${companyId}/numbering`),
  updateNumbering: (companyId, body) =>
    request(`/companies/${companyId}/numbering`, { method: "PUT", body: JSON.stringify(body) }),

  // ---- Import ----
  uploadDepot: (companyId, file) => {
    const fd = new FormData();
    fd.append("company_id", companyId);
    fd.append("file", file);
    return request("/import/depot", { method: "POST", body: fd });
  },
  importBatches: (companyId) => request(`/import/batches?company_id=${companyId}`),

  // ---- Certificates ----
  pendingGroupings: (companyId, filters = {}) =>
    request(`/certificates/pending?${qs({ company_id: companyId, ...filters })}`),
  searchCertificates: (params) => request(`/certificates?${qs(params)}`),
  getCertificate: (id) => request(`/certificates/${id}`),
  generate: (companyId, tin, period) =>
    request("/certificates/generate", {
      method: "POST",
      body: JSON.stringify({ company_id: companyId, tin, period }),
    }),
  generateBulk: (items) =>
    request("/certificates/generate/bulk", {
      method: "POST", body: JSON.stringify({ items }),
    }),
  updateRemarks: (id, remarks) =>
    request(`/certificates/${id}/remarks`, {
      method: "PATCH", body: JSON.stringify({ remarks }),
    }),
  updateTinStatus: (id, has12DigitTin) =>
    request(`/certificates/${id}/tin-status`, {
      method: "PATCH", body: JSON.stringify({ has_12_digit_tin: has12DigitTin }),
    }),
  updateIssueDate: (id, mode, issueDate) =>
    request(`/certificates/${id}/issue-date`, {
      method: "PATCH", body: JSON.stringify({ mode, issue_date: issueDate || null }),
    }),
  anomalies: (id) => request(`/certificates/${id}/anomalies`),
  anomaliesBulk: (filters) =>
    request("/certificates/anomalies/bulk", { method: "POST", body: JSON.stringify(dropBlank(filters)) }),
  dispatchBulk: (filters) =>
    request("/certificates/dispatch/bulk", { method: "POST", body: JSON.stringify(dropBlank(filters)) }),
  exportUrl: (params) => `${BASE}/certificates/export?${qs(params)}`,
  dispatch: (id, payload) =>
    request(`/certificates/${id}/dispatch`, {
      method: "POST", body: JSON.stringify(payload),
    }),
  processQueue: () => request("/dispatch/process", { method: "POST" }),
  dispatchJobsFor: (certId) => request(`/dispatch/jobs?certificate_id=${certId}`),
  dispatchJobs: () => request("/dispatch/jobs"),
  pdfUrl: (id) => `${BASE}/certificates/${id}/pdf`,
  certificateImageUrl: (id) => `${BASE}/certificates/${id}/image`,
  whatsappLinks: (id) => request(`/certificates/${id}/whatsapp-links`),

  // ---- Legacy global org settings (SMTP/WhatsApp/dispatch mode stay global) ----
  logoUrl: `${BASE}/settings/org/logo`,
  sealUrl: `${BASE}/settings/org/seal`,
  signatureUrl: `${BASE}/settings/org/signature`,
  sealImageUrl: `${BASE}/settings/org/seal-image`,

  getOrg: () => request("/settings/org"),
  updateOrg: (body) =>
    request("/settings/org", { method: "PUT", body: JSON.stringify(body) }),
  testEmail: () => request("/settings/org/test-email", { method: "POST" }),
  uploadLogo: (file) => {
    const fd = new FormData(); fd.append("file", file);
    return request("/settings/org/logo", { method: "POST", body: fd });
  },
  resetDatabase: (confirm) =>
    request("/settings/database/reset", {
      method: "POST", body: JSON.stringify({ confirm }),
    }),

  createSupplier: (body) =>
    request("/suppliers", { method: "POST", body: JSON.stringify(body) }),
};
