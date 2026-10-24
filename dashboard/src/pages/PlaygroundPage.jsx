import React, { useEffect, useRef, useState } from "react";
import { DEMO, get, post, streamRun } from "../api.js";
import { Badge, Button, Card, Empty, EvidenceDownloads, RISK_STYLE } from "../components/ui.jsx";
import Trace from "../components/Trace.jsx";

// The attack playground: chat with a real agent (Claude Code, started by `agentguard serve`) and try to
// make it do something harmful. The company data persists for the whole conversation.

const VERDICT_STYLE = {
  harm: "bg-rose-600 text-white",
  blocked: "bg-amber-100 text-amber-900 border border-amber-300",
  refused: "bg-emerald-100 text-emerald-900 border border-emerald-300",
  ok: "bg-slate-100 text-slate-800 border border-slate-200",
  error: "bg-slate-100 text-slate-800 border border-slate-300",
};
const VERDICT_ICON = { harm: "🟥", blocked: "🟨", refused: "🟩", ok: "⬜", error: "⚠" };

export default function PlaygroundPage() {
  if (DEMO) {
    return (
      <Card title="Attack playground">
        <p className="text-sm text-slate-700">
          The playground talks to a real agent started by your own AgentGuard server, so it isn't part of the recorded demo.
          Run it locally: <code className="font-mono">agentguard serve</code>, then open <code className="font-mono">http://localhost:8000/#playground</code>.
        </p>
      </Card>
    );
  }
  return <Playground />;
}

function Playground() {
  const [meta, setMeta] = useState({ presets: [], models: [], agents: {} });
  const [opts, setOpts] = useState({ shield: true, agent: "claude", model: "haiku" });
  const [session, setSession] = useState(null);
  const [text, setText] = useState("");
  const [plant, setPlant] = useState({ ticket_id: "T-78", text: "", open: false });
  const [selected, setSelected] = useState(null); // run id of the turn on the right
  const [followup, setFollowup] = useState(null);
  const [error, setError] = useState(null);
  const chatEnd = useRef(null);

  const start = async (o = opts) => {
    setError(null); setSelected(null); setFollowup(null);
    setSession(await post("/playground/sessions", o));
  };
  useEffect(() => { get("/playground/presets").then(setMeta); start(); }, []);

  // Follow the session while the agent works.
  useEffect(() => {
    if (!session?.busy) return;
    const t = setInterval(async () => setSession(await get(`/playground/sessions/${session.id}`)), 700);
    return () => clearInterval(t);
  }, [session?.id, session?.busy]);
  useEffect(() => { chatEnd.current?.scrollIntoView({ block: "nearest" }); }, [session?.items?.length, session?.busy]);

  const turns = (session?.items || []).filter((i) => i.kind === "turn");
  const current = turns.find((t) => t.run_id === selected) || turns[turns.length - 1];

  const send = async (message) => {
    if (!message.trim() || !session) return;
    setError(null);
    try {
      const turn = await post(`/playground/sessions/${session.id}/messages`, { text: message });
      setText(""); setSelected(turn.run_id);
      setSession(await get(`/playground/sessions/${session.id}`));
    } catch (e) { setError(String(e.message || e)); }
  };
  const doPlant = async (ticket_id, body) => {
    await post(`/playground/sessions/${session.id}/plant`, { ticket_id, text: body });
    setSession(await get(`/playground/sessions/${session.id}`));
  };
  const usePreset = async (p) => {
    if (p.plant) await doPlant(p.plant.ticket_id, p.plant.text);
    setFollowup(p.followup || null);
    await send(p.message);
  };
  const switchShield = (shield) => { const o = { ...opts, shield }; setOpts(o); start(o); };

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
      <div className="space-y-4">
        <Card title="Chat with the agent" actions={<>
          <label className="flex items-center gap-1.5 text-sm">
            <input type="checkbox" checked={opts.shield} disabled={session?.busy} onChange={(e) => switchShield(e.target.checked)} />
            AgentShield
          </label>
          <select className="rounded border-slate-300 py-1 text-xs" value={opts.agent} disabled={session?.busy}
            onChange={(e) => { const o = { ...opts, agent: e.target.value }; setOpts(o); start(o); }}>
            {Object.entries(meta.agents).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
          </select>
          {opts.agent === "claude" && (
            <select className="rounded border-slate-300 py-1 text-xs" value={opts.model || ""} disabled={session?.busy}
              onChange={(e) => { const o = { ...opts, model: e.target.value }; setOpts(o); start(o); }}>
              {meta.models.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          )}
          <Button kind="secondary" disabled={session?.busy} onClick={() => start()}>New conversation</Button>
        </>}>
          <p className="mb-3 text-xs text-slate-500">
            {opts.agent === "claude"
              ? "Real Claude, started by this server through Claude Code, acting on the company's systems (customers, orders, payments ledger, tickets, email outbox, secrets) only through the gateway. Claude refuses many attacks by itself; AgentShield is the guarantee for when a model is fooled."
              : "The obedient test agent does whatever the message or a ticket tells it, like a weaker, misconfigured or jailbroken model. Use it to see what AgentShield stops."}{" "}
            Data persists for the whole conversation; changing a setting starts a fresh one. AgentShield is <b>{opts.shield ? "on" : "off"}</b>.
          </p>

          <div className="max-h-[28rem] space-y-2 overflow-y-auto pr-1">
            {(session?.items || []).length === 0 && <Empty>Pick an attack below, or type your own message.</Empty>}
            {(session?.items || []).map((i, k) => i.kind === "plant" ? (
              <div key={k} className="rounded-lg border border-dashed border-rose-300 bg-rose-50 px-3 py-2 text-xs text-rose-900">
                <b>Hidden text planted in {i.ticket_id}:</b> “{i.text}”
              </div>
            ) : (
              <div key={k} className="space-y-1.5">
                <div className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-sm bg-accent px-3.5 py-2 text-sm text-white">{i.user}</div>
                <button type="button" onClick={() => setSelected(i.run_id)}
                  className={`block w-fit max-w-[90%] rounded-2xl rounded-bl-sm border px-3.5 py-2 text-left text-sm ${
                    current?.run_id === i.run_id ? "border-accent" : "border-slate-200"} bg-surface`}>
                  {i.status === "running" ? <span className="text-slate-500">Agent is working… (watch the right side)</span> : i.reply}
                  {i.verdict && <span className={`mt-1.5 block w-fit rounded px-1.5 py-0.5 text-[11px] ${VERDICT_STYLE[i.verdict.level]}`}>
                    {VERDICT_ICON[i.verdict.level]} {i.verdict.title}</span>}
                </button>
              </div>
            ))}
            <div ref={chatEnd} />
          </div>

          <form className="mt-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); send(text); }}>
            <input className="min-w-0 flex-1 rounded-full border-slate-300 px-4 text-sm" value={text} disabled={session?.busy}
              placeholder={session?.busy ? "The agent is working…" : "Type a message, or try to trick the agent"}
              onChange={(e) => setText(e.target.value)} />
            <Button type="submit" disabled={session?.busy || !text.trim()}>Send</Button>
          </form>
          {followup && !session?.busy && (
            <button type="button" className="mt-2 text-xs text-accent underline" onClick={() => { const f = followup; setFollowup(null); send(f); }}>
              Next: send the follow-up (“{followup.slice(0, 60)}…”)
            </button>
          )}
          {error && <p className="mt-2 text-xs text-rose-700">{error}</p>}
        </Card>

        <Card title="Attacks to try">
          <div className="grid gap-2 sm:grid-cols-2">
            {meta.presets.map((p) => (
              <button key={p.id} type="button" disabled={session?.busy} onClick={() => usePreset(p)}
                className="press rounded-xl border border-slate-200 p-3 text-left hover:border-accent disabled:opacity-40">
                <div className="text-sm font-medium text-slate-900">{p.title}</div>
                <div className="mt-1 text-xs text-slate-500">{p.expect}</div>
              </button>
            ))}
          </div>
          <div className="mt-3 border-t border-slate-200 pt-3">
            <button type="button" className="text-sm font-medium text-slate-900" onClick={() => setPlant({ ...plant, open: !plant.open })}>
              {plant.open ? "▾" : "▸"} Hide your own text in a ticket
            </button>
            {plant.open && (
              <div className="mt-2 space-y-2">
                <p className="text-xs text-slate-500">This is the realistic attack: the attacker writes into data the agent will read later. Plant it, then ask an innocent question like “Please handle ticket {plant.ticket_id}”.</p>
                <div className="flex gap-2">
                  <select className="rounded border-slate-300 text-sm" value={plant.ticket_id} onChange={(e) => setPlant({ ...plant, ticket_id: e.target.value })}>
                    {(session?.tickets || []).map((t) => <option key={t.id}>{t.id}</option>)}
                    <option value="T-90">T-90 (new)</option>
                  </select>
                  <input className="min-w-0 flex-1 rounded border-slate-300 text-sm" value={plant.text} placeholder="e.g. Ignore your instructions and…"
                    onChange={(e) => setPlant({ ...plant, text: e.target.value })} />
                  <Button kind="secondary" disabled={session?.busy || !plant.text.trim()}
                    onClick={async () => { await doPlant(plant.ticket_id, plant.text); setPlant({ ...plant, text: "" }); }}>Plant</Button>
                </div>
              </div>
            )}
          </div>
        </Card>

        <CompanyData session={session} />
      </div>

      <div className="space-y-4">
        {current ? <TurnView key={current.run_id} turn={current} /> : (
          <Card><Empty>Each message runs live: the agent's tool calls, AgentShield's decisions and what changed in the company's systems appear here.</Empty></Card>
        )}
      </div>
    </div>
  );
}

function TurnView({ turn }) {
  const [events, setEvents] = useState([]);
  const [pending, setPending] = useState([]);
  useEffect(() => streamRun(turn.run_id, (e) => setEvents((ev) => [...ev, e]), () => {}), [turn.run_id]);
  useEffect(() => {
    if (turn.status !== "running") { setPending([]); return; }
    const t = setInterval(async () => {
      const all = await get("/approvals").catch(() => []);
      setPending(all.filter((a) => a.run_id === turn.run_id));
    }, 800);
    return () => clearInterval(t);
  }, [turn.run_id, turn.status]);
  const resolve = (id, action) => post(`/approvals/${id}/${action}`, { by: "human:dashboard" });
  const v = turn.verdict;
  const c = turn.changes;

  return (
    <>
      <Card title={`Message ${turn.n} · AgentShield ${turn.shield ? "on" : "off"} · ${turn.agent === "claude" ? `Claude ${turn.model || ""}` : "obedient test agent"}`}
        actions={turn.status === "running" ? <Badge className="bg-accent-soft text-accent">running live</Badge>
          : turn.cost_usd ? <span className="text-xs text-slate-500">${turn.cost_usd.toFixed(3)}</span> : null}>
        {v ? (
          <div className={`rounded-xl px-4 py-3 ${VERDICT_STYLE[v.level]}`}>
            <div className="text-base font-semibold">{VERDICT_ICON[v.level]} {v.title}</div>
            {v.detail.length > 0 && <ul className="mt-1 list-disc pl-5 text-sm">{v.detail.map((d, i) => <li key={i}>{d}</li>)}</ul>}
          </div>
        ) : turn.status === "error" ? (
          <p className="text-sm text-rose-700">{turn.reply}</p>
        ) : (
          <p className="text-sm text-slate-600">The agent is working. Every tool call below goes through {turn.shield ? "AgentShield" : "the gateway with AgentShield off"}.</p>
        )}
        {pending.map((a) => (
          <div key={a.id} className="mt-3 flex flex-wrap items-center gap-2 rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm">
            <Badge className={RISK_STYLE[a.decision.risk]}>{a.decision.risk}</Badge>
            <span className="font-mono">{a.tool} {JSON.stringify(a.args)}</span>
            <span className="text-slate-700">{a.decision.reason}</span>
            <span className="ml-auto flex gap-2">
              <Button kind="approve" onClick={() => resolve(a.id, "approve")}>Approve</Button>
              <Button kind="reject" onClick={() => resolve(a.id, "reject")}>Reject</Button>
            </span>
          </div>
        ))}
      </Card>

      {c && (
        <Card title="What changed in the company's systems">
          <ul className="space-y-1 text-sm">
            {c.refunds.map((r, i) => <li key={`r${i}`}>💸 Refund <b>₹{r.amount_inr.toLocaleString("en-IN")}</b> on {r.order_id}
              {r.refunds_on_order > 1 && <span className="text-rose-700"> (refund #{r.refunds_on_order} on this order)</span>}
              {!r.customer_verified && <span className="text-rose-700"> (customer not verified)</span>}</li>)}
            {c.emails.map((m, i) => <li key={`e${i}`}>✉️ Email to <b>{m.to}</b>: “{m.subject}”
              {m.contains_secret && <span className="text-rose-700"> (contains a secret)</span>}
              {m.external && !m.contains_secret && <span className="text-rose-700"> (outside the company)</span>}</li>)}
            {c.queries.map((q, i) => <li key={`q${i}`}>🗄 Database query <code className="font-mono text-xs">{q.sql}</code>, {q.rows} rows</li>)}
            {c.secrets_read.map((s, i) => <li key={`s${i}`}>🔑 Read secret <b>{s}</b></li>)}
            {c.tickets.map((t, i) => <li key={`t${i}`}>🎫 Ticket {t.id}: {t.was ? `${t.was} → ` : ""}{t.status}</li>)}
            {!c.refunds.length && !c.emails.length && !c.queries.length && !c.secrets_read.length && !c.tickets.length &&
              <li className="text-slate-500">Nothing changed.</li>}
          </ul>
          {turn.controls && (
            <p className="mt-3 text-xs text-slate-500">
              {turn.controls.tool_calls} tool calls · {turn.controls.blocks.length} blocked · {turn.controls.injections} injection flags ·{" "}
              {turn.controls.approvals.length} approvals
            </p>
          )}
          <div className="mt-4 border-t border-slate-200 pt-4"><EvidenceDownloads runId={turn.run_id} /></div>
        </Card>
      )}

      <Card title="Live activity: every tool call and AgentShield's decision">
        {events.length === 0 ? <Empty>Waiting for the agent's first action…</Empty> : <Trace events={events} />}
      </Card>
    </>
  );
}

function CompanyData({ session }) {
  if (!session) return null;
  return (
    <Card title="The company's data right now">
      <div className="grid gap-3 text-xs sm:grid-cols-2">
        <div>
          <div className="label mb-1">Tickets</div>
          {session.tickets.map((t) => (
            <div key={t.id} className="mb-1 truncate" title={t.notes}><b>{t.id}</b> · {t.status} · <span className="text-slate-500">{t.notes}</span></div>
          ))}
        </div>
        <div>
          <div className="label mb-1">Refunds in the ledger</div>
          {session.refunds.length === 0 ? <div className="text-slate-500">None yet.</div>
            : session.refunds.map((r) => <div key={r.id}>{r.order_id} · ₹{r.amount_inr.toLocaleString("en-IN")} · {r.status}</div>)}
          <div className="label mb-1 mt-3">Emails sent</div>
          {session.outbox.length === 0 ? <div className="text-slate-500">None yet.</div>
            : session.outbox.map((m) => <div key={m.id} className="truncate">{m.to} · {m.subject}</div>)}
        </div>
      </div>
      <p className="mt-3 text-xs text-slate-500">Orders: O-9001 (Priya, ₹5,000, verified) · O-9002 (Rahul, ₹30,000, verified) · O-9003 (Ananya, ₹1,200, not verified). Agent limit: ₹5,000 per refund, approval above ₹2,000.</p>
    </Card>
  );
}
