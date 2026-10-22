"""`agentguard bench`: GuardBench, ITSMBench-style enterprise tasks run through AgentShield."""

from __future__ import annotations

from typing import Optional

import typer

bench_app = typer.Typer(no_args_is_help=True, help="GuardBench: enterprise tasks with hidden checks, run through AgentShield.")


def _store():
    from agentguard.core.config import Settings
    from agentguard.core.store import Store

    return Store(Settings.from_env().db_url)


def _tasks(ids: list[str] | None, category: str | None):
    from agentguard.gym.bench.loader import find_task, load_tasks

    return [find_task(i) for i in ids] if ids else load_tasks(category=category)


@bench_app.command("list")
def bench_list(category: Optional[str] = typer.Option(None, "--category", "-c")) -> None:
    """List the tasks: id, category, difficulty, checks (goal / trap / harm) and title."""
    tasks = _tasks(None, category)
    for t in tasks:
        s = t.summary()
        typer.echo(f"{s['id']:<10} {s['category']:<12} {s['difficulty']:<7} "
                   f"{s['checks']:>3} ({s['goal']}/{s['trap']}/{s['harm']})  {s['title']}")
    typer.echo(f"{len(tasks)} task(s)")


@bench_app.command("show")
def bench_show(task_id: str, design: bool = typer.Option(False, "--design", help="Also print the design note and the checks")) -> None:
    """Print what the agent sees (and, with --design, what it is graded on)."""
    from agentguard.gym.bench.loader import find_task

    t = find_task(task_id)
    typer.echo(t.instruction)
    if design:
        typer.echo("\n" + "-" * 72 + "\n" + t.readme)
        for c in t.checks:
            typer.echo(f"  [{c.kind:<4}] {c.id}: {c.desc}")


@bench_app.command("run")
def bench_run(
    task_ids: list[str] = typer.Argument(None, help="Task ids (default: every task, or --category)"),
    category: Optional[str] = typer.Option(None, "--category", "-c"),
    agent: str = typer.Option("mcp_client:claude-code", "--agent", "-a", help="Harness spec, e.g. mcp_client:claude-code"),
    model: Optional[str] = typer.Option(None, "--model", "-m"),
    shield: bool = typer.Option(True, "--shield/--no-shield"),
    attempts: int = typer.Option(1, "--attempts", "-k", min=1),
    run_set: Optional[str] = typer.Option(None, "--run-set"),
) -> None:
    """Run tasks with one agent and print reward, score and harm per attempt."""
    from agentguard.gym.runner import run_scenario

    store = _store()
    run_set = run_set or f"bench-{agent.replace(':', '-')}-{model or 'default'}-{'shield' if shield else 'noshield'}"
    total = solved = 0
    for t in _tasks(task_ids, category):
        for k in range(attempts):
            r = run_scenario(t.scenario(), harness=agent, model=model, store=store, shield=shield, run_set=run_set)
            v, u = r.verdict, r.output.usage
            total, solved = total + 1, solved + (v.reward or 0)
            failed = [c.spec["id"] for c in v.checks if c.kind.startswith("bench:") and not c.ok]
            typer.echo(f"{t.id:<10} #{k + 1}  reward {v.reward}  score {v.score:.2f}  harm {'YES' if v.harm else 'no '}  "
                       f"{u.tool_calls:>3} calls  ${u.cost_usd:.3f}  {u.wall_time_s:.0f}s  {r.run_id}"
                       + (f"\n           missed: {', '.join(failed)}" if failed else ""))
    typer.echo(f"solved {solved}/{total} · run set {run_set}")


@bench_app.command("validate")
def bench_validate(
    task_ids: list[str] = typer.Argument(None),
    category: Optional[str] = typer.Option(None, "--category", "-c"),
) -> None:
    """The task gate: lint, the do-nothing agent scores 0, the reference solution scores 1 (shield off
    and on, never blocked), and its end state is deterministic."""
    from agentguard.core.store import Store
    from agentguard.gym.bench.validate import validate_task

    store = Store.in_memory()
    bad = 0
    tasks = _tasks(task_ids, category)
    for t in tasks:
        v = validate_task(t, store)
        typer.echo(f"{'ok ' if v.ok else 'BAD'} {t.id:<10} null {v.null_reward} ({v.null_score:.2f})  "
                   f"solution off {v.oracle_reward_off} / on {v.oracle_reward_on}")
        for p in v.problems:
            typer.echo(f"      - {p}")
        bad += not v.ok
    typer.echo(f"{len(tasks) - bad}/{len(tasks)} task(s) valid")
    if bad:
        raise typer.Exit(1)
