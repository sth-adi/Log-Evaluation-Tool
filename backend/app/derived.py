"""Math channels: evaluate a user formula over a log's channels.

A formula is a restricted Python expression, parsed with ``ast`` and evaluated over numpy
arrays. Only arithmetic, comparisons, channel names and the whitelisted functions below
are allowed; nothing else (attribute access, imports, subscripts) can run.

    rpm * 2 * pi / 60                  angular speed
    torque * rpm * pi / 30 / 1000      power in kW
    smooth(ect1, 2)                    2 s moving average
    deriv(vehicleSpeed) / 3.6          acceleration in m/s^2
    where(rpm > 11000, 1, 0)           flag
    ch("TimeSlip(-1)") + 1             channel whose name is not an identifier

Functions: abs sqrt exp log log10 sin cos tan floor ceil sign rad deg
           minimum(a, b) maximum(a, b) clip(x, lo, hi) where(cond, a, b)
           deriv(x) integ(x) smooth(x, seconds) lag(x, seconds)
Constants: pi, e, and t (time in seconds).
"""

from __future__ import annotations

import ast
import operator

import numpy as np
import pandas as pd

from .rates import reconstruct

MAX_EXPR_LEN = 500


class FormulaError(ValueError):
    """The formula is malformed, uses something not allowed, or names an unknown channel."""


_BIN = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: np.mod,
    ast.FloorDiv: np.floor_divide,
    ast.Pow: np.power,
}
_CMP = {
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
}


def _fill(x: np.ndarray) -> np.ndarray:
    """Linear fill of NaN gaps so calculus and smoothing do not spread them."""
    s = pd.Series(x)
    return s.interpolate(limit_direction="both").to_numpy(dtype=float)


class _Ctx:
    def __init__(self, columns: dict[str, np.ndarray], t: np.ndarray):
        self.columns = columns
        self.t = t
        dt = np.diff(t)
        self.rate = 1.0 / float(np.median(dt)) if dt.size and np.median(dt) > 0 else 1.0

    # --- calculus / filters -------------------------------------------------------------
    def deriv(self, x):
        x = np.asarray(x, dtype=float)
        bad = np.isnan(x)
        if bad.all():
            return x
        # a channel read slower than the log's rate is a staircase; differentiate the line
        # through its real readings, not the steps
        line = _fill(x) if bad.any() else reconstruct(self.t, x)
        out = np.gradient(line, self.t)
        out[bad] = np.nan
        return out

    def integ(self, x):
        x = np.nan_to_num(np.asarray(x, dtype=float))
        dt = np.diff(self.t, prepend=self.t[0])
        mid = (x + np.concatenate([[x[0]], x[:-1]])) / 2.0
        return np.cumsum(mid * dt)

    def smooth(self, x, seconds):
        n = max(int(round(float(seconds) * self.rate)), 1)
        return pd.Series(np.asarray(x, dtype=float)).rolling(n, center=True, min_periods=1).mean().to_numpy()

    def lag(self, x, seconds):
        n = int(round(float(seconds) * self.rate))
        x = np.asarray(x, dtype=float)
        if n == 0:
            return x
        out = np.full_like(x, np.nan)
        if n > 0:
            out[n:] = x[:-n] if n < len(x) else out[n:]
        else:
            out[:n] = x[-n:] if -n < len(x) else out[:n]
        return out

    def functions(self):
        return {
            "abs": np.abs, "sqrt": np.sqrt, "exp": np.exp, "log": np.log, "log10": np.log10,
            "sin": np.sin, "cos": np.cos, "tan": np.tan, "floor": np.floor, "ceil": np.ceil,
            "sign": np.sign, "rad": np.radians, "deg": np.degrees,
            "minimum": np.minimum, "maximum": np.maximum, "clip": np.clip, "where": np.where,
            "deriv": self.deriv, "integ": self.integ, "smooth": self.smooth, "lag": self.lag,
        }


def referenced_names(expr: str) -> set[str]:
    """Channel names a formula reads (identifiers and ch("...") calls), for dependency checks."""
    tree = _parse(expr)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "ch":
            if node.args and isinstance(node.args[0], ast.Constant):
                names.add(str(node.args[0].value))
        elif isinstance(node, ast.Name):
            names.add(node.id)
    return names


def _parse(expr: str) -> ast.AST:
    if not expr or not expr.strip():
        raise FormulaError("Formula is empty")
    if len(expr) > MAX_EXPR_LEN:
        raise FormulaError(f"Formula is longer than {MAX_EXPR_LEN} characters")
    try:
        return ast.parse(expr.strip(), mode="eval")
    except SyntaxError as e:
        raise FormulaError(f"Syntax error in formula: {e.msg}") from None


def evaluate(expr: str, columns: dict[str, np.ndarray], t: np.ndarray) -> np.ndarray:
    """Evaluate ``expr`` over ``columns`` (name -> array, all the length of ``t``)."""
    tree = _parse(expr)
    ctx = _Ctx(columns, t)
    funcs = ctx.functions()
    consts = {"pi": np.pi, "e": np.e, "t": t}
    n = len(t)

    def lookup(name: str):
        if name in columns:
            return np.asarray(columns[name], dtype=float)
        raise FormulaError(f"Unknown channel '{name}'")

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise FormulaError("Only numbers are allowed as constants")
            return node.value
        if isinstance(node, ast.Name):
            if node.id in columns:
                return lookup(node.id)
            if node.id in consts:
                return consts[node.id]
            if node.id in funcs or node.id == "ch":
                raise FormulaError(f"'{node.id}' is a function; call it like {node.id}(...)")
            raise FormulaError(f"Unknown channel '{node.id}'")
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
            a, b = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow) and np.max(np.abs(np.nan_to_num(b))) > 64:
                raise FormulaError("Exponent too large")
            with np.errstate(all="ignore"):
                return _BIN[type(node.op)](a, b)
        if isinstance(node, ast.UnaryOp):
            v = ev(node.operand)
            if isinstance(node.op, ast.USub):
                return -v
            if isinstance(node.op, ast.UAdd):
                return v
            if isinstance(node.op, ast.Not):
                return np.logical_not(v)
        if isinstance(node, ast.Compare):
            left = ev(node.left)
            result = None
            for op, comp in zip(node.ops, node.comparators):
                if type(op) not in _CMP:
                    raise FormulaError("Unsupported comparison")
                right = ev(comp)
                piece = _CMP[type(op)](left, right)
                result = piece if result is None else np.logical_and(result, piece)
                left = right
            return result
        if isinstance(node, ast.BoolOp):
            vals = [ev(v) for v in node.values]
            f = np.logical_and if isinstance(node.op, ast.And) else np.logical_or
            out = vals[0]
            for v in vals[1:]:
                out = f(out, v)
            return out
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.keywords:
                raise FormulaError("Only plain function calls are allowed")
            if node.func.id == "ch":
                if len(node.args) != 1 or not isinstance(node.args[0], ast.Constant):
                    raise FormulaError('ch() takes one quoted name, e.g. ch("TimeSlip(-1)")')
                return lookup(str(node.args[0].value))
            fn = funcs.get(node.func.id)
            if fn is None:
                raise FormulaError(f"Unknown function '{node.func.id}'")
            args = [ev(a) for a in node.args]
            try:
                with np.errstate(all="ignore"):
                    return fn(*args)
            except TypeError as e:
                raise FormulaError(f"Wrong arguments for {node.func.id}(): {e}") from None
        raise FormulaError(f"'{type(node).__name__}' is not allowed in a formula")

    out = ev(tree)
    out = np.asarray(out, dtype=float)
    if out.ndim == 0:
        out = np.full(n, float(out))
    if out.shape != (n,):
        raise FormulaError("Formula did not produce one value per sample")
    out = np.where(np.isfinite(out), out, np.nan)
    return out
