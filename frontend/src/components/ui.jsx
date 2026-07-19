import { useCallback, useEffect, useState } from "react";

export function PageHeader({ title, subtitle, children }) {
  return (
    <div className="flex items-end justify-between gap-4 mb-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="text-sm text-ink/55 mt-0.5">{subtitle}</p>}
      </div>
      {children}
    </div>
  );
}

export function Notice({ kind = "ok", children, onDismiss }) {
  if (!children) return null;
  return (
    <div className={kind === "ok" ? "notice-ok" : "notice-err"}>
      <span className="mt-px">{kind === "ok" ? "OK" : "!"}</span>
      <div className="flex-1">{children}</div>
      {onDismiss && (
        <button className="opacity-50 hover:opacity-100" onClick={onDismiss}>
          Close
        </button>
      )}
    </div>
  );
}

export function EmptyState({ title, hint }) {
  return (
    <div className="p-10 text-center">
      <p className="font-medium text-ink/60">{title}</p>
      {hint && <p className="text-sm text-ink/40 mt-1">{hint}</p>}
    </div>
  );
}

/* Auto-dismissing toast notification, shared across pages so a save/error
   confirmation always looks and behaves the same. Each notify() call gets a
   fresh id (even for repeated identical text), so the toast always re-pops
   and re-starts its timer instead of looking stale/stuck. */
export function useToast() {
  const [toast, setToast] = useState(null);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 3500);
    return () => clearTimeout(t);
  }, [toast]);
  const notify = useCallback(
    (message, kind = "ok") => setToast({ id: Date.now(), message, kind }),
    []
  );
  const dismiss = useCallback(() => setToast(null), []);
  return [toast, notify, dismiss];
}

export function Toast({ toast, onDismiss }) {
  if (!toast) return null;
  return (
    <div
      key={toast.id}
      role="status"
      aria-live="polite"
      className={`fixed bottom-5 right-5 z-30 max-w-sm shadow-lg animate-toast-in ${
        toast.kind === "err" ? "notice-err" : "notice-ok"
      }`}
    >
      <span className="mt-px">{toast.kind === "err" ? "!" : "OK"}</span>
      <div className="flex-1">{toast.message}</div>
      <button className="opacity-50 hover:opacity-100" onClick={onDismiss} aria-label="Dismiss notification">
        Close
      </button>
    </div>
  );
}

export function LoadingRows({ rows = 3 }) {
  return (
    <div className="p-5 space-y-2.5">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skeleton h-4" style={{ width: `${90 - i * 12}%` }} />
      ))}
    </div>
  );
}
