import { useEffect, useState } from "react";
import { api } from "../api/client.js";

const money = (n) => `BDT ${Number(n || 0).toLocaleString()}`;
const number = (n) => Number(n || 0).toLocaleString();

export default function Dashboard() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.dashboard().then(setData).catch((e) => setError(e.message));
  }, []);

  if (error) return <p className="text-red-700">Couldn't load summary: {error}</p>;
  if (!data) return <p className="text-ink/50">Loading...</p>;

  const issued =
    Number(data.certificates.generated || 0) + Number(data.certificates.sent || 0);
  const sent = Number(data.certificates.sent || 0);
  const generated = Number(data.certificates.generated || 0);
  const pending = Number(data.pending_groupings || 0);
  const queue = Number(data.queued_dispatches || 0);
  const completion = issued ? Math.min(100, (issued / (issued + pending)) * 100) : 0;

  const stats = [
    { label: "Imported transactions", value: number(data.transactions), tone: "Ready" },
    { label: "Suppliers on file", value: number(data.suppliers), tone: "Validated" },
    { label: "Certificates issued", value: number(issued), tone: `${sent} sent` },
    { label: "Pending groups", value: number(pending), tone: "Awaiting issue" },
    { label: "Total TDS recorded", value: money(data.total_tds), tone: "Source total" },
    { label: "Dispatch queue", value: number(queue), tone: queue ? "Action needed" : "Clear" },
  ];

  return (
    <div className="space-y-6">
      <section className="grid grid-cols-4 gap-4">
        <div className="card col-span-2 p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-sm font-medium text-ink/60">Current workload</p>
              <div className="mt-3 flex items-end gap-3">
                <span className="font-mono text-5xl leading-none">{number(pending)}</span>
                <span className="pb-1 text-sm text-ink/60">pending TIN-period groups</span>
              </div>
            </div>
            <span
              className={`rounded px-2 py-1 text-xs font-medium ${
                pending ? "bg-amber-100 text-amber-800" : "bg-ledger/10 text-ledger"
              }`}
            >
              {pending ? "Issue pending" : "No backlog"}
            </span>
          </div>
          <div className="mt-5 h-2 rounded bg-rule">
            <div className="h-2 rounded bg-ledger" style={{ width: `${completion}%` }} />
          </div>
          <div className="mt-2 flex justify-between text-xs text-ink/55">
            <span>{number(issued)} certificates issued</span>
            <span>{number(pending)} remaining</span>
          </div>
        </div>

        <div className="card p-5">
          <p className="text-sm font-medium text-ink/60">Dispatch health</p>
          <div className="mt-3 font-mono text-4xl">{number(queue)}</div>
          <p className="mt-2 text-sm text-ink/60">
            {queue ? "Messages are waiting for processing." : "No email or WhatsApp jobs are waiting."}
          </p>
        </div>

        <div className="card p-5">
          <p className="text-sm font-medium text-ink/60">Generated status</p>
          <div className="mt-3 space-y-2 text-sm">
            <div className="flex justify-between">
              <span>Generated</span>
              <span className="font-mono">{number(generated)}</span>
            </div>
            <div className="flex justify-between">
              <span>Sent</span>
              <span className="font-mono">{number(sent)}</span>
            </div>
            <div className="flex justify-between border-t border-rule pt-2 font-medium">
              <span>Total</span>
              <span className="font-mono">{number(issued)}</span>
            </div>
          </div>
        </div>
      </section>

      <section className="grid grid-cols-3 gap-4">
        {stats.map((s) => (
          <div key={s.label} className="card p-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="font-mono text-2xl">{s.value}</div>
                <div className="mt-1 text-sm text-ink/60">{s.label}</div>
              </div>
              <span className="rounded border border-rule bg-paper px-2 py-1 text-[11px] font-medium text-ink/55">
                {s.tone}
              </span>
            </div>
          </div>
        ))}
      </section>
    </div>
  );
}
