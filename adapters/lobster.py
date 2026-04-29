"""amy 龙虾 ⇄ bo 龙虾 一致性 adapter. Bridges the two systems noted in Step 5.

Design (agreed with Amy-clawd / lucas-clawd 2026-04-28, revised v2):

- Amy 侧数据源: Base44 CMS `LandingPage` entity (environment=production, status=Synced)
- Bo 侧数据源: Notion Bot Database `1113f81f-f51e-8096-93a0-fd6764ad2d7d` (生图类 bot list)
- 主键 (diff): `bot_id` (== slug_id, per bobo 2026-04-28 钦定)
- 次主键: slug_id (alias of bot_id for now)

Key correction 2026-04-28: 跨龙虾 `/shared/` 不是同一挂载，文件通道走不通。
→ Canonical transport = **Slack file uploads in a tracked thread/channel**.

Resolution order for each side:
  1. Explicit HTTP endpoint env (`AMY_LOBSTER_URL` / `BO_LOBSTER_URL`)
  2. Slack channel (`LOBSTER_SLACK_CHANNEL` + `SLACK_BOT_TOKEN`): pull the most
     recent file named `{side}-listings-snapshot.json`.
  3. Local snapshot at `$WORKSPACE/shared/{side}-listings-snapshot.json`
     (only useful for the龙虾 that dumped it; other lobsters won't see it).
  4. Empty stub — keeps loop runnable in dev.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx

from core.config import env

WORKSPACE_ROOT = Path.home() / ".openclaw" / "workspace"
LOCAL_SHARED = WORKSPACE_ROOT / "shared"


def _load_json_file(p: Path) -> list[dict[str, Any]] | None:
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    return _unwrap(data)


def _unwrap(data: Any) -> list[dict[str, Any]] | None:
    """Accept both a plain list and {meta, listings:[...]} / {items:[...]}.

    Amy-clawd's dump wraps {meta, listings:[]}; bo-side dump is a plain list.
    Keep the adapter tolerant of both.
    """
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("listings", "items", "results", "data", "rows"):
            v = data.get(k)
            if isinstance(v, list):
                return v
    return None


def _fetch_http(url: str) -> list[dict[str, Any]]:
    r = httpx.get(url, timeout=15)
    r.raise_for_status()
    data = r.json()
    return _unwrap(data) or []


def _fetch_slack_file(prefix: str, channel: str | None = None,
                      thread_ts: str | None = None,
                      unwrap: bool = True) -> list[dict[str, Any]] | dict[str, Any] | None:
    """Pull the most recent JSON file whose filename starts with ``prefix``.

    Generalized cross-lobster Slack transport. Replaces the old
    `_fetch_slack_latest(side)` helper (which was hard-coded to
    `{side}-listings-snapshot`).

    Args:
      prefix:   filename prefix to match, e.g. ``bot_demands_`` /
                ``bobo-bot-status-`` / ``amy-listings-snapshot``.
      channel:  Slack channel id. Falls back to ``LOBSTER_SLACK_CHANNEL``.
      thread_ts: optional thread timestamp. **Lenient filter** (2026-04-29):
                Slack files.list frequently returns ``thread_ts=None`` and
                empty ``shares`` for files uploaded into a thread via
                ``files.upload_v2`` — the thread association lives in the
                message, not the file object. So we only drop a file when
                it carries explicit thread metadata that *contradicts*
                ``thread_ts``. Files with no thread info are kept; callers
                should additionally scope by ``channel`` + ``prefix`` to
                avoid cross-contamination.
      unwrap:   when True, return the list inside standard wrappers
                (``{listings}``, ``{items}``, …). When False, return the
                raw JSON object (needed for ``bot_demands_*.approved.json``
                which has ``{schema, source, demands:[...]}``).

    Env:
      SLACK_BOT_TOKEN        — xoxb-...
      LOBSTER_SLACK_CHANNEL  — default channel id when ``channel`` is None.

    Returns None when transport is misconfigured or no matching file exists.
    The caller falls back to the next tier (local file / empty stub).
    """
    token = env("SLACK_BOT_TOKEN")
    channel = channel or env("LOBSTER_SLACK_CHANNEL")
    if not token or not channel:
        return None
    try:
        r = httpx.get(
            "https://slack.com/api/files.list",
            headers={"Authorization": f"Bearer {token}"},
            # NOTE: do NOT pass types=spaces — it returns 0 results for uploads.
            params={"channel": channel, "count": 200},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            return None
        files = [
            f for f in data.get("files", [])
            if (f.get("name") or "").startswith(prefix)
            and (f.get("name") or "").endswith(".json")
        ]
        if thread_ts:
            # Lenient filter: Slack's files.list API does NOT reliably
            # populate thread_ts / shares on files uploaded via
            # files.upload_v2 into a thread (real bug observed 2026-04-29
            # end-to-end smoke). Only drop a file when it carries
            # EXPLICIT contradicting thread metadata. Files without thread
            # info pass through — channel + prefix scoping already keeps
            # cross-contamination bounded.
            def keep(f: dict[str, Any]) -> bool:
                f_thread = f.get("thread_ts")
                if f_thread and f_thread == thread_ts:
                    return True
                shares = f.get("shares") or {}
                saw_any_thread_info = bool(f_thread)
                for section in shares.values():
                    if not isinstance(section, dict):
                        continue
                    for sh in section.values():
                        if not isinstance(sh, list):
                            continue
                        for entry in sh:
                            if not isinstance(entry, dict):
                                continue
                            if entry.get("thread_ts") == thread_ts or entry.get("ts") == thread_ts:
                                return True
                            if entry.get("thread_ts") or entry.get("ts"):
                                saw_any_thread_info = True
                # No matching thread info found. Keep ONLY when the file
                # carries no thread signal at all — the Slack API bug path.
                return not saw_any_thread_info
            files = [f for f in files if keep(f)]
        files.sort(key=lambda f: -int(f.get("created", 0)))
        if not files:
            return None
        url = files[0].get("url_private_download") or files[0].get("url_private")
        if not url:
            return None
        r2 = httpx.get(url, headers={"Authorization": f"Bearer {token}"},
                       timeout=30, follow_redirects=True)
        r2.raise_for_status()
        payload = r2.json()
        if not unwrap:
            return payload
        return _unwrap(payload)
    except Exception:
        return None


def _fetch_slack_latest(side: str) -> list[dict[str, Any]] | None:
    """Back-compat shim: pull `{side}-listings-snapshot*.json` from the default channel."""
    return _fetch_slack_file(f"{side}-listings-snapshot")  # type: ignore[return-value]


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
            pass

    # 2. Slack channel file (cross-lobster canonical transport)
    rows = _fetch_slack_latest(side)
    if rows is not None:
        return rows

    # 3. local snapshot (only for the lobster that produced it)
    local = LOCAL_SHARED / f"{side}-listings-snapshot.json"
    rows = _load_json_file(local)
    if rows is not None:
        return rows

    # 4. empty stub
    return []


def diff(amy: list[dict[str, Any]], bo: list[dict[str, Any]],
         key: str = "bot_id") -> dict[str, Any]:
    """Compute set-diff keyed by `bot_id` (default) with slug_id fallback."""
    def _key(row: dict[str, Any]) -> str:
        # slug_id == bot_id per bobo. Prefer bot_id but accept either.
        v = row.get(key) or row.get("bot_id") or row.get("slug_id") or row.get("id")
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
