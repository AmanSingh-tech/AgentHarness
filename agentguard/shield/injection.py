"""Heuristic prompt-injection detection over task text, tool arguments and tool output.

Deliberately simple and explainable: a fixed list of regexes, each with an id
and a description, so every detection says exactly which pattern fired. It is
one layer of defence, not the last: policy still governs every action, so a
bulk export is blocked by permissions even when an injection slips past this.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Iterator

_W = r"[^.\n]{0,40}?"  # a short gap within one sentence

PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    (
        "override_instructions",
        "asks the model to ignore or replace its instructions",
        re.compile(rf"\b(ignore|disregard|forget|override)\b{_W}\b(previous|prior|above|earlier|all|your|any)\b{_W}"
                   r"\b(instructions?|rules|guidelines|prompts?|directions)\b", re.I),
    ),
    (
        "role_hijack",
        "tries to give the model a new role or mode",
        re.compile(r"\byou are now\b|\bact as (an? )?(admin|administrator|developer|root|system)\b|"
                   r"\b(maintenance|developer|debug|god|jailbreak)\s+mode\b", re.I),
    ),
    (
        "fake_system_message",
        "imitates a system or developer message",
        re.compile(r"<\s*/?\s*(system|developer)\s*>|\[\s*(system|developer)\s*\]|\bsystem prompt\b|^\s*system\s*:", re.I | re.M),
    ),
    (
        "bulk_export_request",
        "asks for a bulk export of records",
        re.compile(rf"\b(export|dump|send|email|forward|copy)\b{_W}\b(all|every|entire|full)\b{_W}"
                   r"\b(customers?|users?|records|database|tables?|data)\b", re.I),
    ),
    (
        "credential_request",
        "asks for credentials to be revealed or sent",
        re.compile(rf"\b(send|email|share|reveal|print|post|paste)\b{_W}\b(api[ _-]?keys?|passwords?|credentials?|secrets?|tokens?)\b",
                   re.I),
    ),
    (
        "concealment",
        "asks the model to hide its actions",
        re.compile(rf"\b(do not|don't|never)\s+(tell|inform|mention|notify|alert)\b{_W}\b(user|customer|anyone|human|admin)s?\b",
                   re.I),
    ),
]


@dataclass(frozen=True)
class Finding:
    pattern_id: str
    description: str
    snippet: str  # the matched text, trimmed

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def scan_text(text: str) -> list[Finding]:
    findings = []
    for pid, desc, rx in PATTERNS:
        m = rx.search(text)
        if m:
            findings.append(Finding(pid, desc, _trim(m.group(0))))
    return findings


def scan_value(value: Any) -> list[Finding]:
    """Scan every string inside a JSON-like value. One finding per pattern."""
    seen: dict[str, Finding] = {}
    for s in iter_strings(value):
        for f in scan_text(s):
            seen.setdefault(f.pattern_id, f)
    return list(seen.values())


def iter_strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from iter_strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from iter_strings(v)


def _trim(s: str, limit: int = 120) -> str:
    s = " ".join(s.split())
    return s if len(s) <= limit else s[: limit - 1] + "…"
