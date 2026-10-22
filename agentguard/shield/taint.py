"""Sequence-aware data-flow (taint) tracking.

When a tool result carries sensitive labels (SECRET, PII_BULK, ...), its string
values are fingerprinted for the rest of the session:

- normalised substrings: sha256 of every WINDOW-character slice of each value
  (lower-cased, whitespace collapsed), so a fragment of a secret is still caught;
- digests of the raw, base64 and hex forms of each whole value.

A later call's arguments are checked against the fingerprints, both as written
and after decoding any base64/hex-looking tokens in them. How strict the match
is depends on the record:

- secrets and anything that went through a transform: any single fingerprint hit;
- raw bulk data (PII_BULK): values from at least BULK_ROWS distinct rows, so an
  email to one customer is not mistaken for a bulk export.

Transform tools (`ToolSpec.propagates_taint`, e.g. `encode`) pass taint on:
their result becomes a new record that inherits the labels and the chain
(source -> transform -> ...). Only fingerprints are kept, never values in the
trace; evidence shows a masked preview.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Iterator

from agentguard.core.models import DataLabel, ToolCall, ToolResult, ToolSpec, new_id

WINDOW = 10
MIN_VALUE_LEN = 8
BULK_ROWS = 3
_B64_TOKEN = re.compile(r"[A-Za-z0-9+/_-]{12,}={0,2}")
_HEX_TOKEN = re.compile(r"\b(?:[0-9a-fA-F]{2}){8,}\b")
_SPLIT = re.compile(r"[\s\"'`,;()<>\[\]{}|]+")
_NOT_DATA = {DataLabel.UNTRUSTED}  # provenance, not sensitivity


@dataclass(frozen=True)
class Hop:
    seq: int
    call_id: str
    tool: str

    def to_dict(self) -> dict[str, Any]:
        return {"seq": self.seq, "call_id": self.call_id, "tool": self.tool}


@dataclass
class TaintRecord:
    id: str
    labels: frozenset[DataLabel]
    chain: list[Hop]  # source first, then each transform
    windowed: bool
    windows: set[str] = field(default_factory=set)
    digests: set[str] = field(default_factory=set)
    row_values: dict[int, set[str]] = field(default_factory=dict)  # bulk records: row -> normalised values
    preview: str = ""

    @property
    def source(self) -> Hop:
        return self.chain[0]

    @property
    def transforms(self) -> list[str]:
        return [h.tool for h in self.chain[1:]]


@dataclass
class TaintMatch:
    record: TaintRecord
    how: str  # "whole_value" (raw/base64/hex digest) | "substring" (window) | "bulk_rows"
    form: str  # where in the arguments: "raw" | "base64" | "hex"
    rows: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "record": self.record.id,
            "labels": sorted(l.value for l in self.record.labels),
            "chain": [h.to_dict() for h in self.record.chain],
            "how": self.how,
            "form": self.form,
            **({"rows": self.rows} if self.rows else {}),
            "preview": self.record.preview,
        }


class TaintTracker:
    def __init__(self) -> None:
        self.records: list[TaintRecord] = []

    def label(
        self, call: ToolCall, spec: ToolSpec, result: ToolResult, inherited: list[TaintMatch] | None = None
    ) -> TaintRecord | None:
        """Fingerprint a result. `inherited` are the matches on a transform's arguments."""
        inherited = inherited or []
        labels = {l for l in result.labels if l not in _NOT_DATA}
        for m in inherited:
            labels |= m.record.labels
        if not labels or not result.ok:
            return None

        arg_values = {_norm(s) for s in _strings(call.args)}
        hop = Hop(call.seq, call.id, call.tool)
        parent = inherited[0].record if inherited else None
        record = TaintRecord(
            id=new_id("taint"),
            labels=frozenset(labels),
            chain=(parent.chain if parent else []) + [hop],
            windowed=DataLabel.SECRET in labels or parent is not None,
        )
        for row, raw in _leaves(result.output):
            value = _norm(raw)
            if len(value) < MIN_VALUE_LEN or value in arg_values:
                continue  # too short to be meaningful, or the agent already knew it
            record.digests |= {_h(value), _h(_b64(raw)), _h(raw.encode().hex())}
            if record.windowed:
                record.windows |= {_h(value[i:i + WINDOW]) for i in range(max(1, len(value) - WINDOW + 1))}
            record.row_values.setdefault(row, set()).add(value)
            if not record.preview:
                record.preview = _mask(raw)
        if not record.digests:
            return None
        self.records.append(record)
        return record

    def match(self, args: dict[str, Any]) -> list[TaintMatch]:
        candidates = list(_candidates(args))
        matches = []
        for record in self.records:
            m = self._match_record(record, candidates)
            if m is not None:
                matches.append(m)
        return matches

    def _match_record(self, record: TaintRecord, candidates: list[tuple[str, str]]) -> TaintMatch | None:
        for form, text in candidates:
            if not record.windowed:
                break  # raw bulk data only counts across several rows (below)
            tokens = {d for t in _SPLIT.split(text) if t for d in (_h(t), _h(_norm(t)))}
            if tokens & record.digests:
                return TaintMatch(record, "whole_value", form)
            norm = _norm(text)
            if len(norm) >= WINDOW:
                if any(_h(norm[i:i + WINDOW]) in record.windows for i in range(len(norm) - WINDOW + 1)):
                    return TaintMatch(record, "substring", form)
        if not record.windowed:
            for form, text in candidates:
                norm = _norm(text)
                rows = sum(1 for values in record.row_values.values() if any(v in norm for v in values))
                if rows >= BULK_ROWS:
                    return TaintMatch(record, "bulk_rows", form, rows=rows)
        return None


# -- helpers -----------------------------------------------------------------


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:20]


def _b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


def _mask(s: str) -> str:
    s = " ".join(s.split())
    return s[:4] + "…" + f"({len(s)} chars)" if len(s) > 4 else "…"


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _strings(v)


def _leaves(output: Any) -> Iterator[tuple[int, str]]:
    """(row, string) for every string in the output; row is the index in the
    first list encountered, or -1 outside any list."""

    def walk(v: Any, row: int) -> Iterator[tuple[int, str]]:
        if isinstance(v, str):
            yield row, v
        elif isinstance(v, dict):
            for x in v.values():
                yield from walk(x, row)
        elif isinstance(v, (list, tuple)):
            for i, x in enumerate(v):
                yield from walk(x, i if row == -1 else row)

    yield from walk(output, -1)


def _candidates(args: dict[str, Any]) -> Iterator[tuple[str, str]]:
    """Every argument string as written, plus decodings of base64/hex-looking tokens."""
    for s in _strings(args):
        yield "raw", s
        for tok in _HEX_TOKEN.findall(s):
            try:
                yield "hex", bytes.fromhex(tok).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                pass
        for tok in _B64_TOKEN.findall(s):
            decoded = _try_b64(tok)
            if decoded is not None:
                yield "base64", decoded


def _try_b64(tok: str) -> str | None:
    for altchars in (None, b"-_"):
        padded = tok + "=" * (-len(tok) % 4)
        try:
            raw = base64.b64decode(padded, altchars=altchars, validate=True)
            text = raw.decode("utf-8")
        except (binascii.Error, ValueError, UnicodeDecodeError):
            continue
        if text and sum(c.isprintable() for c in text) / len(text) > 0.9:
            return text
    return None
