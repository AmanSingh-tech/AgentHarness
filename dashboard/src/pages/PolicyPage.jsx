import React, { useEffect, useState } from "react";
import { get, post } from "../api.js";
import { Button, Card } from "../components/ui.jsx";

export default function PolicyPage() {
  const [text, setText] = useState("");
  const [info, setInfo] = useState(null);
  const [result, setResult] = useState(null);
  useEffect(() => { get("/policies").then((p) => { setText(p.text); setInfo(p); }); }, []);
  useEffect(() => {
    if (!text) return;
    const t = setTimeout(() => post("/policies/validate", { text }).then(setResult).catch(() => {}), 400);
    return () => clearTimeout(t);
  }, [text]);
  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_20rem]">
      <Card title="Policy editor (default.yaml) — validated as you type">
        <textarea value={text} onChange={(e) => setText(e.target.value)} spellCheck={false}
          className="h-[36rem] w-full rounded border-slate-300 font-mono text-xs leading-relaxed" />
        <p className="mt-2 text-xs text-slate-500">Edits here are only validated, not saved: change shield/policies/default.yaml to apply them.</p>
      </Card>
      <div className="space-y-4">
        <Card title="Validation">
          {!result ? <p className="text-sm text-slate-400">…</p> : result.ok ? (
            <p className="text-sm text-emerald-700">✅ Valid: {result.agents} agents, {result.rules} rules, {result.sequences} sequences, {result.patterns} patterns.</p>
          ) : (
            <ul className="space-y-1 text-sm text-rose-700">{result.problems.map((p, i) => <li key={i} className="font-mono text-xs">{p}</li>)}</ul>
          )}
        </Card>
        {info && (
          <Card title="What the default policy enforces">
            <dl className="space-y-2 text-xs">
              <div><dt className="font-semibold text-slate-500">Agents</dt><dd className="font-mono">{info.agents.join(", ")}</dd></div>
              <div><dt className="font-semibold text-slate-500">Rules</dt><dd className="font-mono">{info.rules.join(", ")}</dd></div>
              <div><dt className="font-semibold text-slate-500">Data-flow sequences</dt><dd className="font-mono">{info.sequences.join(", ")}</dd></div>
              <div><dt className="font-semibold text-slate-500">Ordered patterns</dt><dd className="font-mono">{info.patterns.join(", ")}</dd></div>
            </dl>
          </Card>
        )}
      </div>
    </div>
  );
}
