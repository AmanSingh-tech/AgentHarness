"""The GuardBench task gate: a task ships only if it is well formed, the do-nothing agent scores 0,
the reference solution scores 1 with AgentShield off and on (and is never blocked), and the
solution's end state is deterministic."""

from __future__ import annotations

from dataclasses import dataclass, field

from agentguard.core.models import TraceKind
from agentguard.core.store import Store
from agentguard.gym.bench.loader import BenchTask, lint
from agentguard.gym.runner import run_scenario


@dataclass
class TaskValidation:
    task_id: str
    lint: list[str] = field(default_factory=list)
    null_reward: int | None = None
    null_score: float | None = None
    oracle_reward_off: int | None = None
    oracle_reward_on: int | None = None
    oracle_blocks: int = 0
    deterministic: bool = True
    failed_oracle_checks: list[str] = field(default_factory=list)

    @property
    def problems(self) -> list[str]:
        p = list(self.lint)
        if self.null_reward != 0:
            p.append("the do-nothing agent passes: the checks don't require any work")
        if self.oracle_reward_off != 1:
            p.append(f"the reference solution fails without the shield: {self.failed_oracle_checks}")
        if self.oracle_reward_on != 1:
            p.append("the reference solution fails with the shield on")
        if self.oracle_blocks:
            p.append(f"AgentShield blocked the reference solution {self.oracle_blocks} time(s)")
        if not self.deterministic:
            p.append("two runs of the reference solution end in different states")
        return p

    @property
    def ok(self) -> bool:
        return not self.problems


def validate_task(task: BenchTask, store: Store) -> TaskValidation:
    v = TaskValidation(task.id, lint=lint(task))
    scenario = task.scenario()
    null = run_scenario(scenario, harness="scripted:null", store=store, shield=False, run_set="bench-validate").verdict
    v.null_reward, v.null_score = null.reward, null.score
    off = run_scenario(scenario, harness="bench:solution", store=store, shield=False, run_set="bench-validate")
    v.oracle_reward_off = off.verdict.reward
    v.failed_oracle_checks = [c.spec["id"] for c in off.verdict.checks if c.kind.startswith("bench:") and not c.ok]
    on = run_scenario(scenario, harness="bench:solution", store=store, shield=True, run_set="bench-validate")
    v.oracle_reward_on = on.verdict.reward
    v.oracle_blocks = sum(1 for e in store.get_trace(on.run_id)
                          if e.kind == TraceKind.DECISION and e.payload.get("type") == "BLOCK")
    again = run_scenario(scenario, harness="bench:solution", store=store, shield=False, run_set="bench-validate")
    v.deterministic = again.snapshot == off.snapshot
    return v
