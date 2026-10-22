"""Milestone 5 acceptance (offline): the same scenarios run under the native and
LangGraph harnesses, verdicts and metrics are recorded per harness + model.
The models are fakes replaying a fixed plan; tests/test_live_models.py is the
same check against real APIs."""

import pytest

from agentguard.gym.metrics import compute_metrics
from agentguard.gym.runner import run_matrix
from agentguard.gym.scenario import find_scenario
from agentguard.harnesses.base import register
from agentguard.harnesses.llm.native import NativeHarness
from agentguard.harnesses.llm.providers import AnthropicProvider

from tests.test_llm_harnesses import REFUND_PLAN, FakeAnthropic


def test_same_scenarios_across_harnesses_with_metrics(store):
    pytest.importorskip("langgraph")
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage

    from agentguard.harnesses.llm.langgraph_harness import LangGraphHarness

    class ToolCallingFake(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    def lg_model(provider, model):
        return ToolCallingFake(messages=iter([
            AIMessage(content="", tool_calls=[{"name": n, "args": a, "id": f"{i}{j}"} for j, (n, a) in enumerate(t)],
                      usage_metadata={"input_tokens": 100, "output_tokens": 10, "total_tokens": 110})
            for i, t in enumerate(REFUND_PLAN)]))

    # a fresh fake per run: each replays the plan from the start
    register("m5_native", lambda *a, **k: NativeHarness(
        "anthropic", provider_factory=lambda name, model=None, **kw: AnthropicProvider(model=model, client=FakeAnthropic(REFUND_PLAN))))
    register("m5_langgraph", lambda *a, **k: LangGraphHarness("anthropic", model_factory=lg_model))

    scenarios = [find_scenario("normal_refund"), find_scenario("customer_lookup_rate_limited")]
    result = run_matrix(scenarios, ["m5_native", "m5_langgraph", "scripted:oracle"], store=store,
                        models=["claude-opus-5-5"], attempts=2, parallel=4)
    for cell in result.cells:
        assert len(cell.runs) == 2 and all(r.verdict for r in cell.runs)

    rows = {r["group"]["harness"]: r for r in compute_metrics(store, group_by=("harness", "model"))}
    assert set(rows) == {"m5_native", "m5_langgraph", "scripted:oracle"}
    for h in ("m5_native", "m5_langgraph"):
        assert rows[h]["group"]["model"] == "claude-opus-5-5"
        assert rows[h]["performance"]["input_tokens"] > 0 and rows[h]["performance"]["cost_usd"] > 0
    for h in rows:
        # the rate-limit fault fired in every harness's runs and counts towards recovery
        assert rows[h]["reliability"]["failure_recovery_rate"] is not None
        assert rows[h]["reliability"]["task_success_rate"] == 1.0
        assert rows[h]["governance"]["audit_completeness"] == 1.0
