import React, { useEffect, useState } from "react";
import { get } from "../api.js";
import { Badge, Card, DECISION_STYLE, Empty, RISK_STYLE } from "../components/ui.jsx";
import { Chain } from "../components/Evidence.jsx";

const STAGE_LABEL = { policy: "permission / rule", taint: "data-flow sequence", pattern: "ordered sequence", injection: "injection" };

export default function BlocksPage() {
  const [blocks, setBlocks] = useState(null);
  const [filter, setFilter] = useState("all");
  useEffect(() => { get("/blocks", { limit_runs: 100 }).then(setBlocks); }, []);
  if (blocks === null) return <Card><Empty>Loading…</Empty></Card>;
  const stages = [...new Set(blocks.map((b) => b.stage))];
  const shown = blocks.filter((b) => filter === "all" || b.stage === filter);
  return (
    <Card title={`Blocked and held actions (${shown.length})`} actions={
      <select className="rounded border-slate-300 text-xs" value={filter} onChange={(e) => setFilter(e.target.value)}>
        <option value="all">all stages</option>
        {stages.map((s) => <option key={s} value={s}>{STAGE_LABEL[s] || s}</option>)}
      </select>}>
      {shown.length === 0 ? <Empty>No blocks yet. Try the naive or adversarial agent.</Empty> : (
        <ul className="space-y-2">
          {shown.map((b, i) => (
            <li key={i} className="rounded-md border border-slate-200 p-3">
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <Badge className={DECISION_STYLE[b.type]}>{b.type}</Badge>
                <Badge className={RISK_STYLE[b.risk]}>{b.risk}</Badge>
                <span className="font-mono font-semibold">{b.tool}</span>
                <span className="font-mono text-xs text-slate-500">{b.rule_id}</span>
                <Badge>{STAGE_LABEL[b.stage] || b.stage}</Badge>
                {b.approval && <Badge className={b.approval.status === "approved" ? "bg-emerald-100 text-emerald-800" : "bg-rose-100 text-rose-800"}>
                  {b.approval.status} by {b.approval.by}</Badge>}
                <span className="ml-auto text-xs text-slate-400">{b.scenario} · {b.harness}</span>
              </div>
              <p className="mt-1 text-sm text-slate-700">{b.reason}</p>
              <Chain evidence={b.evidence} />
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
