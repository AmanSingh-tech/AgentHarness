"""Diagnosis: where did a run go wrong, compared with the reference agent?

`diagnose(run_id)` replays the scenario with its oracle (same seed, faults and
shield setting), lines up the two runs' tool calls, and reports the first step
where they differ, together with the first fault and the first block. The
summary is deterministic plain English; no LLM is involved.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from agentguard.core.models import TraceEvent, TraceKind
from agentguard.core.store import Store


@dataclass
class Step:
    seq: int
    tool: str
    args: dict[str, Any]
    decision: str | None = None
    rule_id: str | None = None
    ok: bool | None = None
    error: str | None = None
    fault: str | None = None


@dataclass
class Diagnosis:
    run_id: str
    oracle_run_id: str | None
    divergence: dict[str, Any] | None  # first step where run and oracle differ
    first_fault: dict[str, Any] | None
    first_block: dict[str, Any] | None
    summary: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def steps(trace: list[TraceEvent]) -> list[Step]:
    """The tool calls of a run, with each one's decision, fault and result attached."""
    by_call: dict[str, Step] = {}
    order: list[str] = []
    for e in trace:
        if e.call_id is None:
            continue
        if e.kind == TraceKind.TOOL_CALL:
            by_call[e.call_id] = Step(seq=e.payload["seq"], tool=e.payload["tool"], args=e.payload["args"])
            order.append(e.call_id)
        elif e.call_id in by_call:
            s = by_call[e.call_id]
            if e.kind == TraceKind.DECISION:
                s.decision, s.rule_id = e.payload["type"], e.payload.get("rule_id")
            elif e.kind == TraceKind.FAULT_INJECTED:
                s.fault = e.payload["fault"]
            elif e.kind == TraceKind.TOOL_RESULT:
                s.ok = e.payload["ok"]
                s.error = (e.payload.get("error") or {}).get("code")
    return [by_call[c] for c in order]


def first_divergence(
    run: list[Step], oracle: list[Step], volatile: dict[str, tuple[str, ...]] | None = None
) -> dict[str, Any] | None:
    """`volatile` maps tool -> arguments to ignore (see ToolSpec.volatile_args)."""
    volatile = volatile or {}
    for i in range(max(len(run), len(oracle))):
        a = run[i] if i < len(run) else None
        b = oracle[i] if i < len(oracle) else None
        if a is not None and b is not None and a.tool == b.tool and \
                _key(a.args, volatile.get(a.tool, ())) == _key(b.args, volatile.get(b.tool, ())):
            continue
        return {
            "step": i + 1,
            "run": asdict(a) if a else None,
            "oracle": asdict(b) if b else None,
            "explanation": _explain(i + 1, a, b, volatile),
        }
    return None


def diagnose(run_id: str, store: Store) -> Diagnosis:
    from agentguard.gym.runner import run_scenario
    from agentguard.gym.scenario import Scenario

    rec = store.get_run(run_id)
    if rec is None:
        raise KeyError(f"run {run_id} not found")
    run_steps = steps(store.get_trace(run_id))
    first_fault = next((asdict(s) for s in run_steps if s.fault), None)
    first_block = next((asdict(s) for s in run_steps if s.decision in ("BLOCK", "REQUIRE_APPROVAL")
                        and s.error in ("BLOCKED", "APPROVAL_REJECTED", "APPROVAL_TIMEOUT")), None)

    oracle_run_id, divergence = None, None
    scenario_data = rec.config.get("scenario")
    if scenario_data is not None:
        scenario = Scenario.model_validate(scenario_data)
        if rec.harness != scenario.oracle:
            oracle = run_scenario(scenario, harness=scenario.oracle, store=store,
                                  shield=rec.config.get("shield_enabled", True), run_set="diagnosis")
            oracle_run_id = oracle.run_id
            divergence = first_divergence(run_steps, steps(store.get_trace(oracle.run_id)),
                                          volatile_args(scenario.world))

    d = Diagnosis(run_id, oracle_run_id, divergence, first_fault, first_block)
    d.summary = summarise(rec.verdict or {}, d)
    return d


def summarise(verdict: dict[str, Any], d: Diagnosis) -> list[str]:
    """Three lines: what happened, where it went wrong, and why it matters."""
    outcome = verdict.get("outcome", "UNKNOWN")
    claim = (verdict.get("claim") or {}).get("kind", "none")
    what = f"Outcome {outcome}: the agent claimed {claim}; the world state was {'as expected' if verdict.get('state_ok') else 'not as expected'}."
    if d.divergence:
        where = d.divergence["explanation"]
    elif d.first_block:
        where = f"Call #{d.first_block['seq']} {d.first_block['tool']} was stopped by {d.first_block['rule_id']}."
    else:
        where = "The agent made the same calls as the reference agent."
    if d.first_fault:
        where += f" A {d.first_fault['fault']} fault hit call #{d.first_fault['seq']} ({d.first_fault['tool']})."
    unsafe = verdict.get("unsafe_side_effects") or []
    violations = verdict.get("violations") or []
    if unsafe:
        why = "Unsafe side effect: " + "; ".join(u["reason"] for u in unsafe) + "."
    elif violations:
        why = f"Forbidden call(s) attempted: {sorted({v['tool'] for v in violations})}."
    elif outcome == "INCORRECT_SUCCESS_CLAIM":
        why = "The agent reported success that the ledger does not support."
    elif verdict.get("passed"):
        why = "No harm: the run passed."
    else:
        why = "The task was not completed as specified."
    return [what, where, why]


def volatile_args(world: str) -> dict[str, tuple[str, ...]]:
    from agentguard.world import WORLDS

    return {t.name: t.volatile_args for t in WORLDS[world]().tools() if t.volatile_args}


def _key(args: dict[str, Any], ignore: tuple[str, ...] = ()) -> str:
    return json.dumps({k: v for k, v in args.items() if k not in ignore}, sort_keys=True, default=str)


def _explain(step: int, a: Step | None, b: Step | None, volatile: dict[str, tuple[str, ...]]) -> str:
    if a is None:
        return f"At step {step} the agent stopped, but the reference agent went on to call {b.tool}."  # type: ignore[union-attr]
    if b is None:
        return f"At step {step} the agent called {a.tool}, after the reference agent had already finished."
    if a.tool != b.tool:
        return f"At step {step} the agent called {a.tool} where the reference agent called {b.tool}."
    ignore = volatile.get(a.tool, ())
    changed = sorted(k for k in set(a.args) | set(b.args) if k not in ignore and a.args.get(k) != b.args.get(k))
    return f"At step {step} the agent called {a.tool} with different {', '.join(changed)} than the reference agent."
