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
    HarnessCapabilities,
    HarnessType,
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
from agentguard.shield.approvals import ApprovalQueue
from agentguard.shield.gateway import FaultHook, Gateway
from agentguard.shield.pipeline import Shield, ShieldConfig
from agentguard.shield.policy import load_policy, resolve_policy_path
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


class PreparedRun:
    """A run that is set up and recorded but not yet driven by an agent.

    `run_once` drives it with a harness; the MCP server (transports/mcp_proxy.py)
    drives it from an external MCP client. Either way: `start()`, tool calls through
    `endpoint`, then `finish(output)`.
    """

    def __init__(self, *, run_id: str, task: TaskSpec, world: World, initial: dict[str, Any], store: Store,
                 tracer: Tracer, unsubscribe: Any, gateway: Gateway, pipeline: Shield | None,
                 config: dict[str, Any], ctx: RunContext, budget: Budget) -> None:
        self.run_id, self.task, self.world, self.initial, self.store = run_id, task, world, initial, store
        self.tracer, self._unsubscribe, self.gateway, self.pipeline = tracer, unsubscribe, gateway, pipeline
        self.config, self.ctx, self.budget = config, ctx, budget
        self.endpoint = InProcessEndpoint(gateway)
        self.finished = False

    def start(self) -> None:
        self.tracer.emit(TraceKind.RUN_STARTED, **self.config)
        if self.pipeline is not None:
            findings = self.pipeline.scan_task(self.task.text)
            if findings:
                self.tracer.emit(TraceKind.INJECTION_DETECTED, source="task", findings=[f.to_dict() for f in findings],
                                 note="Task text flagged as a possible injection. Policy still governs every action.")

    def finish(self, output: AgentOutput, status: RunStatus = RunStatus.FINISHED) -> RunResult:
        if self.finished:
            raise RuntimeError(f"run {self.run_id} is already finished")
        self.finished = True
        self.tracer.emit(TraceKind.AGENT_OUTPUT, **output.model_dump(mode="json"))
        snapshot = self.world.snapshot()
        self.tracer.emit(TraceKind.RUN_FINISHED, status=status.value, tool_calls=self.gateway.call_count)
        self._unsubscribe()
        self.store.finish_run(self.run_id, status, output, snapshot)
        record = self.store.get_run(self.run_id)
        assert record is not None
        return RunResult(record, self.world, self.initial)


def prepare_run(
    *,
    task: TaskSpec,
    harness: str,
    harness_type: HarnessType,
    capabilities: HarnessCapabilities,
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
    shield: ShieldConfig | None = None,
    approvals: ApprovalQueue | None = None,
) -> PreparedRun:
    """Reset the world, record the run, and build the gateway (with AgentShield unless `shield` is None).
    `approvals` replaces the queue built from the shield config (e.g. the dashboard's shared, manual queue)."""
    bus = bus or EventBus()
    budget = budget or Budget()
    w = make_world(world) if isinstance(world, str) else world
    w.reset(seed)
    initial = w.snapshot()

    run_id = new_id("run")
    ctx = RunContext(run_id=run_id, seed=seed, world=w.name, agent_role=task.agent_role, harness=harness,
                     model=model, agent_version=agent_version)
    config = {
        "task": task.model_dump(mode="json"),
        "budget": budget.model_dump(mode="json"),
        "run_context": ctx.model_dump(mode="json"),
        "harness_type": harness_type.value,
        "capabilities": capabilities.model_dump(),
        "shield": shield.model_dump(mode="json") | {"policy_path": str(resolve_policy_path(shield.policy))}
        if shield and shield.enabled else None,
        **(extra_config or {}),
    }
    store.create_run(RunRecord(id=run_id, status=RunStatus.RUNNING, world=w.name, seed=seed, harness=harness,
                               model=model, agent_version=agent_version, scenario_id=scenario_id, config=config))

    unsubscribe = bus.subscribe(store.append_event, run_id=run_id)
    tracer = Tracer(bus, run_id)
    pipeline: Shield | None = None
    if shield is not None and shield.enabled:
        pipeline = Shield(load_policy(shield.policy), w)
        if approvals is None:
            approvals = ApprovalQueue(store, auto=shield.auto_approver, timeout_s=shield.approval_timeout_s)
    else:
        approvals = None
    gateway = Gateway(w, tracer, agent_id=task.agent_role, stages=pipeline.stages if pipeline else None,
                      faults=faults, approvals=approvals)
    return PreparedRun(run_id=run_id, task=task, world=w, initial=initial, store=store, tracer=tracer,
                       unsubscribe=unsubscribe, gateway=gateway, pipeline=pipeline, config=config, ctx=ctx,
                       budget=budget)


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
    shield: ShieldConfig | None = None,
    approvals: ApprovalQueue | None = None,
) -> RunResult:
    """Run one agent on one task. `shield=None` runs without AgentShield (no policy stages)."""
    agent = make_harness(harness)
    run = prepare_run(task=task, harness=harness, harness_type=agent.harness_type, capabilities=agent.capabilities,
                      world=world, seed=seed, store=store, bus=bus, budget=budget, model=model,
                      agent_version=agent_version, scenario_id=scenario_id, extra_config=extra_config, faults=faults,
                      shield=shield, approvals=approvals)
    return execute(run, agent)


def execute(run: PreparedRun, agent: Any) -> RunResult:
    """Drive a prepared run with a harness and finish it."""
    status = RunStatus.FINISHED
    try:
        run.start()
        agent.setup(run.ctx)
        try:
            output = agent.run(run.task, run.endpoint, run.budget)
        finally:
            agent.teardown()
    except Exception as e:  # a crashing agent is a result, not a runner failure
        status = RunStatus.CRASHED
        output = AgentOutput(final_message=f"{type(e).__name__}: {e}", exit_reason="crashed",
                             usage=Usage(tool_calls=run.gateway.call_count))
    return run.finish(output, status)


def scenario_run_kwargs(scenario: Scenario, shield: bool = True, run_set: str | None = None) -> dict[str, Any]:
    """Everything prepare_run/run_once need to replay a scenario: world, seed, budget, faults, shield."""
    faults = None
    if scenario.faults:
        def baseline() -> World:
            w = scenario.build_world()
            w.reset(scenario.seed)
            return w

        faults = FaultInjector(scenario.faults, seed=scenario.seed, baseline=baseline)
    return dict(
        task=scenario.task_spec, world=scenario.build_world(), seed=scenario.seed, budget=scenario.budget,
        scenario_id=scenario.id, faults=faults, shield=scenario.shield if shield else None,
        extra_config={"scenario": scenario.model_dump(mode="json"), "run_set": run_set, "shield_enabled": shield},
    )


def verify_run(scenario: Scenario, result: RunResult, store: Store) -> RunResult:
    result.verdict = verify(scenario, result.run_id, result.initial_snapshot, result.snapshot,
                            store.get_trace(result.run_id), result.output)
    store.set_verdict(result.run_id, result.verdict.model_dump(mode="json"))
    return result


def run_scenario(
    scenario: Scenario,
    *,
    harness: str,
    store: Store,
    model: str | None = None,
    agent_version: str | None = None,
    bus: EventBus | None = None,
    shield: bool = True,
    run_set: str | None = None,
    approvals: ApprovalQueue | None = None,
) -> RunResult:
    """`shield=False` runs the scenario without AgentShield, to measure the agent on its own."""
    result = run_once(harness=harness, store=store, bus=bus, model=model, agent_version=agent_version,
                      approvals=approvals, **scenario_run_kwargs(scenario, shield, run_set))
    return verify_run(scenario, result, store)


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
    shield: bool = True,
    run_set: str | None = None,
) -> MatrixResult:
    """`run_set` labels every run so groups of runs (e.g. "v1", "v2-shield") can be compared later."""
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
                    shield=shield,
                    run_set=run_set,
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
    null: str = "scripted:null", oracle: str | None = None, shield: bool = True,
) -> list[ValidationRow]:
    """Each scenario must fail for `null` and pass for its oracle (`oracle` overrides
    every scenario's own `oracle:` field)."""
    scenarios = list(scenarios)
    nulls = run_matrix(scenarios, [null], store=store, parallel=parallel, shield=shield)
    by_oracle: dict[str, list[Scenario]] = {}
    for s in scenarios:
        by_oracle.setdefault(oracle or s.oracle, []).append(s)
    oracles = {
        (s.id, h): run.cell(s.id, h).verdicts[0]
        for h, group in by_oracle.items()
        for run in [run_matrix(group, [h], store=store, parallel=parallel, shield=shield)]
        for s in group
    }
    return [ValidationRow(s.id, nulls.cell(s.id, null).verdicts[0], oracles[(s.id, oracle or s.oracle)]) for s in scenarios]
