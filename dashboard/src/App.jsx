import React, { useEffect, useState } from "react";
import { get } from "./api.js";
import RunPage from "./pages/RunPage.jsx";
import ApprovalsPage from "./pages/ApprovalsPage.jsx";
import BlocksPage from "./pages/BlocksPage.jsx";
import BenchmarkPage from "./pages/BenchmarkPage.jsx";
import DemoPage from "./pages/DemoPage.jsx";
import PolicyPage from "./pages/PolicyPage.jsx";

const PAGES = [
  ["run", "Live run", RunPage],
  ["approvals", "Approvals", ApprovalsPage],
  ["blocks", "Blocked actions", BlocksPage],
  ["benchmark", "Benchmark", BenchmarkPage],
  ["demo", "Demo script", DemoPage],
  ["policy", "Policy", PolicyPage],
];

export default function App() {
  const [page, setPage] = useState(() => location.hash.slice(1) || "run");
  const [pending, setPending] = useState(0);

  useEffect(() => {
    const onHash = () => setPage(location.hash.slice(1) || "run");
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    let alive = true;
    const tick = () => get("/approvals").then((a) => alive && setPending(a.length)).catch(() => {});
    tick();
    const t = setInterval(tick, 1500);
    return () => { alive = false; clearInterval(t); };
  }, []);

  const Page = (PAGES.find(([id]) => id === page) || PAGES[0])[2];
  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <div>
            <div className="text-base font-semibold">AgentGuard</div>
            <div className="text-xs text-slate-500">Test and protect AI agents: AgentGym + AgentShield</div>
          </div>
          <nav className="flex flex-wrap gap-1">
            {PAGES.map(([id, label]) => (
              <a key={id} href={`#${id}`}
                className={`rounded-md px-3 py-1.5 text-sm ${page === id ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"}`}>
                {label}
                {id === "approvals" && pending > 0 && (
                  <span className="ml-1.5 rounded-full bg-amber-500 px-1.5 text-xs text-white">{pending}</span>
                )}
              </a>
            ))}
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-5">
        <Page />
      </main>
    </div>
  );
}
