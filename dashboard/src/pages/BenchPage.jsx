import React, { useEffect, useMemo, useState } from "react";
import { get, post } from "../api.js";
import { Badge, Button, Card, Empty } from "../components/ui.jsx";

const AGENTS = [
  ["bench:solution", null, "Reference solution"],
  ["scripted:null", null, "Do-nothing agent"],
  ["mcp_client:claude-code", "haiku", "Claude Code · Haiku"],
  ["mcp_client:claude-code", "sonnet", "Claude Code · Sonnet"],
  ["mcp_client:claude-code", "opus", "Claude Code · Opus"],
];
const KIND_STYLE = { goal: "bg-sky-100 text-sky-800", trap: "bg-violet-100 text-violet-800", harm: "bg-rose-100 text-rose-800" };
const pct = (x) => `${Math.round((x || 0) * 100)}%`;

export default function BenchPage() {
  const [tasks, setTasks] = useState([]);
  const [board, setBoard] = useState(null);
  const [selected, setSelected] = useState(null);

  const loadBoard = () => get("/bench/leaderboard").then(setBoard).catch(() => setBoard({ leaderboard: [], most_missed: [] }));
  useEffect(() => { get("/bench/tasks").then((t) => { setTasks(t); setSelected((s) => s || t[0]?.id); }); loadBoard(); }, []);

  const byCategory = useMemo(() => {
    const m = {};
    tasks.forEach((t) => { (m[t.category] = m[t.category] || []).push(t); });
    return m;
  }, [tasks]);

  return (
    <div className="space-y-4">
      <Card title="GuardBench" actions={<span className="text-xs text-slate-500">{tasks.length} enterprise tasks · hidden checks · run through AgentShield</span>}>
        <p className="text-sm text-slate-600">
          Each task is a short ticket in a seeded multi-system environment (service desk, identity, workspace, EDR, firewall, payments and more).
          Hidden checks grade the end state: <Badge className={KIND_STYLE.goal}>goal</Badge> the work asked for,{" "}
          <Badge className={KIND_STYLE.trap}>trap</Badge> what agents usually miss, <Badge className={KIND_STYLE.harm}>harm</Badge> damage that must not happen.
          A run is solved only when every check passes.
        </p>
      </Card>

      <Leaderboard board={board} onRefresh={loadBoard} />

      <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
        <Card title="Tasks">
          <div className="max-h-[640px] space-y-3 overflow-y-auto">
            {Object.entries(byCategory).map(([cat, list]) => (
              <div key={cat}>
                <div className="text-[11px] font-semibold uppercase text-slate-400">{cat}</div>
                {list.map((t) => (
                  <button key={t.id} onClick={() => setSelected(t.id)}
                    className={`mt-1 block w-full rounded-md px-2 py-1.5 text-left text-sm ${selected === t.id ? "bg-slate-900 text-white" : "hover:bg-slate-100"}`}>
                    <span className="font-mono text-xs">{t.id}</span> <span className="text-xs opacity-80">{t.title}</span>
                  </button>
                ))}
              </div>
            ))}
          </div>
        </Card>
        {selected ? <TaskDetail id={selected} onRan={loadBoard} /> : <Card><Empty>Pick a task.</Empty></Card>}
      </div>
    </div>
  );
}

function Leaderboard({ board, onRefresh }) {
  const rows = board?.leaderboard || [];
  return (
    <Card title="Leaderboard" actions={<Button kind="secondary" onClick={onRefresh}>Refresh</Button>}>
      {rows.length === 0 ? <Empty>No bench runs yet. Run a task below, or `agentguard bench sweep -c configs/bench/smoke.yaml`.</Empty> : (
        <table className="w-full text-sm">
          <thead><tr className="text-left text-xs text-slate-500">
            <th>Sweep</th><th>Agent</th><th>Model</th><th>Shield</th><th>Runs</th><th>Solved</th><th>pass^k</th><th>Mean score</th><th>Harm</th><th>Unearned success</th><th>Blocks</th><th>Cost</th>
          </tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-t border-slate-100">
                <td className="py-1.5 font-mono text-xs">{r.sweep}</td><td className="font-mono text-xs">{r.agent}</td><td>{r.model}</td>
                <td>{r.shield ? <Badge className="bg-emerald-100 text-emerald-800">on</Badge> : <Badge>off</Badge>}</td>
                <td>{r.runs}</td><td className="font-semibold">{pct(r.solve_rate)}</td><td>{pct(r.pass_k_rate)}</td>
                <td>{r.mean_score.toFixed(2)}</td><td className={r.harm_rate ? "text-rose-700" : ""}>{pct(r.harm_rate)}</td>
                <td>{r.unearned_success_claims}</td><td>{r.shield ? r.blocks : "–"}</td><td>${r.cost_usd.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {board?.most_missed?.length > 0 && (
        <details className="mt-3 text-sm">
          <summary className="cursor-pointer text-slate-600">Most-missed checks</summary>
          <ul className="mt-2 space-y-1">
            {board.most_missed.slice(0, 15).map((m, i) => (
              <li key={i}><Badge className={KIND_STYLE[m.kind]}>{m.kind}</Badge> <span className="font-mono text-xs">{m.task}</span> {m.desc} <span className="text-slate-400">×{m.misses}</span></li>
            ))}
          </ul>
        </details>
      )}
    </Card>
  );
}

function TaskDetail({ id, onRan }) {
  const [task, setTask] = useState(null);
  const [reveal, setReveal] = useState(false);
  const [agent, setAgent] = useState(0);
  const [shield, setShield] = useState(true);
  const [run, setRun] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { setTask(null); setRun(null); setReveal(false); get(`/bench/tasks/${id}`).then(setTask); }, [id]);

  const start = async () => {
    const [harness, model] = AGENTS[agent];
    setBusy(true); setRun(null);
    const { run_id } = await post("/bench/runs", { task: id, harness, model, shield });
    for (;;) {
      const r = await get(`/runs/${run_id}`).catch(() => null);
      if (r?.verdict) { setRun(r); break; }
      await new Promise((res) => setTimeout(res, 1000));
    }
    setBusy(false); onRan();
  };

  if (!task) return <Card><Empty>Loading…</Empty></Card>;
  const v = run?.verdict;
  const checks = (v?.checks || []).filter((c) => c.kind.startsWith("bench:"));
  return (
    <div className="space-y-4">
      <Card title={`${task.id} · ${task.title}`} actions={<>
        <Badge>{task.category}</Badge><Badge>{task.difficulty}</Badge>
        <span className="text-xs text-slate-500">{task.checks.length} checks ({task.goal} goal / {task.trap} trap / {task.harm} harm)</span>
      </>}>
        <div className="text-xs uppercase text-slate-400">What the agent sees · systems: {task.systems.join(", ")}</div>
        <pre className="mt-1 whitespace-pre-wrap rounded-md bg-slate-50 p-3 text-sm">{task.instruction}</pre>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <select className="rounded border-slate-300 py-1 text-sm" value={agent} onChange={(e) => setAgent(Number(e.target.value))} disabled={busy}>
            {AGENTS.map(([, , label], i) => <option key={i} value={i}>{label}</option>)}
          </select>
          <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={shield} onChange={(e) => setShield(e.target.checked)} disabled={busy} /> AgentShield</label>
          <Button onClick={start} disabled={busy}>{busy ? "Running…" : "Run task"}</Button>
          <Button kind="secondary" onClick={() => setReveal(!reveal)}>{reveal ? "Hide" : "Reveal"} design note and hidden checks</Button>
        </div>
      </Card>

      {v && (
        <Card title="Result" actions={<>
          <Badge className={v.reward ? "bg-emerald-100 text-emerald-800" : "bg-rose-100 text-rose-800"}>{v.reward ? "SOLVED" : "NOT SOLVED"}</Badge>
          <span className="text-sm">score {pct(v.score)}</span>
          {v.harm && <Badge className="bg-rose-600 text-white">HARM</Badge>}
          <span className="font-mono text-xs text-slate-500">{run.id}</span>
        </>}>
          {["goal", "trap", "harm"].map((kind) => (
            <div key={kind} className="mb-2">
              <div className="text-[11px] font-semibold uppercase text-slate-400">{kind}</div>
              {checks.filter((c) => c.kind === `bench:${kind}`).map((c) => (
                <div key={c.spec.id} className="flex items-start gap-2 text-sm">
                  <span>{c.ok ? "✅" : "❌"}</span>
                  <span>{c.spec.desc}{!c.ok && c.note && <span className="text-xs text-slate-500"> — {c.note}</span>}</span>
                </div>
              ))}
            </div>
          ))}
          <p className="mt-2 text-xs text-slate-500">{run.output?.final_message}</p>
        </Card>
      )}

      {reveal && (
        <Card title="Design note">
          <pre className="whitespace-pre-wrap text-sm text-slate-700">{task.readme}</pre>
          <div className="mt-3 space-y-1">
            {task.checks.map((c) => (
              <div key={c.id} className="text-sm"><Badge className={KIND_STYLE[c.kind]}>{c.kind}</Badge> <span className="font-mono text-xs">{c.id}</span> {c.desc}</div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
