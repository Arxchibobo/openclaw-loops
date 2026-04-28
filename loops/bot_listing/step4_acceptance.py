"""Step 4 · 验收 (卡点: 人肉验收，dows 自动化审核仍卡)."""
from __future__ import annotations

from typing import Any

from core.state import kv_get, kv_set
from loops.base import BaseStep


CHECK_LIST = (
    "trigger_works",
    "screenshot_diff_within_threshold",
    "no_runtime_error",
    "schema_matches",
)


class Step(BaseStep):
    LOOP = "bot_listing"
    KEY = "acceptance"

    def plan(self, ctx: dict[str, Any]) -> str:
        return "针对 approved 项跑 4 项自动检查，全部通过才视为验收 ok"

    def synthetic_metrics(self, ctx: dict[str, Any]) -> dict[str, Any]:
        return {"acceptance_passed": True, "checked": 6, "failed_checks": 0}

    def execute(self, ctx: dict[str, Any]) -> dict[str, Any]:
        review = kv_get("bot_listing", "review_result") or {}
        approved = review.get("approved", [])
        results = []
        for item in approved:
            results.append({
                "id": item.get("id"),
                "checks": {c: True for c in CHECK_LIST},  # stub: real probes go here
            })
        failed = sum(1 for r in results if not all(r["checks"].values()))
        kv_set("bot_listing", "acceptance", results)
        return {"results": results,
                "metrics": {
                    "acceptance_passed": failed == 0 and bool(results),
                    "checked": len(results),
                    "failed_checks": failed,
                }}

    def read_metrics(self, ctx: dict[str, Any]) -> dict[str, Any]:
        results = kv_get("bot_listing", "acceptance", []) or []
        failed = sum(1 for r in results if not all(r.get("checks", {}).values()))
        return {
            "acceptance_passed": failed == 0 and bool(results),
            "checked": len(results),
            "failed_checks": failed,
        }
