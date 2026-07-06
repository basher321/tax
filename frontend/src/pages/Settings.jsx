import { useEffect, useState } from "react";
import { api } from "../api/client.js";

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

export default function Settings() {
  const [org, setOrg] = useState(null);
  const [num, setNum] = useState(null);
  const [notice, setNotice] = useState(null);
  const [resetConfirm, setResetConfirm] = useState("");
  const [resetBusy, setResetBusy] = useState(false);

  useEffect(() => {
    api.getOrg().then(setOrg);
    api.getNumbering().then(setNum);
  }, []);

  if (!org || !num) return <p className="text-ink/50">Loading…</p>;

  const setO = (k) => (e) =>
    setOrg({ ...org, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const setN = (k) => (e) => setNum({ ...num, [k]: e.target.value });

  async function saveOrg() {
    const body = { ...org };
    // booleans standing in for stored secrets must not be sent back
    for (const k of ["smtp_password", "wa_token", "wa_twilio_auth"])
      if (typeof body[k] === "boolean") delete body[k];
    delete body.id; delete body.logo_path; delete body.seal_signature_path;
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

  async function saveNumbering() {
    await api.updateNumbering({
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
      const [freshOrg, freshNum] = await Promise.all([api.getOrg(), api.getNumbering()]);
      setOrg(freshOrg);
      setNum(freshNum);
      setResetConfirm("");
      setNotice("Database reset complete. You can start again.");
    } catch (err) {
      setNotice(`Database reset failed: ${err.message}`);
    } finally {
      setResetBusy(false);
    }
  }

  const upload = (fn, label, pathField) => async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    const res = await fn(f);
    setOrg((current) => ({ ...current, [pathField]: res.path }));
    setNotice(`${label} uploaded.`);
  };

  const example = `${num.company_token}${num.separator}2025-26${num.separator}${String(num.start_number).padStart(Number(num.pad_width), "0")}`;

  return (
    <div className="space-y-6 max-w-3xl">
      <h1 className="text-xl font-semibold">Settings</h1>
      {notice && <p className="text-sm text-ledger">{notice}</p>}

      {/* Organizational information */}
      <section className="card p-5 space-y-3">
        <h2 className="font-medium">Organizational information</h2>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Company name"><input className="input" value={org.company_name || ""} onChange={setO("company_name")} /></Field>
          <Field label="Company logo">
            <label className="btn-ghost cursor-pointer inline-block">
              {org.logo_path ? "Replace logo" : "Upload logo"}
              <input type="file" accept="image/*" className="hidden" onChange={upload(api.uploadLogo, "Logo", "logo_path")} />
            </label>
          </Field>
        </div>
        <Field label="Address"><textarea className="input" rows={2} value={org.company_address || ""} onChange={setO("company_address")} /></Field>
      </section>

      {/* Seal/signature + officer — rendered on every certificate */}
      <section className="card p-5 space-y-3">
        <h2 className="font-medium">Seal, signature & designated officer</h2>
        <p className="text-sm text-ink/60">
          These render on every generated certificate. The issue date is placed
          automatically under the seal and signature block.
        </p>
        <Field label="Seal + signature image (PNG with transparency)">
          <label className="btn-ghost cursor-pointer inline-block">
            {org.seal_signature_path ? "Replace image" : "Upload image"}
            <input type="file" accept="image/png,image/jpeg" className="hidden" onChange={upload(api.uploadSeal, "Seal/signature", "seal_signature_path")} />
          </label>
          {org.seal_signature_path && <span className="text-xs text-ledger ml-2">✓ on file</span>}
        </Field>
        <div className="grid grid-cols-3 gap-3">
          <Field label="Officer name"><input className="input" value={org.officer_name || ""} onChange={setO("officer_name")} /></Field>
          <Field label="Designation"><input className="input" value={org.officer_designation || ""} onChange={setO("officer_designation")} /></Field>
          <Field label="Officer email"><input className="input" value={org.officer_email || ""} onChange={setO("officer_email")} /></Field>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Default bank name (Section 07)"><input className="input" value={org.default_bank_name || ""} onChange={setO("default_bank_name")} /></Field>
          <Field label="Default payment description (Section 06)"><input className="input" value={org.default_description || ""} onChange={setO("default_description")} /></Field>
        </div>
      </section>

      {/* Certificate numbering */}
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
        <p className="text-sm">Next number will look like: <span className="font-mono">{example}</span></p>
        <button className="btn-primary" onClick={saveNumbering}>Save numbering</button>
      </section>

      {/* SMTP */}
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

      {/* WhatsApp */}
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

      <button className="btn-primary" onClick={saveOrg}>Save all settings</button>

      <section className="card border-red-200 bg-red-50/40 p-5 space-y-3">
        <h2 className="font-medium text-red-800">Database reset</h2>
        <p className="text-sm text-red-800">
          This removes imports, suppliers, certificates, dispatch jobs, rates,
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
