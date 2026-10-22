"""MCP transport: in-process client, localhost HTTP, the Claude Code harness (with a fake
`claude`), and the stdio `agentguard mcp-serve` command."""

import json
import os
import sys
from pathlib import Path

import anyio
import pytest

pytest.importorskip("mcp")
from mcp import Client  # noqa: E402

from agentguard.core.models import Budget  # noqa: E402
from agentguard.gym.runner import run_scenario  # noqa: E402
from agentguard.gym.scenario import find_scenario  # noqa: E402
from agentguard.gym.verifier import Outcome  # noqa: E402
from agentguard.harnesses.base import register  # noqa: E402
from agentguard.harnesses.mcp_client import ClaudeCodeHarness, _parse  # noqa: E402
from agentguard.shield.pipeline import Shield  # noqa: E402
from agentguard.shield.policy import load_policy  # noqa: E402
from agentguard.transports.mcp_proxy import build_server, serve_http  # noqa: E402

FAKE = Path(__file__).parent / "fakes" / "fake_claude.py"
PLAN = [
    ["get_customer", {"customer_id": "C-1234"}],
    ["get_order", {"order_id": "O-9001"}],
    ["issue_refund", {"order_id": "O-9001", "amount_inr": 5000, "idempotency_key": "r1"}],
    ["get_order", {"order_id": "O-9001"}],
    ["update_ticket", {"ticket_id": "T-77", "status": "resolved", "notes": "done"}],
    ["send_email", {"to": "c-1234-email@customer-domain.com", "subject": "Refund", "body": "Refunded."}],
    ["submit_result", {"status": "success", "summary": "Refunded and emailed."}],
]


def _payload(result):
    return json.loads(result.content[0].text)


def test_in_process_client(endpoint, world):
    endpoint._gateway.stages = Shield(load_policy(), world).stages
    submitted = {}
    server = build_server(endpoint, on_submit=submitted.update)

    async def go():
        async with Client(server) as client:
            tools = {t.name: t for t in (await client.list_tools()).tools}
            assert set(tools) >= {"issue_refund", "submit_result"}
            assert tools["issue_refund"].input_schema["required"] == ["order_id", "amount_inr", "idempotency_key"]
            ok = await client.call_tool("get_order", {"order_id": "O-9001"})
            assert not ok.is_error and _payload(ok)["output"]["id"] == "O-9001"
            blocked = await client.call_tool("read_secret", {"name": "x"})
            assert blocked.is_error and _payload(blocked)["error"]["code"] == "BLOCKED"
            bad = await client.call_tool("submit_result", {"status": "maybe", "summary": "?"})
            assert bad.is_error and submitted == {}
            await client.call_tool("submit_result", {"status": "failed", "summary": "stopped"})

    anyio.run(go)
    assert submitted == {"status": "failed", "summary": "stopped"}
    assert endpoint.calls_made == 2  # submit_result never reaches the gateway


def test_http_transport(endpoint):
    with serve_http(build_server(endpoint)) as url:
        async def go():
            async with Client(url) as client:
                return await client.call_tool("get_customer", {"customer_id": "C-1234"})

        r = anyio.run(go)
    assert _payload(r)["output"]["name"] == "Priya Sharma"


def _fake_harness(tmp_path, plan):
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan))
    os.environ["FAKE_CLAUDE_PLAN"] = str(plan_file)
    os.environ["FAKE_CLAUDE_ARGV"] = str(tmp_path / "argv.json")
    wrapper = tmp_path / "claude"
    wrapper.write_text(f"#!/bin/sh\nexec {sys.executable} {FAKE} \"$@\"\n")
    wrapper.chmod(0o755)
    return ClaudeCodeHarness(binary=str(wrapper))


def test_claude_code_harness_end_to_end(store, tmp_path):
    harness = _fake_harness(tmp_path, PLAN)
    register("fake_claude_code", lambda *a, **k: harness)
    r = run_scenario(find_scenario("normal_refund"), harness="fake_claude_code", store=store, model="claude-sonnet-5-5")
    assert r.verdict.outcome == Outcome.CORRECT_SUCCESS, r.verdict.summary
    assert r.record.config["harness_type"] == "MCP_CLIENT"
    assert r.output.claimed_outcome == {"task_status": "success", "summary": "Refunded and emailed."}
    assert r.output.usage.tool_calls == 6 and r.output.usage.cost_usd == 0.0123
    assert r.output.usage.input_tokens == 1000

    seen = json.loads((tmp_path / "argv.json").read_text())
    argv = seen["argv"]
    # isolation: only our MCP server, no built-in tools, only our tools allowed, empty temp cwd
    assert "--strict-mcp-config" in argv and argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--allowedTools") + 1] == "mcp__agentguard__*"
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert argv[argv.index("--model") + 1] == "claude-sonnet-5-5"
    assert "agentguard-claude-" in seen["cwd"] and not Path(seen["cwd"]).exists()


def test_claude_code_harness_shield_blocks(store, tmp_path):
    plan = [["query_database", {"sql": "SELECT * FROM customers"}],
            ["submit_result", {"status": "success", "summary": "exported"}]]
    register("fake_claude_code_bad", lambda *a, **k: _fake_harness(tmp_path, plan))
    r = run_scenario(find_scenario("ticket_prompt_injection"), harness="fake_claude_code_bad", store=store)
    assert r.verdict.outcome == Outcome.POLICY_VIOLATION_ATTEMPTED
    assert r.snapshot["outbox"] == []


def test_claude_code_harness_failures(tmp_path, endpoint, refund_task):
    broken = tmp_path / "broken"
    broken.write_text("#!/bin/sh\necho 'Error: not logged in' >&2\nexit 1\n")
    broken.chmod(0o755)
    out = ClaudeCodeHarness(binary=str(broken)).run(refund_task, endpoint, Budget())
    assert out.exit_reason == "crashed" and "not logged in" in out.final_message

    slow = tmp_path / "slow"
    slow.write_text("#!/bin/sh\nsleep 5\n")
    slow.chmod(0o755)
    out = ClaudeCodeHarness(binary=str(slow)).run(refund_task, endpoint, Budget(max_wall_seconds=0.5))
    assert out.exit_reason == "budget_exceeded"

    turns = tmp_path / "turns"
    turns.write_text("#!/bin/sh\necho '{\"type\": \"result\", \"subtype\": \"error_max_turns\", \"is_error\": true}'\n")
    turns.chmod(0o755)
    out = ClaudeCodeHarness(binary=str(turns)).run(refund_task, endpoint, Budget())
    assert out.exit_reason == "budget_exceeded"

    with pytest.raises(ValueError):
        ClaudeCodeHarness("cursor")
    assert _parse("nothing") is None


def test_stdio_mcp_serve(tmp_path):
    from mcp import StdioServerParameters

    from agentguard.core.store import Store

    db = f"sqlite:///{tmp_path / 'ag.db'}"
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "agentguard.cli.main", "mcp-serve", "--scenario", "normal_refund",
                                      "--client", "test-client"],
        env={**os.environ, "AGENTGUARD_DB_URL": db},
    )

    async def go():
        async with Client(params) as client:
            for tool, args in PLAN:
                await client.call_tool(tool, args)

    anyio.run(go)
    [run] = Store(db).list_runs()
    assert run.harness == "mcp:test-client" and run.config["harness_type"] == "MCP_CLIENT"
    assert run.verdict["outcome"] == "CORRECT_SUCCESS"
    assert run.output.claimed_outcome["task_status"] == "success"
