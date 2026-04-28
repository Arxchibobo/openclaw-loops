"""Step 8 · 通知反馈 (卡点: bobo 微信是唯一接口 → 通过 bridge 解耦)."""
from __future__ import annotations

from typing import Any

from core import bridge
from core.state import kv_get, kv_set
from loops.base import BaseStep


class Step(BaseStep):
    LOOP = "bot_listing"
    KEY = "notify"

    def plan(self, ctx: dict[str, Any]) -> str:
        return "把 step6 反馈 + step7 决策汇总成消息发往 wechat/slack 桥"

    def synthetic_metrics(self, ctx: dict[str, Any]) -> dict[str, Any]:
        return {"notification_delivered": True, "channels": 2}

    def execute(self, ctx: dict[str, Any]) -> dict[str, Any]:
        feedback = kv_get("bot_listing", "feedback", []) or []
        decision = kv_get("bot_listing", "optimization") or {}
        msg = (f"[bot_listing] feedback_items={len(feedback)} "
               f"optimize={len(decision.get('to_optimize', []))} "
               f"retire={len(decision.get('to_retire', []))}")
        delivered = 0
        for ch in ("wechat", "slack", "log"):
            if bridge.send(ch, msg, meta={"loop": "bot_listing"}):
                delivered += 1
        kv_set("bot_listing", "last_notify", {"msg": msg, "delivered": delivered})
        return {"metrics": {"notification_delivered": delivered > 0,
                            "channels": delivered}}

    def read_metrics(self, ctx: dict[str, Any]) -> dict[str, Any]:
        last = kv_get("bot_listing", "last_notify") or {}
        return {"notification_delivered": bool(last.get("delivered")),
                "channels": int(last.get("delivered", 0))}
