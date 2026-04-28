from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from .config import ROOT


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        for k, v in record.__dict__.items():
            if k in ("args", "msg", "levelname", "name", "exc_info", "exc_text",
                     "stack_info", "lineno", "funcName", "created", "msecs",
                     "relativeCreated", "thread", "threadName", "processName",
                     "process", "pathname", "filename", "module", "levelno"):
                continue
            payload[k] = v
        return json.dumps(payload, ensure_ascii=False)


def get_logger(name: str = "openclaw") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)

    logs_dir = ROOT / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    fh = logging.FileHandler(logs_dir / f"openclaw-{today}.jsonl", encoding="utf-8")
    fh.setFormatter(JsonFormatter())
    fh.setLevel(logging.DEBUG)

    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(logging.Formatter("[%(levelname)s] %(name)s · %(message)s"))
    sh.setLevel(logging.INFO)

    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger
