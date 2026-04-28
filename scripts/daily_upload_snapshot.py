"""Upload /home/lobster/.openclaw/workspace/shared/bo-listings-snapshot.json
to #claw2claude thread 1777350011.598059 with a timestamped filename.
Used by daily cron to publish the fresh bo snapshot before running the loop."""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

import httpx

SNAPSHOT = Path("/home/lobster/.openclaw/workspace/shared/bo-listings-snapshot.json")
CHANNEL = "C0AR3GXL39D"
THREAD_TS = "1777350011.598059"


def main() -> int:
    tok = os.environ["SLACK_BOT_TOKEN"]
    ts = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    filename = f"bo-listings-snapshot-{ts}.json"
    size = SNAPSHOT.stat().st_size

    r = httpx.post(
        "https://slack.com/api/files.getUploadURLExternal",
        headers={"Authorization": f"Bearer {tok}"},
        data={"filename": filename, "length": str(size)},
        timeout=20,
    )
    r.raise_for_status()
    d = r.json()
    if not d.get("ok"):
        print("getUploadURL failed:", d)
        return 1

    with SNAPSHOT.open("rb") as fp:
        httpx.post(d["upload_url"], content=fp.read(), timeout=60).raise_for_status()

    r2 = httpx.post(
        "https://slack.com/api/files.completeUploadExternal",
        headers={
            "Authorization": f"Bearer {tok}",
            "Content-Type": "application/json",
        },
        json={
            "files": [{"id": d["file_id"], "title": f"daily bo snapshot {ts}"}],
            "channel_id": CHANNEL,
            "thread_ts": THREAD_TS,
            "initial_comment": f"🦞 daily bo snapshot · {ts}",
        },
        timeout=20,
    )
    ok = r2.json().get("ok")
    print(f"upload {filename}: ok={ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
