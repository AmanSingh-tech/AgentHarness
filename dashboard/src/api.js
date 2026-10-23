// Thin wrappers over the AgentGuard API (agentguard/server/app.py).
//
// Recorded demo mode (VITE_DEMO=1, used for the static deployment): the same calls are answered from
// recordings of real runs in public/demo/ (made by scripts/export_demo.py). Starting a run replays its
// recorded trace at its own pace; a replay pauses at a human approval until it is approved or rejected.

export const DEMO = import.meta.env.VITE_DEMO === "1";
const BASE = import.meta.env.BASE_URL;

export async function get(path, params) {
  if (DEMO) return demoGet(path, params);
  const qs = params ? "?" + new URLSearchParams(params) : "";
  const r = await fetch(`/api${path}${qs}`);
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

export async function post(path, body) {
  if (DEMO) return demoPost(path, body || {});
  const r = await fetch(`/api${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

// Poll a background job (/api/jobs/:id) until it finishes; onUpdate sees every snapshot.
export async function followJob(jobId, onUpdate, intervalMs = 700) {
  for (;;) {
    const job = await get(`/jobs/${jobId}`);
    onUpdate(job);
    if (job.status !== "running") return job;
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}

// Stream a run's trace: onEvent(traceEvent) for each event, onDone() at the end. Returns a closer.
export function streamRun(runId, onEvent, onDone) {
  if (DEMO) return demoStream(runId, onEvent, onDone);
  const es = new EventSource(`/api/runs/${runId}/stream`);
  es.addEventListener("trace", (m) => onEvent(JSON.parse(m.data)));
  es.addEventListener("done", () => { es.close(); onDone && onDone(); });
  return () => es.close();
}

// -- recorded demo ------------------------------------------------------------------------------------

let manifestPromise = null;
const files = new Map();
const replays = new Map(); // run id -> replay state

function manifest() {
  manifestPromise ||= fetch(`${BASE}demo/manifest.json`).then((r) => r.json());
  return manifestPromise;
}

async function file(name) {
  if (!files.has(name)) files.set(name, fetch(`${BASE}demo/${name}`).then((r) => r.json()));
  return files.get(name);
}

const unavailable = (what) => new Error(`${what} isn't part of the recorded demo. Run \`agentguard serve\` locally for the live version.`);

async function loadRun(runId) {
  const m = await manifest();
  if (!m.runs[runId]) throw unavailable(`Run ${runId}`);
  return file(m.runs[runId]);
}

async function demoGet(path, params) {
  const m = await manifest();
  const clean = params ? Object.fromEntries(Object.entries(params).map(([k, v]) => [k, String(v)])) : null;
  const key = path + (clean && Object.keys(clean).length ? "?" + Object.entries(clean).map(([k, v]) => `${k}=${v}`).join("&") : "");
  if (path === "/approvals") return pendingApprovals(clean);
  if (path.startsWith("/jobs/")) {
    const kind = path.split("/")[2];
    if (!m.jobs[kind]) throw unavailable("This job");
    return file(m.jobs[kind]);
  }
  const run = path.match(/^\/runs\/([^/]+)(?:\/(controls|diagnosis|trace))?$/);
  if (run) {
    const [, id, part] = run;
    const rep = replays.get(id);
    const rec = await loadRun(rep ? rep.source : id);
    if (part === "trace") return rec.trace;
    if (part) {
      if (!rec[part]) throw unavailable("This view");
      return rec[part];
    }
    // While a replay is still running, the run has no verdict yet (as in the live API).
    if (rep && !rep.done) return { ...rec.run, id, status: "running", verdict: null, output: null, outcome: null };
    return { ...rec.run, id };
  }
  if (m.get[key]) return file(m.get[key]);
  if (m.get[path]) return file(m.get[path]);
  throw unavailable(`GET ${key}`);
}

async function demoPost(path, body) {
  const m = await manifest();
  let source = null;
  let ops = path.match(/^\/ops\/(\w+)$/);
  if (ops) {
    source = m.start.ops[`${ops[1]}|${body.decider || "rules"}`];
    if (!source) throw unavailable(`${ops[1]} with decider ${body.decider}`);
    return { run_id: startReplay(source, { manual: body.manual_approvals !== false }) };
  }
  if (path === "/runs") {
    source = m.start.runs[`${body.scenario}|${body.harness}|${!!body.shield}`];
    if (!source) throw unavailable(`${body.harness} on ${body.scenario}`);
    return { run_id: startReplay(source, { manual: false }) };
  }
  if (path === "/bench/runs") {
    source = m.start.bench[`${body.task}|${body.harness}|${body.model || ""}|${!!body.shield}`];
    if (!source) throw unavailable(`${body.harness}${body.model ? " · " + body.model : ""} on ${body.task}${body.shield ? "" : " (shield off)"}`);
    return { run_id: startReplay(source, { manual: false }) };
  }
  const approval = path.match(/^\/approvals\/([^/]+)\/(approve|reject)$/);
  if (approval) return resolveApproval(approval[1], approval[2]);
  if (path === "/demo") return { job_id: "demo" };
  if (path === "/benchmarks") return { job_id: "benchmarks" };
  if (path === "/policies/validate") {
    const policy = await file(m.get["/policies"]);
    return body.text === policy.text ? m.policy_validate
      : { ok: false, problems: ["Editing and validating policies works in the live version (agentguard serve)."] };
  }
  if (/^\/runs\/[^/]+\/promote$/.test(path)) {
    return { accepted: false, reason: "Promoting a run writes a new scenario file, so it is only available in the live version (agentguard serve)." };
  }
  throw unavailable(`POST ${path}`);
}

let seq = 0;
function startReplay(source, { manual }) {
  const id = `${source}-replay${++seq}`;
  const rep = { source, manual, idx: 0, events: null, done: false, listeners: [], paused: null, timer: null };
  replays.set(id, rep);
  // Start right away: some pages only poll for the result and never open a stream.
  loadRun(source).then((rec) => { rep.events = rec.trace; step(id); });
  return id;
}

function demoStream(runId, onEvent, onDone) {
  const rep = replays.get(runId);
  if (!rep) {
    // An existing (non-replayed) recorded run: deliver its whole trace at once.
    let closed = false;
    loadRun(runId).then((rec) => { if (closed) return; rec.trace.forEach(onEvent); onDone && onDone(); });
    return () => { closed = true; };
  }
  const listener = { onEvent, onDone };
  rep.listeners.push(listener);
  rep.events?.slice(0, rep.idx).forEach(onEvent);
  if (rep.done) onDone && onDone();
  return () => { rep.listeners = rep.listeners.filter((l) => l !== listener); };
}

function emit(rep, e) { rep.listeners.forEach((l) => l.onEvent(e)); }

function step(runId) {
  const rep = replays.get(runId);
  if (!rep || rep.paused) return;
  if (rep.idx >= rep.events.length) {
    rep.done = true;
    rep.listeners.forEach((l) => l.onDone && l.onDone());
    return;
  }
  const e = rep.events[rep.idx];
  rep.idx += 1;
  emit(rep, e);
  if (e.kind === "approval_requested" && rep.manual) {
    rep.paused = e.payload.approval; // waits for resolveApproval()
    return;
  }
  const next = rep.events[rep.idx];
  const gap = next ? (Date.parse(next.ts) - Date.parse(e.ts)) || 0 : 0;
  rep.timer = setTimeout(() => step(runId), Math.min(450, Math.max(60, gap)));
}

function pendingApprovals(params) {
  const pending = [...replays.entries()].filter(([, r]) => r.paused)
    .map(([id, r]) => ({ ...r.paused, run_id: id, status: "pending" }));
  if (params && params.status === "") return pending; // history view: nothing resolved yet in this visit
  return pending;
}

async function resolveApproval(approvalId, action) {
  const entry = [...replays.entries()].find(([, r]) => r.paused && r.paused.id === approvalId);
  if (!entry) throw new Error("This approval is no longer pending.");
  const [runId, rep] = entry;
  rep.paused = null;
  if (action === "reject") {
    // Continue from the recorded run where a person rejected this approval.
    const m = await manifest();
    const alt = m.alt[rep.source];
    if (alt) {
      const rec = await loadRun(alt);
      const at = rec.trace.findIndex((e) => e.kind === "approval_requested");
      rep.source = alt;
      rep.events = rec.trace;
      rep.idx = at + 1;
    }
  }
  step(runId);
  return { id: approvalId, status: action === "approve" ? "approved" : "rejected" };
}
