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

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from agentguard.core.store import Store
from agentguard.gym.bench.loader import CATEGORIES, load_tasks
from agentguard.gym.bench.report import run_set_name
from agentguard.gym.runner import run_matrix


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


def run_sweep(cfg: SweepConfig, store: Store, progress=print) -> list[str]:
    """Run the whole sweep; returns the run sets written."""
    scenarios = [t.scenario() for t in cfg.selected_tasks()]
    run_sets = []
    for agent in cfg.agents:
        for shield in cfg.shield:
            rs = run_set_name(cfg.name, agent.harness, agent.model, shield == "on")
            progress(f"{rs}: {len(scenarios)} tasks x {cfg.attempts} attempt(s)")
            run_matrix(scenarios, [agent.harness], store=store, models=[agent.model], attempts=cfg.attempts,
                       parallel=cfg.parallel, shield=shield == "on", run_set=rs)
            run_sets.append(rs)
    return run_sets
