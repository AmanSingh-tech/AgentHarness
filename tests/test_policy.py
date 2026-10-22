import pytest

from agentguard.core.events import EventBus, Tracer
from agentguard.core.models import DecisionType, RiskLevel, ToolCall, TraceKind
from agentguard.shield.gateway import Gateway
from agentguard.shield.pipeline import PolicyStage, Shield, ShieldSession, _domain_allowed
from agentguard.shield.policy import Expr, ExprError, PolicyError, load_policy, parse_policy
from agentguard.world.support.tools import SUPPORT_TOOLS

SPECS = {t.name: t for t in SUPPORT_TOOLS}


def test_default_policy_loads():
    p = load_policy()
    assert {"support_agent", "finance_agent", "ops_agent"} <= set(p.agents)
    assert p.rules[0].id == "no_duplicate_refund"
    with pytest.raises(FileNotFoundError):
        load_policy("no-such-policy")


@pytest.mark.parametrize(
    "text, line, fragment",
    [
        ("agents: [1, 2", 1, "YAML syntax error"),
        ("- just a list", 1, "must be a mapping"),
        ("agents:\n  a:\n    tools:\n      x: {allow: true, bogus: 1}\n", 4, "bogus"),
        ("rules:\n  - id: r\n    when: {tool: t}\n    check: \"__import__('os')\"\n", 4, "unsupported syntax"),
        ("agents:\n  a:\n    tools:\n      x: {deny_patterns: ['(']}\n", 4, "invalid regex"),
        ("sequences:\n  - id: s\n    sources: [NOT_A_LABEL]\n    sinks: [x]\n", 3, "sources"),
        ("rules:\n  - {id: d, when: {tool: t}, check: 'True'}\nsequences:\n  - {id: d, sources: [SECRET], sinks: [x]}\n",
         None, "duplicate"),
    ],
)
def test_policy_errors_point_at_lines(text, line, fragment):
    with pytest.raises(PolicyError) as e:
        parse_policy(text)
    msg = str(e.value)
    assert fragment in msg
    if line is not None:
        assert f"line {line}:" in msg


def test_expr_language():
    q = {"ns": {"double": lambda x: x * 2}}
    assert Expr("ns.double(a) == 4 and not b").evaluate({"a": 2, "b": False}, q) is True
    assert Expr("a in [1, 2] or -a > 0").evaluate({"a": 3}, q) is False
    assert Expr("1 < a <= 3").evaluate({"a": 3}, q) is True
    assert Expr("a + 1 - 1 * 2 / 2").evaluate({"a": 1}, q) == 1
    for bad in ["a.b", "x[0]", "f(1)", "ns.f(k=1)", "lambda: 1", "(", "[i for i in a]"]:
        with pytest.raises(ExprError):
            Expr(bad)
    with pytest.raises(ExprError):
        Expr("missing == 1").evaluate({}, q)
    with pytest.raises(ExprError):
        Expr("ns.nope(1)").evaluate({}, q)


def test_domain_matching():
    assert _domain_allowed("customer-domain.com", ["customer-domain"])
    assert _domain_allowed("mail.company.com", ["company.com"])
    assert not _domain_allowed("company.com.example", ["company.com"])
    assert not _domain_allowed("othercompany.com", ["company.com"])


def _stage(world, agent="support_agent"):
    return PolicyStage(load_policy(), world, ShieldSession()), agent


def _eval(world, tool, args, agent="support_agent"):
    stage, _ = _stage(world)
    return stage.evaluate(ToolCall(run_id="r", agent_id=agent, tool=tool, args=args, seq=1), SPECS[tool])


def test_policy_decisions(world):
    d = _eval(world, "get_order", {"order_id": "O-9001"})
    assert d.type == DecisionType.ALLOW and d.rule_id == "support_agent.get_order.allow"
    d = _eval(world, "get_order", {"order_id": "O-9001"}, agent="stranger")
    assert d.type == DecisionType.BLOCK and d.rule_id == "policy.unknown_agent"
    d = _eval(world, "read_secret", {"name": "x"})
    assert d.type == DecisionType.BLOCK and d.risk == RiskLevel.HIGH
    d = _eval(world, "encode", {"text": "x", "scheme": "hex"}, agent="finance_agent")
    assert d.type == DecisionType.BLOCK and "not listed" in d.reason

    refund = {"order_id": "O-9001", "amount_inr": 1000, "idempotency_key": "k"}
    assert _eval(world, "issue_refund", refund).type == DecisionType.ALLOW
    d = _eval(world, "issue_refund", {**refund, "amount_inr": 3000})
    assert d.type == DecisionType.REQUIRE_APPROVAL and "₹3,000" in d.reason
    d = _eval(world, "issue_refund", {**refund, "amount_inr": 6000})
    assert d.type == DecisionType.BLOCK and d.rule_id.endswith("max_amount_inr")

    d = _eval(world, "send_email", {"to": "someone@elsewhere.example", "subject": "s", "body": "b"})
    assert d.type == DecisionType.BLOCK and "elsewhere.example" in d.reason
    d = _eval(world, "send_email", {"to": "not-an-address", "subject": "s", "body": "b"})
    assert d.type == DecisionType.BLOCK
    d = _eval(world, "query_database", {"sql": "select * from orders"})
    assert d.type == DecisionType.BLOCK and d.risk == RiskLevel.CRITICAL
    d = _eval(world, "query_database", {"sql": "SELECT id FROM orders LIMIT 5000"})
    assert d.type == DecisionType.BLOCK
    d = _eval(world, "query_database", {"sql": "SELECT id FROM orders"})
    assert d.type == DecisionType.ALLOW_WITH_REDACTION


def test_duplicate_refund_rule(world):
    args = {"order_id": "O-9002", "amount_inr": 1000, "idempotency_key": "first"}
    assert _eval(world, "issue_refund", args).type == DecisionType.ALLOW
    world.execute("issue_refund", args)
    # same key: a safe replay
    assert _eval(world, "issue_refund", args).type == DecisionType.ALLOW
    # new key, same amount: a duplicate
    d = _eval(world, "issue_refund", {**args, "idempotency_key": "second"})
    assert d.type == DecisionType.BLOCK and d.rule_id == "no_duplicate_refund"
    assert d.evidence["inputs"]["idempotency_key"] == "second"
    # a different amount on the same order is a separate partial refund
    assert _eval(world, "issue_refund", {**args, "amount_inr": 500, "idempotency_key": "third"}).type == DecisionType.ALLOW


def test_rule_that_cannot_be_evaluated_fails_closed(world):
    policy = parse_policy("""
agents:
  a: {tools: {get_order: {allow: true}}}
rules:
  - {id: needs_missing_arg, when: {tool: get_order}, check: "nonexistent == 1"}
""")
    stage = PolicyStage(policy, world, ShieldSession())
    d = stage.evaluate(ToolCall(run_id="r", agent_id="a", tool="get_order", args={"order_id": "O-9001"}, seq=1),
                       SPECS["get_order"])
    assert d.type == DecisionType.BLOCK and "failing closed" in d.reason


def test_redaction_and_trace(world):
    bus = EventBus()
    events = []
    bus.subscribe(events.append)
    gw = Gateway(world, Tracer(bus, "r"), "support_agent", stages=Shield(load_policy(), world).stages)
    r = gw.call("query_database", {"sql": "SELECT id, name FROM customers"})
    assert r.ok and len(r.output["rows"]) == 10 and r.output["redacted"]["rows_removed"] == 33
    [decision] = [e for e in events if e.kind == TraceKind.DECISION]
    assert decision.payload["type"] == "ALLOW_WITH_REDACTION"
    stages = {v["stage"] for v in decision.payload["evidence"]["votes"]}
    assert {"policy", "risk"} <= stages
    assert decision.payload["risk"] == "HIGH"  # highest vote wins: the tool returns bulk data


def test_broken_stage_fails_closed(world):
    class Broken:
        name = "broken"

        def evaluate(self, call, spec):
            raise RuntimeError("bug")

    gw = Gateway(world, Tracer(EventBus(), "r"), "a", stages=[Broken()])
    r = gw.call("get_order", {"order_id": "O-9001"})
    assert r.error.code == "BLOCKED" and "failing closed" in r.error.message
