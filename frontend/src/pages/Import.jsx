import { useMemo, useState } from "react";
import { api } from "../api/client.js";
import { PageHeader, Notice, EmptyState } from "../components/ui.jsx";

export default function Import() {
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
        title="Import"
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
