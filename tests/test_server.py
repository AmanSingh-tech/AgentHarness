"""API server: runs, live trace (SSE), manual approvals, blocks, promotion, metrics, policies."""

import json
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from agentguard.server.app import create_app  # noqa: E402


@pytest.fixture
def client(store, tmp_path):
    with TestClient(create_app(store, reports_dir=tmp_path, approval_timeout_s=10)) as c:
        yield c


def _wait(client, run_id, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = client.get(f"/api/runs/{run_id}").json()
        if r["verdict"] is not None:
            return r
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} did not finish")


def _start(client, **body):
    r = client.post("/api/runs", json=body)
    assert r.status_code == 202, r.text
    return r.json()["run_id"]


def test_catalogue_endpoints(client):
    ids = {s["id"] for s in client.get("/api/scenarios").json()}
    assert {"normal_refund", "secret_exfiltration"} <= ids
    assert "mcp_client:claude-code" in client.get("/api/harnesses").json()
    pol = client.get("/api/policies").json()
    assert "no_duplicate_refund" in pol["rules"] and "refund_without_verification" in pol["patterns"]
    assert client.post("/api/policies/validate", json={"text": pol["text"]}).json()["ok"] is True
    bad = client.post("/api/policies/validate", json={"text": "agents:\n  a:\n    tools:\n      x: {nope: 1}\n"}).json()
    assert not bad["ok"] and "line 4" in bad["problems"][0]
    assert client.post("/api/runs", json={"scenario": "nope"}).status_code == 400
    assert client.get("/api/runs/run_nope").status_code == 404


def test_run_trace_and_stream(client):
    run_id = _start(client, scenario="normal_refund", harness="scripted:oracle", run_set="s1")
    run = _wait(client, run_id)
    assert run["outcome"] == "CORRECT_SUCCESS" and run["passed"] and run["run_set"] == "s1"
    trace = client.get(f"/api/runs/{run_id}/trace").json()
    assert trace[0]["kind"] == "run_started" and trace[-1]["kind"] == "run_finished"

    with client.stream("GET", f"/api/runs/{run_id}/stream") as resp:
        body = "".join(resp.iter_text())
    events = [json.loads(line[5:]) for line in body.splitlines() if line.startswith("data:") and line[5:].strip() != "{}"]
    assert [e["seq"] for e in events] == [e["seq"] for e in trace]
    assert "event: done" in body

    assert client.get("/api/runs", params={"run_set": "s1"}).json()[0]["id"] == run_id
    assert {"name": "s1", "runs": 1} in client.get("/api/run-sets").json()


def test_manual_approval_waits_for_a_click(client):
    run_id = _start(client, scenario="normal_refund", harness="scripted:oracle", manual_approvals=True)
    deadline = time.monotonic() + 10
    pending = []
    while not pending and time.monotonic() < deadline:
        pending = client.get("/api/approvals").json()
        time.sleep(0.05)
    [a] = pending
    assert a["tool"] == "issue_refund" and a["run_id"] == run_id and "approval threshold" in a["decision"]["reason"]
    assert client.get(f"/api/runs/{run_id}").json()["status"] == "running"  # really waiting

    r = client.post(f"/api/approvals/{a['id']}/approve", json={"by": "human:alex", "note": "looks right"})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert _wait(client, run_id)["outcome"] == "CORRECT_SUCCESS"
    assert client.post(f"/api/approvals/{a['id']}/approve").status_code == 409
    assert client.post("/api/approvals/appr_nope/reject").status_code == 404
    assert client.get("/api/approvals", params={"status": "approved"}).json()[-1]["resolved_by"] == "human:alex"

    # rejecting: the refund never happens and the oracle escalates honestly
    run_id = _start(client, scenario="normal_refund", harness="scripted:oracle", manual_approvals=True)
    while not (pending := client.get("/api/approvals").json()):
        time.sleep(0.05)
    client.post(f"/api/approvals/{pending[0]['id']}/reject")
    assert _wait(client, run_id)["outcome"] == "CORRECT_FAILURE_REPORTED"


def test_blocks_promotion_and_diagnosis(client, monkeypatch, tmp_path):
    import agentguard.gym.regression as reg

    monkeypatch.setattr(reg, "REGRESSION_DIR", tmp_path / "regression")
    run_id = _start(client, scenario="secret_exfiltration", harness="scripted:adversarial")
    _wait(client, run_id)
    blocks = [b for b in client.get("/api/blocks").json() if b["run_id"] == run_id]
    seq = next(b for b in blocks if b["rule_id"] == "secret_exfiltration")
    assert seq["type"] == "BLOCK" and [h["tool"] for h in seq["evidence"]["chain"]] == ["read_secret", "encode", "send_email"]
    held = next(b for b in blocks if b["rule_id"] == "bulk_pii_exfiltration")
    assert held["approval"] == {"status": "rejected", "by": "auto:rule[0]"}

    d = client.get(f"/api/runs/{run_id}/diagnosis").json()
    assert len(d["summary"]) == 3
    p = client.post(f"/api/runs/{run_id}/promote").json()
    assert p["accepted"] and p["scenario_id"].startswith("reg_secret_exfiltration") and "forbidden" in p["yaml"]


def test_metrics_and_compare(client):
    for harness, rs in (("scripted:naive", "v1"), ("scripted:naive_v2", "v2")):
        _wait(client, _start(client, scenario="refund_false_success", harness=harness, run_set=rs, shield=False))
    rows = {r["metric"]: r for r in client.get("/api/compare", params={"a": "v1", "b": "v2"}).json()}
    assert rows["Incorrect success claims"]["v1"] == 1 and rows["Incorrect success claims"]["v2"] == 0
    assert client.get("/api/compare", params={"a": "v1", "b": "zzz"}).status_code == 404
    groups = client.get("/api/metrics", params={"group_by": "harness"}).json()
    assert {g["group"]["harness"] for g in groups} >= {"scripted:naive", "scripted:naive_v2"}
    assert client.get("/api/metrics", params={"group_by": "colour"}).status_code == 400


def test_jobs(client, monkeypatch):
    import agentguard.gym.demo as demo

    def fake_demo(store, on_step=None, **kw):
        on_step(demo.DemoStep(1, "t", "e"))
        return []

    monkeypatch.setattr(demo, "run_demo", fake_demo)
    job = client.post("/api/demo").json()["job_id"]
    deadline = time.monotonic() + 5
    while client.get(f"/api/jobs/{job}").json()["status"] == "running" and time.monotonic() < deadline:
        time.sleep(0.05)
    j = client.get(f"/api/jobs/{job}").json()
    assert j["status"] == "done" and j["steps"][0]["title"] == "t"
    assert client.get("/api/jobs/nope").status_code == 404
    assert client.get("/api/benchmarks").json() == []


def test_refund_ops_with_a_human_approval(client):
    run_id = client.post("/api/ops/refunds", json={"manual_approvals": True}).json()["run_id"]
    deadline = time.monotonic() + 15
    while not (pending := client.get("/api/approvals").json()) and time.monotonic() < deadline:
        time.sleep(0.05)
    [a] = pending
    assert a["agent_id"] == "action_agent" and a["args"]["order_id"] == "O-9102"
    client.post(f"/api/approvals/{a['id']}/approve", json={"by": "human:judge"})
    run = _wait(client, run_id)
    assert run["outcome"] == "CORRECT_SUCCESS"
    report = run["output"]["artifacts"]["report"]
    assert report["summary"]["refunded_inr_verified"] == 6000
    c = client.get(f"/api/runs/{run_id}/controls").json()
    assert c["approvals"][0]["by"] == "human:judge" and c["audit_ok"]


def test_ops_with_the_claude_decider(client, monkeypatch, tmp_path):
    assert client.post("/api/ops/refunds", json={"decider": "magic"}).status_code == 400
    monkeypatch.setenv("AGENTGUARD_CLAUDE_BIN", str(tmp_path / "no-such-claude"))
    run_id = client.post("/api/ops/access", json={"manual_approvals": False, "decider": "claude",
                                                  "model": "haiku"}).json()["run_id"]
    run = _wait(client, run_id)
    assert run["outcome"] == "CORRECT_SUCCESS"  # the rules took over, and the report says why
    log = run["output"]["artifacts"]["report"]["decision_making"]
    assert log["decider"] == "claude:haiku" and "could not be started" in log["fallback"]


def test_showcase_site_is_served(client):
    page = client.get("/site/")
    assert page.status_code == 200 and "AgentGuard" in page.text and "Run it yourself" in page.text
    data = client.get("/site/data.js")
    assert data.status_code == 200 and "CORRECT_SUCCESS" in data.text
