"""REMOTE_HTTP harness: a black-box agent deployed as a web service.

    agentguard run --scenario normal_refund --harness remote_http:http://agent.internal:9200/run

For each run AgentGuard starts a tool gateway (transports/http_proxy.py) with a fresh
bearer token and POSTs the task to the agent:

    POST <agent url>
    {"run_id", "task": {"text", "params", "agent_role"},
     "gateway": {"base_url", "token"}, "budget": {...}}

The agent calls back GET /tools, POST /call and POST /submit on the gateway, then
answers the POST with {"final_message": "..."} (optionally "claimed_outcome").
Every action goes through the gateway and AgentShield; the reply is never evidence.
"""

from __future__ import annotations

import time
from typing import Any, ClassVar

from agentguard.core.models import AgentOutput, Budget, HarnessCapabilities, HarnessType, RunContext, TaskSpec, Usage
from agentguard.transports.base import ToolEndpoint
from agentguard.transports.http_proxy import build_http_gateway, new_token, serve_app
from agentguard.transports.inprocess import InProcessEndpoint
from agentguard.transports.mcp_proxy import output_from_submission


class RemoteHttpHarness:
    harness_type = HarnessType.REMOTE_HTTP
    capabilities: ClassVar[HarnessCapabilities] = HarnessCapabilities(supports_structured_claim=True)

    def __init__(self, agent_url: str | None = None) -> None:
        if not agent_url or not agent_url.startswith(("http://", "https://")):
            raise ValueError("remote_http needs the agent's URL: remote_http:http://host:port/path")
        self.agent_url = agent_url
        self.name = f"remote_http:{agent_url}"
        self.run_ctx: RunContext | None = None

    def setup(self, run_ctx: RunContext) -> None:
        self.run_ctx = run_ctx

    def teardown(self) -> None:
        self.run_ctx = None

    def run(self, task: TaskSpec, tools: ToolEndpoint, budget: Budget) -> AgentOutput:
        import httpx

        if not isinstance(tools, InProcessEndpoint):
            raise TypeError("RemoteHttpHarness serves the in-process endpoint over HTTP")
        submitted: dict[str, Any] = {}
        token = new_token()
        started = time.monotonic()
        calls_before = tools.calls_made

        def usage() -> Usage:
            return Usage(wall_time_s=round(time.monotonic() - started, 3), tool_calls=tools.calls_made - calls_before)

        with serve_app(build_http_gateway(tools, token, on_submit=submitted.update)) as gateway_url:
            body = {
                "run_id": self.run_ctx.run_id if self.run_ctx else None,
                "task": task.model_dump(mode="json"),
                "gateway": {"base_url": gateway_url, "token": token},
                "budget": budget.model_dump(mode="json"),
            }
            try:
                resp = httpx.post(self.agent_url, json=body, timeout=budget.max_wall_seconds)
            except httpx.TimeoutException:
                return AgentOutput(final_message="The remote agent exceeded the wall-clock budget.",
                                   exit_reason="budget_exceeded", usage=usage())
            except httpx.TransportError as e:
                return AgentOutput(final_message=f"Could not reach the remote agent: {e}", exit_reason="crashed",
                                   usage=usage())
        if resp.status_code >= 400:
            return AgentOutput(final_message=f"Remote agent answered HTTP {resp.status_code}: {resp.text[:300]}",
                               exit_reason="crashed", usage=usage())
        try:
            reply = resp.json()
        except ValueError:
            reply = {"final_message": resp.text}
        message = str(reply.get("final_message") or "(no final message)")
        if submitted:
            return output_from_submission(submitted, message, usage())
        claim = reply.get("claimed_outcome") if isinstance(reply.get("claimed_outcome"), dict) else None
        return AgentOutput(final_message=message, claimed_outcome=claim, exit_reason="completed", usage=usage())
