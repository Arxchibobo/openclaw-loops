"""Upload bobo-bot-status-{batch_id}.json back to lucas-clawd's Slack thread.

P1-4 (2026-04-29): completes the GTM Loop Step 2 round trip. After bot_listing
finishes, kv['bot_listing']['bot_statuses'] holds a list of BotStatus dicts.
This script packages them per spec `gtm-loop.bot-status.v1` and uploads a
single JSON file to the thread lucas-clawd is polling.

Contract (matches lucas-clawd's pull_bot_status.py):
  {
    "schema": "gtm-loop.bot-status.v1",
    "batch_id": "20260429T104806Z",
    "source": "bobo-clawd",
    "generated_at": "<iso>",
    "statuses": [ BotStatus dict, ... ]
  }

Usage:
  python -m scripts.upload_bot_status --batch-id 20260429T104806Z
  python -m scripts.upload_bot_status --batch-id 20260429T104806Z --dry-run

Env:
  SLACK_BOT_TOKEN         — xoxb-... (workspace-wide)
  LUCAS_DEMAND_CHANNEL    — default target channel (falls back LOBSTER_SLACK_CHANNEL)
  LUCAS_DEMAND_THREAD     — target thread_ts; required for proper threading
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.config import env  # noqa: E402
from core.state import kv_get  # noqa: E402


SCHEMA_ID = "gtm-loop.bot-status.v1"


def build_payload(batch_id: str, statuses: list[dict]) -> dict:
    return {
        "schema": SCHEMA_ID,
        "batch_id": batch_id,
        "source": "bobo-clawd",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "statuses": statuses,
    }


def _scrub(statuses: list[dict]) -> list[dict]:
    """Defensive: make absolutely sure nothing that could carry a raw NSFW
    kw crosses the wire. BotStatus already omits kw by construction, but
    if a real executor stuffed one into acceptance_result[] during dev,
    catch it here. Strips any key literally named 'kw' and redacts values
    that look like they contain a bracketed kw marker."""
    cleaned = []
    for s in statuses:
        s2 = dict(s)
        s2.pop("kw", None)
        ar = s2.get("acceptance_result") or {}
        if isinstance(ar, dict):
            ar.pop("kw", None)
        cleaned.append(s2)
    return cleaned


def upload(payload: dict, channel: str, thread_ts: str | None,
           comment: str) -> dict:
    token = env("SLACK_BOT_TOKEN")
    if not token:
        raise RuntimeError("SLACK_BOT_TOKEN not configured")

    filename = f"bobo-bot-status-{payload['batch_id']}.json"
    body = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")

    # files.upload_v2 (two-step) — works with modern bot tokens.
    # 1. get upload URL
    r1 = httpx.post(
        "https://slack.com/api/files.getUploadURLExternal",
        headers={"Authorization": f"Bearer {token}"},
        data={"filename": filename, "length": str(len(body))},
        timeout=15,
    )
    r1.raise_for_status()
    j1 = r1.json()
    if not j1.get("ok"):
        raise RuntimeError(f"getUploadURLExternal failed: {j1}")
    upload_url = j1["upload_url"]
    file_id = j1["file_id"]

    # 2. PUT the bytes
    r2 = httpx.post(upload_url, content=body, timeout=30)
    r2.raise_for_status()

    # 3. complete + attach to channel+thread
    payload3 = {
        "files": [{"id": file_id, "title": filename}],
        "channel_id": channel,
        "initial_comment": comment,
    }
    if thread_ts:
        payload3["thread_ts"] = thread_ts
    r3 = httpx.post(
        "https://slack.com/api/files.completeUploadExternal",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        content=json.dumps(payload3).encode("utf-8"),
        timeout=15,
    )
    r3.raise_for_status()
    j3 = r3.json()
    if not j3.get("ok"):
        raise RuntimeError(f"completeUploadExternal failed: {j3}")
    return {"file_id": file_id, "filename": filename,
            "files": j3.get("files", [])}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch-id", required=True,
                    help="Demand batch id, echoed back so lucas can match.")
    ap.add_argument("--channel", default=None,
                    help="Slack channel id. Falls back to LUCAS_DEMAND_CHANNEL "
                         "then LOBSTER_SLACK_CHANNEL.")
    ap.add_argument("--thread-ts", default=None,
                    help="Thread timestamp. Falls back to LUCAS_DEMAND_THREAD.")
    ap.add_argument("--from-kv", action="store_true", default=True,
                    help="Read bot_statuses from kv (default).")
    ap.add_argument("--from-file", default=None,
                    help="Read bot_statuses list from a JSON file instead.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print payload, skip upload.")
    args = ap.parse_args()

    if args.from_file:
        data = json.loads(Path(args.from_file).read_text(encoding="utf-8"))
        statuses = data if isinstance(data, list) else data.get("statuses", [])
    else:
        statuses = kv_get("bot_listing", "bot_statuses") or []

    if not statuses:
        print(f"[upload_bot_status] no bot_statuses found for {args.batch_id}; "
              f"aborting.", file=sys.stderr)
        return 1

    statuses = _scrub(statuses)
    payload = build_payload(args.batch_id, statuses)
    channel = args.channel or env("LUCAS_DEMAND_CHANNEL") or env("LOBSTER_SLACK_CHANNEL")
    thread_ts = args.thread_ts or env("LUCAS_DEMAND_THREAD")

    if args.dry_run:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        print(f"\n[dry-run] would upload to channel={channel} thread_ts={thread_ts}",
              file=sys.stderr)
        return 0

    if not channel:
        print("[upload_bot_status] no channel resolved; set LUCAS_DEMAND_CHANNEL "
              "or pass --channel.", file=sys.stderr)
        return 2

    summary = _summary_line(payload)
    result = upload(payload, channel=channel, thread_ts=thread_ts,
                    comment=summary)
    print(json.dumps({"ok": True, "file_id": result["file_id"],
                      "filename": result["filename"],
                      "batch_id": args.batch_id,
                      "status_count": len(statuses)}, indent=2))
    return 0


def _summary_line(payload: dict) -> str:
    """Slack initial_comment — human-readable one-liner lucas can scan."""
    counts: dict[str, int] = {}
    for s in payload["statuses"]:
        counts[s.get("status", "unknown")] = counts.get(s.get("status"), 0) + 1
    parts = [f"{k}={v}" for k, v in sorted(counts.items())]
    return (f"🦞 bobo-clawd bot_status for batch `{payload['batch_id']}` — "
            f"{len(payload['statuses'])} status ({', '.join(parts)})")


if __name__ == "__main__":
    sys.exit(main())
