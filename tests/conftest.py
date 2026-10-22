import pytest

from agentguard.core.events import EventBus, Tracer
from agentguard.core.models import TaskSpec
from agentguard.core.store import Store
from agentguard.shield.gateway import Gateway
from agentguard.transports.inprocess import InProcessEndpoint
from agentguard.world.support.world import SupportWorld


@pytest.fixture
def store() -> Store:
    return Store.in_memory()


@pytest.fixture
def world() -> SupportWorld:
    w = SupportWorld()
    w.reset(42)
    return w


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def gateway(world, bus) -> Gateway:
    return Gateway(world, Tracer(bus, "run_test"), agent_id="support_agent")


@pytest.fixture
def endpoint(gateway) -> InProcessEndpoint:
    return InProcessEndpoint(gateway)


@pytest.fixture
def refund_task() -> TaskSpec:
    return TaskSpec(
        text="Customer C-1234 asks for a refund of ₹5,000 for order O-9001. "
        "Verify, refund, update ticket T-77, and email confirmation.",
        params={"customer_id": "C-1234", "order_id": "O-9001", "amount_inr": 5000, "ticket_id": "T-77"},
    )
