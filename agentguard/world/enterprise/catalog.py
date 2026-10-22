"""The enterprise system catalog: each mock system is declared in `systems/<name>.yaml`.

    system: idp
    title: Identity provider
    description: Workforce sign-in, MFA factors, groups and app assignments.
    collections:
      users: {fields: {login: string, email: string, status: string, groups: array}}
    operations:
      list_users:   {kind: list, collection: users, filters: [status, department], labels: [PII]}
      get_user:     {kind: get, collection: users}
      suspend_user: {kind: transition, collection: users, set: {status: SUSPENDED}, when: {status: [ACTIVE]}}

Operation kinds:
    list         equality filters (all optional unless `required`), newest-last
    get          one record by id
    search       case-insensitive text match over `fields`
    create       a new record from `fields` (`required` ones must be given); `unique` key tuple
    update       change any of `fields` on one record
    transition   set fixed values (`set`), optionally only `when` fields have one of the given values
    transition_where   `set` on every record matching all `keys` arguments (e.g. revoke all sessions)
    delete       remove one record by id
    delete_where remove the records matching every `keys` argument
    append       add a timestamped line to a text or list field (`field`)

Each operation becomes a ToolSpec named `<system>_<operation>`. `side_effect` defaults to
read for list/get/search and write otherwise; `irreversible`, `labels` (PII, SECRET,
UNTRUSTED) and `description` are optional. Everything is validated when the catalog loads.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentguard.core.models import DataLabel, SideEffect, ToolSpec

SYSTEMS_DIR = Path(__file__).parent / "systems"
FIELD_TYPES = {"string", "integer", "number", "boolean", "array", "object", "any"}
READ_KINDS = {"list", "get", "search"}
Kind = Literal["list", "get", "search", "create", "update", "transition", "transition_where", "delete",
               "delete_where", "append"]


class Collection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = ""
    fields: dict[str, str] = Field(default_factory=dict)  # name -> type; `id` is implicit
    id_prefix: str = ""  # ids minted by `create`, e.g. "INC" -> INC0001

    @model_validator(mode="after")
    def _types(self) -> "Collection":
        bad = {k: v for k, v in self.fields.items() if v not in FIELD_TYPES}
        if bad:
            raise ValueError(f"unknown field types {bad} (use {sorted(FIELD_TYPES)})")
        return self


class Operation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Kind
    collection: str
    description: str = ""
    filters: list[str] = Field(default_factory=list)  # list
    fields: list[str] = Field(default_factory=list)  # search / create / update
    required: list[str] = Field(default_factory=list)  # list / create
    unique: list[str] = Field(default_factory=list)  # create
    set: dict[str, Any] = Field(default_factory=dict)  # transition
    when: dict[str, list[Any]] = Field(default_factory=dict)  # transition precondition
    keys: list[str] = Field(default_factory=list)  # delete_where
    field: str | None = None  # append
    defaults: dict[str, Any] = Field(default_factory=dict)  # create
    side_effect: SideEffect | None = None
    irreversible: bool = False
    labels: list[DataLabel] = Field(default_factory=list)


class System(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system: str
    title: str
    description: str = ""
    collections: dict[str, Collection]
    operations: dict[str, Operation]

    @model_validator(mode="after")
    def _consistent(self) -> "System":
        for name, op in self.operations.items():
            where = f"{self.system}.{name}"
            coll = self.collections.get(op.collection)
            if coll is None:
                raise ValueError(f"{where}: unknown collection '{op.collection}'")
            known = set(coll.fields) | {"id"}
            used = {
                "filters": op.filters, "fields": op.fields, "required": op.required, "unique": op.unique,
                "set": list(op.set), "when": list(op.when), "keys": op.keys, "defaults": list(op.defaults),
                "field": [op.field] if op.field else [],
            }
            for what, names in used.items():
                unknown = sorted(set(names) - known)
                if unknown:
                    raise ValueError(f"{where}: {what} name unknown field(s) {unknown} of '{op.collection}'")
            if op.kind in ("transition", "transition_where") and not op.set:
                raise ValueError(f"{where}: a transition needs `set`")
            if op.kind in ("delete_where", "transition_where") and not op.keys:
                raise ValueError(f"{where}: {op.kind} needs `keys`")
            if op.kind == "append" and not op.field:
                raise ValueError(f"{where}: append needs `field`")
            if op.kind in ("search", "update") and not op.fields:
                raise ValueError(f"{where}: {op.kind} needs `fields`")
        return self

    def field_type(self, collection: str, name: str) -> str:
        return "string" if name == "id" else self.collections[collection].fields.get(name, "any")

    def tool_specs(self) -> list[ToolSpec]:
        return [self._spec(name, op) for name, op in self.operations.items()]

    def _schema(self, op: Operation) -> dict[str, Any]:
        def prop(field: str) -> dict[str, Any]:
            t = self.field_type(op.collection, field)
            return {} if t == "any" else {"type": t}

        props: dict[str, Any]
        required: list[str]
        if op.kind == "list":
            # a filter on an array field takes one value: records whose array contains it
            props = {f: ({} if self.field_type(op.collection, f) == "array" else prop(f)) for f in op.filters}
            props["limit"] = {"type": "integer", "minimum": 1, "maximum": 500}
            required = list(op.required)
        elif op.kind == "search":
            props = {"query": {"type": "string", "description": f"text matched against {', '.join(op.fields)}"},
                     "limit": {"type": "integer", "minimum": 1, "maximum": 100}}
            required = ["query"]
        elif op.kind == "create":
            props = {f: prop(f) for f in op.fields}
            required = list(op.required)
        elif op.kind == "update":
            props = {"id": {"type": "string"}, **{f: prop(f) for f in op.fields}}
            required = ["id"]
        elif op.kind in ("delete_where", "transition_where"):
            props = {k: prop(k) for k in op.keys}
            required = list(op.keys)
        elif op.kind == "append":
            props = {"id": {"type": "string"}, "text": {"type": "string"}}
            required = ["id", "text"]
        else:  # get, transition, delete
            props = {"id": {"type": "string"}}
            required = ["id"]
        return {"type": "object", "properties": props, "required": required, "additionalProperties": False}

    def _spec(self, name: str, op: Operation) -> ToolSpec:
        side = op.side_effect or (SideEffect.READ if op.kind in READ_KINDS else SideEffect.WRITE)
        return ToolSpec(
            name=f"{self.system}_{name}",
            description=f"[{self.title}] {op.description or _default_description(name, op)}",
            input_schema=self._schema(op),
            side_effect=side,
            irreversible=op.irreversible or op.kind in ("delete", "delete_where"),
            returns_labels=tuple(op.labels),
        )


def _default_description(name: str, op: Operation) -> str:
    noun = op.collection.replace("_", " ")
    return {
        "list": f"List {noun}" + (f", filtered by {', '.join(op.filters)}" if op.filters else "") + ".",
        "get": f"Read one of the {noun} by id.",
        "search": f"Search {noun} by {', '.join(op.fields)}.",
        "create": f"Create one of the {noun}.",
        "update": f"Update {', '.join(op.fields)} on one of the {noun}.",
        "transition": f"Set {', '.join(f'{k}={v}' for k, v in op.set.items())} on one of the {noun}.",
        "transition_where": f"Set {', '.join(f'{k}={v}' for k, v in op.set.items())} on every one of the {noun} "
                            f"matching {', '.join(op.keys)}.",
        "delete": f"Delete one of the {noun}.",
        "delete_where": f"Remove the {noun} matching {', '.join(op.keys)}.",
        "append": f"Add a note to {op.field} on one of the {noun}.",
    }[op.kind]


@lru_cache(maxsize=1)
def catalog() -> dict[str, System]:
    systems: dict[str, System] = {}
    for path in sorted(SYSTEMS_DIR.glob("*.yaml")):
        try:
            s = System.model_validate(yaml.safe_load(path.read_text()))
        except Exception as e:
            raise ValueError(f"{path.name}: {e}") from e
        if s.system != path.stem:
            raise ValueError(f"{path.name}: system name '{s.system}' must match the file name")
        systems[s.system] = s
    return systems
