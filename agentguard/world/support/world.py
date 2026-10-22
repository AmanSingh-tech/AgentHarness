"""Customer-support / refunds world backed by an in-memory SQLite database."""

from __future__ import annotations

import base64
import functools
import random
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from agentguard.core.models import ToolSpec
from agentguard.world.base import ToolExecutionError, World
from agentguard.world.support.tools import SUPPORT_TOOLS

FIXTURES_DIR = Path(__file__).parent / "fixtures"
DEFAULT_FIXTURE = FIXTURES_DIR / "support_basic.yaml"

# World time starts here on every reset and advances one minute per write, so
# timestamps are reproducible for a given seed and call sequence.
EPOCH = datetime(2026, 1, 15, 9, 0, 0, tzinfo=timezone.utc)
MAX_QUERY_ROWS = 1000

SCHEMA = """
CREATE TABLE customers (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL,
  tier TEXT NOT NULL, verified INTEGER NOT NULL
);
CREATE TABLE orders (
  id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers(id),
  amount_inr INTEGER NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE payments_ledger (
  id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(id),
  customer_id TEXT NOT NULL, type TEXT NOT NULL, amount_inr INTEGER NOT NULL,
  status TEXT NOT NULL, idempotency_key TEXT UNIQUE, created_at TEXT NOT NULL
);
CREATE TABLE tickets (
  id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, status TEXT NOT NULL, notes TEXT NOT NULL
);
CREATE TABLE outbox (
  id TEXT PRIMARY KEY, "to" TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL, sent_at TEXT NOT NULL
);
CREATE TABLE secrets (
  id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL, value TEXT NOT NULL
);
"""

TABLES = ["customers", "orders", "payments_ledger", "tickets", "outbox", "secrets"]

_FIRST = ["Aarav", "Diya", "Kabir", "Meera", "Vihaan", "Isha", "Arjun", "Sara", "Rohan", "Nisha", "Dev", "Kavya"]
_LAST = ["Patel", "Reddy", "Nair", "Gupta", "Khan", "Das", "Menon", "Joshi", "Bose", "Kapoor", "Rao", "Singh"]


def _locked(fn):
    """One SQLite connection is shared by every tool call; agents (e.g. LangGraph) may call
    tools in parallel threads, so every database access is serialised."""

    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return fn(self, *args, **kwargs)

    return wrapper


class SupportWorld(World):
    name = "support"
    fixtures_dir = FIXTURES_DIR
    side_effect_tables = {"ledger": "payments_ledger", "outbox": "outbox"}

    def __init__(self, fixture: str | Path | None = None) -> None:
        self.fixture_path = Path(fixture) if fixture else DEFAULT_FIXTURE
        self.seed: int | None = None
        self._db: sqlite3.Connection | None = None
        self._clock = EPOCH
        self._counters: dict[str, int] = {}
        self._lock = threading.RLock()

    # -- lifecycle ----------------------------------------------------------

    @_locked
    def reset(self, seed: int) -> None:
        if self._db is not None:
            self._db.close()
        self.seed = seed
        self._clock = EPOCH
        self._counters = {}
        db = sqlite3.connect(":memory:", check_same_thread=False)
        db.row_factory = sqlite3.Row
        db.executescript(SCHEMA)
        self._db = db
        self._load_fixture(yaml.safe_load(self.fixture_path.read_text()), random.Random(seed))

    def _load_fixture(self, fx: dict[str, Any], rng: random.Random) -> None:
        db = self.db
        for c in fx.get("customers", []):
            db.execute(
                "INSERT INTO customers VALUES (?,?,?,?,?)",
                (c["id"], c["name"], c["email"], c["tier"], int(c["verified"])),
            )
        for i in range(fx.get("filler_customers", 0)):
            first, last = rng.choice(_FIRST), rng.choice(_LAST)
            cid = f"C-{5000 + i}"
            db.execute(
                "INSERT INTO customers VALUES (?,?,?,?,?)",
                (cid, f"{first} {last}", f"{first}.{last}.{5000 + i}@customer-domain.com".lower(),
                 rng.choice(["standard", "standard", "gold"]), int(rng.random() < 0.85)),
            )
        for o in fx.get("orders", []):
            db.execute(
                "INSERT INTO orders VALUES (?,?,?,?,?)",
                (o["id"], o["customer_id"], o["amount_inr"], o["status"], o["created_at"]),
            )
        for p in fx.get("payments_ledger", []):
            db.execute(
                "INSERT INTO payments_ledger VALUES (?,?,?,?,?,?,?,?)",
                (self._next_id("LED"), p["order_id"], p["customer_id"], p["type"], p["amount_inr"],
                 p["status"], p.get("idempotency_key"), p["created_at"]),
            )
        for t in fx.get("tickets", []):
            db.execute("INSERT INTO tickets VALUES (?,?,?,?)", (t["id"], t["customer_id"], t["status"], t["notes"]))
        for s in fx.get("secrets", []):
            db.execute("INSERT INTO secrets VALUES (?,?,?)", (self._next_id("SEC"), s["name"], s["value"]))
        db.commit()

    @property
    def db(self) -> sqlite3.Connection:
        if self._db is None:
            raise RuntimeError("SupportWorld.reset(seed) must be called before use")
        return self._db

    def _next_id(self, prefix: str) -> str:
        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        return f"{prefix}-{self._counters[prefix]:04d}"

    def _tick(self) -> str:
        self._clock += timedelta(minutes=1)
        return self._clock.isoformat()

    # -- ToolBackend --------------------------------------------------------

    def tools(self) -> list[ToolSpec]:
        return list(SUPPORT_TOOLS)

    @_locked
    def execute(self, tool: str, args: dict[str, Any]) -> Any:
        handler = getattr(self, f"_tool_{tool}", None)
        if handler is None or self.tool(tool) is None:
            raise ToolExecutionError("UNKNOWN_TOOL", f"No tool named '{tool}'")
        return handler(**args)

    def _tool_get_customer(self, customer_id: str) -> dict[str, Any]:
        row = self.db.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
        if row is None:
            raise ToolExecutionError("NOT_FOUND", f"Customer {customer_id} not found")
        out = dict(row)
        out["verified"] = bool(out["verified"])
        return out

    def _tool_get_order(self, order_id: str) -> dict[str, Any]:
        row = self.db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if row is None:
            raise ToolExecutionError("NOT_FOUND", f"Order {order_id} not found")
        out = dict(row)
        out["refunded_amount_inr"] = self._refunded_total(order_id)
        out["refundable_inr"] = out["amount_inr"] - out["refunded_amount_inr"]
        return out

    def _tool_get_ticket(self, ticket_id: str) -> dict[str, Any]:
        row = self.db.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if row is None:
            raise ToolExecutionError("NOT_FOUND", f"Ticket {ticket_id} not found")
        return dict(row)

    def _tool_list_tickets(self, status: str) -> dict[str, Any]:
        rows = self.db.execute("SELECT id, customer_id, status FROM tickets WHERE status = ? ORDER BY id", (status,))
        tickets = [dict(r) for r in rows]
        return {"tickets": tickets, "count": len(tickets)}

    def _tool_issue_refund(self, order_id: str, amount_inr: int, idempotency_key: str) -> dict[str, Any]:
        existing = self.db.execute(
            "SELECT * FROM payments_ledger WHERE idempotency_key = ?", (idempotency_key,)
        ).fetchone()
        if existing is not None:
            if existing["order_id"] != order_id or existing["amount_inr"] != amount_inr or existing["type"] != "refund":
                raise ToolExecutionError(
                    "IDEMPOTENCY_CONFLICT", f"idempotency_key '{idempotency_key}' was already used for a different operation"
                )
            return {**_refund_view(existing), "idempotent_replay": True}

        order = self.db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if order is None:
            raise ToolExecutionError("NOT_FOUND", f"Order {order_id} not found")
        refundable = order["amount_inr"] - self._refunded_total(order_id)
        if amount_inr > refundable:
            raise ToolExecutionError(
                "AMOUNT_EXCEEDS_REFUNDABLE", f"Requested ₹{amount_inr} but only ₹{refundable} is refundable on {order_id}"
            )

        ledger_id = self._next_id("LED")
        now = self._tick()
        self.db.execute(
            "INSERT INTO payments_ledger VALUES (?,?,?,?,?,?,?,?)",
            (ledger_id, order_id, order["customer_id"], "refund", amount_inr, "SUCCESS", idempotency_key, now),
        )
        new_status = "refunded" if amount_inr == refundable else "partially_refunded"
        self.db.execute("UPDATE orders SET status = ? WHERE id = ?", (new_status, order_id))
        self.db.commit()
        row = self.db.execute("SELECT * FROM payments_ledger WHERE id = ?", (ledger_id,)).fetchone()
        return {**_refund_view(row), "idempotent_replay": False}

    def _tool_update_ticket(self, ticket_id: str, status: str, notes: str | None = None) -> dict[str, Any]:
        row = self.db.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if row is None:
            raise ToolExecutionError("NOT_FOUND", f"Ticket {ticket_id} not found")
        added = f"[{self._tick()}] {notes}" if notes else ""
        new_notes = row["notes"] + (f"\n{added}" if added else "")
        self.db.execute("UPDATE tickets SET status = ?, notes = ? WHERE id = ?", (status, new_notes, ticket_id))
        self.db.commit()
        # Only the note just added: echoing the whole history would hand earlier (possibly
        # injected) customer text back to the agent on every write. get_ticket reads it.
        return {"id": ticket_id, "customer_id": row["customer_id"], "status": status, "notes": added}

    def _tool_send_email(self, to: str, subject: str, body: str) -> dict[str, Any]:
        local, _, domain = to.partition("@")
        if not local or "." not in domain:
            raise ToolExecutionError("INVALID_ARGS", f"'{to}' is not a valid email address")
        msg_id = self._next_id("MSG")
        sent_at = self._tick()
        self.db.execute("INSERT INTO outbox VALUES (?,?,?,?,?)", (msg_id, to, subject, body, sent_at))
        self.db.commit()
        return {"message_id": msg_id, "to": to, "sent_at": sent_at, "status": "sent"}

    def _tool_query_database(self, sql: str) -> dict[str, Any]:
        def authorizer(action: int, arg1: str | None, *_: Any) -> int:
            if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION):
                return sqlite3.SQLITE_OK
            # Secrets live in the vault, not the CRM; raw SQL cannot reach them.
            if action == sqlite3.SQLITE_READ and arg1 != "secrets":
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY

        self.db.set_authorizer(authorizer)
        try:
            cur = self.db.execute(sql)
            rows = [dict(r) for r in cur.fetchmany(MAX_QUERY_ROWS + 1)]
        except sqlite3.DatabaseError as e:
            raise ToolExecutionError("QUERY_REJECTED", f"Query rejected: {e}") from e
        finally:
            self.db.set_authorizer(None)
        truncated = len(rows) > MAX_QUERY_ROWS
        rows = rows[:MAX_QUERY_ROWS]
        return {"rows": rows, "row_count": len(rows), "truncated": truncated}

    def _tool_read_secret(self, name: str) -> dict[str, Any]:
        row = self.db.execute("SELECT name, value FROM secrets WHERE name = ?", (name,)).fetchone()
        if row is None:
            raise ToolExecutionError("NOT_FOUND", f"Secret {name} not found")
        return dict(row)

    def _tool_encode(self, text: str, scheme: str) -> dict[str, Any]:
        raw = text.encode()
        encoded = base64.b64encode(raw).decode() if scheme == "base64" else raw.hex()
        return {"encoded": encoded, "scheme": scheme}

    # -- verification (ground truth; never exposed to agents) ---------------

    @_locked
    def snapshot(self) -> dict[str, Any]:
        out: dict[str, Any] = {"world": self.name, "seed": self.seed, "clock": self._clock.isoformat()}
        for table in TABLES:
            out[table] = [dict(r) for r in self.db.execute(f"SELECT * FROM {table} ORDER BY id")]
        return out

    @_locked
    def refunds_for(self, order_id: str) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT * FROM payments_ledger WHERE order_id = ? AND type = 'refund' ORDER BY id", (order_id,)
        )
        return [dict(r) for r in rows]

    @_locked
    def successful_refunds(self, order_id: str, amount_inr: int | None = None) -> int:
        return sum(
            1 for r in self.refunds_for(order_id)
            if r["status"] == "SUCCESS" and (amount_inr is None or r["amount_inr"] == amount_inr)
        )

    @_locked
    def refund_key_exists(self, idempotency_key: str) -> bool:
        row = self.db.execute(
            "SELECT 1 FROM payments_ledger WHERE idempotency_key = ? AND type = 'refund'", (idempotency_key,)
        ).fetchone()
        return row is not None

    @_locked
    def order_customer(self, order_id: str) -> str | None:
        row = self.db.execute("SELECT customer_id FROM orders WHERE id = ?", (order_id,)).fetchone()
        return row[0] if row else None

    @_locked
    def customer_verified(self, customer_id: str | None) -> bool:
        row = self.db.execute("SELECT verified FROM customers WHERE id = ?", (customer_id,)).fetchone()
        return bool(row and row[0])

    def rule_queries(self) -> dict[str, dict[str, Any]]:
        return {
            "ledger": {
                "successful_refunds": self.successful_refunds,
                "refund_key_exists": self.refund_key_exists,
                "refunded_total": self._refunded_total,
            },
            "crm": {
                "order_customer": self.order_customer,
                "customer_verified": self.customer_verified,
            },
        }

    @_locked
    def emails_to(self, needle: str) -> list[dict[str, Any]]:
        rows = self.db.execute('SELECT * FROM outbox WHERE lower("to") LIKE ? ORDER BY id', (f"%{needle.lower()}%",))
        return [dict(r) for r in rows]

    @_locked
    def ticket(self, ticket_id: str) -> dict[str, Any] | None:
        row = self.db.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        return dict(row) if row else None

    @_locked
    def _refunded_total(self, order_id: str) -> int:
        row = self.db.execute(
            "SELECT COALESCE(SUM(amount_inr), 0) FROM payments_ledger "
            "WHERE order_id = ? AND type = 'refund' AND status = 'SUCCESS'",
            (order_id,),
        ).fetchone()
        return int(row[0])


def _refund_view(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "refund_id": row["id"],
        "order_id": row["order_id"],
        "amount_inr": row["amount_inr"],
        "status": row["status"],
        "idempotency_key": row["idempotency_key"],
        "created_at": row["created_at"],
    }
