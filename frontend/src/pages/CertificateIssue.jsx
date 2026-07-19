import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client.js";
import { useCompany } from "../context/CompanyContext.jsx";

const fmt = (n) => (n == null ? "" : Number(n).toLocaleString());

const normalizeAnomalies = (items) =>
  Array.isArray(items)
    ? items.map((a) => ({
        code: a?.code || "ANOMALY",
        message: a?.message || "Dispatch is blocked by an anomaly check.",
      }))
    : [];

async function blockedAnomalies(certId, detail) {
  const fromError = normalizeAnomalies(detail?.anomalies);
  if (fromError.length) return fromError;
  try {
    const fromApi = normalizeAnomalies(await api.anomalies(certId));
    if (fromApi.length) return fromApi;
  } catch {
    // Fall through to the generic row below.
  }
  return [{
    code: "BLOCKED",
    message: "Dispatch is blocked, but the anomaly details could not be loaded.",
  }];
}

/* ------------------------------------------------------------------ */
/* Preview modal: fixed layout, read-only except Remarks               */
/* ------------------------------------------------------------------ */
function Preview({ certId, onClose }) {
  const [cert, setCert] = useState(null);
  const [anomalies, setAnomalies] = useState([]);
  const [remarks, setRemarks] = useState("");
  const [override, setOverride] = useState("");
  const [notice, setNotice] = useState(null);
  const [noticeKind, setNoticeKind] = useState("ok");
  const [emailBusy, setEmailBusy] = useState(false);
  const [dateMode, setDateMode] = useState("auto");
  const [manualDate, setManualDate] = useState("");
  // Cache-busts the certificate image below every time the server re-renders
  // it, so edits (Remarks/TIN/date) are reflected immediately instead of
  // showing a browser-cached copy of the old image at the same URL.
  const [imgVersion, setImgVersion] = useState(0);

  const showNotice = (message, kind = "ok") => {
    setNotice(message);
    setNoticeKind(kind);
  };

  const [waLinks, setWaLinks] = useState(null);
  const [emailJobs, setEmailJobs] = useState([]);

  const refreshEmailStatus = () =>
    api.dispatchJobsFor(certId).then(
      (jobs) => setEmailJobs(jobs.filter((j) => j.channel === "email")),
      () => {},
    );

  const load = () =>
    Promise.all([
      api.getCertificate(certId),
      api.anomalies(certId),
      api.whatsappLinks(certId).catch(() => null),
      refreshEmailStatus(),
    ]).then(
      ([c, a, wa]) => {
        setCert(c); setRemarks(c.remarks || ""); setAnomalies(a); setWaLinks(wa);
        setDateMode(c.issue_date_mode || "auto");
        setManualDate(c.issue_date || "");
        setImgVersion((v) => v + 1);
      }
    );
  useEffect(() => { load(); }, [certId]);

  async function saveRemarks() {
    const c = await api.updateRemarks(certId, remarks);
    setCert(c);
    setImgVersion((v) => v + 1);
    showNotice("Remarks saved - certificate re-rendered.");
  }

  async function setTinStatus(has12DigitTin) {
    const c = await api.updateTinStatus(certId, has12DigitTin);
    setCert(c);
    setImgVersion((v) => v + 1);
    showNotice("TIN status saved - certificate re-rendered.");
  }

  async function saveIssueDate() {
    if (dateMode === "manual" && !manualDate) {
      showNotice("Pick a date for Manual mode before saving.", "warn");
      return;
    }
    const c = await api.updateIssueDate(certId, dateMode, dateMode === "manual" ? manualDate : null);
    setCert(c);
    setManualDate(c.issue_date || "");
    setImgVersion((v) => v + 1);
    showNotice("Issue date saved - certificate re-rendered.");
  }

  async function sendEmail() {
    showNotice("Sending email with certificate PDF attached...");
    setEmailBusy(true);
    try {
      const org = await api.getOrg();
      if (!org.smtp_host || !(org.smtp_from || org.smtp_user || org.officer_email)) {
        openManualEmail();
        showNotice("SMTP is not configured. Gmail compose and the PDF opened in separate windows; attach the PDF manually, or configure SMTP in Settings for automatic attachment.", "warn");
        return;
      }
      const jobs = await api.dispatch(certId, {
        channel: "email",
        override_reason: override || undefined,
        user: "web-ui",
      });
      const failed = jobs.find((j) => j.error);
      if (failed) {
        if (failed.error.includes("SMTP is not configured")) {
          openManualEmail();
          showNotice("SMTP is not configured. Gmail compose and the PDF opened in separate windows; attach the PDF manually, or configure SMTP in Settings for automatic attachment.", "warn");
        } else {
          showNotice(`Email failed: ${failed.error}`, "err");
        }
        return;
      }
      if (jobs.some((j) => j.status === "queued")) {
        showNotice(`Email queued, not sent yet: ${jobs.map((j) => j.recipient).join(", ")}. Settings is in offline dispatch mode, so run Process Queue or switch Dispatch mode to Online to send immediately.`, "warn");
      } else {
        showNotice(`Email sent successfully with certificate PDF attached to: ${jobs.map((j) => j.recipient).join(", ")}`);
      }
    } catch (err) {
      if (err.detail?.blocked) {
        setAnomalies(await blockedAnomalies(certId, err.detail));
        showNotice("Send blocked. Fix the anomalies below, or enter an override reason and retry.", "err");
      } else {
        showNotice(`Email failed: ${err.message}`, "err");
      }
    } finally {
      setEmailBusy(false);
      refreshEmailStatus();
    }
  }

  function sendWhatsApp() {
    setNotice(null);
    if (waLinks === null) {
      showNotice("The WhatsApp link is still loading. Please try again in a moment.", "warn");
      return;
    }
    if (!waLinks.links.length) {
      showNotice("No WhatsApp number on record for this supplier.");
      return;
    }
    window.open(waLinks.links[0].url, "_blank", "noopener");
    window.open(api.pdfUrl(cert.id), "_blank", "noopener");
    showNotice("The PDF and WhatsApp chat were opened. Attach the certificate PDF in WhatsApp to send it with no API cost.", "warn");
  }

  function openManualEmail() {
    const recipients = (cert.supplier.contacts || [])
      .filter((c) => c.kind === "email")
      .map((c) => c.value)
      .join(",");
    const subject = `Tax Deduction Certificate ${cert.certificate_no}`;
    const body = [
      `Dear ${cert.supplier.name},`,
      "",
      `Please find attached the Certificate of Deduction of Tax (${cert.certificate_no}) for the period ${cert.period}.`,
      "",
      "Regards,",
    ].join("\n");
    const gmailUrl = `https://mail.google.com/mail/?view=cm&fs=1&to=${encodeURIComponent(recipients)}&su=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
    window.open(gmailUrl, "_blank", "noopener");
    window.open(api.pdfUrl(cert.id), "_blank", "noopener");
  }

  if (!cert) return null;

  return (
    <div className="fixed inset-0 bg-ink/50 flex items-start justify-center overflow-auto p-6 z-20">
      <div className="bg-white rounded-lg w-full max-w-4xl">
        {/* action bar - all dispatch options live here, inside Certificate Issue */}
        <div className="flex items-center gap-2 px-5 py-3 border-b border-rule sticky top-0 bg-white rounded-t-lg">
          <div className="font-mono text-sm mr-auto">{cert.certificate_no}</div>
          <button className="btn-ghost" onClick={sendEmail} disabled={emailBusy}>
            {emailBusy ? "Sending..." : "Send email"}
          </button>
          <button className="btn-ghost" onClick={sendWhatsApp}>Send WhatsApp</button>
          <button className="btn-ghost" onClick={() => {
            const w = window.open(api.pdfUrl(cert.id), "_blank");
            w?.addEventListener("load", () => w.print());
          }}>Print</button>
          <a className="btn-ghost" href={api.pdfUrl(cert.id)} download>Download PDF</a>
          <a className="btn-ghost" href={api.certificateImageUrl(cert.id)} download>
            Download image
          </a>
          <button className="btn-primary" onClick={onClose}>Close</button>
        </div>

        {notice && (
          <p className={`mx-5 mt-3 rounded border px-3 py-2 text-sm ${
            noticeKind === "err"
              ? "border-red-200 bg-red-50 text-red-800"
              : noticeKind === "warn"
                ? "border-amber-200 bg-amber-50 text-amber-800"
                : "border-ledger/20 bg-ledger/[0.07] text-ledger"
          }`}>
            {notice}
          </p>
        )}
        {anomalies.length > 0 && (
          <div className="mx-5 mt-3 border border-red-300 bg-red-50 rounded p-3 text-sm">
            <p className="font-medium text-red-800 mb-1">
              Anomalies - sending is blocked until fixed or overridden:
            </p>
            <ul className="list-disc ml-5 text-red-800 space-y-0.5">
              {normalizeAnomalies(anomalies).map((a, i) => (
                <li key={i}><span className="font-mono text-xs">{a.code}</span> - {a.message}</li>
              ))}
            </ul>
            <input
              className="input mt-2"
              placeholder="Override reason (logged with your name)..."
              value={override}
              onChange={(e) => setOverride(e.target.value)}
            />
          </div>
        )}

        {emailJobs.length > 0 && (
          <div className="mx-5 mt-3 border border-rule rounded p-3 text-sm">
            <div className="flex items-center mb-1">
              <p className="font-medium mr-auto">Email delivery status</p>
              <button className="btn-ghost !py-0.5 text-xs" onClick={refreshEmailStatus}>Refresh</button>
            </div>
            <ul className="space-y-0.5">
              {emailJobs.map((j) => (
                <li key={j.id} className="flex items-center gap-2">
                  <span>{j.recipient}</span>
                  <span className="text-ink/50">- {j.status}</span>
                  {j.status === "sent" && (
                    j.opened_at
                      ? <span className="text-ledger text-xs">Opened {new Date(j.opened_at).toLocaleString()}</span>
                      : <span className="text-ink/40 text-xs">Not opened yet</span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Editable certificate fields, kept separate from the certificate
            image below — that image is the exact same PDF used for Print,
            WhatsApp sharing, and email attachment, so it can't contain
            interactive controls. Saving here re-renders that PDF/image
            immediately (see setImgVersion calls). */}
        <div className="mx-5 mt-3 card p-4 space-y-4 text-sm">
          <h3 className="font-medium">Edit certificate details</h3>
          <div>
            <label className="label">Remarks (the only editable table field)</label>
            <div className="flex gap-2">
              <input className="input" value={remarks} onChange={(e) => setRemarks(e.target.value)} />
              <button className="btn-primary" onClick={saveRemarks}>Save remarks</button>
            </div>
          </div>
          <div>
            <label className="label">Does the payee have a Twelve-digit TIN?</label>
            <div className="flex items-center gap-4">
              <label className="flex items-center gap-1.5 cursor-pointer">
                <input type="radio" name="has12DigitTin" checked={cert.has_12_digit_tin === true}
                  onChange={() => setTinStatus(true)} />
                Yes
              </label>
              <label className="flex items-center gap-1.5 cursor-pointer">
                <input type="radio" name="has12DigitTin" checked={cert.has_12_digit_tin === false}
                  onChange={() => setTinStatus(false)} />
                No
              </label>
            </div>
          </div>
          <div>
            <label className="label">Issue date</label>
            <div className="flex items-center gap-3">
              <label className="flex items-center gap-1.5 cursor-pointer">
                <input type="radio" name="dateMode" checked={dateMode === "auto"}
                  onChange={() => setDateMode("auto")} />
                Automatic (today)
              </label>
              <label className="flex items-center gap-1.5 cursor-pointer">
                <input type="radio" name="dateMode" checked={dateMode === "manual"}
                  onChange={() => setDateMode("manual")} />
                Manual
              </label>
              {dateMode === "manual" && (
                <input type="date" className="input !w-auto" value={manualDate}
                  onChange={(e) => setManualDate(e.target.value)} />
              )}
              <button className="btn-ghost" onClick={saveIssueDate}>Save date</button>
            </div>
          </div>
        </div>

        {/* The certificate itself: the exact image rasterized from the same
            PDF used for Print, WhatsApp sharing, and email attachment — not
            a separate HTML re-implementation — so this is guaranteed
            pixel-identical to every exported/printed/shared format. */}
        <img
          src={`${api.certificateImageUrl(cert.id)}?v=${imgVersion}`}
          alt={`Certificate ${cert.certificate_no}`}
          className="w-full h-auto block mt-3 rounded-b-lg"
        />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Vendor onboarding modal: Email, WhatsApp, Company Name, Company     */
/* Address, TIN (12-digit), BIN are all mandatory — validated inline   */
/* client-side, and re-validated server-side by POST /suppliers.       */
/* ------------------------------------------------------------------ */
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const WHATSAPP_RE = /^\+?\d{10,15}$/;
const TIN_RE = /^\d{12}$/;

const VENDOR_FIELDS = [
  { key: "name", label: "Company name" },
  { key: "address", label: "Company address" },
  { key: "tin", label: "TIN (12 digits)" },
  { key: "bin", label: "BIN" },
  { key: "email", label: "Email" },
  { key: "whatsapp", label: "WhatsApp No." },
];

function validateVendorField(key, value) {
  const v = (value || "").trim();
  if (!v) return "This field is required";
  if (key === "tin" && !TIN_RE.test(v.replace(/\D/g, "")))
    return "TIN must be exactly 12 digits";
  if (key === "email" && !EMAIL_RE.test(v))
    return "Enter a valid email address";
  if (key === "whatsapp" && !WHATSAPP_RE.test(v.replace(/[\s-]/g, "")))
    return "Enter a valid WhatsApp number (10-15 digits)";
  return null;
}

function VendorOnboardingModal({ companyId, onClose, onCreated }) {
  const [form, setForm] = useState({ name: "", address: "", tin: "", bin: "", email: "", whatsapp: "" });
  const [touched, setTouched] = useState({});
  const [busy, setBusy] = useState(false);
  const [serverError, setServerError] = useState(null);

  const errors = useMemo(
    () => Object.fromEntries(VENDOR_FIELDS.map(({ key }) => [key, validateVendorField(key, form[key])])),
    [form],
  );
  const isValid = Object.values(errors).every((e) => !e);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const blur = (k) => () => setTouched({ ...touched, [k]: true });

  async function submit() {
    setTouched(Object.fromEntries(VENDOR_FIELDS.map(({ key }) => [key, true])));
    if (!isValid) return;
    setBusy(true);
    setServerError(null);
    try {
      const supplier = await api.createSupplier({ ...form, company_id: companyId });
      onCreated(supplier);
    } catch (err) {
      setServerError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-ink/50 flex items-start justify-center overflow-auto p-6 z-30">
      <div className="bg-white rounded-lg w-full max-w-lg">
        <div className="flex items-center gap-2 px-5 py-3 border-b border-rule">
          <h2 className="font-medium mr-auto">Add vendor</h2>
          <button className="btn-ghost" onClick={onClose}>Close</button>
        </div>
        <div className="p-5 space-y-3">
          {serverError && (
            <p className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">{serverError}</p>
          )}
          {VENDOR_FIELDS.map(({ key, label }) => (
            <div key={key}>
              <span className="label">{label}</span>
              <input
                className={`input ${touched[key] && errors[key] ? "border-red-400 focus:border-red-500" : ""}`}
                value={form[key]}
                onChange={set(key)}
                onBlur={blur(key)}
              />
              {touched[key] && errors[key] && (
                <p className="text-xs text-red-700 mt-1">{errors[key]}</p>
              )}
            </div>
          ))}
          <button className="btn-primary w-full" onClick={submit} disabled={busy || !isValid}>
            {busy ? "Saving..." : "Save vendor"}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Bulk anomaly check + bulk send results panels (items 5 & 10)        */
/* ------------------------------------------------------------------ */
function BulkAnomalyPanel({ results, onClose }) {
  return (
    <div className="card border-red-300 bg-red-50/40">
      <div className="px-5 py-3 border-b border-red-200 flex items-center">
        <h2 className="font-medium text-red-800 mr-auto">
          Bulk anomaly check — {results.length} certificate(s) need attention
        </h2>
        <button className="btn-ghost !py-0.5" onClick={onClose}>Dismiss</button>
      </div>
      {results.length === 0 ? (
        <p className="p-5 text-sm text-ledger">No anomalies found across the matching certificates.</p>
      ) : (
        <ul className="divide-y divide-red-200/70 text-sm">
          {results.map((r) => (
            <li key={r.certificate_id} className="px-5 py-2.5">
              <div className="font-medium">{r.supplier_name} <span className="font-mono text-ink/50">{r.certificate_no}</span></div>
              <ul className="list-disc ml-5 text-red-800">
                {r.anomalies.map((a, i) => (
                  <li key={i}><span className="font-mono text-xs">{a.code}</span> - {a.message}</li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function BulkSendPanel({ results, onClose }) {
  const ok = results.filter((r) => r.ok).length;
  return (
    <div className="card">
      <div className="px-5 py-3 border-b border-rule flex items-center">
        <h2 className="font-medium mr-auto">Bulk send summary — {ok} sent, {results.length - ok} skipped</h2>
        <button className="btn-ghost !py-0.5" onClick={onClose}>Dismiss</button>
      </div>
      <ul className="divide-y divide-rule/60 text-sm">
        {results.map((r) => (
          <li key={r.certificate_id} className="px-5 py-2 flex items-center gap-2">
            <span className={r.ok ? "text-ledger" : "text-red-700"}>{r.ok ? "Sent" : "Skipped"}</span>
            <span className="font-mono text-ink/50">{r.certificate_no}</span>
            <span>{r.supplier_name}</span>
            {r.error && <span className="text-ink/50 text-xs ml-auto">{r.error}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Main screen: search/filter + pending groupings + generated list     */
/* ------------------------------------------------------------------ */
export default function CertificateIssue() {
  const { companyId } = useCompany();
  const [filters, setFilters] = useState({ tin: "", bin: "", supplier_name: "", date_from: "", date_to: "" });
  const [page, setPage] = useState(1);
  const [results, setResults] = useState({ items: [], total: 0 });
  const [pending, setPending] = useState([]);
  const [checked, setChecked] = useState({});
  const [previewId, setPreviewId] = useState(null);
  const [notice, setNotice] = useState(null);
  const [showVendorModal, setShowVendorModal] = useState(false);
  const [bulkAnomalies, setBulkAnomalies] = useState(null);
  const [bulkChecking, setBulkChecking] = useState(false);
  const [bulkSendResults, setBulkSendResults] = useState(null);
  const [bulkSending, setBulkSending] = useState(false);

  const search = (nextPage = page) => {
    if (!companyId) return Promise.resolve();
    return api.searchCertificates({ ...filters, company_id: companyId, page: nextPage, page_size: 20 }).then(setResults);
  };
  const loadPending = () => {
    if (!companyId) return Promise.resolve();
    return api.pendingGroupings(companyId, filters).then(setPending);
  };

  useEffect(() => { search(); }, [page, companyId]);
  useEffect(() => { loadPending(); }, [companyId]);

  function applyFilters() {
    setPage(1);
    search(1);
    loadPending();
    setBulkAnomalies(null);
    setBulkSendResults(null);
  }

  async function generateOne(g) {
    try {
      const c = await api.generate(companyId, g.tin, g.period);
      setNotice(`Generated ${c.certificate_no} for ${g.supplier_name}`);
      await Promise.all([search(), loadPending()]);
      setPreviewId(c.id);
    } catch (e) { setNotice(e.message); }
  }

  async function generateBulk() {
    const items = pending.filter((g) => checked[`${g.tin}|${g.period}`])
      .map((g) => ({ company_id: companyId, tin: g.tin, period: g.period }));
    if (!items.length) return;
    const res = await api.generateBulk(items);
    const ok = res.filter((r) => r.ok).length;
    setNotice(`Bulk generation: ${ok} succeeded, ${res.length - ok} failed.`);
    setChecked({});
    await Promise.all([search(), loadPending()]);
  }

  async function runBulkCheck() {
    setBulkChecking(true);
    setBulkSendResults(null);
    try {
      const res = await api.anomaliesBulk({ ...filters, company_id: companyId });
      setBulkAnomalies(res);
    } catch (e) {
      setNotice(e.message);
    } finally {
      setBulkChecking(false);
    }
  }

  async function runBulkSend() {
    setBulkSending(true);
    setBulkAnomalies(null);
    try {
      const res = await api.dispatchBulk({ ...filters, company_id: companyId, channel: "email" });
      setBulkSendResults(res);
      await search();
    } catch (e) {
      setNotice(e.message);
    } finally {
      setBulkSending(false);
    }
  }

  function exportFiltered() {
    window.open(api.exportUrl({ ...filters, company_id: companyId }), "_blank", "noopener");
  }

  function exportOne(certId) {
    window.open(api.exportUrl({ company_id: companyId, certificate_id: certId }), "_blank", "noopener");
  }

  const set = (k) => (e) => setFilters({ ...filters, [k]: e.target.value });
  const submitOnEnter = (e) => {
    if (e.key === "Enter") applyFilters();
  };

  if (!companyId) {
    return (
      <div className="space-y-6">
        <h1 className="text-xl font-semibold">Certificate Issue</h1>
        <p className="text-sm text-ink/60">Select a company from the header above to continue.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-semibold mr-auto">Certificate Issue</h1>
        <button className="btn-primary" onClick={() => setShowVendorModal(true)}>+ Add Vendor</button>
      </div>
      {notice && <p className="text-sm text-ledger">{notice}</p>}

      {/* Search & filter - TIN, BIN, Supplier Name, Date range (combinable) */}
      <div className="card p-4 grid grid-cols-6 gap-3 items-end">
        <div><span className="label">TIN</span><input className="input font-mono" value={filters.tin} onChange={set("tin")} onKeyDown={submitOnEnter} /></div>
        <div><span className="label">BIN</span><input className="input font-mono" value={filters.bin} onChange={set("bin")} onKeyDown={submitOnEnter} /></div>
        <div><span className="label">Supplier name</span><input className="input" value={filters.supplier_name} onChange={set("supplier_name")} onKeyDown={submitOnEnter} /></div>
        <div><span className="label">Date from</span><input type="date" className="input" value={filters.date_from} onChange={set("date_from")} /></div>
        <div><span className="label">Date to</span><input type="date" className="input" value={filters.date_to} onChange={set("date_to")} /></div>
        <button className="btn-primary" onClick={applyFilters}>Search</button>
      </div>

      {/* Pending groupings with per-row + bulk generation */}
      <div className="card">
        <div className="px-5 py-3 border-b border-rule flex items-center">
          <h2 className="font-medium mr-auto">Pending <span className="text-ink/40 font-normal">({pending.length})</span></h2>
          <button className="btn-primary" onClick={generateBulk}>Generate selected</button>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-ink/50 border-b border-rule">
              <th className="px-5 py-2 w-8"></th><th className="py-2">Supplier</th>
              <th>TIN</th><th>Period</th><th>Payment dates</th><th className="text-right">Rows</th>
              <th className="text-right">Payment</th><th className="text-right pr-3">TDS</th><th></th>
            </tr>
          </thead>
          <tbody>
            {pending.slice(0, 15).map((g) => {
              const key = `${g.tin}|${g.period}`;
              return (
                <tr key={key} className="border-b border-rule/60">
                  <td className="px-5"><input type="checkbox" checked={!!checked[key]}
                    onChange={(e) => setChecked({ ...checked, [key]: e.target.checked })} /></td>
                  <td className="py-1.5">{g.supplier_name}</td>
                  <td className="font-mono">{g.tin}</td>
                  <td>{g.period}</td>
                  <td>{g.payment_from || ""}{g.payment_to && g.payment_to !== g.payment_from ? ` to ${g.payment_to}` : ""}</td>
                  <td className="text-right">{g.row_count}</td>
                  <td className="text-right font-mono">{fmt(g.total_payment)}</td>
                  <td className="text-right font-mono pr-3">{fmt(g.total_tax_deducted)}</td>
                  <td className="pr-4 text-right">
                    <button className="btn-ghost !py-0.5" onClick={() => generateOne(g)}>Generate Certificate</button>
                  </td>
                </tr>
              );
            })}
            {pending.length === 0 && (
              <tr><td colSpan={9} className="p-5 text-ink/50">No pending groupings match these filters.</td></tr>
            )}
          </tbody>
        </table>
        {pending.length > 15 && (
          <p className="px-5 py-2 text-xs text-ink/50">{pending.length - 15} more. Narrow with the search above.</p>
        )}
      </div>

      {/* Generated certificates */}
      <div className="card">
        <div className="px-5 py-3 border-b border-rule flex items-center gap-2">
          <h2 className="font-medium mr-auto">Generated certificates <span className="text-ink/40 font-normal">({results.total})</span></h2>
          <button className="btn-ghost !py-0.5" onClick={exportFiltered}>Export filtered</button>
          <button className="btn-ghost !py-0.5" onClick={runBulkCheck} disabled={bulkChecking}>
            {bulkChecking ? "Checking..." : "Check all"}
          </button>
          <button className="btn-primary !py-0.5" onClick={runBulkSend} disabled={bulkSending}>
            {bulkSending ? "Sending..." : "Send all"}
          </button>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-ink/50 border-b border-rule">
              <th className="px-5 py-2">Certificate No.</th><th>Supplier</th><th>TIN</th>
              <th>Period</th><th>Issued</th><th className="text-right">TDS</th><th>Status</th><th></th>
            </tr>
          </thead>
          <tbody>
            {results.items.map((c) => (
              <tr key={c.id} className="border-b border-rule/60">
                <td className="px-5 py-1.5 font-mono">{c.certificate_no}</td>
                <td>{c.supplier.name}</td>
                <td className="font-mono">{c.tin}</td>
                <td>{c.period}</td>
                <td>{c.issue_date}</td>
                <td className="text-right font-mono">{fmt(c.total_tax_deducted)}</td>
                <td><span className={`text-xs px-1.5 py-0.5 rounded ${c.status === "sent" ? "bg-ledger/10 text-ledger" : "bg-paper"}`}>{c.status}</span></td>
                <td className="pr-4 text-right whitespace-nowrap">
                  <button className="btn-ghost !py-0.5" onClick={() => exportOne(c.id)}>Export</button>
                  <button className="btn-ghost !py-0.5" onClick={() => setPreviewId(c.id)}>Preview / send</button>
                </td>
              </tr>
            ))}
            {results.items.length === 0 && (
              <tr><td colSpan={8} className="p-5 text-ink/50">No certificates match these filters.</td></tr>
            )}
          </tbody>
        </table>
        <div className="px-5 py-2 flex gap-2 items-center text-sm">
          <button className="btn-ghost" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
          <span>Page {page} of {Math.max(1, Math.ceil(results.total / 20))}</span>
          <button className="btn-ghost" disabled={page * 20 >= results.total} onClick={() => setPage(page + 1)}>Next</button>
        </div>
      </div>

      {bulkAnomalies && <BulkAnomalyPanel results={bulkAnomalies} onClose={() => setBulkAnomalies(null)} />}
      {bulkSendResults && <BulkSendPanel results={bulkSendResults} onClose={() => setBulkSendResults(null)} />}

      {previewId && <Preview certId={previewId} onClose={() => { setPreviewId(null); search(); }} />}
      {showVendorModal && (
        <VendorOnboardingModal
          companyId={companyId}
          onClose={() => setShowVendorModal(false)}
          onCreated={(supplier) => {
            setShowVendorModal(false);
            setNotice(`Vendor ${supplier.name} saved (TIN ${supplier.tin}).`);
          }}
        />
      )}
    </div>
  );
}
