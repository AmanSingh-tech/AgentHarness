"""RefundOps: a multi-agent system that works a retail support inbox end to end.

    data ingestion  -> intake agent      reads every open ticket, extracts the request
    decision        -> decision agent    checks identity, ownership, amounts and history
    action          -> action agent      refunds, updates the ticket, emails the customer
    outcome report  -> reporting agent   re-checks every refund in the ledger, writes the report

Each agent acts through its own identity on the same gateway, so AgentShield holds
it to its own permissions (policy `intake_agent`, `decision_agent`, ...): the intake
and reporting agents cannot change anything, only the action agent can refund, and
only within limits; large refunds wait for a human. The decision logic is
deterministic and every decision carries plain-English reasons.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from agentguard.core.models import DataLabel, ToolResult
from agentguard.shield.injection import scan_text
from agentguard.transports.inprocess import InProcessEndpoint

ROLES = {"intake": "intake_agent", "decision": "decision_agent", "action": "action_agent", "reporting": "reporting_agent"}

_ORDER = re.compile(r"\bO-\d{3,}\b")
_AMOUNT = re.compile(r"(?:₹|\brs\.?|\binr)\s*([\d,]+(?:\.\d+)?)", re.IGNORECASE)
_REFUND_WORDS = re.compile(r"\b(refund\w*|money back|reimburse\w*|return\w*|charge ?back)\b", re.IGNORECASE)
_CONTROL_CODES = ("BLOCKED", "APPROVAL_REJECTED", "APPROVAL_TIMEOUT", "VERIFICATION_FAILED")


@dataclass
class Request:
    ticket_id: str
    customer_id: str | None
    text: str
    is_refund: bool
    order_id: str | None
    amount_inr: int | None  # None: the customer did not say; the decision uses what is refundable
    untrusted: bool  # AgentShield flagged the ticket text as a possible prompt injection
    notes: list[str] = field(default_factory=list)


@dataclass
class Decision:
    kind: str  # REFUND | REFUSE | ESCALATE | NEED_INFO | ROUTE
    amount_inr: int | None
    reasons: list[str]
    customer_email: str | None = None
    customer_name: str | None = None
    escalate_to: str | None = None


@dataclass
class Outcome:
    ticket_id: str
    customer_id: str | None
    order_id: str | None
    requested_inr: int | None
    decision: str
    reasons: list[str]
    action: str
    status: str  # refunded | refused | escalated | awaiting_info | routed | stopped_by_controls | failed
    refunded_inr: int = 0
    verified: bool | None = None  # refunds only: confirmed independently in the ledger
    controls: list[str] = field(default_factory=list)  # shield interventions seen by the agents


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------


class IntakeAgent:
    """Data ingestion: read the inbox and turn each ticket into a structured request."""

    def __init__(self, ep: InProcessEndpoint) -> None:
        self.ep = ep

    def run(self) -> list[Request]:
        listing = self.ep.call("list_tickets", {"status": "open"})
        if not listing.ok:
            raise RuntimeError(f"intake could not read the inbox: {listing.error.message if listing.error else ''}")
        requests = []
        for t in listing.output["tickets"]:
            r = self.ep.call("get_ticket", {"ticket_id": t["id"]})
            if not r.ok:
                continue
            text = str(r.output.get("notes", ""))
            orders = _ORDER.findall(text)
            amounts = [int(float(a.replace(",", ""))) for a in _AMOUNT.findall(text)]
            req = Request(
                ticket_id=t["id"], customer_id=t.get("customer_id"), text=text,
                is_refund=bool(_REFUND_WORDS.search(text)), order_id=orders[0] if orders else None,
                amount_inr=amounts[0] if amounts else None,
                # defence in depth: AgentShield's label, or the agent's own check of the text
                untrusted=DataLabel.UNTRUSTED in r.labels or bool(scan_text(text)),
            )
            if len(set(orders)) > 1:
                req.notes.append(f"several order numbers mentioned: {sorted(set(orders))}")
            if len(set(amounts)) > 1:
                req.notes.append(f"several amounts mentioned: {sorted(set(amounts))}")
            requests.append(req)
        return requests


class DecisionAgent:
    """Intelligent decision-making: eligibility, explained."""

    def __init__(self, ep: InProcessEndpoint, refund_limit_inr: int | None, approval_above_inr: int | None) -> None:
        self.ep = ep
        self.limit = refund_limit_inr
        self.approval_above = approval_above_inr

    def _contact(self, customer_id: str | None) -> tuple[str | None, str | None]:
        if not customer_id:
            return None, None
        r = self.ep.call("get_customer", {"customer_id": customer_id})
        return (r.output.get("email"), r.output.get("name")) if r.ok else (None, None)

    def decide(self, req: Request) -> Decision:
        if req.untrusted:
            return Decision("ESCALATE", None, ["The ticket text looks like a prompt injection; a person must read it "
                                               "before anything is done."], escalate_to="security review")
        if not req.is_refund:
            return Decision("ROUTE", None, ["Not a refund request."], escalate_to="general support")
        if req.order_id is None:
            email, name = self._contact(req.customer_id)
            return Decision("NEED_INFO", None, ["The customer did not give an order number."], email, name)
        if len(req.notes) and any("several" in n for n in req.notes):
            return Decision("ESCALATE", None, [f"Ambiguous request: {'; '.join(req.notes)}."], escalate_to="support lead")

        customer = self.ep.call("get_customer", {"customer_id": req.customer_id}) if req.customer_id else None
        if customer is None or not customer.ok:
            return Decision("REFUSE", None, ["The customer record could not be found."])
        c = customer.output
        email, name = c.get("email"), c.get("name")
        order = self.ep.call("get_order", {"order_id": req.order_id})
        if not order.ok:
            return Decision("REFUSE", None, [f"Order {req.order_id} does not exist."], email, name)
        o = order.output
        if not c.get("verified"):
            return Decision("REFUSE", None, ["The customer's identity is not verified; they need to verify their "
                                             "account before a refund can be issued."], email, name)
        if o.get("customer_id") != req.customer_id:
            return Decision("REFUSE", None, [f"Order {req.order_id} belongs to a different customer."], email, name)
        refundable = int(o.get("refundable_inr", 0))
        if refundable <= 0:
            return Decision("REFUSE", None, [f"Order {req.order_id} has already been refunded in full."], email, name)
        amount = req.amount_inr if req.amount_inr is not None else refundable
        if amount > refundable:
            return Decision("REFUSE", None, [f"₹{amount:,} requested but only ₹{refundable:,} of order "
                                             f"{req.order_id} is refundable."], email, name)
        if self.limit is not None and amount > self.limit:
            return Decision("ESCALATE", amount, [f"₹{amount:,} is above this team's ₹{self.limit:,} refund limit."],
                            email, name, escalate_to="finance")
        reasons = [f"Verified customer, own order, ₹{amount:,} of ₹{refundable:,} refundable."]
        if self.approval_above is not None and amount > self.approval_above:
            reasons.append(f"Above ₹{self.approval_above:,}: AgentShield will hold it for human approval.")
        return Decision("REFUND", amount, reasons, email, name)


class ActionAgent:
    """Action execution: carry out the decision through the guarded tools."""

    def __init__(self, ep: InProcessEndpoint) -> None:
        self.ep = ep

    def act(self, req: Request, d: Decision) -> Outcome:
        out = Outcome(req.ticket_id, req.customer_id, req.order_id, req.amount_inr, d.kind, d.reasons, "", "")
        if d.kind == "REFUND":
            key = f"refundops-{req.ticket_id}-{req.order_id}-{d.amount_inr}"
            r = self._call(out, "issue_refund", {"order_id": req.order_id, "amount_inr": d.amount_inr,
                                                 "idempotency_key": key})
            if r.ok:
                out.action, out.status, out.refunded_inr = f"Refunded ₹{d.amount_inr:,}", "refunded", int(d.amount_inr or 0)

                self._call(out, "update_ticket", {"ticket_id": req.ticket_id, "status": "resolved",
                                                  "notes": f"RefundOps: refunded ₹{d.amount_inr:,} for {req.order_id} "
                                                           f"(key {key})."})
                self._email(out, d, f"Your refund for order {req.order_id}",
                            f"we have refunded ₹{d.amount_inr:,} for order {req.order_id}. "
                            "It should reach you in 5-7 business days.")
            else:
                code = r.error.code if r.error else "ERROR"
                out.action = f"Refund not issued ({code})"
                out.status = "stopped_by_controls" if code in _CONTROL_CODES else "failed"
                self._call(out, "update_ticket", {"ticket_id": req.ticket_id, "status": "escalated",
                                                  "notes": f"RefundOps: refund not issued: {code}. "
                                                           f"{r.error.message if r.error else ''}"[:500]})
        elif d.kind == "REFUSE":
            out.action, out.status = "Refused with explanation", "refused"
            self._call(out, "update_ticket", {"ticket_id": req.ticket_id, "status": "resolved",
                                              "notes": "RefundOps: refused. " + " ".join(d.reasons)})
            self._email(out, d, "About your refund request",
                        "we could not issue this refund: " + " ".join(d.reasons))
        elif d.kind == "ESCALATE":
            out.action, out.status = f"Escalated to {d.escalate_to}", "escalated"
            self._call(out, "update_ticket", {"ticket_id": req.ticket_id, "status": "escalated",
                                              "notes": f"RefundOps: escalated to {d.escalate_to}. " + " ".join(d.reasons)})
        elif d.kind == "NEED_INFO":
            out.action, out.status = "Asked the customer for the order number", "awaiting_info"
            self._call(out, "update_ticket", {"ticket_id": req.ticket_id, "status": "pending",
                                              "notes": "RefundOps: waiting for the order number from the customer."})
            self._email(out, d, "We need your order number",
                        "please reply with the order number (it looks like O-1234) so we can process your refund.")
        else:  # ROUTE
            out.action, out.status = f"Routed to {d.escalate_to}", "routed"
            self._call(out, "update_ticket", {"ticket_id": req.ticket_id, "status": "pending",
                                              "notes": f"RefundOps: not a refund request; routed to {d.escalate_to}."})
        return out

    def _email(self, out: Outcome, d: Decision, subject: str, body: str) -> None:
        if d.customer_email:
            self._call(out, "send_email", {"to": d.customer_email, "subject": subject,
                                           "body": f"Hi {d.customer_name or 'there'}, {body}"})

    def _call(self, out: Outcome, tool: str, args: dict[str, Any]) -> ToolResult:
        r = self.ep.call(tool, args)
        if not r.ok and r.error:
            if r.error.code in _CONTROL_CODES:
                out.controls.append(f"{tool}: {r.error.code}: {r.error.message}")
            # any step that did not happen means the ticket is not handled as decided
            if out.status not in ("stopped_by_controls", "failed"):
                out.status = "stopped_by_controls" if r.error.code in _CONTROL_CODES else "failed"
                out.action += f" ({tool} not done: {r.error.code})"
        return r


class ReportingAgent:
    """Outcome reporting: verify every refund independently, then summarise."""

    def __init__(self, ep: InProcessEndpoint) -> None:
        self.ep = ep

    def report(self, outcomes: list[Outcome], ledger_before: dict[str, int]) -> dict[str, Any]:
        for o in outcomes:
            if o.refunded_inr <= 0 or not o.order_id:
                continue
            r = self.ep.call("get_order", {"order_id": o.order_id})
            after = int(r.output.get("refunded_amount_inr", 0)) if r.ok else None
            o.verified = after is not None and after - ledger_before.get(o.order_id, 0) == o.refunded_inr
        statuses = [o.status for o in outcomes]
        return {
            "process": "RefundOps",
            "domain": "Retail and Supply: customer refunds",
            "summary": {
                "tickets": len(outcomes),
                "refunded": sum(1 for o in outcomes if o.refunded_inr > 0),
                "refunded_inr_verified": sum(o.refunded_inr for o in outcomes if o.verified),
                "refunds_unverified": sum(1 for o in outcomes if o.refunded_inr > 0 and not o.verified),
                "refused": statuses.count("refused"),
                "escalated": statuses.count("escalated"),
                "awaiting_info": statuses.count("awaiting_info"),
                "routed": statuses.count("routed"),
                "stopped_by_controls": statuses.count("stopped_by_controls"),
                "failed": statuses.count("failed"),
                "needs_human": sum(1 for o in outcomes if o.status in ("escalated", "stopped_by_controls", "failed")),
            },
            "items": [asdict(o) for o in outcomes],
        }


# ---------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------


def run_refund_ops(endpoint: InProcessEndpoint, refund_limit_inr: int | None = 5000,
                   approval_above_inr: int | None = 2000) -> dict[str, Any]:
    intake = IntakeAgent(endpoint.as_agent(ROLES["intake"]))
    decider = DecisionAgent(endpoint.as_agent(ROLES["decision"]), refund_limit_inr, approval_above_inr)
    actor = ActionAgent(endpoint.as_agent(ROLES["action"]))
    reporter = ReportingAgent(endpoint.as_agent(ROLES["reporting"]))

    requests = intake.run()
    outcomes, before = [], {}
    for req in requests:
        d = decider.decide(req)
        if d.kind == "REFUND" and req.order_id:
            r = actor.ep.call("get_order", {"order_id": req.order_id})
            before[req.order_id] = int(r.output.get("refunded_amount_inr", 0)) if r.ok else 0
        outcomes.append(actor.act(req, d))
    return reporter.report(outcomes, before)


def limits_from_policy(policy: Any) -> tuple[int | None, int | None]:
    """The decision agent uses the same limits AgentShield enforces on the action agent."""
    perm = policy.agents.get(ROLES["action"])
    refund = perm.tools.get("issue_refund") if perm else None
    return (refund.max_amount_inr, refund.approval_above_inr) if refund else (None, None)


def to_markdown(report: dict[str, Any], controls: dict[str, Any] | None = None) -> str:
    s = report["summary"]
    lines = [
        f"# {report['process']} outcome report",
        "",
        f"Domain: {report['domain']}",
        "",
        f"- Tickets processed: **{s['tickets']}**",
        f"- Refunded: **{s['refunded']}** (₹{s['refunded_inr_verified']:,} confirmed in the ledger"
        + (f", {s['refunds_unverified']} NOT confirmed" if s["refunds_unverified"] else "") + ")",
        f"- Refused with an explanation: {s['refused']}",
        f"- Escalated to a person: {s['escalated']}",
        f"- Waiting for the customer: {s['awaiting_info']} · routed elsewhere: {s['routed']}",
        f"- Stopped by AgentShield / human reviewer: {s['stopped_by_controls']} · failed: {s['failed']}",
        "",
        "| Ticket | Order | Requested | Decision | Action | Status | Verified | Why |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for i in report["items"]:
        verified = {True: "✅ ledger", False: "❌", None: ""}[i["verified"]]
        req = f"₹{i['requested_inr']:,}" if i["requested_inr"] is not None else ""
        lines.append(f"| {i['ticket_id']} | {i['order_id'] or ''} | {req} | {i['decision']} | {i['action']} | "
                     f"{i['status']} | {verified} | {' '.join(i['reasons'])} |")
    if controls:
        lines += ["", "## Responsible-AI controls in this run", ""]
        lines.append(f"- Human approvals: {controls.get('approvals_granted', 0)} granted, "
                     f"{controls.get('approvals_rejected', 0)} rejected")
        lines.append(f"- Actions blocked by policy: {controls.get('blocks', 0)}"
                     + (f" ({', '.join(controls.get('blocked_rules', []))})" if controls.get("blocked_rules") else ""))
        lines.append(f"- Prompt injections detected: {controls.get('injections', 0)}")
        lines.append(f"- Post-action verifications: {controls.get('verifications_passed', 0)} passed, "
                     f"{controls.get('verifications_failed', 0)} failed")
        lines.append(f"- Audit log: {controls.get('audit_events', 0)} events, hash chain "
                     f"{'verified' if controls.get('audit_ok') else 'NOT verified'}")
    return "\n".join(lines) + "\n"
