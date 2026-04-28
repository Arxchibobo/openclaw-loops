"""Cross-channel notification bridge: wechat <-> slack <-> openclaw.

The bridge is the documented blocking point in both loops (bobo wechat is the
sole interface; slack/wechat are not interoperable). This module exposes a
provider-agnostic `send(channel, message)` and queues messages locally when no
provider is configured so nothing is silently dropped.

Channels
--------
- `log`    — always available; writes to JSONL log.
- `slack`  — via webhook (SLACK_WEBHOOK) OR the local `openclaw` CLI / `slack`
             companion (SLACK_BOT_TOKEN + default channel). Webhook wins when
             both are set.
- `wechat` — via webhook (WECHAT_WEBHOOK). Without webhook, messages are queued
             to `state/bridge-queue.jsonl` so 大波比 / 人肉接口可以补发。
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from .config import ROOT, env, load_config
from .logger import get_logger

log = get_logger("openclaw.bridge")
QUEUE_PATH = ROOT / "state" / "bridge-queue.jsonl"


RESERVED_LOG_KEYS = {"message", "asctime", "msg"}


def _enqueue(record: dict[str, Any]) -> None:
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with QUEUE_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _log_safe(record: dict[str, Any]) -> dict[str, Any]:
    """Strip keys that collide with stdlib logging's LogRecord."""
    return {k: v for k, v in record.items() if k not in RESERVED_LOG_KEYS}


def _send_slack_webhook(webhook: str, message: str) -> None:
    r = httpx.post(webhook, json={"text": message}, timeout=10)
    r.raise_for_status()


def _send_slack_bot_token(message: str, *, target: str) -> None:
    """Fallback path: use Slack bot token to post via chat.postMessage.

    Requires `SLACK_BOT_TOKEN` and `SLACK_DEFAULT_TARGET` (channel id or user id)
    or explicit `target` from meta.
    """
    token = env("SLACK_BOT_TOKEN")
    if not token:
        raise RuntimeError("no SLACK_BOT_TOKEN / SLACK_WEBHOOK configured")
    r = httpx.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json; charset=utf-8"},
        json={"channel": target, "text": message},
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"slack error: {data.get('error')}")


def _send_wechat(webhook: str, message: str) -> None:
    # wechat webhooks vary by vendor (feishu/wecom/serverchan). Accept both
    # a raw endpoint expecting {"text": ...} and WeCom-flavoured {"msgtype":
    # "text", "text": {"content": ...}}.
    payload: dict[str, Any]
    if "qyapi.weixin.qq.com" in webhook or env("WECHAT_FLAVOR") == "wecom":
        payload = {"msgtype": "text", "text": {"content": message}}
    else:
        payload = {"text": message}
    r = httpx.post(webhook, json=payload, timeout=10)
    r.raise_for_status()


def send(channel: str, message: str, *, meta: dict[str, Any] | None = None) -> bool:
    """Send a message to wechat | slack | log. Returns True on delivery.

    `meta` may include:
      - `target`  — Slack channel id / Slack user id / wechat groupid
      - `loop`, `step`, etc. — surfaced in logs and the queue
    """
    cfg = load_config()
    bridge_cfg = cfg.raw.get("bridge", {})
    record: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "channel": channel,
        "message": message,
        "meta": meta or {},
    }

    if channel == "log":
        log.info("bridge.log", extra=_log_safe(record))
        return True

    conf = bridge_cfg.get(channel, {})
    webhook_env = conf.get("webhook_env", "")
    webhook = env(webhook_env) if webhook_env else None

    # channel-specific delivery
    try:
        if channel == "slack":
            if webhook:
                _send_slack_webhook(webhook, message)
            else:
                target = (meta or {}).get("target") or env("SLACK_DEFAULT_TARGET")
                if not target:
                    raise RuntimeError("slack needs webhook or target")
                _send_slack_bot_token(message, target=target)
        elif channel == "wechat":
            if not webhook:
                raise RuntimeError("missing WECHAT_WEBHOOK")
            _send_wechat(webhook, message)
        else:
            raise RuntimeError(f"unknown channel: {channel}")
    except Exception as exc:
        record["delivered"] = False
        record["reason"] = f"{channel} error: {exc}"
        _enqueue(record)
        log.warning("bridge.queued", extra=_log_safe(record))
        return False

    record["delivered"] = True
    log.info("bridge.delivered", extra=_log_safe(record))
    return True


def drain_queue() -> Path:
    return QUEUE_PATH

