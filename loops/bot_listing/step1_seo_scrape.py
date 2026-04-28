"""Step 1 · seokw 抓取 (Notion: Yes，卡点 CLAWbo 抓取)."""
from __future__ import annotations

from typing import Any

from adapters import seo
from core.state import kv_get, kv_set
from loops.base import BaseStep


class Step(BaseStep):
    LOOP = "bot_listing"
    KEY = "seo_scrape"

    def plan(self, ctx: dict[str, Any]) -> str:
        return "fetch keywords from CLAWbo SEO endpoint, dedupe, persist snapshot"

    def synthetic_metrics(self, ctx: dict[str, Any]) -> dict[str, Any]:
        return {"keyword_count": 60, "fresh_pct": 0.85}

    def execute(self, ctx: dict[str, Any]) -> dict[str, Any]:
        kws = seo.scrape(limit=200)
        kv_set("bot_listing", "latest_keywords", kws)
        return {"keywords": kws,
                "metrics": {"keyword_count": len(kws),
                            "fresh_pct": _fresh_pct(kws)}}

    def read_metrics(self, ctx: dict[str, Any]) -> dict[str, Any]:
        kws = kv_get("bot_listing", "latest_keywords", []) or []
        return {"keyword_count": len(kws), "fresh_pct": _fresh_pct(kws)}


def _fresh_pct(kws: list[dict[str, Any]]) -> float:
    if not kws:
        return 0.0
    rising = sum(1 for k in kws if k.get("trend") == "rising")
    return round(rising / len(kws), 3)
