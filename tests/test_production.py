"""Production mode: HTTP backend, runtime sessions, post-action verification, cross-process
approvals, promotion of incidents to draft scenarios, and `agentguard protect` over MCP."""

import json
import os
import sys
import threading
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from agentguard.backends.http import HttpBackendConfig, HttpToolBackend  # noqa: E402
from agentguard.core.models import ApprovalStatus, TraceKind  # noqa: E402
from agentguard.gym.regression import promote  # noqa: E402
from agentguard.gym.scenario import Scenario  # noqa: E402
from agentguard.runtime import RuntimeSession  # noqa: E402
from agentguard.shield.approvals import ApprovalQueue, AutoApprover, resolve_in_store  # noqa: E402
from examples.payments_service import create_app  # noqa: E402

CONFIG = HttpBackendConfig.load("examples/payments_backend.yaml")
REFUND = {"order_id": "O-9002", "amount_inr": 1000, "idempotency_key": "k-1"}


def _backend(fault=None):
    return HttpToolBackend(CONFIG, client=TestClient(create_app(fault=fault), base_url="http://test"))


def _session(store, backend, approve="approve"):
    return RuntimeSession(backend, store, agent_id="support_agent", client="test",
                          backend_config=CONFIG.model_dump(mode="json"),
                          approvals=ApprovalQueue(store, auto=AutoApprover(default=approve), timeout_s=5))


def test_http_backend_maps_tools_queries_and_errors():
    b = _backend()
    assert [t.name for t in b.tools()] == ["get_customer", "get_order", "issue_refund", "update_ticket", "send_email"]
    assert b.execute("get_order", {"order_id": "O-9001"})["amount_inr"] == 5000
    r = b.execute("issue_refund", {"order_id": "O-9001", "amount_inr": 5000, "idempotency_key": "x"})
    assert r["status"] == "SUCCESS"
    assert b.execute("update_ticket", {"ticket_id": "T-77", "status": "resolved", "notes": "n"})["status"] == "resolved"

    from agentguard.world.base import ToolExecutionError

    with pytest.raises(ToolExecutionError) as e:
        b.execute("get_order", {"order_id": "nope"})
    assert e.value.code == "NOT_FOUND"
    with pytest.raises(ToolExecutionError) as e:
        b.execute("issue_refund", {"order_id": "O-9001", "amount_inr": 1, "idempotency_key": "y"})
    assert e.value.code == "AMOUNT_EXCEEDS_REFUNDABLE"  # the service's own code is passed through

    q = b.rule_queries()
    assert q["ledger"]["refund_key_exists"]("x") is True and q["ledger"]["refund_key_exists"]("zzz") is False
    assert q["ledger"]["successful_refunds"]("O-9001", 5000) == 1
    assert q["crm"]["order_customer"]("nope") is None and q["crm"]["customer_verified"]("C-3001") is False
    with pytest.raises(ValueError):
        HttpToolBackend(CONFIG.model_copy(update={"routes": {"fly": CONFIG.routes["get_order"]}}), client=object())


def test_runtime_session_enforces_policy_and_verifies(store):
    s = _session(store, _backend())
    ep = s.endpoint
    # policy rules evaluated against the real service's data
    s.endpoint.call("get_customer", {"customer_id": "C-3001"})
    s.endpoint.call("get_order", {"order_id": "O-9003"})
    blocked = ep.call("issue_refund", {"order_id": "O-9003", "amount_inr": 100, "idempotency_key": "u"})
    assert blocked.error.code == "BLOCKED" and "not verified" in blocked.error.message
    assert ep.call("read_secret", {"name": "x"}).error.code == "BLOCKED"  # not even routed

    ep.call("get_customer", {"customer_id": "C-2001"})
    ep.call("get_order", {"order_id": "O-9002"})
    ok = ep.call("issue_refund", REFUND)
    assert ok.ok
    rec = s.close()
    assert rec.verdict is None and rec.final_snapshot is None and rec.config["mode"] == "runtime"
    trace = store.get_trace(rec.id)
    checks = [e.payload for e in trace if e.kind == TraceKind.VERIFICATION]
    assert [c["passed"] for c in checks] == [True]
    assert store.verify_audit(rec.id).ok


def test_false_success_is_caught_at_runtime_and_promoted(store, tmp_path):
    s = _session(store, _backend(fault="false_success_once"))
    ep = s.endpoint
    ep.call("get_customer", {"customer_id": "C-2001"})
    ep.call("get_order", {"order_id": "O-9002"})
    lie = ep.call("issue_refund", REFUND)
    assert not lie.ok and lie.error.code == "VERIFICATION_FAILED"  # the agent never sees the false success
    real = ep.call("issue_refund", REFUND)  # an honest retry with the same key books it
    assert real.ok and real.output["refund_id"].startswith("LED-")
    ep.call("query_database", {"sql": "SELECT * FROM customers"})  # blocked: not routed
    rec = s.close()

    p = promote(rec.id, store, out_dir=tmp_path)
    assert not p.accepted and p.path.parent == tmp_path and "draft" in p.reason
    text = p.path.read_text()
    assert text.startswith("# DRAFT")
    draft = Scenario.load(p.path)
    assert draft.world == "support" and draft.agent_role == "support_agent"
    assert [(f.tool, f.type.value, f.on_call) for f in draft.faults] == [("issue_refund", "false_success", 1)]
    assert [f.tool_called for f in draft.expected.forbidden] == ["query_database"]
    assert "production" in draft.tags and f"source_run:{rec.id}" in draft.tags


def test_cross_process_approval(store):
    s = _session(store, _backend(), approve="manual")
    s.endpoint.call("get_customer", {"customer_id": "C-2001"})
    s.endpoint.call("get_order", {"order_id": "O-9002"})
    result = {}
    t = threading.Thread(target=lambda: result.setdefault("r", s.endpoint.call(
        "issue_refund", {**REFUND, "amount_inr": 3000})))  # above the approval threshold
    t.start()
    deadline = time.monotonic() + 5
    while not (pending := store.list_approvals(status=ApprovalStatus.PENDING)) and time.monotonic() < deadline:
        time.sleep(0.05)
    # "another process" (e.g. the dashboard) decides through the store only
    resolve_in_store(store, pending[0].id, True, by="human:other-process")
    t.join(timeout=5)
    assert result["r"].ok
    with pytest.raises(ValueError):
        resolve_in_store(store, pending[0].id, False, by="late")
    s.close()


def test_agentguard_protect_over_mcp(tmp_path):
    """The real CLI: `agentguard protect` in front of a live service, driven by an MCP client."""
    import anyio
    import uvicorn
    from mcp import Client, StdioServerParameters

    from agentguard.core.store import Store
    from agentguard.transports.mcp_proxy import _free_port

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.02)
    cfg = tmp_path / "backend.yaml"
    cfg.write_text(json.dumps({**CONFIG.model_dump(mode="json"), "base_url": f"http://127.0.0.1:{port}"}))
    db = f"sqlite:///{tmp_path / 'ag.db'}"
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "agentguard.cli.main", "protect", "--backend", str(cfg), "--agent-id", "support_agent",
              "--client", "test", "--task", "Refund ₹1,000 on O-9002"],
        env={**os.environ, "AGENTGUARD_DB_URL": db})

    async def go():
        async with Client(params) as client:
            names = {t.name for t in (await client.list_tools()).tools}
            assert "issue_refund" in names and "read_secret" not in names
            await client.call_tool("get_customer", {"customer_id": "C-2001"})
            await client.call_tool("get_order", {"order_id": "O-9002"})
            r = await client.call_tool("issue_refund", REFUND)
            assert not r.is_error, r.content[0].text
            await client.call_tool("submit_result", {"status": "success", "summary": "refunded"})

    try:
        anyio.run(go)
    finally:
        server.should_exit = True
    store = Store(db)
    [run] = store.list_runs()
    assert run.harness == "runtime:test" and run.config["task"]["text"].startswith("Refund")
    assert run.output.claimed_outcome["task_status"] == "success"
    assert store.verify_audit(run.id).ok


def test_headers_expand_from_env(monkeypatch):
    monkeypatch.delenv("PAYMENTS_TOKEN", raising=False)
    b = _backend()
    assert b.headers == {} and b.skipped_headers == ["Authorization"]
    monkeypatch.setenv("PAYMENTS_TOKEN", "s3cret")
    assert _backend().headers == {"Authorization": "Bearer s3cret"}
