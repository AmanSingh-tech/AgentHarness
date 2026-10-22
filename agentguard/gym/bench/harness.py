"""`bench:solution`: runs a GuardBench task's reference `solve(api)` through the gateway.

The solution sees the same tools as any agent, via a small client:

    def solve(api):
        user = api.idp_get_user(id="U1")          # raises BenchApiError when the call fails
        r = api.try_("idp_suspend_user", id="U1")  # returns the ToolResult instead of raising
        return "Suspended the account and routed the ticket to Legal."
"""

from __future__ import annotations

import importlib.util
import time
from typing import Any, ClassVar

from agentguard.core.models import (AgentOutput, Budget, HarnessCapabilities, HarnessType, RunContext, TaskSpec,
                                    ToolResult, Usage)
from agentguard.transports.base import ToolEndpoint


class BenchApiError(RuntimeError):
    def __init__(self, tool: str, result: ToolResult) -> None:
        err = result.error
        super().__init__(f"{tool}: {err.code if err else 'ERROR'}: {err.message if err else ''}")
        self.tool, self.result = tool, result


class Api:
    def __init__(self, endpoint: ToolEndpoint) -> None:
        self._ep = endpoint

    def try_(self, tool: str, **args: Any) -> ToolResult:
        return self._ep.call(tool, args)

    def call(self, tool: str, **args: Any) -> Any:
        r = self._ep.call(tool, args)
        if not r.ok:
            raise BenchApiError(tool, r)
        return r.output

    def __getattr__(self, tool: str):
        if tool.startswith("_"):
            raise AttributeError(tool)
        return lambda **args: self.call(tool, **args)


def load_solution(task_id: str):
    from agentguard.gym.bench.loader import find_task

    path = find_task(task_id).solution_path
    spec = importlib.util.spec_from_file_location(f"guardbench_solution_{task_id.replace('-', '_')}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module.solve


class BenchSolutionHarness:
    harness_type = HarnessType.SCRIPTED
    capabilities: ClassVar[HarnessCapabilities] = HarnessCapabilities(supports_structured_claim=True)

    def __init__(self, variant: str = "solution") -> None:
        if variant != "solution":
            raise ValueError(f"unknown bench harness '{variant}' (available: ['solution'])")
        self.name = "bench:solution"
        self.run_ctx: RunContext | None = None

    def setup(self, run_ctx: RunContext) -> None:
        self.run_ctx = run_ctx

    def teardown(self) -> None:
        self.run_ctx = None

    def run(self, task: TaskSpec, tools: ToolEndpoint, budget: Budget) -> AgentOutput:
        task_id = task.params.get("bench_task")
        if not task_id:
            raise ValueError("bench:solution runs GuardBench tasks only (task.params.bench_task is missing)")
        started = time.monotonic()
        before = getattr(tools, "calls_made", 0)
        try:
            summary = load_solution(task_id)(Api(tools))
            status, message = "success", str(summary or "Done.")
        except BenchApiError as e:
            status, message = "failed", f"Stopped: {e}"
        usage = Usage(wall_time_s=round(time.monotonic() - started, 3),
                      tool_calls=getattr(tools, "calls_made", 0) - before)
        return AgentOutput(final_message=message, claimed_outcome={"status": status, "summary": message},
                           exit_reason="completed", usage=usage)
