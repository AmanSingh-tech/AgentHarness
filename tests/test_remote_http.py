"""REMOTE_HTTP harness: a web-service agent calling back the per-run, token-scoped gateway."""

import threading
import time

import httpx
import pytest

pytest.importorskip("fastapi")
import uvicorn  # noqa: E402

from agentguard.core.models import Budget  # noqa: E402
from agentguard.gym.runner import run_scenario  # noqa: E402
from agentguard.gym.scenario import find_scenario  # noqa: E402
from agentguard.gym.verifier import Outcome  # noqa: E402
from agentguard.harnesses.remote_http import RemoteHttpHarness  # noqa: E402
from agentguard.transports.http_proxy import build_http_gateway, serve_app  # noqa: E402
from examples.remote_agent import app as agent_app  # noqa: E402


@pytest.fixture(scope="module")
def agent_url():
    from agentguard.transports.mcp_proxy import _free_port

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(agent_app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}/run"
    server.should_exit = True


def test_remote_agent_completes_refund(store, agent_url):
    r = run_scenario(find_scenario("normal_refund"), harness=f"remote_http:{agent_url}", store=store)
    assert r.verdict.outcome == Outcome.CORRECT_SUCCESS, r.verdict.summary
    assert r.record.config["harness_type"] == "REMOTE_HTTP"
    assert r.output.claimed_outcome["task_status"] == "success" and r.output.usage.tool_calls == 6


def test_remote_agent_refuses_and_shield_blocks(store, agent_url):
    r = run_scenario(find_scenario("unverified_customer_refused"), harness=f"remote_http:{agent_url}", store=store)
    assert r.verdict.outcome == Outcome.CORRECT_FAILURE_REPORTED
    r = run_scenario(find_scenario("normal_refund"), harness=f"remote_http:{agent_url}?mode=careless", store=store)
    # blocked, and the refund still happened, but the attempt itself is reported
    assert r.verdict.outcome == Outcome.POLICY_VIOLATION_ATTEMPTED and r.verdict.state_ok
    blocked = [e for e in store.get_trace(r.run_id) if e.kind.value == "decision" and e.payload["type"] == "BLOCK"]
    assert blocked[0].payload["tool"] == "query_database" and blocked[0].payload["risk"] == "CRITICAL"


def test_gateway_requires_the_run_token(endpoint):
    with serve_app(build_http_gateway(endpoint, "right-token")) as url:
        assert httpx.get(f"{url}/tools").status_code == 401
        assert httpx.get(f"{url}/tools", headers={"Authorization": "Bearer wrong"}).status_code == 401
        ok = httpx.get(f"{url}/tools", headers={"Authorization": "Bearer right-token"}).json()
        assert {"issue_refund", "submit_result"} <= {t["name"] for t in ok["tools"]}
        h = {"Authorization": "Bearer right-token"}
        r = httpx.post(f"{url}/call", json={"tool": "get_order", "args": {"order_id": "nope"}}, headers=h).json()
        assert r == {"ok": False, "error": {"code": "NOT_FOUND", "message": "Order nope not found", "retryable": False}}
        assert httpx.post(f"{url}/submit", json={"status": "maybe"}, headers=h).status_code == 422
        assert httpx.post(f"{url}/call", json={"tool": "submit_result", "args": {}}, headers=h).status_code == 400


def test_unreachable_and_bad_agents(endpoint, refund_task):
    from agentguard.transports.mcp_proxy import _free_port

    out = RemoteHttpHarness(f"http://127.0.0.1:{_free_port()}/run").run(refund_task, endpoint, Budget())
    assert out.exit_reason == "crashed" and "Could not reach" in out.final_message
    with pytest.raises(ValueError):
        RemoteHttpHarness("not-a-url")
