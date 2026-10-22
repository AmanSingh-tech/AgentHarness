from agentguard.world.base import ToolBackend, ToolExecutionError, World
from agentguard.world.enterprise.engine import EnterpriseWorld
from agentguard.world.itsm.world import ItsmWorld
from agentguard.world.support.world import SupportWorld

WORLDS: dict[str, type[World]] = {"support": SupportWorld, "itsm": ItsmWorld, "enterprise": EnterpriseWorld}


def make_world(name: str, **kwargs) -> World:
    try:
        return WORLDS[name](**kwargs)
    except KeyError:
        raise ValueError(f"Unknown world '{name}'. Available: {sorted(WORLDS)}") from None


__all__ = ["WORLDS", "EnterpriseWorld", "ItsmWorld", "SupportWorld", "ToolBackend", "ToolExecutionError", "World", "make_world"]
