"""Step 2 · bot 提需求 (卡点: bobo 微信提需 — 通过 bridge 自动收口)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core import bridge
from core.state import kv_get, kv_set
from loops.base import BaseStep


class Step(BaseStep):
    LOOP = "bot_listing"
    KEY = "demand_intake"

    def plan(self, ctx: dict[str, Any]) -> str:
        return ("将 step1 的 keywords 转换成 bot 需求草稿，"
                "推送到微信桥并落入 demands.json 等待响应")

    def synthetic_metrics(self, ctx: dict[str, Any]) -> dict[str, Any]:
        return {"demands_recorded": True, "draft_count": 8}

    def execute(self, ctx: dict[str, Any]) -> dict[str, Any]:
        kws = kv_get("bot_listing", "latest_keywords", []) or []
        # take the top-N keywords as demand candidates
        candidates = sorted(kws, key=lambda k: -int(k.get("volume", 0)))[:10]
        demands = [{
            "id": f"D{int(datetime.now(timezone.utc).timestamp())}-{i}",
            "kw": c["kw"],
            "source": "seo",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "draft",
        } for i, c in enumerate(candidates)]

        kv_set("bot_listing", "demands", demands)
        bridge.send("log", f"[demand-intake] queued {len(demands)} demands",
                    meta={"demands": [d["id"] for d in demands]})
        return {"demands": demands,
                "metrics": {"demands_recorded": bool(demands),
                            "draft_count": len(demands)}}

    def read_metrics(self, ctx: dict[str, Any]) -> dict[str, Any]:
        demands = kv_get("bot_listing", "demands", []) or []
        return {"demands_recorded": bool(demands), "draft_count": len(demands)}
