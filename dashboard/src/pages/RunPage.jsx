import React, { useEffect, useRef, useState } from "react";
import { DEMO, get, post, streamRun } from "../api.js";
import { Badge, Button, Card, Empty, OUTCOME_STYLE } from "../components/ui.jsx";
import Trace from "../components/Trace.jsx";
import Verdict from "../components/Verdict.jsx";

export default function RunPage() {
  const [scenarios, setScenarios] = useState([]);
  const [harnesses, setHarnesses] = useState([]);
  const [form, setForm] = useState({ scenario: "normal_refund", harness: "scripted:oracle", shield: true, manual_approvals: false });
  const [runs, setRuns] = useState([]);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    get("/scenarios").then(setScenarios);
    // The recorded demo has the scripted agents for every scenario.
    get("/harnesses").then((h) => setHarnesses(DEMO ? h.filter((x) => x.startsWith("scripted:") && x !== "scripted:refuser") : h));
  }, []);
  useEffect(() => {
    const load = () => get("/runs", { limit: 25 }).then(setRuns).catch(() => {});
    load();
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, []);

  const scenario = scenarios.find((s) => s.id === form.scenario);
  const start = async () => {
    setError(null);
    try {
      const { run_id } = await post("/runs", form);
      setSelected(run_id);
    } catch (e) { setError(String(e)); }
  };

  return (
    <div className="grid gap-4 lg:grid-cols-[22rem_1fr]">
      <div className="space-y-4">
        <Card title="Start a run">
          <div className="space-y-3 text-sm">
            <label className="block">
              <span className="text-xs font-medium text-slate-500">Scenario</span>
              <select className="mt-1 w-full rounded border-slate-300 text-sm" value={form.scenario}
                onChange={(e) => setForm({ ...form, scenario: e.target.value })}>
                {scenarios.map((s) => <option key={s.id} value={s.id}>{s.id}</option>)}
              </select>
            </label>
            {scenario && (
              <div className="rounded bg-slate-50 p-2 text-xs text-slate-600">
                <p>{scenario.task}</p>
                <div className="mt-1 flex flex-wrap gap-1">
                  {scenario.faults.map((f, i) => <Badge key={i} className="bg-violet-100 text-violet-800">{f.type} @ {f.tool}</Badge>)}
                  {scenario.tags.map((t) => <Badge key={t}>{t}</Badge>)}
                </div>
              </div>
            )}
            <label className="block">
              <span className="text-xs font-medium text-slate-500">Agent (harness)</span>
              <select className="mt-1 w-full rounded border-slate-300 text-sm" value={form.harness}
                onChange={(e) => setForm({ ...form, harness: e.target.value })}>
                {harnesses.map((h) => <option key={h}>{h}</option>)}
              </select>
            </label>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={form.shield} onChange={(e) => setForm({ ...form, shield: e.target.checked })} />
              AgentShield on
            </label>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={form.manual_approvals} disabled={!form.shield}
                onChange={(e) => setForm({ ...form, manual_approvals: e.target.checked })} />
              Hold risky calls for my approval
            </label>
            <Button onClick={start}>Run</Button>
            {error && <p className="text-xs text-rose-600">{error}</p>}
          </div>
        </Card>
        <Card title="Recent runs">
          {runs.length === 0 ? <Empty>No runs yet.</Empty> : (
            <ul className="max-h-[32rem] space-y-1 overflow-auto">
              {runs.map((r) => (
                <li key={r.id}>
                  <button onClick={() => setSelected(r.id)}
                    className={`w-full rounded px-2 py-1.5 text-left text-xs hover:bg-slate-50 ${selected === r.id ? "bg-slate-100" : ""}`}>
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium">{r.scenario}</span>
                      {r.outcome ? <Badge className={OUTCOME_STYLE[r.outcome]}>{r.outcome}</Badge> : <Badge>{r.status}</Badge>}
                    </div>
                    <div className="text-slate-500">{r.harness} · shield {r.shield ? "on" : "off"}</div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
      {selected ? <RunView key={selected} runId={selected} /> : <Card><Empty>Start a run or pick one to see its live trace and verdict.</Empty></Card>}
    </div>
  );
}

function RunView({ runId }) {
  const [events, setEvents] = useState([]);
  const [run, setRun] = useState(null);
  const [diagnosis, setDiagnosis] = useState(null);
  const [promotion, setPromotion] = useState(null);
  const [busy, setBusy] = useState(false);
  const done = useRef(false);

  useEffect(() => {
    const close = streamRun(runId, (e) => setEvents((ev) => [...ev, e]), () => { done.current = true; });
    let alive = true;
    const poll = async () => {
      while (alive) {
        const r = await get(`/runs/${runId}`).catch(() => null);
        if (r && alive) setRun(r);
        if (r?.verdict) return;
        await new Promise((res) => setTimeout(res, 600));
      }
    };
    poll();
    return () => { alive = false; close(); };
  }, [runId]);

  const act = async (fn) => { setBusy(true); try { await fn(); } finally { setBusy(false); } };
  return (
    <div className="space-y-4">
      <Card title={`Run ${runId}`} actions={run && <span className="text-xs text-slate-500">{run.scenario} · {run.harness} · shield {run.shield ? "on" : "off"}</span>}>
        {events.length === 0 ? <Empty>Waiting for the first event…</Empty> : <Trace events={events} />}
      </Card>
      {run?.verdict && (
        <Card title="Verdict (independent of what the agent says)" actions={<>
          <Button kind="secondary" disabled={busy} onClick={() => act(async () => setDiagnosis(await get(`/runs/${runId}/diagnosis`)))}>Diagnose</Button>
          <Button kind="secondary" disabled={busy} onClick={() => act(async () => setPromotion(await post(`/runs/${runId}/promote`)))}>Promote to regression</Button>
        </>}>
          <Verdict run={run} />
          {diagnosis && (
            <div className="mt-3 rounded-md border border-slate-200 bg-slate-50 p-3 text-sm">
              <div className="text-xs font-semibold uppercase text-slate-500">Diagnosis (vs the reference agent)</div>
              {diagnosis.summary.map((l, i) => <p key={i}>{l}</p>)}
            </div>
          )}
          {promotion && (
            <div className={`mt-3 rounded-md border p-3 text-sm ${promotion.accepted ? "border-emerald-300 bg-emerald-50" : "border-slate-200 bg-slate-50"}`}>
              <p><b>{promotion.accepted ? "New regression scenario" : "Not promoted"}:</b> {promotion.reason}</p>
              {promotion.accepted && <pre className="mt-2 max-h-64 overflow-auto rounded bg-surface p-2 font-mono text-xs">{promotion.yaml}</pre>}
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
