"""Evidence reports: built from the stored run, deterministic, and served by the CLI and the API."""

import json

import pytest
from sqlmodel import Session, select

from agentguard.core.store import TraceEventRow
from agentguard.governance.evidence import build_evidence, evidence_markdown
from agentguard.gym.runner import run_scenario
from agentguard.gym.scenario import find_scenario
from agentguard.shield.approvals import ApprovalQueue, AutoApprover


@pytest.fixture
def refund_run(store):
    queue = ApprovalQueue(store, auto=AutoApprover(default="approve"), timeout_s=60)
    return run_scenario(find_scenario("refund_ops_inbox"), harness="ops:refunds", store=store, shield=True,
                        run_set="ops", approvals=queue).run_id


def test_refundops_evidence_lists_every_control(store, refund_run):
    ev = build_evidence(store, refund_run)
    assert {a["agent"] for a in ev["agents"]} == {"intake_agent", "decision_agent", "action_agent", "reporting_agent"}
    assert [(a["tool"], a["status"]) for a in ev["approvals"]] == [("issue_refund", "approved")]
    assert ev["approvals"][0]["args"]["amount_inr"] == 4500
    assert len(ev["injections"]) == 1 and ev["injections"][0]["tool"] == "get_ticket"
    assert [v["passed"] for v in ev["verifications"]] == [True, True]
    assert ev["claim_vs_outcome"]["verdict"] == "CORRECT_SUCCESS"
    assert ev["audit"]["ok"] and ev["audit"]["events"] == ev["controls"]["audit_events"]
    assert len(ev["tool_calls"]) == ev["controls"]["tool_calls"]

    md = evidence_markdown(ev)
    for text in ("## Human approvals", "₹4,500 is above action_agent's approval threshold", "| approved |",
                 "## Prompt injections detected", "ledger.refund_key_exists", "CORRECT_SUCCESS",
                 "Audit chain **verified**", "EU AI Act Art. 14"):
        assert text in md, text


def test_evidence_is_deterministic(store, refund_run):
    assert evidence_markdown(build_evidence(store, refund_run)) == evidence_markdown(build_evidence(store, refund_run))
    json.dumps(build_evidence(store, refund_run))  # JSON-able as returned


def test_evidence_shows_blocks_and_a_broken_chain(store):
    run_id = run_scenario(find_scenario("secret_exfiltration"), harness="scripted:adversarial", store=store,
                          shield=True).run_id
    ev = build_evidence(store, run_id)
    assert "secret_exfiltration" in {b["rule"] for b in ev["blocks"]}
    assert "## Actions blocked by policy" in evidence_markdown(ev)

    with Session(store.engine) as s:  # tamper with one stored event
        row = s.exec(select(TraceEventRow).where(TraceEventRow.run_id == run_id, TraceEventRow.seq == 2)).one()
        row.payload = {**row.payload, "tampered": True}
        s.add(row)
        s.commit()
    md = evidence_markdown(build_evidence(store, run_id))
    assert "Audit chain **FAILED**" in md and "event #2" in md


def test_unknown_run(store):
    with pytest.raises(KeyError):
        build_evidence(store, "run_missing")


def test_evidence_endpoint(store, refund_run, tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from agentguard.server.app import create_app

    with TestClient(create_app(store, reports_dir=tmp_path)) as c:
        assert c.get(f"/api/runs/{refund_run}/evidence").json()["run"]["id"] == refund_run
        r = c.get(f"/api/runs/{refund_run}/evidence?format=md")
        assert r.headers["content-type"].startswith("text/markdown") and r.text.startswith("# Evidence report")
        assert c.get("/api/runs/run_missing/evidence").status_code == 404


def test_audit_report_cli(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from agentguard.cli.main import app
    from agentguard.core.store import Store

    db = f"sqlite:///{tmp_path / 'ag.db'}"
    monkeypatch.setenv("AGENTGUARD_DB_URL", db)
    run_id = run_scenario(find_scenario("normal_refund"), harness="scripted:oracle", store=Store(db), shield=True).run_id
    out = tmp_path / "evidence.md"
    r = CliRunner().invoke(app, ["audit", "report", run_id, "--out", str(out)])
    assert r.exit_code == 0, r.output
    assert out.read_text().startswith(f"# Evidence report: {run_id}")
    r = CliRunner().invoke(app, ["audit", "report", run_id, "--format", "json"])
    assert json.loads(r.output)["audit"]["ok"] is True
