"""In-process transport: Python callables and native tool schemas that route
every invocation through the Gateway."""

from __future__ import annotations

from typing import Any, Callable, Literal

from agentguard.core.models import ToolResult, ToolSpec
from agentguard.core.tooling import EXPORTERS
from agentguard.shield.gateway import Gateway
from agentguard.transports.base import ToolEndpoint


class InProcessEndpoint(ToolEndpoint):
    kind = "inprocess"

    def __init__(self, gateway: Gateway, agent_id: str | None = None) -> None:
        self._gateway = gateway
        self.agent_id = agent_id  # None: the gateway's default identity

    def as_agent(self, agent_id: str) -> "InProcessEndpoint":
        """The same run, acting as another agent (its own permissions in the policy)."""
        return InProcessEndpoint(self._gateway, agent_id)

    def specs(self) -> list[ToolSpec]:
        return self._gateway.tools()

    def call(self, tool: str, args: dict[str, Any] | None = None) -> ToolResult:
        return self._gateway.call(tool, args or {}, agent_id=self.agent_id)

    @property
    def calls_made(self) -> int:
        return self._gateway.call_count

    def schemas(self, provider: Literal["anthropic", "openai", "gemini"]) -> list[dict[str, Any]]:
        export = EXPORTERS[provider]
        return [export(s) for s in self.specs()]

    def functions(self) -> dict[str, Callable[..., ToolResult]]:
        """Plain Python callables, one per tool, e.g. for framework adapters."""
        return {spec.name: self._make_fn(spec) for spec in self.specs()}

    def _make_fn(self, spec: ToolSpec) -> Callable[..., ToolResult]:
        def fn(**kwargs: Any) -> ToolResult:
            return self.call(spec.name, kwargs)

        fn.__name__ = spec.name
        fn.__doc__ = spec.description
        return fn
