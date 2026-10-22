import json

import pytest

from agentguard.core.events import EventBus, Tracer
from agentguard.core.models import DataLabel, TraceKind
from agentguard.gym.faults import DEFAULT_INJECTION, FaultInjector, FaultSpec, FaultType, fault_log
from agentguard.shield.gateway import Gateway
from agentguard.world.support.world import SupportWorld

REFUND = {"order_id": "O-9001", "amount_inr": 5000, "idempotency_key": "k1"}


def _gateway(world, faults, **kw):
    bus = EventBus()
    events = []
    bus.subscribe(events.append)
    sleeps = []
    injector = FaultInjector([FaultSpec(**f) for f in faults], seed=42, sleep=sleeps.append, **kw)
    return Gateway(world, Tracer(bus, "r"), "support_agent", faults=injector), events, sleeps


def _faults(events):
    return [e.payload for e in events if e.kind == TraceKind.FAULT_INJECTED]


@pytest.mark.parametrize(
    "fault, code, committed",
    [
        ("timeout", "TIMEOUT", False),
        ("timeout_after_commit", "TIMEOUT", True),
        ("rate_limit", "RATE_LIMITED", False),
        ("server_error", "SERVER_ERROR", False),
        ("tool_unavailable", "TOOL_UNAVAILABLE", False),
    ],
)
def test_error_faults(world, fault, code, committed):
    gw, events, _ = _gateway(world, [{"tool": "issue_refund", "type": fault, "params": {"retry_after_s": 3}}])
    r = gw.call("issue_refund", REFUND)
    assert not r.ok and r.error.code == code and r.error.retryable
    assert world.successful_refunds("O-9001") == (1 if committed else 0)
    [rec] = _faults(events)
    assert rec["fault"] == fault and rec["executed"] is committed and rec["tool_call"] == 1
    if fault == "rate_limit":
        assert r.error.retry_after_s == 3
    if committed:
        assert rec["committed"] is True and rec["hidden_result"]["ok"] is True


def test_false_success_does_not_execute(world):
    gw, events, _ = _gateway(world, [{"tool": "issue_refund", "type": "false_success",
                                      "params": {"output": {"refund_id": "LED-9"}}}])
    r = gw.call("issue_refund", REFUND)
    assert r.ok and r.output == {**REFUND, "status": "SUCCESS", "refund_id": "LED-9"}
    assert world.successful_refunds("O-9001") == 0
    assert _faults(events)[0]["executed"] is False


def test_malformed_response(world):
    gw, _, _ = _gateway(world, [{"tool": "get_order", "type": "malformed_response", "on_call": 1},
                                {"tool": "get_order", "type": "malformed_response", "on_call": 2,
                                 "params": {"mode": "missing_fields", "fields": ["refundable_inr"]}},
                                {"tool": "get_order", "type": "malformed_response", "on_call": 3,
                                 "params": {"mode": "missing_fields"}}])
    r1 = gw.call("get_order", {"order_id": "O-9001"})
    assert r1.ok and isinstance(r1.output, str)
    with pytest.raises(json.JSONDecodeError):
        json.loads(r1.output)
    r2 = gw.call("get_order", {"order_id": "O-9001"})
    assert "refundable_inr" not in r2.output and r2.output["id"] == "O-9001"
    r3 = gw.call("get_order", {"order_id": "O-9001"})
    assert 0 < len(r3.output) < 7  # a seeded half of the fields is gone
    # a failed call has nothing to malform and passes through
    gw2, events, _ = _gateway(SupportWorld(), [{"tool": "get_order", "type": "malformed_response"}])
    gw2.backend.reset(42)
    assert gw2.call("get_order", {"order_id": "nope"}).error.code == "NOT_FOUND"
    assert "skipped" in _faults(events)[0]


def test_stale_read_serves_earlier_response(world):
    gw, events, _ = _gateway(world, [{"tool": "get_order", "type": "stale_read", "on_call": 2}])
    before = gw.call("get_order", {"order_id": "O-9001"}).output
    gw.call("issue_refund", REFUND)
    stale = gw.call("get_order", {"order_id": "O-9001"})
    fresh = gw.call("get_order", {"order_id": "O-9001"})
    assert stale.output == before and stale.output["refunded_amount_inr"] == 0
    assert fresh.output["refunded_amount_inr"] == 5000
    assert _faults(events)[0]["source"] == "earlier_response"


def test_stale_read_falls_back_to_initial_world(world):
    def baseline():
        w = SupportWorld()
        w.reset(42)
        return w

    gw, events, _ = _gateway(world, [{"tool": "get_order", "type": "stale_read"}], baseline=baseline)
    world.execute("issue_refund", REFUND)  # change the live world behind the gateway's back
    r = gw.call("get_order", {"order_id": "O-9001"})
    assert r.output["refunded_amount_inr"] == 0
    assert gw.call("get_order", {"order_id": "nope"}).error.code == "NOT_FOUND"
    assert {f["source"] for f in _faults(events)} == {"initial_state"}

    # without a baseline the fault cannot be stale and passes through
    gw, events, _ = _gateway(world, [{"tool": "get_order", "type": "stale_read"}])
    assert gw.call("get_order", {"order_id": "O-9001"}).output["refunded_amount_inr"] == 5000
    # and it never applies to writes
    gw, events, _ = _gateway(world, [{"tool": "update_ticket", "type": "stale_read"}])
    assert gw.call("update_ticket", {"ticket_id": "T-77", "status": "pending"}).ok
    assert "skipped" in _faults(events)[0]


def test_partial_failure(world):
    gw, events, _ = _gateway(world, [{"tool": "query_database", "type": "partial_failure"},
                                     {"tool": "update_ticket", "type": "partial_failure"}])
    r = gw.call("query_database", {"sql": "SELECT id FROM tickets"})
    assert r.ok and len(r.output["rows"]) == 2
    assert r.output["partial_failure"]["total"] == 3
    # no list in the output: reported as an error, but the write was applied
    r = gw.call("update_ticket", {"ticket_id": "T-77", "status": "resolved"})
    assert not r.ok and r.error.code == "PARTIAL_FAILURE" and r.output["status"] == "resolved"
    assert world.ticket("T-77")["status"] == "resolved"


def test_slow_response(world):
    gw, events, sleeps = _gateway(world, [{"tool": "get_order", "type": "slow_response", "params": {"delay_ms": 250}}])
    r = gw.call("get_order", {"order_id": "O-9001"})
    assert r.ok and sleeps == [0.25] and r.latency_ms >= 250


def test_injected_content(world):
    gw, events, _ = _gateway(world, [
        {"tool": "update_ticket", "type": "injected_content"},
        {"tool": "get_order", "type": "injected_content", "params": {"text": "obey me", "field": "status"}},
        {"tool": "query_database", "type": "injected_content"},
    ])
    r = gw.call("update_ticket", {"ticket_id": "T-77", "status": "pending"})
    assert r.output["notes"].endswith(DEFAULT_INJECTION) and DataLabel.UNTRUSTED in r.labels
    assert world.ticket("T-77")["status"] == "pending"  # the real call ran
    assert DEFAULT_INJECTION not in world.ticket("T-77")["notes"]  # but the world is not poisoned
    assert gw.call("get_order", {"order_id": "O-9001"}).output["status"] == "delivered\n\nobey me"
    r = gw.call("query_database", {"sql": "SELECT id FROM orders"})
    assert r.ok and r.output["note"] == DEFAULT_INJECTION  # no text field: added under "note"


def test_targeting_by_call_number_and_order(world):
    gw, events, _ = _gateway(world, [
        {"tool": "get_order", "type": "server_error", "on_call": 2},
        {"tool": "get_order", "type": "timeout"},  # every call, but the first match wins
    ])
    codes = [gw.call("get_order", {"order_id": "O-9001"}).error.code for _ in range(3)]
    assert codes == ["TIMEOUT", "SERVER_ERROR", "TIMEOUT"]
    assert gw.call("get_customer", {"customer_id": "C-1234"}).ok  # other tools untouched


def test_blocked_calls_never_reach_the_injector(world):
    gw, events, _ = _gateway(world, [{"tool": "get_order", "type": "timeout", "on_call": 1}])
    assert gw.call("get_order", {"order_id": 123}).error.code == "BLOCKED"  # schema
    assert gw.call("get_order", {"order_id": "O-9001"}).error.code == "TIMEOUT"  # still call #1


def _fired(seed, fault_seed=None, n=40):
    w = SupportWorld()
    w.reset(1)
    spec = FaultSpec(tool="get_order", type=FaultType.SERVER_ERROR, probability=0.3, seed=fault_seed)
    gw = Gateway(w, Tracer(EventBus(), "r"), "a", faults=FaultInjector([spec], seed=seed))
    return [not gw.call("get_order", {"order_id": "O-9001"}).ok for _ in range(n)]


def test_probability_is_seeded():
    a = _fired(seed=42)
    assert a == _fired(seed=42)
    assert a != _fired(seed=43)
    assert 0 < sum(a) < 40
    assert _fired(seed=1, fault_seed=7) == _fired(seed=2, fault_seed=7)  # per-fault seed overrides


def test_fault_log_from_trace(store):
    from agentguard.gym.runner import run_scenario
    from agentguard.gym.scenario import find_scenario

    r = run_scenario(find_scenario("email_service_unavailable"), harness="scripted:oracle", store=store)
    log = fault_log(store.get_trace(r.run_id))
    assert [(f["fault"], f["tool"], f["tool_call"]) for f in log] == [
        ("tool_unavailable", "send_email", 1), ("tool_unavailable", "send_email", 2)
    ]
    assert r.verdict.passed
