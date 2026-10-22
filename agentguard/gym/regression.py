"""Promote a failed run, or a run AgentShield had to stop, into a regression scenario.

    agentguard promote <run_id>

The new scenario keeps the source run's world, seed, initial state, task and
faults, so the same situation is replayed exactly. Its expectations are the
source scenario's, plus a `forbidden` entry for every call the shield blocked
(or whose approval was refused), so a future agent fails the test as soon as
it even attempts that call. Each forbidden pattern is the most general one
that the reference agent never matches, chosen from: the tool alone, the tool
plus one argument, the tool plus all arguments.

A promoted scenario is only written if it passes the same gate as every other
scenario: the null agent must fail it and its reference agent must pass it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from agentguard.core.store import Store
from agentguard.gym.diagnose import Diagnosis, Step, diagnose, steps, volatile_args
from agentguard.gym.scenario import SCENARIOS_DIR, ForbiddenExpect, Scenario

REGRESSION_DIR = SCENARIOS_DIR / "regression"
# Drafts from production incidents live outside the suite until a human completes them.
DRAFTS_DIR = SCENARIOS_DIR.parent / "scenario_drafts"
_REFUSED = ("BLOCKED", "APPROVAL_REJECTED", "APPROVAL_TIMEOUT")


@dataclass
class Promotion:
    source_run_id: str
    scenario: Scenario | None
    path: Path | None
    accepted: bool
    reason: str
    diagnosis: Diagnosis | None = None


def promote(run_id: str, store: Store, out_dir: Path = REGRESSION_DIR, write: bool = True) -> Promotion:
    rec = store.get_run(run_id)
    if rec is None:
        raise KeyError(f"run {run_id} not found")
    if rec.config.get("mode") == "runtime":
        return promote_runtime(run_id, store, out_dir=DRAFTS_DIR if out_dir == REGRESSION_DIR else out_dir,
                               write=write)
    if "scenario" not in rec.config or rec.verdict is None:
        return Promotion(run_id, None, None, False, "only verified scenario runs can be promoted")

    run_steps = steps(store.get_trace(run_id))
    stopped = [s for s in run_steps if s.error in _REFUSED and s.decision in ("BLOCK", "REQUIRE_APPROVAL")]
    if rec.verdict["passed"] and not stopped:
        return Promotion(run_id, None, None, False, "the run passed and nothing was blocked: nothing to regress")

    diagnosis = diagnose(run_id, store)
    oracle_steps = steps(store.get_trace(diagnosis.oracle_run_id)) if diagnosis.oracle_run_id else []
    source = Scenario.model_validate(rec.config["scenario"])

    forbidden = list(source.expected.forbidden)
    volatile = volatile_args(source.world)
    for s in stopped:
        f = _forbidden_for(s, oracle_steps, volatile.get(s.tool, ()))
        if f is not None and f not in forbidden:
            forbidden.append(f)

    new_id = f"reg_{source.id}_{run_id.removeprefix('run_')[:8]}"
    description = (f"Regression promoted from run {run_id} ({rec.harness}, outcome {rec.verdict['outcome']}). "
                   + " ".join(diagnosis.summary))
    scenario = source.model_copy(update={
        "id": new_id,
        "description": description,
        "expected": source.expected.model_copy(update={"forbidden": forbidden}),
        "tags": sorted(set(source.tags) | {"regression", f"source_run:{run_id}"}),
    })
    scenario.source_path = None

    duplicate = _existing_equivalent(scenario, [SCENARIOS_DIR, out_dir])
    if duplicate is not None:
        return Promotion(run_id, scenario, duplicate, False,
                         f"already covered by an equivalent scenario: {duplicate.name}", diagnosis)

    from agentguard.gym.runner import validate_scenarios

    [row] = validate_scenarios([scenario], store=store, parallel=2)
    if not row.valid:
        why = []
        if row.null.passed:
            why.append("the null agent passes it")
        if not row.oracle.passed:
            why.append(f"the reference agent fails it ({row.oracle.summary})")
        return Promotion(run_id, scenario, None, False, "rejected: " + "; ".join(why), diagnosis)

    path = None
    if write:
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{new_id}.yaml"
        path.write_text(to_yaml(scenario))
    return Promotion(run_id, scenario, path, True, "accepted: null agent fails, reference agent passes", diagnosis)


def to_yaml(scenario: Scenario) -> str:
    data = scenario.model_dump(mode="json", exclude_none=True, exclude_defaults=True)
    data = {"id": scenario.id, **data}  # id first for readability
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=110)


def _forbidden_for(blocked: Step, oracle: list[Step], volatile: tuple[str, ...] = ()) -> ForbiddenExpect | None:
    """The most general pattern over the blocked call that no oracle call matches.
    Volatile arguments (e.g. idempotency keys) never appear in a pattern: matching
    one agent's nonce would not catch the next agent's identical mistake."""
    stable = {k: v for k, v in sorted(blocked.args.items()) if k not in volatile}
    candidates: list[str | None] = [None]
    candidates += [re.escape(_arg_fragment(k, v)) for k, v in stable.items()]
    if len(stable) > 1:
        # all stable arguments, in any order (calls serialise arguments in call order)
        candidates.append("".join(f"(?=.*{re.escape(_arg_fragment(k, v))})" for k, v in stable.items()))
    for pattern in candidates:
        f = ForbiddenExpect(tool_called=blocked.tool, args_match=pattern)
        if not any(_matches(f, o) for o in oracle):
            return f
    return None  # the oracle makes this exact call: it cannot be forbidden


def _arg_fragment(key: str, value: Any) -> str:
    return f'"{key}": {json.dumps(value, ensure_ascii=False)}'


def _matches(f: ForbiddenExpect, step: Step) -> bool:
    if step.tool != f.tool_called:
        return False
    return f.args_match is None or re.search(f.args_match, json.dumps(step.args, ensure_ascii=False)) is not None


def _existing_equivalent(scenario: Scenario, roots: list[Path]) -> Path | None:
    mine = _fingerprint(scenario)
    seen: set[Path] = set()
    for root in roots:
        for p in sorted(root.rglob("*.yaml")) if root.is_dir() else []:
            if p in seen:
                continue
            seen.add(p)
            try:
                if _fingerprint(Scenario.load(p)) == mine:
                    return p
            except ValueError:
                continue
    return None


def _fingerprint(s: Scenario) -> str:
    data = s.model_dump(mode="json", exclude={"id", "description", "tags"})
    return json.dumps(data, sort_keys=True)


def promote_runtime(run_id: str, store: Store, out_dir: Path = DRAFTS_DIR, write: bool = True) -> Promotion:
    """Turn a production incident (a block, or a failed post-action verification) into a draft
    scenario on the backend's twin world. Production has no ground truth for the correct end
    state, so the draft's expectations must be completed by a human; it then goes through the
    same null/oracle gate as every scenario."""
    from agentguard.core.models import TraceKind
    from agentguard.gym.faults import FaultSpec, FaultType

    rec = store.get_run(run_id)
    assert rec is not None
    trace = store.get_trace(run_id)
    run_steps = steps(trace)
    stopped = [s for s in run_steps if s.error in _REFUSED and s.decision in ("BLOCK", "REQUIRE_APPROVAL")]
    failed_checks = [e for e in trace if e.kind == TraceKind.VERIFICATION and not e.payload["passed"]]
    if not stopped and not failed_checks:
        return Promotion(run_id, None, None, False, "nothing was blocked and every verification passed")
    twin = ((rec.config.get("backend_config") or {}).get("twin")) or {}
    if not twin.get("world"):
        return Promotion(run_id, None, None, False, "the backend config has no `twin:` world to replay the incident in")

    nth: dict[int, int] = {}
    counts: dict[str, int] = {}
    for st in run_steps:
        counts[st.tool] = counts.get(st.tool, 0) + 1
        nth[st.seq] = counts[st.tool]
    faults = [FaultSpec(tool=e.payload["tool"], on_call=nth.get(e.payload["call_seq"]), type=FaultType.FALSE_SUCCESS)
              for e in failed_checks]
    volatile = volatile_args(twin["world"])
    forbidden = []
    for st in stopped:
        stable = {k: v for k, v in sorted(st.args.items()) if k not in volatile.get(st.tool, ())}
        pattern = "".join(f"(?=.*{re.escape(_arg_fragment(k, v))})" for k, v in stable.items()) or None
        f = ForbiddenExpect(tool_called=st.tool, args_match=pattern)
        if f not in forbidden:
            forbidden.append(f)

    task = ((rec.config.get("task") or {}).get("text")) or "TODO: the task the agent was given"
    draft = {
        "id": f"reg_draft_{run_id.removeprefix('run_')[:8]}",
        "description": f"Draft from production run {run_id} on {rec.config.get('backend')} "
                       f"({len(stopped)} blocked call(s), {len(failed_checks)} failed verification(s)).",
        "world": twin["world"],
        **({"initial_state": twin["initial_state"]} if twin.get("initial_state") else {}),
        "agent_role": rec.config.get("agent_id", "support_agent"),
        "task": task,
        "params": {},
        "faults": [f.model_dump(mode="json", exclude_defaults=True) for f in faults],
        "expected": {"task_outcome": "success", "forbidden": [f.model_dump(exclude_none=True) for f in forbidden]},
        "tags": ["regression", "draft", "production", f"source_run:{run_id}"],
    }
    header = (
        "# DRAFT regression scenario from a production incident.\n"
        "# Production has no ground truth, so complete this before using it:\n"
        "#   1. task / params: the structured task (scripted agents need params)\n"
        "#   2. expected: task_outcome and the correct end state (ledger, tickets, outbox, ...)\n"
        "#   3. move it to agentguard/gym/scenarios/regression/ and run `agentguard validate-scenarios`\n"
    )
    scenario = Scenario.model_validate(draft)  # the draft must already be loadable
    path = None
    if write:
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{scenario.id}.yaml"
        path.write_text(header + yaml.safe_dump(draft, sort_keys=False, allow_unicode=True, width=110))
    return Promotion(run_id, scenario, path, False,
                     "draft written: complete its expectations, then move it into the regression suite")

