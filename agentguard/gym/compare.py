"""Compare two sets of runs (e.g. agent v1 vs v2, shield off vs on) metric by metric."""

from __future__ import annotations

from typing import Any

from agentguard.core.models import RunRecord
from agentguard.core.store import Store
from agentguard.gym.metrics import compute_metrics

# Headline outcomes, in the order they are reported. Direction: +1 means higher is better.
HEADLINE: list[tuple[str, str, str, int]] = [
    ("reliability", "task_success_rate", "Task success rate", +1),
    ("reliability", "pass_k", "pass^k (all attempts pass)", +1),
    ("reliability", "failure_recovery_rate", "Recovery from injected faults", +1),
    ("reliability", "duplicate_refund_runs", "Runs with a duplicate refund", -1),
    ("reliability", "incorrect_success_claims", "Incorrect success claims", -1),
    ("reliability", "unsafe_side_effect_runs", "Runs with an unsafe side effect", -1),
    ("security", "exfiltration_attempts_stopped", "Exfiltration attempts stopped", 0),
    ("security", "injected_actions_blocked", "Injected actions blocked", 0),
    ("security", "policy_violations_attempted", "Policy violations attempted", -1),
    ("governance", "blocks_with_explanation", "Blocks with an explanation", +1),
    ("governance", "audit_completeness", "Audit completeness", +1),
]


def runs_in_set(store: Store, run_set: str) -> list[RunRecord]:
    return [r for r in store.list_runs(limit=100_000) if r.config.get("run_set") == run_set and r.verdict]


def summarise_set(store: Store, run_set: str) -> dict[str, Any]:
    runs = runs_in_set(store, run_set)
    if not runs:
        raise ValueError(f"no verified runs in run set '{run_set}'")
    [row] = compute_metrics(store, runs, group_by=())
    return row


def headline(row: dict[str, Any]) -> dict[str, Any]:
    return {label: row[section][key] for section, key, label, _ in HEADLINE}


def compare(store: Store, set_a: str, set_b: str) -> list[dict[str, Any]]:
    a, b = summarise_set(store, set_a), summarise_set(store, set_b)
    out = []
    for section, key, label, direction in HEADLINE:
        va, vb = a[section][key], b[section][key]
        delta = None if va is None or vb is None else round(vb - va, 4)
        better = None if not delta or direction == 0 else (delta * direction > 0)
        out.append({"metric": label, set_a: va, set_b: vb, "delta": delta, "better": better})
    return out
