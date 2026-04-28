"""Cross-channel notification bridge: wechat <-> slack <-> openclaw.

The bridge is the documented blocking point in both loops (bobo wechat is the
sole interface; slack/wechat are not interoperable). This module exposes a
provider-agnostic `send(channel, message)` and queues messages locally when no
provider is configured so nothing is silently dropped.
"""
from __future__ import annotations

import json
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


def send(channel: str, message: str, *, meta: dict[str, Any] | None = None) -> bool:
    """Send a message to wechat | slack | log. Returns True on delivery."""
    cfg = load_config()
    bridge = cfg.raw.get("bridge", {})
    record: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "channel": channel,
        "message": message,
        "meta": meta or {},
    }

    if channel == "log":
        log.info("bridge.log", extra=_log_safe(record))
        return True

    conf = bridge.get(channel, {})
    if not conf.get("enabled"):
        record["delivered"] = False
        record["reason"] = "channel disabled, queued"
        _enqueue(record)
        log.warning("bridge.queued", extra=_log_safe(record))
        return False

    webhook = env(conf.get("webhook_env", ""))
    if not webhook:
        record["delivered"] = False
        record["reason"] = "missing webhook env"
        _enqueue(record)
        log.warning("bridge.no_webhook", extra=_log_safe(record))
        return False

    try:
        r = httpx.post(webhook, json={"text": message}, timeout=10)
        r.raise_for_status()
        record["delivered"] = True
        log.info("bridge.delivered", extra=_log_safe(record))
        return True
    except Exception as exc:
        record["delivered"] = False
        record["reason"] = f"http error: {exc}"
        _enqueue(record)
        log.exception("bridge.failed")
        return False


def drain_queue() -> Path:
    return QUEUE_PATH
