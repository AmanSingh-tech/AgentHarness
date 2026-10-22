from agentguard.gym.metrics import compute_metrics
from agentguard.gym.runner import run_matrix
from agentguard.gym.scenario import find_scenario

import pytest


def test_metrics_over_a_matrix(store):
    scenarios = [find_scenario(s) for s in ("normal_refund", "refund_timeout_retry", "refund_false_success",
                                            "ticket_prompt_injection", "secret_exfiltration")]
    run_matrix(scenarios, ["scripted:oracle", "scripted:naive", "scripted:adversarial"], store=store, attempts=2,
               parallel=8, agent_version="v1")
    rows = {r["group"]["harness"]: r for r in compute_metrics(store)}

    oracle, naive, adv = rows["scripted:oracle"], rows["scripted:naive"], rows["scripted:adversarial"]
    assert oracle["runs"] == 10 and oracle["group"]["agent_version"] == "v1"
    # the oracle fails only the scenario it is not the reference agent for (secret_exfiltration)
    assert oracle["reliability"]["task_success_rate"] == 0.8 and oracle["reliability"]["pass_k"] == 0.8
    assert oracle["reliability"]["failure_recovery_rate"] == 1.0
    assert naive["reliability"]["incorrect_success_claim_rate"] == pytest.approx(0.2)  # false_success scenario
    assert naive["security"]["blocks_by_rule"]["no_duplicate_refund"] == 4  # 2 retries x 2 attempts
    assert naive["security"]["injections_detected"] >= 2
    assert adv["security"]["exfiltration_attempts_stopped"] > 0
    assert adv["security"]["policy_violations_attempted"] > 0
    for row in rows.values():
        gov = row["governance"]
        assert gov["audit_completeness"] == 1.0
        assert gov["blocks_with_explanation"] in (1.0, None)
        assert row["performance"]["latency_p95_s"] >= row["performance"]["latency_p50_s"]
    assert oracle["governance"]["approvals_requested"] == oracle["governance"]["approvals_granted"] > 0

    by_scenario = compute_metrics(store, group_by=("scenario",))
    assert {r["group"]["scenario"] for r in by_scenario} == {s.id for s in scenarios}
    with pytest.raises(ValueError):
        compute_metrics(store, group_by=("colour",))
