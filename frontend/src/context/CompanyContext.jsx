import { createContext, useContext, useEffect, useState } from "react";
import { api } from "../api/client.js";

const STORAGE_KEY = "tds_company_id";

const CompanyContext = createContext(null);

export function CompanyProvider({ children }) {
  const [companies, setCompanies] = useState([]);
  const [companyId, setCompanyIdState] = useState(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored ? Number(stored) : null;
  });
  const [loading, setLoading] = useState(true);

  function setCompanyId(id) {
    setCompanyIdState(id);
    if (id != null) localStorage.setItem(STORAGE_KEY, String(id));
  }

  function refreshCompanies() {
    return api.listCompanies().then((list) => {
      setCompanies(list);
      return list;
    });
  }

  useEffect(() => {
    refreshCompanies().then((list) => {
      setLoading(false);
      const stillExists = companyId != null && list.some((c) => c.id === companyId);
      if (!stillExists && list.length) {
        const fallback = list.find((c) => c.is_default) || list[0];
        setCompanyId(fallback.id);
      }
      // eslint-disable-next-line react-hooks/exhaustive-deps
    });
  }, []);

  return (
    <CompanyContext.Provider value={{ companies, companyId, setCompanyId, loading, refreshCompanies }}>
      {children}
    </CompanyContext.Provider>
  );
}

export function useCompany() {
  const ctx = useContext(CompanyContext);
  if (!ctx) throw new Error("useCompany must be used within CompanyProvider");
  return ctx;
}
