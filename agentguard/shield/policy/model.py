"""Typed policy objects. `loader.load_policy` builds these from YAML."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator

from agentguard.core.models import DataLabel, DecisionType, RiskLevel
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


class Policy(_Strict):
    version: int = 1
    agents: dict[str, AgentPolicy] = Field(default_factory=dict)
    rules: list[Rule] = Field(default_factory=list)
    sequences: list[Sequence] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_ids(self) -> "Policy":
        ids = [r.id for r in self.rules] + [s.id for s in self.sequences]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate rule/sequence ids: {dupes}")
        return self
