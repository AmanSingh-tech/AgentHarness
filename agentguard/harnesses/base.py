"""Harness interface and plugin registry.

A harness spec string is "<key>:<variant>", e.g. "scripted:oracle" or (later)
"cli_sandbox:claude-code". `key` resolves to a harness class registered either
built-in or via the `agentguard.harnesses` entry-point group; `variant` is
passed to its constructor.
"""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Callable, ClassVar, Protocol, runtime_checkable

from agentguard.core.models import AgentOutput, Budget, HarnessCapabilities, HarnessType, RunContext, TaskSpec
from agentguard.transports.base import ToolEndpoint


@runtime_checkable
class AgentHarness(Protocol):
    name: str
    harness_type: HarnessType
    capabilities: ClassVar[HarnessCapabilities]

    def setup(self, run_ctx: RunContext) -> None: ...

    def run(self, task: TaskSpec, tools: ToolEndpoint, budget: Budget) -> AgentOutput: ...

    def teardown(self) -> None: ...


HarnessFactory = Callable[..., AgentHarness]
ENTRY_POINT_GROUP = "agentguard.harnesses"

_registry: dict[str, HarnessFactory] = {}


def register(key: str, factory: HarnessFactory) -> None:
    _registry[key] = factory


def _discover() -> dict[str, HarnessFactory]:
    found = dict(_registry)
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        found.setdefault(ep.name, ep.load())
    return found


def available() -> list[str]:
    return sorted(_discover())


def parse_spec(spec: str) -> tuple[str, str | None]:
    key, sep, variant = spec.partition(":")
    return key, (variant if sep else None)


def make_harness(spec: str, **kwargs) -> AgentHarness:
    key, variant = parse_spec(spec)
    factories = _discover()
    if key not in factories:
        raise ValueError(f"Unknown harness '{key}'. Available: {sorted(factories)}")
    return factories[key](variant, **kwargs) if variant is not None else factories[key](**kwargs)
