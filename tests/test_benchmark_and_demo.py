"""Agent v2, run-set comparison, the MVP benchmark report and the demo script."""

import json

import pytest

from agentguard.gym.benchmark import benchmark_suite, run_benchmark, to_markdown, write_report
from agentguard.gym.compare import compare, summarise_set
from agentguard.gym.demo import run_demo
from agentguard.gym.runner import run_matrix, run_scenario
from agentguard.gym.scenario import find_scenario
from agentguard.gym.verifier import Outcome


@pytest.mark.parametrize("sid", ["refund_timeout_retry", "refund_false_success", "ticket_prompt_injection",
                                 "stale_order_after_refund"])
def test_v2_fixes_the_v1_failures_without_the_shield(store, sid):
    r = run_scenario(find_scenario(sid), harness="scripted:naive_v2", store=store, shield=False)
    assert r.verdict.outcome == Outcome.CORRECT_SUCCESS, r.verdict.summary


def test_v2_still_misses_identity_checks(store):
    # deliberately imperfect: it does not check who owns the order
    r = run_scenario(find_scenario("wrong_customer_refused"), harness="scripted:naive_v2", store=store, shield=False)
    assert r.verdict.outcome == Outcome.UNSAFE_SIDE_EFFECT
    # the shield catches the unverified-customer case for it
    r = run_scenario(find_scenario("unverified_customer_refused"), harness="scripted:naive_v2", store=store)
    assert r.verdict.outcome == Outcome.CORRECT_FAILURE_REPORTED


def test_compare_run_sets(store):
    suite = [find_scenario(s) for s in ("refund_timeout_retry", "refund_false_success", "normal_refund")]
    run_matrix(suite, ["scripted:naive"], store=store, shield=False, run_set="a")
    run_matrix(suite, ["scripted:naive_v2"], store=store, shield=False, run_set="b")
    rows = {r["metric"]: r for r in compare(store, "a", "b")}
    assert rows["Task success rate"]["a"] == pytest.approx(1 / 3, abs=1e-4) and rows["Task success rate"]["b"] == 1.0
    assert rows["Task success rate"]["better"] is True
    assert rows["Runs with a duplicate refund"]["a"] == 1 and rows["Runs with a duplicate refund"]["better"] is True
    assert rows["Incorrect success claims"]["delta"] == -1
    with pytest.raises(ValueError):
        summarise_set(store, "missing")


def test_benchmark_report(store, tmp_path):
    suite = [find_scenario(s) for s in ("refund_timeout_retry", "normal_refund", "ticket_prompt_injection")]
    report = run_benchmark(store, attempts=2, scenarios=suite, stamp="T1")
    assert set(report["run_sets"]) == {"naive|shield-off|T1", "naive|shield-on|T1",
                                       "naive_v2|shield-off|T1", "naive_v2|shield-on|T1"}
    off, on = report["run_sets"]["naive|shield-off|T1"], report["run_sets"]["naive|shield-on|T1"]
    assert off["headline"]["Runs with a duplicate refund"] == 2 and on["headline"]["Runs with a duplicate refund"] == 0
    assert on["blocks_by_rule"]["no_duplicate_refund"] == 4
    json_path, md_path = write_report(report, tmp_path)
    assert json.loads(json_path.read_text())["attempts"] == 2
    md = md_path.read_text()
    assert "| Runs with a duplicate refund | 2 | 0 |" in md and "no_duplicate_refund x4" in md
    assert all(s.oracle == "scripted:oracle" for s in benchmark_suite())


def test_demo_script(store, tmp_path):
    steps = run_demo(store, regression_dir=tmp_path)
    assert [s.number for s in steps] == [1, 2, 3, 4, 5, 6]
    assert all(s.ok for s in steps), [(s.number, s.runs, s.notes) for s in steps if not s.ok]
    assert any(n.startswith("NEW") for n in steps[5].notes) and list(tmp_path.glob("reg_*.yaml"))
    assert any("HELD, REJECTED" in stop for stop in steps[4].runs[0].stops)
