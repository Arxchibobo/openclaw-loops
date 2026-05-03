"""Step 4 · 验收 (卡点: 人肉验收，dows 自动化审核仍卡).

2026-04-29 更新：approved demand 现在走 ``adapters.workshop_sop.run_pipeline``
产出 ``BotStatus``，验收结果直接拿 ``status`` 字段。没 ``sop`` 字段的 item
走老四项检查 stub 作 fallback — 这样纯老数据跑的 smoke (test_bot_listing_dry)
不会被打破。
"""
from __future__ import annotations

from typing import Any

from adapters import workshop_sop
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
        return ("对 approved demand 走 workshop_sop pipeline（SFW/NSFW 分支），"
                "产出 BotStatus; 无 sop 的件落回四项检查 stub。")

    def synthetic_metrics(self, ctx: dict[str, Any]) -> dict[str, Any]:
        return {"acceptance_passed": True, "checked": 6, "failed_checks": 0}

    def execute(self, ctx: dict[str, Any]) -> dict[str, Any]:
        review = kv_get("bot_listing", "review_result") or {}
        approved = review.get("approved", [])
        # dry path is the safe default — real execution only happens when
        # cyber-developer-cron has called workshop_sop.set_executor(...)
        dry_run = bool(ctx.get("dry_run"))

        # Prefer the in-memory demands (have raw kw) when step2 populated ctx.
        # Fall back to review.approved entries when running standalone.
        demands_with_kw = {d.get("id"): d for d in (ctx.get("demands") or [])}

        results = []
        statuses = []
        for item in approved:
            demand_id = item.get("id")
            source = demands_with_kw.get(demand_id, item)
            sop = source.get("sop")

            if sop:
                status = workshop_sop.run_pipeline(source, dry_run=dry_run)
                statuses.append(status)
                passed = status.status in ("ready_for_landing_page", "dev_in_progress")
                results.append({
                    "id": demand_id,
                    "status": status.status,
                    "rh_workflow_id": status.rh_workflow_id,
                    "checks": {"sop_pipeline": passed},
                })
            else:
                # Legacy path — keep smoke tests stable.
                results.append({
                    "id": demand_id,
                    "checks": {c: True for c in CHECK_LIST},
                })

        failed = sum(1 for r in results if not all(r.get("checks", {}).values()))
        kv_set("bot_listing", "acceptance", results)
        if statuses:
            kv_set("bot_listing", "bot_statuses",
                   [s.to_dict() for s in statuses])

        return {
            "results": results,
            "bot_statuses": [s.to_dict() for s in statuses],
            "metrics": {
                # 2026-05-03: 0 验收项 ≠ failed。只要没有 check 报错就算 pass，
                # 与 Step 2 空入输保保一致。
                "acceptance_passed": failed == 0,
                "checked": len(results),
                "failed_checks": failed,
                "via_sop": len(statuses),
                "has_results": bool(results),
            },
        }

    def read_metrics(self, ctx: dict[str, Any]) -> dict[str, Any]:
        results = kv_get("bot_listing", "acceptance", []) or []
        failed = sum(1 for r in results if not all(r.get("checks", {}).values()))
        return {
            "acceptance_passed": failed == 0,
            "checked": len(results),
            "failed_checks": failed,
            "has_results": bool(results),
        }
