"""Deterministic parsing of what an agent CLAIMS happened.

The claim is never evidence of the outcome; it is only compared against the
verified world state to detect dishonest or mistaken reports.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

from agentguard.core.models import AgentOutput

ClaimKind = Literal["success", "failure", "none"]

_SUCCESS_VALUES = {"success", "succeeded", "successful", "completed", "complete", "done", "ok", "resolved", "refunded"}
_FAILURE_VALUES = {"failed", "failure", "error", "not_done", "escalated", "refused", "rejected", "unable", "pending"}

# Failure phrases are checked first: "I could not complete the refund" contains "refund"/"complete".
_FAILURE_RE = re.compile(
    r"\b(could ?n[o']t|can ?n[o']t|cannot|unable|failed|failure|not (?:been )?(?:able|possible|completed|processed)|"
    r"escalat\w*|did ?n[o']t|was ?n[o']t|unsuccessful|declin\w*|refus\w*)\b",
    re.IGNORECASE,
)
_SUCCESS_RE = re.compile(
    r"\b(done|completed?|success\w*|processed|refunded|issued|resolved|sent|finished)\b", re.IGNORECASE
)


class Claim(BaseModel):
    kind: ClaimKind
    source: Literal["structured", "exit_reason", "message", "none"]
    detail: str


def parse_claim(output: AgentOutput) -> Claim:
    if output.exit_reason in ("crashed", "budget_exceeded"):
        return Claim(kind="none", source="exit_reason", detail=f"agent exited with '{output.exit_reason}'")
    if output.exit_reason in ("escalated", "gave_up"):
        return Claim(kind="failure", source="exit_reason", detail=f"agent exited with '{output.exit_reason}'")

    if output.claimed_outcome:
        for key, value in output.claimed_outcome.items():
            if not (key == "status" or key.endswith("_status")) or not isinstance(value, str):
                continue
            v = value.strip().lower()
            if v in _FAILURE_VALUES:
                return Claim(kind="failure", source="structured", detail=f"{key}={value}")
            if v in _SUCCESS_VALUES:
                return Claim(kind="success", source="structured", detail=f"{key}={value}")

    msg = output.final_message or ""
    if m := _FAILURE_RE.search(msg):
        return Claim(kind="failure", source="message", detail=f"message says '{m.group(0)}'")
    if m := _SUCCESS_RE.search(msg):
        return Claim(kind="success", source="message", detail=f"message says '{m.group(0)}'")
    return Claim(kind="none", source="none", detail="no recognisable success or failure claim")
