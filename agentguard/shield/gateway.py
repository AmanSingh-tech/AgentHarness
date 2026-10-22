"""The single choke point every tool call passes through.

Milestone 1 implements the skeleton of the pipeline: schema validation, a
pluggable list of decision stages (policy, risk, taint, injection arrive in
later milestones), execution against a ToolBackend, and a TraceEvent for every
step. With no stages configured every valid call is ALLOWed, and the decision
says so explicitly.

In AgentGym runs an optional FaultHook sits between the decision and the
backend: it decides whether the real call happens and what the agent sees.
Production mode never sets one.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Protocol

from agentguard.core.events import Tracer
from agentguard.core.models import (
    Decision,
    DecisionType,
    RiskLevel,
    ToolCall,
    ToolError,
    ToolResult,
    ToolSpec,
    TraceKind,
)
from agentguard.core.tooling import validate_args
from agentguard.world.base import ToolBackend, ToolExecutionError


class DecisionStage(Protocol):
    """A pipeline stage. Returns None to abstain, or a Decision."""

    name: str

    def evaluate(self, call: ToolCall, spec: ToolSpec) -> Decision | None: ...


class FaultHook(Protocol):
    """Wraps execution of an ALLOWed call (implemented by gym.faults.FaultInjector).

    `execute` runs the call against the backend; the hook may skip it, run it
    and alter the result, or pass it through. Returns the result the agent sees
    and, if a fault fired, a JSON-serialisable record for the trace."""

    def apply(
        self, call: ToolCall, spec: ToolSpec, execute: Callable[[], ToolResult]
    ) -> tuple[ToolResult, dict[str, Any] | None]: ...


# Most restrictive decision wins when several stages vote.
_SEVERITY = {
    DecisionType.ALLOW: 0,
    DecisionType.ALLOW_WITH_REDACTION: 1,
    DecisionType.REQUIRE_APPROVAL: 2,
    DecisionType.BLOCK: 3,
}


class Gateway:
    def __init__(
        self,
        backend: ToolBackend,
        tracer: Tracer,
        agent_id: str,
        stages: list[DecisionStage] | None = None,
        faults: FaultHook | None = None,
    ) -> None:
        self.backend = backend
        self.tracer = tracer
        self.agent_id = agent_id
        self.stages = list(stages or [])
        self.faults = faults
        self._seq = 0
        self._lock = threading.Lock()

    @property
    def run_id(self) -> str:
        return self.tracer.run_id

    @property
    def call_count(self) -> int:
        return self._seq

    def tools(self) -> list[ToolSpec]:
        return self.backend.tools()

    def call(self, tool: str, args: dict[str, Any] | None = None) -> ToolResult:
        args = dict(args or {})
        with self._lock:
            self._seq += 1
            seq = self._seq
        call = ToolCall(run_id=self.run_id, agent_id=self.agent_id, tool=tool, args=args, seq=seq)
        self.tracer.emit(TraceKind.TOOL_CALL, call_id=call.id, tool=tool, args=args, seq=seq, agent_id=self.agent_id)

        spec = self.backend.tool(tool)
        decision = self._decide(call, spec)
        self.tracer.emit(TraceKind.DECISION, call_id=call.id, tool=tool, **decision.model_dump(mode="json"))

        if decision.type != DecisionType.ALLOW:
            # REQUIRE_APPROVAL / ALLOW_WITH_REDACTION are wired up in milestone 4;
            # until then anything other than ALLOW fails closed.
            return self._finish(
                call,
                ToolResult(
                    call_id=call.id,
                    tool=tool,
                    ok=False,
                    error=ToolError(code="BLOCKED", message=decision.reason),
                ),
            )

        assert spec is not None  # _decide blocks unknown tools
        if self.faults is None:
            return self._finish(call, self._execute(call, spec))
        result, fault = self.faults.apply(call, spec, lambda: self._execute(call, spec))
        if fault is not None:
            self.tracer.emit(TraceKind.FAULT_INJECTED, call_id=call.id, **fault)
        return self._finish(call, result)

    def _execute(self, call: ToolCall, spec: ToolSpec) -> ToolResult:
        started = time.perf_counter()
        try:
            output = self.backend.execute(call.tool, call.args)
            result = ToolResult(call_id=call.id, tool=call.tool, ok=True, output=output, labels=list(spec.returns_labels))
        except ToolExecutionError as e:
            result = ToolResult(
                call_id=call.id, tool=call.tool, ok=False,
                error=ToolError(code=e.code, message=e.message, retryable=e.retryable),
            )
        except Exception as e:  # backend bug: surface it, never crash the agent loop
            result = ToolResult(
                call_id=call.id, tool=call.tool, ok=False,
                error=ToolError(code="INTERNAL", message=f"{type(e).__name__}: {e}"),
            )
        result.latency_ms = round((time.perf_counter() - started) * 1000, 3)
        return result

    def _decide(self, call: ToolCall, spec: ToolSpec | None) -> Decision:
        if spec is None:
            return Decision(
                type=DecisionType.BLOCK,
                reason=f"Unknown tool '{call.tool}'",
                rule_id="gateway.unknown_tool",
                risk=RiskLevel.MEDIUM,
            )
        problems = validate_args(spec, call.args)
        if problems:
            return Decision(
                type=DecisionType.BLOCK,
                reason="Invalid arguments: " + "; ".join(problems),
                rule_id="gateway.schema",
                risk=RiskLevel.LOW,
            )

        votes = [d for stage in self.stages if (d := stage.evaluate(call, spec)) is not None]
        if not votes:
            return Decision(type=DecisionType.ALLOW, reason="No rule objected", rule_id=None, risk=RiskLevel.LOW)
        return max(votes, key=lambda d: _SEVERITY[d.type])

    def _finish(self, call: ToolCall, result: ToolResult) -> ToolResult:
        self.tracer.emit(TraceKind.TOOL_RESULT, call_id=call.id, **result.model_dump(mode="json", exclude={"call_id"}))
        return result
