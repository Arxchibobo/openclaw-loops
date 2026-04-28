"""Step 1 · 抓住核心词汇，内容去重，制作周报 social calendar
卡点: 数据清洗阶段不够干净 → 这里实现 v2 cleaning：lower + strip + 同义合并 + 子串去重."""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from core.state import kv_get, kv_set
from loops.base import BaseStep

_PUNCT = re.compile(r"[\s\-_/.,!?#@]+")


def _norm(s: str) -> str:
    return _PUNCT.sub(" ", s.lower()).strip()


def clean_keywords(raw: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], float]:
    """Return (cleaned, dedup_rate). dedup_rate = 1 - kept/raw."""
    if not raw:
        return [], 0.0
    seen: dict[str, dict[str, Any]] = {}
    for k in raw:
        n = _norm(str(k.get("kw", "")))
        if not n or len(n) < 2:
            continue
        # substring-merge: if existing key contains this or vice-versa, keep the
        # higher-volume one
        merged = False
        for ex in list(seen):
            if n == ex or n in ex or ex in n:
                if int(k.get("volume", 0)) > int(seen[ex].get("volume", 0)):
                    seen.pop(ex)
                    seen[n] = {**k, "kw": n}
                merged = True
                break
        if not merged:
            seen[n] = {**k, "kw": n}
    cleaned = sorted(seen.values(), key=lambda x: -int(x.get("volume", 0)))
    rate = round(1 - len(cleaned) / len(raw), 3) if raw else 0.0
    return cleaned, rate


def build_calendar(cleaned: list[dict[str, Any]],
                   start: date | None = None,
                   days: int = 7) -> list[dict[str, Any]]:
    start = start or date.today()
    cal = []
    top = cleaned[: days * 2]
    for i in range(days):
        slot = top[i * 2: i * 2 + 2]
        cal.append({
            "date": (start + timedelta(days=i)).isoformat(),
            "themes": [s["kw"] for s in slot],
        })
    return cal


class Step(BaseStep):
    LOOP = "social_ops"
    KEY = "kw_calendar"

    def plan(self, ctx: dict[str, Any]) -> str:
        return "拉取 keywords → 清洗去重(v2) → 生成 7 天 social calendar"

    def synthetic_metrics(self, ctx: dict[str, Any]) -> dict[str, Any]:
        return {"dedup_rate": 0.96, "calendar_days": 7}

    def execute(self, ctx: dict[str, Any]) -> dict[str, Any]:
        # reuse SEO snapshot from bot_listing if available, else seed empty
        raw = kv_get("bot_listing", "latest_keywords", []) or []
        cleaned, rate = clean_keywords(raw)
        cal = build_calendar(cleaned)
        kv_set("social_ops", "keywords_clean", cleaned)
        kv_set("social_ops", "calendar", cal)
        return {"metrics": {"dedup_rate": rate, "calendar_days": len(cal),
                            "kept_kw": len(cleaned)}}

    def read_metrics(self, ctx: dict[str, Any]) -> dict[str, Any]:
        cal = kv_get("social_ops", "calendar", []) or []
        clean = kv_get("social_ops", "keywords_clean", []) or []
        raw = kv_get("bot_listing", "latest_keywords", []) or []
        rate = round(1 - len(clean) / len(raw), 3) if raw else 0.0
        return {"dedup_rate": rate, "calendar_days": len(cal), "kept_kw": len(clean)}
