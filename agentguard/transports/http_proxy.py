"""HTTP transport: the run's tools as a small REST gateway for agents deployed as services.

    GET  /tools               -> {"tools": [{name, description, input_schema, side_effect}, ...]}
    POST /call   {tool, args} -> {"ok": true, "output": ...} | {"ok": false, "error": {...}}
    POST /tools/<name>  {args} -> the same, REST style (handy for curl in shell agents)
    POST /submit {status, summary}  -> the agent's structured claim

Every request needs `Authorization: Bearer <token>`; the token is minted per run,
so an agent can only act within the run it was given. Calls go through the
Gateway (and AgentShield) exactly as in-process calls do.
"""

from __future__ import annotations

import contextlib
import hmac
import secrets
import threading
import time
from typing import Any, Callable, Iterator

from pydantic import BaseModel

from agentguard.harnesses.llm.native import _EXIT, SUBMIT, _render
from agentguard.transports.inprocess import InProcessEndpoint


# Request bodies live at module level: FastAPI cannot resolve postponed annotations
# of classes defined inside the factory function.
class Call(BaseModel):
    tool: str
    args: dict[str, Any] = {}


class Submit(BaseModel):
    status: str
    summary: str = ""


def build_http_gateway(endpoint: InProcessEndpoint, token: str,
                       on_submit: Callable[[dict[str, Any]], None] | None = None) -> Any:
    from fastapi import Depends, FastAPI, Header, HTTPException
    from fastapi.concurrency import run_in_threadpool
    from fastapi.responses import Response

    def auth(authorization: str | None = Header(default=None)) -> None:
        given = (authorization or "").removeprefix("Bearer ").strip()
        if not hmac.compare_digest(given, token):
            raise HTTPException(401, "missing or invalid run token")

    app = FastAPI(title="AgentGuard tool gateway", dependencies=[Depends(auth)])

    @app.get("/tools")
    def tools() -> dict[str, Any]:
        return {"tools": [{"name": s.name, "description": s.description, "input_schema": s.input_schema,
                           "side_effect": s.side_effect.value} for s in endpoint.specs() + [SUBMIT]]}

    @app.post("/call")
    async def call(body: Call) -> Response:
        if body.tool == SUBMIT.name:
            raise HTTPException(400, "use POST /submit to report the outcome")
        # the gateway may block on an approval: keep the event loop free
        result = await run_in_threadpool(endpoint.call, body.tool, body.args)
        return Response(_render(result), media_type="application/json")

    @app.post("/tools/{tool}")
    async def call_rest(tool: str, args: dict[str, Any] | None = None) -> Response:
        """REST style for shell agents: curl -X POST $GW/tools/get_order -d '{"order_id": "O-1"}'"""
        return await call(Call(tool=tool, args=args or {}))

    @app.post("/submit")
    def submit(body: Submit) -> dict[str, Any]:
        if body.status not in _EXIT:
            raise HTTPException(422, "status must be success, failed or refused")
        if on_submit is not None:
            on_submit(body.model_dump())
        return {"ok": True, "output": "recorded"}

    return app


def new_token() -> str:
    return secrets.token_urlsafe(24)


@contextlib.contextmanager
def serve_app(app: Any, host: str = "127.0.0.1") -> Iterator[str]:
    """Serve an ASGI app on a free localhost port in a background thread; yields its base URL."""
    import uvicorn

    from agentguard.transports.mcp_proxy import _free_port

    port = _free_port(host)
    httpd = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning", lifespan="on"))
    thread = threading.Thread(target=httpd.run, name="agentguard-http-gateway", daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not httpd.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError("HTTP gateway failed to start")
        time.sleep(0.02)
    try:
        yield f"http://{host}:{port}"
    finally:
        httpd.should_exit = True
        thread.join(timeout=10)
