"""Protect your own tools with AgentShield: a ToolBackend, a short YAML policy, and a RuntimeSession.

    python examples/protect_your_tools.py

Any agent that calls tools through `session.endpoint` (or through MCP / HTTP, see the README) gets the same
treatment: permissions and limits from the policy, human approval above a threshold, a plain-English reason
for every block, and a hash-chained audit log of everything that happened.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from agentguard.core.models import AgentOutput, SideEffect, ToolSpec
from agentguard.core.store import Store
from agentguard.runtime import RuntimeSession
from agentguard.shield.approvals import ApprovalQueue, AutoApprover
from agentguard.world.base import ToolBackend, ToolExecutionError

# 1. Your tools: any Python functions (or calls to your own services).
INVOICES = {"INV-7": {"vendor": "Acme Supplies", "amount_inr": 4_000}, "INV-8": {"vendor": "Nimbus Cloud", "amount_inr": 25_000}}


def _schema(**props: str) -> dict[str, Any]:
    return {"type": "object", "properties": {k: {"type": t} for k, t in props.items()},
            "required": list(props), "additionalProperties": False}


class InvoiceTools(ToolBackend):
    name = "invoices"

    def tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(name="lookup_invoice", description="Read an invoice.", input_schema=_schema(invoice_id="string"),
                     side_effect=SideEffect.READ),
            ToolSpec(name="pay_invoice", description="Pay an invoice.",
                     input_schema=_schema(invoice_id="string", amount_inr="integer"),
                     side_effect=SideEffect.WRITE, irreversible=True),
            ToolSpec(name="delete_vendor", description="Delete a vendor record.", input_schema=_schema(vendor="string"),
                     side_effect=SideEffect.WRITE, irreversible=True),
        ]

    def execute(self, tool: str, args: dict[str, Any]) -> Any:
        if tool == "lookup_invoice":
            if args["invoice_id"] not in INVOICES:
                raise ToolExecutionError("NOT_FOUND", f"No invoice {args['invoice_id']}")
            return INVOICES[args["invoice_id"]]
        if tool == "pay_invoice":
            return {"paid": args["invoice_id"], "amount_inr": args["amount_inr"]}
        return {"deleted": args["vendor"]}


# 2. Your policy: what this agent may do, with limits and approvals.
POLICY = """
agents:
  finance_assistant:
    tools:
      lookup_invoice: {allow: true}
      pay_invoice:    {allow: true, max_amount_inr: 50000, approval_above_inr: 10000}
      delete_vendor:  {allow: false}
"""


def main() -> list[tuple[str, str]]:
    policy_file = Path(tempfile.mkdtemp()) / "policy.yaml"
    policy_file.write_text(POLICY)
    store = Store.in_memory()
    # 3. One session puts AgentShield in front of your tools. Here an auto-approver stands in for the human
    #    who would approve held payments in the dashboard (`agentguard serve`, Approvals page).
    session = RuntimeSession(InvoiceTools(), store, agent_id="finance_assistant", policy=str(policy_file),
                             approvals=ApprovalQueue(store, auto=AutoApprover(default="approve")),
                             task="Pay this week's approved invoices")

    calls = [
        ("lookup_invoice", {"invoice_id": "INV-7"}),
        ("pay_invoice", {"invoice_id": "INV-7", "amount_inr": 4_000}),     # within limits
        ("pay_invoice", {"invoice_id": "INV-8", "amount_inr": 25_000}),    # above 10,000: held for a human
        ("pay_invoice", {"invoice_id": "INV-9", "amount_inr": 90_000}),    # above the 50,000 limit: blocked
        ("delete_vendor", {"vendor": "Acme Supplies"}),                     # not allowed for this agent
    ]
    outcomes = []
    for tool, args in calls:
        held_before = len([a for a in store.list_approvals() if a.run_id == session.run_id])
        r = session.endpoint.call(tool, args)
        held = len([a for a in store.list_approvals() if a.run_id == session.run_id]) > held_before
        outcome = ("held for a human -> approved -> ok" if held else "ok") if r.ok else f"{r.error.code}: {r.error.message}"
        outcomes.append((tool, outcome))
        print(f"{tool:<15} {args}  ->  {outcome}")

    record = session.close(AgentOutput(final_message="Paid INV-7 and INV-8.", exit_reason="completed"))
    audit = store.verify_audit(record.id)
    approvals = [a for a in store.list_approvals() if a.run_id == record.id]
    print(f"\nhuman approvals: {len(approvals)} ({', '.join(f'{a.tool} -> {a.status.value}' for a in approvals)})")
    print(f"audit log: {audit.events} events, hash chain {'verified' if audit.ok else 'BROKEN: ' + str(audit.problem)}")
    return outcomes


if __name__ == "__main__":
    main()
