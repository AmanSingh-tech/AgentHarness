import React, { useState } from "react";
import { evidence } from "../api.js";

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
    <span title={title} className={`inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 font-mono text-[11px] font-medium uppercase tracking-wide ${className}`}>
      {children}
    </span>
  );
}

export function Card({ title, actions, children, className = "" }) {
  return (
    <section className={`rounded-2xl border border-slate-200 bg-surface ${className}`}>
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 border-b border-slate-200 px-5 py-3.5">
          <h2 className="text-[15px] font-medium tracking-tight text-slate-900">{title}</h2>
          <div className="flex flex-wrap items-center gap-2">{actions}</div>
        </header>
      )}
      <div className="overflow-x-auto p-5">{children}</div>
    </section>
  );
}

export function Button({ children, onClick, disabled, kind = "primary", type = "button" }) {
  const styles = {
    primary: "bg-accent text-white hover:bg-accent-strong",
    secondary: "border border-slate-300 bg-transparent text-slate-900 hover:border-slate-400 hover:bg-slate-100",
    approve: "bg-emerald-600 text-white hover:bg-emerald-500",
    reject: "bg-rose-600 text-white hover:bg-rose-500",
  };
  return (
    <button type={type} onClick={onClick} disabled={disabled}
      className={`press inline-flex h-9 items-center justify-center whitespace-nowrap rounded-full px-4 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-40 ${styles[kind]}`}>
      {children}
    </button>
  );
}

export function Json({ value }) {
  return (
    <pre className="max-h-48 overflow-auto rounded-lg bg-slate-50 p-3 font-mono text-xs leading-relaxed text-slate-700">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

export function Empty({ children }) {
  return <p className="py-8 text-center font-mono text-xs uppercase tracking-wide text-slate-400">{children}</p>;
}

export function pct(v) {
  if (v === null || v === undefined) return "n/a";
  return typeof v === "number" && v <= 1 && !Number.isInteger(v) ? `${Math.round(v * 100)}%` : String(v);
}

// A small Markdown renderer for task tickets and design notes: headings, paragraphs, bullet and numbered
// lists, **bold** and `code`. Text is rendered as React text (no HTML injection).
function inline(text) {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).filter(Boolean).map((part, i) => {
    if (part.startsWith("**")) return <strong key={i} className="font-semibold text-slate-900">{part.slice(2, -2)}</strong>;
    if (part.startsWith("`")) return <code key={i} className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[0.85em]">{part.slice(1, -1)}</code>;
    return part;
  });
}

export function Markdown({ text, className = "" }) {
  const blocks = [];
  let list = null;
  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    const bullet = line.match(/^\s*(?:[-*]|\d+\.)\s+(.*)$/);
    if (bullet) {
      if (!list) { list = { ordered: /^\s*\d/.test(line), items: [] }; blocks.push(list); }
      list.items.push(bullet[1]);
      continue;
    }
    list = null;
    if (!line.trim()) continue;
    const h = line.match(/^(#{1,3})\s+(.*)$/);
    blocks.push(h ? { heading: h[1].length, text: h[2] } : { text: line });
  }
  return (
    <div className={`space-y-2.5 text-sm leading-relaxed text-slate-700 ${className}`}>
      {blocks.map((b, i) => b.items ? (
        b.ordered
          ? <ol key={i} className="list-decimal space-y-1 pl-5">{b.items.map((t, j) => <li key={j}>{inline(t)}</li>)}</ol>
          : <ul key={i} className="list-disc space-y-1 pl-5">{b.items.map((t, j) => <li key={j}>{inline(t)}</li>)}</ul>
      ) : b.heading === 1 ? <h3 key={i} className="text-lg font-medium tracking-tight text-slate-900">{inline(b.text)}</h3>
        : b.heading ? <h4 key={i} className="label pt-2">{inline(b.text)}</h4>
        : <p key={i}>{inline(b.text)}</p>)}
    </div>
  );
}

export function agentLabel(agent, model) {
  const names = { "mcp_client:claude-code": "Claude Code", "bench:solution": "Reference solution", "scripted:null": "Do-nothing agent" };
  const name = names[agent] || agent;
  return model && model !== "default" ? `${name} · ${model[0].toUpperCase()}${model.slice(1)}` : name;
}

// Download a run's evidence: the Markdown report for auditors, the same as JSON, and the raw trace.
export function EvidenceDownloads({ runId }) {
  const [error, setError] = useState(null);
  const save = async (format) => {
    setError(null);
    try {
      const data = await evidence(runId, format);
      const md = format === "md";
      const blob = new Blob([md ? data : JSON.stringify(data, null, 2)], { type: md ? "text/markdown" : "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${format === "trace" ? "trace" : "evidence"}-${runId}.${md ? "md" : "json"}`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    } catch (e) {
      setError(e.message);
    }
  };
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button onClick={() => save("md")}>Download evidence report</Button>
      <Button kind="secondary" onClick={() => save("json")}>Evidence (JSON)</Button>
      <Button kind="secondary" onClick={() => save("trace")}>Full trace (JSON)</Button>
      {error && <span className="text-xs text-rose-700">{error}</span>}
    </div>
  );
}
