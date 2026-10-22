import asyncio

from agentguard.core.config import Settings, load_dotenv
from agentguard.core.events import EventBus, Tracer
from agentguard.core.models import AgentOutput, RunRecord, RunStatus, TraceKind
from agentguard.core.tooling import EXPORTERS, validate_args
from agentguard.world.support.tools import SUPPORT_TOOLS

REFUND = next(t for t in SUPPORT_TOOLS if t.name == "issue_refund")
TICKET = next(t for t in SUPPORT_TOOLS if t.name == "update_ticket")


def test_exporters_cover_every_tool():
    for name, export in EXPORTERS.items():
        for spec in SUPPORT_TOOLS:
            out = export(spec)
            assert spec.name in str(out), name
    assert EXPORTERS["anthropic"](REFUND)["input_schema"]["required"] == ["order_id", "amount_inr", "idempotency_key"]
    assert EXPORTERS["openai"](REFUND)["function"]["parameters"] == REFUND.input_schema


def test_validate_args():
    assert validate_args(REFUND, {"order_id": "O", "amount_inr": 5, "idempotency_key": "k"}) == []
    problems = validate_args(REFUND, {"order_id": 1, "amount_inr": True, "extra": 1})
    text = " ".join(problems)
    assert "missing required argument 'idempotency_key'" in text
    assert "'order_id' must be string" in text
    assert "'amount_inr' must be integer, got boolean" in text
    assert "unknown argument 'extra'" in text
    assert "must be >= 1" in " ".join(validate_args(REFUND, {"order_id": "O", "amount_inr": 0, "idempotency_key": "k"}))
    assert "must be one of" in " ".join(validate_args(TICKET, {"ticket_id": "T", "status": "closed"}))
    assert validate_args(TICKET, ["not", "a", "dict"])  # type: ignore[arg-type]


def test_tracer_seq_and_bus_filtering():
    bus = EventBus()
    seen_all, seen_a = [], []
    bus.subscribe(seen_all.append)
    unsub = bus.subscribe(seen_a.append, run_id="a")
    Tracer(bus, "a").emit(TraceKind.RUN_STARTED)
    tb = Tracer(bus, "b")
    tb.emit(TraceKind.RUN_STARTED)
    ev = tb.emit(TraceKind.RUN_FINISHED, ok=True)
    assert ev.seq == 2 and ev.payload == {"ok": True}
    assert len(seen_all) == 3 and len(seen_a) == 1
    unsub()
    unsub()  # idempotent
    Tracer(bus, "a").emit(TraceKind.RUN_STARTED)
    assert len(seen_a) == 1


def test_bus_async_queue_fanout():
    async def main():
        bus = EventBus()
        q = bus.queue("r1", maxsize=1)
        t = Tracer(bus, "r1")
        t.emit(TraceKind.RUN_STARTED)
        t.emit(TraceKind.RUN_FINISHED)  # dropped: queue full, must not raise
        await asyncio.sleep(0)
        assert q.qsize() == 1
        assert (await q.get()).kind == TraceKind.RUN_STARTED

    asyncio.run(main())


def test_store_roundtrip(store):
    store.create_run(RunRecord(id="r1", status=RunStatus.RUNNING, world="support", seed=1, harness="scripted:null"))
    assert store.get_run("r1").output is None
    store.finish_run("r1", RunStatus.FINISHED, AgentOutput(final_message="x", exit_reason="completed"), {"a": 1})
    rec = store.get_run("r1")
    assert rec.status == RunStatus.FINISHED and rec.output.final_message == "x" and rec.final_snapshot == {"a": 1}
    assert rec.finished_at is not None
    assert [r.id for r in store.list_runs()] == ["r1"]
    assert store.get_run("missing") is None
    try:
        store.finish_run("missing", RunStatus.FINISHED, None, None)
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError")


def test_file_store(tmp_path):
    from agentguard.core.store import Store

    s = Store(f"sqlite:///{tmp_path / 'ag.db'}")
    s.create_run(RunRecord(id="r", status=RunStatus.RUNNING, world="support", seed=1, harness="h"))
    assert Store(f"sqlite:///{tmp_path / 'ag.db'}").get_run("r") is not None


def test_settings_from_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AGENTGUARD_DB_URL", raising=False)
    (tmp_path / ".env").write_text("# comment\nAGENTGUARD_DB_URL='sqlite:///x.db'\nbadline\n")
    assert Settings.from_env().db_url == "sqlite:///x.db"
    monkeypatch.setenv("AGENTGUARD_DB_URL", "sqlite:///y.db")
    load_dotenv(tmp_path / ".env")  # existing env wins
    assert Settings.from_env().db_url == "sqlite:///y.db"
    load_dotenv(tmp_path / "missing.env")
