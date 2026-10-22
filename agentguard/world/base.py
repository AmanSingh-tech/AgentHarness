"""World / ToolBackend interfaces.

A ToolBackend is anything that can execute a named tool: the simulated worlds
in AgentGym, or real enterprise systems in production mode. A World is a
ToolBackend that can also be reset to a seeded state and fully snapshotted for
independent verification.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from agentguard.core.models import ToolSpec


class ToolExecutionError(Exception):
    """Raised by a backend for an expected, agent-visible tool failure."""

    def __init__(self, code: str, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class ToolBackend(ABC):
    @abstractmethod
    def tools(self) -> list[ToolSpec]: ...

    @abstractmethod
    def execute(self, tool: str, args: dict[str, Any]) -> Any:
        """Run the tool for real. Args have already been validated against the spec."""

    def tool(self, name: str) -> ToolSpec | None:
        return next((t for t in self.tools() if t.name == name), None)


class World(ToolBackend):
    name: str
    fixtures_dir: Path  # where scenario `initial_state` paths are resolved

    @abstractmethod
    def reset(self, seed: int) -> None: ...

    @abstractmethod
    def snapshot(self) -> dict[str, Any]:
        """Full, JSON-serialisable state dump. Ground truth for the verifier."""
