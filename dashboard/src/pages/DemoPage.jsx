import React, { useState } from "react";
import { followJob, post } from "../api.js";
import { Badge, Button, Card, Empty, OUTCOME_STYLE, pct } from "../components/ui.jsx";

export default function DemoPage() {
  const [job, setJob] = useState(null);
  const start = async () => {
    setJob({ status: "running", steps: [] });
    const { job_id } = await post("/demo");
    await followJob(job_id, setJob);
  };
  const steps = job?.steps || [];
  return (
    <div className="space-y-4">
      <Card title="Demo script" actions={<Button onClick={start} disabled={job?.status === "running"}>
        {job?.status === "running" ? "Running…" : "Run the demo"}</Button>}>
        <p className="text-sm text-slate-600">Normal refund → timeout after commit → false success → prompt injection →
          exfiltration sequence → regression and agent v2. Every step runs real scenarios through the gateway, AgentShield
          and the verifier. Open the run ids on the Live run page for full traces.</p>
        {job?.status === "failed" && <p className="mt-2 text-sm text-rose-600">{job.error}</p>}
      </Card>
      {steps.length === 0 && job?.status !== "running" && <Card><Empty>Press "Run the demo".</Empty></Card>}
      {steps.map((s) => (
        <Card key={s.number} title={`Step ${s.number}: ${s.title}`} actions={
          <Badge className={s.ok ? "bg-emerald-600 text-white" : "bg-rose-600 text-white"}>{s.ok ? "as expected" : "unexpected"}</Badge>}>
          <p className="text-sm text-slate-600">{s.expectation}</p>
          <ul className="mt-2 space-y-2">
            {s.runs.map((r) => (
              <li key={r.run_id} className="rounded border border-slate-200 p-2 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs">{r.harness}</span>
                  <Badge>shield {r.shield ? "on" : "off"}</Badge>
                  <Badge className={OUTCOME_STYLE[r.outcome]}>{r.outcome}</Badge>
                  <span className="text-xs text-slate-500">claimed {r.claim}{r.refunds !== null ? ` · refunds in ledger: ${r.refunds}` : ""} · emails: {r.emails}</span>
                  <span className="ml-auto font-mono text-xs text-slate-400">{r.run_id}</span>
                </div>
                {r.stops.map((x, i) => <p key={i} className="mt-1 text-xs text-slate-600">• {x}</p>)}
              </li>
            ))}
          </ul>
          {s.notes.map((n, i) => <p key={i} className="mt-1 font-mono text-xs text-slate-500">{n}</p>)}
          {s.table.length > 0 && (
            <table className="mt-2 w-full text-sm">
              <thead><tr className="label text-left [&>th]:pb-2 [&>th]:pr-3 [&>th]:font-normal"><th>Outcome (shield on)</th><th>v1</th><th>v2</th></tr></thead>
              <tbody>
                {s.table.map((r) => (
                  <tr key={r.metric} className="border-t border-slate-100">
                    <td className="py-1">{r.metric}</td><td>{pct(r["demo-v1"])}</td>
                    <td className={r.better === true ? "font-semibold text-emerald-700" : ""}>{pct(r["demo-v2"])}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      ))}
    </div>
  );
}
