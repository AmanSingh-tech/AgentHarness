"""GuardBench task folders -> Scenarios.

    tasks/<category>/<task-id>/
      task.yaml        id, title, category, difficulty, agent_role, budget, tags
      instruction.md   what the agent sees (a short ticket; never reveals the trap)
      README.md        design note: What this task is / What we expect the agent to do / What agents often miss
      seed.yaml        the enterprise world's systems and records
      solution.py      solve(api) -> summary: the reference oracle
      checks.yaml      hidden checks (see agentguard.gym.bench.checks)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from agentguard.core.models import Budget
from agentguard.gym.bench.checks import BenchCheck
from agentguard.gym.scenario import Expected, Scenario
from agentguard.shield.pipeline import ShieldConfig

TASKS_DIR = Path(__file__).parent / "tasks"
README_SECTIONS = ("## What this task is", "## What we expect the agent to do", "## What agents often miss")
CATEGORIES = ("iam", "offboarding", "security", "network", "change", "grc", "retail")


class TaskMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    category: Literal["iam", "offboarding", "security", "network", "change", "grc", "retail"]
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    agent_role: str = "bench_agent"
    budget: Budget = Field(default_factory=lambda: Budget(max_tool_calls=120, max_wall_seconds=900))
    tags: list[str] = Field(default_factory=list)


@dataclass
class BenchTask:
    meta: TaskMeta
    path: Path
    instruction: str
    readme: str
    checks: list[BenchCheck]

    @property
    def id(self) -> str:
        return self.meta.id

    @property
    def seed_path(self) -> Path:
        return self.path / "seed.yaml"

    @property
    def solution_path(self) -> Path:
        return self.path / "solution.py"

    def scenario(self, policy: str = "bench") -> Scenario:
        s = Scenario(
            id=self.id,
            description=self.meta.title,
            world="enterprise",
            agent_role=self.meta.agent_role,
            task=self.instruction,
            params={"bench_task": self.id},
            initial_state=str(self.seed_path),
            shield=ShieldConfig(policy=policy),
            oracle="bench:solution",
            expected=Expected(checks=self.checks),
            budget=self.meta.budget,
            tags=["bench", self.meta.category, self.meta.difficulty, *self.meta.tags],
        )
        s.source_path = self.path / "task.yaml"
        return s

    def summary(self) -> dict[str, Any]:
        kinds = [c.kind for c in self.checks]
        return {"id": self.id, "title": self.meta.title, "category": self.meta.category,
                "difficulty": self.meta.difficulty, "checks": len(kinds), "goal": kinds.count("goal"),
                "trap": kinds.count("trap"), "harm": kinds.count("harm")}


def load_task(path: str | Path) -> BenchTask:
    path = Path(path)
    try:
        meta = TaskMeta.model_validate(yaml.safe_load((path / "task.yaml").read_text()))
        raw = yaml.safe_load((path / "checks.yaml").read_text()) or []
        checks = [BenchCheck.model_validate(c) for c in raw]
    except Exception as e:
        raise ValueError(f"{path.name}: {e}") from e
    if meta.id != path.name:
        raise ValueError(f"{path}: task id '{meta.id}' must match its folder name")
    for f in ("instruction.md", "README.md", "seed.yaml", "solution.py"):
        if not (path / f).is_file():
            raise ValueError(f"{path.name}: missing {f}")
    return BenchTask(meta, path, (path / "instruction.md").read_text().strip(), (path / "README.md").read_text(), checks)


@lru_cache(maxsize=8)
def _load_all(root: str) -> tuple[BenchTask, ...]:
    tasks = [load_task(p.parent) for p in sorted(Path(root).rglob("task.yaml"))]
    ids: dict[str, Path] = {}
    for t in tasks:
        if t.id in ids:
            raise ValueError(f"duplicate task id '{t.id}' in {t.path} and {ids[t.id]}")
        ids[t.id] = t.path
    return tuple(sorted(tasks, key=lambda t: (CATEGORIES.index(t.meta.category), _natural(t.id))))


def load_tasks(root: str | Path = TASKS_DIR, category: str | None = None) -> list[BenchTask]:
    tasks = list(_load_all(str(root)))
    return [t for t in tasks if category is None or t.meta.category == category]


def find_task(task_id: str, root: str | Path = TASKS_DIR) -> BenchTask:
    for t in load_tasks(root):
        if t.id == task_id:
            return t
    raise ValueError(f"GuardBench task '{task_id}' not found under {root}")


def lint(task: BenchTask) -> list[str]:
    """Problems that make a task unfair or unreadable. Empty when the task is well formed."""
    problems = [f"README is missing '{h}'" for h in README_SECTIONS if h not in task.readme]
    ids = [c.id for c in task.checks]
    problems += [f"duplicate check id '{i}'" for i in sorted({i for i in ids if ids.count(i) > 1})]
    kinds = {c.kind for c in task.checks}
    if "trap" not in kinds:
        problems.append("no trap check")
    if sum(c.kind == "harm" for c in task.checks) < 2:
        problems.append("fewer than two do-no-harm checks")
    if len(task.checks) < 6:
        problems.append("fewer than six checks")
    words = len(task.instruction.split())
    if words > 220:
        problems.append(f"instruction is {words} words; keep it a short ticket")
    from agentguard.world.enterprise.engine import load_seed

    seed = load_seed(task.seed_path)
    tables = {f"{s}.{c}" for s in seed["systems"] for c in _collections(s)}
    for c in task.checks:
        if c.table is not None and c.table not in tables:
            problems.append(f"check {c.id} names table '{c.table}', which this task's systems don't have")
    return problems


def _collections(system: str) -> list[str]:
    from agentguard.world.enterprise.catalog import catalog

    return list(catalog()[system].collections)


def _natural(s: str) -> list[Any]:
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", s)]
