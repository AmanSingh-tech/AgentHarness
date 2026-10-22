"""Production-mode ToolBackend: the world's ToolSpecs mapped onto an existing REST service.

    name: payments-prod
    base_url: http://payments.internal:9100
    tools_from: support                 # reuse a world's ToolSpecs (only routed tools are exposed)
    headers: {Authorization: "Bearer ${PAYMENTS_TOKEN}"}   # ${VAR} expands from the environment; unset -> header omitted
    timeout_s: 10
    routes:
      get_order:    {method: GET,  path: "/orders/{order_id}"}
      issue_refund: {method: POST, path: "/refunds"}          # remaining args go in the JSON body
    queries:                            # read-only lookups for policy rules and verify checks
      ledger.refund_key_exists: {path: "/refunds/by-key/{0}", result: exists, missing: false}
    twin:                               # the AgentGym world that stands in for this system in tests
      world: support
      initial_state: fixtures/support_basic.yaml

Path placeholders take the named argument; for queries, positional ones ({0}, {1}).
HTTP errors become agent-visible ToolErrors: 404 NOT_FOUND, 409/422 the service's
`code` (or INVALID_ARGS), 429 RATE_LIMITED, 5xx SERVER_ERROR, timeouts TIMEOUT.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Callable

import yaml
from pydantic import BaseModel, ConfigDict, Field

from agentguard.core.models import ToolSpec
from agentguard.world.base import ToolBackend, ToolExecutionError

_ENV = re.compile(r"\$\{(\w+)\}")
_MISSING = object()


class Route(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: str = "GET"
    path: str


class Query(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: str = "GET"
    path: str
    params: dict[str, str] = Field(default_factory=dict)
    result: str | None = None  # dotted key into the JSON response; None = whole body
    missing: Any = None  # value when the service answers 404


class Twin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    world: str
    initial_state: str | None = None


class HttpBackendConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    base_url: str
    tools_from: str = "support"
    headers: dict[str, str] = Field(default_factory=dict)
    timeout_s: float = 10.0
    routes: dict[str, Route]
    queries: dict[str, Query] = Field(default_factory=dict)
    twin: Twin | None = None

    @classmethod
    def load(cls, path: str | Path) -> "HttpBackendConfig":
        return cls.model_validate(yaml.safe_load(Path(path).read_text()))


class HttpToolBackend(ToolBackend):
    def __init__(self, config: HttpBackendConfig, client: Any = None) -> None:
        from agentguard.world import WORLDS

        self.config = config
        self.name = config.name
        specs = {s.name: s for s in WORLDS[config.tools_from]().tools()}
        unknown = sorted(set(config.routes) - set(specs))
        if unknown:
            raise ValueError(f"routes for unknown tools {unknown} (known: {sorted(specs)})")
        self._specs = [specs[name] for name in config.routes]
        if client is None:
            import httpx

            client = httpx.Client(base_url=config.base_url, timeout=config.timeout_s)
        self.client = client
        # A header whose ${VAR} is unset is left out rather than sent half-filled.
        self.headers = {k: v for k, raw in config.headers.items() if (v := _expand(raw)) is not None}
        self.skipped_headers = sorted(set(config.headers) - set(self.headers))

    def tools(self) -> list[ToolSpec]:
        return list(self._specs)

    def execute(self, tool: str, args: dict[str, Any]) -> Any:
        route = self.config.routes.get(tool)
        if route is None:
            raise ToolExecutionError("UNKNOWN_TOOL", f"No tool named '{tool}'")
        path, used = _fill(route.path, args)
        rest = {k: v for k, v in args.items() if k not in used}
        method = route.method.upper()
        kwargs: dict[str, Any] = {"headers": self.headers}
        if method in ("GET", "DELETE"):
            kwargs["params"] = rest
        else:
            kwargs["json"] = rest
        return _decode(self._send(method, path, **kwargs))

    def rule_queries(self) -> dict[str, dict[str, Callable[..., Any]]]:
        out: dict[str, dict[str, Callable[..., Any]]] = {}
        for dotted, q in self.config.queries.items():
            ns, _, fn = dotted.partition(".")
            out.setdefault(ns, {})[fn] = self._query_fn(q)
        return out

    def _query_fn(self, q: Query) -> Callable[..., Any]:
        def call(*args: Any) -> Any:
            path = q.path.format(*args)
            params = {k: v.format(*args) for k, v in q.params.items()}
            resp = self._send(q.method.upper(), path, params=params, headers=self.headers, raise_404=False)
            if resp.status_code == 404:
                return q.missing
            body = _decode(resp)
            if q.result is None:
                return body
            for part in q.result.split("."):
                body = body.get(part, _MISSING) if isinstance(body, dict) else _MISSING
                if body is _MISSING:
                    raise ToolExecutionError("BAD_RESPONSE", f"query result has no '{q.result}'")
            return body

        return call

    def _send(self, method: str, path: str, raise_404: bool = True, **kwargs: Any) -> Any:
        import httpx

        try:
            resp = self.client.request(method, path, **kwargs)
        except httpx.TimeoutException:
            raise ToolExecutionError("TIMEOUT", f"{self.name} did not answer in time", retryable=True) from None
        except httpx.TransportError as e:
            raise ToolExecutionError("TOOL_UNAVAILABLE", f"{self.name} is unreachable: {e}", retryable=True) from None
        if resp.status_code < 400 or (resp.status_code == 404 and not raise_404):
            return resp
        body = _safe_json(resp)
        message = (body.get("message") or body.get("detail") or resp.text) if isinstance(body, dict) else resp.text
        if resp.status_code == 404:
            raise ToolExecutionError("NOT_FOUND", str(message))
        if resp.status_code == 429:
            raise ToolExecutionError("RATE_LIMITED", str(message), retryable=True)
        if resp.status_code >= 500:
            raise ToolExecutionError("SERVER_ERROR", f"{self.name} returned {resp.status_code}", retryable=True)
        code = body.get("code") if isinstance(body, dict) and isinstance(body.get("code"), str) else "INVALID_ARGS"
        raise ToolExecutionError(code, str(message))


def _fill(template: str, args: dict[str, Any]) -> tuple[str, set[str]]:
    used: set[str] = set()

    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key not in args:
            raise ToolExecutionError("INVALID_ARGS", f"missing argument '{key}'")
        used.add(key)
        return str(args[key])

    return re.sub(r"\{(\w+)\}", sub, template), used


def _expand(value: str) -> str | None:
    """Expand ${VAR}s from the environment; None if any of them is unset or empty."""
    names = _ENV.findall(value)
    if any(not os.environ.get(n) for n in names):
        return None
    return _ENV.sub(lambda m: os.environ[m.group(1)], value)


def _safe_json(resp: Any) -> Any:
    try:
        return resp.json()
    except ValueError:
        return None


def _decode(resp: Any) -> Any:
    body = _safe_json(resp)
    if body is None and resp.text:
        raise ToolExecutionError("BAD_RESPONSE", "the service did not return JSON")
    return body
