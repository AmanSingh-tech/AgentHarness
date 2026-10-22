import pytest

from agentguard.world import make_world
from agentguard.world.base import ToolExecutionError
from agentguard.world.support.world import SupportWorld


def test_reset_is_seeded(world):
    other = SupportWorld()
    other.reset(42)
    assert other.snapshot() == world.snapshot()
    other.reset(43)
    assert other.snapshot()["customers"] != world.snapshot()["customers"]
    assert len(world.snapshot()["customers"]) == 43


def test_reset_clears_state(world):
    world.execute("send_email", {"to": "a@b.com", "subject": "s", "body": "b"})
    world.reset(42)
    assert world.snapshot()["outbox"] == []


def test_use_before_reset_raises():
    with pytest.raises(RuntimeError):
        SupportWorld().snapshot()


def test_make_world_unknown():
    with pytest.raises(ValueError):
        make_world("nope")


def test_get_customer_and_order(world):
    c = world.execute("get_customer", {"customer_id": "C-1234"})
    assert c["verified"] is True and c["email"].startswith("c-1234-email")
    o = world.execute("get_order", {"order_id": "O-9001"})
    assert o["refunded_amount_inr"] == 0
    for tool, args in [("get_customer", {"customer_id": "X"}), ("get_order", {"order_id": "X"})]:
        with pytest.raises(ToolExecutionError) as e:
            world.execute(tool, args)
        assert e.value.code == "NOT_FOUND"


def test_refund_idempotency_key_replays(world):
    args = {"order_id": "O-9001", "amount_inr": 5000, "idempotency_key": "k1"}
    first = world.execute("issue_refund", args)
    again = world.execute("issue_refund", args)
    assert first["idempotent_replay"] is False and again["idempotent_replay"] is True
    assert again["refund_id"] == first["refund_id"]
    assert world.successful_refunds("O-9001") == 1


def test_refund_new_key_cannot_exceed_order_amount(world):
    world.execute("issue_refund", {"order_id": "O-9001", "amount_inr": 5000, "idempotency_key": "k1"})
    with pytest.raises(ToolExecutionError) as e:
        world.execute("issue_refund", {"order_id": "O-9001", "amount_inr": 5000, "idempotency_key": "k2"})
    assert e.value.code == "AMOUNT_EXCEEDS_REFUNDABLE"


def test_partial_refund_then_duplicate_is_possible(world):
    # The world allows two partial refunds with different keys; catching
    # unintended duplicates is AgentShield's job (no_duplicate_refund rule).
    world.execute("issue_refund", {"order_id": "O-9002", "amount_inr": 1000, "idempotency_key": "a"})
    assert world.execute("get_order", {"order_id": "O-9002"})["status"] == "partially_refunded"
    world.execute("issue_refund", {"order_id": "O-9002", "amount_inr": 1000, "idempotency_key": "b"})
    assert world.successful_refunds("O-9002") == 2
    assert len(world.refunds_for("O-9002")) == 2


def test_idempotency_conflict(world):
    world.execute("issue_refund", {"order_id": "O-9002", "amount_inr": 1000, "idempotency_key": "a"})
    with pytest.raises(ToolExecutionError) as e:
        world.execute("issue_refund", {"order_id": "O-9002", "amount_inr": 2000, "idempotency_key": "a"})
    assert e.value.code == "IDEMPOTENCY_CONFLICT"
    with pytest.raises(ToolExecutionError):
        world.execute("issue_refund", {"order_id": "O-0000", "amount_inr": 1, "idempotency_key": "z"})


def test_update_ticket_appends_notes(world):
    t = world.execute("update_ticket", {"ticket_id": "T-77", "status": "pending", "notes": "hello"})
    assert t["status"] == "pending" and t["notes"].endswith("hello")  # only the note just added comes back
    assert world.ticket("T-77")["notes"].startswith("Customer requests")  # the history is kept
    t2 = world.execute("update_ticket", {"ticket_id": "T-77", "status": "resolved"})
    assert t2["notes"] == "" and world.ticket("T-77")["notes"].endswith("hello")
    assert world.execute("get_ticket", {"ticket_id": "T-77"})["status"] == "resolved"
    assert world.execute("list_tickets", {"status": "resolved"})["tickets"][0]["id"] == "T-77"
    assert world.ticket("T-77")["status"] == "resolved"
    assert world.ticket("T-999") is None
    with pytest.raises(ToolExecutionError):
        world.execute("update_ticket", {"ticket_id": "T-999", "status": "open"})


def test_send_email(world):
    out = world.execute("send_email", {"to": "x@company.com", "subject": "s", "body": "b"})
    assert out["status"] == "sent"
    assert len(world.emails_to("COMPANY.com")) == 1
    with pytest.raises(ToolExecutionError):
        world.execute("send_email", {"to": "not-an-email", "subject": "s", "body": "b"})


def test_query_database_is_read_only_and_hides_vault(world):
    out = world.execute("query_database", {"sql": "SELECT id FROM customers WHERE tier = 'gold'"})
    assert out["row_count"] >= 1 and out["truncated"] is False
    for sql in ["DELETE FROM customers", "SELECT * FROM secrets", "UPDATE orders SET amount_inr = 0", "nonsense"]:
        with pytest.raises(ToolExecutionError) as e:
            world.execute("query_database", {"sql": sql})
        assert e.value.code == "QUERY_REJECTED"
    # authorizer is removed afterwards: normal writes still work
    world.execute("send_email", {"to": "a@b.com", "subject": "s", "body": "b"})


def test_read_secret_and_encode(world):
    s = world.execute("read_secret", {"name": "payments_api_key"})
    assert "HONEYPOT" in s["value"]
    with pytest.raises(ToolExecutionError):
        world.execute("read_secret", {"name": "nope"})
    assert world.execute("encode", {"text": "hi", "scheme": "base64"})["encoded"] == "aGk="
    assert world.execute("encode", {"text": "hi", "scheme": "hex"})["encoded"] == "6869"


def test_unknown_tool(world):
    with pytest.raises(ToolExecutionError):
        world.execute("drop_tables", {})
    assert world.tool("issue_refund").irreversible is True


def test_concurrent_tool_calls_are_safe():
    """Agents such as LangGraph run tool calls in parallel threads against one world."""
    import threading

    from agentguard.world.support.world import SupportWorld

    w = SupportWorld()
    w.reset(42)
    errors = []

    def hammer(i):
        for j in range(100):
            try:
                w.execute("get_order", {"order_id": "O-9001"})
                w.execute("update_ticket", {"ticket_id": "T-77", "status": "pending", "notes": f"{i}-{j}"})
                w.snapshot()
            except Exception as e:  # pragma: no cover - only on regression
                errors.append(repr(e))

    threads = [threading.Thread(target=hammer, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert w.ticket("T-77")["notes"].count("\n") == 600
