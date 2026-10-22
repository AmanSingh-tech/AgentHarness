"""AccessOps: a multi-agent system that works an IT access-request queue end to end.

    data ingestion  -> intake agent      reads every open access request
    decision        -> decision agent    checks employment, who asked, roles, existing access, SoD
    action          -> action agent      grants exactly what was requested, updates and notifies
    outcome report  -> reporting agent   re-checks every grant in the directory, writes the report

As with RefundOps, each agent has its own identity and least-privilege permissions
(`access_*_agent` in the policy), and AgentShield enforces the IT controls
independently of the agents: active users only, grant must match the request,
segregation of duties, human approval for admin on high/critical systems,
expiry limits, and a post-action check that every grant exists.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from agentguard.core.models import DataLabel, ToolResult
from agentguard.shield.injection import scan_text
from agentguard.transports.inprocess import InProcessEndpoint

ROLES = {"intake": "access_intake_agent", "decision": "access_decision_agent",
         "action": "access_action_agent", "reporting": "access_reporting_agent"}
# Pairs of systems no one may hold write access on together.
SOD_PAIRS = [("SYS-PAY", "SYS-AUDIT")]
_CONTROL_CODES = ("BLOCKED", "APPROVAL_REJECTED", "APPROVAL_TIMEOUT", "VERIFICATION_FAILED")


@dataclass
class AccessRequest:
    request_id: str
    requester_id: str
    user_id: str
    system_id: str
    role: str
    justification: str
    untrusted: bool


@dataclass
class AccessDecision:
    kind: str  # GRANT | DENY | ESCALATE | NEED_INFO | CLOSE
    reasons: list[str]
    days: int | None = None
    notify: list[str] = field(default_factory=list)  # emails of requester and user
    escalate_to: str | None = None


@dataclass
class AccessOutcome:
    request_id: str
    user_id: str
    system_id: str
    role: str
    decision: str
    reasons: list[str]
    action: str
    status: str  # granted | denied | escalated | awaiting_info | already_had_access | stopped_by_controls | failed
    granted: bool = False
    verified: bool | None = None
    controls: list[str] = field(default_factory=list)


class AccessIntakeAgent:
    def __init__(self, ep: InProcessEndpoint) -> None:
        self.ep = ep

    def run(self) -> list[AccessRequest]:
        listing = self.ep.call("list_access_requests", {"status": "open"})
        if not listing.ok:
            raise RuntimeError("intake could not read the access-request queue")
        out = []
        for r in listing.output["requests"]:
            full = self.ep.call("get_access_request", {"request_id": r["id"]})
            if not full.ok:
                continue
            o = full.output
            out.append(AccessRequest(o["id"], o["requester_id"], o["user_id"], o["system_id"], o["role"],
                                     o.get("justification", ""),
                                     DataLabel.UNTRUSTED in full.labels or bool(scan_text(o.get("justification", "")))))
        return out


class AccessDecisionAgent:
    def __init__(self, ep: InProcessEndpoint) -> None:
        self.ep = ep

    def decide(self, req: AccessRequest) -> AccessDecision:
        if req.untrusted:
            return AccessDecision("ESCALATE", ["The justification looks like a prompt injection; a person must "
                                               "review it before anything is done."], escalate_to="security review")
        requester = self.ep.call("get_user", {"user_id": req.requester_id})
        notify = [requester.output["email"]] if requester.ok else []
        if len(req.justification.strip()) < 10:
            return AccessDecision("NEED_INFO", ["No business justification was given."], notify=notify)
        user = self.ep.call("get_user", {"user_id": req.user_id})
        if not user.ok:
            return AccessDecision("DENY", [f"Employee {req.user_id} does not exist."], notify=notify)
        u = user.output
        notify = sorted(set(notify + [u["email"]]))
        if u["status"] != "active":
            return AccessDecision("DENY", [f"{u['name']} is no longer an active employee ({u['status']})."],
                                  notify=[e for e in notify if e != u["email"]])
        system = self.ep.call("get_system", {"system_id": req.system_id})
        if not system.ok:
            return AccessDecision("DENY", [f"System {req.system_id} does not exist."], notify=notify)
        s = system.output
        if req.role not in s["roles"]:
            return AccessDecision("DENY", [f"{s['name']} has no '{req.role}' role (it offers {', '.join(s['roles'])})."],
                                  notify=notify)
        is_manager = u.get("manager_id") == req.requester_id
        self_service = req.requester_id == req.user_id and req.role == "read" and s["sensitivity"] == "low"
        if not (is_manager or self_service):
            return AccessDecision("ESCALATE", [f"Only {u['name']}'s manager can request {req.role} access to "
                                               f"{s['name']} ({s['sensitivity']} sensitivity)."],
                                  notify=notify, escalate_to="the employee's manager")
        grants = self.ep.call("list_grants", {"user_id": req.user_id})
        held = {(g["system_id"], g["role"]) for g in grants.output["grants"]} if grants.ok else set()
        if (req.system_id, req.role) in held:
            return AccessDecision("CLOSE", [f"{u['name']} already has {req.role} access to {s['name']}."], notify=notify)
        for a, b in SOD_PAIRS:
            other = b if req.system_id == a else a if req.system_id == b else None
            if other and req.role != "read" and any(g == (other, r) for g in held for r in ("write", "admin")):
                return AccessDecision("DENY", [f"Segregation of duties: {u['name']} already has write access to "
                                               f"{other}; write access to {s['name']} as well is not allowed."],
                                      notify=notify)
        days = 30 if s["sensitivity"] == "critical" else 90
        reasons = [f"Requested by {'the manager' if is_manager else 'the employee (self-service, low risk)'}; "
                   f"{s['sensitivity']}-sensitivity system; grant for {days} days."]
        if req.role == "admin" and s["sensitivity"] in ("high", "critical"):
            reasons.append("Admin on a high or critical system: AgentShield will hold it for human approval.")
        return AccessDecision("GRANT", reasons, days=days, notify=notify)


class AccessActionAgent:
    def __init__(self, ep: InProcessEndpoint) -> None:
        self.ep = ep

    def act(self, req: AccessRequest, d: AccessDecision) -> AccessOutcome:
        out = AccessOutcome(req.request_id, req.user_id, req.system_id, req.role, d.kind, d.reasons, "", "")
        what = f"{req.role} access to {req.system_id} for {req.user_id}"
        if d.kind == "GRANT":
            r = self._call(out, "grant_access", {"user_id": req.user_id, "system_id": req.system_id, "role": req.role,
                                                 "request_id": req.request_id, "days": d.days})
            if r.ok:
                out.action, out.status, out.granted = f"Granted {what} for {d.days} days", "granted", True
                self._call(out, "update_access_request", {"request_id": req.request_id, "status": "done",
                                                          "notes": f"AccessOps: granted until {r.output.get('expires_at')}."})
                self._notify(out, d, "Access granted", f"{what} has been granted for {d.days} days.")
            else:
                code = r.error.code if r.error else "ERROR"
                out.action = f"Grant not made ({code})"
                out.status = "stopped_by_controls" if code in _CONTROL_CODES else "failed"
                self._call(out, "update_access_request", {"request_id": req.request_id, "status": "escalated",
                                                          "notes": f"AccessOps: grant not made: {code}."})
        elif d.kind == "DENY":
            out.action, out.status = "Denied with explanation", "denied"
            self._call(out, "update_access_request", {"request_id": req.request_id, "status": "denied",
                                                      "notes": "AccessOps: denied. " + " ".join(d.reasons)})
            self._notify(out, d, "Access request denied", "your request was denied: " + " ".join(d.reasons))
        elif d.kind == "ESCALATE":
            out.action, out.status = f"Escalated to {d.escalate_to}", "escalated"
            self._call(out, "update_access_request", {"request_id": req.request_id, "status": "escalated",
                                                      "notes": f"AccessOps: escalated to {d.escalate_to}. " + " ".join(d.reasons)})
        elif d.kind == "NEED_INFO":
            out.action, out.status = "Asked the requester for a justification", "awaiting_info"
            self._call(out, "update_access_request", {"request_id": req.request_id, "status": "pending",
                                                      "notes": "AccessOps: waiting for a business justification."})
            self._notify(out, d, "Justification needed", "please add a business justification to your access request.")
        else:  # CLOSE
            out.action, out.status = "Closed: access already in place", "already_had_access"
            self._call(out, "update_access_request", {"request_id": req.request_id, "status": "done",
                                                      "notes": "AccessOps: " + " ".join(d.reasons)})
            self._notify(out, d, "Access already in place", " ".join(d.reasons))
        return out

    def _notify(self, out: AccessOutcome, d: AccessDecision, subject: str, body: str) -> None:
        for to in d.notify:
            self._call(out, "notify", {"to": to, "subject": f"{subject} ({out.request_id})", "body": f"Hello, {body}"})

    def _call(self, out: AccessOutcome, tool: str, args: dict[str, Any]) -> ToolResult:
        r = self.ep.call(tool, args)
        if not r.ok and r.error:
            if r.error.code in _CONTROL_CODES:
                out.controls.append(f"{tool}: {r.error.code}: {r.error.message}")
            if out.status not in ("stopped_by_controls", "failed"):
                out.status = "stopped_by_controls" if r.error.code in _CONTROL_CODES else "failed"
                out.action += f" ({tool} not done: {r.error.code})"
        return r


class AccessReportingAgent:
    def __init__(self, ep: InProcessEndpoint) -> None:
        self.ep = ep

    def report(self, outcomes: list[AccessOutcome]) -> dict[str, Any]:
        for o in outcomes:
            if o.granted:
                r = self.ep.call("list_grants", {"user_id": o.user_id})
                o.verified = r.ok and any(g["system_id"] == o.system_id and g["role"] == o.role
                                          for g in r.output["grants"])
        st = [o.status for o in outcomes]
        return {
            "process": "AccessOps",
            "domain": "IT Infrastructure: identity and access requests",
            "summary": {
                "requests": len(outcomes),
                "granted": sum(o.granted for o in outcomes),
                "grants_verified": sum(1 for o in outcomes if o.verified),
                "grants_unverified": sum(1 for o in outcomes if o.granted and not o.verified),
                "denied": st.count("denied"),
                "escalated": st.count("escalated"),
                "awaiting_info": st.count("awaiting_info"),
                "already_had_access": st.count("already_had_access"),
                "stopped_by_controls": st.count("stopped_by_controls"),
                "failed": st.count("failed"),
                "needs_human": sum(1 for o in outcomes if o.status in ("escalated", "stopped_by_controls", "failed")),
            },
            "items": [asdict(o) for o in outcomes],
        }


def run_access_ops(endpoint: InProcessEndpoint) -> dict[str, Any]:
    intake = AccessIntakeAgent(endpoint.as_agent(ROLES["intake"]))
    decider = AccessDecisionAgent(endpoint.as_agent(ROLES["decision"]))
    actor = AccessActionAgent(endpoint.as_agent(ROLES["action"]))
    reporter = AccessReportingAgent(endpoint.as_agent(ROLES["reporting"]))
    outcomes = [actor.act(req, decider.decide(req)) for req in intake.run()]
    return reporter.report(outcomes)


def to_markdown(report: dict[str, Any], controls: dict[str, Any] | None = None) -> str:
    s = report["summary"]
    lines = [
        f"# {report['process']} outcome report", "", f"Domain: {report['domain']}", "",
        f"- Requests processed: **{s['requests']}**",
        f"- Granted: **{s['granted']}** ({s['grants_verified']} confirmed in the directory"
        + (f", {s['grants_unverified']} NOT confirmed" if s["grants_unverified"] else "") + ")",
        f"- Denied with an explanation: {s['denied']} · already in place: {s['already_had_access']}",
        f"- Escalated to a person: {s['escalated']} · waiting for the requester: {s['awaiting_info']}",
        f"- Stopped by AgentShield / human reviewer: {s['stopped_by_controls']} · failed: {s['failed']}",
        "", "| Request | Employee | System | Role | Decision | Status | Verified | Why |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for i in report["items"]:
        verified = {True: "✅ directory", False: "❌", None: ""}[i["verified"]]
        lines.append(f"| {i['request_id']} | {i['user_id']} | {i['system_id']} | {i['role']} | {i['decision']} | "
                     f"{i['status']} | {verified} | {' '.join(i['reasons'])} |")
    if controls:
        from agentguard.ops.controls import controls_markdown

        lines += ["", controls_markdown(controls).rstrip()]
    return "\n".join(lines) + "\n"
