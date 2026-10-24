"""A per-run evidence report: who did what, what was held, blocked or verified, what the agent claimed
against what happened, and whether the audit chain is intact.

Everything comes from the stored run, its hash-chained trace and its verdict, so the same run always
gives the same report (`agentguard audit report <run>`, `GET /api/runs/{id}/evidence`).
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any

from agentguard.core.models import TraceKind
from agentguard.core.store import Store
from agentguard.ops.controls import controls_from_trace

FRAMEWORKS = [
    ("Record-keeping of every action and decision", "EU AI Act Art. 12 · SOC 2 CC7 · NIST AI RMF Manage"),
    ("Human oversight of high-risk actions", "EU AI Act Art. 14 · NIST AI RMF Govern"),
    ("Least privilege per agent", "SOC 2 CC6 · ISO/IEC 42001 operational controls"),
    ("Robustness: injection defence, post-action verification", "EU AI Act Art. 15 · NIST AI RMF Measure"),
]


def _iso(t: Any) -> str | None:
    if t is None:
        return None
    s = t if isinstance(t, str) else t.isoformat()
    return s if s.endswith("Z") or "+" in s[10:] else s + "Z"  # stored times are UTC


def build_evidence(store: Store, run_id: str) -> dict[str, Any]:
    """The evidence for one run, as plain JSON-able data. Raises KeyError for an unknown run."""
    rec = store.get_run(run_id)
    if rec is None:
        raise KeyError(run_id)
    trace = store.get_trace(run_id)
    audit = store.verify_audit(run_id)

    decisions = {e.call_id: e.payload for e in trace if e.kind == TraceKind.DECISION}
    results = {e.call_id: e.payload for e in trace if e.kind == TraceKind.TOOL_RESULT}
    calls = []
    for e in trace:
        if e.kind != TraceKind.TOOL_CALL:
            continue
        d, r = decisions.get(e.call_id, {}), results.get(e.call_id)
        calls.append({
            "seq": e.payload.get("seq"), "ts": _iso(e.ts), "agent": e.payload.get("agent_id"),
            "tool": e.payload.get("tool"), "args": e.payload.get("args", {}),
            "decision": d.get("type"), "rule": d.get("rule_id"), "risk": d.get("risk"), "reason": d.get("reason"),
            "ok": None if r is None else r.get("ok"),
            "error": (r or {}).get("error"),
        })

    per_agent: dict[str, Counter] = defaultdict(Counter)
    tools_by_agent: dict[str, set[str]] = defaultdict(set)
    for c in calls:
        per_agent[c["agent"]][c["decision"] or "NONE"] += 1
        tools_by_agent[c["agent"]].add(c["tool"])
    agents = [{"agent": a, "calls": sum(n.values()), "tools": sorted(tools_by_agent[a]),
               "allowed": n["ALLOW"] + n["ALLOW_WITH_REDACTION"], "held": n["REQUIRE_APPROVAL"], "blocked": n["BLOCK"]}
              for a, n in sorted(per_agent.items())]

    approvals = []
    for e in trace:
        if e.kind == TraceKind.APPROVAL_RESOLVED:
            a = e.payload["approval"]
            approvals.append({"id": a["id"], "agent": a["agent_id"], "tool": a["tool"], "args": a["args"],
                              "why_held": a["decision"]["reason"], "rule": a["decision"]["rule_id"],
                              "status": a["status"], "by": a.get("resolved_by"), "note": a.get("note"),
                              "requested_at": _iso(a["created_at"]), "resolved_at": _iso(a.get("resolved_at"))})

    blocks = [{"seq": c["seq"], "agent": c["agent"], "tool": c["tool"], "rule": c["rule"], "risk": c["risk"],
               "reason": c["reason"]} for c in calls if c["decision"] == "BLOCK"]
    injections = [{"tool": e.payload.get("tool"), "call_seq": e.payload.get("call_seq"),
                   "source": e.payload.get("source"),
                   "findings": [f["description"] for f in e.payload.get("findings", [])]}
                  for e in trace if e.kind == TraceKind.INJECTION_DETECTED]
    verifications = [{"tool": e.payload.get("tool"), "call_seq": e.payload.get("call_seq"),
                      "check": e.payload.get("check"), "passed": e.payload.get("passed"), "risk": e.payload.get("risk")}
                     for e in trace if e.kind == TraceKind.VERIFICATION]
    faults = sum(1 for e in trace if e.kind == TraceKind.FAULT_INJECTED)

    shield = rec.config.get("shield") or {}
    v = rec.verdict or {}
    checks = v.get("checks") or []
    out = rec.output
    return {
        "run": {
            "id": rec.id, "status": rec.status.value, "scenario": rec.scenario_id, "world": rec.world,
            "harness": rec.harness, "model": rec.model, "seed": rec.seed,
            "shield": rec.config.get("shield_enabled", shield.get("enabled")), "policy": shield.get("policy"),
            "task": (rec.config.get("task") or {}).get("text"),
            "started_at": _iso(rec.created_at), "finished_at": _iso(rec.finished_at),
        },
        "agents": agents,
        "approvals": approvals,
        "blocks": blocks,
        "injections": injections,
        "verifications": verifications,
        "faults_injected": faults,
        "claim_vs_outcome": {
            "claimed": out.final_message if out else None,
            "claimed_outcome": out.claimed_outcome if out else None,
            "exit_reason": out.exit_reason if out else None,
            "verdict": v.get("outcome"), "passed": v.get("passed"), "summary": v.get("summary"),
            "claim_kind": (v.get("claim") or {}).get("kind"),
            "checks_passed": sum(1 for c in checks if c.get("ok")), "checks_total": len(checks),
            "failed_checks": [{"kind": c.get("kind"), "spec": c.get("spec"), "note": c.get("note")}
                              for c in checks if not c.get("ok")],
        } if v or out else None,
        "audit": {"ok": audit.ok, "events": audit.events, "head": audit.head, "problem": audit.problem,
                  "first_bad_seq": audit.first_bad_seq},
        "controls": controls_from_trace(store, run_id),
        "tool_calls": calls,
    }


def _cell(v: Any, limit: int = 90) -> str:
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, separators=(", ", ": "))
    s = s.replace("|", "\\|").replace("\n", " ")
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _table(head: list[str], rows: list[list[Any]]) -> list[str]:
    return ["| " + " | ".join(head) + " |", "|" + "---|" * len(head),
            *["| " + " | ".join(_cell(c) if c not in (None, "") else "–" for c in r) + " |" for r in rows], ""]


def evidence_markdown(ev: dict[str, Any]) -> str:
    run, audit, cv = ev["run"], ev["audit"], ev["claim_vs_outcome"]
    chain = (f"**verified**: {audit['events']} events, head `{(audit['head'] or '')[:16]}`" if audit["ok"]
             else f"**FAILED**: {audit['problem']}" + (f" (at event #{audit['first_bad_seq']})" if audit["first_bad_seq"] else ""))
    lines = [f"# Evidence report: {run['id']}", "",
             "Built by AgentGuard from the run's stored record, its hash-chained audit log and the independent verdict.",
             f"Audit chain {chain}. Re-check it with `agentguard audit verify {run['id']}`.", "",
             "## Run", ""]
    lines += _table(["Field", "Value"], [
        ["Task", run["task"]], ["Scenario", run["scenario"]], ["Harness", run["harness"]], ["Model", run["model"]],
        ["AgentShield", ("on" if run["shield"] else "off") + (f", policy `{run['policy']}`" if run["policy"] else "")],
        ["Started", run["started_at"]], ["Finished", run["finished_at"]], ["Status", run["status"]],
        ["Independent verdict", cv and cv["verdict"]],
    ])

    lines += ["## Agents and what they were allowed to do", ""]
    lines += _table(["Agent", "Tool calls", "Allowed", "Held for a person", "Blocked", "Tools used"],
                    [[a["agent"], a["calls"], a["allowed"], a["held"], a["blocked"], ", ".join(a["tools"])] for a in ev["agents"]])

    lines += ["## Human approvals", ""]
    lines += (_table(["Agent", "Action", "Why it was held", "Outcome", "Decided by", "Requested", "Decided"],
                     [[a["agent"], f"{a['tool']} {_cell(a['args'], 60)}", a["why_held"], a["status"], a["by"],
                       a["requested_at"], a["resolved_at"]] for a in ev["approvals"]])
              if ev["approvals"] else ["No action needed a person's approval.", ""])

    lines += ["## Actions blocked by policy", ""]
    lines += (_table(["Call", "Agent", "Tool", "Rule", "Risk", "Reason"],
                     [[f"#{b['seq']}", b["agent"], b["tool"], b["rule"], b["risk"], _cell(b["reason"], 240)]
                      for b in ev["blocks"]])
              if ev["blocks"] else ["No action was blocked.", ""])

    lines += ["## Prompt injections detected", ""]
    lines += (_table(["Found in", "Tool", "What it tried"],
                     [[f"output of call #{i['call_seq']}" if i["call_seq"] else f"the {i['source'] or 'input'}", i["tool"],
                       "; ".join(i["findings"])] for i in ev["injections"]])
              + ["Untrusted text is labelled and every later action is still decided by policy.", ""]
              if ev["injections"] else ["None detected.", ""])

    lines += ["## Post-action verifications", ""]
    lines += (_table(["After call", "Tool", "Check against the system of record", "Result"],
                     [[f"#{c['call_seq']}", c["tool"], c["check"], "passed" if c["passed"] else "FAILED"]
                      for c in ev["verifications"]])
              if ev["verifications"] else ["No action needed a post-action check.", ""])
    if ev["faults_injected"]:
        lines += [f"Test run: {ev['faults_injected']} tool fault(s) were injected by AgentGym.", ""]

    lines += ["## What the agent claimed, and what happened", ""]
    if cv:
        lines += [f"- Claimed: {cv['claimed'] or '–'}",
                  f"- Independent verdict: **{cv['verdict'] or 'not graded'}**"
                  + (f", {cv['checks_passed']}/{cv['checks_total']} checks on the final state passed" if cv["checks_total"] else ""),
                  *([f"- {cv['summary']}"] if cv["summary"] else []),
                  *[f"- Failed check: {f['kind']} {_cell(f['spec'], 120)}" + (f" ({f['note']})" if f["note"] else "")
                    for f in cv["failed_checks"]], ""]
    else:
        lines += ["The run has no output or verdict yet.", ""]

    lines += ["## Every tool call", ""]
    lines += _table(["#", "Agent", "Tool", "Arguments", "Decision", "Rule", "Risk", "Result"],
                    [[c["seq"], c["agent"], c["tool"], _cell(c["args"], 60), c["decision"], c["rule"], c["risk"],
                      "ok" if c["ok"] else (c["error"] or {}).get("code", "error") if c["ok"] is False else None]
                     for c in ev["tool_calls"]])

    lines += ["## Frameworks this evidence supports", ""]
    lines += _table(["Evidence", "Supports"], [list(f) for f in FRAMEWORKS])
    lines += ["Supporting evidence for these controls, not a certification of compliance.", ""]
    return "\n".join(lines)
