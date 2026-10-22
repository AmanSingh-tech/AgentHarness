"""AgentShield: the decision stages the Gateway runs for every tool call.

    ToolCall -> injection scan (input) -> policy (identity, permission, limits, rules)
             -> risk score -> taint/sequence check -> decision
             -> [approval wait] -> [fault injector, gym only] -> execute
             -> injection scan (output) -> redaction -> taint labelling -> result

Each stage votes; the Gateway takes the most restrictive vote and the highest
risk, and records every vote in the trace. Stages that need to see results
implement `observe(call, spec, result)` and may return extra trace events.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agentguard.core.models import (
    DataLabel,
    Decision,
    DecisionType,
    RiskLevel,
    ToolCall,
    ToolResult,
    ToolSpec,
    TraceKind,
    decision_rank,
)
from agentguard.shield import injection, risk
from agentguard.shield.approvals import AutoApprover
from agentguard.shield.policy import Policy, ToolPermission
from agentguard.shield.policy.expr import ExprError
from agentguard.shield.taint import TaintMatch, TaintTracker
from agentguard.world.base import ToolBackend

Events = list[tuple[TraceKind, dict[str, Any]]]
_EMAIL = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
_RECIPIENT_FIELDS = ("to", "cc", "bcc", "recipient", "recipients")


class ShieldConfig(BaseModel):
    """Per-run AgentShield settings (a scenario's `shield:` block)."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    policy: str = "default"  # built-in name or path
    auto_approver: AutoApprover = Field(default_factory=AutoApprover)
    approval_timeout_s: float = 30.0


@dataclass
class ShieldSession:
    """State shared by the stages for one run."""

    taint: TaintTracker = field(default_factory=TaintTracker)
    untrusted_calls: list[int] = field(default_factory=list)  # call seqs whose output was flagged
    untrusted_task: bool = False

    def untrusted_note(self) -> str:
        where = []
        if self.untrusted_task:
            where.append("the task text")
        if self.untrusted_calls:
            where.append("output of call " + ", ".join(f"#{n}" for n in self.untrusted_calls))
        if not where:
            return ""
        return (f" Defense in depth: possible prompt injection was seen in {' and '.join(where)}; "
                "this action is blocked by policy whether or not that detection fired.")


class Shield:
    def __init__(self, policy: Policy, backend: ToolBackend) -> None:
        self.policy = policy
        self.session = ShieldSession()
        self.stages = [
            InjectionStage(self.session),
            PolicyStage(policy, backend, self.session),
            RiskStage(self.session),
            TaintStage(policy, self.session),
        ]

    def scan_task(self, text: str) -> list[injection.Finding]:
        findings = injection.scan_text(text)
        if findings:
            self.session.untrusted_task = True
        return findings


def _d(type_: DecisionType, reason: str, rule_id: str, risk_: RiskLevel, stage: str, **evidence: Any) -> Decision:
    return Decision(type=type_, reason=reason, rule_id=rule_id, risk=risk_, stage=stage, evidence=evidence)


# ---------------------------------------------------------------------------


class InjectionStage:
    name = "injection"

    def __init__(self, session: ShieldSession) -> None:
        self.session = session

    def evaluate(self, call: ToolCall, spec: ToolSpec) -> Decision | None:
        findings = injection.scan_value(call.args)
        if not findings:
            return None
        ids = ", ".join(f.pattern_id for f in findings)
        return _d(DecisionType.ALLOW, f"Arguments contain text that looks like a prompt injection ({ids}).",
                  "injection.input", RiskLevel.HIGH, self.name, findings=[f.to_dict() for f in findings])

    def observe(self, call: ToolCall, spec: ToolSpec, result: ToolResult) -> Events:
        findings = injection.scan_value(result.output)
        if result.error is not None:
            findings += injection.scan_text(result.error.message)
        flagged = DataLabel.UNTRUSTED in result.labels
        if not findings and not flagged:
            return []
        if not flagged:
            result.labels.append(DataLabel.UNTRUSTED)
        self.session.untrusted_calls.append(call.seq)
        return [(TraceKind.INJECTION_DETECTED, {
            "source": "tool_output", "tool": call.tool, "call_seq": call.seq,
            "findings": [f.to_dict() for f in findings],
            "note": "Output labelled UNTRUSTED. Policy still governs every action that follows.",
        })]


class PolicyStage:
    name = "policy"

    def __init__(self, policy: Policy, backend: ToolBackend, session: ShieldSession) -> None:
        self.policy = policy
        self.queries = backend.rule_queries()
        self.session = session
        self._redact: dict[str, int] = {}  # call id -> max rows

    def evaluate(self, call: ToolCall, spec: ToolSpec) -> Decision:
        votes = self._votes(call, spec)
        worst = max(votes, key=decision_rank)
        if worst.type == DecisionType.BLOCK:
            worst.reason += self.session.untrusted_note()
        return worst

    def _votes(self, call: ToolCall, spec: ToolSpec) -> list[Decision]:
        agent_id, tool, args = call.agent_id, call.tool, call.args
        agent = self.policy.agents.get(agent_id)
        if agent is None:
            return [_d(DecisionType.BLOCK, f"No policy is defined for agent '{agent_id}', so it may not call any tool.",
                       "policy.unknown_agent", RiskLevel.MEDIUM, self.name)]
        perm = agent.tools.get(tool)
        base = f"{agent_id}.{tool}"
        if perm is None or not perm.allow:
            why = "is not listed for" if perm is None else "is denied for"
            sensitive = spec.irreversible or bool({DataLabel.SECRET, DataLabel.PII_BULK} & set(spec.returns_labels))
            return [_d(DecisionType.BLOCK, f"Tool '{tool}' {why} agent '{agent_id}'.", f"{base}.allow",
                       RiskLevel.HIGH if sensitive else RiskLevel.MEDIUM, self.name)]

        votes = [_d(DecisionType.ALLOW, f"'{agent_id}' may call '{tool}'.", f"{base}.allow", RiskLevel.LOW, self.name)]
        votes += self._limits(call, spec, perm, base)
        votes += self._rules(call)
        if perm.max_rows is not None:
            self._redact[call.id] = perm.max_rows
            votes.append(_d(DecisionType.ALLOW_WITH_REDACTION, f"Results are limited to {perm.max_rows} rows.",
                            f"{base}.max_rows", RiskLevel.LOW, self.name, max_rows=perm.max_rows))
        return votes

    def _limits(self, call: ToolCall, spec: ToolSpec, perm: ToolPermission, base: str) -> list[Decision]:
        votes = []
        agent_id, args = call.agent_id, call.args
        encoded = json.dumps(args, ensure_ascii=False)
        for pattern in perm.deny_patterns:
            m = re.search(pattern, encoded)
            if m:
                bulk = bool({DataLabel.SECRET, DataLabel.PII_BULK} & set(spec.returns_labels))
                votes.append(_d(DecisionType.BLOCK,
                                f"'{call.tool}' arguments match denied pattern '{pattern}' (matched '{m.group(0)}')"
                                + (": this would be a bulk export of sensitive data." if bulk else "."),
                                f"{base}.deny_patterns", RiskLevel.CRITICAL if bulk else RiskLevel.HIGH, self.name,
                                pattern=pattern, matched=m.group(0)))
        amount = args.get("amount_inr")
        if isinstance(amount, (int, float)):
            if perm.max_amount_inr is not None and amount > perm.max_amount_inr:
                votes.append(_d(DecisionType.BLOCK,
                                f"₹{amount:,} exceeds {agent_id}'s limit of ₹{perm.max_amount_inr:,} for '{call.tool}'.",
                                f"{base}.max_amount_inr", RiskLevel.HIGH, self.name,
                                amount_inr=amount, limit=perm.max_amount_inr))
            elif perm.approval_above_inr is not None and amount > perm.approval_above_inr:
                votes.append(_d(DecisionType.REQUIRE_APPROVAL,
                                f"₹{amount:,} is above {agent_id}'s approval threshold of ₹{perm.approval_above_inr:,}.",
                                f"{base}.approval_above_inr", RiskLevel.HIGH, self.name,
                                amount_inr=amount, threshold=perm.approval_above_inr))
        if perm.allowed_domains is not None:
            bad = sorted({d for d in _recipient_domains(args) if not _domain_allowed(d, perm.allowed_domains)})
            if bad:
                votes.append(_d(DecisionType.BLOCK,
                                f"Recipient domain(s) {bad} are not in {agent_id}'s allowed domains {perm.allowed_domains}.",
                                f"{base}.allowed_domains", RiskLevel.HIGH, self.name, domains=bad))
        if perm.require_approval:
            votes.append(_d(DecisionType.REQUIRE_APPROVAL, f"'{call.tool}' always requires approval for {agent_id}.",
                            f"{base}.require_approval", RiskLevel.MEDIUM, self.name))
        return votes

    def _rules(self, call: ToolCall) -> list[Decision]:
        votes = []
        for rule in self.policy.rules:
            if rule.when.tool != call.tool:
                continue
            if rule.when.args_match and not re.search(rule.when.args_match, json.dumps(call.args, ensure_ascii=False)):
                continue
            variables = {**call.args, "args": call.args, "agent": call.agent_id}
            try:
                ok = bool(rule.expr.evaluate(variables, self.queries))
            except (ExprError, TypeError, ValueError, KeyError) as e:
                votes.append(_d(DecisionType.BLOCK, f"Rule '{rule.id}' could not be evaluated ({e}); failing closed.",
                                rule.id, rule.risk, self.name, check=rule.check))
                continue
            if not ok:
                votes.append(_d(rule.on_fail, rule.message or rule.description or f"Rule '{rule.id}' failed.",
                                rule.id, rule.risk, self.name, check=rule.check,
                                inputs={n: variables.get(n) for n in rule.expr.names}))
        return votes

    def observe(self, call: ToolCall, spec: ToolSpec, result: ToolResult) -> Events:
        limit = self._redact.pop(call.id, None)
        out = result.output
        if limit is None or not result.ok or not isinstance(out, dict):
            return []
        rows = out.get("rows")
        if isinstance(rows, list) and len(rows) > limit:
            out["rows"] = rows[:limit]
            out["row_count"] = limit
            out["redacted"] = {"rows_removed": len(rows) - limit, "reason": f"policy max_rows={limit}"}
        return []


class RiskStage:
    name = "risk"

    def __init__(self, session: ShieldSession) -> None:
        self.session = session

    def evaluate(self, call: ToolCall, spec: ToolSpec) -> Decision:
        untrusted = list(self.session.untrusted_calls)
        s = risk.score(call, spec, untrusted)
        if self.session.untrusted_task and spec.side_effect.value in ("write", "external"):
            s.factors.append("task text was flagged as a possible injection")
        return _d(DecisionType.ALLOW, f"Risk {s.level.value}: {'; '.join(s.factors)}.", "risk.score", s.level,
                  self.name, factors=s.factors)


class TaintStage:
    name = "taint"

    def __init__(self, policy: Policy, session: ShieldSession) -> None:
        self.sequences = policy.sequences
        self.session = session
        self._pending: dict[str, list[TaintMatch]] = {}  # transform call id -> matches on its input

    def evaluate(self, call: ToolCall, spec: ToolSpec) -> Decision | None:
        matches = self.session.taint.match(call.args)
        if not matches:
            return None
        if spec.propagates_taint:
            self._pending[call.id] = matches
        # Explain with the most complete path: a match on encode's output beats the same data decoded back.
        matches.sort(key=lambda m: len(m.record.chain), reverse=True)
        hits: list[Decision] = []
        for seq in self.sequences:
            if call.tool not in seq.sinks:
                continue
            for m in matches:
                if not (set(seq.sources) & m.record.labels):
                    continue
                if any(t not in seq.through_transforms for t in m.record.transforms):
                    continue
                chain = [h.to_dict() for h in m.record.chain] + [{"seq": call.seq, "call_id": call.id, "tool": call.tool}]
                path = " -> ".join(f"{h['tool']} (#{h['seq']})" for h in chain)
                labels = ", ".join(sorted(l.value for l in m.record.labels & set(seq.sources)))
                hits.append(_d(seq.on_match,
                               f"{labels} data flows to external sink: {path}. {seq.description}".strip(),
                               seq.id, seq.risk, self.name, chain=chain, match=m.to_dict()))
                break
        if hits:
            return max(hits, key=decision_rank)
        labels = sorted({l.value for m in matches for l in m.record.labels})
        return _d(DecisionType.ALLOW, f"Arguments carry data labelled {labels} (not a sink for any sequence rule).",
                  "taint.carried", RiskLevel.MEDIUM, self.name, matches=[m.to_dict() for m in matches])

    def observe(self, call: ToolCall, spec: ToolSpec, result: ToolResult) -> Events:
        inherited = self._pending.pop(call.id, []) if spec.propagates_taint else []
        record = self.session.taint.label(call, spec, result, inherited)
        if record is None:
            return []
        return [(TraceKind.TAINT_LABELLED, {
            "record": record.id, "tool": call.tool, "call_seq": call.seq,
            "labels": sorted(l.value for l in record.labels),
            "chain": [h.to_dict() for h in record.chain], "preview": record.preview,
        })]


def _recipient_domains(args: dict[str, Any]) -> list[str]:
    out = []
    for key in _RECIPIENT_FIELDS:
        for s in injection.iter_strings(args.get(key)):
            found = _EMAIL.findall(s)
            out += [d.lower() for d in found] or ["<invalid address>"]
    return out


def _domain_allowed(domain: str, allowed: list[str]) -> bool:
    for entry in allowed:
        entry = entry.lower()
        if "." in entry:
            if domain == entry or domain.endswith("." + entry):
                return True
        elif entry in domain.split("."):  # a bare label such as "customer-domain"
            return True
    return False
