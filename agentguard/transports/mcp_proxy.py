"""MCP transport: the world's tools as an MCP server, every call through the Gateway.

Two ways to use it:

- `agentguard mcp-serve --scenario <id>` (stdio): any MCP client (Claude Code, Cursor,
  an IDE agent) connects; the run starts when the server starts and is verified
  when the client disconnects. Nothing but MCP JSON-RPC is written to stdout.
- `serve_http(...)` (localhost streamable HTTP): used by the mcp_client harness so
  the run, the gateway and the verifier stay in the runner's process.

Besides the world's tools the server offers `submit_result(status, summary)`, the
same structured claim the LLM harnesses use. The agent never sees the verdict.
"""

from __future__ import annotations

import contextlib
import json
import socket
import sys
import threading
import time
from typing import Any, Callable, Iterator

import anyio
import mcp.types as types
from mcp.server.lowlevel import Server

from agentguard.core.models import AgentOutput, HarnessCapabilities, HarnessType, RunStatus, Usage
from agentguard.harnesses.llm.native import _EXIT, SUBMIT, _render
from agentguard.transports.inprocess import InProcessEndpoint

SERVER_NAME = "agentguard"
MCP_CAPABILITIES = HarnessCapabilities(supports_mcp=True, supports_structured_claim=True)


def build_server(endpoint: InProcessEndpoint, on_submit: Callable[[dict[str, Any]], None] | None = None,
                 name: str = SERVER_NAME) -> Server:
    """An MCP server exposing the endpoint's tools (generated from their ToolSpecs) plus submit_result."""
    specs = endpoint.specs() + [SUBMIT]

    async def list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[
            types.Tool(name=s.name, description=s.description, input_schema=s.input_schema) for s in specs
        ])

    async def call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        args = dict(params.arguments or {})
        if params.name == SUBMIT.name:
            if args.get("status") not in _EXIT:
                return _text({"ok": False, "error": {"code": "INVALID_ARGS",
                                                     "message": "status must be success, failed or refused"}}, True)
            if on_submit is not None:
                on_submit(args)
            return _text({"ok": True, "output": "recorded"}, False)
        # The gateway may block (e.g. waiting for a human approval): keep the event loop free.
        result = await anyio.to_thread.run_sync(endpoint.call, params.name, args)
        return types.CallToolResult(content=[types.TextContent(type="text", text=_render(result))],
                                    is_error=not result.ok)

    return Server(name, on_list_tools=list_tools, on_call_tool=call_tool)


def _text(payload: dict[str, Any], is_error: bool) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(payload))], is_error=is_error)


def output_from_submission(submitted: dict[str, Any], fallback_message: str, usage: Usage) -> AgentOutput:
    status = submitted.get("status")
    if status in _EXIT:
        summary = str(submitted.get("summary", ""))
        return AgentOutput(final_message=summary or fallback_message,
                           claimed_outcome={"task_status": status, "summary": summary},
                           exit_reason=_EXIT[status], usage=usage)
    return AgentOutput(final_message=fallback_message, exit_reason="completed", usage=usage)


# ---------------------------------------------------------------------------
# Localhost streamable HTTP (used by harnesses/mcp_client.py)
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def serve_http(server: Server, host: str = "127.0.0.1") -> Iterator[str]:
    """Serve on a free localhost port in a background thread; yields the MCP URL."""
    import uvicorn

    port = _free_port(host)
    app = server.streamable_http_app(host=host)
    config = uvicorn.Config(app, host=host, port=port, log_level="warning", lifespan="on")
    httpd = uvicorn.Server(config)
    thread = threading.Thread(target=httpd.run, name="agentguard-mcp-http", daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not httpd.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError("MCP HTTP server failed to start")
        time.sleep(0.02)
    try:
        yield f"http://{host}:{port}/mcp"
    finally:
        httpd.should_exit = True
        thread.join(timeout=10)


def _free_port(host: str = "127.0.0.1") -> int:
    with socket.socket() as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]


# ---------------------------------------------------------------------------
# stdio: one scenario run per server process
# ---------------------------------------------------------------------------


def serve_scenario_stdio(scenario: Any, store: Any, *, shield: bool = True, client: str = "external",
                         run_set: str | None = None, model: str | None = None) -> Any:
    """Run `scenario` with an external MCP client as the agent, over stdio. Returns the verified RunResult."""
    from agentguard.gym.runner import prepare_run, scenario_run_kwargs, verify_run

    run = prepare_run(harness=f"mcp:{client}", harness_type=HarnessType.MCP_CLIENT, capabilities=MCP_CAPABILITIES,
                      store=store, model=model, **scenario_run_kwargs(scenario, shield, run_set))
    submitted: dict[str, Any] = {}
    started = time.monotonic()
    run.start()
    server = build_server(run.endpoint, on_submit=submitted.update)

    async def main() -> None:
        from mcp.server.stdio import stdio_server

        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    status = RunStatus.FINISHED
    try:
        anyio.run(main)
    except Exception as e:  # pragma: no cover - transport failure
        status = RunStatus.CRASHED
        print(f"agentguard: MCP server error: {e}", file=sys.stderr)
    usage = Usage(wall_time_s=round(time.monotonic() - started, 3), tool_calls=run.gateway.call_count)
    output = output_from_submission(submitted, "MCP client disconnected without calling submit_result.", usage)
    result = verify_run(scenario, run.finish(output, status), store)
    print(f"agentguard: run {result.run_id} {result.verdict.outcome.value}: {result.verdict.summary}", file=sys.stderr)
    return result
