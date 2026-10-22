"""An example "existing system" to put behind AgentShield in production mode.

A small REST payments/CRM service. Here it is backed by the support world's data
so it runs anywhere; in a real deployment it would be your own service.

    uvicorn examples.payments_service:app --port 9100
    PAYMENTS_FAULT=false_success_once uvicorn ...   # first refund reports success but is not booked

Then: agentguard protect --backend examples/payments_backend.yaml --agent-id support_agent
"""

from __future__ import annotations

import os
import threading
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from agentguard.world.base import ToolExecutionError
from agentguard.world.support.world import SupportWorld


class Refund(BaseModel):
    order_id: str
    amount_inr: int
    idempotency_key: str


class TicketUpdate(BaseModel):
    status: str
    notes: str | None = None


class Email(BaseModel):
    to: str
    subject: str
    body: str


def create_app(seed: int = 42, fault: str | None = None) -> FastAPI:
    world = SupportWorld()
    world.reset(seed)
    state = {"fault": fault if fault is not None else os.environ.get("PAYMENTS_FAULT", "")}
    lock = threading.Lock()
    app = FastAPI(title="Example payments service")
    app.state.world = world

    def call(tool: str, args: dict[str, Any]) -> Any:
        try:
            return world.execute(tool, args)
        except ToolExecutionError as e:
            status = 404 if e.code == "NOT_FOUND" else 409
            raise HTTPException(status, detail={"code": e.code, "message": e.message}) from None

    @app.exception_handler(HTTPException)
    async def _errors(request, exc: HTTPException):  # flatten {"detail": {...}} to {"code", "message"}
        body = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
        return JSONResponse(body, status_code=exc.status_code)

    @app.get("/customers/{customer_id}")
    def customer(customer_id: str):
        return call("get_customer", {"customer_id": customer_id})

    @app.get("/orders/{order_id}")
    def order(order_id: str):
        return call("get_order", {"order_id": order_id})

    @app.post("/refunds")
    def refund(r: Refund):
        with lock:
            if state["fault"] == "false_success_once":
                state["fault"] = ""
                return {"refund_id": "LED-PENDING", "status": "SUCCESS", **r.model_dump()}
        return call("issue_refund", r.model_dump())

    @app.patch("/tickets/{ticket_id}")
    def ticket(ticket_id: str, t: TicketUpdate):
        return call("update_ticket", {"ticket_id": ticket_id, **t.model_dump(exclude_none=True)})

    @app.post("/emails")
    def email(e: Email):
        return call("send_email", e.model_dump())

    @app.get("/refunds/by-key/{key}")
    def refund_by_key(key: str):
        return {"exists": world.refund_key_exists(key)}

    @app.get("/orders/{order_id}/refunds")
    def order_refunds(order_id: str, amount_inr: int | None = None):
        return {"count": world.successful_refunds(order_id, amount_inr)}

    return app


app = create_app()
