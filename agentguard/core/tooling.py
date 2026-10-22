"""Generate provider-specific tool schemas from a ToolSpec, and validate args.

Validation is deliberately a small, deterministic subset of JSON Schema
(required keys, no unknown keys, primitive types, enums). Every tool's
input_schema must stay within that subset.
"""

from __future__ import annotations

from typing import Any

from agentguard.core.models import ToolSpec

_JSON_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "object": (dict,),
    "array": (list,),
}


def to_anthropic(spec: ToolSpec) -> dict[str, Any]:
    return {"name": spec.name, "description": spec.description, "input_schema": spec.input_schema}


def to_openai(spec: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {"name": spec.name, "description": spec.description, "parameters": spec.input_schema},
    }


def to_gemini(spec: ToolSpec) -> dict[str, Any]:
    return {"name": spec.name, "description": spec.description, "parameters": spec.input_schema}


EXPORTERS = {"anthropic": to_anthropic, "openai": to_openai, "gemini": to_gemini}


def validate_args(spec: ToolSpec, args: dict[str, Any]) -> list[str]:
    """Return a list of human-readable problems; empty means valid."""
    schema = spec.input_schema
    props: dict[str, Any] = schema.get("properties", {})
    problems: list[str] = []

    if not isinstance(args, dict):
        return [f"arguments must be an object, got {type(args).__name__}"]

    for key in schema.get("required", []):
        if key not in args:
            problems.append(f"missing required argument '{key}'")

    for key, value in args.items():
        if key not in props:
            if schema.get("additionalProperties", False) is False:
                problems.append(f"unknown argument '{key}'")
            continue
        prop = props[key]
        expected = prop.get("type")
        if expected:
            py_types = _JSON_TYPES[expected]
            # bool is a subclass of int in Python; JSON treats them as distinct.
            if isinstance(value, bool) and bool not in py_types:
                problems.append(f"argument '{key}' must be {expected}, got boolean")
                continue
            if not isinstance(value, py_types):
                problems.append(f"argument '{key}' must be {expected}, got {type(value).__name__}")
                continue
        if "enum" in prop and value not in prop["enum"]:
            problems.append(f"argument '{key}' must be one of {prop['enum']}, got {value!r}")
        if "minimum" in prop and isinstance(value, (int, float)) and value < prop["minimum"]:
            problems.append(f"argument '{key}' must be >= {prop['minimum']}")

    return problems
