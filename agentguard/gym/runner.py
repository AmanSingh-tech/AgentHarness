"""Execute agents against tasks and scenarios.

- `run_once`: one agent, one task, one freshly reset world.
- `run_scenario`: `run_once` for a Scenario, followed by independent verification.
- `run_matrix`: scenarios x harnesses x models x attempts, in parallel, with pass^k.
- `validate_scenarios`: every scenario must fail for the null agent and pass for the oracle.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from agentguard.core.events import EventBus, Tracer
from agentguard.core.models import (
    AgentOutput,
    Budget,
    RunContext,
    RunRecord,
    RunStatus,
    TaskSpec,
    TraceKind,
    Usage,
    new_id,
)
from agentguard.core.store import Store
from agentguard.gym.faults import FaultInjector
from agentguard.gym.scenario import Scenario
from agentguard.gym.verifier import Verdict, verify
from agentguard.harnesses.base import make_harness
from agentguard.shield.gateway import FaultHook, Gateway
from agentguard.transports.inprocess import InProcessEndpoint
from agentguard.world import World, make_world


class RunResult:
    def __init__(self, record: RunRecord, world: World, initial_snapshot: dict[str, Any]) -> None:
        self.record = record
        self.world = world  # kept live so callers can use ground-truth helpers
        self.initial_snapshot = initial_snapshot
        self.verdict: Verdict | None = None

    @property
    def run_id(self) -> str:
        return self.record.id

    @property
    def output(self) -> AgentOutput:
        assert self.record.output is not None
        return self.record.output

    @property
    def snapshot(self) -> dict[str, Any]:
        assert self.record.final_snapshot is not None
        return self.record.final_snapshot


def run_once(
    *,
    task: TaskSpec,
    harness: str,
    world: str | World = "support",
    seed: int = 42,
    store: Store,
    bus: EventBus | None = None,
    budget: Budget | None = None,
    model: str | None = None,
    agent_version: str | None = None,
    scenario_id: str | None = None,
    extra_config: dict[str, Any] | None = None,
    faults: FaultHook | None = None,
) -> RunResult:
    bus = bus or EventBus()
    budget = budget or Budget()
    w = make_world(world) if isinstance(world, str) else world
    w.reset(seed)
    initial = w.snapshot()

    run_id = new_id("run")
    agent = make_harness(harness)
    ctx = RunContext(
        run_id=run_id,
        seed=seed,
        world=w.name,
        agent_role=task.agent_role,
        harness=harness,
        model=model,
        agent_version=agent_version,
    )
    config = {
        "task": task.model_dump(mode="json"),
        "budget": budget.model_dump(mode="json"),
        "run_context": ctx.model_dump(mode="json"),
        "harness_type": agent.harness_type.value,
        "capabilities": agent.capabilities.model_dump(),
        **(extra_config or {}),
    }
    store.create_run(
        RunRecord(
            id=run_id,
            status=RunStatus.RUNNING,
            world=w.name,
            seed=seed,
            harness=harness,
            model=model,
            agent_version=agent_version,
            scenario_id=scenario_id,
            config=config,
        )
    )

    unsubscribe = bus.subscribe(store.append_event, run_id=run_id)
    tracer = Tracer(bus, run_id)
    gateway = Gateway(w, tracer, agent_id=task.agent_role, faults=faults)
    endpoint = InProcessEndpoint(gateway)

    status = RunStatus.FINISHED
    try:
        tracer.emit(TraceKind.RUN_STARTED, **config)
        agent.setup(ctx)
        try:
            output = agent.run(task, endpoint, budget)
        finally:
            agent.teardown()
    except Exception as e:  # a crashing agent is a result, not a runner failure
        status = RunStatus.CRASHED
        output = AgentOutput(
            final_message=f"{type(e).__name__}: {e}",
            exit_reason="crashed",
            usage=Usage(tool_calls=gateway.call_count),
        )
    tracer.emit(TraceKind.AGENT_OUTPUT, **output.model_dump(mode="json"))

    snapshot = w.snapshot()
    tracer.emit(TraceKind.RUN_FINISHED, status=status.value, tool_calls=gateway.call_count)
    unsubscribe()
    store.finish_run(run_id, status, output, snapshot)

    record = store.get_run(run_id)
    assert record is not None
    return RunResult(record, w, initial)


def run_scenario(
    scenario: Scenario,
    *,
    harness: str,
    store: Store,
    model: str | None = None,
    agent_version: str | None = None,
    bus: EventBus | None = None,
) -> RunResult:
    faults = None
    if scenario.faults:
        def baseline() -> World:
            w = scenario.build_world()
            w.reset(scenario.seed)
            return w

        faults = FaultInjector(scenario.faults, seed=scenario.seed, baseline=baseline)
    result = run_once(
        task=scenario.task_spec,
        harness=harness,
        world=scenario.build_world(),
        seed=scenario.seed,
        store=store,
        bus=bus,
        budget=scenario.budget,
        model=model,
        agent_version=agent_version,
        scenario_id=scenario.id,
        extra_config={"scenario": scenario.model_dump(mode="json")},
        faults=faults,
    )
    result.verdict = verify(
        scenario,
        result.run_id,
        result.initial_snapshot,
        result.snapshot,
        store.get_trace(result.run_id),
        result.output,
    )
    store.set_verdict(result.run_id, result.verdict.model_dump(mode="json"))
    return result


# ---------------------------------------------------------------------------
# Matrix execution
# ---------------------------------------------------------------------------


@dataclass
class Cell:
    """All attempts of one scenario x harness x model combination."""

    scenario_id: str
    harness: str
    model: str | None
    runs: list[RunResult] = field(default_factory=list)

    @property
    def verdicts(self) -> list[Verdict]:
        return [r.verdict for r in self.runs if r.verdict is not None]

    @property
    def pass_count(self) -> int:
        return sum(v.passed for v in self.verdicts)

    @property
    def pass_k(self) -> bool:
        """Reliable only if every attempt passed."""
        return bool(self.runs) and self.pass_count == len(self.runs)


@dataclass
class MatrixResult:
    cells: list[Cell]

    def cell(self, scenario_id: str, harness: str, model: str | None = None) -> Cell:
        return next(c for c in self.cells if (c.scenario_id, c.harness, c.model) == (scenario_id, harness, model))

    @property
    def runs(self) -> list[RunResult]:
        return [r for c in self.cells for r in c.runs]


def run_matrix(
    scenarios: Sequence[Scenario],
    harnesses: Sequence[str],
    *,
    store: Store,
    models: Sequence[str | None] = (None,),
    attempts: int = 1,
    parallel: int = 4,
    agent_version: str | None = None,
) -> MatrixResult:
    cells = [Cell(s.id, h, m) for s in scenarios for h in harnesses for m in models]
    by_id = {s.id: s for s in scenarios}
    jobs = [(c, attempt) for c in cells for attempt in range(attempts)]
    bus = EventBus()

    async def main() -> None:
        sem = asyncio.Semaphore(max(1, parallel))

        async def one(cell: Cell) -> None:
            async with sem:
                result = await asyncio.to_thread(
                    run_scenario,
                    by_id[cell.scenario_id],
                    harness=cell.harness,
                    store=store,
                    model=cell.model,
                    agent_version=agent_version,
                    bus=bus,
                )
            cell.runs.append(result)

        await asyncio.gather(*(one(c) for c, _ in jobs))

    asyncio.run(main())
    return MatrixResult(cells)


@dataclass
class ValidationRow:
    scenario_id: str
    null: Verdict
    oracle: Verdict

    @property
    def valid(self) -> bool:
        return (not self.null.passed) and self.oracle.passed


def validate_scenarios(
    scenarios: Iterable[Scenario], *, store: Store, parallel: int = 4,
    null: str = "scripted:null", oracle: str = "scripted:oracle",
) -> list[ValidationRow]:
    scenarios = list(scenarios)
    result = run_matrix(scenarios, [null, oracle], store=store, parallel=parallel)
    rows = []
    for s in scenarios:
        n, o = result.cell(s.id, null).verdicts[0], result.cell(s.id, oracle).verdicts[0]
        rows.append(ValidationRow(s.id, n, o))
    return rows
