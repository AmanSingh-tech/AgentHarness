"""Production (runtime) mode: AgentShield in front of a real ToolBackend.

The same gateway, policy, approvals, post-action verification and hash-chained
audit trace as in AgentGym, but against a real system: no fault injection, no
world snapshots, and no verdict at the end (there is no ground truth to compare
with). Blocks and failed verifications can be promoted into draft AgentGym
scenarios on the backend's twin world (gym/regression.py: promote_runtime).

    session = RuntimeSession(backend, store, agent_id="support_agent")
    result = session.endpoint.call("get_order", {"order_id": "O-9001"})
    session.close()

`agentguard protect --backend <config.yaml>` serves a session over MCP for any MCP client.
"""

from __future__ import annotations

import time
from typing import Any

from agentguard.core.events import EventBus, Tracer
from agentguard.core.models import AgentOutput, RunRecord, RunStatus, TraceKind, Usage, new_id
from agentguard.core.store import Store
from agentguard.shield.approvals import ApprovalQueue, AutoApprover
from agentguard.shield.gateway import Gateway
from agentguard.shield.pipeline import Shield
from agentguard.shield.policy import load_policy, resolve_policy_path
from agentguard.transports.inprocess import InProcessEndpoint
from agentguard.world.base import ToolBackend


class RuntimeSession:
    def __init__(
        self,
        backend: ToolBackend,
        store: Store,
        *,
        agent_id: str,
        policy: str = "default",
        approvals: ApprovalQueue | None = None,
        bus: EventBus | None = None,
        client: str = "external",
        task: str | None = None,
        backend_config: dict[str, Any] | None = None,
    ) -> None:
        self.store = store
        self.run_id = new_id("run")
        self.started = time.monotonic()
        bus = bus or EventBus()
        self.config = {
            "mode": "runtime",
            "backend": getattr(backend, "name", type(backend).__name__),
            "backend_config": backend_config,
            "agent_id": agent_id,
            "task": {"text": task} if task else None,
            "shield": {"policy": policy, "policy_path": str(resolve_policy_path(policy))},
            "harness_type": "RUNTIME",
        }
        store.create_run(RunRecord(id=self.run_id, status=RunStatus.RUNNING, world=self.config["backend"], seed=0,
                                   harness=f"runtime:{client}", config=self.config))
        self._unsubscribe = bus.subscribe(store.append_event, run_id=self.run_id)
        self.tracer = Tracer(bus, self.run_id)
        self.shield = Shield(load_policy(policy), backend)
        self.approvals = approvals or ApprovalQueue(store, auto=AutoApprover(default="manual"), timeout_s=300)
        self.gateway = Gateway(backend, self.tracer, agent_id=agent_id, stages=self.shield.stages,
                               approvals=self.approvals)
        self.endpoint = InProcessEndpoint(self.gateway)
        self.tracer.emit(TraceKind.RUN_STARTED, **self.config)
        if task:
            findings = self.shield.scan_task(task)
            if findings:
                self.tracer.emit(TraceKind.INJECTION_DETECTED, source="task", findings=[f.to_dict() for f in findings],
                                 note="Task text flagged as a possible injection. Policy still governs every action.")
        self.closed = False

    def close(self, output: AgentOutput | None = None, status: RunStatus = RunStatus.FINISHED) -> RunRecord:
        if self.closed:
            raise RuntimeError(f"session {self.run_id} is already closed")
        self.closed = True
        usage = Usage(wall_time_s=round(time.monotonic() - self.started, 3), tool_calls=self.gateway.call_count)
        output = output or AgentOutput(final_message="session closed", exit_reason="completed", usage=usage)
        output.usage.wall_time_s, output.usage.tool_calls = usage.wall_time_s, usage.tool_calls
        self.tracer.emit(TraceKind.AGENT_OUTPUT, **output.model_dump(mode="json"))
        self.tracer.emit(TraceKind.RUN_FINISHED, status=status.value, tool_calls=self.gateway.call_count)
        self._unsubscribe()
        self.store.finish_run(self.run_id, status, output, None)
        record = self.store.get_run(self.run_id)
        assert record is not None
        return record
