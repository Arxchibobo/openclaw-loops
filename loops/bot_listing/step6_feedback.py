"""Step 6 · 上架反馈 (Notion: Yes)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.state import kv_get, kv_set
from loops.base import BaseStep


class Step(BaseStep):
    LOOP = "bot_listing"
    KEY = "feedback"

    def plan(self, ctx: dict[str, Any]) -> str:
        return "拉取上线后 24h 数据(对接埋点)，落入 feedback 表"

    def synthetic_metrics(self, ctx: dict[str, Any]) -> dict[str, Any]:
        return {"feedback_collected": True, "items": 6}

    def execute(self, ctx: dict[str, Any]) -> dict[str, Any]:
        published = (kv_get("bot_listing", "publish") or {}).get("published", [])
        feedback = [{
            "bot_id": pid,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "metrics": {"runs_24h": 0, "errors_24h": 0, "stars": None},
        } for pid in published]
        kv_set("bot_listing", "feedback", feedback)
        return {"metrics": {"feedback_collected": bool(feedback),
                            "items": len(feedback)}}

    def read_metrics(self, ctx: dict[str, Any]) -> dict[str, Any]:
        f = kv_get("bot_listing", "feedback", []) or []
        return {"feedback_collected": bool(f), "items": len(f)}
