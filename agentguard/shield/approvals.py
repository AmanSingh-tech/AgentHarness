"""Human-in-the-loop approvals.

A REQUIRE_APPROVAL decision creates an Approval and the tool call blocks in
`wait()` until someone resolves it, or until the timeout (which rejects by
default). Every approval is persisted, and the gateway emits trace events for
the request and the resolution, which is how the dashboard sees them live.

In AgentGym an AutoApprover resolves requests immediately so runs stay unattended.
"""

from __future__ import annotations

import fnmatch
import threading
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

from agentguard.core.models import Approval, ApprovalStatus, Decision, ToolCall, utcnow

if TYPE_CHECKING:
    from agentguard.core.store import Store


class AutoApproverRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str | None = None  # glob over the decision's rule id, e.g. "bulk_pii_*"
    tool: str | None = None
    decision: Literal["approve", "reject"]


class AutoApprover(BaseModel):
    """First matching rule wins; otherwise `default`. `manual` leaves the request
    pending for a human (or the timeout)."""

    model_config = ConfigDict(extra="forbid")

    default: Literal["approve", "reject", "manual"] = "approve"
    rules: list[AutoApproverRule] = Field(default_factory=list)

    def decide(self, approval: Approval) -> tuple[Literal["approve", "reject", "manual"], str]:
        for i, r in enumerate(self.rules):
            if r.tool is not None and r.tool != approval.tool:
                continue
            if r.rule_id is not None and not fnmatch.fnmatchcase(approval.decision.rule_id or "", r.rule_id):
                continue
            return r.decision, f"auto:rule[{i}]"
        return self.default, "auto:default"


class ApprovalQueue:
    def __init__(
        self,
        store: "Store | None" = None,
        auto: AutoApprover | None = None,
        timeout_s: float = 300.0,
        on_timeout: Literal["reject", "approve"] = "reject",
    ) -> None:
        self.store = store
        self.auto = auto
        self.timeout_s = timeout_s
        self.on_timeout = on_timeout
        self._items: dict[str, Approval] = {}
        self._events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def request(self, call: ToolCall, decision: Decision) -> Approval:
        approval = Approval(
            run_id=call.run_id, call_id=call.id, agent_id=call.agent_id, tool=call.tool, args=call.args, decision=decision
        )
        with self._lock:
            self._items[approval.id] = approval
            self._events[approval.id] = threading.Event()
        self._persist(approval)
        if self.auto is not None:
            verdict, by = self.auto.decide(approval)
            if verdict != "manual":
                return self.resolve(approval.id, verdict == "approve", by=by)
        return approval

    def wait(self, approval_id: str, timeout_s: float | None = None) -> Approval:
        event = self._events[approval_id]
        if not event.wait(self.timeout_s if timeout_s is None else timeout_s):
            with self._lock:
                approval = self._items[approval_id]
                if approval.status == ApprovalStatus.PENDING:
                    approval.status = ApprovalStatus.TIMED_OUT
                    approval.resolved_by = "timeout"
                    approval.note = f"no decision within {self.timeout_s}s; treated as {self.on_timeout}"
                    approval.resolved_at = utcnow()
            self._persist(approval)
        return self._items[approval_id]

    def resolve(self, approval_id: str, approved: bool, by: str, note: str | None = None) -> Approval:
        with self._lock:
            approval = self._items.get(approval_id)
            if approval is None:
                raise KeyError(approval_id)
            if approval.status != ApprovalStatus.PENDING:
                raise ValueError(f"approval {approval_id} is already {approval.status.value}")
            approval.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
            approval.resolved_by = by
            approval.note = note
            approval.resolved_at = utcnow()
            event = self._events[approval_id]
        self._persist(approval)
        event.set()
        return approval

    def granted(self, approval: Approval) -> bool:
        if approval.status == ApprovalStatus.TIMED_OUT:
            return self.on_timeout == "approve"
        return approval.status == ApprovalStatus.APPROVED

    def get(self, approval_id: str) -> Approval | None:
        return self._items.get(approval_id)

    def pending(self) -> list[Approval]:
        with self._lock:
            return [a for a in self._items.values() if a.status == ApprovalStatus.PENDING]

    def _persist(self, approval: Approval) -> None:
        if self.store is not None:
            self.store.save_approval(approval)
