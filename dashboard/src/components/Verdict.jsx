import React from "react";
import { Badge, OUTCOME_STYLE } from "./ui.jsx";

const STATE_KINDS = ["ledger", "orders", "tickets", "outbox"];

export default function Verdict({ run }) {
  const v = run?.verdict;
  if (!v) return null;
  const claimText = run.output?.claimed_outcome
    ? JSON.stringify(run.output.claimed_outcome)
    : run.output?.final_message;
  return (
    <div className="space-y-3">
      {v.outcome === "INCORRECT_SUCCESS_CLAIM" && (
        <div className="rounded-md bg-rose-600 px-4 py-3 text-base font-semibold text-white">
          ❌ Agent incorrectly reported success
        </div>
      )}
      {v.outcome === "UNSAFE_SIDE_EFFECT" && (
        <div className="rounded-md bg-rose-600 px-4 py-3 text-base font-semibold text-white">⚠ Unsafe side effect in the world</div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Badge className={OUTCOME_STYLE[v.outcome]}>{v.outcome}</Badge>
        <Badge className={v.passed ? "bg-emerald-600 text-white" : "bg-slate-600 text-page"}>{v.passed ? "PASS" : "FAIL"}</Badge>
        <span className="text-xs text-slate-500">expected outcome: {v.task_outcome}</span>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-md border border-slate-200 p-3">
          <div className="text-xs font-semibold uppercase text-slate-500">What the agent claimed</div>
          <p className="mt-1 text-sm">{claimText}</p>
          <p className="mt-1 text-xs text-slate-500">parsed as <b>{v.claim.kind}</b> ({v.claim.source}: {v.claim.detail})</p>
        </div>
        <div className="rounded-md border border-slate-200 p-3">
          <div className="text-xs font-semibold uppercase text-slate-500">What the world shows (evidence)</div>
          <ul className="mt-1 space-y-1 text-sm">
            {v.checks.filter((c) => STATE_KINDS.includes(c.kind) || !c.ok).map((c, i) => (
              <li key={i} className="flex gap-2">
                <span>{c.ok ? "✅" : "❌"}</span>
                <span>
                  <span className="font-mono text-xs">{c.kind}</span> {fmtSpec(c.spec)}
                  {typeof c.expected === "number" && <> — expected {c.expected}, found {String(c.actual)}</>}
                  {c.note && !c.ok && <span className="text-xs text-slate-500"> ({c.note})</span>}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>
      <p className="text-sm text-slate-600">{v.summary}</p>
    </div>
  );
}

function fmtSpec(spec) {
  return Object.entries(spec).filter(([k]) => k !== "count").map(([k, v]) => `${k}=${v}`).join(", ");
}
