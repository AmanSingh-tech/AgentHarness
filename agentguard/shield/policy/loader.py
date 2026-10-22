"""Load and validate policy YAML into typed objects, with errors that point at
the offending YAML line."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from agentguard.shield.policy.model import Policy

POLICIES_DIR = Path(__file__).parent.parent / "policies"
DEFAULT_POLICY = POLICIES_DIR / "default.yaml"


class PolicyError(ValueError):
    def __init__(self, source: str, problems: list[str]) -> None:
        self.source = source
        self.problems = problems
        super().__init__(f"{source}: invalid policy\n" + "\n".join(f"  {p}" for p in problems))


def load_policy(ref: str | Path | None = None) -> Policy:
    """`ref` is a path, a built-in policy name (e.g. "default"), or None for the default."""
    path = resolve_policy_path(ref)
    return parse_policy(path.read_text(), source=str(path))


def resolve_policy_path(ref: str | Path | None) -> Path:
    if ref is None:
        return DEFAULT_POLICY
    p = Path(ref)
    if p.is_file():
        return p
    builtin = POLICIES_DIR / f"{ref}.yaml"
    if builtin.is_file():
        return builtin
    known = sorted(f.stem for f in POLICIES_DIR.glob("*.yaml"))
    raise FileNotFoundError(f"policy '{ref}' not found (built-in: {known})")


def parse_policy(text: str, source: str = "<policy>") -> Policy:
    try:
        node = yaml.compose(text)
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f"line {mark.line + 1}: " if mark else ""
        raise PolicyError(source, [f"{where}YAML syntax error: {getattr(e, 'problem', e)}"]) from None
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise PolicyError(source, ["line 1: a policy must be a mapping"])
    try:
        return Policy.model_validate(data)
    except ValidationError as e:
        problems = []
        for err in e.errors():
            loc = [p for p in err["loc"] if not (isinstance(p, str) and p.startswith(("function-", "literal[")))]
            line = _line_of(node, loc)
            path = ".".join(str(p) for p in loc) or "<root>"
            msg = err["msg"].removeprefix("Value error, ")
            problems.append(f"line {line}: {path}: {msg}" if line else f"{path}: {msg}")
        raise PolicyError(source, problems) from None


def _line_of(node: Any, loc: list[Any]) -> int | None:
    """1-based line of the deepest YAML node that `loc` reaches."""
    line = node.start_mark.line + 1 if node is not None else None
    for part in loc:
        if isinstance(node, yaml.MappingNode):
            child = next((v for k, v in node.value if k.value == str(part)), None)
            if child is None:
                # an unexpected key is reported at the key itself
                key = next((k for k, _ in node.value if k.value == str(part)), None)
                return key.start_mark.line + 1 if key is not None else line
            node = child
        elif isinstance(node, yaml.SequenceNode) and isinstance(part, int) and part < len(node.value):
            node = node.value[part]
        else:
            break
        line = node.start_mark.line + 1
    return line
