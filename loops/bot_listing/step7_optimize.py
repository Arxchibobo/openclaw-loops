"""Step 7 · 优化/下架替换 (Notion: Yes)."""
from __future__ import annotations

from typing import Any

from core.state import kv_get, kv_set
from loops.base import BaseStep

ERROR_THRESHOLD = 0.2  # >20% error → schedule retire


class Step(BaseStep):
    LOOP = "bot_listing"
    KEY = "optimize"

    def plan(self, ctx: dict[str, Any]) -> str:
        return "基于 feedback 计算优化/下架决策，生成 todo list"

    def synthetic_metrics(self, ctx: dict[str, Any]) -> dict[str, Any]:
        return {"optimization_decision": True, "to_optimize": 1, "to_retire": 0}

    def execute(self, ctx: dict[str, Any]) -> dict[str, Any]:
        feedback = kv_get("bot_listing", "feedback", []) or []
        to_optimize, to_retire = [], []
        for f in feedback:
            m = f.get("metrics", {})
            runs = max(int(m.get("runs_24h", 0)), 0)
            errors = max(int(m.get("errors_24h", 0)), 0)
            err_rate = (errors / runs) if runs else 0.0
            if runs == 0:
                to_optimize.append({"bot_id": f["bot_id"], "reason": "no traffic"})
            elif err_rate > ERROR_THRESHOLD:
                to_retire.append({"bot_id": f["bot_id"], "err_rate": err_rate})
        decision = {"to_optimize": to_optimize, "to_retire": to_retire}
        kv_set("bot_listing", "optimization", decision)
        return {"metrics": {"optimization_decision": True,
                            "to_optimize": len(to_optimize),
                            "to_retire": len(to_retire)}}

    def read_metrics(self, ctx: dict[str, Any]) -> dict[str, Any]:
        d = kv_get("bot_listing", "optimization") or {}
        return {"optimization_decision": bool(d),
                "to_optimize": len(d.get("to_optimize", [])),
                "to_retire": len(d.get("to_retire", []))}
