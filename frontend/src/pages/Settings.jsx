import { useEffect, useState } from "react";
import { api } from "../api/client.js";
import { useCompany } from "../context/CompanyContext.jsx";

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
      notify(`Could not create company: ${err.message}`);
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
/* Named signatures (item 8): multiple per company, one marked default */
/* ------------------------------------------------------------------ */
function SignaturesSection({ companyId, notify }) {
  const [signatures, setSignatures] = useState([]);
  const [newName, setNewName] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => api.listSignatures(companyId).then(setSignatures);
  useEffect(() => { if (companyId) load(); }, [companyId]);

  async function addSignature(e) {
    const file = e.target.files?.[0];
    if (!file || !newName.trim()) {
      notify("Enter a name for the signature before choosing a file.");
      e.target.value = "";
      return;
    }
    setBusy(true);
    try {
      await api.createSignature(companyId, newName.trim(), file);
      setNewName("");
      await load();
      notify("Signature uploaded.");
    } catch (err) {
      notify(`Could not upload signature: ${err.message}`);
    } finally {
      setBusy(false);
      e.target.value = "";
    }
  }

  async function makeDefault(sig) {
    await api.updateSignature(companyId, sig.id, { is_default: true });
    await load();
  }

  return (
    <section className="card p-5 space-y-3">
      <h2 className="font-medium">Signatures</h2>
      <p className="text-sm text-ink/60">
        Upload and name more than one signature (e.g. per signatory/designation). The signature
        picked when generating a certificate renders in the Signature and seal block.
      </p>
      {signatures.length > 0 && (
        <ul className="space-y-2">
          {signatures.map((s) => (
            <li key={s.id} className="flex items-center gap-3">
              <img src={api.signatureImageUrl(companyId, s.id)} alt={s.name}
                className="h-8 border border-rule rounded bg-white object-contain px-1" />
              <span className="text-sm">{s.name}</span>
              {s.is_default ? (
                <span className="text-xs text-ledger">Default</span>
              ) : (
                <button className="btn-ghost !py-0.5 text-xs" onClick={() => makeDefault(s)}>Set default</button>
              )}
            </li>
          ))}
        </ul>
      )}
      <div className="flex gap-2 items-end">
        <Field label="Signature name">
          <input className="input" placeholder="e.g. Head of Tax & VAT" value={newName}
            onChange={(e) => setNewName(e.target.value)} />
        </Field>
        <label className={`btn-ghost cursor-pointer inline-block ${busy ? "opacity-60 pointer-events-none" : ""}`}>
          {busy ? "Uploading..." : "Upload signature image"}
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
  const [notice, setNotice] = useState(null);
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
          refreshCompanies={refreshCompanies} notify={setNotice}
        />
        <p className="text-sm text-ink/60">Create a company above to configure its identity, seal, signatures, letterhead, and numbering.</p>
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
    delete body.id; delete body.logo_path; delete body.seal_signature_path;
    delete body.signature_path; delete body.seal_path;
    await api.updateOrg(body);
    setNotice("Settings saved.");
  }

  async function testEmail() {
    try {
      await saveOrg();
      const res = await api.testEmail();
      setNotice(`Test email sent to ${res.recipient}.`);
    } catch (err) {
      setNotice(`Email test failed: ${err.message}`);
    }
  }

  async function saveCompany() {
    const { id, logo_path, seal_path, letterhead_header_path, letterhead_footer_path, ...body } = companyForm;
    await api.updateCompany(companyId, body);
    await refreshCompanies();
    setNotice("Company details saved.");
  }

  async function saveNumbering() {
    await api.updateNumbering(companyId, {
      ...num,
      pad_width: Number(num.pad_width),
      start_number: Number(num.start_number),
    });
    setNotice("Numbering configuration saved.");
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
      setNotice("Database reset complete. You can start again.");
    } catch (err) {
      setNotice(`Database reset failed: ${err.message}`);
    } finally {
      setResetBusy(false);
    }
  }

  const uploadCompanyImage = (fn, label, pathField) => async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    const res = await fn(companyId, f);
    setCompanyForm((current) => ({ ...current, [pathField]: res.path }));
    await refreshCompanies();
    setNotice(`${label} uploaded.`);
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
      {notice && <p className="text-sm text-ledger">{notice}</p>}

      <CompaniesSection
        companies={companies} companyId={companyId} setCompanyId={setCompanyId}
        refreshCompanies={refreshCompanies} notify={setNotice}
      />

      {/* Organizational information (per company) */}
      <section className="card p-5 space-y-3">
        <h2 className="font-medium">Organizational information</h2>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Company name"><input className="input" value={companyForm.name || ""} onChange={setC("name")} /></Field>
          <Field label="Company logo">
            <div className="flex items-center gap-3">
              {companyForm.logo_path && (
                <img src={`${api.companyLogoUrl(companyId)}?t=${companyForm.logo_path}`} alt="Logo preview" className="h-8 border border-rule rounded bg-white object-contain px-1" />
              )}
              <label className="btn-ghost cursor-pointer inline-block">
                {companyForm.logo_path ? "Replace logo" : "Upload logo"}
                <input type="file" accept="image/*" className="hidden" onChange={uploadCompanyImage(api.uploadCompanyLogo, "Logo", "logo_path")} />
              </label>
            </div>
          </Field>
        </div>
        <Field label="Address"><textarea className="input" rows={2} value={companyForm.address || ""} onChange={setC("address")} /></Field>
        <button className="btn-primary" onClick={saveCompany}>Save company details</button>
      </section>

      {/* Seal + designated officer (per company) */}
      <section className="card p-5 space-y-3">
        <h2 className="font-medium">Seal &amp; designated officer</h2>
        <p className="text-sm text-ink/60">
          The seal renders below the issue date at the bottom of the Signature and seal block.
        </p>
        <Field label="Seal image (PNG with transparency)">
          <div className="flex items-center gap-3">
            {companyForm.seal_path && (
              <img src={`${api.companySealUrl(companyId)}?t=${companyForm.seal_path}`} alt="Seal preview" className="h-10 border border-rule rounded bg-white object-contain" />
            )}
            <label className="btn-ghost cursor-pointer inline-block">
              {companyForm.seal_path ? "Replace seal" : "Upload seal"}
              <input type="file" accept="image/png,image/jpeg" className="hidden" onChange={uploadCompanyImage(api.uploadCompanySeal, "Seal", "seal_path")} />
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
        <button className="btn-primary" onClick={saveCompany}>Save seal &amp; officer details</button>
      </section>

      <SignaturesSection companyId={companyId} notify={setNotice} />

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
              {companyForm.letterhead_header_path && (
                <img src={`${api.letterheadHeaderUrl(companyId)}?t=${companyForm.letterhead_header_path}`} alt="Letterhead header preview" className="w-full border border-rule rounded bg-white object-contain" />
              )}
              <label className="btn-ghost cursor-pointer inline-block">
                {companyForm.letterhead_header_path ? "Replace header" : "Upload header"}
                <input type="file" accept="image/png,image/jpeg" className="hidden" onChange={uploadCompanyImage(api.uploadLetterheadHeader, "Letterhead header", "letterhead_header_path")} />
              </label>
            </div>
          </Field>
          <Field label="Letterhead footer">
            <div className="space-y-2">
              {companyForm.letterhead_footer_path && (
                <img src={`${api.letterheadFooterUrl(companyId)}?t=${companyForm.letterhead_footer_path}`} alt="Letterhead footer preview" className="w-full border border-rule rounded bg-white object-contain" />
              )}
              <label className="btn-ghost cursor-pointer inline-block">
                {companyForm.letterhead_footer_path ? "Replace footer" : "Upload footer"}
                <input type="file" accept="image/png,image/jpeg" className="hidden" onChange={uploadCompanyImage(api.uploadLetterheadFooter, "Letterhead footer", "letterhead_footer_path")} />
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
    </div>
  );
}
