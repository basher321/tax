import { useMemo, useState } from "react";
import { api } from "../api/client.js";
import { PageHeader, Notice, EmptyState } from "../components/ui.jsx";

const TXN_EDIT_FIELDS = [
  { key: "challan_no", label: "Challan No" },
  { key: "challan_date", label: "Challan Date", type: "date" },
  { key: "section", label: "Section" },
  { key: "total_challan_amount", label: "Total Challan Amount", type: "number" },
  { key: "sum_of_bill_amount", label: "Sum of Bill Amount", type: "number" },
  { key: "sum_of_tds", label: "Sum of TDS", type: "number" },
  { key: "sum_of_vds", label: "Sum of VDS", type: "number" },
];

/* Challan file upload: auto-fills challan/amount fields on matching
   transactions, then lets the user manually override any auto-filled
   value before it feeds into certificate generation (item 7). */
function ChallanPanel() {
  const [busy, setBusy] = useState(false);
  const [batch, setBatch] = useState(null);
  const [error, setError] = useState(null);
  const [rows, setRows] = useState({}); // id -> editable field values
  const [savingId, setSavingId] = useState(null);
  const [savedIds, setSavedIds] = useState({});

  async function handleFile(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setError(null);
    setBatch(null);
    setRows({});
    setSavedIds({});
    try {
      const result = await api.uploadChallan(file);
      setBatch(result);
      setRows(Object.fromEntries((result.updated_transactions || []).map((t) => [t.id, { ...t }])));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
      event.target.value = "";
    }
  }

  const setField = (id, key) => (e) =>
    setRows({ ...rows, [id]: { ...rows[id], [key]: e.target.value } });

  async function saveRow(id) {
    setSavingId(id);
    try {
      const body = Object.fromEntries(
        TXN_EDIT_FIELDS.map(({ key }) => [key, rows[id][key] === "" ? null : rows[id][key]])
      );
      const updated = await api.adjustTransaction(id, body);
      setRows({ ...rows, [id]: { ...updated } });
      setSavedIds({ ...savedIds, [id]: true });
    } catch (err) {
      setError(err.message);
    } finally {
      setSavingId(null);
    }
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title=""
        subtitle="Upload a challan file to auto-fill challan number/date and the adjusted bill/TDS/VDS amounts on matching transactions. Override any value below before generating certificates."
      >
        <label className={`btn-primary cursor-pointer ${busy ? "opacity-60 pointer-events-none" : ""}`}>
          {busy ? "Parsing..." : "Upload challan file"}
          <input type="file" accept=".xlsx,.xls" className="hidden" onChange={handleFile} disabled={busy} />
        </label>
      </PageHeader>

      {error && <Notice kind="err" onDismiss={() => setError(null)}>{error}</Notice>}

      {busy && (
        <div className="card p-8 text-center text-sm text-ink/50">
          Reading the challan file. Large files can take a few seconds.
        </div>
      )}

      {!busy && !batch && !error && (
        <div className="card">
          <EmptyState
            title="No challan file uploaded yet"
            hint="Choose an .xlsx/.xls file with Challan No, Challan Date, TIN/Supplier Name, and Month columns."
          />
        </div>
      )}

      {batch && (
        <div className="card overflow-hidden">
          <div className="card-head">
            <span className="card-title">{batch.filename}</span>
            <span className="badge-green">{batch.ok_rows.toLocaleString()} matched</span>
            {batch.error_rows > 0 && (
              <span className="badge-red">{batch.error_rows} skipped</span>
            )}
            <span className="ml-auto text-xs text-ink/40">
              {(batch.updated_transactions || []).length} transaction(s) auto-filled
            </span>
          </div>

          {batch.errors?.length > 0 && (
            <div className="px-5 py-3 border-b border-rule text-sm">
              <p className="font-medium text-red-800 mb-1">Row errors (row not applied, batch continued):</p>
              <ul className="list-disc ml-5 text-red-800 space-y-0.5">
                {batch.errors.map((e, i) => (
                  <li key={i}>Row {e.row_number}{e.column ? ` (${e.column})` : ""}: {e.message}</li>
                ))}
              </ul>
            </div>
          )}

          {(batch.updated_transactions || []).length > 0 && (
            <div className="overflow-auto max-h-[60vh]">
              <table className="tbl min-w-max">
                <thead className="sticky top-0 z-10">
                  <tr>
                    <th>TIN</th><th>Supplier</th><th>Month</th>
                    {TXN_EDIT_FIELDS.map((f) => <th key={f.key}>{f.label}</th>)}
                    <th></th>
                  </tr>
                </thead>
                <tbody className="text-xs">
                  {batch.updated_transactions.map((t) => {
                    const r = rows[t.id] || t;
                    return (
                      <tr key={t.id}>
                        <td className="font-mono">{t.tin}</td>
                        <td>{t.supplier_name}</td>
                        <td>{t.month}</td>
                        {TXN_EDIT_FIELDS.map((f) => (
                          <td key={f.key}>
                            <input
                              type={f.type || "text"}
                              className="input !py-1 !text-xs"
                              value={r[f.key] ?? ""}
                              onChange={setField(t.id, f.key)}
                            />
                          </td>
                        ))}
                        <td className="whitespace-nowrap">
                          <button className="btn-ghost !py-0.5" onClick={() => saveRow(t.id)} disabled={savingId === t.id}>
                            {savingId === t.id ? "Saving..." : savedIds[t.id] ? "Saved" : "Save"}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function DepotPanel() {
  const [busy, setBusy] = useState(false);
  const [batch, setBatch] = useState(null);
  const [error, setError] = useState(null);

  const errorsByRow = useMemo(() => {
    const map = {};
    for (const err of batch?.errors || []) {
      (map[err.row_number] ||= []).push(
        err.column ? `${err.column}: ${err.message}` : err.message
      );
    }
    return map;
  }, [batch]);

  async function handleFile(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setError(null);
    setBatch(null);
    try {
      setBatch(await api.uploadDepot(file));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
      event.target.value = "";
    }
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title=""
        subtitle="Upload the Depot-SCB workbook. Every parsed row and column appears below."
      >
        <label className={`btn-primary cursor-pointer ${busy ? "opacity-60 pointer-events-none" : ""}`}>
          {busy ? "Parsing..." : "Upload .xlsx file"}
          <input type="file" accept=".xlsx" className="hidden" onChange={handleFile} disabled={busy} />
        </label>
      </PageHeader>

      {error && <Notice kind="err" onDismiss={() => setError(null)}>{error}</Notice>}

      {busy && (
        <div className="card p-8 text-center text-sm text-ink/50">
          Reading the workbook. Large files can take a few seconds.
        </div>
      )}

      {!busy && !batch && !error && (
        <div className="card">
          <EmptyState
            title="No file uploaded yet"
            hint="Choose an .xlsx file to review the full parsed sheet here."
          />
        </div>
      )}

      {batch && (
        <div className="card overflow-hidden">
          <div className="card-head">
            <span className="card-title">{batch.filename}</span>
            <span className="badge-green">{batch.ok_rows.toLocaleString()} imported</span>
            {batch.error_rows > 0 && (
              <span className="badge-red" title="Tinted rows below show the skipped row reason">
                {batch.error_rows} skipped
              </span>
            )}
            <span className="ml-auto text-xs text-ink/40">
              {batch.total_rows.toLocaleString()} rows, {batch.columns?.length || 0} columns
            </span>
          </div>

          <div className="overflow-auto max-h-[70vh]">
            <table className="tbl min-w-max">
              <thead className="sticky top-0 z-10">
                <tr>
                  <th>Row</th>
                  {batch.columns?.map((column) => <th key={column}>{column}</th>)}
                </tr>
              </thead>
              <tbody className="font-mono text-xs">
                {batch.rows?.map((row) => {
                  const errors = errorsByRow[row.__excel_row];
                  return (
                    <tr
                      key={row.__excel_row}
                      className={errors ? "!bg-red-50 hover:!bg-red-100" : ""}
                      title={errors?.join("\n")}
                    >
                      <td className="text-ink/40">{row.__excel_row}</td>
                      {batch.columns?.map((column) => (
                        <td key={column} className="max-w-[220px] truncate">
                          {row[column]}
                        </td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

export default function Import() {
  const [tab, setTab] = useState("depot");

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2 mb-1">
        <h1 className="text-xl font-semibold mr-4">Import</h1>
        <div className="inline-flex rounded-md border border-rule overflow-hidden text-sm">
          <button
            className={`px-3 py-1.5 ${tab === "depot" ? "bg-ink text-paper" : "bg-white text-ink/70"}`}
            onClick={() => setTab("depot")}
          >
            Depot workbook
          </button>
          <button
            className={`px-3 py-1.5 ${tab === "challan" ? "bg-ink text-paper" : "bg-white text-ink/70"}`}
            onClick={() => setTab("challan")}
          >
            Challan file
          </button>
        </div>
      </div>
      {tab === "depot" ? <DepotPanel /> : <ChallanPanel />}
    </div>
  );
}
