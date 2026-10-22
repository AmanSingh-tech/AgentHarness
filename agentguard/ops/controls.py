"""What the responsible-AI controls did during a run, from its audit trace."""

from __future__ import annotations

from typing import Any

from agentguard.core.models import TraceKind
from agentguard.core.store import Store


def controls_from_trace(store: Store, run_id: str) -> dict[str, Any]:
    trace = store.get_trace(run_id)
    approvals = [e.payload["approval"] for e in trace if e.kind == TraceKind.APPROVAL_RESOLVED]
    blocks = [e.payload for e in trace if e.kind == TraceKind.DECISION and e.payload["type"] == "BLOCK"]
    checks = [e.payload for e in trace if e.kind == TraceKind.VERIFICATION]
    agents = sorted({e.payload["agent_id"] for e in trace if e.kind == TraceKind.TOOL_CALL})
    audit = store.verify_audit(run_id)
    return {
        "agents": agents,
        "tool_calls": sum(1 for e in trace if e.kind == TraceKind.TOOL_CALL),
        "approvals_granted": sum(a["status"] == "approved" for a in approvals),
        "approvals_rejected": sum(a["status"] in ("rejected", "timed_out") for a in approvals),
        "approvals": [{"tool": a["tool"], "status": a["status"], "by": a["resolved_by"],
                       "reason": a["decision"]["reason"]} for a in approvals],
        "blocks": len(blocks),
        "blocked_rules": sorted({b["rule_id"] for b in blocks}),
        "injections": sum(1 for e in trace if e.kind == TraceKind.INJECTION_DETECTED),
        "verifications_passed": sum(c["passed"] for c in checks),
        "verifications_failed": sum(not c["passed"] for c in checks),
        "audit_events": audit.events,
        "audit_ok": audit.ok,
    }


def controls_markdown(controls: dict[str, Any]) -> str:
    lines = ["## Responsible-AI controls in this run", ""]
    lines.append(f"- Agents, each with its own identity and least privilege: {', '.join(controls.get('agents', []))}")
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

