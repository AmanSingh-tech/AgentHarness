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
    show_trace: bool = typer.Option(False, "--trace", help="Print the trace of each run"),
) -> None:
    """Run scenarios x harnesses x models x attempts and print verified results."""
    from agentguard.gym.faults import fault_log
    from agentguard.gym.runner import run_matrix

    store = _store()
    scenarios = _load(scenario, suite)
    result = run_matrix(
        scenarios, harness, store=store, models=model or [None], attempts=attempts,
        parallel=parallel, agent_version=agent_version,
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
            faults = fault_log(store.get_trace(r.run_id))
            if faults:
                typer.echo("         faults: " + ", ".join(f"{f['fault']}@{f['tool']}#{f['tool_call']}" for f in faults))
            if not v.passed:
                typer.echo(f"         {v.summary}")
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
) -> None:
    """Check every scenario fails for the null agent and passes for the oracle."""
    from agentguard.gym.runner import validate_scenarios
    from agentguard.gym.scenario import SCENARIOS_DIR, load_scenarios

    rows = validate_scenarios(load_scenarios(root or SCENARIOS_DIR), store=_store(), parallel=parallel)
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


if __name__ == "__main__":
    app()
