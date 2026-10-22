"""LLM harnesses driven by fake provider clients that replay a scripted conversation.

They exercise the real loop, gateway, shield and verifier; only the model is
canned. tests/test_live_models.py runs the same scenarios against real APIs
when keys are set."""

import json
from types import SimpleNamespace as NS

import pytest

from agentguard.gym.runner import run_scenario
from agentguard.gym.scenario import find_scenario
from agentguard.gym.verifier import Outcome
from agentguard.harnesses.base import register
from agentguard.harnesses.llm.native import NativeHarness
from agentguard.harnesses.llm.providers import AnthropicProvider, OpenAIProvider, cost_usd, Turn

REFUND_PLAN = [
    [("get_customer", {"customer_id": "C-1234"}), ("get_order", {"order_id": "O-9001"})],
    [("issue_refund", {"order_id": "O-9001", "amount_inr": 5000, "idempotency_key": "refund-O-9001"})],
    [("get_order", {"order_id": "O-9001"})],
    [("update_ticket", {"ticket_id": "T-77", "status": "resolved", "notes": "Refunded 5000"}),
     ("send_email", {"to": "c-1234-email@customer-domain.com", "subject": "Refund", "body": "Refunded."})],
    [("submit_result", {"status": "success", "summary": "Refunded ₹5,000 and emailed the customer."})],
]


# -- fake Anthropic client ---------------------------------------------------------------


class FakeAnthropic:
    """Returns one canned response per call; records every request."""

    def __init__(self, plan, model="claude-opus-5-5", final_text=None, stop_reason=None, served_by=None):
        self.plan = list(plan)
        self.requests = []
        self.model = model
        self.final_text = final_text
        self.stop_reason = stop_reason
        self.served_by = served_by
        self.messages = NS(create=self._create)
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        n = len(self.requests)
        usage = NS(input_tokens=1000, output_tokens=100, cache_read_input_tokens=0, cache_creation_input_tokens=0)
        if self.stop_reason == "refusal":
            return NS(content=[], stop_reason="refusal", stop_details=NS(category="cyber"), usage=usage, model=self.model)
        if not self.plan:
            return NS(content=[NS(type="text", text=self.final_text or "All done.")], stop_reason="end_turn",
                      usage=usage, model=self.model)
        calls = self.plan.pop(0)
        blocks = [NS(type="text", text="Working on it.")] + [
            NS(type="tool_use", id=f"tu_{n}_{i}", name=name, input=args) for i, (name, args) in enumerate(calls)
        ]
        return NS(content=blocks, stop_reason="tool_use", usage=usage, model=self.served_by or self.model)


def _register(key, client, **provider_kwargs):
    register(key, lambda *a, **k: NativeHarness(
        "anthropic", provider_factory=lambda name, model=None, **kw: AnthropicProvider(model=model, client=client,
                                                                                       **provider_kwargs)))


def test_native_anthropic_completes_refund(store):
    client = FakeAnthropic(REFUND_PLAN)
    _register("fake_anthropic", client)
    r = run_scenario(find_scenario("normal_refund"), harness="fake_anthropic", store=store, model="claude-opus-5-5")
    assert r.verdict.outcome == Outcome.CORRECT_SUCCESS, r.verdict.summary
    out = r.output
    assert out.exit_reason == "completed" and out.claimed_outcome["task_status"] == "success"
    assert out.usage.tool_calls == 6
    assert (out.usage.input_tokens, out.usage.output_tokens) == (5000, 500)
    assert out.usage.cost_usd == pytest.approx(5000 * 4 / 1e6 + 500 * 20 / 1e6)

    first = client.requests[0]
    assert first["model"] == "claude-opus-5-5" and first["fallbacks"] == "default"
    assert first["betas"] == ["server-side-fallback-2026-07-01"]
    assert first["output_config"] == {"effort": "high"}
    assert {t["name"] for t in first["tools"]} >= {"issue_refund", "submit_result"}
    # parallel tool results go back in a single user message, matched by id
    results = client.requests[1]["messages"][2]["content"]
    assert [r["tool_use_id"] for r in results] == ["tu_1_0", "tu_1_1"]
    assert json.loads(results[0]["content"])["output"]["id"] == "C-1234"


def test_tool_errors_and_shield_blocks_reach_the_model(store):
    plan = [[("read_secret", {"name": "anything"}), ("get_order", {"order_id": "nope"})],
            [("submit_result", {"status": "failed", "summary": "Could not do it."})]]
    client = FakeAnthropic(plan)
    _register("fake_anthropic_err", client)
    r = run_scenario(find_scenario("normal_refund"), harness="fake_anthropic_err", store=store)
    results = client.requests[1]["messages"][2]["content"]
    blocked, missing = (json.loads(x["content"]) for x in results)
    assert all(x["is_error"] for x in results)
    assert blocked["error"]["code"] == "BLOCKED" and "read_secret" in blocked["error"]["message"]
    assert missing["error"]["code"] == "NOT_FOUND"
    assert r.output.exit_reason == "gave_up"
    assert r.verdict.outcome == Outcome.POLICY_VIOLATION_ATTEMPTED  # read_secret is forbidden in this scenario


def test_end_without_submit_uses_text_claim(store):
    _register("fake_anthropic_text", FakeAnthropic([], final_text="I could not find the order, escalating."))
    r = run_scenario(find_scenario("normal_refund"), harness="fake_anthropic_text", store=store)
    assert r.output.claimed_outcome is None
    assert r.verdict.claim.kind == "failure" and r.verdict.outcome == Outcome.CORRECT_FAILURE_REPORTED


def test_refusal_and_fallback_notes(store, refund_task):
    _register("fake_refusal", FakeAnthropic([], stop_reason="refusal"))
    r = run_scenario(find_scenario("normal_refund"), harness="fake_refusal", store=store)
    assert r.output.exit_reason == "gave_up" and "declined (cyber)" in r.output.final_message

    _register("fake_fallback", FakeAnthropic(REFUND_PLAN, served_by="claude-opus-4-8"))
    r = run_scenario(find_scenario("normal_refund"), harness="fake_fallback", store=store)
    assert "served by fallback model claude-opus-4-8" in r.output.final_message


def test_no_fallbacks_for_models_without_the_default_form():
    client = FakeAnthropic([])
    p = AnthropicProvider(model="claude-haiku-5-5", client=client)
    p.start("s", "t", [])
    p.next()
    assert "fallbacks" not in client.requests[0] and "betas" not in client.requests[0]


def test_budgets_and_crashes(store):
    _register("fake_budget", FakeAnthropic(REFUND_PLAN))
    s = find_scenario("normal_refund").model_copy(update={"budget": find_scenario("normal_refund").budget.model_copy(
        update={"max_tokens": 1500})})
    r = run_scenario(s, harness="fake_budget", store=store)
    assert r.output.exit_reason == "budget_exceeded" and "token budget" in r.output.final_message

    class Boom(FakeAnthropic):
        def _create(self, **kwargs):
            raise ConnectionError("network down")

    _register("fake_crash", Boom([]))
    r = run_scenario(find_scenario("normal_refund"), harness="fake_crash", store=store)
    assert r.output.exit_reason == "crashed" and "network down" in r.output.final_message
    assert r.verdict.claim.kind == "none"


def test_unknown_model_cost():
    assert cost_usd(Turn(text="", tool_calls=[], stop_reason="", model="mystery", input_tokens=10)) == (0.0, False)


# -- fake OpenAI client ---------------------------------------------------------------------


class FakeOpenAI:
    def __init__(self, plan):
        self.plan = list(plan)
        self.requests = []
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(json.loads(json.dumps(kwargs, default=str)))
        n = len(self.requests)
        usage = NS(prompt_tokens=800, completion_tokens=50, prompt_tokens_details=NS(cached_tokens=300))
        if not self.plan:
            msg = NS(content="Done.", tool_calls=None, refusal=None)
            return NS(choices=[NS(message=msg, finish_reason="stop")], usage=usage, model="test-model")
        calls = [NS(id=f"c{n}_{i}", function=NS(name=name, arguments=args if isinstance(args, str) else json.dumps(args)))
                 for i, (name, args) in enumerate(self.plan.pop(0))]
        msg = NS(content=None, tool_calls=calls, refusal=None)
        return NS(choices=[NS(message=msg, finish_reason="tool_calls")], usage=usage, model="test-model")


def test_native_openai(store):
    plan = [[("get_order", "{not json")]] + REFUND_PLAN
    client = FakeOpenAI(plan)
    register("fake_openai", lambda *a, **k: NativeHarness(
        "openai", provider_factory=lambda name, model=None, **kw: OpenAIProvider(model=model, client=client)))
    r = run_scenario(find_scenario("normal_refund"), harness="fake_openai", store=store, model="test-model")
    assert r.verdict.outcome == Outcome.CORRECT_SUCCESS, r.verdict.summary
    tool_msgs = [m for m in client.requests[1]["messages"] if m["role"] == "tool"]
    assert json.loads(tool_msgs[0]["content"])["error"]["code"] == "INVALID_JSON"
    assert r.output.usage.cost_usd == 0 and "cost unknown" in r.output.final_message
    assert r.output.usage.input_tokens == 800 * 6  # cached tokens are counted once, not twice
    with pytest.raises(ValueError, match="--model"):
        OpenAIProvider(model=None, client=client)


# -- LangGraph -----------------------------------------------------------------------------------


def test_langgraph_harness(store):
    pytest.importorskip("langgraph")
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage

    from agentguard.harnesses.llm.langgraph_harness import LangGraphHarness

    class ToolCallingFake(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    def model_factory(provider, model):
        msgs = [AIMessage(content="", tool_calls=[{"name": n, "args": a, "id": f"lg{i}_{j}"} for j, (n, a) in enumerate(turn)],
                          usage_metadata={"input_tokens": 100, "output_tokens": 10, "total_tokens": 110})
                for i, turn in enumerate(REFUND_PLAN)]
        return ToolCallingFake(messages=iter(msgs))

    register("fake_langgraph", lambda *a, **k: LangGraphHarness("anthropic", model_factory=model_factory))
    r = run_scenario(find_scenario("normal_refund"), harness="fake_langgraph", store=store, model="claude-opus-5-5")
    assert r.verdict.outcome == Outcome.CORRECT_SUCCESS, r.verdict.summary
    assert r.record.config["harness_type"] == "FRAMEWORK"
    assert r.output.usage.tool_calls == 6 and r.output.usage.input_tokens == 500
    assert r.output.usage.cost_usd > 0


def test_registry_has_llm_harnesses():
    from agentguard.harnesses.base import available, make_harness

    assert {"native", "langgraph"} <= set(available())
    assert make_harness("native:openai").name == "native:openai"
    assert make_harness("langgraph:anthropic").harness_type.value == "FRAMEWORK"
