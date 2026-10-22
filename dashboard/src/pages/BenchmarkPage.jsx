import React, { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { followJob, get, post } from "../api.js";
import { Button, Card, Empty, pct } from "../components/ui.jsx";

const SERIES = [
  ["Task success rate", "#0f766e", true],
  ["Runs with a duplicate refund", "#e11d48", false],
  ["Incorrect success claims", "#f59e0b", false],
  ["Runs with an unsafe side effect", "#7c3aed", false],
];

export default function BenchmarkPage() {
  const [reports, setReports] = useState([]);
  const [idx, setIdx] = useState(0);
  const [attempts, setAttempts] = useState(1);
  const [job, setJob] = useState(null);
  const [sets, setSets] = useState([]);
  const [pair, setPair] = useState(["", ""]);
  const [diff, setDiff] = useState(null);

  const load = () => { get("/benchmarks").then(setReports); get("/run-sets").then(setSets); };
  useEffect(load, []);
  const run = async () => {
    const { job_id } = await post("/benchmarks", { attempts });
    await followJob(job_id, setJob, 1500);
    setIdx(0); load();
  };
  const report = reports[idx];

  return (
    <div className="space-y-4">
      <Card title="MVP benchmark: agent v1 vs v2, AgentShield off vs on" actions={<>
        <label className="text-xs text-slate-500">attempts
          <input type="number" min="1" max="5" value={attempts} onChange={(e) => setAttempts(+e.target.value)}
            className="ml-1 w-14 rounded border-slate-300 py-0.5 text-xs" /></label>
        <Button onClick={run} disabled={job?.status === "running"}>{job?.status === "running" ? "Running…" : "Run benchmark"}</Button>
      </>}>
        {job?.status === "failed" && <p className="mb-2 text-sm text-rose-600">{job.error}</p>}
        {!report ? <Empty>No report yet. Run the benchmark (about 20 s per attempt).</Empty> : <Report report={report} />}
        {reports.length > 1 && (
          <select className="mt-3 rounded border-slate-300 text-xs" value={idx} onChange={(e) => setIdx(+e.target.value)}>
            {reports.map((r, i) => <option key={r.created} value={i}>{r.created}</option>)}
          </select>
        )}
      </Card>
      <Card title="Compare any two run sets">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          {[0, 1].map((k) => (
            <select key={k} className="rounded border-slate-300 text-xs" value={pair[k]}
              onChange={(e) => setPair(k ? [pair[0], e.target.value] : [e.target.value, pair[1]])}>
              <option value="">{k ? "B" : "A"}…</option>
              {sets.map((s) => <option key={s.name} value={s.name}>{s.name} ({s.runs})</option>)}
            </select>
          ))}
          <Button kind="secondary" disabled={!pair[0] || !pair[1]}
            onClick={async () => setDiff(await get("/compare", { a: pair[0], b: pair[1] }))}>Compare</Button>
        </div>
        {diff && (
          <table className="mt-3 w-full text-sm">
            <thead><tr className="text-left text-xs text-slate-500"><th>Outcome</th><th>A</th><th>B</th><th>Change</th></tr></thead>
            <tbody>
              {diff.map((r) => (
                <tr key={r.metric} className="border-t border-slate-100">
                  <td className="py-1">{r.metric}</td><td>{pct(r[pair[0]])}</td><td>{pct(r[pair[1]])}</td>
                  <td className={r.better === true ? "text-emerald-700" : r.better === false ? "text-rose-700" : ""}>
                    {r.delta === null ? "n/a" : (r.delta > 0 ? "+" : "") + pct(r.delta)}
                    {r.better === true ? " better" : r.better === false ? " worse" : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}

function Report({ report }) {
  const sets = Object.values(report.run_sets);
  const label = (s) => `${s.agent.split(":").pop()} · shield ${s.shield ? "on" : "off"}`;
  const metrics = Object.keys(sets[0].headline);
  const chart = sets.map((s) => ({ name: label(s), ...Object.fromEntries(SERIES.map(([m, , rate]) =>
    [m, rate ? Math.round((s.headline[m] ?? 0) * 100) : s.headline[m]])) }));
  return (
    <div className="space-y-4">
      <p className="text-xs text-slate-500">{report.scenarios.length} scenarios ({report.regression_scenarios} regression) × {report.attempts} attempt(s) · {report.created}</p>
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="h-64">
          <ResponsiveContainer>
            <BarChart data={chart}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="name" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} unit="%" domain={[0, 100]} />
              <Tooltip /><Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar dataKey="Task success rate" fill="#0f766e" />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="h-64">
          <ResponsiveContainer>
            <BarChart data={chart}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="name" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
              <Tooltip /><Legend wrapperStyle={{ fontSize: 11 }} />
              {SERIES.slice(1).map(([m, color]) => <Bar key={m} dataKey={m} fill={color} />)}
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
      <table className="w-full text-sm">
        <thead><tr className="text-left text-xs text-slate-500"><th>Outcome</th>{sets.map((s) => <th key={label(s)}>{label(s)}</th>)}</tr></thead>
        <tbody>
          {metrics.map((m) => (
            <tr key={m} className="border-t border-slate-100">
              <td className="py-1">{m}</td>{sets.map((s) => <td key={label(s)}>{pct(s.headline[m])}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
