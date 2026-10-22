"""`agentguard` command-line interface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from agentguard.core.config import Settings
from agentguard.core.store import Store
from agentguard.core.tooling import EXPORTERS
from agentguard.harnesses import base as harness_registry
from agentguard.world import make_world

app = typer.Typer(no_args_is_help=True, help="AgentGuard: test and protect AI agents.")
world_app = typer.Typer(no_args_is_help=True, help="Inspect simulated worlds.")
app.add_typer(world_app, name="world")
policy_app = typer.Typer(no_args_is_help=True, help="Validate and inspect AgentShield policies.")
app.add_typer(policy_app, name="policy")
audit_app = typer.Typer(no_args_is_help=True, help="Check the tamper-evident audit log.")
app.add_typer(audit_app, name="audit")


@audit_app.command("verify")
def audit_verify(
    run_ids: list[str] = typer.Argument(None, help="Run ids (default: the most recent --limit runs)"),
    limit: int = typer.Option(100, "--limit"),
) -> None:
    """Recompute each run's hash chain and compare it with the head recorded at the end of the run."""
    store = _store()
    ids = list(run_ids or []) or [r.id for r in store.list_runs(limit=limit)]
    bad = 0
    for rid in ids:
        rep = store.verify_audit(rid)
        bad += not rep.ok
        mark = "ok  " if rep.ok else "FAIL"
        detail = f"{rep.events} events, head {rep.head[:12] if rep.head else '-'}" if rep.ok else \
            f"{rep.problem}" + (f" (at event #{rep.first_bad_seq})" if rep.first_bad_seq else "")
        typer.echo(f"{mark} {rid}  {detail}")
    typer.echo(f"\n{len(ids) - bad}/{len(ids)} runs verified")
    raise typer.Exit(1 if bad else 0)


@world_app.command("reset")
def world_reset(name: str = typer.Argument("support"), seed: int = typer.Option(42, "--seed")) -> None:
    """Reset a world and print its state summary (row counts per table)."""
    w = make_world(name)
    w.reset(seed)
    snap = w.snapshot()
    summary = {k: (len(v) if isinstance(v, list) else v) for k, v in snap.items()}
    typer.echo(json.dumps(summary, indent=2))


@world_app.command("tools")
def world_tools(
    name: str = typer.Argument("support"),
    fmt: str = typer.Option("summary", "--format", help="summary | anthropic | openai | gemini"),
) -> None:
    """List a world's tools, or export them as native function-calling schemas."""
    specs = make_world(name).tools()
    if fmt == "summary":
        for s in specs:
            labels = ",".join(l.value for l in s.returns_labels) or "-"
            flags = " irreversible" if s.irreversible else ""
            typer.echo(f"{s.name:16} {s.side_effect.value:9}{flags:13} labels={labels}")
        return
    if fmt not in EXPORTERS:
        raise typer.BadParameter(f"unknown format {fmt!r}")
    typer.echo(json.dumps([EXPORTERS[fmt](s) for s in specs], indent=2, ensure_ascii=False))


@app.command("harnesses")
def list_harnesses() -> None:
    """List registered harness types."""
    for key in harness_registry.available():
        typer.echo(key)


def _store() -> Store:
    return Store(Settings.from_env().db_url)


def _load(scenario: Optional[str], suite: Optional[Path]):
    from agentguard.gym.scenario import SCENARIOS_DIR, find_scenario, load_scenarios

    if bool(scenario) == bool(suite):
        raise typer.BadParameter("pass exactly one of --scenario or --suite")
    return [find_scenario(scenario)] if scenario else load_scenarios(suite or SCENARIOS_DIR)


@app.command("scenarios")
def list_scenarios(root: Optional[Path] = typer.Argument(None)) -> None:
    """List scenarios."""
    from agentguard.gym.scenario import SCENARIOS_DIR, load_scenarios

    for s in load_scenarios(root or SCENARIOS_DIR):
        typer.echo(f"{s.id:32} {s.expected.task_outcome:8} {','.join(s.tags)}")


@app.command("run")
def run(
    scenario: Optional[str] = typer.Option(None, "--scenario", help="Scenario id or YAML path"),
    suite: Optional[Path] = typer.Option(None, "--suite", help="Directory of scenarios"),
    harness: list[str] = typer.Option(["scripted:oracle"], "--harness", help="Repeatable"),
    model: list[str] = typer.Option([], "--model", help="Repeatable"),
    attempts: int = typer.Option(1, "--attempts", min=1),
    parallel: int = typer.Option(4, "--parallel", min=1),
    agent_version: Optional[str] = typer.Option(None, "--agent-version"),
    run_set: Optional[str] = typer.Option(None, "--run-set", help="Label these runs, e.g. for promote/compare"),
    show_trace: bool = typer.Option(False, "--trace", help="Print the trace of each run"),
    shield: bool = typer.Option(True, "--shield/--no-shield", help="Run with or without AgentShield"),
) -> None:
    """Run scenarios x harnesses x models x attempts and print verified results."""
    from agentguard.gym.faults import fault_log
    from agentguard.gym.runner import run_matrix

    store = _store()
    scenarios = _load(scenario, suite)
    result = run_matrix(
        scenarios, harness, store=store, models=model or [None], attempts=attempts,
        parallel=parallel, agent_version=agent_version, shield=shield, run_set=run_set,
    )
    failed = 0
    for cell in result.cells:
        combo = f"{cell.harness}" + (f" / {cell.model}" if cell.model else "")
        mark = "PASS" if cell.pass_k else "FAIL"
        failed += not cell.pass_k
        typer.echo(f"[{mark}] {cell.scenario_id:32} {combo:24} pass^{len(cell.runs)}: {cell.pass_count}/{len(cell.runs)}")
        for r in cell.runs:
            v = r.verdict
            typer.echo(f"         {r.run_id}  {v.outcome.value}")
            trace = store.get_trace(r.run_id)
            for ev in trace:
                if ev.kind.value == "decision" and ev.payload["type"] != "ALLOW":
                    p = ev.payload
                    typer.echo(f"         shield: {p['type']} {p['tool']} [{p['rule_id']}, {p['risk']}] {p['reason']}")
            faults = fault_log(trace)
            if faults:
                typer.echo("         faults: " + ", ".join(f"{f['fault']}@{f['tool']}#{f['tool_call']}" for f in faults))
            if not v.passed:
                typer.echo(f"         {v.summary}")
            if r.output.exit_reason == "crashed":
                typer.echo(f"         agent crashed: {r.output.final_message.splitlines()[0][:300]}")
            if show_trace:
                for ev in store.get_trace(r.run_id):
                    typer.echo(f"           #{ev.seq:<3} {ev.kind.value:13} "
                               f"{json.dumps(ev.payload, ensure_ascii=False, default=str)[:140]}")
    typer.echo(f"\n{len(result.cells) - failed}/{len(result.cells)} combinations reliable (pass^{attempts})")
    raise typer.Exit(1 if failed else 0)


@app.command("validate-scenarios")
def validate(
    root: Optional[Path] = typer.Argument(None, help="Scenario file or directory (default: built-in suite)"),
    parallel: int = typer.Option(4, "--parallel", min=1),
    shield: bool = typer.Option(True, "--shield/--no-shield", help="Validate with or without AgentShield"),
) -> None:
    """Check every scenario fails for the null agent and passes for its oracle."""
    from agentguard.gym.runner import validate_scenarios
    from agentguard.gym.scenario import SCENARIOS_DIR, load_scenarios

    rows = validate_scenarios(load_scenarios(root or SCENARIOS_DIR), store=_store(), parallel=parallel, shield=shield)
    for row in rows:
        mark = "ok  " if row.valid else "BAD "
        typer.echo(f"{mark} {row.scenario_id:32} null={row.null.outcome.value:26} oracle={row.oracle.outcome.value}")
        if not row.valid:
            if row.null.passed:
                typer.echo(f"     null agent passed: {row.null.summary}")
            if not row.oracle.passed:
                typer.echo(f"     oracle failed: {row.oracle.summary}")
    bad = sum(not r.valid for r in rows)
    typer.echo(f"\n{len(rows) - bad}/{len(rows)} scenarios valid")
    raise typer.Exit(1 if bad else 0)


@app.command("diagnose")
def diagnose_cmd(run_id: str = typer.Argument(...)) -> None:
    """Explain where a run went wrong, compared with the scenario's reference agent."""
    from agentguard.gym.diagnose import diagnose

    d = diagnose(run_id, _store())
    for line in d.summary:
        typer.echo(line)
    if d.oracle_run_id:
        typer.echo(f"(reference run: {d.oracle_run_id})")


@app.command("promote")
def promote_cmd(
    run_ids: list[str] = typer.Argument(None, help="Run ids to promote"),
    run_set: Optional[str] = typer.Option(None, "--run-set", help="Promote every failed or blocked run in this run set"),
    out_dir: Optional[Path] = typer.Option(None, "--out", help="Where to write (default: the built-in regression suite)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate but do not write"),
) -> None:
    """Turn failed or blocked runs into validated regression scenarios."""
    from agentguard.gym.regression import REGRESSION_DIR, promote

    store = _store()
    ids = list(run_ids or [])
    if run_set:
        ids += [r.id for r in store.list_runs(limit=100_000) if r.config.get("run_set") == run_set]
    if not ids:
        raise typer.BadParameter("give run ids or --run-set")
    accepted = 0
    for rid in ids:
        p = promote(rid, store, out_dir=out_dir or REGRESSION_DIR, write=not dry_run)
        accepted += p.accepted
        mark = "NEW " if p.accepted else "skip"
        typer.echo(f"{mark} {rid}: {p.reason}" + (f" -> {p.path}" if p.accepted and p.path else ""))
    typer.echo(f"\n{accepted} regression scenario(s) {'validated' if dry_run else 'written'}")


@app.command("benchmark")
def benchmark_cmd(
    agent: list[str] = typer.Option(["scripted:naive", "scripted:naive_v2"], "--agent", help="Repeatable"),
    attempts: int = typer.Option(3, "--attempts", min=1),
    parallel: int = typer.Option(8, "--parallel", min=1),
    out: Path = typer.Option(Path("reports"), "--out"),
) -> None:
    """Run the MVP benchmark (agents x shield off/on x attempts) and write a report."""
    from agentguard.gym.benchmark import run_benchmark, to_markdown, write_report

    report = run_benchmark(_store(), agents=agent, attempts=attempts, parallel=parallel)
    json_path, md_path = write_report(report, out)
    typer.echo(to_markdown(report))
    typer.echo(f"Report: {md_path} and {json_path}")
    typer.echo("Run sets: " + ", ".join(report["run_sets"]))


@app.command("compare")
def compare_cmd(run_set_a: str = typer.Argument(...), run_set_b: str = typer.Argument(...)) -> None:
    """Compare two run sets on the headline outcomes."""
    from agentguard.gym.compare import compare

    rows = compare(_store(), run_set_a, run_set_b)
    typer.echo(f"{'outcome':34} {'A':>10} {'B':>10} {'delta':>9}")
    for r in rows:
        mark = {True: " better", False: " worse", None: ""}[r["better"]]
        typer.echo(f"{r['metric']:34} {_cell(r[run_set_a]):>10} {_cell(r[run_set_b]):>10} {_cell(r['delta']):>9}{mark}")
    typer.echo(f"A = {run_set_a}\nB = {run_set_b}")


def _cell(v) -> str:
    return "n/a" if v is None else str(v)


@app.command("demo")
def demo_cmd(
    regression_out: Optional[Path] = typer.Option(None, "--regression-out",
                                                  help="Where promoted scenarios go (default: a temp dir)"),
) -> None:
    """Run the end-to-end demo script (normal, timeout, false success, injection, exfiltration, regression)."""
    from agentguard.gym.demo import run_demo

    def show(step) -> None:
        status = typer.style("OK  ", fg="green") if step.ok else typer.style("FAIL", fg="red")
        typer.echo(f"\n{status} Step {step.number}: {step.title}")
        typer.echo(f"     expect: {step.expectation}")
        for r in step.runs:
            extra = f" refunds={r.refunds}" if r.refunds is not None else ""
            typer.echo(f"     {r.harness} shield={'on' if r.shield else 'off'} -> {r.outcome} "
                       f"(claimed {r.claim}){extra} emails={r.emails}  [{r.run_id}]")
            for stop in r.stops:
                typer.echo(f"       {stop[:220]}")
        for n in step.notes:
            typer.echo(f"     {n}")
        for row in step.table:
            a, b = [v for k, v in row.items() if k not in ("metric", "delta", "better")]
            typer.echo(f"     {row['metric']:34} v1={_cell(a):>8}  v2={_cell(b):>8}")

    steps = run_demo(_store(), regression_out, on_step=show)
    bad = [s.number for s in steps if not s.ok]
    typer.echo(f"\n{len(steps) - len(bad)}/{len(steps)} demo steps behaved as expected")
    raise typer.Exit(1 if bad else 0)


@app.command("metrics")
def metrics(
    group_by: str = typer.Option("harness,model,agent_version", "--group-by",
                                 help="Comma-separated: harness, model, agent_version, scenario"),
    limit: int = typer.Option(1000, "--limit", help="Most recent N runs"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Reliability, security, performance and governance metrics over stored runs."""
    from agentguard.gym.metrics import compute_metrics

    store = _store()
    rows = compute_metrics(store, store.list_runs(limit=limit), tuple(f.strip() for f in group_by.split(",") if f.strip()))
    if as_json:
        typer.echo(json.dumps(rows, indent=2, default=str))
        return
    for row in rows:
        g = ", ".join(f"{k}={v}" for k, v in row["group"].items())
        rel, sec, perf, gov = row["reliability"], row["security"], row["performance"], row["governance"]
        typer.echo(f"{g}  ({row['runs']} runs)")
        typer.echo(f"  reliability  success={rel['task_success_rate']} pass^k={rel['pass_k']} "
                   f"recovery={rel['failure_recovery_rate']} false-success={rel['incorrect_success_claim_rate']}")
        typer.echo(f"  security     blocks={sec['blocks_by_rule']} injections={sec['injections_detected']} "
                   f"exfil-stopped={sec['exfiltration_attempts_stopped']} violations={sec['policy_violations_attempted']}")
        typer.echo(f"  performance  p50={perf['latency_p50_s']}s p95={perf['latency_p95_s']}s "
                   f"calls/task={perf['tool_calls_per_task']} tokens={perf['input_tokens']}/{perf['output_tokens']} "
                   f"cost=${perf['cost_usd']} per-success=${perf['cost_per_successful_task_usd']}")
        typer.echo(f"  governance   approvals={gov['approvals_requested']} (granted {gov['approvals_granted']}, "
                   f"rejected {gov['approvals_rejected']}) high-risk={gov['high_risk_actions']} "
                   f"audit={gov['audit_completeness']} explained-blocks={gov['blocks_with_explanation']}")


@app.command("mcp-serve")
def mcp_serve(
    scenario: str = typer.Option(..., "--scenario", help="Scenario id or YAML path"),
    shield: bool = typer.Option(True, "--shield/--no-shield"),
    client: str = typer.Option("external", "--client", help="Label for the connecting agent, e.g. claude-code"),
    run_set: Optional[str] = typer.Option(None, "--run-set"),
) -> None:
    """Serve one scenario run over MCP (stdio). The run is verified when the client disconnects.

    Example: claude mcp add agentguard -- agentguard mcp-serve --scenario ticket_prompt_injection
    """
    from agentguard.gym.scenario import find_scenario
    from agentguard.transports.mcp_proxy import serve_scenario_stdio

    serve_scenario_stdio(find_scenario(scenario), _store(), shield=shield, client=client, run_set=run_set)


@app.command("serve")
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
    reports: Path = typer.Option(Path("reports"), "--reports", help="Where benchmark reports are read and written"),
) -> None:
    """Start the API server and the dashboard."""
    import uvicorn

    from agentguard.server.app import DASHBOARD_DIST, create_app

    if not DASHBOARD_DIST.is_dir():
        typer.echo("Dashboard not built (cd dashboard && npm install && npm run build); serving the API only.")
    typer.echo(f"AgentGuard on http://{host}:{port}")
    uvicorn.run(create_app(_store(), reports_dir=reports), host=host, port=port, log_level="warning")


@app.command("protect")
def protect(
    backend: Path = typer.Option(..., "--backend", exists=True, dir_okay=False, help="HTTP backend config (YAML)"),
    agent_id: str = typer.Option(..., "--agent-id", help="The agent's identity in the policy, e.g. support_agent"),
    policy: str = typer.Option("default", "--policy"),
    client: str = typer.Option("external", "--client", help="Label for the connecting agent"),
    task: Optional[str] = typer.Option(None, "--task", help="What the agent was asked (scanned; kept for promotion)"),
    approval_timeout: float = typer.Option(300.0, "--approval-timeout"),
) -> None:
    """Production mode: serve a real backend over MCP (stdio) with AgentShield in front of it.

    Approvals wait for a decision in the dashboard (agentguard serve, same database).
    Example: claude mcp add guarded -- agentguard protect --backend examples/payments_backend.yaml --agent-id support_agent
    """
    import sys

    import anyio

    from agentguard.backends.http import HttpBackendConfig, HttpToolBackend
    from agentguard.runtime import RuntimeSession
    from agentguard.shield.approvals import ApprovalQueue, AutoApprover
    from agentguard.transports.mcp_proxy import build_server, output_from_submission

    store = _store()
    cfg = HttpBackendConfig.load(backend)
    session = RuntimeSession(HttpToolBackend(cfg), store, agent_id=agent_id, policy=policy, client=client, task=task,
                             backend_config=cfg.model_dump(mode="json"),
                             approvals=ApprovalQueue(store, auto=AutoApprover(default="manual"),
                                                     timeout_s=approval_timeout))
    submitted: dict = {}
    server = build_server(session.endpoint, on_submit=submitted.update)

    async def main() -> None:
        from mcp.server.stdio import stdio_server

        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    try:
        anyio.run(main)
    finally:
        from agentguard.core.models import Usage

        rec = session.close(output_from_submission(submitted, "MCP client disconnected.", Usage()))
        print(f"agentguard: runtime session {rec.id} closed ({rec.output.usage.tool_calls} calls)", file=sys.stderr)


@policy_app.command("validate")
def policy_validate(path: Path = typer.Argument(..., exists=True, dir_okay=False)) -> None:
    """Validate a policy file; errors point at the YAML line."""
    from agentguard.shield.policy import PolicyError, load_policy

    try:
        p = load_policy(path)
    except PolicyError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1)
    typer.echo(f"ok  {path}: {len(p.agents)} agents, {len(p.rules)} rules, {len(p.sequences)} sequences")


@policy_app.command("show")
def policy_show(ref: str = typer.Argument("default", help="Built-in policy name or path")) -> None:
    """Summarise what each agent may do under a policy."""
    from agentguard.shield.policy import load_policy

    p = load_policy(ref)
    for agent_id, agent in p.agents.items():
        typer.echo(f"{agent_id}: {agent.description}")
        for tool, perm in agent.tools.items():
            extras = perm.model_dump(exclude_defaults=True, exclude={"allow"})
            typer.echo(f"  {'allow' if perm.allow else 'DENY ':5} {tool:16} {extras or ''}")
    for r in p.rules:
        typer.echo(f"rule {r.id} on {r.when.tool}: {r.check} -> {r.on_fail.value} ({r.risk.value})")
    for q in p.sequences:
        typer.echo(f"sequence {q.id}: {[l.value for l in q.sources]} -> {q.sinks} via {q.through_transforms} "
                   f"-> {q.on_match.value} ({q.risk.value})")


if __name__ == "__main__":
    app()
