import React, { useEffect, useRef, useState } from "react";
import { get, post } from "../api.js";
import { Badge, Button, Card, Empty, OUTCOME_STYLE, RISK_STYLE } from "../components/ui.jsx";
import Trace from "../components/Trace.jsx";

const STAGES = [
  ["Data ingestion", "intake_agent", "Reads every open ticket and extracts order, amount and intent. Read-only."],
  ["Decision", "decision_agent", "Checks identity, ownership, refundable amount and history. Explains every decision. Read-only."],
  ["Action", "action_agent", "Refunds within limits, updates tickets, emails customers. Large refunds wait for a human."],
  ["Outcome report", "reporting_agent", "Re-checks every refund in the ledger and writes the report. Read-only."],
];

const STATUS_STYLE = {
  refunded: "bg-emerald-100 text-emerald-800", refused: "bg-slate-200 text-slate-800",
  escalated: "bg-amber-100 text-amber-900", awaiting_info: "bg-sky-100 text-sky-800",
  routed: "bg-slate-100 text-slate-700", stopped_by_controls: "bg-rose-100 text-rose-800", failed: "bg-rose-600 text-white",
};

export default function OpsPage() {
  const [opts, setOpts] = useState({ shield: true, manual_approvals: true });
  const [runId, setRunId] = useState(null);
  const [events, setEvents] = useState([]);
  const [run, setRun] = useState(null);
  const [controls, setControls] = useState(null);
  const [pending, setPending] = useState([]);
  const src = useRef(null);

  const start = async () => {
    setEvents([]); setRun(null); setControls(null);
    const { run_id } = await post("/ops/refunds", opts);
    setRunId(run_id);
  };

  useEffect(() => {
    if (!runId) return;
    const es = new EventSource(`/api/runs/${runId}/stream`);
    src.current = es;
    es.addEventListener("trace", (m) => setEvents((ev) => [...ev, JSON.parse(m.data)]));
    es.addEventListener("done", () => es.close());
    let alive = true;
    (async () => {
      while (alive) {
        const r = await get(`/runs/${runId}`).catch(() => null);
        if (r?.verdict) { setRun(r); setControls(await get(`/runs/${runId}/controls`)); return; }
        const p = await get("/approvals").catch(() => []);
        setPending(p.filter((a) => a.run_id === runId));
        await new Promise((res) => setTimeout(res, 700));
      }
    })();
    return () => { alive = false; es.close(); };
  }, [runId]);

  const resolve = async (id, action) => {
    await post(`/approvals/${id}/${action}`, { by: "human:dashboard" });
    setPending((p) => p.filter((a) => a.id !== id));
  };
  const report = run?.output?.artifacts?.report;
  const running = runId && !run;

  return (
    <div className="space-y-4">
      <Card title="RefundOps · Retail and Supply · customer refunds" actions={<>
        <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={opts.shield}
          onChange={(e) => setOpts({ ...opts, shield: e.target.checked })} /> AgentShield</label>
        <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={opts.manual_approvals}
          disabled={!opts.shield} onChange={(e) => setOpts({ ...opts, manual_approvals: e.target.checked })} /> I approve large refunds</label>
        <Button onClick={start} disabled={running}>{running ? "Working the inbox…" : "Work today's inbox"}</Button>
      </>}>
        <div className="grid gap-2 md:grid-cols-4">
          {STAGES.map(([title, agent, text], i) => (
            <div key={agent} className="rounded-md border border-slate-200 p-3">
              <div className="text-xs font-semibold uppercase text-slate-500">{i + 1}. {title}</div>
              <div className="mt-0.5 font-mono text-xs">{agent}</div>
              <p className="mt-1 text-xs text-slate-600">{text}</p>
              <p className="mt-1 text-xs text-slate-400">{events.filter((e) => e.kind === "tool_call" && e.payload.agent_id === agent).length} tool calls</p>
            </div>
          ))}
        </div>
        <p className="mt-3 text-xs text-slate-500">Every tool call goes through AgentShield: per-agent permissions, refund limits,
          verified-customer and duplicate-refund rules, injection detection, post-action ledger verification, a
          hash-chained audit log, and a human approval for refunds above ₹2,000.</p>
      </Card>

      {pending.length > 0 && (
        <Card title="Waiting for your decision" className="border-amber-300">
          {pending.map((a) => (
            <div key={a.id} className="flex flex-wrap items-center gap-2 text-sm">
              <Badge className={RISK_STYLE[a.decision.risk]}>{a.decision.risk}</Badge>
              <span className="font-mono">{a.agent_id} → {a.tool}</span>
              <span className="font-mono text-xs text-slate-500">{JSON.stringify(a.args)}</span>
              <span className="text-slate-700">{a.decision.reason}</span>
              <span className="ml-auto flex gap-2">
                <Button kind="approve" onClick={() => resolve(a.id, "approve")}>Approve</Button>
                <Button kind="reject" onClick={() => resolve(a.id, "reject")}>Reject</Button>
              </span>
            </div>
          ))}
        </Card>
      )}

      {report && (
        <Card title="Outcome report" actions={run?.verdict && <>
          <span className="text-xs text-slate-500">independent check of the world state:</span>
          <Badge className={OUTCOME_STYLE[run.verdict.outcome]}>{run.verdict.outcome}</Badge></>}>
          <Summary s={report.summary} />
          <table className="mt-3 w-full text-sm">
            <thead><tr className="text-left text-xs text-slate-500">
              <th>Ticket</th><th>Order</th><th>Requested</th><th>Decision</th><th>Status</th><th>Ledger</th><th>Why</th></tr></thead>
            <tbody>
              {report.items.map((i) => (
                <tr key={i.ticket_id} className="border-t border-slate-100 align-top">
                  <td className="py-1.5 font-mono">{i.ticket_id}</td><td className="font-mono">{i.order_id}</td>
                  <td>{i.requested_inr != null ? `₹${i.requested_inr.toLocaleString("en-IN")}` : ""}</td>
                  <td><Badge>{i.decision}</Badge></td>
                  <td><Badge className={STATUS_STYLE[i.status]}>{i.status.replaceAll("_", " ")}</Badge><div className="text-xs text-slate-500">{i.action}</div></td>
                  <td>{i.verified === true ? "✅ confirmed" : i.verified === false ? "❌ not found" : ""}</td>
                  <td className="text-xs text-slate-600">{i.reasons.join(" ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {controls && <Controls c={controls} />}

      <Card title={runId ? `Live activity · run ${runId}` : "Live activity"}>
        {events.length === 0 ? <Empty>Press "Work today's inbox".</Empty> : <Trace events={events} />}
      </Card>
    </div>
  );
}

export function Summary({ s }) {
  const tiles = [
    ["Tickets", s.tickets], ["Refunded", `${s.refunded} · ₹${s.refunded_inr_verified.toLocaleString("en-IN")}`],
    ["Refused", s.refused], ["Escalated to people", s.escalated], ["Waiting for customer", s.awaiting_info],
    ["Routed", s.routed], ["Stopped by controls", s.stopped_by_controls],
  ];
  return (
    <div className="grid grid-cols-2 gap-2 md:grid-cols-7">
      {tiles.map(([k, v]) => (
        <div key={k} className="rounded-md bg-slate-50 p-2">
          <div className="text-[11px] uppercase text-slate-500">{k}</div><div className="text-lg font-semibold">{v}</div>
        </div>
      ))}
    </div>
  );
}

export function Controls({ c }) {
  const rows = [
    ["Agents (own identity, least privilege)", c.agents.join(", ")],
    ["Human approvals", `${c.approvals_granted} granted, ${c.approvals_rejected} rejected` +
      (c.approvals.length ? ` (${c.approvals.map((a) => `${a.tool} by ${a.by}`).join("; ")})` : "")],
    ["Actions blocked by policy", `${c.blocks}${c.blocked_rules.length ? ` (${c.blocked_rules.join(", ")})` : ""}`],
    ["Prompt injections detected", c.injections],
    ["Post-action verifications", `${c.verifications_passed} passed, ${c.verifications_failed} failed`],
    ["Audit log", `${c.audit_events} events, hash chain ${c.audit_ok ? "verified ✅" : "NOT verified ❌"}`],
  ];
  return (
    <Card title="Responsible-AI controls in this run">
      <dl className="grid gap-x-6 gap-y-1 text-sm md:grid-cols-2">
        {rows.map(([k, v]) => (<React.Fragment key={k}><dt className="text-slate-500">{k}</dt><dd>{v}</dd></React.Fragment>))}
      </dl>
    </Card>
  );
}
