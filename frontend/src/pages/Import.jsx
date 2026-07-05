import { useEffect, useState } from "react";
import { api } from "../api/client.js";

function Uploader({ title, hint, onUpload }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  async function handleFile(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true); setError(null); setResult(null);
    try {
      setResult(await onUpload(file));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
      e.target.value = "";
    }
  }

  return (
    <div className="card p-5">
      <h2 className="font-medium">{title}</h2>
      <p className="text-sm text-ink/60 mt-1">{hint}</p>
      <label className="btn-primary inline-block mt-3 cursor-pointer">
        {busy ? "Uploading…" : "Choose .xlsx file"}
        <input type="file" accept=".xlsx" className="hidden" onChange={handleFile} disabled={busy} />
      </label>
      {error && <p className="text-sm text-red-700 mt-2">{error}</p>}
      {result && (
        <p className="text-sm mt-2">
          {result.total_rows} rows read — {" "}
          <span className="text-ledger font-medium">{result.ok_rows} imported</span>
          {result.error_rows > 0 && (
            <span className="text-red-700"> · {result.error_rows} rows need attention (see table below)</span>
          )}
        </p>
      )}
    </div>
  );
}

export default function Import() {
  const [batches, setBatches] = useState([]);
  const [selected, setSelected] = useState(null);

  const refresh = () => api.importBatches().then((b) => {
    setBatches(b);
    if (b.length && !selected) setSelected(b[0]);
  });

  useEffect(() => { refresh(); }, []);

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Import</h1>

      <div className="grid grid-cols-2 gap-4">
        <Uploader
          title="Depot-SCB workbook"
          hint="Imports all 21 columns from the Depot-SCB sheet. Bad rows are skipped and listed below — the import never aborts on a single row."
          onUpload={async (f) => { const r = await api.uploadDepot(f); refresh(); setSelected(r); return r; }}
        />
        <Uploader
          title="Challan file"
          hint="Auto-fills Challan No., Challan Date, Total Challan Amount and Section on matching supplier / month records."
          onUpload={async (f) => { const r = await api.uploadChallan(f); refresh(); setSelected(r); return r; }}
        />
      </div>

      <div className="card">
        <div className="px-5 py-3 border-b border-rule flex items-center gap-3">
          <h2 className="font-medium">Row-level errors</h2>
          <select
            className="input !w-auto"
            value={selected?.id || ""}
            onChange={(e) => setSelected(batches.find((b) => b.id === Number(e.target.value)))}
          >
            {batches.map((b) => (
              <option key={b.id} value={b.id}>
                #{b.id} · {b.filename} ({b.kind}) — {b.error_rows} errors
              </option>
            ))}
          </select>
        </div>
        {!selected || selected.errors?.length === 0 ? (
          <p className="p-5 text-sm text-ink/50">
            No errors in this batch. Every row imported cleanly.
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-ink/50 border-b border-rule">
                <th className="px-5 py-2">Excel row</th>
                <th className="px-3 py-2">Column</th>
                <th className="px-3 py-2">Problem</th>
              </tr>
            </thead>
            <tbody>
              {selected.errors.map((e, i) => (
                <tr key={i} className="border-b border-rule/60">
                  <td className="px-5 py-2 font-mono">{e.row_number}</td>
                  <td className="px-3 py-2">{e.column || "—"}</td>
                  <td className="px-3 py-2 text-red-800">{e.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
