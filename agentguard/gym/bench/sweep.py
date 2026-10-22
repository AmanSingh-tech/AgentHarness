"""GuardBench sweeps: every task x agent x model x shield setting x attempt, like ITSMBench's run configs.

    # configs/bench/claude.yaml
    name: claude
    attempts: 3
    parallel: 2
    shield: [off, on]
    tasks: all                 # or a list of task ids / categories
    agents:
      - {harness: mcp_client:claude-code, model: haiku}
      - {harness: mcp_client:claude-code, model: sonnet}
"""

from __future__ import annotations

import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from agentguard.core.store import Store
from agentguard.gym.bench.loader import CATEGORIES, load_tasks
from agentguard.gym.bench.report import run_set_name
from agentguard.gym.runner import run_scenario


class AgentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    harness: str
    model: str | None = None


class SweepConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    agents: list[AgentSpec]
    attempts: int = Field(1, ge=1)
    parallel: int = Field(2, ge=1)
    shield: list[Literal["off", "on"]] = Field(default_factory=lambda: ["on"])
    tasks: str | list[str] = "all"

    @field_validator("shield", mode="before")
    @classmethod
    def _yaml_booleans(cls, v):
        # YAML 1.1 reads bare on/off as true/false
        return [("on" if x else "off") if isinstance(x, bool) else x for x in (v if isinstance(v, list) else [v])]

    @field_validator("name")
    @classmethod
    def _safe(cls, v: str) -> str:
        if "/" in v or not v.strip():
            raise ValueError("a sweep name is a single word (no '/')")
        return v

    @classmethod
    def load(cls, path: str | Path) -> "SweepConfig":
        return cls.model_validate(yaml.safe_load(Path(path).read_text()))

    def selected_tasks(self):
        tasks = load_tasks()
        if self.tasks == "all":
            return tasks
        wanted = set([self.tasks] if isinstance(self.tasks, str) else self.tasks)
        unknown = wanted - {t.id for t in tasks} - set(CATEGORIES)
        if unknown:
            raise ValueError(f"unknown tasks or categories: {sorted(unknown)}")
        return [t for t in tasks if t.id in wanted or t.meta.category in wanted]

    def runs(self) -> int:
        return len(self.selected_tasks()) * len(self.agents) * len(self.shield) * self.attempts


def run_sweep(cfg: SweepConfig, store: Store, progress=print, resume: bool = False) -> list[str]:
    """Run the whole sweep, printing one line per finished run; returns the run sets written.

    With `resume`, attempts already stored (with a verdict) for a run set and task are skipped, so an
    interrupted sweep continues where it stopped. A run that crashes is reported and the sweep goes on."""
    tasks = cfg.selected_tasks()
    jobs = []
    for agent in cfg.agents:
        for shield in cfg.shield:
            rs = run_set_name(cfg.name, agent.harness, agent.model, shield == "on")
            done = Counter()
            if resume:
                for r in store.list_runs(limit=1_000_000):
                    if (r.config or {}).get("run_set") == rs and r.verdict:
                        done[r.scenario_id] += 1
            for t in tasks:
                jobs += [(rs, agent, shield == "on", t)] * max(0, cfg.attempts - done[t.id])
    total = len(jobs)
    progress(f"{total} run(s) to do" + (" (resuming)" if resume else ""))
    lock = threading.Lock()
    finished = 0

    def one(job) -> None:
        nonlocal finished
        rs, agent, shield, task = job
        try:
            r = run_scenario(task.scenario(), harness=agent.harness, model=agent.model, store=store, shield=shield,
                             run_set=rs)
            v, u = r.verdict, r.output.usage
            line = (f"{task.id:<7} {'solved' if v.reward else 'missed'}  score {v.score:.2f}  "
                    f"{'HARM  ' if v.harm else ''}${u.cost_usd:.3f}  {u.wall_time_s:.0f}s")
        except Exception as e:  # keep the sweep going; the failure is visible in the log
            line = f"{task.id:<7} ERROR {type(e).__name__}: {e}"[:200]
        with lock:
            finished += 1
            progress(f"[{finished}/{total}] {rs.removeprefix('bench/')}  {line}")

    with ThreadPoolExecutor(max_workers=cfg.parallel) as pool:
        list(pool.map(one, jobs))
    return sorted({rs for rs, *_ in jobs})
