"""The MVP benchmark: agents x shield off/on x k attempts over the refund suite.

    agentguard benchmark --agent scripted:naive --agent scripted:naive_v2 --attempts 3

Each agent/shield combination is stored as a run set named "<agent>|shield-<on|off>|<stamp>",
so it can be compared later with `agentguard compare`. The report (JSON + markdown)
holds the headline outcomes from gym/compare.py for every combination.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from agentguard.core.store import Store
from agentguard.gym.compare import HEADLINE, headline, summarise_set
from agentguard.gym.runner import run_matrix
from agentguard.gym.scenario import Scenario, load_scenarios

DEFAULT_AGENTS = ("scripted:naive", "scripted:naive_v2")


def benchmark_suite() -> list[Scenario]:
    """Scenarios whose reference agent is the refund oracle, i.e. tasks a refund agent should do.
    (Red-team scenarios such as secret_exfiltration use their own agents.)"""
    return [s for s in load_scenarios() if s.oracle == "scripted:oracle"]


def run_benchmark(
    store: Store,
    agents: Sequence[str] = DEFAULT_AGENTS,
    attempts: int = 3,
    shield_modes: Sequence[bool] = (False, True),
    scenarios: list[Scenario] | None = None,
    parallel: int = 8,
    stamp: str | None = None,
    models: Sequence[str | None] = (None,),
) -> dict[str, Any]:
    """`models` applies to model-driven agents (native:*, langgraph:*, mcp_client:*); each
    agent x model x shield combination becomes one run set."""
    scenarios = scenarios if scenarios is not None else benchmark_suite()
    stamp = stamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sets: dict[str, dict[str, Any]] = {}
    for agent in agents:
        agent_models = (None,) if agent.startswith("scripted:") else models
        for model in agent_models:
            for shield in shield_modes:
                label = agent.split(":")[-1] + (f"@{model}" if model else "")
                name = f"{label}|shield-{'on' if shield else 'off'}|{stamp}"
                run_matrix(scenarios, [agent], store=store, models=[model], attempts=attempts, parallel=parallel,
                           shield=shield, run_set=name, agent_version=agent)
                row = summarise_set(store, name)
                sets[name] = {"agent": agent, "model": model, "shield": shield, "runs": row["runs"],
                              "headline": headline(row), "blocks_by_rule": row["security"]["blocks_by_rule"],
                              "cost_usd": row["performance"]["cost_usd"],
                              "tool_calls_per_task": row["performance"]["tool_calls_per_task"]}
    return {
        "created": stamp,
        "scenarios": [s.id for s in scenarios],
        "regression_scenarios": sum("regression" in s.tags for s in scenarios),
        "attempts": attempts,
        "run_sets": sets,
    }


def write_report(report: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / f"benchmark-{report['created']}"
    json_path, md_path = base.with_suffix(".json"), base.with_suffix(".md")
    json_path.write_text(json.dumps(report, indent=2, default=str))
    md_path.write_text(to_markdown(report))
    return json_path, md_path


def to_markdown(report: dict[str, Any]) -> str:
    sets = report["run_sets"]
    cols = [f"{v['agent'].split(':')[-1]}{' (' + v['model'] + ')' if v.get('model') else ''}, "
            f"shield {'on' if v['shield'] else 'off'}" for v in sets.values()]
    lines = [
        f"# AgentGuard benchmark {report['created']}",
        "",
        f"{len(report['scenarios'])} scenarios ({report['regression_scenarios']} regression) x "
        f"{report['attempts']} attempts per combination.",
        "",
        "| Outcome | " + " | ".join(cols) + " |",
        "|---|" + "---|" * len(cols),
    ]
    for _, _, label, _ in HEADLINE:
        lines.append(f"| {label} | " + " | ".join(_fmt(v["headline"][label]) for v in sets.values()) + " |")
    lines.append("| Cost (USD) | " + " | ".join(_num(v.get("cost_usd"), "${:.4f}") for v in sets.values()) + " |")
    lines.append("| Tool calls per task | " + " | ".join(_num(v.get("tool_calls_per_task"), "{:.1f}")
                                                       for v in sets.values()) + " |")
    lines += ["", "Blocks by rule:", ""]
    for name, v in sets.items():
        if v["blocks_by_rule"]:
            lines.append(f"- {name.rsplit('|', 1)[0]}: " + ", ".join(f"{k} x{n}" for k, n in v["blocks_by_rule"].items()))
    return "\n".join(lines) + "\n"


def _fmt(v: Any) -> str:
    """Headline values: floats are rates, ints are counts."""
    if v is None:
        return "n/a"
    return f"{v:.0%}" if isinstance(v, float) else str(v)


def _num(v: Any, fmt: str) -> str:
    return "n/a" if v is None else fmt.format(v)
