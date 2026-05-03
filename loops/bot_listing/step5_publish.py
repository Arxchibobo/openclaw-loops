"""Step 5 · 通过上架 (卡点: amy 上架龙虾 ↔ bo 龙虾未打通)."""
from __future__ import annotations

from typing import Any

from adapters import lobster
from core.state import kv_get, kv_set
from loops.base import BaseStep


class Step(BaseStep):
    LOOP = "bot_listing"
    KEY = "publish"

    def plan(self, ctx: dict[str, Any]) -> str:
        return "调用 amy/bo 双侧 lobster, diff 并触发 reconcile，最终一致才发布"

    def synthetic_metrics(self, ctx: dict[str, Any]) -> dict[str, Any]:
        return {"amy_bo_consistent": True, "published": 6}

    def execute(self, ctx: dict[str, Any]) -> dict[str, Any]:
        accepted = kv_get("bot_listing", "acceptance", []) or []
        # 2026-05-03: amy/bo 对账是关键的日常信号，不能依赖上游有无 acceptance。
        # 没有 demand/acceptance 时，仍要抓 amy/bo 最新快照跑 diff 输出 only_amy/only_bo。
        amy = lobster.fetch_state("amy")
        bo = lobster.fetch_state("bo")
        d = lobster.diff(amy, bo)
        published = [a["id"] for a in accepted] if (accepted and d["consistent"]) else []
        kv_set("bot_listing", "publish", {"published": published, "diff": d})
        return {"metrics": {"amy_bo_consistent": d["consistent"],
                            "published": len(published),
                            "only_amy": len(d["only_amy"]),
                            "only_bo": len(d["only_bo"]),
                            "has_acceptance": bool(accepted)}}

    def read_metrics(self, ctx: dict[str, Any]) -> dict[str, Any]:
        rec = kv_get("bot_listing", "publish") or {}
        diff = rec.get("diff", {})
        return {"amy_bo_consistent": bool(diff.get("consistent", False)),
                "published": len(rec.get("published", []))}
