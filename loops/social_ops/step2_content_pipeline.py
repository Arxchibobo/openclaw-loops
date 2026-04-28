"""Step 2 · 内容生产 + 发布
卡点: 无法持续性工作，容易陷入混乱 → 用 production_queue + 当日目标解决."""
from __future__ import annotations

from datetime import date
from typing import Any

from core.state import kv_get, kv_set
from loops.base import BaseStep

DAILY_TARGET = 2  # default: 2 posts per day


class Step(BaseStep):
    LOOP = "social_ops"
    KEY = "content_pipeline"

    def plan(self, ctx: dict[str, Any]) -> str:
        return ("基于 calendar 当天 themes 生成 caption + hashtag 草稿，"
                "推入 production_queue，记录 daily_output")

    def synthetic_metrics(self, ctx: dict[str, Any]) -> dict[str, Any]:
        return {"daily_output": 2, "target": DAILY_TARGET, "queue_depth": 4}

    def execute(self, ctx: dict[str, Any]) -> dict[str, Any]:
        cal = kv_get("social_ops", "calendar", []) or []
        today = date.today().isoformat()
        themes: list[str] = []
        for d in cal:
            if d["date"] == today:
                themes = d["themes"]
                break
        drafts = [{
            "theme": t,
            "caption": f"Exploring {t}: what changed this week.",
            "hashtags": [f"#{t.replace(' ', '')}", "#ai", "#myshell"],
            "status": "draft",
        } for t in themes]

        queue = kv_get("social_ops", "production_queue", []) or []
        queue.extend(drafts)
        kv_set("social_ops", "production_queue", queue)

        # daily_output is what *would* be published; without a real publisher we
        # promote the first DAILY_TARGET drafts to published
        published_today = drafts[:DAILY_TARGET]
        kv_set("social_ops", f"published:{today}", published_today)

        return {"metrics": {"daily_output": len(published_today),
                            "target": DAILY_TARGET,
                            "queue_depth": len(queue)}}

    def read_metrics(self, ctx: dict[str, Any]) -> dict[str, Any]:
        today = date.today().isoformat()
        published = kv_get("social_ops", f"published:{today}", []) or []
        queue = kv_get("social_ops", "production_queue", []) or []
        return {"daily_output": len(published), "target": DAILY_TARGET,
                "queue_depth": len(queue)}
