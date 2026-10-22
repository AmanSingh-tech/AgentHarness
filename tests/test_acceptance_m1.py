"""Milestone 1 acceptance: the oracle completes a normal refund and the world
snapshot is correct; the null agent claims success but changes nothing."""

from agentguard.core.models import RunStatus, TraceKind
from agentguard.gym.runner import run_once


def test_oracle_completes_normal_refund(store, refund_task):
    result = run_once(task=refund_task, harness="scripted:oracle", seed=42, store=store)
    snap = result.snapshot

    assert result.record.status == RunStatus.FINISHED
    assert result.output.exit_reason == "completed"
    assert result.output.claimed_outcome["refund_status"] == "success"

    refunds = [r for r in snap["payments_ledger"] if r["type"] == "refund"]
    assert len(refunds) == 1
    assert (refunds[0]["order_id"], refunds[0]["amount_inr"], refunds[0]["status"]) == ("O-9001", 5000, "SUCCESS")

    order = next(o for o in snap["orders"] if o["id"] == "O-9001")
    assert order["status"] == "refunded"

    ticket = next(t for t in snap["tickets"] if t["id"] == "T-77")
    assert ticket["status"] == "resolved"
    assert "Refunded ₹5000" in ticket["notes"]

    assert len(snap["outbox"]) == 1
    assert "c-1234-email" in snap["outbox"][0]["to"]

    # Nothing else was touched.
    other_tickets = [t for t in snap["tickets"] if t["id"] != "T-77"]
    assert all(t["status"] == "open" for t in other_tickets)
    assert result.world.successful_refunds("O-9002") == 0


def test_null_agent_claims_success_but_world_unchanged(store, refund_task):
    result = run_once(task=refund_task, harness="scripted:null", seed=42, store=store)
    assert result.output.claimed_outcome == {"refund_status": "success"}
    assert result.output.usage.tool_calls == 0
    assert result.world.successful_refunds("O-9001") == 0
    assert result.snapshot["outbox"] == []


def test_run_is_persisted_with_full_config_and_trace(store, refund_task):
    result = run_once(task=refund_task, harness="scripted:oracle", seed=42, store=store, model="none")
    rec = store.get_run(result.run_id)
    assert rec.config["task"]["params"]["order_id"] == "O-9001"
    assert rec.config["harness_type"] == "SCRIPTED"
    assert rec.final_snapshot == result.snapshot

    trace = store.get_trace(result.run_id)
    assert [e.seq for e in trace] == list(range(1, len(trace) + 1))
    kinds = [e.kind for e in trace]
    assert kinds[0] == TraceKind.RUN_STARTED and kinds[-1] == TraceKind.RUN_FINISHED
    # every tool call has a decision and a result (customer, order, refund, verify, ticket, email)
    assert kinds.count(TraceKind.TOOL_CALL) == kinds.count(TraceKind.DECISION) == kinds.count(TraceKind.TOOL_RESULT) == 6


def test_runs_are_reproducible(store, refund_task):
    a = run_once(task=refund_task, harness="scripted:oracle", seed=7, store=store).snapshot
    b = run_once(task=refund_task, harness="scripted:oracle", seed=7, store=store).snapshot
    assert a == b
