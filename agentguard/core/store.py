"""Persistence for runs and traces (approvals and scenarios arrive in later milestones).

SQLite by default; only portable column types (JSON, text, ints, timestamps)
are used so the same models work on Postgres.
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, SQLModel, create_engine, select

from agentguard.core.models import (
    AgentOutput,
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


class Store:
    def __init__(self, db_url: str = "sqlite:///agentguard.db") -> None:
        kwargs: dict[str, Any] = {}
        if db_url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
            if db_url in ("sqlite://", "sqlite:///:memory:"):
                kwargs["poolclass"] = StaticPool
        self.engine = create_engine(db_url, **kwargs)
        SQLModel.metadata.create_all(self.engine)
        # SQLite allows one writer at a time and the in-memory DB shares a single
        # connection, so serialise access; parallel runs spend their time in the agent.
        self._lock = threading.RLock()

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
        with self._lock, Session(self.engine) as s:
            s.add(
                TraceEventRow(
                    run_id=event.run_id,
                    seq=event.seq,
                    kind=event.kind.value,
                    ts=event.ts,
                    call_id=event.call_id,
                    payload=event.model_dump(mode="json")["payload"],
                )
            )
            s.commit()

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
