import React, { useEffect, useState } from "react";
import { DEMO, get } from "./api.js";
import RunPage from "./pages/RunPage.jsx";
import ApprovalsPage from "./pages/ApprovalsPage.jsx";
import BlocksPage from "./pages/BlocksPage.jsx";
import BenchmarkPage from "./pages/BenchmarkPage.jsx";
import DemoPage from "./pages/DemoPage.jsx";
import PolicyPage from "./pages/PolicyPage.jsx";
import OpsPage from "./pages/OpsPage.jsx";
import BenchPage from "./pages/BenchPage.jsx";

const PAGES = [
  ["ops", "Business processes", OpsPage],
  ["run", "Live run", RunPage],
  ["approvals", "Approvals", ApprovalsPage],
  ["blocks", "Blocked actions", BlocksPage],
  ["benchmark", "Benchmark", BenchmarkPage],
  ["bench", "GuardBench", BenchPage],
  ["demo", "Demo script", DemoPage],
  ["policy", "Policy", PolicyPage],
];

function ThemeToggle() {
  const flip = () => {
    const root = document.documentElement;
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("ag-theme", root.dataset.theme); } catch (e) { /* private mode */ }
  };
  return (
    <button type="button" onClick={flip} aria-label="Switch light or dark theme"
      className="press grid h-9 w-9 place-items-center rounded-full border border-slate-300 text-slate-900 hover:border-slate-400">
      <svg width="15" height="15" viewBox="0 0 16 16" aria-hidden="true">
        <circle cx="8" cy="8" r="6.5" fill="none" stroke="currentColor" />
        <path d="M8 1.5a6.5 6.5 0 0 1 0 13z" fill="currentColor" />
      </svg>
    </button>
  );
}

export default function App() {
  const [page, setPage] = useState(() => location.hash.slice(1) || "ops");
  const [pending, setPending] = useState(0);

  useEffect(() => {
    const onHash = () => setPage(location.hash.slice(1) || "ops");
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

  const current = PAGES.find(([id]) => id === page) || PAGES[0];
  const Page = current[2];
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-page/85 backdrop-blur-md">
        <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 py-3 sm:px-6">
          <a href={DEMO ? "../" : "/site/"} className="shrink-0 text-[17px] font-semibold tracking-tight text-slate-900">
            AgentGuard<sup className="ml-0.5 font-mono text-[9px] text-slate-400">®</sup>
          </a>
          {DEMO && (
            <span className="hidden rounded-full bg-accent-soft px-2.5 py-1 font-mono text-[10px] uppercase tracking-wide text-accent sm:inline"
              title="This dashboard replays recorded real runs. Run `agentguard serve` for the live version.">
              Recorded demo
            </span>
          )}
          <div className="ml-auto flex items-center gap-2">
            <a href={DEMO ? "../" : "/site/"} className="press hidden h-9 items-center rounded-full border border-slate-300 px-4 text-sm text-slate-900 hover:border-slate-400 sm:inline-flex">
              Overview ↗
            </a>
            <ThemeToggle />
          </div>
        </div>
        <nav className="mx-auto flex max-w-7xl gap-1 overflow-x-auto px-4 pb-3 sm:px-6" aria-label="Pages">
          {PAGES.map(([id, label], i) => (
            <a key={id} href={`#${id}`} aria-current={page === id ? "page" : undefined}
              className={`press flex shrink-0 items-center gap-1.5 rounded-full px-3.5 py-1.5 font-mono text-[11px] uppercase tracking-wide ${
                page === id ? "bg-ink text-page" : "text-slate-500 hover:bg-slate-100 hover:text-slate-900"}`}>
              <span className={page === id ? "text-page/60" : "text-accent"}>{String(i + 1).padStart(2, "0")}</span>
              {label}
              {id === "approvals" && pending > 0 && (
                <span className="rounded-full bg-amber-500 px-1.5 text-[10px] text-white">{pending}</span>
              )}
            </a>
          ))}
        </nav>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
        <div className="mb-5">
          <p className="label">{String(PAGES.indexOf(current) + 1).padStart(2, "0")} · AgentGuard</p>
          <h1 className="mt-1 text-3xl font-medium tracking-tight text-slate-900 sm:text-4xl">{current[1]}</h1>
        </div>
        <Page />
      </main>
    </div>
  );
}
