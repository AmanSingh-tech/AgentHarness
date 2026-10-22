import React from "react";

export const OUTCOME_STYLE = {
  CORRECT_SUCCESS: "bg-emerald-100 text-emerald-800",
  CORRECT_FAILURE_REPORTED: "bg-sky-100 text-sky-800",
  INCORRECT_SUCCESS_CLAIM: "bg-rose-100 text-rose-800",
  INCORRECT_FAILURE_CLAIM: "bg-amber-100 text-amber-800",
  SILENT_FAILURE: "bg-amber-100 text-amber-800",
  UNSAFE_SIDE_EFFECT: "bg-rose-100 text-rose-800",
  POLICY_VIOLATION_ATTEMPTED: "bg-orange-100 text-orange-800",
};

export const RISK_STYLE = {
  LOW: "bg-slate-100 text-slate-700",
  MEDIUM: "bg-yellow-100 text-yellow-800",
  HIGH: "bg-orange-100 text-orange-800",
  CRITICAL: "bg-rose-600 text-white",
};

export const DECISION_STYLE = {
  ALLOW: "bg-emerald-50 text-emerald-700",
  ALLOW_WITH_REDACTION: "bg-teal-100 text-teal-800",
  REQUIRE_APPROVAL: "bg-amber-100 text-amber-800",
  BLOCK: "bg-rose-600 text-white",
};

export function Badge({ children, className = "bg-slate-100 text-slate-700", title }) {
  return (
    <span title={title} className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ${className}`}>
      {children}
    </span>
  );
}

export function Card({ title, actions, children, className = "" }) {
  return (
    <section className={`rounded-lg border border-slate-200 bg-white shadow-sm ${className}`}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-2 border-b border-slate-100 px-4 py-2.5">
          <h2 className="text-sm font-semibold text-slate-700">{title}</h2>
          <div className="flex items-center gap-2">{actions}</div>
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Button({ children, onClick, disabled, kind = "primary", type = "button" }) {
  const styles = {
    primary: "bg-slate-900 text-white hover:bg-slate-700",
    secondary: "border border-slate-300 bg-white text-slate-800 hover:bg-slate-50",
    approve: "bg-emerald-600 text-white hover:bg-emerald-700",
    reject: "bg-rose-600 text-white hover:bg-rose-700",
  };
  return (
    <button type={type} onClick={onClick} disabled={disabled}
      className={`rounded-md px-3 py-1.5 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-40 ${styles[kind]}`}>
      {children}
    </button>
  );
}

export function Json({ value }) {
  return (
    <pre className="max-h-48 overflow-auto rounded bg-slate-50 p-2 font-mono text-xs leading-relaxed text-slate-700">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

export function Empty({ children }) {
  return <p className="py-6 text-center text-sm text-slate-400">{children}</p>;
}

export function pct(v) {
  if (v === null || v === undefined) return "n/a";
  return typeof v === "number" && v <= 1 && !Number.isInteger(v) ? `${Math.round(v * 100)}%` : String(v);
}
