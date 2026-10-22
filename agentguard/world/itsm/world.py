"""IT service management world: employees, systems, access grants and access requests."""

from __future__ import annotations

import functools
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from agentguard.core.models import ToolSpec
from agentguard.world.base import ToolExecutionError, World
from agentguard.world.itsm.tools import ITSM_TOOLS

FIXTURES_DIR = Path(__file__).parent / "fixtures"
DEFAULT_FIXTURE = FIXTURES_DIR / "itsm_basic.yaml"
EPOCH = datetime(2026, 2, 2, 9, 0, 0, tzinfo=timezone.utc)

SCHEMA = """
CREATE TABLE users (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL, department TEXT NOT NULL,
  manager_id TEXT, status TEXT NOT NULL
);
CREATE TABLE systems (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, sensitivity TEXT NOT NULL, owner_department TEXT NOT NULL,
  roles TEXT NOT NULL
);
CREATE TABLE access_grants (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL, system_id TEXT NOT NULL, role TEXT NOT NULL,
  request_id TEXT, expires_at TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE access_requests (
  id TEXT PRIMARY KEY, requester_id TEXT NOT NULL, user_id TEXT NOT NULL, system_id TEXT NOT NULL,
  role TEXT NOT NULL, justification TEXT NOT NULL, status TEXT NOT NULL, notes TEXT NOT NULL
);
CREATE TABLE outbox (
  id TEXT PRIMARY KEY, "to" TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL, sent_at TEXT NOT NULL
);
"""
TABLES = ["users", "systems", "access_grants", "access_requests", "outbox"]


def _locked(fn):
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return fn(self, *args, **kwargs)

    return wrapper


class ItsmWorld(World):
    name = "itsm"
    fixtures_dir = FIXTURES_DIR
    side_effect_tables = {"grants": "access_grants", "outbox": "outbox"}

    def __init__(self, fixture: str | Path | None = None) -> None:
        self.fixture_path = Path(fixture) if fixture else DEFAULT_FIXTURE
        self.seed: int | None = None
        self._db: sqlite3.Connection | None = None
        self._clock = EPOCH
        self._counters: dict[str, int] = {}
        self._lock = threading.RLock()

    @_locked
    def reset(self, seed: int) -> None:
        if self._db is not None:
            self._db.close()
        self.seed, self._clock, self._counters = seed, EPOCH, {}
        db = sqlite3.connect(":memory:", check_same_thread=False)
        db.row_factory = sqlite3.Row
        db.executescript(SCHEMA)
        self._db = db
        fx = yaml.safe_load(self.fixture_path.read_text())
        for u in fx.get("users", []):
            db.execute("INSERT INTO users VALUES (?,?,?,?,?,?)",
                       (u["id"], u["name"], u["email"], u["department"], u.get("manager_id"), u["status"]))
        for s in fx.get("systems", []):
            db.execute("INSERT INTO systems VALUES (?,?,?,?,?)",
                       (s["id"], s["name"], s["sensitivity"], s["owner_department"], ",".join(s["roles"])))
        for g in fx.get("access_grants", []):
            db.execute("INSERT INTO access_grants VALUES (?,?,?,?,?,?,?,?)",
                       (self._next_id("GR"), g["user_id"], g["system_id"], g["role"], g.get("request_id"),
                        g.get("expires_at"), g.get("status", "active"), g.get("created_at", EPOCH.isoformat())))
        for r in fx.get("access_requests", []):
            db.execute("INSERT INTO access_requests VALUES (?,?,?,?,?,?,?,?)",
                       (r["id"], r["requester_id"], r["user_id"], r["system_id"], r["role"], r["justification"],
                        r.get("status", "open"), r.get("notes", "")))
        db.commit()

    @property
    def db(self) -> sqlite3.Connection:
        if self._db is None:
            raise RuntimeError("ItsmWorld.reset(seed) must be called before use")
        return self._db

    def _next_id(self, prefix: str) -> str:
        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        return f"{prefix}-{self._counters[prefix]:04d}"

    def _tick(self) -> datetime:
        self._clock += timedelta(minutes=1)
        return self._clock

    def tools(self) -> list[ToolSpec]:
        return list(ITSM_TOOLS)

    @_locked
    def execute(self, tool: str, args: dict[str, Any]) -> Any:
        handler = getattr(self, f"_tool_{tool}", None)
        if handler is None or self.tool(tool) is None:
            raise ToolExecutionError("UNKNOWN_TOOL", f"No tool named '{tool}'")
        return handler(**args)

    def _one(self, table: str, key: str, label: str) -> dict[str, Any]:
        row = self.db.execute(f"SELECT * FROM {table} WHERE id = ?", (key,)).fetchone()
        if row is None:
            raise ToolExecutionError("NOT_FOUND", f"{label} {key} not found")
        return dict(row)

    def _tool_list_access_requests(self, status: str) -> dict[str, Any]:
        rows = [dict(r) for r in self.db.execute(
            "SELECT id, requester_id, user_id, system_id, role, status FROM access_requests WHERE status = ? ORDER BY id",
            (status,))]
        return {"requests": rows, "count": len(rows)}

    def _tool_get_access_request(self, request_id: str) -> dict[str, Any]:
        return self._one("access_requests", request_id, "Access request")

    def _tool_get_user(self, user_id: str) -> dict[str, Any]:
        return self._one("users", user_id, "User")

    def _tool_get_system(self, system_id: str) -> dict[str, Any]:
        s = self._one("systems", system_id, "System")
        s["roles"] = s["roles"].split(",")
        return s

    def _tool_list_grants(self, user_id: str) -> dict[str, Any]:
        self._one("users", user_id, "User")
        rows = [dict(r) for r in self.db.execute(
            "SELECT id, system_id, role, expires_at, status FROM access_grants WHERE user_id = ? AND status = 'active' "
            "ORDER BY id", (user_id,))]
        return {"user_id": user_id, "grants": rows}

    def _tool_grant_access(self, user_id: str, system_id: str, role: str, request_id: str, days: int) -> dict[str, Any]:
        user = self._one("users", user_id, "User")
        system = self._tool_get_system(system_id)
        if user["status"] != "active":
            raise ToolExecutionError("USER_INACTIVE", f"{user_id} is {user['status']}")
        if role not in system["roles"]:
            raise ToolExecutionError("INVALID_ROLE", f"{system_id} has no '{role}' role")
        existing = self.db.execute(
            "SELECT * FROM access_grants WHERE user_id = ? AND system_id = ? AND role = ? AND status = 'active'",
            (user_id, system_id, role)).fetchone()
        if existing is not None:
            return {"grant_id": existing["id"], "already_granted": True, "expires_at": existing["expires_at"]}
        now = self._tick()
        gid = self._next_id("GR")
        expires = (now + timedelta(days=days)).isoformat()
        self.db.execute("INSERT INTO access_grants VALUES (?,?,?,?,?,?,?,?)",
                        (gid, user_id, system_id, role, request_id, expires, "active", now.isoformat()))
        self.db.commit()
        return {"grant_id": gid, "user_id": user_id, "system_id": system_id, "role": role, "expires_at": expires,
                "already_granted": False}

    def _tool_revoke_access(self, user_id: str, system_id: str, role: str) -> dict[str, Any]:
        cur = self.db.execute("UPDATE access_grants SET status = 'revoked' WHERE user_id = ? AND system_id = ? "
                              "AND role = ? AND status = 'active'", (user_id, system_id, role))
        self.db.commit()
        return {"revoked": cur.rowcount}

    def _tool_update_access_request(self, request_id: str, status: str, notes: str | None = None) -> dict[str, Any]:
        row = self._one("access_requests", request_id, "Access request")
        added = f"[{self._tick().isoformat()}] {notes}" if notes else ""
        new = row["notes"] + (f"\n{added}" if row["notes"] and added else added)
        self.db.execute("UPDATE access_requests SET status = ?, notes = ? WHERE id = ?", (status, new, request_id))
        self.db.commit()
        return {"id": request_id, "status": status, "notes": added}

    def _tool_notify(self, to: str, subject: str, body: str) -> dict[str, Any]:
        local, _, domain = to.partition("@")
        if not local or "." not in domain:
            raise ToolExecutionError("INVALID_ARGS", f"'{to}' is not a valid email address")
        mid = self._next_id("MSG")
        sent = self._tick().isoformat()
        self.db.execute("INSERT INTO outbox VALUES (?,?,?,?,?)", (mid, to, subject, body, sent))
        self.db.commit()
        return {"message_id": mid, "to": to, "status": "sent"}

    def _tool_query_directory(self, sql: str) -> dict[str, Any]:
        def authorizer(action: int, *_: Any) -> int:
            return sqlite3.SQLITE_OK if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ,
                                                   sqlite3.SQLITE_FUNCTION) else sqlite3.SQLITE_DENY

        self.db.set_authorizer(authorizer)
        try:
            rows = [dict(r) for r in self.db.execute(sql).fetchmany(1001)]
        except sqlite3.DatabaseError as e:
            raise ToolExecutionError("QUERY_REJECTED", f"Query rejected: {e}") from e
        finally:
            self.db.set_authorizer(None)
        return {"rows": rows[:1000], "row_count": min(len(rows), 1000), "truncated": len(rows) > 1000}

    # -- ground truth and rule queries ------------------------------------------------

    @_locked
    def snapshot(self) -> dict[str, Any]:
        out: dict[str, Any] = {"world": self.name, "seed": self.seed, "clock": self._clock.isoformat()}
        for table in TABLES:
            out[table] = [dict(r) for r in self.db.execute(f"SELECT * FROM {table} ORDER BY id")]
        return out

    @_locked
    def user_active(self, user_id: str | None) -> bool:
        row = self.db.execute("SELECT status FROM users WHERE id = ?", (user_id,)).fetchone()
        return bool(row and row["status"] == "active")

    @_locked
    def manager_of(self, user_id: str | None) -> str | None:
        row = self.db.execute("SELECT manager_id FROM users WHERE id = ?", (user_id,)).fetchone()
        return row["manager_id"] if row else None

    @_locked
    def system_sensitivity(self, system_id: str | None) -> str | None:
        row = self.db.execute("SELECT sensitivity FROM systems WHERE id = ?", (system_id,)).fetchone()
        return row["sensitivity"] if row else None

    @_locked
    def has_grant(self, user_id: str, system_id: str, role: str) -> bool:
        row = self.db.execute("SELECT 1 FROM access_grants WHERE user_id = ? AND system_id = ? AND role = ? "
                              "AND status = 'active'", (user_id, system_id, role)).fetchone()
        return row is not None

    @_locked
    def request_field(self, request_id: str, field: str) -> Any:
        if field not in ("requester_id", "user_id", "system_id", "role", "status"):
            return None
        row = self.db.execute(f"SELECT {field} FROM access_requests WHERE id = ?", (request_id,)).fetchone()
        return row[0] if row else None

    def rule_queries(self) -> dict[str, dict[str, Any]]:
        return {"iam": {"user_active": self.user_active, "manager_of": self.manager_of,
                        "system_sensitivity": self.system_sensitivity, "has_grant": self.has_grant,
                        "request_field": self.request_field}}
