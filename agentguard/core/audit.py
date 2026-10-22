"""Tamper evidence for the audit log.

Every trace event is chained to the previous event of the same run:

    hash_n = sha256(hash_{n-1} || canonical(run_id, seq, kind, ts, call_id, payload))

and the run record stores the head of the chain (last hash and event count) when
the run finishes. Editing, deleting, reordering or appending to a run's stored
events therefore breaks verification, and so does truncating the chain.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

GENESIS = "0" * 64


def canonical_ts(ts: datetime) -> str:
    """Timestamps lose their timezone in some databases: hash them as naive UTC."""
    if ts.tzinfo is not None:
        ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
    return ts.isoformat()


def event_hash(prev: str, run_id: str, seq: int, kind: str, ts: datetime, call_id: str | None,
               payload: dict[str, Any]) -> str:
    body = json.dumps([run_id, seq, kind, canonical_ts(ts), call_id, payload], sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256((prev + body).encode()).hexdigest()


@dataclass
class AuditReport:
    run_id: str
    ok: bool
    events: int
    head: str | None
    problem: str | None = None
    first_bad_seq: int | None = None
