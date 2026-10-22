"""The single choke point every tool call passes through.

The gateway validates arguments, asks each decision stage to vote (AgentShield's
stages live in shield/pipeline.py), applies the most restrictive vote, waits
for approval when one is required, executes against a ToolBackend, and lets
stages observe the result. Every step emits a TraceEvent. With no stages every
valid call is ALLOWed, and the decision says so explicitly.

In AgentGym runs an optional FaultHook sits between the decision and the
backend: it decides whether the real call happens and what the agent sees.
Production mode never sets one.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Any, Callable, Protocol

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
    decision_rank,
    max_risk,
)
from agentguard.core.tooling import validate_args
from agentguard.world.base import ToolBackend, ToolExecutionError

if TYPE_CHECKING:
    from agentguard.shield.approvals import ApprovalQueue


class DecisionStage(Protocol):
    """A pipeline stage. Returns None to abstain, or a Decision.

    A stage may also define `observe(call, spec, result) -> list[(TraceKind, payload)]`,
    called in stage order after the tool ran; it may modify the result in place
    (labels, redaction) and returns extra trace events."""

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


class Gateway:
    def __init__(
        self,
        backend: ToolBackend,
        tracer: Tracer,
        agent_id: str,
        stages: list[DecisionStage] | None = None,
        faults: FaultHook | None = None,
        approvals: "ApprovalQueue | None" = None,
    ) -> None:
        self.backend = backend
        self.tracer = tracer
        self.agent_id = agent_id
        self.stages = list(stages or [])
        self.faults = faults
        self.approvals = approvals
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

    def call(self, tool: str, args: dict[str, Any] | None = None, agent_id: str | None = None) -> ToolResult:
        """`agent_id` overrides the gateway's default identity: several agents of one
        multi-agent system share a run (and its trace and shield session) but are each
        held to their own permissions in the policy."""
        args = dict(args or {})
        agent_id = agent_id or self.agent_id
        with self._lock:
            self._seq += 1
            seq = self._seq
        call = ToolCall(run_id=self.run_id, agent_id=agent_id, tool=tool, args=args, seq=seq)
        self.tracer.emit(TraceKind.TOOL_CALL, call_id=call.id, tool=tool, args=args, seq=seq, agent_id=agent_id)

        spec = self.backend.tool(tool)
        decision = self._decide(call, spec)
        self.tracer.emit(TraceKind.DECISION, call_id=call.id, tool=tool, **decision.model_dump(mode="json"))

        if decision.type == DecisionType.BLOCK:
            return self._finish(call, _refused(call, "BLOCKED", decision.reason))
        if decision.type == DecisionType.REQUIRE_APPROVAL:
            refusal = self._await_approval(call, decision)
            if refusal is not None:
                return self._finish(call, refusal)

        assert spec is not None  # _decide blocks unknown tools
        if self.faults is None:
            result = self._execute(call, spec)
        else:
            result, fault = self.faults.apply(call, spec, lambda: self._execute(call, spec))
            if fault is not None:
                self.tracer.emit(TraceKind.FAULT_INJECTED, call_id=call.id, **fault)

        for stage in self.stages:
            observe = getattr(stage, "observe", None)
            if observe is not None:
                for kind, payload in observe(call, spec, result) or []:
                    self.tracer.emit(kind, call_id=call.id, **payload)
        return self._finish(call, result)

    def _await_approval(self, call: ToolCall, decision: Decision) -> ToolResult | None:
        """Block until the approval is resolved. Returns a refusal, or None to proceed."""
        if self.approvals is None:
            return _refused(call, "BLOCKED", f"{decision.reason} Approval is required but no approval queue is "
                                             "configured, so the call fails closed.")
        approval = self.approvals.request(call, decision)
        self.tracer.emit(TraceKind.APPROVAL_REQUESTED, call_id=call.id, approval=approval.model_dump(mode="json"))
        approval = self.approvals.wait(approval.id)
        self.tracer.emit(TraceKind.APPROVAL_RESOLVED, call_id=call.id, approval=approval.model_dump(mode="json"))
        if self.approvals.granted(approval):
            return None
        code = "APPROVAL_TIMEOUT" if approval.status.value == "timed_out" else "APPROVAL_REJECTED"
        note = f" ({approval.note})" if approval.note else ""
        return _refused(call, code, f"Approval {approval.status.value} by {approval.resolved_by}{note}. "
                                    f"Approval was required because: {decision.reason}")

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

        votes = []
        for stage in self.stages:
            try:
                vote = stage.evaluate(call, spec)
            except Exception as e:  # a broken stage must never let a call through
                vote = Decision(type=DecisionType.BLOCK, reason=f"Stage '{stage.name}' failed ({type(e).__name__}: {e}); "
                                "failing closed.", rule_id=f"{stage.name}.error", risk=RiskLevel.HIGH, stage=stage.name)
            if vote is not None:
                votes.append(vote)
        if not votes:
            return Decision(type=DecisionType.ALLOW, reason="No rule objected", rule_id=None, risk=RiskLevel.LOW)
        winner = max(votes, key=decision_rank)
        return winner.model_copy(update={
            "risk": max_risk(*(v.risk for v in votes)),
            "evidence": {**winner.evidence, "votes": [
                {"stage": v.stage, "type": v.type.value, "rule_id": v.rule_id, "risk": v.risk.value, "reason": v.reason}
                for v in votes
            ]},
        })

    def _finish(self, call: ToolCall, result: ToolResult) -> ToolResult:
        self.tracer.emit(TraceKind.TOOL_RESULT, call_id=call.id, **result.model_dump(mode="json", exclude={"call_id"}))
        return result


def _refused(call: ToolCall, code: str, message: str) -> ToolResult:
    return ToolResult(call_id=call.id, tool=call.tool, ok=False, error=ToolError(code=code, message=message))
