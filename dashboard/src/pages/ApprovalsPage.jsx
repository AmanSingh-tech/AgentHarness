import React, { useEffect, useState } from "react";
import { get, post } from "../api.js";
import { Badge, Button, Card, Empty, Json, RISK_STYLE } from "../components/ui.jsx";
import { Chain } from "../components/Evidence.jsx";

export default function ApprovalsPage() {
  const [pending, setPending] = useState([]);
  const [history, setHistory] = useState([]);
  const load = () => {
    get("/approvals").then(setPending).catch(() => {});
    get("/approvals", { status: "" }).then((h) => setHistory(h.filter((a) => a.status !== "pending").reverse().slice(0, 20))).catch(() => {});
  };
  useEffect(() => { load(); const t = setInterval(load, 1000); return () => clearInterval(t); }, []);
  const resolve = async (id, action) => { await post(`/approvals/${id}/${action}`, { by: "human:dashboard" }); load(); };

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title={`Waiting for a decision (${pending.length})`}>
        {pending.length === 0 ? <Empty>Nothing is waiting. Start a run with "Hold risky calls for my approval" ticked.</Empty> : (
          <ul className="space-y-3">
            {pending.map((a) => (
              <li key={a.id} className="rounded-md border border-amber-300 bg-amber-50/50 p-3">
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="font-mono font-semibold">{a.tool}</span>
                  <Badge className={RISK_STYLE[a.decision.risk]}>{a.decision.risk}</Badge>
                  <span className="font-mono text-xs text-slate-500">{a.decision.rule_id}</span>
                </div>
                <p className="mt-1 text-sm">{a.decision.reason}</p>
                <Chain evidence={a.decision.evidence} />
                <div className="mt-2"><Json value={a.args} /></div>
                <div className="mt-2 flex gap-2">
                  <Button kind="approve" onClick={() => resolve(a.id, "approve")}>Approve</Button>
                  <Button kind="reject" onClick={() => resolve(a.id, "reject")}>Reject</Button>
                  <span className="self-center text-xs text-slate-500">run {a.run_id}</span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card title="Recently resolved">
        {history.length === 0 ? <Empty>No decisions yet.</Empty> : (
          <ul className="divide-y divide-slate-100 text-sm">
            {history.map((a) => (
              <li key={a.id} className="flex items-center justify-between gap-2 py-1.5">
                <span><span className="font-mono">{a.tool}</span> <span className="text-xs text-slate-500">{a.decision.rule_id}</span></span>
                <span className="text-xs">
                  <Badge className={a.status === "approved" ? "bg-emerald-100 text-emerald-800" : "bg-rose-100 text-rose-800"}>{a.status}</Badge>{" "}
                  {a.resolved_by}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
