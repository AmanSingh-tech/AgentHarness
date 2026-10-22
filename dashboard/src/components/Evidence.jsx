import React from "react";
import { Badge } from "./ui.jsx";

// The steps that led to a decision: a taint chain (source -> transform -> sink)
// or the call sequence an ordered pattern matched.
export function Chain({ evidence }) {
  if (!evidence) return null;
  const steps = evidence.chain || evidence.sequence;
  if (!steps || !steps.length) return null;
  const labels = evidence.match?.labels || [];
  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs">
      {steps.map((s, i) => {
        const last = i === steps.length - 1;
        const role = evidence.chain ? (i === 0 ? "source" : last ? "sink" : "transform") : last ? "this call" : "earlier";
        return (
          <React.Fragment key={i}>
            {i > 0 && <span className="text-slate-400">→</span>}
            <span className={`rounded border px-2 py-1 font-mono ${last ? "border-rose-300 bg-rose-50" : "border-slate-200 bg-white"}`}>
              <span className="text-slate-400">#{s.seq} </span>{s.tool}
              <span className="ml-1 text-[10px] uppercase text-slate-400">{role}</span>
            </span>
          </React.Fragment>
        );
      })}
      {labels.map((l) => <Badge key={l} className="bg-rose-100 text-rose-800">{l}</Badge>)}
      {evidence.match?.how && <span className="text-slate-500">matched by {evidence.match.how} ({evidence.match.form})</span>}
    </div>
  );
}

export function Votes({ votes }) {
  if (!votes?.length) return null;
  return (
    <ul className="mt-2 space-y-0.5 text-xs text-slate-500">
      {votes.map((v, i) => (
        <li key={i}><span className="font-mono">{v.stage}</span> · {v.type} · {v.rule_id} · {v.risk}: {v.reason}</li>
      ))}
    </ul>
  );
}
