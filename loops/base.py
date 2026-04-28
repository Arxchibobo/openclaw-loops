"""Base step interface: every step file defines a `Step` class subclassing this."""
from __future__ import annotations

from typing import Any

from core.logger import get_logger


class BaseStep:
    KEY: str = ""
    LOOP: str = ""

    def __init__(self) -> None:
        self.log = get_logger(f"openclaw.{self.LOOP}.{self.KEY}")

    # ---- mode hooks ----
    def dry(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Dry-run: describe what would happen, return synthetic metrics."""
        plan = self.plan(ctx)
        self.log.info("dry", extra={"plan": plan})
        return {"plan": plan, "metrics": self.synthetic_metrics(ctx)}

    def run(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Real execution. Subclass must implement `execute`."""
        result = self.execute(ctx)
        metrics = result.get("metrics") if isinstance(result, dict) else None
        if not metrics:
            metrics = self.metrics_from_result(result, ctx)
        self.log.info("run.done", extra={"metrics": metrics})
        return {"result": result, "metrics": metrics}

    def metrics(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Verify-mode: read the latest measurable state, return metrics dict."""
        return {"metrics": self.read_metrics(ctx)}

    # ---- subclass hooks ----
    def plan(self, ctx: dict[str, Any]) -> str:
        return f"{self.LOOP}.{self.KEY}: dry-run plan placeholder"

    def synthetic_metrics(self, ctx: dict[str, Any]) -> dict[str, Any]:
        return {}

    def execute(self, ctx: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(f"{self.LOOP}.{self.KEY} `execute` not implemented yet")

    def read_metrics(self, ctx: dict[str, Any]) -> dict[str, Any]:
        return {}

    def metrics_from_result(self, result: Any, ctx: dict[str, Any]) -> dict[str, Any]:
        return {}
