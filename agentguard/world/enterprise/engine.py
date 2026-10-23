"""The `enterprise` world: many mock systems, one seeded record store.

A task's seed file picks the systems it uses and fills their collections:

    today: "2026-07-11T09:00:00Z"
    systems: [servicedesk, idp]          # optional: defaults to the systems under `data`
    data:
      idp:
        users:
          - {id: U1, login: dana, status: SUSPENDED}

Only the chosen systems' operations are exposed as tools, plus `search_operations`,
which agents use to discover them (as ITSMBench agents search a mock API catalog).
The snapshot is every collection, keyed `<system>.<collection>`, which is what bench
checks assert on.
"""

from __future__ import annotations

import copy
import datetime as dt
import functools
import re
import threading
from pathlib import Path
from typing import Any

import yaml

from agentguard.core.models import SideEffect, ToolSpec
from agentguard.world.base import ToolExecutionError, World
from agentguard.world.enterprise.catalog import Operation, System, catalog

FIXTURES_DIR = Path(__file__).parent / "fixtures"
DEFAULT_TODAY = "2026-07-01T09:00:00Z"
LIST_LIMIT = 100
SEARCH_LIMIT = 20

SEARCH_TOOL = ToolSpec(
    name="search_operations",
    description="Search the available API operations across every system in this environment. Returns tool names, "
                "what they do and their arguments. Start here to find the right tool.",
    input_schema={"type": "object", "properties": {
        "query": {"type": "string", "description": "words describing what you want to do or read"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50}},
        "required": ["query"], "additionalProperties": False},
    side_effect=SideEffect.READ,
)


def _locked(fn):
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return fn(self, *args, **kwargs)

    return wrapper


def _plain(value: Any) -> Any:
    """YAML may parse dates; the store holds JSON-compatible values only."""
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def load_seed(path: str | Path) -> dict[str, Any]:
    seed = _plain(yaml.safe_load(Path(path).read_text()) or {})
    data = seed.get("data") or {}
    systems = seed.get("systems") or sorted(data)
    known = catalog()
    unknown = sorted(set(systems) - set(known))
    if unknown:
        raise ValueError(f"{path}: unknown system(s) {unknown} (available: {sorted(known)})")
    for system, colls in data.items():
        if system not in systems:
            raise ValueError(f"{path}: data for '{system}', which is not in `systems`")
        spec = known[system]
        for coll, rows in (colls or {}).items():
            if coll not in spec.collections:
                raise ValueError(f"{path}: {system} has no collection '{coll}' "
                                 f"(it has {sorted(spec.collections)})")
            allowed = set(spec.collections[coll].fields) | {"id"}
            seen: set[str] = set()
            for row in rows or []:
                if "id" not in row:
                    raise ValueError(f"{path}: a {system}.{coll} record has no id: {row}")
                if row["id"] in seen:
                    raise ValueError(f"{path}: duplicate id {row['id']} in {system}.{coll}")
                seen.add(row["id"])
                extra = sorted(set(row) - allowed)
                if extra:
                    raise ValueError(f"{path}: {system}.{coll} {row['id']} has undeclared field(s) {extra}")
    return {"today": seed.get("today", DEFAULT_TODAY), "systems": list(systems), "data": data}


class EnterpriseWorld(World):
    name = "enterprise"
    fixtures_dir = FIXTURES_DIR
    side_effect_tables: dict[str, str] = {}  # bench checks account for every change explicitly

    def __init__(self, fixture: str | Path | None = None) -> None:
        self.fixture_path = Path(fixture) if fixture else None
        self._seed = load_seed(self.fixture_path) if self.fixture_path else {"today": DEFAULT_TODAY, "systems": [], "data": {}}
        self.systems: dict[str, System] = {s: catalog()[s] for s in self._seed["systems"]}
        self._ops: dict[str, tuple[System, str, Operation]] = {
            f"{s.system}_{name}": (s, name, op) for s in self.systems.values() for name, op in s.operations.items()
        }
        self._tools = [SEARCH_TOOL] + [t for s in self.systems.values() for t in s.tool_specs()]
        self._tables: dict[str, dict[str, dict[str, Any]]] = {}
        self._counters: dict[str, int] = {}
        self._clock = self._parse_time(self._seed["today"])
        self._lock = threading.RLock()
        self.seed: int | None = None

    # -- World ---------------------------------------------------------------------------------

    def tools(self) -> list[ToolSpec]:
        return self._tools

    @_locked
    def reset(self, seed: int) -> None:
        self.seed = seed
        self._clock = self._parse_time(self._seed["today"])
        self._counters = {}
        self._tables = {f"{s}.{c}": {} for s, sys in self.systems.items() for c in sys.collections}
        for system, colls in self._seed["data"].items():
            for coll, rows in (colls or {}).items():
                for row in rows or []:
                    self._tables[f"{system}.{coll}"][str(row["id"])] = copy.deepcopy({**row, "id": str(row["id"])})

    @_locked
    def snapshot(self) -> dict[str, Any]:
        return {name: [copy.deepcopy(r) for _, r in sorted(rows.items())] for name, rows in self._tables.items()}

    @_locked
    def execute(self, tool: str, args: dict[str, Any]) -> Any:
        if tool == SEARCH_TOOL.name:
            return self._search_operations(str(args["query"]), int(args.get("limit", 10)))
        if tool not in self._ops:
            raise ToolExecutionError("UNKNOWN_TOOL", f"No tool named '{tool}'")
        system, _, op = self._ops[tool]
        table = self._tables[f"{system.system}.{op.collection}"]
        handler = getattr(self, f"_op_{op.kind}")
        return handler(system, op, table, dict(args))

    def rule_queries(self) -> dict[str, dict[str, Any]]:
        return {"records": {
            "get": lambda table, id: copy.deepcopy(self._tables.get(table, {}).get(str(id))),
            "count": lambda table, field, value: sum(1 for r in self._tables.get(table, {}).values()
                                                     if r.get(field) == value),
        }}

    # -- operation kinds --------------------------------------------------------------------------

    def _op_list(self, system: System, op: Operation, table: dict, args: dict) -> dict[str, Any]:
        limit = int(args.pop("limit", LIST_LIMIT))
        rows = [r for r in table.values() if all(_field_matches(r.get(k), v) for k, v in args.items())]
        return {"items": [copy.deepcopy(r) for r in rows[:limit]], "count": min(len(rows), limit),
                "total": len(rows), "truncated": len(rows) > limit}

    def _op_get(self, system: System, op: Operation, table: dict, args: dict) -> dict[str, Any]:
        return copy.deepcopy(self._row(system, op, table, args["id"]))

    def _op_search(self, system: System, op: Operation, table: dict, args: dict) -> dict[str, Any]:
        words = [w for w in re.split(r"\W+", str(args["query"]).lower()) if w]
        limit = int(args.get("limit", SEARCH_LIMIT))
        hits = []
        for r in table.values():
            text = " ".join(str(r.get(f, "")) for f in op.fields).lower()
            if words and all(w in text for w in words):
                hits.append(copy.deepcopy(r))
        return {"items": hits[:limit], "count": min(len(hits), limit), "total": len(hits)}

    def _op_create(self, system: System, op: Operation, table: dict, args: dict) -> dict[str, Any]:
        missing = [f for f in op.required if args.get(f) in (None, "")]
        if missing:
            raise ToolExecutionError("INVALID_ARGUMENT", f"missing required field(s): {missing}")
        if op.unique:
            key = tuple(args.get(k) for k in op.unique)
            dup = next((r for r in table.values() if tuple(r.get(k) for k in op.unique) == key), None)
            if dup is not None:
                raise ToolExecutionError("CONFLICT", f"{op.collection} {dup['id']} already exists for "
                                                     f"{dict(zip(op.unique, key))}")
        coll = system.collections[op.collection]
        args = self._resolve_refs(system, op.collection, args)
        row = {**copy.deepcopy(op.defaults), **args, "id": self._mint(system.system, op.collection, coll.id_prefix, table)}
        self._stamp(coll.fields, row, "created_at", "updated_at")
        table[row["id"]] = row
        return copy.deepcopy(row)

    def _op_update(self, system: System, op: Operation, table: dict, args: dict) -> dict[str, Any]:
        row = self._row(system, op, table, args.pop("id"))
        if not args:
            raise ToolExecutionError("INVALID_ARGUMENT", f"give at least one of {op.fields} to update")
        row.update(copy.deepcopy(self._resolve_refs(system, op.collection, args)))
        self._stamp(system.collections[op.collection].fields, row, "updated_at")
        return copy.deepcopy(row)

    def _op_transition(self, system: System, op: Operation, table: dict, args: dict) -> dict[str, Any]:
        row = self._row(system, op, table, args["id"])
        if all(row.get(k) == v for k, v in op.set.items()):
            return {**copy.deepcopy(row), "note": "already in that state; nothing changed"}
        for field, allowed in op.when.items():
            if row.get(field) not in allowed:
                raise ToolExecutionError("PRECONDITION_FAILED",
                                         f"{op.collection} {row['id']} has {field}={row.get(field)!r}; "
                                         f"this operation needs {field} in {allowed}")
        row.update(copy.deepcopy(op.set))
        self._stamp(system.collections[op.collection].fields, row, "updated_at")
        return copy.deepcopy(row)

    def _op_transition_where(self, system: System, op: Operation, table: dict, args: dict) -> dict[str, Any]:
        rows = [r for r in table.values() if all(r.get(k) == args[k] for k in op.keys)]
        changed = [r for r in rows if not all(r.get(k) == v for k, v in op.set.items())]
        for r in changed:
            r.update(copy.deepcopy(op.set))
            self._stamp(system.collections[op.collection].fields, r, "updated_at")
        return {"matched": len(rows), "changed": sorted(r["id"] for r in changed)}

    def _op_delete(self, system: System, op: Operation, table: dict, args: dict) -> dict[str, Any]:
        row = self._row(system, op, table, args["id"])
        del table[row["id"]]
        self._tick()
        return {"deleted": row["id"]}

    def _op_delete_where(self, system: System, op: Operation, table: dict, args: dict) -> dict[str, Any]:
        doomed = [rid for rid, r in table.items() if all(r.get(k) == args[k] for k in op.keys)]
        if not doomed:
            raise ToolExecutionError("NOT_FOUND", f"no {op.collection} match {args}")
        for rid in doomed:
            del table[rid]
        self._tick()
        return {"deleted": sorted(doomed)}

    def _op_append(self, system: System, op: Operation, table: dict, args: dict) -> dict[str, Any]:
        row = self._row(system, op, table, args["id"])
        stamp = self._tick()
        current = row.get(op.field)
        if isinstance(current, list) or system.field_type(op.collection, op.field) == "array":
            row[op.field] = list(current or []) + [{"at": stamp, "text": args["text"]}]
        else:
            row[op.field] = (f"{current}\n" if current else "") + f"[{stamp}] {args['text']}"
        return copy.deepcopy(row)

    # -- helpers ------------------------------------------------------------------------------------

    def _resolve_refs(self, system: System, collection: str, args: dict[str, Any]) -> dict[str, Any]:
        refs = system.collections[collection].refs
        out = dict(args)
        for field, target in refs.items():
            value = out.get(field)
            if value in (None, ""):
                continue
            rows = self._tables[f"{system.system}.{target}"]
            if str(value) in rows:
                continue
            by_name = [rid for rid, r in rows.items() if str(r.get("name", "")).lower() == str(value).lower()]
            if len(by_name) == 1:
                out[field] = by_name[0]
                continue
            choices = ", ".join(f"{rid} ({r.get('name', '')})" for rid, r in sorted(rows.items())[:20])
            raise ToolExecutionError("INVALID_ARGUMENT", f"{field} '{value}' is not a known {target} id or name. "
                                                         f"Known: {choices}")
        return out

    def _row(self, system: System, op: Operation, table: dict, rid: Any) -> dict[str, Any]:
        row = table.get(str(rid))
        if row is None:
            raise ToolExecutionError("NOT_FOUND", f"{system.title}: no {op.collection} with id {rid!r}")
        return row

    def _mint(self, system: str, collection: str, prefix: str, table: dict) -> str:
        key = f"{system}.{collection}"
        while True:
            self._counters[key] = self._counters.get(key, 0) + 1
            rid = f"{prefix or collection[:3].upper()}{self._counters[key]:04d}"
            if rid not in table:
                return rid

    def _tick(self) -> str:
        self._clock += dt.timedelta(minutes=1)
        return self._clock.strftime("%Y-%m-%dT%H:%M:%SZ")

    def _stamp(self, fields: dict[str, str], row: dict[str, Any], *names: str) -> None:
        now = self._tick()
        for n in names:
            if n in fields:
                row[n] = now

    @staticmethod
    def _parse_time(value: str) -> dt.datetime:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    def _search_operations(self, query: str, limit: int) -> dict[str, Any]:
        words = [w for w in re.split(r"\W+", query.lower()) if len(w) > 1]
        scored = []
        for t in self._tools[1:]:
            system, name, op = self._ops[t.name]
            hay = f"{t.name} {name.replace('_', ' ')} {t.description} {system.system} {system.title} " \
                  f"{system.description} {op.collection.replace('_', ' ')}".lower()
            score = sum(2 if w in t.name else 1 for w in words if w in hay)
            if score:
                scored.append((score, t))
        scored.sort(key=lambda st: (-st[0], st[1].name))
        return {"operations": [
            {"tool": t.name, "description": t.description, "side_effect": t.side_effect.value,
             "arguments": t.input_schema["properties"], "required": t.input_schema.get("required", [])}
            for _, t in scored[:limit]
        ], "systems": [{"system": s.system, "title": s.title} for s in self.systems.values()]}


def _field_matches(value: Any, want: Any) -> bool:
    if isinstance(value, list) and not isinstance(want, list):
        return want in value
    return value == want
