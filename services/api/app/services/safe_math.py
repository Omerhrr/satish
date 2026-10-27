"""Exact arithmetic for Satish AI without eval(): a tiny AST walker that only
allows numbers, + - * / // % **, parentheses and a few pure functions."""

from __future__ import annotations

import ast
import operator

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
_UN = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {"round": round, "min": min, "max": max, "abs": abs, "sum": lambda *a: sum(a[0] if len(a) == 1 and isinstance(a[0], list) else a)}


def evaluate(expression: str) -> float | int:
    import re

    # "2,500" -> 2500, but keep commas between arguments: max(1, 2).
    text = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", expression or "").replace("×", "*").replace("÷", "/").strip()
    if not text or len(text) > 300:
        raise ValueError("expression is empty or too long")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise ValueError("couldn't read that expression") from exc

    def walk(n: ast.AST):
        if isinstance(n, ast.Expression):
            return walk(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _BIN:
            left, right = walk(n.left), walk(n.right)
            if isinstance(n.op, ast.Pow) and (abs(right) > 100 or abs(left) > 1e12):
                raise ValueError("power too large")
            return _BIN[type(n.op)](left, right)
        if isinstance(n, ast.UnaryOp) and type(n.op) in _UN:
            return _UN[type(n.op)](walk(n.operand))
        if isinstance(n, ast.List):
            return [walk(e) for e in n.elts]
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FUNCS and not n.keywords:
            return _FUNCS[n.func.id](*[walk(a) for a in n.args])
        raise ValueError("only numbers and + - * / % ** ( ) round min max sum abs are allowed")

    try:
        result = walk(tree)
    except ZeroDivisionError as exc:
        raise ValueError("division by zero") from exc
    if isinstance(result, float):
        result = round(result, 10)
    return result
