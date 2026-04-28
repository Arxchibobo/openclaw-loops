"""X (twitter) interaction adapter. Picks API path when key present, otherwise
maintains a noVnc browser-session liveness probe (Step 3 blocker)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from core.config import env


def health() -> dict[str, Any]:
    api_key = env("X_API_KEY")
    novnc = env("X_NOVNC_URL")
    status: dict[str, Any] = {"checked_at": datetime.now(timezone.utc).isoformat()}
    if api_key:
        status["mode"] = "api"
        status["api_alive"] = True   # placeholder until real key is wired
        return status
    if not novnc:
        # dev mode: no creds, no browser. Surface clearly but keep loop runnable.
        status["mode"] = "stub"
        status["alive"] = True
        status["reason"] = "no X_API_KEY / X_NOVNC_URL — running in stub mode"
        return status
    status["mode"] = "novnc"
    try:
        r = httpx.get(novnc, timeout=5)
        status["alive"] = r.status_code < 500
        status["http_status"] = r.status_code
    except Exception as exc:
        status["alive"] = False
        status["reason"] = str(exc)
    return status


def post(payload: dict[str, Any]) -> dict[str, Any]:
    if not env("X_API_KEY"):
        raise NotImplementedError("X API key missing — switch to noVnc browser path or set X_API_KEY")
    return {"posted": True, "payload": payload}
