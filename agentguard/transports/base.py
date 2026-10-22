from __future__ import annotations

from typing import Literal

from agentguard.core.models import ToolSpec


class ToolEndpoint:
    """Where an agent sends tool calls. Harnesses receive one of these and must
    not give the agent any other route to the world. Every concrete endpoint
    (in-process, MCP, HTTP) terminates in shield.gateway.Gateway."""

    kind: Literal["inprocess", "mcp", "http"]

    def specs(self) -> list[ToolSpec]:
        raise NotImplementedError
