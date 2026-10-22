from agentguard.core.models import Decision, DecisionType, RiskLevel, TraceKind
from agentguard.shield.gateway import Gateway
from agentguard.transports.inprocess import InProcessEndpoint


def _trace(bus, run_id="run_test"):
    events = []
    bus.subscribe(events.append, run_id=run_id)
    return events


def test_allowed_call_emits_call_decision_result(endpoint, bus):
    events = _trace(bus)
    r = endpoint.call("get_customer", {"customer_id": "C-1234"})
    assert r.ok and r.labels == ["PII"] and r.latency_ms >= 0
    assert [e.kind for e in events] == [TraceKind.TOOL_CALL, TraceKind.DECISION, TraceKind.TOOL_RESULT]
    assert len({e.call_id for e in events}) == 1
    assert events[1].payload["type"] == "ALLOW" and events[1].payload["reason"]


def test_unknown_tool_and_bad_args_are_blocked_with_reason(endpoint, world):
    r = endpoint.call("drop_tables", {})
    assert not r.ok and r.error.code == "BLOCKED" and "Unknown tool" in r.error.message
    r = endpoint.call("issue_refund", {"order_id": "O-9001", "amount_inr": "5000"})
    assert not r.ok and r.error.code == "BLOCKED" and "Invalid arguments" in r.error.message
    assert world.successful_refunds("O-9001") == 0


def test_tool_errors_become_results(endpoint):
    r = endpoint.call("get_order", {"order_id": "nope"})
    assert not r.ok and r.error.code == "NOT_FOUND"


def test_backend_exception_is_contained(world, bus):
    class Broken(type(world)):
        def execute(self, tool, args):
            raise ZeroDivisionError("boom")

    b = Broken()
    b.reset(1)
    from agentguard.core.events import Tracer

    r = Gateway(b, Tracer(bus, "x"), "a").call("get_order", {"order_id": "O-9001"})
    assert r.error.code == "INTERNAL" and "boom" in r.error.message


def test_stages_most_restrictive_wins(world, bus):
    from agentguard.core.events import Tracer

    class Vote:
        def __init__(self, name, decision):
            self.name, self.decision = name, decision

        def evaluate(self, call, spec):
            return self.decision

    stages = [
        Vote("abstain", None),
        Vote("approve", Decision(type=DecisionType.REQUIRE_APPROVAL, reason="big", rule_id="r1", risk=RiskLevel.HIGH)),
        Vote("block", Decision(type=DecisionType.BLOCK, reason="dup", rule_id="no_dup", risk=RiskLevel.CRITICAL)),
    ]
    gw = Gateway(world, Tracer(bus, "x"), "a", stages=stages)
    r = gw.call("issue_refund", {"order_id": "O-9001", "amount_inr": 5000, "idempotency_key": "k"})
    assert not r.ok and r.error.message == "dup"
    assert world.successful_refunds("O-9001") == 0


def test_endpoint_exports_and_functions(endpoint, gateway):
    assert len(endpoint.schemas("anthropic")) == len(gateway.tools()) == 8
    fns = endpoint.functions()
    assert fns["get_order"].__doc__.startswith("Look up an order")
    assert fns["get_order"](order_id="O-9001").ok
    assert endpoint.calls_made == 1
    assert isinstance(endpoint, InProcessEndpoint) and endpoint.kind == "inprocess"
