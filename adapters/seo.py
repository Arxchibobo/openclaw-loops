"""SEO keyword scrape adapter.

Resolution order for real data (no config needed, picks up whichever exists):
  1. `SEO_BASE_URL` env  → HTTP endpoint (future CLAWbo daemon)
  2. `SEO_SNAPSHOT_JSON` env → explicit JSON file path
  3. Latest `seo_*.json` from `skills/omni-channel-agent/output/`
     (this is what Amy-clawd's pipeline produces today)
  4. Deterministic stub set (dev mode) so the loop can still advance.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from core.config import env
from core.state import kv_set

WORKSPACE_ROOT = Path.home() / ".openclaw" / "workspace"
OMNI_OUTPUT = WORKSPACE_ROOT / "skills" / "omni-channel-agent" / "output"


def _from_omni_snapshot() -> list[dict[str, Any]] | None:
    """Pick the newest `seo_*.json` produced by Amy-clawd's pipeline."""
    if not OMNI_OUTPUT.exists():
        return None
    candidates = sorted(OMNI_OUTPUT.glob("seo_*.json"),
                        key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        return None
    try:
        data = json.loads(candidates[0].read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, list):
        return None
    return [_normalize(row) for row in data]


def _normalize(row: dict[str, Any]) -> dict[str, Any]:
    """Map Amy's schema → loop schema (kw / volume / trend)."""
    kw = row.get("kw") or row.get("keyword") or row.get("phrase") or ""
    volume = row.get("volume") or row.get("search_volume") or 0
    # infer trend from coverage_label / kd — 'rising' gets downstream bonus
    label = str(row.get("coverage_label") or "")
    kd = row.get("kd")
    trend = "rising" if ("新机会" in label or "🔥" in label or
                          (isinstance(kd, (int, float)) and kd <= 40)) else "flat"
    return {
        "kw": str(kw),
        "volume": int(volume) if isinstance(volume, (int, float)) else 0,
        "trend": trend,
        "kd": kd,
        "source": row.get("comp_domain") or row.get("source"),
        "raw": row,
    }


def _from_http(base_url: str, limit: int) -> list[dict[str, Any]]:
    r = httpx.get(base_url, params={"limit": limit}, timeout=15)
    r.raise_for_status()
    data = r.json()
    rows = data.get("keywords") if isinstance(data, dict) else data
    return [_normalize(x) for x in (rows or [])]


def scrape(provider: str = "clawbo", limit: int = 200) -> list[dict[str, Any]]:
    # 1. HTTP endpoint
    base_url = env("SEO_BASE_URL")
    if base_url:
        try:
            rows = _from_http(base_url, limit)
            kv_set("seo", f"snapshot:{date.today().isoformat()}", rows)
            kv_set("seo", "last_source", {"kind": "http", "url": base_url})
            return rows[:limit]
        except Exception as exc:
            kv_set("seo", "last_error", f"http: {exc}")

    # 2. explicit JSON file
    snap_path = env("SEO_SNAPSHOT_JSON")
    if snap_path and Path(snap_path).exists():
        data = json.loads(Path(snap_path).read_text(encoding="utf-8"))
        if isinstance(data, list):
            rows = [_normalize(x) for x in data][:limit]
            kv_set("seo", f"snapshot:{date.today().isoformat()}", rows)
            kv_set("seo", "last_source", {"kind": "file", "path": snap_path})
            return rows

    # 3. omni-channel-agent latest output (Amy-clawd's canonical feed)
    rows = _from_omni_snapshot()
    if rows:
        rows = rows[:limit]
        kv_set("seo", f"snapshot:{date.today().isoformat()}", rows)
        kv_set("seo", "last_source", {"kind": "omni-channel-agent"})
        return rows

    # 4. deterministic stub
    bases = ["ai agent", "ai-agent", "AI Agent", "agentic ai", "llm app",
             "LLM Apps", "rag pipeline", "rag pipelines", "vector db",
             "vector database", "prompt engineering", "prompt-engineering"]
    keywords: list[dict[str, Any]] = []
    for i in range(min(limit, 80)):
        base = bases[i % len(bases)]
        keywords.append({
            "kw": base if i < len(bases) * 4 else f"{base} {i}",
            "volume": 1000 - i * 7,
            "trend": "rising" if i % 3 else "flat",
        })
    kv_set("seo", f"snapshot:{date.today().isoformat()}", keywords)
    kv_set("seo", "last_source", {"kind": "stub"})
    return keywords
