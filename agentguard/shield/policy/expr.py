"""A tiny, deterministic expression language for policy `rules[].check`.

    check: "ledger.refund_key_exists(idempotency_key) or ledger.successful_refunds(order_id, amount_inr) == 0"

Allowed: literals, names (the call's arguments, plus `args` for the whole
dict), comparisons, and/or/not, + - * / on numbers, and calls of the form
`<namespace>.<function>(...)` where the backend exposes that function through
`ToolBackend.rule_queries()`. Nothing else parses: no attribute access on
values, no subscripts, no builtins, so a policy file cannot execute code.
"""

from __future__ import annotations

import ast
import operator
from typing import Any, Callable

_CMP = {
    ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt, ast.LtE: operator.le,
    ast.Gt: operator.gt, ast.GtE: operator.ge, ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b,
}
_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


class ExprError(ValueError):
    pass


class Expr:
    def __init__(self, source: str) -> None:
        self.source = source
        try:
            tree = ast.parse(source, mode="eval")
        except SyntaxError as e:
            raise ExprError(f"invalid expression {source!r}: {e.msg}") from None
        _validate(tree.body)
        self._tree = tree.body
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
        self.namespaces = {n.func.value.id for n in calls}  # type: ignore[attr-defined]  (shape checked above)
        self.names = sorted({n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} - self.namespaces)

    def evaluate(self, variables: dict[str, Any], queries: dict[str, dict[str, Callable[..., Any]]]) -> Any:
        return _eval(self._tree, variables, queries)


def _validate(node: ast.AST) -> None:
    if isinstance(node, ast.Constant):
        return
    if isinstance(node, ast.Name):
        return
    if isinstance(node, ast.BoolOp):
        for v in node.values:
            _validate(v)
        return
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.Not, ast.USub)):
        _validate(node.operand)
        return
    if isinstance(node, ast.Compare) and all(type(op) in _CMP for op in node.ops):
        _validate(node.left)
        for c in node.comparators:
            _validate(c)
        return
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        _validate(node.left)
        _validate(node.right)
        return
    if isinstance(node, (ast.List, ast.Tuple)):
        for e in node.elts:
            _validate(e)
        return
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and not node.keywords
    ):
        for a in node.args:
            _validate(a)
        return
    raise ExprError(f"unsupported syntax in rule expression: {ast.unparse(node)!r}")


def _eval(node: ast.AST, variables: dict[str, Any], queries: dict[str, dict[str, Callable[..., Any]]]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in variables:
            raise ExprError(f"unknown name '{node.id}'")
        return variables[node.id]
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            return all(_eval(v, variables, queries) for v in node.values)
        return any(_eval(v, variables, queries) for v in node.values)
    if isinstance(node, ast.UnaryOp):
        val = _eval(node.operand, variables, queries)
        return (not val) if isinstance(node.op, ast.Not) else -val
    if isinstance(node, ast.Compare):
        left = _eval(node.left, variables, queries)
        for op, comp in zip(node.ops, node.comparators):
            right = _eval(comp, variables, queries)
            if not _CMP[type(op)](left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.BinOp):
        return _BIN[type(node.op)](_eval(node.left, variables, queries), _eval(node.right, variables, queries))
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_eval(e, variables, queries) for e in node.elts]
    if isinstance(node, ast.Call):
        assert isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
        ns, fn = node.func.value.id, node.func.attr
        func = queries.get(ns, {}).get(fn)
        if func is None:
            raise ExprError(f"unknown query '{ns}.{fn}'")
        return func(*[_eval(a, variables, queries) for a in node.args])
    raise ExprError(f"cannot evaluate {ast.unparse(node)!r}")  # unreachable after _validate
