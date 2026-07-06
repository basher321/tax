import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client.js";

const fmt = (n) => (n == null ? "" : Number(n).toLocaleString());

const inDateRange = (from, to, dateFrom, dateTo) => {
  if (!dateFrom && !dateTo) return true;
  const start = from || to;
  const end = to || from;
  if (!start && !end) return false;
  return (!dateTo || start <= dateTo) && (!dateFrom || end >= dateFrom);
};

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
      ([c, a, wa]) => { setCert(c); setRemarks(c.remarks || ""); setAnomalies(a); setWaLinks(wa); }
    );
  useEffect(() => { load(); }, [certId]);

  async function saveRemarks() {
    const c = await api.updateRemarks(certId, remarks);
    setCert(c);
    showNotice("Remarks saved - PDF re-rendered.");
  }

  async function setTinStatus(has12DigitTin) {
    const c = await api.updateTinStatus(certId, has12DigitTin);
    setCert(c);
    showNotice("TIN status saved - PDF re-rendered.");
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

        {/* Fixed certificate layout - mirrors certificate_format.jpeg.
            Everything is read-only; ONLY Remarks below is editable. */}
        <div className="p-6 text-sm">
          <h2 className="text-center font-semibold text-base">Certificate of Deduction of Tax</h2>
          <p className="text-center text-xs">[Section 145 of the Income Tax Act 2023]</p>

          <div className="flex justify-between border border-ink px-2 py-1 mt-3 font-medium">
            <span>No. {cert.certificate_no}</span>
            <span>{cert.issue_date}</span>
          </div>

          <table className="w-full border border-ink mt-2 [&_td]:border [&_td]:border-ink [&_td]:px-2 [&_td]:py-1">
            <tbody>
              <tr><td className="w-6">1</td><td className="font-medium w-64">Name of Payee:</td><td colSpan={2}>{cert.supplier.name}</td></tr>
              <tr><td>2</td><td className="font-medium">Address of Payee:</td><td colSpan={2}>{cert.supplier.address || ""}</td></tr>
              <tr><td>3</td><td>Does the person have a Twelve-digit TIN?</td>
                <td>
                  <label className="cursor-pointer">
                    <input type="radio" name="has12DigitTin" className="mr-1"
                      checked={cert.has_12_digit_tin === true}
                      onChange={() => setTinStatus(true)} />
                    Yes
                  </label>
                </td>
                <td>
                  <label className="cursor-pointer">
                    <input type="radio" name="has12DigitTin" className="mr-1"
                      checked={cert.has_12_digit_tin === false}
                      onChange={() => setTinStatus(false)} />
                    No
                  </label>
                </td>
              </tr>
              <tr><td>4</td><td>Twelve-digit TIN (if answer of 03 is Yes)</td><td className="font-mono" colSpan={2}>E-TIN&nbsp;&nbsp;{cert.tin}</td></tr>
              <tr><td>5</td><td>Period for which payment is made From (date) to (date)</td>
                <td colSpan={2}>From {cert.period_from} to {cert.period_to}</td></tr>
            </tbody>
          </table>

          <p className="font-medium mt-4">06. Particulars of the making of payment and the deduction of tax</p>
          <table className="w-full border border-ink mt-1 [&_td]:border [&_th]:border [&_td]:border-ink [&_th]:border-ink [&_td]:px-2 [&_th]:px-2 [&_td]:py-0.5 [&_th]:py-1">
            <thead className="bg-paper text-xs">
              <tr><th>Sl</th><th>Date of Payment</th><th>Description of payment</th><th>Section</th>
                <th>Amount of payment</th><th>Amount of tax deducted</th><th>Remarks</th></tr>
            </thead>
            <tbody>
              {cert.lines.map((l, idx) => (
                <tr key={l.sl}>
                  <td className="text-center">{l.sl}</td>
                  <td className="text-center">{l.date_of_payment}</td>
                  <td>{l.description}</td>
                  <td className="text-center">{l.section}</td>
                  <td className="text-right font-mono">{fmt(l.amount_of_payment)}</td>
                  <td className="text-right font-mono">{fmt(l.amount_of_tax_deducted)}</td>
                  {idx === 0 && (
                    <td rowSpan={cert.lines.length} className="align-top">
                      {cert.remarks}
                    </td>
                  )}
                </tr>
              ))}
              <tr className="font-semibold">
                <td colSpan={4} className="text-center">Total</td>
                <td className="text-right font-mono">{fmt(cert.total_payment)}</td>
                <td className="text-right font-mono">{fmt(cert.total_tax_deducted)}</td>
                <td />
              </tr>
            </tbody>
          </table>

          <p className="font-medium mt-4">07. Payment of deducted tax to the credit of the Government</p>
          <table className="w-full border border-ink mt-1 [&_td]:border [&_th]:border [&_td]:border-ink [&_th]:border-ink [&_td]:px-2 [&_th]:px-2 [&_td]:py-0.5 [&_th]:py-1">
            <thead className="bg-paper text-xs">
              <tr><th>Sl</th><th>Challan Number</th><th>Challan date</th><th>Bank Name</th>
                <th>Total amount in the challan</th><th>Amount relating to this certificate</th><th>Remarks</th></tr>
            </thead>
            <tbody>
              {cert.challan_lines.map((l, idx) => (
                <tr key={l.sl}>
                  <td className="text-center">{l.sl}</td>
                  <td className="font-mono">{l.challan_number}</td>
                  <td className="text-center">{l.challan_date}</td>
                  <td>{l.bank_name}</td>
                  <td className="text-right font-mono">{fmt(l.total_challan_amount)}</td>
                  <td className="text-right font-mono">{fmt(l.amount_related)}</td>
                  {idx === 0 && (
                    <td rowSpan={cert.challan_lines.length} className="align-top">
                      {cert.remarks}
                    </td>
                  )}
                </tr>
              ))}
              <tr className="font-semibold">
                <td colSpan={5} className="text-center">Total</td>
                <td className="text-right font-mono">{fmt(cert.total_tax_deducted)}</td>
                <td />
              </tr>
            </tbody>
          </table>

          <p className="mt-3"><span className="font-medium">Amount In word:</span> {cert.amount_in_words}</p>
          <p className="text-ink/70">Certified that the information given above is correct and complete.</p>

          {/* the ONLY editable field */}
          <div className="mt-4">
            <label className="label">Remarks (the only editable field)</label>
            <div className="flex gap-2">
              <input className="input" value={remarks} onChange={(e) => setRemarks(e.target.value)} />
              <button className="btn-primary" onClick={saveRemarks}>Save remarks</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Main screen: search/filter + pending groupings + generated list     */
/* ------------------------------------------------------------------ */
export default function CertificateIssue() {
  const [filters, setFilters] = useState({ tin: "", bin: "", supplier_name: "", date_from: "", date_to: "" });
  const [page, setPage] = useState(1);
  const [results, setResults] = useState({ items: [], total: 0 });
  const [pending, setPending] = useState([]);
  const [checked, setChecked] = useState({});
  const [previewId, setPreviewId] = useState(null);
  const [notice, setNotice] = useState(null);

  const search = (nextPage = page) =>
    api.searchCertificates({ ...filters, page: nextPage, page_size: 20 }).then(setResults);
  const loadPending = () => api.pendingGroupings().then(setPending);

  useEffect(() => { search(); }, [page]);
  useEffect(() => { loadPending(); }, []);

  const filteredPending = useMemo(() => {
    const tin = filters.tin.trim().toLowerCase();
    const bin = filters.bin.trim().toLowerCase();
    const supplierName = filters.supplier_name.trim().toLowerCase();
    const dateFrom = filters.date_from;
    const dateTo = filters.date_to;

    return pending.filter((g) => {
      const matchesTin = !tin || String(g.tin || "").toLowerCase().includes(tin);
      const matchesBin = !bin || String(g.bin || "").toLowerCase().includes(bin);
      const matchesName =
        !supplierName ||
        String(g.supplier_name || "").toLowerCase().includes(supplierName);
      const matchesDate = inDateRange(g.payment_from, g.payment_to, dateFrom, dateTo);
      return matchesTin && matchesBin && matchesName && matchesDate;
    });
  }, [filters.bin, filters.date_from, filters.date_to, filters.supplier_name, filters.tin, pending]);

  function applyFilters() {
    setPage(1);
    search(1);
  }

  async function generateOne(g) {
    try {
      const c = await api.generate(g.tin, g.period);
      setNotice(`Generated ${c.certificate_no} for ${g.supplier_name}`);
      await Promise.all([search(), loadPending()]);
      setPreviewId(c.id);
    } catch (e) { setNotice(e.message); }
  }

  async function generateBulk() {
    const items = filteredPending.filter((g) => checked[`${g.tin}|${g.period}`])
      .map((g) => ({ tin: g.tin, period: g.period }));
    if (!items.length) return;
    const res = await api.generateBulk(items);
    const ok = res.filter((r) => r.ok).length;
    setNotice(`Bulk generation: ${ok} succeeded, ${res.length - ok} failed.`);
    setChecked({});
    await Promise.all([search(), loadPending()]);
  }

  const set = (k) => (e) => setFilters({ ...filters, [k]: e.target.value });
  const submitOnEnter = (e) => {
    if (e.key === "Enter") applyFilters();
  };

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Certificate Issue</h1>
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
          <h2 className="font-medium mr-auto">Pending <span className="text-ink/40 font-normal">({filteredPending.length})</span></h2>
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
            {filteredPending.slice(0, 15).map((g) => {
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
            {filteredPending.length === 0 && (
              <tr><td colSpan={9} className="p-5 text-ink/50">No pending groupings match these filters.</td></tr>
            )}
          </tbody>
        </table>
        {filteredPending.length > 15 && (
          <p className="px-5 py-2 text-xs text-ink/50">{filteredPending.length - 15} more. Narrow with the search above.</p>
        )}
      </div>

      {/* Generated certificates */}
      <div className="card">
        <div className="px-5 py-3 border-b border-rule">
          <h2 className="font-medium">Generated certificates <span className="text-ink/40 font-normal">({results.total})</span></h2>
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
                <td className="pr-4 text-right">
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

      {previewId && <Preview certId={previewId} onClose={() => { setPreviewId(null); search(); }} />}
    </div>
  );
}
