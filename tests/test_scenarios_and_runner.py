import pytest

from agentguard.gym.runner import run_matrix, run_scenario, validate_scenarios
from agentguard.gym.scenario import SCENARIOS_DIR, FaultType, Scenario, find_scenario, load_scenarios
from agentguard.gym.verifier import Outcome
from agentguard.harnesses.base import register
from agentguard.harnesses.scripted import ScriptedHarness

MINIMAL = "id: {id}\ntask: t\nexpected: {{}}\n"


def test_builtin_suite_loads():
    scenarios = load_scenarios()
    assert len(scenarios) >= 10
    assert [s.id for s in scenarios] == sorted(s.id for s in scenarios)
    s = find_scenario("normal_refund")
    assert s.task_spec.params["order_id"] == "O-9001"
    assert s.fixture_path().name == "support_basic.yaml"
    assert find_scenario(str(s.source_path)).id == "normal_refund"


def test_scenario_validation_errors(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("id: x\ntask: t\nexpected: {}\nworld: mars\n")
    with pytest.raises(ValueError, match="unknown world"):
        Scenario.load(bad)
    bad.write_text("id: x\ntask: t\nexpected: {ledger: [{order: O-1}]}\n")
    with pytest.raises(ValueError, match="bad.yaml"):
        Scenario.load(bad)
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError, match="not found"):
        find_scenario("nope", root=empty)


def test_duplicate_ids_rejected(tmp_path):
    (tmp_path / "a.yaml").write_text(MINIMAL.format(id="dup"))
    (tmp_path / "b.yaml").write_text(MINIMAL.format(id="dup"))
    with pytest.raises(ValueError, match="duplicate"):
        load_scenarios(tmp_path)


def test_fixture_resolution(tmp_path):
    (tmp_path / "custom.yaml").write_text((SCENARIOS_DIR.parent.parent / "world/support/fixtures/support_basic.yaml").read_text())
    f = tmp_path / "s.yaml"
    f.write_text(MINIMAL.format(id="s") + "initial_state: custom.yaml\n")
    assert Scenario.load(f).fixture_path() == tmp_path / "custom.yaml"
    f.write_text(MINIMAL.format(id="s") + "initial_state: support_history.yaml\n")
    assert Scenario.load(f).fixture_path().name == "support_history.yaml"
    f.write_text(MINIMAL.format(id="s") + "initial_state: missing.yaml\n")
    with pytest.raises(FileNotFoundError):
        Scenario.load(f).fixture_path()
    f.write_text(MINIMAL.format(id="s"))
    s = Scenario.load(f)
    assert s.fixture_path() is None and s.build_world().name == "support"


def test_faults_parse_and_are_validated(tmp_path):
    f = tmp_path / "s.yaml"
    f.write_text(MINIMAL.format(id="s") + "faults: [{tool: issue_refund, on_call: 1, type: timeout_after_commit}]\n")
    s = Scenario.load(f)
    assert s.faults[0].type == FaultType.TIMEOUT_AFTER_COMMIT and s.faults[0].probability == 1.0
    for bad in [
        "faults: [{tool: no_such_tool, type: timeout}]",
        "faults: [{tool: issue_refund, type: not_a_fault}]",
        "faults: [{tool: issue_refund, type: timeout, on_call: 0}]",
        "faults: [{tool: issue_refund, type: timeout, probability: 1.5}]",
        "faults: [{tool: get_order, type: malformed_response, params: {mode: garbage}}]",
    ]:
        f.write_text(MINIMAL.format(id="s") + bad + "\n")
        with pytest.raises(ValueError):
            Scenario.load(f)


def test_run_scenario_persists_verdict_and_scenario_config(store):
    r = run_scenario(find_scenario("normal_refund"), harness="scripted:null", store=store)
    rec = store.get_run(r.run_id)
    assert rec.scenario_id == "normal_refund"
    assert rec.config["scenario"]["expected"]["ledger"][0]["order_id"] == "O-9001"
    assert rec.verdict["outcome"] == Outcome.INCORRECT_SUCCESS_CLAIM.value
    assert rec.verdict["claim"]["kind"] == "success"


def test_matrix_pass_k(store):
    import threading

    flaky_state = {"n": 0}
    lock = threading.Lock()

    class Flaky(ScriptedHarness):
        """Behaves like the oracle on even attempts and like null on odd ones."""

        def __init__(self, *_):
            with lock:
                flaky_state["n"] += 1
                n = flaky_state["n"]
            super().__init__("oracle" if n % 2 else "null")

    register("flaky", Flaky)
    s = [find_scenario("normal_refund")]
    result = run_matrix(s, ["scripted:oracle", "flaky"], store=store, attempts=4, parallel=3, agent_version="v1")
    oracle, flaky = result.cell("normal_refund", "scripted:oracle"), result.cell("normal_refund", "flaky")
    assert oracle.pass_k and oracle.pass_count == 4
    assert not flaky.pass_k and flaky.pass_count == 2
    assert len(result.runs) == 8
    assert all(store.get_run(r.run_id).agent_version == "v1" for r in result.runs)


def test_validate_flags_bad_scenario(store, tmp_path):
    # A scenario that expects nothing at all is satisfied by the null agent: invalid.
    f = tmp_path / "s.yaml"
    f.write_text(MINIMAL.format(id="vacuous"))
    [row] = validate_scenarios(load_scenarios(f), store=store)
    assert not row.valid and row.null.passed
