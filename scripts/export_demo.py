"""Record the dashboard's recorded demo (dashboard/public/demo/) from real runs.

Everything is captured through the real API (FastAPI TestClient), so the recorded responses have exactly
the shapes the dashboard reads:

* offline runs made here: business processes (approve and reject branches), Live-run scenarios with the
  scripted agents, GuardBench reference and do-nothing runs, the demo script and a benchmark;
* real model runs copied from stored databases when given: Claude-decided business processes, Claude
  Code GuardBench sweeps (`--store` can be repeated).

    .venv/bin/python scripts/export_demo.py --store sqlite:///agentguard.db --store sqlite:///other.db
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from agentguard.core.store import Store
from agentguard.gym.bench.report import build_report
from agentguard.server.app import create_app

OUT = Path(__file__).resolve().parents[1] / "dashboard" / "public" / "demo"
ATTEMPT_AGENTS = ("scripted:oracle", "scripted:naive", "scripted:naive_v2", "scripted:adversarial", "scripted:null")


class Recorder:
    def __init__(self) -> None:
        self.manifest: dict[str, Any] = {"get": {}, "runs": {}, "start": {"ops": {}, "runs": {}, "bench": {}},
                                         "alt": {}, "jobs": {}, "policy_validate": None}
        self.n = 0

    def _write(self, name: str, data: Any) -> str:
        path = OUT / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, separators=(",", ":"), default=str))
        return name

    def get(self, client: TestClient, path: str, params: dict[str, Any] | None = None, key: str | None = None) -> Any:
        r = client.get(f"/api{path}", params=params)
        r.raise_for_status()
        self.n += 1
        qs = "&".join(f"{k}={v}" for k, v in (params or {}).items())
        self.manifest["get"][key or (path + (f"?{qs}" if qs else ""))] = self._write(f"get/{self.n}.json", r.json())
        return r.json()

    def run(self, client: TestClient, run_id: str) -> None:
        if run_id in self.manifest["runs"]:
            return
        detail = client.get(f"/api/runs/{run_id}").json()
        trace = client.get(f"/api/runs/{run_id}/trace").json()
        for e in trace:
            e["payload"] = slim(e.get("payload") or {})
        for c in (detail.get("verdict") or {}).get("checks", []):
            c["evidence"] = slim(c.get("evidence") or [], items=2)
            c["actual"], c["expected"] = slim(c.get("actual"), items=4), slim(c.get("expected"), items=4)
        record: dict[str, Any] = {"run": detail, "trace": trace}
        c = client.get(f"/api/runs/{run_id}/controls")
        if c.status_code == 200:
            record["controls"] = c.json()
        e = client.get(f"/api/runs/{run_id}/evidence", params={"format": "md"})
        if e.status_code == 200:
            record["evidence_md"] = e.text
            ev = client.get(f"/api/runs/{run_id}/evidence").json()
            ev["tool_calls"] = [{**c, "args": slim(c["args"], items=4, chars=200)} for c in ev["tool_calls"]]
            record["evidence"] = ev
        d = client.get(f"/api/runs/{run_id}/diagnosis")
        if d.status_code == 200:
            record["diagnosis"] = d.json()
        self.manifest["runs"][run_id] = self._write(f"runs/{run_id}.json", record)


def slim(value: Any, items: int = 6, chars: int = 500) -> Any:
    """Keep recorded payloads small: long lists and strings are cut, with a visible marker."""
    if isinstance(value, list):
        cut = [slim(v, items, chars) for v in value[:items]]
        return cut + [f"... {len(value) - items} more (trimmed for the recorded demo)"] if len(value) > items else cut
    if isinstance(value, dict):
        return {k: slim(v, items, chars) for k, v in value.items()}
    if isinstance(value, str) and len(value) > chars:
        return value[:chars] + " ... (trimmed)"
    return value


def wait(client: TestClient, run_id: str, timeout: float = 120) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = client.get(f"/api/runs/{run_id}").json()
        if r.get("verdict"):
            return r
        time.sleep(0.05)
    raise TimeoutError(run_id)


def ops_run(client: TestClient, process: str, decision: str) -> str:
    run_id = client.post(f"/api/ops/{process}", json={"manual_approvals": True}).json()["run_id"]
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        pending = [a for a in client.get("/api/approvals").json() if a["run_id"] == run_id]
        for a in pending:
            client.post(f"/api/approvals/{a['id']}/{decision}", json={"by": "human:dashboard"})
        if client.get(f"/api/runs/{run_id}").json().get("verdict"):
            return run_id
        time.sleep(0.05)
    raise TimeoutError(process)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", action="append", default=[], help="Extra stores with real model runs to copy")
    args = ap.parse_args()

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    rec = Recorder()
    reports = Path(tempfile.mkdtemp())
    store = Store.in_memory()
    client = TestClient(create_app(store=store, reports_dir=reports))

    # -- business processes: approve and reject branches (rule-based decisions) ------------------------
    for process in ("refunds", "access"):
        approved, rejected = ops_run(client, process, "approve"), ops_run(client, process, "reject")
        rec.run(client, approved)
        rec.run(client, rejected)
        rec.manifest["start"]["ops"][f"{process}|rules"] = approved
        rec.manifest["alt"][approved] = rejected
    print("ops recorded")

    # -- Live run: every scenario with the scripted agents, shield off and on --------------------------
    scenarios = rec.get(client, "/scenarios")
    for s in scenarios:
        for harness in ATTEMPT_AGENTS:
            for shield in (True, False):
                run_id = client.post("/api/runs", json={"scenario": s["id"], "harness": harness, "shield": shield,
                                                        "run_set": "dashboard"}).json()["run_id"]
                wait(client, run_id)
                rec.run(client, run_id)
                rec.manifest["start"]["runs"][f"{s['id']}|{harness}|{str(shield).lower()}"] = run_id
    print("scenario runs recorded")

    # -- GuardBench reference and do-nothing runs --------------------------------------------------------
    tasks = rec.get(client, "/bench/tasks")
    for t in tasks:
        rec.get(client, f"/bench/tasks/{t['id']}")
        for harness in ("bench:solution", "scripted:null"):
            for shield in (True, False):
                run_id = client.post("/api/bench/runs", json={"task": t["id"], "harness": harness,
                                                              "shield": shield}).json()["run_id"]
                wait(client, run_id)
                rec.run(client, run_id)
                rec.manifest["start"]["bench"][f"{t['id']}|{harness}||{str(shield).lower()}"] = run_id
    print("bench baselines recorded")

    # -- demo script and a one-attempt benchmark (jobs) -----------------------------------------------
    for kind, body in (("demo", None), ("benchmarks", {"attempts": 1})):
        job_id = client.post(f"/api/{kind}", json=body).json()["job_id"]
        while (job := client.get(f"/api/jobs/{job_id}").json())["status"] == "running":
            time.sleep(0.2)
        rec.manifest["jobs"][kind] = rec._write(f"jobs/{kind}.json", job)
    print("jobs recorded")

    # -- static pages ------------------------------------------------------------------------------------
    rec.get(client, "/harnesses")
    policy = rec.get(client, "/policies")
    rec.manifest["policy_validate"] = client.post("/api/policies/validate", json={"text": policy["text"]}).json()
    rec.get(client, "/approvals", key="/approvals")
    rec.get(client, "/approvals", {"status": ""})
    rec.get(client, "/blocks", {"limit_runs": 100})
    rec.get(client, "/benchmarks")
    sets = rec.get(client, "/run-sets")
    names = [s["name"] for s in sets if not s["name"].startswith("bench/") and s["name"] not in ("dashboard", "ops")]
    for a in names:
        for b in names:
            if a != b:
                rec.get(client, "/compare", {"a": a, "b": b})
    rec.get(client, "/runs", {"limit": 25})

    # -- real model runs from other stores -------------------------------------------------------------
    boards = [build_report(store)]
    for url in args.store:
        other = Store(url)
        oc = TestClient(create_app(store=other, reports_dir=reports))
        for r in other.list_runs(limit=1_000_000):
            rs = (r.config or {}).get("run_set") or ""
            if not r.verdict:
                continue
            if r.harness in ("ops:refunds+claude", "ops:access+claude"):
                process = r.harness.split(":")[1].split("+")[0]
                key = f"{process}|claude"
                if key not in rec.manifest["start"]["ops"]:
                    rec.run(oc, r.id)
                    rec.manifest["start"]["ops"][key] = r.id
            elif rs.startswith("bench/") and r.harness == "mcp_client:claude-code":
                shield = rs.endswith("/shield")
                key = f"{r.scenario_id}|{r.harness}|{r.model}|{str(shield).lower()}"
                if key not in rec.manifest["start"]["bench"]:
                    rec.run(oc, r.id)
                    rec.manifest["start"]["bench"][key] = r.id
        boards.append(build_report(other))
        print(f"copied model runs from {url}")

    # one leaderboard over every store (baselines here + model sweeps there)
    # the "dashboard" sweep holds this recorder's own reference runs, which repeat the stored baselines
    leaderboard = [row for b in boards for row in b["leaderboard"] if row["sweep"] != "dashboard"] or boards[0]["leaderboard"]
    most_missed = next((b["most_missed"] for b in boards[1:] if b["most_missed"]), boards[0]["most_missed"])
    rec.manifest["get"]["/bench/leaderboard"] = rec._write("get/leaderboard.json", {
        "sweep": None, "leaderboard": sorted(leaderboard, key=lambda r: (-r["solve_rate"], r["harm_rate"])),
        "shield_effect": [e for b in boards for e in b.get("shield_effect", [])], "most_missed": most_missed})

    (OUT / "manifest.json").write_text(json.dumps(rec.manifest, separators=(",", ":")))
    size = sum(p.stat().st_size for p in OUT.rglob("*.json"))
    print(f"wrote {len(rec.manifest['runs'])} runs, {size / 1e6:.1f} MB to {OUT}")


if __name__ == "__main__":
    main()
