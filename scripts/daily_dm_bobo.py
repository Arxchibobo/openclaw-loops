"""DM bobo (U07P68KNDUG) with the daily openclaw-loops gap summary.

Reads:
  - /tmp/loops-daily-out.txt          (openclaw run bot_listing tail)
  - reports/bot_listing-run-*.md      (latest = today)

Posts a compact Slack message to the DM channel.
"""
from __future__ import annotations

import glob
import os
import re
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
BOBO_USER_ID = "U07P68KNDUG"
THREAD_URL = "https://myshellhq.slack.com/archives/C0AR3GXL39D/p1777350011598059"


def latest_report() -> Path | None:
    files = sorted(glob.glob(str(REPO / "reports" / "bot_listing-run-*.md")),
                   key=os.path.getmtime, reverse=True)
    return Path(files[0]) if files else None


def parse_metrics(md: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in ("amy_bo_consistent", "published", "only_amy", "only_bo"):
        m = re.search(rf"- {re.escape(key)}:\s*(\S+)", md)
        if m:
            out[key] = m.group(1)
    return out


def main() -> int:
    tok = os.environ["SLACK_BOT_TOKEN"]

    # find/open bobo DM
    r = httpx.post(
        "https://slack.com/api/conversations.open",
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
        json={"users": BOBO_USER_ID},
        timeout=15,
    )
    dm = r.json()
    if not dm.get("ok"):
        print("conversations.open failed:", dm)
        return 1
    ch = dm["channel"]["id"]

    report_path = latest_report()
    metrics = parse_metrics(report_path.read_text(encoding="utf-8")) if report_path else {}

    try:
        run_out = Path("/tmp/loops-daily-out.txt").read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        run_out = "(no run output)"

    ok = metrics.get("amy_bo_consistent", "?")
    summary_icon = "✅" if ok == "True" else "⚠️"

    msg = (
        f"🦞 *每日 openclaw-loops 报告* (北京 12:00 / UTC 04:00)\n\n"
        f"*一致性*: {summary_icon} `{ok}`\n"
        f"*only_amy* (CMS 有 / Notion 缺 art上线 tag): `{metrics.get('only_amy','?')}` 条\n"
        f"*only_bo* (Notion 有 / CMS 未 Synced) 真 QA backlog: `{metrics.get('only_bo','?')}` 条\n"
        f"*已上架*: `{metrics.get('published','?')}`\n\n"
        f"*step5 table*:\n```\n{run_out}\n```\n\n"
        f"完整报告: `{report_path.name if report_path else 'n/a'}`\n"
        f"thread: {THREAD_URL}\n\n"
        f"_如需详情或修 gap, 喊「汪汪~ 按报告处理」_"
    )

    r2 = httpx.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
        json={"channel": ch, "text": msg, "unfurl_links": False},
        timeout=15,
    )
    print("DM:", r2.json().get("ok"), "metrics:", metrics)
    return 0 if r2.json().get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
