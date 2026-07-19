import { useEffect } from "react";
import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import Dashboard from "./pages/Dashboard.jsx";
import Settings from "./pages/Settings.jsx";
import Import from "./pages/Import.jsx";
import CertificateIssue from "./pages/CertificateIssue.jsx";
import { useCompany } from "./context/CompanyContext.jsx";

// The sidebar contains EXACTLY these four items — per spec, no additions.
const NAV = [
  { to: "/dashboard", label: "Dashboard", kicker: "Control center" },
  { to: "/settings", label: "Settings", kicker: "Company profile" },
  { to: "/import", label: "Import", kicker: "Workbook intake" },
  { to: "/certificates", label: "Certificate Issue", kicker: "Generate and send" },
];

const PAGE_TITLES = {
  "/dashboard": {
    title: "Dashboard",
    description: "Operational overview for tax certificate processing.",
  },
  "/settings": {
    title: "Settings",
    description: "Organization, numbering, email, and WhatsApp configuration.",
  },
  "/import": {
    title: "Import",
    description: "Load Depot-SCB workbooks with row-level validation.",
  },
  "/certificates": {
    title: "Certificate Issue",
    description: "Generate, preview, dispatch, print, and download certificates.",
  },
};

export default function App() {
  const location = useLocation();
  const page = PAGE_TITLES[location.pathname] || PAGE_TITLES["/dashboard"];
  const { companies, companyId, setCompanyId, loading: companiesLoading } = useCompany();

  useEffect(() => {
    const state = window.history.state || {};

    const keepAppOpen = (event) => {
      if (!event.state?.tdsAppEntry) return;
      window.history.pushState(
        { tdsAppPage: true },
        "",
        window.location.href
      );
    };

    if (!state.tdsAppEntry && !state.tdsAppPage) {
      window.history.replaceState(
        { ...state, tdsAppEntry: true },
        "",
        window.location.href
      );
      window.history.pushState(
        { tdsAppPage: true },
        "",
        window.location.href
      );
    }

    window.addEventListener("popstate", keepAppOpen);
    return () => window.removeEventListener("popstate", keepAppOpen);
  }, []);

  useEffect(() => {
    if (window.history.state?.tdsAppPage) return;
    window.history.replaceState(
      { ...(window.history.state || {}), tdsAppPage: true },
      "",
      window.location.href
    );
  }, [location.pathname]);

  return (
    <div className="flex min-h-screen bg-paper text-ink">
      <aside className="sticky top-0 h-screen w-72 shrink-0 overflow-y-auto bg-ink text-paper flex flex-col border-r border-black/20">
        <div className="px-6 py-6 border-b border-white/10">
          <div className="font-mono text-[11px] tracking-[0.18em] text-white/50 uppercase">
            TDS Operations
          </div>
          <div className="font-semibold leading-tight mt-2 text-lg">
            Tax Deduction Certificates
          </div>
          <div className="mt-3 inline-flex items-center gap-2 rounded border border-white/10 px-2 py-1 text-xs text-white/70">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-300" />
            Section 145 workflow
          </div>
        </div>
        <nav className="p-3 space-y-1.5">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `block rounded-md px-3 py-3 text-sm transition-colors ${
                  isActive
                    ? "bg-white text-ink shadow-sm"
                    : "text-white/70 hover:bg-white/10 hover:text-white"
                }`
              }
            >
              <span className="block font-medium">{item.label}</span>
              <span className="mt-0.5 block text-xs opacity-60">{item.kicker}</span>
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto border-t border-white/10 px-6 py-4 text-xs text-white/55">
          Local ERP module
          <span className="block font-mono text-white/35">localhost:5173</span>
        </div>
      </aside>

      <div className="min-w-0 flex-1">
        <header className="sticky top-0 z-10 border-b border-rule bg-paper/95 px-8 py-5 backdrop-blur">
          <div className="flex items-center justify-between gap-4">
            <div>
              <div className="font-mono text-xs uppercase text-ink/45">
                Tax certificate module
              </div>
              <h1 className="mt-1 text-2xl font-semibold">{page.title}</h1>
              <p className="mt-1 text-sm text-ink/60">{page.description}</p>
            </div>
            <div className="flex items-center gap-3">
              {!companiesLoading && companies.length > 0 && (
                <div className="text-right">
                  <span className="block text-[11px] uppercase tracking-wide text-ink/45">Company</span>
                  <select
                    className="input !py-1.5 !w-56"
                    value={companyId ?? ""}
                    onChange={(e) => setCompanyId(Number(e.target.value))}
                  >
                    {companies.map((c) => (
                      <option key={c.id} value={c.id}>{c.name}</option>
                    ))}
                  </select>
                </div>
              )}
              <div className="rounded border border-rule bg-white px-3 py-2 text-right text-xs text-ink/60 shadow-sm">
                <span className="block font-medium text-ink">System ready</span>
                PostgreSQL connected
              </div>
            </div>
          </div>
        </header>

        <main className="max-w-7xl px-8 py-8">
          <Routes>
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/import" element={<Import />} />
            <Route path="/certificates" element={<CertificateIssue />} />
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}
