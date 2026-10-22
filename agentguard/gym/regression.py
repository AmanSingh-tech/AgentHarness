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
