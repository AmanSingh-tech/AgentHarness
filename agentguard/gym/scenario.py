"""Scenario format: world + initial state + task + faults + expected end state."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agentguard.core.models import Budget, TaskSpec
from agentguard.gym.faults import FaultSpec, FaultType  # noqa: F401  (re-exported)
from agentguard.shield.pipeline import ShieldConfig
from agentguard.world import WORLDS, World, make_world

SCENARIOS_DIR = Path(__file__).parent / "scenarios"


# -- expectations -------------------------------------------------------------
# Every non-`count` field is an equality filter (or a *_contains substring
# filter); `count` is the exact number of matching rows required at the end.


class _Expect(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LedgerExpect(_Expect):
    order_id: str | None = None
    customer_id: str | None = None
    type: str | None = None
    amount_inr: int | None = None
    status: str | None = None
    count: int = 1


class TicketExpect(_Expect):
    id: str
    status: str | None = None
    notes_contains: str | None = None


class OrderExpect(_Expect):
    id: str
    status: str | None = None


class OutboxExpect(_Expect):
    to_contains: str | None = None
    subject_contains: str | None = None
    body_contains: str | None = None
    count: int = 1


class RowsExpect(_Expect):
    """Any world: `count` rows of `table` match every field in `match` (and contain `contains`)."""

    table: str
    match: dict[str, Any] = Field(default_factory=dict)
    contains: dict[str, str] = Field(default_factory=dict)
    count: int = 1


class RecordExpect(_Expect):
    """Any world: the record `id` of `table` has these field values (and substrings)."""

    table: str
    id: str
    match: dict[str, Any] = Field(default_factory=dict)
    contains: dict[str, str] = Field(default_factory=dict)


class ForbiddenExpect(_Expect):
    tool_called: str
    args_match: str | None = None  # regex over the JSON-encoded arguments


class Expected(_Expect):
    # success: the task should be completed. refuse: the correct behaviour is to
    # make no change and honestly report that it cannot be done.
    task_outcome: Literal["success", "refuse"] = "success"
    ledger: list[LedgerExpect] = Field(default_factory=list)
    tickets: list[TicketExpect] = Field(default_factory=list)
    orders: list[OrderExpect] = Field(default_factory=list)
    outbox: list[OutboxExpect] = Field(default_factory=list)
    rows: list[RowsExpect] = Field(default_factory=list)
    records: list[RecordExpect] = Field(default_factory=list)
    forbidden: list[ForbiddenExpect] = Field(default_factory=list)


class ClaimRules(_Expect):
    must_not_claim_success_if_failed: bool = True


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    description: str = ""
    world: str = "support"
    seed: int = 42
    agent_role: str = "support_agent"
    task: str
    params: dict[str, Any] = Field(default_factory=dict)  # structured slots for scripted agents
    initial_state: str | None = None
    faults: list[FaultSpec] = Field(default_factory=list)
    shield: ShieldConfig = Field(default_factory=ShieldConfig)
    # The reference agent that must pass this scenario in validate-scenarios.
    oracle: str = "scripted:oracle"
    expected: Expected
    claims: ClaimRules = Field(default_factory=ClaimRules)
    budget: Budget = Field(default_factory=Budget)
    tags: list[str] = Field(default_factory=list)

    source_path: Path | None = Field(default=None, exclude=True)

    @field_validator("world")
    @classmethod
    def _known_world(cls, v: str) -> str:
        if v not in WORLDS:
            raise ValueError(f"unknown world '{v}' (available: {sorted(WORLDS)})")
        return v

    @model_validator(mode="after")
    def _faults_target_real_tools(self) -> "Scenario":
        tools = {t.name for t in WORLDS[self.world]().tools()}
        unknown = sorted({f.tool for f in self.faults} - tools)
        if unknown:
            raise ValueError(f"faults target unknown tool(s) {unknown} (world '{self.world}' has {sorted(tools)})")
        return self

    @property
    def task_spec(self) -> TaskSpec:
        return TaskSpec(text=self.task, params=self.params, agent_role=self.agent_role)

    def fixture_path(self) -> Path | None:
        if self.initial_state is None:
            return None
        p = Path(self.initial_state)
        world_dir = WORLDS[self.world].fixtures_dir
        candidates = [p] if p.is_absolute() else []
        if self.source_path is not None:
            candidates.append(self.source_path.parent / p)
        candidates += [world_dir.parent / p, world_dir / p.name]
        for c in candidates:
            if c.is_file():
                return c
        raise FileNotFoundError(f"scenario {self.id}: initial_state '{self.initial_state}' not found")

    def build_world(self) -> World:
        fixture = self.fixture_path()
        return make_world(self.world, **({"fixture": fixture} if fixture else {}))

    @classmethod
    def load(cls, path: str | Path) -> "Scenario":
        path = Path(path)
        data = yaml.safe_load(path.read_text())
        try:
            scenario = cls.model_validate(data)
        except Exception as e:
            raise ValueError(f"{path}: {e}") from e
        scenario.source_path = path
        return scenario


def load_scenarios(root: str | Path = SCENARIOS_DIR) -> list[Scenario]:
    """Load every *.yaml under `root` (recursively), sorted by id. Ids must be unique."""
    root = Path(root)
    files = [root] if root.is_file() else sorted(root.rglob("*.yaml"))
    scenarios = [Scenario.load(f) for f in files]
    seen: dict[str, Path | None] = {}
    for s in scenarios:
        if s.id in seen:
            raise ValueError(f"duplicate scenario id '{s.id}' in {s.source_path} and {seen[s.id]}")
        seen[s.id] = s.source_path
    return sorted(scenarios, key=lambda s: s.id)


def find_scenario(ref: str, root: str | Path = SCENARIOS_DIR) -> Scenario:
    """Resolve a scenario by file path or by id."""
    p = Path(ref)
    if p.suffix in (".yaml", ".yml") and p.is_file():
        return Scenario.load(p)
    for s in load_scenarios(root):
        if s.id == ref:
            return s
    raise ValueError(f"scenario '{ref}' not found under {root}")
