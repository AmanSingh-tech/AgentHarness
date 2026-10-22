"""Thin provider interface for tool-calling LLM APIs.

A Provider owns one conversation in its API's native message format: the
harness starts it, asks for the next turn, and feeds tool results back. The
harness loop is the same for every provider (harnesses/llm/native.py).

SDKs are imported lazily so the core library installs without them:
`pip install -e ".[llm]"`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from agentguard.core.models import ToolSpec
from agentguard.core.tooling import EXPORTERS

# USD per million tokens (input, output). Models not listed are recorded with cost 0
# and `cost_known: false` in the run's usage notes.
PRICING: dict[str, tuple[float, float]] = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
}

# Models that accept server-side refusal fallbacks in the `fallbacks: "default"` form.
_FALLBACK_DEFAULT_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}


@dataclass
class ToolRequest:
    id: str
    name: str
    args: dict[str, Any]
    parse_error: str | None = None  # the model sent arguments that are not a JSON object


@dataclass
class Turn:
    text: str
    tool_calls: list[ToolRequest]
    stop_reason: str
    model: str  # the model that actually answered (may differ after a fallback)
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    refusal: str | None = None  # set when the provider declined the request
    notes: list[str] = field(default_factory=list)


class Provider(Protocol):
    name: str
    model: str

    def start(self, system: str, task: str, tools: list[ToolSpec]) -> None: ...

    def next(self) -> Turn: ...

    def add_tool_results(self, results: list[tuple[str, str, bool]]) -> None:
        """(tool call id, content, is_error) for every tool call of the last turn."""


def cost_usd(turn: Turn) -> tuple[float, bool]:
    price = PRICING.get(turn.model)
    if price is None:
        return 0.0, False
    inp, out = price
    total = (
        turn.input_tokens * inp
        + turn.cache_read_tokens * inp * 0.1
        + turn.cache_write_tokens * inp * 1.25
        + turn.output_tokens * out
    ) / 1_000_000
    return total, True


# ---------------------------------------------------------------------------
# Anthropic (Claude)
# ---------------------------------------------------------------------------


class AnthropicProvider:
    name = "anthropic"
    default_model = "claude-opus-5-5"

    def __init__(
        self,
        model: str | None = None,
        client: Any = None,
        max_tokens: int = 16000,
        effort: str | None = "high",
        fallbacks: bool = True,
    ) -> None:
        self.model = model or self.default_model
        self.max_tokens = max_tokens
        self.effort = effort
        self.fallbacks = fallbacks and self.model in _FALLBACK_DEFAULT_MODELS
        if client is None:
            import anthropic  # lazy: optional dependency

            client = anthropic.Anthropic()
        self.client = client
        self.system = ""
        self.messages: list[dict[str, Any]] = []
        self.tools: list[dict[str, Any]] = []

    def start(self, system: str, task: str, tools: list[ToolSpec]) -> None:
        self.system = system
        self.tools = [EXPORTERS["anthropic"](t) for t in tools]
        self.messages = [{"role": "user", "content": task}]

    def next(self) -> Turn:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": self.system,
            "messages": self.messages,
            "tools": self.tools,
        }
        if self.effort:
            kwargs["output_config"] = {"effort": self.effort}
        if self.fallbacks:
            # If a safety classifier declines, the API re-runs the request on a suitable model.
            response = self.client.beta.messages.create(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
            )
        else:
            response = self.client.messages.create(**kwargs)

        # Append the full content (thinking blocks included) so the history stays valid.
        self.messages.append({"role": "assistant", "content": response.content})
        usage = response.usage
        turn = Turn(
            text="".join(b.text for b in response.content if b.type == "text"),
            tool_calls=[ToolRequest(b.id, b.name, dict(b.input)) for b in response.content if b.type == "tool_use"],
            stop_reason=response.stop_reason or "",
            model=getattr(response, "model", None) or self.model,
            input_tokens=usage.input_tokens or 0,
            output_tokens=usage.output_tokens or 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
        )
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            turn.refusal = f"declined ({getattr(details, 'category', None) or 'no category'})"
        if turn.model != self.model:
            turn.notes.append(f"served by fallback model {turn.model}")
        return turn

    def add_tool_results(self, results: list[tuple[str, str, bool]]) -> None:
        if not results:
            # pause_turn or a turn without tool calls: continue the same assistant turn
            return
        self.messages.append({
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": i, "content": c, "is_error": e} for i, c, e in results],
        })


# ---------------------------------------------------------------------------
# OpenAI (chat completions with function calling)
# ---------------------------------------------------------------------------


class OpenAIProvider:
    name = "openai"
    default_model = None  # no default: pass --model explicitly

    def __init__(self, model: str | None = None, client: Any = None, max_tokens: int = 16000) -> None:
        if not model:
            raise ValueError("the openai provider needs a model: pass --model <name>")
        self.model = model
        self.max_tokens = max_tokens
        if client is None:
            import openai  # lazy: optional dependency

            client = openai.OpenAI()
        self.client = client
        self.messages: list[dict[str, Any]] = []
        self.tools: list[dict[str, Any]] = []

    def start(self, system: str, task: str, tools: list[ToolSpec]) -> None:
        self.tools = [EXPORTERS["openai"](t) for t in tools]
        self.messages = [{"role": "system", "content": system}, {"role": "user", "content": task}]

    def next(self) -> Turn:
        response = self.client.chat.completions.create(
            model=self.model, messages=self.messages, tools=self.tools, max_completion_tokens=self.max_tokens,
        )
        choice = response.choices[0]
        msg = choice.message
        calls = []
        for tc in msg.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
                error = None if isinstance(args, dict) else "arguments must be a JSON object"
            except json.JSONDecodeError as e:
                args, error = {}, f"invalid JSON arguments: {e}"
            calls.append(ToolRequest(tc.id, tc.function.name, args if isinstance(args, dict) else {}, error))
        self.messages.append({
            "role": "assistant",
            "content": msg.content,
            **({"tool_calls": [
                {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ]} if msg.tool_calls else {}),
        })
        usage = response.usage
        cached = getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", 0) or 0
        turn = Turn(
            text=msg.content or "",
            tool_calls=calls,
            stop_reason=choice.finish_reason or "",
            model=getattr(response, "model", None) or self.model,
            input_tokens=(usage.prompt_tokens or 0) - cached if usage else 0,
            output_tokens=(usage.completion_tokens or 0) if usage else 0,
            cache_read_tokens=cached,
        )
        if getattr(msg, "refusal", None):
            turn.refusal = f"declined: {msg.refusal}"
        return turn

    def add_tool_results(self, results: list[tuple[str, str, bool]]) -> None:
        for call_id, content, _ in results:
            self.messages.append({"role": "tool", "tool_call_id": call_id, "content": content})


PROVIDERS: dict[str, type] = {"anthropic": AnthropicProvider, "openai": OpenAIProvider}


def make_provider(name: str, model: str | None = None, **kwargs: Any) -> Provider:
    try:
        cls = PROVIDERS[name]
    except KeyError:
        raise ValueError(f"unknown provider '{name}' (available: {sorted(PROVIDERS)})") from None
    return cls(model=model, **kwargs)
