"""Milestone 2 acceptance: >= 10 scenarios pass for the oracle and fail for the null agent."""

from agentguard.gym.runner import validate_scenarios
from agentguard.gym.scenario import load_scenarios
from agentguard.gym.verifier import Outcome


def test_ten_scenarios_valid(store):
    scenarios = load_scenarios()
    assert len(scenarios) >= 10
    rows = validate_scenarios(scenarios, store=store, parallel=4)
    bad = [(r.scenario_id, r.null.summary, r.oracle.summary) for r in rows if not r.valid]
    assert not bad, bad
    # The null agent's failure mode is always a false success claim.
    assert {r.null.outcome for r in rows} == {Outcome.INCORRECT_SUCCESS_CLAIM}
    # Both kinds of scenario are represented.
    assert {r.oracle.outcome for r in rows} == {Outcome.CORRECT_SUCCESS, Outcome.CORRECT_FAILURE_REPORTED}
