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

export const api = {
  dashboard: () => request("/dashboard"),

  uploadDepot: (file) => {
    const fd = new FormData();
    fd.append("file", file);
    return request("/import/depot", { method: "POST", body: fd });
  },
  uploadChallan: (file) => {
    const fd = new FormData();
    fd.append("file", file);
    return request("/import/challan", { method: "POST", body: fd });
  },
  adjustTransaction: (id, body) =>
    request(`/transactions/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  importBatches: () => request("/import/batches"),

  pendingGroupings: () => request("/certificates/pending"),
  searchCertificates: (params) =>
    request(`/certificates?${new URLSearchParams(
      Object.fromEntries(Object.entries(params).filter(([, v]) => v))
    )}`),
  getCertificate: (id) => request(`/certificates/${id}`),
  generate: (tin, period) =>
    request("/certificates/generate", {
      method: "POST", body: JSON.stringify({ tin, period }),
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
  anomalies: (id) => request(`/certificates/${id}/anomalies`),
  dispatch: (id, payload) =>
    request(`/certificates/${id}/dispatch`, {
      method: "POST", body: JSON.stringify(payload),
    }),
  processQueue: () => request("/dispatch/process", { method: "POST" }),
  dispatchJobsFor: (certId) => request(`/dispatch/jobs?certificate_id=${certId}`),
  dispatchJobs: () => request("/dispatch/jobs"),
  pdfUrl: (id) => `${BASE}/certificates/${id}/pdf`,
  whatsappLinks: (id) => request(`/certificates/${id}/whatsapp-links`),
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
  uploadSeal: (file) => {
    const fd = new FormData(); fd.append("file", file);
    return request("/settings/org/seal", { method: "POST", body: fd });
  },
  uploadSignature: (file) => {
    const fd = new FormData(); fd.append("file", file);
    return request("/settings/org/signature", { method: "POST", body: fd });
  },
  uploadSealImage: (file) => {
    const fd = new FormData(); fd.append("file", file);
    return request("/settings/org/seal-image", { method: "POST", body: fd });
  },
  getNumbering: () => request("/settings/numbering"),
  updateNumbering: (body) =>
    request("/settings/numbering", { method: "PUT", body: JSON.stringify(body) }),
  resetDatabase: (confirm) =>
    request("/settings/database/reset", {
      method: "POST", body: JSON.stringify({ confirm }),
    }),

  createSupplier: (body) =>
    request("/suppliers", { method: "POST", body: JSON.stringify(body) }),
};
