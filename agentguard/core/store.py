"""Persistence for runs, traces and approvals (scenarios arrive in a later milestone).

SQLite by default; only portable column types (JSON, text, ints, timestamps)
are used so the same models work on Postgres.
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column, UniqueConstraint, inspect, text
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, SQLModel, create_engine, select

from agentguard.core.audit import GENESIS, AuditReport, event_hash
from agentguard.core.models import (
    AgentOutput,
    Approval,
    ApprovalStatus,
    RunRecord,
    RunStatus,
    TraceEvent,
    TraceKind,
    utcnow,
)


class RunRow(SQLModel, table=True):
    __tablename__ = "runs"

    id: str = Field(primary_key=True)
    status: str
    world: str
    seed: int
    harness: str = Field(index=True)
    model: str | None = Field(default=None, index=True)
    agent_version: str | None = Field(default=None, index=True)
    scenario_id: str | None = Field(default=None, index=True)
    config: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    output: dict | None = Field(default=None, sa_column=Column(JSON))
    final_snapshot: dict | None = Field(default=None, sa_column=Column(JSON))
    verdict: dict | None = Field(default=None, sa_column=Column(JSON))
    audit_head: str | None = None  # hash of the last trace event when the run finished
    audit_count: int | None = None
    created_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None


class TraceEventRow(SQLModel, table=True):
    __tablename__ = "trace_events"
    __table_args__ = (UniqueConstraint("run_id", "seq"),)

    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(index=True)
    seq: int
    kind: str
    ts: datetime
    call_id: str | None = None
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    prev_hash: str | None = None
    hash: str | None = None


class ApprovalRow(SQLModel, table=True):
    __tablename__ = "approvals"

    id: str = Field(primary_key=True)
    run_id: str = Field(index=True)
    call_id: str
    agent_id: str
    tool: str
    status: str = Field(index=True)
    data: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))  # the full Approval
    created_at: datetime
    resolved_at: datetime | None = None


class Store:
    def __init__(self, db_url: str = "sqlite:///agentguard.db") -> None:
        kwargs: dict[str, Any] = {}
        if db_url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
            if db_url in ("sqlite://", "sqlite:///:memory:"):
                kwargs["poolclass"] = StaticPool
        self.engine = create_engine(db_url, **kwargs)
        SQLModel.metadata.create_all(self.engine)
        self._add_missing_columns()
        # SQLite allows one writer at a time and the in-memory DB shares a single
        # connection, so serialise access; parallel runs spend their time in the agent.
        self._lock = threading.RLock()
        self._heads: dict[str, str] = {}  # run id -> last event hash, for appends

    def _add_missing_columns(self) -> None:
        """Databases created by earlier versions lack the audit columns: add them (nullable)."""
        wanted = {"runs": {"audit_head": "VARCHAR", "audit_count": "INTEGER"},
                  "trace_events": {"prev_hash": "VARCHAR", "hash": "VARCHAR"}}
        insp = inspect(self.engine)
        with self.engine.begin() as conn:
            for table, cols in wanted.items():
                have = {c["name"] for c in insp.get_columns(table)}
                for name, type_ in cols.items():
                    if name not in have:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {type_}"))

    @classmethod
    def in_memory(cls) -> "Store":
        return cls("sqlite://")

    # -- runs ---------------------------------------------------------------

    def create_run(self, record: RunRecord) -> None:
        with self._lock, Session(self.engine) as s:
            s.add(RunRow(**_run_to_row(record)))
            s.commit()

    def finish_run(
        self,
        run_id: str,
        status: RunStatus,
        output: AgentOutput | None,
        final_snapshot: dict[str, Any] | None,
    ) -> None:
        with self._lock, Session(self.engine) as s:
            row = s.get(RunRow, run_id)
            if row is None:
                raise KeyError(run_id)
            row.status = status.value
            row.output = output.model_dump(mode="json") if output else None
            row.final_snapshot = final_snapshot
            row.finished_at = utcnow()
            row.audit_head = self._head(s, run_id)
            row.audit_count = len(s.exec(select(TraceEventRow.id).where(TraceEventRow.run_id == run_id)).all())
            s.add(row)
            s.commit()

    def set_verdict(self, run_id: str, verdict: dict[str, Any]) -> None:
        with self._lock, Session(self.engine) as s:
            row = s.get(RunRow, run_id)
            if row is None:
                raise KeyError(run_id)
            row.verdict = verdict
            s.add(row)
            s.commit()

    def get_run(self, run_id: str) -> RunRecord | None:
        with self._lock, Session(self.engine) as s:
            row = s.get(RunRow, run_id)
            return _row_to_run(row) if row else None

    def list_runs(self, limit: int = 100) -> list[RunRecord]:
        with self._lock, Session(self.engine) as s:
            rows = s.exec(select(RunRow).order_by(RunRow.created_at.desc()).limit(limit)).all()
            return [_row_to_run(r) for r in rows]

    # -- traces -------------------------------------------------------------

    def append_event(self, event: TraceEvent) -> None:
        payload = event.model_dump(mode="json")["payload"]
        with self._lock, Session(self.engine) as s:
            prev = self._heads.get(event.run_id) or self._head(s, event.run_id) or GENESIS
            digest = event_hash(prev, event.run_id, event.seq, event.kind.value, event.ts, event.call_id, payload)
            s.add(
                TraceEventRow(
                    run_id=event.run_id,
                    seq=event.seq,
                    kind=event.kind.value,
                    ts=event.ts,
                    call_id=event.call_id,
                    payload=payload,
                    prev_hash=prev,
                    hash=digest,
                )
            )
            s.commit()
            self._heads[event.run_id] = digest

    def _head(self, s: Session, run_id: str) -> str | None:
        row = s.exec(select(TraceEventRow).where(TraceEventRow.run_id == run_id)
                     .order_by(TraceEventRow.seq.desc()).limit(1)).first()
        return row.hash if row else None

    def verify_audit(self, run_id: str) -> AuditReport:
        """Recompute the run's hash chain from the stored events and compare it with the
        head recorded when the run finished."""
        with self._lock, Session(self.engine) as s:
            run = s.get(RunRow, run_id)
            if run is None:
                raise KeyError(run_id)
            rows = s.exec(select(TraceEventRow).where(TraceEventRow.run_id == run_id)
                          .order_by(TraceEventRow.seq)).all()
        prev = GENESIS
        for i, r in enumerate(rows, start=1):
            if r.hash is None:
                return AuditReport(run_id, False, len(rows), None, "event has no hash (written before auditing existed)", r.seq)
            if r.seq != i:
                return AuditReport(run_id, False, len(rows), None, f"sequence gap: expected #{i}, found #{r.seq}", r.seq)
            if r.prev_hash != prev:
                return AuditReport(run_id, False, len(rows), None, "chain link does not match the previous event", r.seq)
            if event_hash(prev, r.run_id, r.seq, r.kind, r.ts, r.call_id, r.payload) != r.hash:
                return AuditReport(run_id, False, len(rows), None, "event content does not match its hash", r.seq)
            prev = r.hash
        head = prev if rows else None
        if run.audit_head is None:
            ok = run.finished_at is None  # still running: nothing to compare yet
            return AuditReport(run_id, ok, len(rows), head, None if ok else "run has no recorded audit head")
        if run.audit_count != len(rows) or run.audit_head != head:
            return AuditReport(run_id, False, len(rows), head,
                               f"chain head does not match the run record ({run.audit_count} events recorded, {len(rows)} found)")
        return AuditReport(run_id, True, len(rows), head)

    def get_trace(self, run_id: str) -> list[TraceEvent]:
        with self._lock, Session(self.engine) as s:
            rows = s.exec(
                select(TraceEventRow).where(TraceEventRow.run_id == run_id).order_by(TraceEventRow.seq)
            ).all()
            return [
                TraceEvent(
                    run_id=r.run_id, seq=r.seq, kind=TraceKind(r.kind), ts=r.ts, call_id=r.call_id, payload=r.payload
                )
                for r in rows
            ]


    # -- approvals ----------------------------------------------------------

    def save_approval(self, approval: Approval) -> None:
        with self._lock, Session(self.engine) as s:
            row = s.get(ApprovalRow, approval.id) or ApprovalRow(
                id=approval.id, run_id=approval.run_id, call_id=approval.call_id, agent_id=approval.agent_id,
                tool=approval.tool, status=approval.status.value, created_at=approval.created_at,
            )
            row.status = approval.status.value
            row.data = approval.model_dump(mode="json")
            row.resolved_at = approval.resolved_at
            s.add(row)
            s.commit()

    def get_approval(self, approval_id: str) -> Approval | None:
        with self._lock, Session(self.engine) as s:
            row = s.get(ApprovalRow, approval_id)
            return Approval.model_validate(row.data) if row else None

    def list_approvals(self, status: ApprovalStatus | None = None, run_id: str | None = None) -> list[Approval]:
        with self._lock, Session(self.engine) as s:
            q = select(ApprovalRow).order_by(ApprovalRow.created_at)
            if status is not None:
                q = q.where(ApprovalRow.status == status.value)
            if run_id is not None:
                q = q.where(ApprovalRow.run_id == run_id)
            return [Approval.model_validate(r.data) for r in s.exec(q).all()]


def _run_to_row(record: RunRecord) -> dict[str, Any]:
    data = record.model_dump(mode="json")
    data["created_at"] = record.created_at
    data["finished_at"] = record.finished_at
    return data


def _row_to_run(row: RunRow) -> RunRecord:
    return RunRecord(
        id=row.id,
        status=RunStatus(row.status),
        world=row.world,
        seed=row.seed,
        harness=row.harness,
        model=row.model,
        agent_version=row.agent_version,
        scenario_id=row.scenario_id,
        config=row.config,
        output=AgentOutput.model_validate(row.output) if row.output else None,
        final_snapshot=row.final_snapshot,
        verdict=row.verdict,
        created_at=row.created_at,
        finished_at=row.finished_at,
    )
