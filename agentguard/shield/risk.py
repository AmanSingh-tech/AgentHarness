"""Rule-based risk scoring. No ML: every factor is a named, explainable rule."""

from __future__ import annotations

from dataclasses import dataclass

from agentguard.core.models import DataLabel, RiskLevel, SideEffect, ToolCall, ToolSpec

_LEVELS = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]
_BASE = {
    SideEffect.READ: RiskLevel.LOW,
    SideEffect.TRANSFORM: RiskLevel.LOW,
    SideEffect.WRITE: RiskLevel.MEDIUM,
    SideEffect.EXTERNAL: RiskLevel.MEDIUM,
}


@dataclass
class RiskScore:
    level: RiskLevel
    factors: list[str]


def score(call: ToolCall, spec: ToolSpec, untrusted_seen: list[int]) -> RiskScore:
    """`untrusted_seen` are the call numbers whose output was flagged UNTRUSTED earlier in the session."""
    level = _BASE[spec.side_effect]
    factors = [f"{spec.side_effect.value} tool ({level.value})"]

    def at_least(target: RiskLevel, why: str) -> None:
        nonlocal level
        if _LEVELS.index(target) > _LEVELS.index(level):
            level = target
        factors.append(why)

    if spec.irreversible:
        at_least(RiskLevel.HIGH, "irreversible")
    sensitive = {DataLabel.SECRET, DataLabel.PII_BULK} & set(spec.returns_labels)
    if sensitive:
        at_least(RiskLevel.HIGH, f"returns {', '.join(sorted(l.value for l in sensitive))}")
    if untrusted_seen and spec.side_effect in (SideEffect.WRITE, SideEffect.EXTERNAL):
        bumped = _LEVELS[min(_LEVELS.index(level) + 1, len(_LEVELS) - 1)]
        calls = ", ".join(f"#{n}" for n in untrusted_seen)
        at_least(bumped, f"acting after untrusted content (call {calls})")
    return RiskScore(level, factors)
