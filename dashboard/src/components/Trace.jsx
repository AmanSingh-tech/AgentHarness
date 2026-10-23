import React, { useState } from "react";
import { Badge, DECISION_STYLE, Json, RISK_STYLE } from "./ui.jsx";
import { Chain, Votes } from "./Evidence.jsx";

const AGENT_STYLE = {
  intake_agent: "bg-sky-100 text-sky-800",
  decision_agent: "bg-indigo-100 text-indigo-800",
  action_agent: "bg-amber-100 text-amber-900",
  reporting_agent: "bg-emerald-100 text-emerald-800",
};

// Group the flat event stream into one row per tool call: call -> decision -> approval -> fault -> result.
export function groupTrace(events) {
  const calls = new Map();
  const runEvents = [];
  for (const e of events) {
    if (!e.call_id) { runEvents.push(e); continue; }
    if (!calls.has(e.call_id)) calls.set(e.call_id, { call_id: e.call_id, events: [] });
    const c = calls.get(e.call_id);
    c.events.push(e);
    if (e.kind === "tool_call") c.call = e.payload;
    if (e.kind === "decision") c.decision = e.payload;
    if (e.kind === "approval_resolved") c.approval = e.payload.approval;
    if (e.kind === "approval_requested") c.approvalPending = c.approvalPending || e.payload.approval;
    if (e.kind === "fault_injected") c.fault = e.payload;
    if (e.kind === "injection_detected") c.injection = e.payload;
    if (e.kind === "taint_labelled") c.taint = e.payload;
    if (e.kind === "tool_result") c.result = e.payload;
  }
  return { calls: [...calls.values()].filter((c) => c.call), runEvents };
}

export default function Trace({ events }) {
  const { calls, runEvents } = groupTrace(events);
  const taskInjection = runEvents.find((e) => e.kind === "injection_detected");
  return (
    <ol className="space-y-2">
      {taskInjection && (
        <li className="rounded-md border border-amber-300 bg-amber-50 p-2 text-sm">
          Task text flagged as a possible prompt injection: {taskInjection.payload.findings.map((f) => f.pattern_id).join(", ")}
        </li>
      )}
      {calls.map((c) => <CallRow key={c.call_id} c={c} />)}
    </ol>
  );
}

function CallRow({ c }) {
  const [open, setOpen] = useState(false);
  const d = c.decision;
  const blocked = c.result && !c.result.ok && ["BLOCKED", "APPROVAL_REJECTED", "APPROVAL_TIMEOUT"].includes(c.result.error?.code);
  const border = blocked ? "border-rose-300 bg-rose-50/40" : c.fault ? "border-violet-300 bg-violet-50/40" : "border-slate-200 bg-surface";
  return (
    <li className={`enter rounded-xl border p-3 ${border}`}>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-mono text-xs text-slate-400">#{c.call.seq}</span>
        {c.call.agent_id && <Badge className={AGENT_STYLE[c.call.agent_id] || "bg-slate-100 text-slate-600"}>{c.call.agent_id}</Badge>}
        <button onClick={() => setOpen(!open)} className="font-mono font-semibold hover:underline">{c.call.tool}</button>
        <span className="truncate font-mono text-xs text-slate-500" style={{ maxWidth: "28rem" }}>{JSON.stringify(c.call.args)}</span>
        {d && <Badge className={DECISION_STYLE[d.type]}>{d.type}</Badge>}
        {d && <Badge className={RISK_STYLE[d.risk]}>{d.risk}</Badge>}
        {c.approval && <Badge className={c.approval.status === "approved" ? "bg-emerald-100 text-emerald-800" : "bg-rose-100 text-rose-800"}>
          approval {c.approval.status} · {c.approval.resolved_by}</Badge>}
        {!c.approval && c.approvalPending && <Badge className="bg-amber-400 text-white">waiting for approval</Badge>}
        {c.fault && <Badge className="bg-violet-600 text-white">fault: {c.fault.fault}</Badge>}
        {c.injection && <Badge className="bg-amber-500 text-white">injection in output</Badge>}
        {c.taint && <Badge className="bg-rose-100 text-rose-800">labelled {c.taint.labels.join(", ")}</Badge>}
        {c.result && (c.result.ok
          ? <Badge className="bg-emerald-50 text-emerald-700">ok</Badge>
          : <Badge className="bg-slate-600 text-page">{c.result.error?.code}</Badge>)}
      </div>
      {d && d.type !== "ALLOW" && (
        <div className="mt-1.5 text-sm text-slate-700">
          <span className="font-mono text-xs text-slate-500">{d.rule_id}</span> · {d.reason}
          <Chain evidence={d.evidence} />
        </div>
      )}
      {c.result && !c.result.ok && !blocked && <div className="mt-1 text-xs text-slate-600">{c.result.error?.message}</div>}
      {open && (
        <div className="mt-2 grid gap-2 md:grid-cols-2">
          <div><div className="mb-1 text-xs font-medium text-slate-500">Result the agent saw</div><Json value={c.result} /></div>
          <div>
            <div className="mb-1 text-xs font-medium text-slate-500">All stage votes</div>
            <Votes votes={d?.evidence?.votes} />
            {c.fault && <><div className="mb-1 mt-2 text-xs font-medium text-slate-500">Fault</div><Json value={c.fault} /></>}
          </div>
        </div>
      )}
    </li>
  );
}
