"""Tamper-evident audit log: every edit, deletion, reorder or append is detected."""

import pytest
from sqlalchemy import text

from agentguard.gym.runner import run_scenario
from agentguard.gym.scenario import find_scenario


@pytest.fixture
def run_id(store):
    return run_scenario(find_scenario("ticket_prompt_injection"), harness="scripted:naive", store=store).run_id


def _exec(store, sql, **params):
    with store.engine.begin() as conn:
        conn.execute(text(sql), params)


def test_untouched_run_verifies(store, run_id):
    rep = store.verify_audit(run_id)
    assert rep.ok and rep.events == len(store.get_trace(run_id)) and len(rep.head) == 64


@pytest.mark.parametrize("tamper, problem", [
    # change what a decision said (e.g. hide a block)
    ("UPDATE trace_events SET payload = REPLACE(payload, 'BLOCK', 'ALLOW') WHERE run_id = :r AND kind = 'decision'",
     "content does not match"),
    # delete one event from the middle
    ("DELETE FROM trace_events WHERE run_id = :r AND seq = 5", "sequence gap"),
    # drop the tail (truncation)
    ("DELETE FROM trace_events WHERE run_id = :r AND seq > 10", "chain head does not match"),
    # rewrite a timestamp
    ("UPDATE trace_events SET ts = '2020-01-01 00:00:00' WHERE run_id = :r AND seq = 3", "content does not match"),
])
def test_tampering_is_detected(store, run_id, tamper, problem):
    _exec(store, tamper, r=run_id)
    rep = store.verify_audit(run_id)
    assert not rep.ok and problem in rep.problem


def test_recomputing_one_hash_is_not_enough(store, run_id):
    """An attacker who edits an event and fixes its own hash still breaks the next link."""
    from agentguard.core.audit import event_hash
    from agentguard.core.store import TraceEventRow
    from sqlmodel import Session, select

    with Session(store.engine) as s:
        row = s.exec(select(TraceEventRow).where(TraceEventRow.run_id == run_id, TraceEventRow.seq == 4)).one()
        row.payload = {**row.payload, "note": "edited"}
        row.hash = event_hash(row.prev_hash, row.run_id, row.seq, row.kind, row.ts, row.call_id, row.payload)
        s.add(row)
        s.commit()
    rep = store.verify_audit(run_id)
    assert not rep.ok and rep.first_bad_seq == 5 and "chain link" in rep.problem


def test_appending_after_the_run_is_detected(store, run_id):
    from agentguard.core.models import TraceEvent, TraceKind

    n = len(store.get_trace(run_id))
    store.append_event(TraceEvent(run_id=run_id, seq=n + 1, kind=TraceKind.AGENT_OUTPUT, payload={"forged": True}))
    rep = store.verify_audit(run_id)
    assert not rep.ok and "chain head" in rep.problem


def test_old_databases_get_the_columns(tmp_path):
    import sqlite3

    from agentguard.core.store import Store

    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE runs (id VARCHAR PRIMARY KEY, status VARCHAR, world VARCHAR, seed INTEGER, harness VARCHAR,"
                " model VARCHAR, agent_version VARCHAR, scenario_id VARCHAR, config JSON, output JSON,"
                " final_snapshot JSON, verdict JSON, created_at DATETIME, finished_at DATETIME)")
    con.execute("CREATE TABLE trace_events (id INTEGER PRIMARY KEY, run_id VARCHAR, seq INTEGER, kind VARCHAR,"
                " ts DATETIME, call_id VARCHAR, payload JSON)")
    con.commit()
    con.close()
    store = Store(f"sqlite:///{db}")
    r = run_scenario(find_scenario("normal_refund"), harness="scripted:oracle", store=store)
    assert store.verify_audit(r.run_id).ok
