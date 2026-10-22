"""Shared types used by every AgentGuard component.

Everything that crosses a module boundary (tool calls, decisions, trace events,
run records) is a Pydantic model so it can be persisted, streamed over SSE and
diffed between runs without custom serialisation.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SideEffect(str, Enum):
    READ = "read"
    WRITE = "write"
    EXTERNAL = "external"  # leaves the trust boundary (email, webhook, ...)
    TRANSFORM = "transform"  # pure function of its input; propagates taint


class DataLabel(str, Enum):
    PII = "PII"
    PII_BULK = "PII_BULK"
    SECRET = "SECRET"
    UNTRUSTED = "UNTRUSTED"


class DecisionType(str, Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    ALLOW_WITH_REDACTION = "ALLOW_WITH_REDACTION"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class HarnessType(str, Enum):
    NATIVE_FUNCTION_CALLING = "NATIVE_FUNCTION_CALLING"
    FRAMEWORK = "FRAMEWORK"
    MCP_CLIENT = "MCP_CLIENT"
    CLI_SANDBOX = "CLI_SANDBOX"
    REMOTE_HTTP = "REMOTE_HTTP"
    SCRIPTED = "SCRIPTED"


class TraceKind(str, Enum):
    RUN_STARTED = "run_started"
    TOOL_CALL = "tool_call"
    INJECTION_DETECTED = "injection_detected"
    DECISION = "decision"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_RESOLVED = "approval_resolved"
    FAULT_INJECTED = "fault_injected"  # AgentGym only; never emitted in production mode
    TOOL_RESULT = "tool_result"
    TAINT_LABELLED = "taint_labelled"
    VERIFICATION = "verification"  # post-action check against the real system
    AGENT_OUTPUT = "agent_output"
    RUN_FINISHED = "run_finished"


ExitReason = Literal["completed", "gave_up", "budget_exceeded", "crashed", "escalated"]


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class ToolSpec(BaseModel):
    """Single source of truth for a tool. Native schemas, MCP tools, framework
    tools and HTTP routes are all generated from this."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    input_schema: dict[str, Any]
    side_effect: SideEffect
    irreversible: bool = False
    returns_labels: tuple[DataLabel, ...] = ()
    propagates_taint: bool = False
    # Arguments whose values the agent picks freely (nonces, idempotency keys). They are
    # ignored when comparing runs and when generating regression patterns.
    volatile_args: tuple[str, ...] = ()


class ToolCall(BaseModel):
    id: str = Field(default_factory=lambda: new_id("call"))
    run_id: str
    agent_id: str
    tool: str
    args: dict[str, Any]
    seq: int  # 1-based index of this call within the run
    ts: datetime = Field(default_factory=utcnow)


class ToolError(BaseModel):
    code: str  # NOT_FOUND, INVALID_ARGS, BLOCKED, TIMEOUT, INTERNAL, ...
    message: str
    retryable: bool = False
    retry_after_s: float | None = None  # set for rate limiting (HTTP 429 Retry-After)


class ToolResult(BaseModel):
    call_id: str
    tool: str
    ok: bool
    output: Any = None
    error: ToolError | None = None
    labels: list[DataLabel] = Field(default_factory=list)
    latency_ms: float = 0.0


_RISK_ORDER = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2, RiskLevel.CRITICAL: 3}


def risk_rank(level: RiskLevel) -> int:
    return _RISK_ORDER[level]


def max_risk(*levels: RiskLevel) -> RiskLevel:
    return max(levels, key=risk_rank, default=RiskLevel.LOW)


# Most restrictive decision wins when several stages vote.
_DECISION_ORDER = {
    DecisionType.ALLOW: 0,
    DecisionType.ALLOW_WITH_REDACTION: 1,
    DecisionType.REQUIRE_APPROVAL: 2,
    DecisionType.BLOCK: 3,
}


def decision_rank(decision: "Decision") -> tuple[int, int]:
    """Sort key: decision severity first, then risk."""
    return _DECISION_ORDER[decision.type], risk_rank(decision.risk)


class Decision(BaseModel):
    type: DecisionType
    reason: str  # always human-readable: shown verbatim in the trace UI and to the agent on a block
    rule_id: str | None = None
    risk: RiskLevel = RiskLevel.LOW
    stage: str | None = None  # which pipeline stage produced it
    evidence: dict[str, Any] = Field(default_factory=dict)  # e.g. the taint chain, matched pattern, rule inputs


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMED_OUT = "timed_out"


class Approval(BaseModel):
    id: str = Field(default_factory=lambda: new_id("appr"))
    run_id: str
    call_id: str
    agent_id: str
    tool: str
    args: dict[str, Any]
    decision: Decision
    status: ApprovalStatus = ApprovalStatus.PENDING
    resolved_by: str | None = None  # "human:<name>", "auto:<rule>", "timeout"
    note: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    resolved_at: datetime | None = None


# ---------------------------------------------------------------------------
# Tracing
# ---------------------------------------------------------------------------


class TraceEvent(BaseModel):
    run_id: str
    seq: int
    kind: TraceKind
    ts: datetime = Field(default_factory=utcnow)
    call_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Agent / harness I/O
# ---------------------------------------------------------------------------


class TaskSpec(BaseModel):
    """What the agent is asked to do. `text` is what an LLM agent sees;
    `params` are the same facts in structured form for scripted agents."""

    text: str
    params: dict[str, Any] = Field(default_factory=dict)
    agent_role: str = "support_agent"


class Budget(BaseModel):
    max_tool_calls: int = 50
    max_wall_seconds: float = 300.0
    max_tokens: int | None = None
    max_cost_usd: float | None = None


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    wall_time_s: float = 0.0
    tool_calls: int = 0


class AgentOutput(BaseModel):
    final_message: str  # what the agent CLAIMS happened
    claimed_outcome: dict[str, Any] | None = None
    exit_reason: ExitReason
    usage: Usage = Field(default_factory=Usage)


class HarnessCapabilities(BaseModel):
    supports_streaming: bool = False
    supports_structured_claim: bool = False
    supports_mcp: bool = False
    needs_docker: bool = False


class RunContext(BaseModel):
    run_id: str
    seed: int
    world: str
    agent_role: str
    harness: str  # full spec, e.g. "scripted:oracle"
    model: str | None = None
    agent_version: str | None = None
    workdir: str | None = None


class RunStatus(str, Enum):
    RUNNING = "running"
    FINISHED = "finished"
    CRASHED = "crashed"


class RunRecord(BaseModel):
    id: str
    status: RunStatus
    world: str
    seed: int
    harness: str
    model: str | None = None
    agent_version: str | None = None
    scenario_id: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    output: AgentOutput | None = None
    final_snapshot: dict[str, Any] | None = None
    verdict: dict[str, Any] | None = None  # gym.verifier.Verdict, stored as JSON
    created_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
