import { useEffect, useState } from "react";
import { api } from "../api/client.js";
import { useCompany } from "../context/CompanyContext.jsx";
import { Toast, useToast } from "../components/ui.jsx";

// Preset SMTP hosts for the organization's preferred email providers.
const SMTP_PRESETS = {
  "Microsoft 365 / Outlook": { smtp_host: "smtp.office365.com", smtp_port: 587, smtp_use_tls: true },
  "Google Workspace": { smtp_host: "smtp.gmail.com", smtp_port: 587, smtp_use_tls: true },
  "Zimbra": { smtp_host: "", smtp_port: 587, smtp_use_tls: true },
  "Other (custom SMTP)": {},
};

function Field({ label, children }) {
  return (
    <div>
      <span className="label">{label}</span>
      {children}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Companies: create new + pick which one the sections below edit.     */
/* The header switcher and this list share the same active company.   */
/* ------------------------------------------------------------------ */
function CompaniesSection({ companies, companyId, setCompanyId, refreshCompanies, notify }) {
  const [showAdd, setShowAdd] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  async function addCompany() {
    if (!name.trim()) return;
    setBusy(true);
    try {
      const company = await api.createCompany({ name: name.trim() });
      await refreshCompanies();
      setCompanyId(company.id);
      setName("");
      setShowAdd(false);
      notify(`Company "${company.name}" created.`);
    } catch (err) {
      notify(`Could not create company: ${err.message}`, "err");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card p-5 space-y-3">
      <div className="flex items-center gap-3">
        <h2 className="font-medium mr-auto">Companies</h2>
        <button className="btn-ghost" onClick={() => setShowAdd((v) => !v)}>
          {showAdd ? "Cancel" : "+ Add company"}
        </button>
      </div>
      <p className="text-sm text-ink/60">
        Every section below (identity, seal, signatures, letterhead, numbering) applies to the
        company selected here — the same picker shown in the page header.
      </p>
      <div className="flex flex-wrap gap-2">
        {companies.map((c) => (
          <button
            key={c.id}
            className={`px-3 py-1.5 rounded border text-sm ${
              c.id === companyId ? "bg-ink text-paper border-ink" : "border-rule hover:bg-paper"
            }`}
            onClick={() => setCompanyId(c.id)}
          >
            {c.name}{c.is_default ? " (default)" : ""}
          </button>
        ))}
      </div>
      {showAdd && (
        <div className="flex gap-2 items-end">
          <Field label="New company name">
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <button className="btn-primary" onClick={addCompany} disabled={busy || !name.trim()}>
            {busy ? "Creating..." : "Create"}
          </button>
        </div>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* Named signatures: multiple per company. Every one flagged enabled     */
/* renders on every certificate for that company, evenly laid out above */
/* the footer — there's no more "pick one at generation time."          */
/* ------------------------------------------------------------------ */
function SignaturesSection({ companyId, notify }) {
  const [signatures, setSignatures] = useState([]);
  const [newName, setNewName] = useState("");
  const [newDesignation, setNewDesignation] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [editForm, setEditForm] = useState({ name: "", designation: "", email: "" });

  const load = () => api.listSignatures(companyId).then(setSignatures);
  useEffect(() => { if (companyId) load(); }, [companyId]);

  async function addSignature(e) {
    const file = e.target.files?.[0];
    if (!file || !newName.trim()) {
      notify("Enter a signatory name before choosing an image.", "err");
      e.target.value = "";
      return;
    }
    setBusy(true);
    try {
      await api.createSignature(companyId, newName.trim(), newDesignation.trim() || null,
        newEmail.trim() || null, file);
      setNewName("");
      setNewDesignation("");
      setNewEmail("");
      await load();
      notify("Signature added.");
    } catch (err) {
      notify(`Could not add signature: ${err.message}`, "err");
    } finally {
      setBusy(false);
      e.target.value = "";
    }
  }

  async function toggleEnabled(sig) {
    try {
      await api.updateSignature(companyId, sig.id, { enabled: !sig.enabled });
      await load();
      notify(`"${sig.name}" ${sig.enabled ? "disabled" : "enabled"}.`);
    } catch (err) {
      notify(`Could not update signature: ${err.message}`, "err");
    }
  }

  function startEdit(sig) {
    setEditingId(sig.id);
    setEditForm({ name: sig.name, designation: sig.designation || "", email: sig.email || "" });
  }

  async function saveEdit(sig) {
    if (!editForm.name.trim()) {
      notify("Signatory name cannot be empty.", "err");
      return;
    }
    try {
      await api.updateSignature(companyId, sig.id, {
        name: editForm.name.trim(),
        designation: editForm.designation.trim() || null,
        email: editForm.email.trim() || null,
      });
      setEditingId(null);
      await load();
      notify("Signature updated.");
    } catch (err) {
      notify(`Could not update signature: ${err.message}`, "err");
    }
  }

  async function remove(sig) {
    if (!window.confirm(`Delete the signature "${sig.name}"? This cannot be undone.`)) return;
    try {
      await api.deleteSignature(companyId, sig.id);
      await load();
      notify(`Signature "${sig.name}" deleted.`);
    } catch (err) {
      notify(`Could not delete signature: ${err.message}`, "err");
    }
  }

  return (
    <section className="card p-5 space-y-3">
      <h2 className="font-medium">Signatures</h2>
      <p className="text-sm text-ink/60">
        Every signature marked Enabled renders together, evenly spaced, on every certificate
        generated for this company.
      </p>
      {signatures.length > 0 && (
        <ul className="divide-y divide-rule/70">
          {signatures.map((s) => (
            <li key={s.id} className="flex flex-wrap items-center gap-3 py-2.5">
              <img
                src={api.signatureImageUrl(companyId, s.id)}
                alt={`${s.name} signature`}
                className="h-10 w-16 shrink-0 border border-rule rounded bg-white object-contain px-1"
              />
              {editingId === s.id ? (
                <div className="flex flex-1 min-w-[22rem] flex-wrap gap-2">
                  <input
                    className="input flex-1 min-w-[8rem]"
                    aria-label="Signatory name"
                    value={editForm.name}
                    onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                  />
                  <input
                    className="input flex-1 min-w-[8rem]"
                    aria-label="Designation"
                    placeholder="Designation"
                    value={editForm.designation}
                    onChange={(e) => setEditForm({ ...editForm, designation: e.target.value })}
                  />
                  <input
                    className="input flex-1 min-w-[8rem]"
                    aria-label="Email"
                    type="email"
                    placeholder="Email"
                    value={editForm.email}
                    onChange={(e) => setEditForm({ ...editForm, email: e.target.value })}
                  />
                </div>
              ) : (
                <div className="flex-1 min-w-[10rem]">
                  <p className="text-sm font-medium">{s.name}</p>
                  {s.designation && <p className="text-xs text-ink/50">{s.designation}</p>}
                  {s.email && <p className="text-xs text-ink/40">{s.email}</p>}
                </div>
              )}
              <label className="flex shrink-0 items-center gap-1.5 text-xs text-ink/60">
                <input type="checkbox" checked={s.enabled} onChange={() => toggleEnabled(s)} />
                Enabled
              </label>
              {editingId === s.id ? (
                <>
                  <button className="btn-ghost btn-sm" onClick={() => saveEdit(s)}>Save</button>
                  <button className="btn-ghost btn-sm" onClick={() => setEditingId(null)}>Cancel</button>
                </>
              ) : (
                <button className="btn-ghost btn-sm" onClick={() => startEdit(s)}>Edit</button>
              )}
              <button
                className="btn-ghost btn-sm border-red-200 text-red-700 hover:border-red-700 hover:text-red-800"
                onClick={() => remove(s)}
              >
                Delete
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap items-end gap-2 pt-1">
        <Field label="Signatory name">
          <input className="input" placeholder="e.g. Md. Rahim Uddin" value={newName}
            onChange={(e) => setNewName(e.target.value)} />
        </Field>
        <Field label="Designation (optional)">
          <input className="input" placeholder="e.g. Head of Tax & VAT" value={newDesignation}
            onChange={(e) => setNewDesignation(e.target.value)} />
        </Field>
        <Field label="Email (optional)">
          <input className="input" type="email" placeholder="e.g. rahim@company.com" value={newEmail}
            onChange={(e) => setNewEmail(e.target.value)} />
        </Field>
        <label className={`btn-ghost cursor-pointer inline-block ${busy ? "opacity-60 pointer-events-none" : ""}`}>
          {busy ? "Uploading..." : "Add signature image"}
          <input type="file" accept="image/png,image/jpeg" className="hidden" onChange={addSignature} disabled={busy} />
        </label>
      </div>
    </section>
  );
}

export default function Settings() {
  const { companies, companyId, setCompanyId, refreshCompanies } = useCompany();
  const [org, setOrg] = useState(null);
  const [num, setNum] = useState(null);
  const [companyForm, setCompanyForm] = useState(null);
  const [toast, notify, dismissToast] = useToast();
  // Uploaded images are served from the database with no filename/path to
  // cache-bust against — bump this on every upload so the browser fetches
  // the fresh bytes instead of showing a stale cached image at the same URL.
  const [imgVersion, setImgVersion] = useState(0);
  const [resetConfirm, setResetConfirm] = useState("");
  const [resetBusy, setResetBusy] = useState(false);

  useEffect(() => {
    api.getOrg().then(setOrg);
  }, []);

  useEffect(() => {
    if (!companyId) { setNum(null); setCompanyForm(null); return; }
    api.getNumbering(companyId).then(setNum);
    const company = companies.find((c) => c.id === companyId);
    if (company) setCompanyForm({ ...company });
  }, [companyId, companies]);

  if (!org) return <p className="text-ink/50">Loading…</p>;

  if (companies.length === 0) {
    return (
      <div className="space-y-6 max-w-3xl">
        <h1 className="text-xl font-semibold">Settings</h1>
        <CompaniesSection
          companies={companies} companyId={companyId} setCompanyId={setCompanyId}
          refreshCompanies={refreshCompanies} notify={notify}
        />
        <p className="text-sm text-ink/60">Create a company above to configure its identity, seal, signatures, letterhead, and numbering.</p>
        <Toast toast={toast} onDismiss={dismissToast} />
      </div>
    );
  }

  if (!companyId || !num || !companyForm) {
    return <p className="text-ink/50">Loading…</p>;
  }

  const setO = (k) => (e) =>
    setOrg({ ...org, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const setN = (k) => (e) => setNum({ ...num, [k]: e.target.value });
  const setC = (k) => (e) => setCompanyForm({ ...companyForm, [k]: e.target.value });

  async function saveOrg() {
    const body = { ...org };
    // booleans standing in for stored secrets must not be sent back
    for (const k of ["smtp_password", "wa_token", "wa_twilio_auth"])
      if (typeof body[k] === "boolean") delete body[k];
    delete body.id;
    delete body.has_logo; delete body.has_seal_signature;
    delete body.has_signature; delete body.has_seal;
    try {
      await api.updateOrg(body);
      notify("Settings saved.");
    } catch (err) {
      notify(`Could not save settings: ${err.message}`, "err");
    }
  }

  async function testEmail() {
    try {
      await saveOrg();
      const res = await api.testEmail();
      notify(`Test email sent to ${res.recipient}.`);
    } catch (err) {
      notify(`Email test failed: ${err.message}`, "err");
    }
  }

  async function saveCompany(message = "Company details saved.") {
    const { id, has_seal, has_letterhead_header, has_letterhead_footer, ...body } = companyForm;
    try {
      await api.updateCompany(companyId, body);
      await refreshCompanies();
      notify(message);
    } catch (err) {
      notify(`Could not save: ${err.message}`, "err");
    }
  }

  async function saveNumbering() {
    try {
      await api.updateNumbering(companyId, {
        ...num,
        pad_width: Number(num.pad_width),
        start_number: Number(num.start_number),
      });
      notify("Numbering configuration saved.");
    } catch (err) {
      notify(`Could not save numbering: ${err.message}`, "err");
    }
  }

  async function resetDatabase() {
    if (resetConfirm !== "RESET") return;
    if (!window.confirm("Reset the database and remove all module data?")) return;
    setResetBusy(true);
    try {
      await api.resetDatabase(resetConfirm);
      const freshCompanies = await refreshCompanies();
      if (!freshCompanies.length) setCompanyId(null);
      setOrg(await api.getOrg());
      setResetConfirm("");
      notify("Database reset complete. You can start again.");
    } catch (err) {
      notify(`Database reset failed: ${err.message}`, "err");
    } finally {
      setResetBusy(false);
    }
  }

  const uploadCompanyImage = (fn, label, hasField) => async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    try {
      await fn(companyId, f);
      setCompanyForm((current) => ({ ...current, [hasField]: true }));
      setImgVersion((v) => v + 1);
      await refreshCompanies();
      notify(`${label} uploaded.`);
    } catch (err) {
      notify(`Could not upload ${label.toLowerCase()}: ${err.message}`, "err");
    }
  };

  // Mirrors backend numbering.render_number_format's token substitution
  // exactly, so the preview here always matches the generated number.
  function formatNumberPreview() {
    const [fyStart, fyEnd] = "2025-26".split("-");
    const fy = num.fiscal_year_format === "YYYY" ? fyStart
      : num.fiscal_year_format === "YY-YY" ? `${fyStart.slice(-2)}-${fyEnd}`
      : `${fyStart}-${fyEnd}`;
    const autoNumber = String(num.start_number).padStart(Number(num.pad_width), "0");
    const template = num.number_format || "{CompanyName}{sep}{FiscalYear}{sep}{AutoNumber}";
    return template
      .split("{CompanyName}").join(num.company_token)
      .split("{FiscalYear}").join(fy)
      .split("{AutoNumber}").join(autoNumber)
      .split("{sep}").join(num.separator);
  }
  const example = formatNumberPreview();

  return (
    <div className="space-y-6 max-w-3xl">
      <h1 className="text-xl font-semibold">Settings</h1>

      <CompaniesSection
        companies={companies} companyId={companyId} setCompanyId={setCompanyId}
        refreshCompanies={refreshCompanies} notify={notify}
      />

      {/* Organizational information (per company) */}
      <section className="card p-5 space-y-3">
        <h2 className="font-medium">Organizational information</h2>
        <Field label="Company name"><input className="input" value={companyForm.name || ""} onChange={setC("name")} /></Field>
        <Field label="Address"><textarea className="input" rows={2} value={companyForm.address || ""} onChange={setC("address")} /></Field>
        <button className="btn-primary" onClick={() => saveCompany()}>Save company details</button>
      </section>

      {/* Seal + designated officer (per company) */}
      <section className="card p-5 space-y-3">
        <h2 className="font-medium">Seal &amp; designated officer</h2>
        <p className="text-sm text-ink/60">
          The seal renders below the issue date in the footer's Seal block, separate from the
          signatures configured below.
        </p>
        <Field label="Seal image (PNG with transparency)">
          <div className="flex items-center gap-3">
            {companyForm.has_seal && (
              <img src={`${api.companySealUrl(companyId)}?v=${imgVersion}`} alt="Seal preview" className="h-10 border border-rule rounded bg-white object-contain" />
            )}
            <label className="btn-ghost cursor-pointer inline-block">
              {companyForm.has_seal ? "Replace seal" : "Upload seal"}
              <input type="file" accept="image/png,image/jpeg" className="hidden" onChange={uploadCompanyImage(api.uploadCompanySeal, "Seal", "has_seal")} />
            </label>
          </div>
        </Field>
        <div className="grid grid-cols-3 gap-3">
          <Field label="Officer name"><input className="input" value={companyForm.officer_name || ""} onChange={setC("officer_name")} /></Field>
          <Field label="Designation"><input className="input" value={companyForm.officer_designation || ""} onChange={setC("officer_designation")} /></Field>
          <Field label="Officer email"><input className="input" value={companyForm.officer_email || ""} onChange={setC("officer_email")} /></Field>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Default bank name (Section 07)"><input className="input" value={companyForm.default_bank_name || ""} onChange={setC("default_bank_name")} /></Field>
          <Field label="Default payment description (Section 06)"><input className="input" value={companyForm.default_description || ""} onChange={setC("default_description")} /></Field>
        </div>
        <button className="btn-primary" onClick={() => saveCompany("Seal & officer details saved.")}>Save seal &amp; officer details</button>
      </section>

      <SignaturesSection companyId={companyId} notify={notify} />

      {/* Company letterhead (item 12) */}
      <section className="card p-5 space-y-3">
        <h2 className="font-medium">Company letterhead</h2>
        <p className="text-sm text-ink/60">
          Header and footer images of this company's letterhead pad, uploaded and replaced
          separately. They render at the top and bottom of every certificate generated for
          this company.
        </p>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Letterhead header">
            <div className="space-y-2">
              {companyForm.has_letterhead_header && (
                <img src={`${api.letterheadHeaderUrl(companyId)}?v=${imgVersion}`} alt="Letterhead header preview" className="w-full max-h-24 border border-rule rounded bg-white object-contain" />
              )}
              <label className="btn-ghost cursor-pointer inline-block">
                {companyForm.has_letterhead_header ? "Replace header" : "Upload header"}
                <input type="file" accept="image/png,image/jpeg" className="hidden" onChange={uploadCompanyImage(api.uploadLetterheadHeader, "Letterhead header", "has_letterhead_header")} />
              </label>
            </div>
          </Field>
          <Field label="Letterhead footer">
            <div className="space-y-2">
              {companyForm.has_letterhead_footer && (
                <img src={`${api.letterheadFooterUrl(companyId)}?v=${imgVersion}`} alt="Letterhead footer preview" className="w-full max-h-24 border border-rule rounded bg-white object-contain" />
              )}
              <label className="btn-ghost cursor-pointer inline-block">
                {companyForm.has_letterhead_footer ? "Replace footer" : "Upload footer"}
                <input type="file" accept="image/png,image/jpeg" className="hidden" onChange={uploadCompanyImage(api.uploadLetterheadFooter, "Letterhead footer", "has_letterhead_footer")} />
              </label>
            </div>
          </Field>
        </div>
      </section>

      {/* Certificate numbering (per company) */}
      <section className="card p-5 space-y-3">
        <h2 className="font-medium">Certificate numbering</h2>
        <div className="grid grid-cols-3 gap-3">
          <Field label="Company token"><input className="input" value={num.company_token} onChange={setN("company_token")} /></Field>
          <Field label="Fiscal year format">
            <select className="input" value={num.fiscal_year_format} onChange={setN("fiscal_year_format")}>
              <option value="YYYY-YY">2025-26</option>
              <option value="YYYY">2025</option>
              <option value="YY-YY">25-26</option>
            </select>
          </Field>
          <Field label="Separator"><input className="input" value={num.separator} onChange={setN("separator")} /></Field>
          <Field label="Number width (zero padding)"><input type="number" min="1" max="10" className="input" value={num.pad_width} onChange={setN("pad_width")} /></Field>
          <Field label="Starting number"><input type="number" min="1" className="input" value={num.start_number} onChange={setN("start_number")} /></Field>
          <Field label="Reset policy">
            <select className="input" value={num.reset_policy} onChange={setN("reset_policy")}>
              <option value="per_fiscal_year">Restart each fiscal year</option>
              <option value="continuous">Continuous</option>
            </select>
          </Field>
        </div>
        <Field label="Number format (tokens: {CompanyName}, {FiscalYear}, {AutoNumber}, {sep})">
          <input className="input font-mono" value={num.number_format || ""} onChange={setN("number_format")} />
        </Field>
        <p className="text-sm">Next number will look like: <span className="font-mono">{example}</span></p>
        <button className="btn-primary" onClick={saveNumbering}>Save numbering</button>
      </section>

      {/* SMTP (global) */}
      <section className="card p-5 space-y-3">
        <div className="flex items-center gap-3">
          <h2 className="font-medium mr-auto">Email (SMTP)</h2>
          <button className="btn-ghost" onClick={testEmail}>Send test email</button>
        </div>
        <Field label="Provider preset">
          <select className="input" onChange={(e) => setOrg({ ...org, ...SMTP_PRESETS[e.target.value] })}>
            {Object.keys(SMTP_PRESETS).map((k) => <option key={k}>{k}</option>)}
          </select>
        </Field>
        <div className="grid grid-cols-3 gap-3">
          <Field label="SMTP host"><input className="input" value={org.smtp_host || ""} onChange={setO("smtp_host")} /></Field>
          <Field label="Port"><input type="number" className="input" value={org.smtp_port || 587} onChange={setO("smtp_port")} /></Field>
          <Field label="From address"><input className="input" value={org.smtp_from || ""} onChange={setO("smtp_from")} /></Field>
          <Field label="Username"><input className="input" value={org.smtp_user || ""} onChange={setO("smtp_user")} /></Field>
          <Field label={org.smtp_password === true ? "Password (stored — enter to replace)" : "Password"}>
            <input type="password" className="input" onChange={setO("smtp_password")} />
          </Field>
          <label className="flex items-center gap-2 text-sm mt-5">
            <input type="checkbox" checked={!!org.smtp_use_tls} onChange={setO("smtp_use_tls")} /> Use STARTTLS
          </label>
        </div>
      </section>

      {/* WhatsApp (global) */}
      <section className="card p-5 space-y-3">
        <h2 className="font-medium">WhatsApp API</h2>
        <Field label="Provider">
          <select className="input" value={org.wa_provider || "cloud"} onChange={setO("wa_provider")}>
            <option value="cloud">WhatsApp Business Cloud API</option>
            <option value="twilio">Twilio</option>
          </select>
        </Field>
        {org.wa_provider === "twilio" ? (
          <div className="grid grid-cols-3 gap-3">
            <Field label="Account SID"><input className="input" value={org.wa_twilio_sid || ""} onChange={setO("wa_twilio_sid")} /></Field>
            <Field label={org.wa_twilio_auth === true ? "Auth token (stored — enter to replace)" : "Auth token"}>
              <input type="password" className="input" onChange={setO("wa_twilio_auth")} />
            </Field>
            <Field label="From number"><input className="input" value={org.wa_twilio_from || ""} onChange={setO("wa_twilio_from")} /></Field>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-3">
            <Field label={org.wa_token === true ? "Access token (stored — enter to replace)" : "Access token"}>
              <input type="password" className="input" onChange={setO("wa_token")} />
            </Field>
            <Field label="Phone number ID"><input className="input" value={org.wa_phone_number_id || ""} onChange={setO("wa_phone_number_id")} /></Field>
          </div>
        )}
        <Field label="Dispatch mode">
          <select className="input !w-auto" value={org.dispatch_mode} onChange={setO("dispatch_mode")}>
            <option value="online">Online — send immediately</option>
            <option value="offline">Offline — queue, send when connectivity returns</option>
          </select>
        </Field>
      </section>

      <button className="btn-primary" onClick={saveOrg}>Save email/WhatsApp settings</button>

      <section className="card border-red-200 bg-red-50/40 p-5 space-y-3">
        <h2 className="font-medium text-red-800">Database reset</h2>
        <p className="text-sm text-red-800">
          This removes imports, suppliers, certificates, dispatch jobs, rates, companies,
          settings, and numbering data.
        </p>
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Type RESET to confirm">
            <input
              className="input max-w-48 border-red-200 focus:border-red-700 focus:ring-red-700/10"
              value={resetConfirm}
              onChange={(e) => setResetConfirm(e.target.value)}
            />
          </Field>
          <button
            className="btn border-red-700 bg-red-700 text-white shadow-sm hover:bg-red-800"
            onClick={resetDatabase}
            disabled={resetBusy || resetConfirm !== "RESET"}
          >
            {resetBusy ? "Resetting..." : "Reset database"}
          </button>
        </div>
      </section>

      <Toast toast={toast} onDismiss={dismissToast} />
    </div>
  );
}
