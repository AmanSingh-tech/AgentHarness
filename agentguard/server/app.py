"""AgentGuard API server (FastAPI) and the dashboard's backend.

    agentguard serve            # http://127.0.0.1:8000

Runs started here execute in background threads through the same runner, gateway,
shield and verifier as the CLI. Live traces stream over Server-Sent Events.
Runs started with `manual_approvals` share one approval queue that waits for a
click in the dashboard (or a POST to /api/approvals/{id}/approve|reject).
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from agentguard.core.events import EventBus
from agentguard.core.models import ApprovalStatus, RunRecord, TraceKind
from agentguard.core.store import Store
from agentguard.harnesses.base import make_harness
from agentguard.shield.approvals import ApprovalQueue, AutoApprover, resolve_in_store

DASHBOARD_DIST = Path(os.environ.get("AGENTGUARD_DASHBOARD_DIST")
                      or Path(__file__).resolve().parents[2] / "dashboard" / "dist")
SUGGESTED_HARNESSES = [
    "scripted:oracle", "scripted:naive", "scripted:naive_v2", "scripted:adversarial", "scripted:refuser",
    "scripted:null", "mcp_client:claude-code", "native:anthropic", "langgraph:anthropic",
]


class RunRequest(BaseModel):
    scenario: str
    harness: str = "scripted:oracle"
    shield: bool = True
    manual_approvals: bool = False
    model: str | None = None
    run_set: str | None = None


class Resolution(BaseModel):
    by: str = "human:dashboard"
    note: str | None = None


class PolicyText(BaseModel):
    text: str


class OpsRequest(BaseModel):
    shield: bool = True
    manual_approvals: bool = True


class BenchmarkRequest(BaseModel):
    attempts: int = 1
    agents: list[str] = ["scripted:naive", "scripted:naive_v2"]


def create_app(store: Store | None = None, reports_dir: Path = Path("reports"),
               approval_timeout_s: float = 300.0) -> FastAPI:
    from agentguard.core.config import Settings

    store = store or Store(Settings.from_env().db_url)
    bus = EventBus()  # shared, so the SSE endpoint can follow runs started here (each run persists its own events)
    approvals = ApprovalQueue(store, auto=AutoApprover(default="manual"), timeout_s=approval_timeout_s)
    jobs: dict[str, dict[str, Any]] = {}
    app = FastAPI(title="AgentGuard", version="0.1.0")
    app.state.store, app.state.bus, app.state.approvals, app.state.jobs = store, bus, approvals, jobs

    # -- scenarios, harnesses, policies -------------------------------------------------

    @app.get("/api/scenarios")
    def scenarios() -> list[dict[str, Any]]:
        from agentguard.gym.scenario import load_scenarios

        return [{
            "id": s.id, "description": s.description, "task": s.task, "tags": s.tags, "oracle": s.oracle,
            "agent_role": s.agent_role, "task_outcome": s.expected.task_outcome,
            "faults": [f.model_dump(mode="json", exclude_defaults=True) for f in s.faults],
        } for s in load_scenarios()]

    @app.get("/api/harnesses")
    def harnesses() -> list[str]:
        return SUGGESTED_HARNESSES

    @app.get("/api/policies")
    def policies() -> dict[str, Any]:
        from agentguard.shield.policy import DEFAULT_POLICY, load_policy

        p = load_policy()
        return {"name": "default", "text": DEFAULT_POLICY.read_text(), "agents": sorted(p.agents),
                "rules": [r.id for r in p.rules], "sequences": [q.id for q in p.sequences],
                "patterns": [q.id for q in p.patterns]}

    @app.post("/api/policies/validate")
    def validate_policy(body: PolicyText) -> dict[str, Any]:
        from agentguard.shield.policy import PolicyError, parse_policy

        try:
            p = parse_policy(body.text)
        except PolicyError as e:
            return {"ok": False, "problems": e.problems}
        return {"ok": True, "agents": len(p.agents), "rules": len(p.rules), "sequences": len(p.sequences),
                "patterns": len(p.patterns)}

    # -- runs -------------------------------------------------------------------------------

    @app.post("/api/runs", status_code=202)
    def start_run(req: RunRequest) -> dict[str, str]:
        from agentguard.gym.runner import execute, prepare_run, scenario_run_kwargs, verify_run
        from agentguard.gym.scenario import find_scenario

        try:
            scenario = find_scenario(req.scenario)
            agent = make_harness(req.harness)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        run = prepare_run(harness=req.harness, harness_type=agent.harness_type, capabilities=agent.capabilities,
                          store=store, bus=bus, model=req.model, approvals=approvals if req.manual_approvals else None,
                          **scenario_run_kwargs(scenario, req.shield, req.run_set or "dashboard"))

        def work() -> None:
            verify_run(scenario, execute(run, agent), store)

        threading.Thread(target=work, name=f"run-{run.run_id}", daemon=True).start()
        return {"run_id": run.run_id}

    @app.post("/api/ops/refunds", status_code=202)
    def start_refund_ops(req: OpsRequest) -> dict[str, str]:
        """Run RefundOps on the support inbox; with manual approvals, held refunds wait for a click."""
        from agentguard.gym.runner import execute, prepare_run, scenario_run_kwargs, verify_run
        from agentguard.gym.scenario import find_scenario

        scenario = find_scenario("refund_ops_inbox")
        agent = make_harness("ops:refunds")
        auto = None if req.manual_approvals else ApprovalQueue(store, auto=AutoApprover(default="approve"))
        run = prepare_run(harness="ops:refunds", harness_type=agent.harness_type, capabilities=agent.capabilities,
                          store=store, bus=bus, approvals=approvals if req.manual_approvals else auto,
                          **scenario_run_kwargs(scenario, req.shield, "ops"))

        def work() -> None:
            verify_run(scenario, execute(run, agent), store)

        threading.Thread(target=work, name=f"ops-{run.run_id}", daemon=True).start()
        return {"run_id": run.run_id}

    @app.get("/api/runs/{run_id}/controls")
    def run_controls(run_id: str) -> dict[str, Any]:
        from agentguard.ops.controls import controls_from_trace

        _run(store, run_id)
        return controls_from_trace(store, run_id)

    @app.get("/api/runs")
    def list_runs(limit: int = 50, run_set: str | None = None) -> list[dict[str, Any]]:
        runs = store.list_runs(limit=limit if run_set is None else 100_000)
        if run_set is not None:
            runs = [r for r in runs if r.config.get("run_set") == run_set][:limit]
        return [_summary(r) for r in runs]

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        rec = _run(store, run_id)
        return {**_summary(rec), "output": rec.output.model_dump(mode="json") if rec.output else None,
                "verdict": rec.verdict, "task": rec.config.get("task"), "scenario": rec.config.get("scenario")}

    @app.get("/api/runs/{run_id}/trace")
    def get_trace(run_id: str) -> list[dict[str, Any]]:
        _run(store, run_id)
        return [e.model_dump(mode="json") for e in store.get_trace(run_id)]

    @app.get("/api/runs/{run_id}/stream")
    async def stream(run_id: str) -> EventSourceResponse:
        _run(store, run_id)
        queue = bus.queue(run_id)  # subscribe before reading history so nothing falls in between

        async def events():
            sent = 0
            for e in store.get_trace(run_id):
                sent = e.seq
                yield {"event": "trace", "data": e.model_dump_json()}
                if e.kind == TraceKind.RUN_FINISHED:
                    yield {"event": "done", "data": "{}"}
                    return
            while True:
                rec = store.get_run(run_id)
                if rec is not None and rec.status.value != "running" and queue.empty():
                    # finished while we were catching up: flush anything stored after `sent`
                    for e in store.get_trace(run_id):
                        if e.seq > sent:
                            yield {"event": "trace", "data": e.model_dump_json()}
                    yield {"event": "done", "data": "{}"}
                    return
                try:
                    e = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                if e.seq <= sent:
                    continue
                sent = e.seq
                yield {"event": "trace", "data": e.model_dump_json()}
                if e.kind == TraceKind.RUN_FINISHED:
                    # the verdict is written just after RUN_FINISHED; give the client a moment to fetch it
                    yield {"event": "done", "data": "{}"}
                    return

        return EventSourceResponse(events())

    @app.get("/api/runs/{run_id}/diagnosis")
    def diagnosis(run_id: str) -> dict[str, Any]:
        from agentguard.gym.diagnose import diagnose

        _run(store, run_id)
        return diagnose(run_id, store).to_dict()

    @app.post("/api/runs/{run_id}/promote")
    def promote_run(run_id: str, dry_run: bool = False) -> dict[str, Any]:
        from agentguard.gym.regression import REGRESSION_DIR, promote, to_yaml

        _run(store, run_id)
        p = promote(run_id, store, out_dir=REGRESSION_DIR, write=not dry_run)
        return {"accepted": p.accepted, "reason": p.reason, "path": str(p.path) if p.path else None,
                "scenario_id": p.scenario.id if p.scenario else None,
                "yaml": to_yaml(p.scenario) if p.scenario else None,
                "summary": p.diagnosis.summary if p.diagnosis else []}

    @app.get("/api/run-sets")
    def run_sets() -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for r in store.list_runs(limit=100_000):
            name = r.config.get("run_set")
            if name:
                counts[name] = counts.get(name, 0) + 1
        return [{"name": k, "runs": v} for k, v in sorted(counts.items())]

    # -- shield activity ----------------------------------------------------------------------

    @app.get("/api/blocks")
    def blocks(limit_runs: int = 50) -> list[dict[str, Any]]:
        """Every BLOCK / REQUIRE_APPROVAL decision in recent runs, with its evidence and resolution."""
        out = []
        for rec in store.list_runs(limit=limit_runs):
            trace = store.get_trace(rec.id)
            resolved = {e.call_id: e.payload["approval"] for e in trace if e.kind == TraceKind.APPROVAL_RESOLVED}
            args = {e.call_id: e.payload.get("args") for e in trace if e.kind == TraceKind.TOOL_CALL}
            for e in trace:
                if e.kind == TraceKind.DECISION and e.payload["type"] in ("BLOCK", "REQUIRE_APPROVAL"):
                    a = resolved.get(e.call_id)
                    out.append({
                        "run_id": rec.id, "scenario": rec.scenario_id, "harness": rec.harness, "ts": e.ts.isoformat(),
                        "tool": e.payload["tool"], "args": args.get(e.call_id), "type": e.payload["type"],
                        "rule_id": e.payload.get("rule_id"), "risk": e.payload["risk"], "stage": e.payload.get("stage"),
                        "reason": e.payload["reason"], "evidence": e.payload.get("evidence", {}),
                        "approval": {"status": a["status"], "by": a["resolved_by"]} if a else None,
                    })
        return out

    @app.get("/api/approvals")
    def list_approvals(status: str | None = "pending") -> list[dict[str, Any]]:
        if status == "pending":
            # this server's runs, plus runs in other processes (e.g. `agentguard protect`) sharing the store
            mine = {a.id: a for a in approvals.pending()}
            others = {a.id: a for a in store.list_approvals(status=ApprovalStatus.PENDING) if a.id not in mine}
            return [a.model_dump(mode="json") for a in [*mine.values(), *others.values()]]
        st = ApprovalStatus(status) if status else None
        return [a.model_dump(mode="json") for a in store.list_approvals(status=st)][-100:]

    @app.post("/api/approvals/{approval_id}/{action}")
    def resolve(approval_id: str, action: str, body: Resolution | None = None) -> dict[str, Any]:
        if action not in ("approve", "reject"):
            raise HTTPException(404, "action must be approve or reject")
        body = body or Resolution()
        try:
            if approvals.get(approval_id) is not None:
                a = approvals.resolve(approval_id, action == "approve", by=body.by, note=body.note)
            else:  # waited on by another process; it picks the decision up from the store
                a = resolve_in_store(store, approval_id, action == "approve", by=body.by, note=body.note)
        except KeyError:
            raise HTTPException(404, f"no pending approval {approval_id}") from None
        except ValueError as e:
            raise HTTPException(409, str(e)) from None
        return a.model_dump(mode="json")

    # -- metrics, benchmark, demo ----------------------------------------------------------------

    @app.get("/api/metrics")
    def metrics(group_by: str = "harness,model,agent_version", limit: int = 1000) -> list[dict[str, Any]]:
        from agentguard.gym.metrics import compute_metrics

        try:
            return compute_metrics(store, store.list_runs(limit=limit),
                                   tuple(f for f in group_by.split(",") if f))
        except ValueError as e:
            raise HTTPException(400, str(e)) from None

    @app.get("/api/compare")
    def compare_sets(a: str, b: str) -> list[dict[str, Any]]:
        from agentguard.gym.compare import compare

        try:
            return compare(store, a, b)
        except ValueError as e:
            raise HTTPException(404, str(e)) from None

    @app.get("/api/benchmarks")
    def benchmarks() -> list[dict[str, Any]]:
        if not reports_dir.is_dir():
            return []
        return [json.loads(p.read_text()) for p in sorted(reports_dir.glob("benchmark-*.json"), reverse=True)]

    @app.post("/api/benchmarks", status_code=202)
    def start_benchmark(req: BenchmarkRequest) -> dict[str, str]:
        from agentguard.gym.benchmark import run_benchmark, write_report

        def work(job: dict[str, Any]) -> None:
            report = run_benchmark(store, agents=req.agents, attempts=req.attempts)
            write_report(report, reports_dir)
            job["result"] = report

        return _job(jobs, "benchmark", work)

    @app.post("/api/demo", status_code=202)
    def start_demo() -> dict[str, str]:
        from dataclasses import asdict

        from agentguard.gym.demo import run_demo

        def work(job: dict[str, Any]) -> None:
            job["steps"] = []
            run_demo(store, on_step=lambda step: job["steps"].append(asdict(step)))

        return _job(jobs, "demo", work)

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        if job_id not in jobs:
            raise HTTPException(404, "no such job")
        return dict(jobs[job_id])

    # -- dashboard ----------------------------------------------------------------------------------

    if DASHBOARD_DIST.is_dir():
        app.mount("/assets", StaticFiles(directory=DASHBOARD_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            return FileResponse(DASHBOARD_DIST / "index.html")

    return app


def _run(store: Store, run_id: str) -> RunRecord:
    rec = store.get_run(run_id)
    if rec is None:
        raise HTTPException(404, f"run {run_id} not found")
    return rec


def _summary(r: RunRecord) -> dict[str, Any]:
    v = r.verdict or {}
    return {
        "id": r.id, "status": r.status.value, "scenario": r.scenario_id, "harness": r.harness, "model": r.model,
        "run_set": r.config.get("run_set"), "shield": r.config.get("shield_enabled", r.config.get("shield") is not None),
        "created_at": r.created_at.isoformat(), "outcome": v.get("outcome"), "passed": v.get("passed"),
        "claim": (v.get("claim") or {}).get("kind"), "summary": v.get("summary"),
        "tool_calls": r.output.usage.tool_calls if r.output else None,
    }


def _job(jobs: dict[str, dict[str, Any]], kind: str, fn: Any) -> dict[str, str]:
    """Run `fn(job)` in a background thread; `fn` may write progress into the job dict."""
    from agentguard.core.models import new_id

    job_id = new_id(kind)
    job: dict[str, Any] = {"id": job_id, "kind": kind, "status": "running"}
    jobs[job_id] = job

    def work() -> None:
        try:
            fn(job)
            job["status"] = "done"
        except Exception as e:  # reported to the dashboard, not raised in a dead thread
            job.update(status="failed", error=f"{type(e).__name__}: {e}")

    threading.Thread(target=work, name=f"job-{job_id}", daemon=True).start()
    return {"job_id": job_id}
