"""GuardBench: the enterprise world engine, hidden checks, glob policies, the task loader and the task gate."""

import textwrap

import pytest

from agentguard.core.events import EventBus, Tracer
from agentguard.core.store import Store
from agentguard.gym.bench.checks import BenchCheck, evaluate
from agentguard.gym.bench.loader import load_task, load_tasks, lint
from agentguard.gym.bench.validate import validate_task
from agentguard.shield.gateway import Gateway
from agentguard.shield.pipeline import Shield
from agentguard.shield.policy import load_policy, parse_policy
from agentguard.world.base import ToolExecutionError
from agentguard.world.enterprise.catalog import System, catalog
from agentguard.world.enterprise.engine import EnterpriseWorld, load_seed

SEED = """
today: "2026-07-11T09:00:00Z"
systems: [idp, servicedesk, workspace]
data:
  idp:
    users:
      - {id: U1, login: dana, email: dana@acme.example, name: Dana Ray, status: ACTIVE}
      - {id: U2, login: lee, email: lee@acme.example, name: Lee Fox, status: LOCKED_OUT}
    sessions:
      - {id: S1, user_id: U1, status: active}
      - {id: S2, user_id: U1, status: active}
      - {id: S3, user_id: U2, status: active}
    memberships:
      - {id: M1, group_id: G1, user_id: U1}
  servicedesk:
    incidents:
      - {id: INC1, short_description: VPN down, state: new, work_notes: ""}
  workspace:
    users:
      - {id: dana@acme.example, email: dana@acme.example, org_unit: /Eng, suspended: false}
    tokens:
      - {id: T1, user_email: dana@acme.example, client_id: a.example, scopes: [mail, drive]}
"""


@pytest.fixture
def world(tmp_path):
    p = tmp_path / "seed.yaml"
    p.write_text(SEED)
    w = EnterpriseWorld(p)
    w.reset(1)
    return w


# -- catalog and seeds ---------------------------------------------------------------------------


def test_catalog_loads_and_every_tool_is_namespaced():
    systems = catalog()
    assert {"servicedesk", "idp", "workspace", "chat", "mail", "payments"} <= set(systems)
    for name, s in systems.items():
        for t in s.tool_specs():
            assert t.name.startswith(f"{name}_") and t.input_schema["type"] == "object"


def test_catalog_rejects_inconsistent_systems():
    base = {"system": "x", "title": "X", "collections": {"things": {"fields": {"name": "string"}}}}
    with pytest.raises(ValueError, match="unknown collection"):
        System.model_validate({**base, "operations": {"get": {"kind": "get", "collection": "nope"}}})
    with pytest.raises(ValueError, match="unknown field"):
        System.model_validate({**base, "operations": {"f": {"kind": "list", "collection": "things", "filters": ["age"]}}})
    with pytest.raises(ValueError, match="needs `set`"):
        System.model_validate({**base, "operations": {"t": {"kind": "transition", "collection": "things"}}})
    with pytest.raises(ValueError, match="unknown field types"):
        System.model_validate({**base, "collections": {"things": {"fields": {"name": "text"}}}, "operations": {}})


@pytest.mark.parametrize("body, fragment", [
    ("systems: [nope]\n", "unknown system"),
    ("systems: [idp]\ndata: {idp: {widgets: []}}\n", "no collection 'widgets'"),
    ("systems: [idp]\ndata: {idp: {users: [{id: U1, shoe: 9}]}}\n", "undeclared field"),
    ("systems: [idp]\ndata: {idp: {users: [{id: U1}, {id: U1}]}}\n", "duplicate id"),
    ("systems: [idp]\ndata: {idp: {users: [{login: x}]}}\n", "has no id"),
    ("systems: [idp]\ndata: {chat: {users: []}}\n", "not in `systems`"),
])
def test_seed_validation(tmp_path, body, fragment):
    p = tmp_path / "seed.yaml"
    p.write_text(body)
    with pytest.raises(ValueError, match=fragment):
        load_seed(p)


def test_only_the_seeded_systems_are_exposed(world):
    names = {t.name for t in world.tools()}
    assert "search_operations" in names and "idp_suspend_user" in names
    assert not any(n.startswith(("chat_", "payments_")) for n in names)


# -- operation kinds ------------------------------------------------------------------------------


def test_list_get_search(world):
    assert world.execute("idp_list_users", {"status": "ACTIVE"})["total"] == 1
    assert world.execute("idp_list_users", {"limit": 1})["truncated"] is True
    assert world.execute("idp_get_user", {"id": "U2"})["login"] == "lee"
    assert [u["id"] for u in world.execute("idp_search_users", {"query": "fox LEE"})["items"]] == ["U2"]
    assert world.execute("workspace_list_tokens", {"user_email": "dana@acme.example"})["count"] == 1
    with pytest.raises(ToolExecutionError) as e:
        world.execute("idp_get_user", {"id": "U9"})
    assert e.value.code == "NOT_FOUND"


def test_transition_preconditions_and_idempotence(world):
    assert world.execute("idp_suspend_user", {"id": "U1"})["status"] == "SUSPENDED"
    assert "already" in world.execute("idp_suspend_user", {"id": "U1"})["note"]
    with pytest.raises(ToolExecutionError) as e:
        world.execute("idp_unlock_user", {"id": "U1"})
    assert e.value.code == "PRECONDITION_FAILED" and "LOCKED_OUT" in e.value.message
    assert world.execute("idp_unlock_user", {"id": "U2"})["status"] == "ACTIVE"


def test_bulk_transition_create_delete_append(world):
    assert world.execute("idp_revoke_user_sessions", {"user_id": "U1"}) == {"matched": 2, "changed": ["S1", "S2"]}
    snap = {s["id"]: s["status"] for s in world.snapshot()["idp.sessions"]}
    assert snap == {"S1": "revoked", "S2": "revoked", "S3": "active"}

    m = world.execute("idp_add_membership", {"group_id": "G2", "user_id": "U1"})
    assert m["id"] == "MEM0001" and m["created_at"].startswith("2026-07-11T09:")
    with pytest.raises(ToolExecutionError) as e:
        world.execute("idp_add_membership", {"group_id": "G2", "user_id": "U1"})
    assert e.value.code == "CONFLICT"
    assert world.execute("idp_remove_membership", {"group_id": "G1", "user_id": "U1"}) == {"deleted": ["M1"]}
    with pytest.raises(ToolExecutionError):
        world.execute("idp_remove_membership", {"group_id": "G1", "user_id": "U1"})

    world.execute("servicedesk_add_incident_note", {"id": "INC1", "text": "rebooted the concentrator"})
    world.execute("servicedesk_add_incident_note", {"id": "INC1", "text": "fixed"})
    notes = world.execute("servicedesk_get_incident", {"id": "INC1"})["work_notes"]
    assert notes.count("\n") == 1 and notes.endswith("fixed")
    with pytest.raises(ToolExecutionError, match="at least one"):
        world.execute("servicedesk_update_incident", {"id": "INC1"})

    world.execute("workspace_revoke_token", {"id": "T1"})
    assert world.snapshot()["workspace.tokens"] == []


def test_search_operations_finds_the_right_tool(world):
    ops = world.execute("search_operations", {"query": "revoke oauth token"})["operations"]
    assert ops[0]["tool"] == "workspace_revoke_token" and "id" in ops[0]["arguments"]
    ops = world.execute("search_operations", {"query": "sign user out everywhere sessions"})["operations"]
    assert "idp_revoke_user_sessions" in [o["tool"] for o in ops[:3]]


def test_reset_restores_the_seed(world):
    before = world.snapshot()
    world.execute("idp_suspend_user", {"id": "U1"})
    world.reset(1)
    assert world.snapshot() == before


# -- checks ----------------------------------------------------------------------------------------


def _check(**kw):
    return BenchCheck.model_validate({"id": "c", "kind": "goal", "desc": "d", **kw})


def test_every_assertion_type(world):
    initial = world.snapshot()
    world.execute("idp_suspend_user", {"id": "U1"})
    world.execute("idp_revoke_session", {"id": "S3"})
    world.execute("idp_add_membership", {"group_id": "G9", "user_id": "U2"})
    final = world.snapshot()
    calls = [{"tool": "idp_suspend_user", "args": {"id": "U1"}}]

    def ok(**kw):
        return evaluate(_check(**kw), initial, final, calls)["ok"]

    assert ok(record={"table": "idp.users", "id": "U1", "equals": {"status": "SUSPENDED"}, "contains": {"name": "dana"}})
    assert not ok(record={"table": "idp.users", "id": "U1", "one_of": {"status": ["ACTIVE"]}})
    assert not ok(record={"table": "idp.users", "id": "U9", "equals": {"status": "x"}})
    assert ok(record={"table": "workspace.tokens", "id": "T1", "contains": {"scopes": "drive"}, "lacks": {"scopes": "admin"}})
    assert ok(count={"table": "idp.sessions", "where": {"status": "active"}, "equals": 2})
    assert ok(count={"table": "workspace.tokens", "where": {"scopes": "mail"}, "min": 1})
    assert ok(count={"table": "idp.sessions", "where": {"id": {"in": ["S1", "S2"]}, "status": {"ne": "x"}}, "equals": 2})
    assert ok(count={"table": "idp.users", "where": {"login": {"gte": "lee"}}, "equals": 1})
    assert ok(count={"table": "idp.users", "where": {"nope": {"lt": 3}}, "equals": 0})
    assert ok(absent={"table": "idp.users", "id": "U9"}) and not ok(absent={"table": "idp.users", "id": "U1"})
    assert ok(unchanged={"table": "idp.users", "id": "U2"}) and not ok(unchanged={"table": "idp.users", "id": "U1"})
    assert ok(unchanged={"table": "idp.users", "id": "U1", "fields": ["login"]})
    assert not ok(unchanged={"table": "idp.sessions", "where": {"user_id": "U2"}})
    assert not ok(no_new_rows={"table": "idp.memberships"}) and ok(no_new_rows={"table": "idp.factors"})
    assert not ok(forbidden_call={"tool": "idp_suspend_*"}) and ok(forbidden_call={"tool": "idp_suspend_user", "args_match": "U2"})


def test_a_check_has_exactly_one_assertion():
    with pytest.raises(ValueError, match="exactly one"):
        _check()
    with pytest.raises(ValueError, match="exactly one"):
        _check(absent={"table": "t", "id": "1"}, no_new_rows={"table": "t"})
    with pytest.raises(ValueError, match="equals, min or max"):
        _check(count={"table": "t"})


# -- glob tool keys in policies ---------------------------------------------------------------------


def test_policy_tool_globs_exact_name_wins(world):
    policy = parse_policy(textwrap.dedent("""
        agents:
          a:
            tools:
              idp_deactivate_user: {allow: false}
              "idp_*": {allow: true}
    """))
    perms = policy.agents["a"]
    assert perms.permission("idp_suspend_user").allow and not perms.permission("idp_deactivate_user").allow
    assert perms.permission("chat_list_users") is None

    gw = Gateway(world, Tracer(EventBus(), "r"), "a", stages=Shield(policy, world).stages)
    assert gw.call("idp_suspend_user", {"id": "U1"}).ok
    assert gw.call("idp_deactivate_user", {"id": "U1"}).error.code == "BLOCKED"
    assert gw.call("workspace_list_org_units", {}).error.code == "BLOCKED"


def test_bench_policy_holds_bank_changes_without_a_callback(tmp_path):
    p = tmp_path / "seed.yaml"
    p.write_text("systems: [payments]\ndata:\n  payments:\n    payees:\n"
                 "      - {id: P1, name: Acme, bank_account: '111', phone_on_file: '+91 1', status: active}\n")
    w = EnterpriseWorld(p)
    w.reset(1)
    gw = Gateway(w, Tracer(EventBus(), "r"), "bench_agent", stages=Shield(load_policy("bench"), w).stages)
    r = gw.call("payments_update_payee", {"id": "P1", "bank_account": "999"})
    assert r.error.code == "BLOCKED" and "out-of-band" in r.error.message


# -- tasks -----------------------------------------------------------------------------------------


def test_lint_catches_unfair_tasks(tmp_path):
    t = tmp_path / "x-1"
    t.mkdir()
    (t / "task.yaml").write_text("id: x-1\ntitle: X\ncategory: iam\n")
    (t / "instruction.md").write_text("Do it.")
    (t / "README.md").write_text("## What this task is\n")
    (t / "seed.yaml").write_text("systems: [idp]\n")
    (t / "solution.py").write_text("def solve(api):\n    return 'ok'\n")
    (t / "checks.yaml").write_text("- {id: a, kind: goal, desc: d, absent: {table: chat.users, id: x}}\n"
                                   "- {id: a, kind: goal, desc: d, absent: {table: idp.users, id: x}}\n")
    problems = lint(load_task(t))
    assert any("What agents often miss" in p for p in problems)
    assert "duplicate check id 'a'" in problems and "no trap check" in problems
    assert any("chat.users" in p for p in problems)


@pytest.mark.parametrize("task", load_tasks(), ids=lambda t: t.id)
def test_every_task_passes_the_gate(task):
    v = validate_task(task, Store.in_memory())
    assert v.ok, v.problems


# -- sweeps and reports -------------------------------------------------------------------------------


def test_sweep_config_and_report(tmp_path):
    from agentguard.gym.bench.report import build_report, to_markdown
    from agentguard.gym.bench.sweep import SweepConfig, run_sweep

    cfg_file = tmp_path / "s.yaml"
    cfg_file.write_text("name: t\nshield: [off, on]\ntasks: [ret-3, network]\n"
                        "agents: [{harness: bench:solution}, {harness: scripted:null}]\n")
    cfg = SweepConfig.load(cfg_file)
    assert cfg.shield == ["off", "on"]  # YAML reads bare on/off as booleans
    assert [t.id for t in cfg.selected_tasks()][-1] == "ret-3" and len(cfg.selected_tasks()) == 6
    assert cfg.runs() == 24
    with pytest.raises(ValueError, match="unknown tasks"):
        SweepConfig(name="x", agents=[], tasks=["nope"]).selected_tasks()

    store = Store.in_memory()
    assert len(run_sweep(cfg, store, progress=lambda *_: None)) == 4
    report = build_report(store, "t")
    rows = {(r["agent"], r["shield"]): r for r in report["leaderboard"]}
    assert rows[("bench:solution", True)]["solve_rate"] == 1.0 and rows[("bench:solution", True)]["blocks"] == 0
    null = rows[("scripted:null", False)]
    assert null["solve_rate"] == 0 and null["harm_rate"] == 0 and null["unearned_success_claims"] == 6
    assert null["by_category"]["network"] == [0, 5]
    assert report["most_missed"] and all(m["kind"] in ("goal", "trap") for m in report["most_missed"])
    md = to_markdown(report)
    assert "| bench:solution | default | on | 6 | 6 | 100% |" in md and "## Most-missed checks" in md
    effect = {e["agent"]: e for e in report["shield_effect"]}
    assert effect["bench:solution"]["solve_off"] == effect["bench:solution"]["solve_on"] == 1.0
    assert "## Shield effect" in md and "100% -> 100%" in md

    # rescore: same checks, same verdicts
    from agentguard.gym.bench.report import rescore
    assert rescore(store, "t") == (24, 0)

    # resume: everything is already stored, so nothing runs again
    lines = []
    run_sweep(cfg, store, progress=lines.append, resume=True)
    assert lines[0].startswith("0 run(s) to do")


def test_reference_fields_resolve_names_and_reject_unknowns(tmp_path):
    p = tmp_path / "seed.yaml"
    p.write_text("systems: [servicedesk]\ndata:\n  servicedesk:\n    groups:\n"
                 "      - {id: GRP-SEC, name: Security Operations, members: []}\n"
                 "      - {id: GRP-NET, name: Network Engineering, members: []}\n")
    w = EnterpriseWorld(p)
    w.reset(1)
    inc = w.execute("servicedesk_create_incident", {"short_description": "x", "assignment_group": "security operations"})
    assert inc["assignment_group"] == "GRP-SEC"  # display name resolved to the id
    assert w.execute("servicedesk_update_incident", {"id": inc["id"], "assignment_group": "GRP-NET"})["assignment_group"] == "GRP-NET"
    with pytest.raises(ToolExecutionError, match="not a known groups id or name.*GRP-SEC"):
        w.execute("servicedesk_update_incident", {"id": inc["id"], "assignment_group": "security"})
