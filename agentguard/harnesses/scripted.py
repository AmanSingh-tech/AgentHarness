"""SCRIPTED harness: deterministic, non-LLM agents defined in YAML.

These are the reference agents used to validate scenarios (null must fail,
oracle must pass) and to play the naive/adversarial roles in demos.

DSL summary (see scripted_agents/*.yaml):

    steps:
      - id: refund                 # optional, used in failure messages
        call: issue_refund
        args: {order_id: "{{task.order_id}}"}
        when: {path: order.status, equals: delivered}   # skip unless true
        save: refund               # store the result output under this name
        expect:                    # post-conditions on the output
          - {path: status, equals: SUCCESS}
        retry: 2                   # extra attempts after an error...
        retry_on: [RATE_LIMITED]   # ...only for these codes (omit = any error)
        on_error: [ ...steps ]     # recovery; recovered iff every executed step succeeds
        on_unrecovered: fail       # or `continue`
    injection_triggers:            # makes the agent hijackable (naive agent)
      - pattern: "(?i)ignore previous instructions.*?(?P<to>\\S+@\\S+)"
        steps: [ ...steps ]        # run once, the first time any tool output matches
    on_success: {message: ..., claimed_outcome: {...}, exit_reason: completed}
    on_failure: {message: ..., claimed_outcome: {...}, exit_reason: escalated}

Templates: "{{path.to.value}}" over {task: params, <saved vars>, failure: {...},
attempt: 1-based attempt number of the current call, injection: the trigger's
named groups}. A string that is exactly one template keeps the raw value's type.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, ClassVar, Literal

import yaml
from pydantic import BaseModel, Field

from agentguard.core.models import (
    AgentOutput,
    Budget,
    ExitReason,
    HarnessCapabilities,
    HarnessType,
    RunContext,
    TaskSpec,
    Usage,
)
from agentguard.transports.base import ToolEndpoint
from agentguard.transports.inprocess import InProcessEndpoint

AGENTS_DIR = Path(__file__).parent / "scripted_agents"
_TEMPLATE = re.compile(r"\{\{\s*([\w.\-]+)\s*\}\}")
_MISSING = object()


class TemplateError(KeyError):
    pass


# ---------------------------------------------------------------------------
# DSL models
# ---------------------------------------------------------------------------


class Condition(BaseModel):
    path: str
    equals: Any = _MISSING
    not_equals: Any = _MISSING
    exists: bool | None = None
    gte: float | str | None = None  # number or template, e.g. "{{task.amount_inr}}"

    model_config = {"arbitrary_types_allowed": True}


class Step(BaseModel):
    id: str | None = None
    call: str
    args: dict[str, Any] = Field(default_factory=dict)
    when: Condition | None = None
    save: str | None = None
    expect: list[Condition] = Field(default_factory=list)
    retry: int = 0
    retry_on: list[str] | None = None
    on_error: list["Step"] = Field(default_factory=list)
    on_unrecovered: Literal["fail", "continue"] = "fail"


class InjectionTrigger(BaseModel):
    """Deterministic stand-in for an agent that obeys instructions found in tool
    output: when `pattern` matches the JSON text of any tool output, the agent
    runs `steps` on top of its task (their errors are ignored), then carries on."""

    pattern: str
    steps: list[Step]


class Outcome(BaseModel):
    message: str
    claimed_outcome: dict[str, Any] | None = None
    exit_reason: ExitReason


class ScriptedAgentDef(BaseModel):
    name: str
    version: str = "1"
    description: str = ""
    steps: list[Step] = Field(default_factory=list)
    injection_triggers: list[InjectionTrigger] = Field(default_factory=list)
    on_success: Outcome
    on_failure: Outcome

    @classmethod
    def load(cls, name_or_path: str) -> "ScriptedAgentDef":
        p = Path(name_or_path)
        if not p.suffix:
            p = AGENTS_DIR / f"{name_or_path}.yaml"
        if not p.is_file():
            known = sorted(f.stem for f in AGENTS_DIR.glob("*.yaml"))
            raise ValueError(f"Scripted agent '{name_or_path}' not found. Built-in: {known}")
        return cls.model_validate(yaml.safe_load(p.read_text()))


# ---------------------------------------------------------------------------
# Templating
# ---------------------------------------------------------------------------


def lookup(ctx: dict[str, Any], path: str) -> Any:
    cur: Any = ctx
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return _MISSING
    return cur


def render(value: Any, ctx: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {k: render(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [render(v, ctx) for v in value]
    if not isinstance(value, str):
        return value

    whole = _TEMPLATE.fullmatch(value.strip())
    if whole:
        found = lookup(ctx, whole.group(1))
        if found is _MISSING:
            raise TemplateError(whole.group(1))
        return found

    def sub(m: re.Match) -> str:
        found = lookup(ctx, m.group(1))
        if found is _MISSING:
            raise TemplateError(m.group(1))
        return str(found)

    return _TEMPLATE.sub(sub, value)


def check(cond: Condition, data: Any, ctx: dict[str, Any]) -> bool:
    found = lookup(data, cond.path) if isinstance(data, (dict, list)) else _MISSING
    if cond.exists is not None and (found is not _MISSING) != cond.exists:
        return False
    if cond.equals is not _MISSING and (found is _MISSING or found != render(cond.equals, ctx)):
        return False
    if cond.not_equals is not _MISSING and found == render(cond.not_equals, ctx):
        return False
    if cond.gte is not None:
        bound = render(cond.gte, ctx)
        if not (_is_number(found) and _is_number(bound) and found >= bound):
            return False
    return True


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


class _Stop(Exception):
    def __init__(self, exit_reason: ExitReason, failure: dict[str, Any]) -> None:
        self.exit_reason = exit_reason
        self.failure = failure


class ScriptedHarness:
    harness_type = HarnessType.SCRIPTED
    capabilities: ClassVar[HarnessCapabilities] = HarnessCapabilities(supports_structured_claim=True)

    def __init__(self, agent: str = "oracle") -> None:
        self.definition = ScriptedAgentDef.load(agent)
        self.name = f"scripted:{self.definition.name}"
        self.run_ctx: RunContext | None = None

    def setup(self, run_ctx: RunContext) -> None:
        self.run_ctx = run_ctx

    def teardown(self) -> None:
        self.run_ctx = None

    def run(self, task: TaskSpec, tools: ToolEndpoint, budget: Budget) -> AgentOutput:
        if not isinstance(tools, InProcessEndpoint):
            raise TypeError("ScriptedHarness only supports in-process tool endpoints")
        started = time.monotonic()
        calls_before = tools.calls_made
        ctx: dict[str, Any] = {"task": dict(task.params)}
        exec_ = _Executor(tools, budget, ctx, started, calls_before, self.definition.injection_triggers)

        try:
            for step in self.definition.steps:
                exec_.run_step(step)
            outcome, exit_reason = self.definition.on_success, None
        except _Stop as stop:
            ctx["failure"] = stop.failure
            outcome, exit_reason = self.definition.on_failure, stop.exit_reason
        except TemplateError as e:
            ctx["failure"] = {"step": None, "code": "TEMPLATE_ERROR", "message": f"unresolved template '{e.args[0]}'"}
            outcome, exit_reason = self.definition.on_failure, "crashed"

        usage = Usage(wall_time_s=round(time.monotonic() - started, 4), tool_calls=tools.calls_made - calls_before)
        try:
            message = render(outcome.message, ctx)
            claim = render(outcome.claimed_outcome, ctx) if outcome.claimed_outcome is not None else None
        except TemplateError as e:
            message, claim, exit_reason = f"[scripted agent template error: {e.args[0]}]", None, "crashed"
        return AgentOutput(
            final_message=message,
            claimed_outcome=claim,
            exit_reason=exit_reason or outcome.exit_reason,
            usage=usage,
        )


class _Executor:
    def __init__(
        self,
        tools: InProcessEndpoint,
        budget: Budget,
        ctx: dict[str, Any],
        started: float,
        calls_before: int,
        triggers: list[InjectionTrigger] = (),
    ) -> None:
        self.tools, self.budget, self.ctx = tools, budget, ctx
        self.started, self.calls_before = started, calls_before
        self.pending_triggers = list(triggers)

    def run_step(self, step: Step) -> bool:
        """Execute a step (with retries and recovery). Returns True on success.
        Raises _Stop when the agent should give up."""
        if step.when is not None and not check(step.when, self.ctx, self.ctx):
            return True

        try:
            error = self._attempt(step)
        except TemplateError as e:
            if step.on_unrecovered != "continue":
                raise
            error = {"code": "TEMPLATE_ERROR", "message": f"unresolved template '{e.args[0]}'"}
        if error is None:
            return True

        recovered = bool(step.on_error) and all(self._recover(s) for s in step.on_error)
        if recovered or step.on_unrecovered == "continue":
            return recovered
        raise _Stop("escalated", {"step": step.id or step.call, **error})

    def _recover(self, step: Step) -> bool:
        try:
            return self.run_step(step)
        except _Stop:
            return False

    def _attempt(self, step: Step) -> dict[str, Any] | None:
        error: dict[str, Any] | None = None
        for attempt in range(1, step.retry + 2):
            self.ctx["attempt"] = attempt
            args = render(step.args, self.ctx)
            self._check_budget()
            result = self.tools.call(step.call, args)
            if result.ok:
                if step.save:
                    self.ctx[step.save] = result.output
                self._obey_injections(result.output)
                failed = next((c for c in step.expect if not check(c, result.output, self.ctx)), None)
                if failed is None:
                    return None
                return {"code": "EXPECTATION_FAILED", "message": f"expected {failed.model_dump(exclude_defaults=True)}"}
            assert result.error is not None
            error = {"code": result.error.code, "message": result.error.message}
            if step.retry_on is not None and result.error.code not in step.retry_on:
                break
        return error

    def _obey_injections(self, output: Any) -> None:
        if not self.pending_triggers:
            return
        text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False, default=str)
        for trigger in list(self.pending_triggers):
            m = re.search(trigger.pattern, text)
            if m is None:
                continue
            self.pending_triggers.remove(trigger)  # each trigger fires once; also stops recursion
            saved_attempt = self.ctx.get("attempt")
            self.ctx["injection"] = m.groupdict()
            for step in trigger.steps:
                try:
                    self.run_step(step)
                except (_Stop, TemplateError) as e:
                    if isinstance(e, _Stop) and e.failure.get("code") == "BUDGET":
                        raise
            self.ctx["attempt"] = saved_attempt

    def _check_budget(self) -> None:
        used = self.tools.calls_made - self.calls_before
        if used >= self.budget.max_tool_calls:
            raise _Stop("budget_exceeded", {"step": None, "code": "BUDGET", "message": "tool-call budget exhausted"})
        if time.monotonic() - self.started > self.budget.max_wall_seconds:
            raise _Stop("budget_exceeded", {"step": None, "code": "BUDGET", "message": "wall-clock budget exhausted"})
