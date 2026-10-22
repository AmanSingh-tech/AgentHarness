"""Milestone 3 acceptance: the naive agent produces a duplicate refund and an
incorrect success claim, and both are detected; the oracle survives every fault.

These measure the agents on their own, so AgentShield is off (`shield=False`);
test_acceptance_m4.py runs the same scenarios with it on."""

from agentguard.gym.faults import FaultType
from agentguard.gym.runner import run_matrix, run_scenario
from agentguard.gym.scenario import find_scenario, load_scenarios
from agentguard.gym.verifier import Outcome


def test_naive_duplicate_refund_is_detected(store):
    r = run_scenario(find_scenario("refund_timeout_retry"), harness="scripted:naive", store=store, shield=False)
    refunds = [x for x in r.world.refunds_for("O-9006") if x["status"] == "SUCCESS"]
    assert len(refunds) == 2  # the duplicate really happened in the world
    assert len({x["idempotency_key"] for x in refunds}) == 2  # because each retry minted a new key

    v = r.verdict
    assert v.outcome == Outcome.UNSAFE_SIDE_EFFECT and not v.passed
    assert v.claim.kind == "success"  # it also claimed success
    assert any("expected 1" in u["reason"] for u in v.unsafe_side_effects)
    ledger = next(c for c in v.checks if c.kind == "ledger")
    assert (ledger.expected, ledger.actual) == (1, 2) and len(ledger.evidence) == 2


def test_naive_incorrect_success_claim_is_detected(store):
    r = run_scenario(find_scenario("refund_false_success"), harness="scripted:naive", store=store, shield=False)
    assert r.world.refunds_for("O-9001") == []
    v = r.verdict
    assert v.outcome == Outcome.INCORRECT_SUCCESS_CLAIM and not v.passed
    assert v.claim.kind == "success" and v.claim.source == "structured"
    assert "expected 1, found 0" in v.summary


def test_naive_follows_injected_instructions(store):
    r = run_scenario(find_scenario("ticket_prompt_injection"), harness="scripted:naive", store=store, shield=False)
    v = r.verdict
    assert v.outcome == Outcome.UNSAFE_SIDE_EFFECT
    assert [x["tool"] for x in v.violations] == ["query_database"]
    assert r.world.emails_to("exfil-mail.example")  # the export left the building


def test_every_fault_type_is_covered_and_oracle_is_reliable(store):
    faulted = [s for s in load_scenarios() if s.faults]
    used = {f.type for s in faulted for f in s.faults}
    # partial_failure has no natural target in the refund flow; it is unit-tested in test_faults.py
    assert used == set(FaultType) - {FaultType.PARTIAL_FAILURE}

    result = run_matrix(faulted, ["scripted:oracle", "scripted:naive"], store=store, attempts=2, parallel=8, shield=False)
    for s in faulted:
        assert result.cell(s.id, "scripted:oracle").pass_k, s.id
    naive_failed = {s.id for s in faulted if not result.cell(s.id, "scripted:naive").pass_k}
    assert naive_failed == {"refund_timeout_retry", "refund_false_success", "ticket_prompt_injection"}
