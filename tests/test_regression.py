"""Diagnosis and regression promotion."""

import pytest

from agentguard.gym.diagnose import Step, first_divergence
from agentguard.gym.regression import _forbidden_for, promote
from agentguard.gym.runner import run_scenario
from agentguard.gym.scenario import Scenario, find_scenario, load_scenarios


def test_first_divergence_ignores_volatile_args():
    a = [Step(1, "get_order", {"order_id": "O-1"}), Step(2, "issue_refund", {"order_id": "O-1", "idempotency_key": "x"})]
    b = [Step(1, "get_order", {"order_id": "O-1"}), Step(2, "issue_refund", {"order_id": "O-1", "idempotency_key": "y"})]
    assert first_divergence(a, b, {"issue_refund": ("idempotency_key",)}) is None
    d = first_divergence(a, b)
    assert d["step"] == 2 and "idempotency_key" in d["explanation"]
    assert "stopped" in first_divergence(a[:1], b)["explanation"]
    assert "already finished" in first_divergence(a, b[:1])["explanation"]
    assert "where the reference agent called" in first_divergence([b[1]], [a[0]])["explanation"]


def test_forbidden_pattern_is_most_general_that_spares_the_oracle():
    blocked = Step(5, "query_database", {"sql": "SELECT * FROM customers"})
    assert _forbidden_for(blocked, [Step(1, "get_order", {"order_id": "O-1"})]).args_match is None  # tool alone
    oracle = [Step(1, "query_database", {"sql": "SELECT id FROM orders"})]
    assert "customers" in _forbidden_for(blocked, oracle).args_match  # narrowed to the argument
    refund = Step(3, "issue_refund", {"order_id": "O-1", "amount_inr": 5, "idempotency_key": "k2"})
    same = [Step(3, "issue_refund", {"order_id": "O-1", "amount_inr": 5, "idempotency_key": "k1"})]
    assert _forbidden_for(refund, same, ("idempotency_key",)) is None  # only the nonce differs: cannot forbid


def test_promote_blocked_injection_run(store, tmp_path):
    r = run_scenario(find_scenario("ticket_prompt_injection"), harness="scripted:naive", store=store)
    p = promote(r.run_id, store, out_dir=tmp_path)
    assert p.accepted and p.path.exists()
    new = Scenario.load(p.path)
    assert new.id.startswith("reg_ticket_prompt_injection_") and "regression" in new.tags
    assert f"source_run:{r.run_id}" in new.tags
    assert new.faults == find_scenario("ticket_prompt_injection").faults
    assert any(f.tool_called == "query_database" and f.args_match is None for f in new.expected.forbidden)
    assert len(p.diagnosis.summary) == 3 and "injected_content" in p.diagnosis.summary[1]

    # the promoted scenario is part of the suite under that folder and stays valid
    assert [s.id for s in load_scenarios(tmp_path)] == [new.id]
    # promoting the same failure again is recognised as a duplicate
    again = run_scenario(find_scenario("ticket_prompt_injection"), harness="scripted:naive", store=store)
    assert "already covered" in promote(again.run_id, store, out_dir=tmp_path).reason


def test_promote_refuses_what_adds_nothing(store, tmp_path):
    ok = run_scenario(find_scenario("normal_refund"), harness="scripted:oracle", store=store)
    assert "nothing to regress" in promote(ok.run_id, store, out_dir=tmp_path).reason
    dup = run_scenario(find_scenario("refund_timeout_retry"), harness="scripted:naive", store=store, shield=False)
    assert "already covered" in promote(dup.run_id, store, out_dir=tmp_path).reason
    with pytest.raises(KeyError):
        promote("run_nope", store)


def test_promote_exfiltration_and_gate(store, tmp_path):
    r = run_scenario(find_scenario("secret_exfiltration"), harness="scripted:adversarial", store=store)
    p = promote(r.run_id, store, out_dir=tmp_path)
    assert p.accepted
    assert {f.tool_called for f in p.scenario.expected.forbidden} >= {"send_email", "read_secret"}


def test_promote_rejected_when_reference_agent_would_fail(store, tmp_path, monkeypatch):
    import agentguard.gym.regression as reg

    r = run_scenario(find_scenario("ticket_prompt_injection"), harness="scripted:naive", store=store)
    # pretend the reference agent makes the blocked call too: the only possible pattern would fail it
    monkeypatch.setattr(reg, "_forbidden_for", lambda blocked, oracle, volatile=(): reg.ForbiddenExpect(tool_called="get_order"))
    p = promote(r.run_id, store, out_dir=tmp_path)
    assert not p.accepted and "reference agent fails it" in p.reason
    assert list(tmp_path.iterdir()) == []
