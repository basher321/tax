import { useCallback, useRef, useState } from "react";
import { api } from "../api/client.js";
import { PageHeader, Notice, EmptyState } from "../components/ui.jsx";
import { useCompany } from "../context/CompanyContext.jsx";
import VirtualizedTable from "../components/VirtualizedTable.jsx";

// Rows are fetched from the database in pages this size and accumulated
// client-side — keeps every single response small regardless of how large
// the uploaded workbook was (a 50,000+ row file returned in one shot would
// risk the response itself becoming too large).
const ROWS_PAGE_SIZE = 5000;

const COLUMNS = [
  { key: "Payment Date", label: "Payment Date", width: 100 },
  { key: "Cheque Number", label: "Cheque Number", width: 120 },
  { key: "Supplier Name", label: "Supplier Name", width: 240 },
  { key: "Supplier Address", label: "Supplier Address", width: 200 },
  { key: "WhatsApp No.", label: "WhatsApp No.", width: 120 },
  { key: "Email", label: "Email", width: 180 },
  { key: "Depot Code", label: "Depot Code", width: 100 },
  { key: "Sum of Bill Amount", label: "Sum of Bill Amount", width: 130, align: "right" },
  { key: "Sum of TDS", label: "Sum of TDS", width: 110, align: "right" },
  { key: "Base Amount", label: "Base Amount", width: 120, align: "right" },
  {
    key: "TDS Rate", label: "TDS Rate", width: 90, align: "right",
    format: (v) => (v === "" || v == null ? "" : `${(Number(v) * 100).toFixed(0)}%`),
  },
  { key: "Section", label: "Section", width: 80 },
  { key: "TIN", label: "TIN", width: 130 },
  { key: "Challan No", label: "Challan No", width: 160 },
  { key: "Challan Date", label: "Challan Date", width: 100 },
  { key: "Bank Name", label: "Bank Name", width: 150 },
  { key: "Description of Payment", label: "Description of Payment", width: 180 },
  { key: "Cheque/Challan SL", label: "Cheque/Challan SL", width: 110 },
  { key: "Month", label: "Month", width: 100 },
  { key: "Total Challan Amount", label: "Total Challan Amount", width: 150, align: "right" },
  { key: "Remarks", label: "Remarks", width: 160 },
];

function validateDepotFile(file) {
  if (!file.name.toLowerCase().endsWith(".xlsx")) {
    return "Only .xlsx workbooks are supported. Choose a different file.";
  }
  return null;
}

function DepotPanel({ companyId }) {
  const [busy, setBusy] = useState(false);
  const [batch, setBatch] = useState(null);
  const [error, setError] = useState(null);
  const [rows, setRows] = useState([]);
  const [loadingRows, setLoadingRows] = useState(false);
  const [rowsLoaded, setRowsLoaded] = useState(0);
  const [rowsTotal, setRowsTotal] = useState(0);
  const fileInputRef = useRef(null);

  const loadAllRows = useCallback(async (batchId) => {
    setLoadingRows(true);
    setRows([]);
    setRowsLoaded(0);
    setRowsTotal(0);
    try {
      let page = 1;
      let all = [];
      // Loop paginated reads (straight from the database — see GET
      // /import/rows) until every row for this batch is loaded, then hand
      // the whole array to the virtualized table for rendering.
      for (;;) {
        const res = await api.importRows(companyId, batchId, page, ROWS_PAGE_SIZE);
        all = all.concat(res.rows);
        setRowsTotal(res.total);
        setRowsLoaded(all.length);
        setRows(all);
        if (all.length >= res.total || res.rows.length === 0) break;
        page += 1;
      }
    } catch (err) {
      setError(`Could not load imported rows: ${err.message}`);
    } finally {
      setLoadingRows(false);
    }
  }, [companyId]);

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
      const b = await api.uploadDepot(companyId, file);
      setBatch(b);
      await loadAllRows(b.id);
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
        <div className="flex items-center gap-2">
          <a className="btn-ghost" href="/Sample_TDS_Format.xlsx" download>
            Download sample file
          </a>
          <label className={`btn-primary cursor-pointer ${busy || !companyId ? "opacity-60 pointer-events-none" : ""}`}>
            {busy ? "Uploading..." : batch || error ? "Replace file" : "Upload .xlsx file"}
            <input
              ref={fileInputRef}
              type="file" accept=".xlsx" className="hidden"
              onChange={handleFile} disabled={busy || !companyId}
            />
          </label>
        </div>
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
            <span className="ml-auto text-xs text-ink/40">
              {loadingRows
                ? `Loading rows... ${rowsLoaded.toLocaleString()} of ${rowsTotal.toLocaleString()}`
                : `${rows.length.toLocaleString()} rows, ${COLUMNS.length} columns`}
            </span>
          </div>
          <div className="p-3">
            <VirtualizedTable columns={COLUMNS} rows={rows} height={560} />
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
