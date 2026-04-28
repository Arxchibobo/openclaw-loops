"""Step 4 · 自主判断每日流量 → 优化帖子/多渠道
卡点: 没有每日埋点 + KW 价值判断不稳定 → 这里实现 daily metrics + KW score model."""
from __future__ import annotations

from datetime import date
from typing import Any

from core.state import kv_get, kv_set
from loops.base import BaseStep


def kw_score(kw: dict[str, Any]) -> float:
    vol = float(kw.get("volume", 0))
    rising_bonus = 1.2 if kw.get("trend") == "rising" else 1.0
    return round(vol * rising_bonus, 2)


class Step(BaseStep):
    LOOP = "social_ops"
    KEY = "analytics"

    def plan(self, ctx: dict[str, Any]) -> str:
        return "采集当日 metrics + 重算 KW score，写入 metrics:{date}"

    def synthetic_metrics(self, ctx: dict[str, Any]) -> dict[str, Any]:
        return {"metrics_emitted": True, "kw_scored": 30}

    def execute(self, ctx: dict[str, Any]) -> dict[str, Any]:
        cleaned = kv_get("social_ops", "keywords_clean", []) or []
        scored = sorted(
            [{**k, "score": kw_score(k)} for k in cleaned],
            key=lambda x: -x["score"],
        )
        today = date.today().isoformat()
        published = kv_get("social_ops", f"published:{today}", []) or []
        eq = kv_get("social_ops", "engagement_queue", []) or []
        h = kv_get("social_ops", "x_health") or {}
        metrics = {
            "date": today,
            "kw_scored": len(scored),
            "top_kw": scored[0]["kw"] if scored else None,
            "published_today": len(published),
            "engagement_queue_depth": len(eq),
            "x_alive": bool(h.get("alive") or h.get("api_alive")),
        }
        kv_set("social_ops", f"metrics:{today}", metrics)
        kv_set("social_ops", "kw_scored", scored)
        return {"metrics": {**metrics, "metrics_emitted": True}}

    def read_metrics(self, ctx: dict[str, Any]) -> dict[str, Any]:
        today = date.today().isoformat()
        m = kv_get("social_ops", f"metrics:{today}") or {}
        return {**m, "metrics_emitted": bool(m)}
