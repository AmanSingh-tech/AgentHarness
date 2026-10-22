"""`ops:refunds` harness: RefundOps as an agent system that AgentGym can run, verify and benchmark.

    agentguard run --scenario refund_ops_inbox --harness ops:refunds
    agentguard ops run                     # the same, with the outcome report printed
"""

from __future__ import annotations

from typing import ClassVar

from agentguard.core.models import AgentOutput, Budget, HarnessCapabilities, HarnessType, RunContext, TaskSpec, Usage
from agentguard.transports.base import ToolEndpoint
from agentguard.transports.inprocess import InProcessEndpoint

PROCESSES = {"refunds", "access"}


class OpsHarness:
    harness_type = HarnessType.FRAMEWORK
    capabilities: ClassVar[HarnessCapabilities] = HarnessCapabilities(supports_structured_claim=True)

    def __init__(self, process: str = "refunds", policy: str = "default") -> None:
        if process not in PROCESSES:
            raise ValueError(f"unknown process '{process}' (available: {sorted(PROCESSES)})")
        self.process = process
        self.policy = policy
        self.name = f"ops:{process}"
        self.run_ctx: RunContext | None = None

    def setup(self, run_ctx: RunContext) -> None:
        self.run_ctx = run_ctx

    def teardown(self) -> None:
        self.run_ctx = None

    def run(self, task: TaskSpec, tools: ToolEndpoint, budget: Budget) -> AgentOutput:
        import time

        from agentguard.shield.policy import load_policy

        if not isinstance(tools, InProcessEndpoint):
            raise TypeError("OpsHarness uses the in-process endpoint")
        started, before = time.monotonic(), tools.calls_made
        if self.process == "refunds":
            from agentguard.ops.refunds import limits_from_policy, run_refund_ops

            limit, approval_above = limits_from_policy(load_policy(self.policy))
            report = run_refund_ops(tools, refund_limit_inr=limit, approval_above_inr=approval_above)
            s = report["summary"]
            message = (f"Processed {s['tickets']} tickets: {s['refunded']} refunded (₹{s['refunded_inr_verified']:,} "
                       f"confirmed in the ledger), {s['refused']} refused, {s['escalated']} escalated, "
                       f"{s['awaiting_info']} waiting for the customer, {s['routed']} routed, "
                       f"{s['stopped_by_controls']} stopped by controls.")
            unverified = s["refunds_unverified"]
        else:
            from agentguard.ops.access import run_access_ops

            report = run_access_ops(tools)
            s = report["summary"]
            message = (f"Processed {s['requests']} access requests: {s['granted']} granted ({s['grants_verified']} "
                       f"confirmed in the directory), {s['denied']} denied, {s['already_had_access']} already in place, "
                       f"{s['escalated']} escalated, {s['awaiting_info']} waiting for the requester, "
                       f"{s['stopped_by_controls']} stopped by controls.")
            unverified = s["grants_unverified"]
        usage = Usage(wall_time_s=round(time.monotonic() - started, 3), tool_calls=tools.calls_made - before)
        # Honest claim: the batch only counts as done if no step was stopped or failed.
        done = s["stopped_by_controls"] == 0 and s["failed"] == 0 and unverified == 0
        if not done:
            message += " Not every ticket could be handled as decided; see the report."
        return AgentOutput(final_message=message,
                           claimed_outcome={"process_status": "completed" if done else "escalated", **s},
                           exit_reason="completed", usage=usage, artifacts={"report": report})
