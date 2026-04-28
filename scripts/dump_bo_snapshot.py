"""Dump 大波比 (bo) 侧的 'published listings' to `/shared/bo-listings-snapshot.json`.

Source of truth: Notion Bot Database `1113f81f-f51e-8096-93a0-fd6764ad2d7d`
(生图类 bot list, data source `.` 详见 MEMORY.md). We include only items whose
`GUI_bot` multi_select contains `art上线`, because that's the canonical
"actually shipped on art.myshell.ai" signal.

Usage:
  python scripts/dump_bo_snapshot.py          # writes snapshot + prints summary
  python scripts/dump_bo_snapshot.py --dry    # prints first 5 rows, no write
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx

NOTION_DATABASE_ID = "1113f81f-f51e-8096-93a0-fd6764ad2d7d"
NOTION_VERSION = "2025-09-03"

SNAPSHOT_PATH = Path("/home/lobster/.openclaw/workspace/shared/bo-listings-snapshot.json")


def _notion_key() -> str:
    p = Path.home() / ".config" / "notion" / "api_key"
    if not p.exists():
        raise SystemExit("missing ~/.config/notion/api_key")
    return p.read_text(encoding="utf-8").strip()


def _fetch_data_source_id(key: str) -> str:
    """Notion v2025-09-03: data_source_id is required for query."""
    r = httpx.get(
        f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}",
        headers={"Authorization": f"Bearer {key}",
                 "Notion-Version": NOTION_VERSION},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    sources = data.get("data_sources") or []
    if not sources:
        raise SystemExit("no data_sources on Bot Database")
    return sources[0]["id"]


def _prop_text(prop: dict) -> str:
    t = prop.get("type")
    if t == "title":
        return "".join(x.get("plain_text", "") for x in prop.get("title", []))
    if t == "rich_text":
        return "".join(x.get("plain_text", "") for x in prop.get("rich_text", []))
    if t == "url":
        return prop.get("url") or ""
    return ""


def _prop_multi(prop: dict) -> list[str]:
    return [x.get("name", "") for x in (prop.get("multi_select") or [])]


def _extract(row: dict) -> dict:
    props = row.get("properties", {})
    bot_id = _prop_text(props.get("Bot_ID", {}))
    name = _prop_text(props.get("Bot_Name", {}) or props.get("Name", {}))
    slug_id = _prop_text(props.get("Slug_ID", {})) or _prop_text(props.get("slug_id", {}))
    url = _prop_text(props.get("URL", {})) or _prop_text(props.get("url", {}))
    gui = _prop_multi(props.get("GUI_bot", {}))
    return {
        "id": row.get("id"),                      # Notion page id (bo-side primary)
        "bot_id": bot_id,                          # cross-side matching key
        "slug_id": slug_id or None,
        "bot_name": name,
        "environment": "production",
        "status": "Synced" if ("art上线" in gui and "暂不上线" not in gui) else "Edit",
        "url": url or None,
        "gui_bot": gui,
    }


def dump(dry: bool = False) -> list[dict]:
    key = _notion_key()
    ds_id = _fetch_data_source_id(key)
    all_rows: list[dict] = []
    cursor: str | None = None
    while True:
        body: dict = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        r = httpx.post(
            f"https://api.notion.com/v1/data_sources/{ds_id}/query",
            headers={"Authorization": f"Bearer {key}",
                     "Notion-Version": NOTION_VERSION,
                     "Content-Type": "application/json"},
            json=body, timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        for row in data.get("results", []):
            all_rows.append(_extract(row))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    # only keep rows with a bot_id (anything else is unanchored / draft)
    filtered = [r for r in all_rows if r["bot_id"]]
    # canonical: only Synced (art上线) entries count as "published"
    published = [r for r in filtered if r["status"] == "Synced"]

    # CMS reality filter: drop bot_ids flagged by amy-clawd as 'NotFound' (no
    # LandingPage in any CMS env) or 'Deleted'. Prevents inflating only_bo with
    # bots that never made it to CMS. Source: data/cms_notfound_bot_ids.json
    cms_excl_path = Path(__file__).resolve().parent.parent / "data" / "cms_notfound_bot_ids.json"
    if cms_excl_path.exists():
        try:
            excl_data = json.loads(cms_excl_path.read_text(encoding="utf-8"))
            excl_ids = set(excl_data.get("notfound_bot_ids", []) +
                           excl_data.get("deleted_bot_ids", []))
            if excl_ids:
                before = len(published)
                published = [r for r in published if r["bot_id"] not in excl_ids]
                print(f"[cms-filter] dropped {before - len(published)} bots"
                      f" (NotFound/Deleted in CMS per amy-clawd)")
        except Exception as e:
            print(f"[cms-filter] WARN: failed to load {cms_excl_path.name}: {e}")

    # Env-mismatch filter: Notion粉上 art上线 但 CMS 在 test-framely 或 production-porn 环境
    # 这种不属于真正的 art-production gap, 应该从 published 列表排除。
    # Source: data/env_mismatch_bot_ids.json (amy-clawd CMS sweep)
    env_path = Path(__file__).resolve().parent.parent / "data" / "env_mismatch_bot_ids.json"
    if env_path.exists():
        try:
            env_data = json.loads(env_path.read_text(encoding="utf-8"))
            env_ids = set(env_data.get("test_framely_bot_ids", []) +
                          env_data.get("production_porn_bot_ids", []))
            if env_ids:
                before = len(published)
                published = [r for r in published if r["bot_id"] not in env_ids]
                print(f"[env-filter] dropped {before - len(published)} bots"
                      f" (env-mismatch: test-framely / production-porn)")
        except Exception as e:
            print(f"[env-filter] WARN: failed to load {env_path.name}: {e}")

    if dry:
        print(f"[dry] total rows: {len(all_rows)}, with_bot_id: {len(filtered)},"
              f" published: {len(published)}")
        for r in published[:5]:
            print(" ", r["bot_id"], "|", r["bot_name"], "| slug=", r["slug_id"])
        return published

    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "Notion Bot Database",
        "database_id": NOTION_DATABASE_ID,
        "total": len(published),
        "items": published,
    }
    # Write list-of-dicts to match adapters.lobster.fetch_state contract.
    SNAPSHOT_PATH.write_text(
        json.dumps(published, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    SNAPSHOT_PATH.with_suffix(".meta.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"✅ wrote {SNAPSHOT_PATH} · {len(published)} published bots")
    return published


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    dump(dry=args.dry)
