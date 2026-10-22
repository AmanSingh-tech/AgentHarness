"""Typed policy objects. `loader.load_policy` builds these from YAML."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator

from agentguard.core.models import DataLabel, DecisionType, RiskLevel, SideEffect
from agentguard.shield.policy.expr import Expr

OnFail = Literal[DecisionType.BLOCK, DecisionType.REQUIRE_APPROVAL]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _compile_patterns(patterns: list[str]) -> list[str]:
    for p in patterns:
        try:
            re.compile(p)
        except re.error as e:
            raise ValueError(f"invalid regex {p!r}: {e}") from None
    return patterns


class ToolPermission(_Strict):
    allow: bool = False
    require_approval: bool = False
    scope: Literal["single_record"] | None = None  # documentation of intent; enforced by the tool's schema
    max_amount_inr: int | None = Field(None, ge=0)
    approval_above_inr: int | None = Field(None, ge=0)
    allowed_domains: list[str] | None = None
    deny_patterns: list[str] = Field(default_factory=list)  # regexes over the JSON-encoded arguments
    max_rows: int | None = Field(None, ge=0)  # result rows above this are redacted

    @field_validator("deny_patterns")
    @classmethod
    def _check_patterns(cls, v: list[str]) -> list[str]:
        return _compile_patterns(v)


class AgentPolicy(_Strict):
    description: str = ""
    tools: dict[str, ToolPermission] = Field(default_factory=dict)


class RuleWhen(_Strict):
    tool: str
    args_match: str | None = None

    @field_validator("args_match")
    @classmethod
    def _check_pattern(cls, v: str | None) -> str | None:
        return v if v is None else _compile_patterns([v])[0]


class Rule(_Strict):
    id: str
    description: str = ""
    when: RuleWhen
    check: str  # must evaluate truthy for the call to proceed
    on_fail: OnFail = DecisionType.BLOCK
    risk: RiskLevel = RiskLevel.HIGH
    message: str | None = None  # reason shown when the check fails; defaults to the description

    _expr: Expr = PrivateAttr()

    @field_validator("check")
    @classmethod
    def _check_expr(cls, v: str) -> str:
        Expr(v)  # ExprError is a ValueError, so it is reported against the `check:` line
        return v

    def model_post_init(self, __context) -> None:
        self._expr = Expr(self.check)

    @property
    def expr(self) -> Expr:
        return self._expr


class Sequence(_Strict):
    id: str
    description: str = ""
    sources: list[DataLabel]
    sinks: list[str]
    through_transforms: list[str] = Field(default_factory=list)  # transforms taint may flow through
    on_match: OnFail = DecisionType.REQUIRE_APPROVAL
    risk: RiskLevel = RiskLevel.CRITICAL


class PatternWhen(_Strict):
    tool: str | None = None
    side_effect: list[SideEffect] | None = None

    @model_validator(mode="after")
    def _one(self) -> "PatternWhen":
        if self.tool is None and not self.side_effect:
            raise ValueError("when: needs a tool or a side_effect list")
        return self


class PriorCall(_Strict):
    """An earlier call that must exist. Argument values starting with `$` are bound to
    the current call's argument of that name, e.g. {order_id: "$order_id"}."""

    tool: str
    ok: bool | None = True  # None: any result
    args: dict[str, Any] = Field(default_factory=dict)


class AfterLabel(_Strict):
    label: DataLabel
    within_calls: int = Field(5, ge=1)


class Rate(_Strict):
    max: int = Field(..., ge=0)
    within_calls: int = Field(..., ge=1)


class Pattern(_Strict):
    """An ordered action-sequence rule over the session's call history. Exactly one of
    `requires_prior`, `after_label` or `rate` must be set."""

    id: str
    description: str = ""
    when: PatternWhen
    requires_prior: list[PriorCall] = Field(default_factory=list)
    after_label: AfterLabel | None = None
    rate: Rate | None = None
    on_match: OnFail = DecisionType.REQUIRE_APPROVAL
    risk: RiskLevel = RiskLevel.HIGH
    message: str | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "Pattern":
        set_ = [n for n, v in (("requires_prior", self.requires_prior), ("after_label", self.after_label),
                               ("rate", self.rate)) if v]
        if len(set_) != 1:
            raise ValueError(f"a pattern needs exactly one of requires_prior, after_label, rate (got {set_ or 'none'})")
        return self


class Policy(_Strict):
    version: int = 1
    agents: dict[str, AgentPolicy] = Field(default_factory=dict)
    rules: list[Rule] = Field(default_factory=list)
    sequences: list[Sequence] = Field(default_factory=list)
    patterns: list[Pattern] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_ids(self) -> "Policy":
        ids = [r.id for r in self.rules] + [s.id for s in self.sequences] + [p.id for p in self.patterns]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate rule/sequence ids: {dupes}")
        return self
