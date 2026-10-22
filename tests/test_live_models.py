"""Milestone 5 acceptance against real models. Costs money, so it only runs when asked:

    AGENTGUARD_LIVE=1 ANTHROPIC_API_KEY=... pytest tests/test_live_models.py -s
    AGENTGUARD_LIVE=1 OPENAI_API_KEY=... AGENTGUARD_OPENAI_MODEL=<model> pytest tests/test_live_models.py -s

It checks that the scenarios run end to end and that metrics are recorded, not
that a given model passes them: that is what the benchmark is for.
"""

import os

import pytest

from agentguard.gym.metrics import compute_metrics
from agentguard.gym.runner import run_matrix
from agentguard.gym.scenario import find_scenario

pytestmark = pytest.mark.skipif(os.environ.get("AGENTGUARD_LIVE") != "1", reason="set AGENTGUARD_LIVE=1 to call real APIs")

SCENARIOS = ["normal_refund", "refund_timeout_retry", "ticket_prompt_injection", "unverified_customer_refused"]


def _combos():
    combos = []
    if os.environ.get("ANTHROPIC_API_KEY"):
        model = os.environ.get("AGENTGUARD_ANTHROPIC_MODEL", "claude-opus-5-5")
        combos += [("native:anthropic", model), ("langgraph:anthropic", model)]
    if os.environ.get("OPENAI_API_KEY") and os.environ.get("AGENTGUARD_OPENAI_MODEL"):
        combos += [("native:openai", os.environ["AGENTGUARD_OPENAI_MODEL"])]
    return combos


@pytest.mark.parametrize("harness, model", _combos() or [pytest.param(None, None, marks=pytest.mark.skip("no API keys"))])
def test_live_scenarios_record_metrics(store, harness, model):
    result = run_matrix([find_scenario(s) for s in SCENARIOS], [harness], store=store, models=[model], parallel=2)
    for run in result.runs:
        assert run.verdict is not None and run.output.exit_reason != "crashed", run.output.final_message
        print(f"{run.record.scenario_id:30} {run.verdict.outcome.value:28} calls={run.output.usage.tool_calls} "
              f"tokens={run.output.usage.input_tokens}/{run.output.usage.output_tokens} cost=${run.output.usage.cost_usd}")
    [row] = compute_metrics(store, result.runs and [r.record for r in result.runs] or [], group_by=("harness", "model"))
    assert row["runs"] == len(SCENARIOS) and row["performance"]["input_tokens"] > 0
