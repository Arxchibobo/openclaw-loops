#!/bin/bash
# Daily openclaw-loops runner — refresh bo snapshot, run bot_listing, DM bobo.
# Called by cron every day 04:00 UTC (= Beijing 12:00).
set -u
cd /home/lobster/.openclaw/workspace/projects/openclaw-loops/repo

SLACK_BOT_TOKEN=$(python3 -c "import json; print(json.load(open('/home/lobster/.openclaw/secrets.json'))['SLACK_BOT_TOKEN'])")
export SLACK_BOT_TOKEN
export LOBSTER_SLACK_CHANNEL=C0AR3GXL39D

# 1) refresh bo snapshot from Notion
.venv/bin/python scripts/dump_bo_snapshot.py 2>&1 | tail -3 > /tmp/loops-daily-dump.txt
cat /tmp/loops-daily-dump.txt

# 2) upload snapshot to Slack thread
.venv/bin/python scripts/daily_upload_snapshot.py

# 3) sleep to let Slack index the new file
sleep 20

# 4) run full bot_listing loop
.venv/bin/openclaw run bot_listing 2>&1 | tail -14 > /tmp/loops-daily-out.txt
cat /tmp/loops-daily-out.txt

# 5) DM bobo with summary
.venv/bin/python scripts/daily_dm_bobo.py

echo "[$(date -u +%FT%TZ)] daily-loops-report done"
