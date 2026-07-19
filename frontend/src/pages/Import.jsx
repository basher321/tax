import { useMemo, useRef, useState } from "react";
import { api } from "../api/client.js";
import { PageHeader, Notice, EmptyState } from "../components/ui.jsx";
import { useCompany } from "../context/CompanyContext.jsx";

const MAX_FILE_SIZE = 15 * 1024 * 1024; // 15 MB

function validateDepotFile(file) {
  if (!file.name.toLowerCase().endsWith(".xlsx")) {
    return "Only .xlsx workbooks are supported. Choose a different file.";
  }
  if (file.size > MAX_FILE_SIZE) {
    return `File is too large (${(file.size / (1024 * 1024)).toFixed(1)} MB). Maximum size is 15 MB.`;
  }
  return null;
}

function DepotPanel({ companyId }) {
  const [busy, setBusy] = useState(false);
  const [batch, setBatch] = useState(null);
  const [error, setError] = useState(null);
  const fileInputRef = useRef(null);

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
    const validationError = validateDepotFile(file);
    if (validationError) {
      setError(validationError);
      setBatch(null);
      event.target.value = "";
      return;
    }
    setBusy(true);
    setError(null);
    setBatch(null);
    try {
      setBatch(await api.uploadDepot(companyId, file));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
      event.target.value = "";
    }
  }

  // Re-upload/Replace file: re-opens the same file picker inline, without a
  // page reload or touching any other state on the page (item 4).
  function reupload() {
    fileInputRef.current?.click();
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title=""
        subtitle="Upload the Depot-SCB workbook. Every parsed row and column appears below."
      >
        <label className={`btn-primary cursor-pointer ${busy || !companyId ? "opacity-60 pointer-events-none" : ""}`}>
          {busy ? "Parsing..." : batch || error ? "Replace file" : "Upload .xlsx file"}
          <input
            ref={fileInputRef}
            type="file" accept=".xlsx" className="hidden"
            onChange={handleFile} disabled={busy || !companyId}
          />
        </label>
      </PageHeader>

      {error && (
        <Notice kind="err" onDismiss={() => setError(null)}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span>{error}</span>
            <button className="btn-ghost btn-sm shrink-0" onClick={reupload}>Re-upload</button>
          </div>
        </Notice>
      )}

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
  const { companyId } = useCompany();

  return (
    <div className="space-y-5">
      <h1 className="text-xl font-semibold">Import</h1>
      {!companyId && (
        <Notice kind="err">Select a company from the header above before importing.</Notice>
      )}
      <DepotPanel companyId={companyId} />
    </div>
  );
}
