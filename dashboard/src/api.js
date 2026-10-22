// Thin wrappers over the AgentGuard API (agentguard/server/app.py).

export async function get(path, params) {
  const qs = params ? "?" + new URLSearchParams(params) : "";
  const r = await fetch(`/api${path}${qs}`);
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

export async function post(path, body) {
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
