"""An example agent deployed as a web service, for the remote_http harness.

    uvicorn examples.remote_agent:app --port 9200
    agentguard run --scenario normal_refund --harness remote_http:http://127.0.0.1:9200/run
    agentguard run --scenario normal_refund --harness "remote_http:http://127.0.0.1:9200/run?mode=careless"

It receives a task, calls back the AgentGuard gateway it is given, and reports
the outcome with /submit. `mode=careless` tries a bulk export first.
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import FastAPI

app = FastAPI(title="Example remote agent")


@app.post("/run")
def run(body: dict[str, Any], mode: str = "careful") -> dict[str, Any]:
    gw = body["gateway"]
    p = body["task"].get("params", {})
    client = httpx.Client(base_url=gw["base_url"], headers={"Authorization": f"Bearer {gw['token']}"}, timeout=60)

    def call(tool: str, **args: Any) -> dict[str, Any]:
        return client.post("/call", json={"tool": tool, "args": args}).json()

    def submit(status: str, summary: str) -> dict[str, Any]:
        client.post("/submit", json={"status": status, "summary": summary})
        return {"final_message": summary}

    if mode == "careless":
        call("query_database", sql="SELECT * FROM customers")
    customer = call("get_customer", customer_id=p["customer_id"])
    order = call("get_order", order_id=p["order_id"])
    if not (customer["ok"] and order["ok"] and customer["output"]["verified"]
            and order["output"]["customer_id"] == p["customer_id"]
            and order["output"]["refundable_inr"] >= p["amount_inr"]):
        return submit("refused", "The refund cannot be issued: verification failed.")
    key = f"remote-{p['order_id']}-{p['amount_inr']}"
    refund = call("issue_refund", order_id=p["order_id"], amount_inr=p["amount_inr"], idempotency_key=key)
    check = call("get_order", order_id=p["order_id"])
    if not (check["ok"] and check["output"]["refunded_amount_inr"] > order["output"]["refunded_amount_inr"]):
        return submit("failed", f"The refund did not land ({(refund.get('error') or {}).get('code')}).")
    call("update_ticket", ticket_id=p["ticket_id"], status="resolved", notes=f"Refunded {p['amount_inr']}")
    call("send_email", to=customer["output"]["email"], subject="Your refund", body="Your refund is on its way.")
    return submit("success", f"Refunded {p['amount_inr']} for {p['order_id']}.")
