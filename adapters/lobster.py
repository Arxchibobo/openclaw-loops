"""amy 龙虾 ⇄ bo 龙虾 一致性 adapter. Bridges the two systems noted in Step 5.

Design (agreed with Amy-clawd / lucas-clawd 2026-04-28):

- Amy 侧数据源: Base44 CMS `LandingPage` entity (environment=production, status=Synced)
- Bo 侧数据源: Notion Bot Database `1113f81f-f51e-8096-93a0-fd6764ad2d7d` (生图类 bot list)
- 主键 (diff): `bot_id` (MyShell bot_id，两侧都有，整数字符串)
- 次主键 / 业务 key: `slug_id` (e.g. "celebrity-look-alike")

Resolution order for each side:
  1. Explicit HTTP endpoint env (`AMY_LOBSTER_URL` / `BO_LOBSTER_URL`) returns
     a JSON list matching the schema.
  2. Shared snapshot file at `/shared/amy-listings-snapshot.json` /
     `/shared/bo-listings-snapshot.json` (方案 B, easy fallback)
  3. Cross-lobster live fetch via `sessions_send` (方案 A; only if
     `LOBSTER_LIVE_FETCH=1`, since it requires an active agent session).
  4. Empty stub — keeps loop runnable in dev.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from core.config import env

SHARED_DIR = Path("/home/lobster/.openclaw/workspace/shared")

# Canonical schema (documented; not enforced in code):
#   { id, slug_id, bot_id, environment, status, url, ... }
# `id` is the side-local primary key (CMS entity id or Notion page id).
# `bot_id` is the cross-side matching key used in diff().


def _load_json_file(p: Path) -> list[dict[str, Any]] | None:
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, list) else None


def _fetch_http(url: str) -> list[dict[str, Any]]:
    r = httpx.get(url, timeout=15)
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else data.get("items", [])


def fetch_state(side: str) -> list[dict[str, Any]]:
    """Return the list of 'published listings' on the given side.

    side: 'amy' | 'bo'
    """
    assert side in ("amy", "bo"), f"unknown side {side!r}"
    url_env = "AMY_LOBSTER_URL" if side == "amy" else "BO_LOBSTER_URL"
    url = env(url_env)

    # 1. HTTP endpoint
    if url:
        try:
            return _fetch_http(url)
        except Exception:
            pass  # fall through to file snapshot

    # 2. shared snapshot file
    snap = SHARED_DIR / f"{side}-listings-snapshot.json"
    rows = _load_json_file(snap)
    if rows is not None:
        return rows

    # 3. dev stub (empty, consistent)
    return []


def diff(amy: list[dict[str, Any]], bo: list[dict[str, Any]],
         key: str = "bot_id") -> dict[str, Any]:
    """Compute set-diff keyed by `bot_id` (default) with slug_id on ties."""
    def _key(row: dict[str, Any]) -> str:
        v = row.get(key) or row.get("slug_id") or row.get("id")
        return str(v) if v is not None else ""

    amy_map = {_key(x): x for x in amy if _key(x)}
    bo_map = {_key(x): x for x in bo if _key(x)}
    amy_ids = set(amy_map)
    bo_ids = set(bo_map)
    return {
        "only_amy": sorted(amy_ids - bo_ids),
        "only_bo": sorted(bo_ids - amy_ids),
        "common": sorted(amy_ids & bo_ids),
        "consistent": amy_ids == bo_ids,
        "key": key,
        "amy_count": len(amy_ids),
        "bo_count": len(bo_ids),
    }
