"""FRAMEWORK harness: a LangGraph agent (built with langchain's `create_agent`)
whose tools are generated from the world's ToolSpecs and call the Gateway.

    agentguard run --scenario normal_refund --harness langgraph:anthropic --model claude-opus-5-5

Requires `pip install -e ".[langgraph]"`.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, ClassVar

from agentguard.core.models import (
    AgentOutput,
    Budget,
    HarnessCapabilities,
    HarnessType,
    RunContext,
    TaskSpec,
    ToolSpec,
    Usage,
)
from agentguard.harnesses.llm.native import _EXIT, DEFAULT_SYSTEM_PROMPT, SUBMIT, _render
from agentguard.harnesses.llm.providers import PRICING, AnthropicProvider
from agentguard.transports.base import ToolEndpoint
from agentguard.transports.inprocess import InProcessEndpoint


def chat_model(provider: str, model: str | None) -> Any:
    """Build the LangChain chat model for a provider."""
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=model or AnthropicProvider.default_model, max_tokens=16000)
    if provider == "openai":
        if not model:
            raise ValueError("the openai provider needs a model: pass --model <name>")
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=model)
    raise ValueError(f"unknown provider '{provider}' (available: ['anthropic', 'openai'])")


def make_tools(endpoint: InProcessEndpoint, on_submit: Callable[[dict[str, Any]], None], budget: Budget,
               calls_before: int) -> list[Any]:
    """One LangChain StructuredTool per ToolSpec, plus submit_result."""
    from langchain_core.tools import StructuredTool

    def world_tool(spec: ToolSpec) -> Any:
        def call(**kwargs: Any) -> str:
            if endpoint.calls_made - calls_before >= budget.max_tool_calls:
                return json.dumps({"ok": False, "error": {"code": "BUDGET", "message": "tool-call budget exhausted"}})
            return _render(endpoint.call(spec.name, kwargs))

        return StructuredTool.from_function(func=call, name=spec.name, description=spec.description,
                                            args_schema=spec.input_schema)

    def submit(**kwargs: Any) -> str:
        on_submit(kwargs)
        return json.dumps({"ok": True, "output": "recorded"})

    tools = [world_tool(s) for s in endpoint.specs()]
    tools.append(StructuredTool.from_function(func=submit, name=SUBMIT.name, description=SUBMIT.description,
                                              args_schema=SUBMIT.input_schema, return_direct=True))
    return tools


class LangGraphHarness:
    harness_type = HarnessType.FRAMEWORK
    capabilities: ClassVar[HarnessCapabilities] = HarnessCapabilities(supports_structured_claim=True)

    def __init__(self, provider: str = "anthropic", *, model_factory: Callable[[str, str | None], Any] | None = None,
                 system_prompt: str = DEFAULT_SYSTEM_PROMPT) -> None:
        self.provider = provider
        self.name = f"langgraph:{provider}"
        self._model_factory = model_factory or chat_model
        self.system_prompt = system_prompt
        self.run_ctx: RunContext | None = None

    def setup(self, run_ctx: RunContext) -> None:
        self.run_ctx = run_ctx

    def teardown(self) -> None:
        self.run_ctx = None

    def run(self, task: TaskSpec, tools: ToolEndpoint, budget: Budget) -> AgentOutput:
        if not isinstance(tools, InProcessEndpoint):
            raise TypeError("LangGraphHarness uses the in-process endpoint")
        from langchain.agents import create_agent
        from langgraph.errors import GraphRecursionError

        model_name = self.run_ctx.model if self.run_ctx else None
        llm = self._model_factory(self.provider, model_name)
        started = time.monotonic()
        calls_before = tools.calls_made
        submitted: dict[str, Any] = {}
        agent = create_agent(
            llm, make_tools(tools, submitted.update, budget, calls_before),
            system_prompt=self.system_prompt.format(role=task.agent_role.replace("_", " ")),
        )
        # Each tool round trip is two graph steps (model, tools); leave room for the final answer.
        config = {"recursion_limit": 2 * budget.max_tool_calls + 6}
        exit_reason, messages = "completed", []
        try:
            state = agent.invoke({"messages": [("user", task.text)]}, config=config)
            messages = state["messages"]
        except GraphRecursionError:
            exit_reason = "budget_exceeded"
        usage = _usage(messages, model_name or getattr(llm, "model", None) or getattr(llm, "model_name", None))
        usage.wall_time_s = round(time.monotonic() - started, 3)
        usage.tool_calls = tools.calls_made - calls_before

        last_text = next((m.content for m in reversed(messages)
                          if getattr(m, "type", "") == "ai" and isinstance(m.content, str) and m.content), "")
        if exit_reason == "budget_exceeded":
            return AgentOutput(final_message="Stopped: graph step limit reached.", exit_reason="budget_exceeded",
                               usage=usage)
        status = submitted.get("status")
        if status in _EXIT:
            return AgentOutput(final_message=str(submitted.get("summary", "")) or last_text,
                               claimed_outcome={"task_status": status, "summary": submitted.get("summary", "")},
                               exit_reason=_EXIT[status], usage=usage)
        return AgentOutput(final_message=last_text or "(no final message)", exit_reason="completed", usage=usage)


def _usage(messages: list[Any], model: str | None) -> Usage:
    u = Usage()
    for m in messages:
        meta = getattr(m, "usage_metadata", None)
        if meta:
            u.input_tokens += meta.get("input_tokens", 0)
            u.output_tokens += meta.get("output_tokens", 0)
    price = PRICING.get(model or "")
    if price:
        u.cost_usd = round((u.input_tokens * price[0] + u.output_tokens * price[1]) / 1_000_000, 6)
    return u
