"""Step 3 · art站 workshop 审核 (卡点: 人肉审核)."""
from __future__ import annotations

from typing import Any

from adapters import workshop
from core.state import kv_get, kv_set
from loops.base import BaseStep


class Step(BaseStep):
    LOOP = "bot_listing"
    KEY = "workshop_review"

    def plan(self, ctx: dict[str, Any]) -> str:
        return "对 demands 调用规则引擎 + LLM 双道审核，保留 pending_human 队列"

    def synthetic_metrics(self, ctx: dict[str, Any]) -> dict[str, Any]:
        return {"review_decision_present": True, "approved": 6, "pending_human": 1}

    def execute(self, ctx: dict[str, Any]) -> dict[str, Any]:
        demands = kv_get("bot_listing", "demands", []) or []
        # demands lack scores in the stub path → assume score 0.8 unless blocked
        items = [{**d, "score": d.get("score", 0.8), "tags": d.get("tags", [])} for d in demands]
        result = workshop.review(items)
        kv_set("bot_listing", "review_result", result)
        return {"review": result,
                "metrics": {
                    "review_decision_present": bool(result),
                    "approved": len(result["approved"]),
                    "rejected": len(result["rejected"]),
                    "pending_human": len(result["pending_human"]),
                }}

    def read_metrics(self, ctx: dict[str, Any]) -> dict[str, Any]:
        r = kv_get("bot_listing", "review_result") or {}
        return {
            "review_decision_present": bool(r),
            "approved": len(r.get("approved", [])),
            "rejected": len(r.get("rejected", [])),
            "pending_human": len(r.get("pending_human", [])),
        }
