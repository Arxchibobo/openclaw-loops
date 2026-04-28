from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .logger import get_logger

log = get_logger("openclaw.verifier")


@dataclass
class VerifyResult:
    ok: bool
    expression: str
    detail: str
    metrics: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "expression": self.expression,
                "detail": self.detail, "metrics": self.metrics}


def _safe_eval(expr: str, ctx: dict[str, Any]) -> bool:
    """Allow only simple comparisons / boolean keys in verify expressions."""
    expr = expr.strip()
    if not expr:
        return True
    # bare key truthiness: e.g. "demands_recorded"
    if expr in ctx:
        return bool(ctx[expr])
    # simple comparison: "kw_count >= 50"
    for op, fn in (
        (">=", lambda a, b: a >= b),
        ("<=", lambda a, b: a <= b),
        ("==", lambda a, b: a == b),
        ("!=", lambda a, b: a != b),
        (">",  lambda a, b: a > b),
        ("<",  lambda a, b: a < b),
    ):
        if op in expr:
            left, right = (s.strip() for s in expr.split(op, 1))
            lv = ctx.get(left, left)
            try:
                rv = float(right) if "." in right else int(right)
            except ValueError:
                rv = ctx.get(right, right)
            try:
                return bool(fn(float(lv), float(rv)))
            except (TypeError, ValueError):
                return bool(fn(lv, rv))
    return bool(ctx.get(expr, False))


def verify(expression: str, metrics: dict[str, Any]) -> VerifyResult:
    ok = _safe_eval(expression, metrics)
    detail = f"{expression} → {ok}"
    log.info("verify", extra={"expression": expression, "ok": ok, "metrics": metrics})
    return VerifyResult(ok=ok, expression=expression, detail=detail, metrics=metrics)


VerifyFn = Callable[[dict[str, Any]], VerifyResult]
