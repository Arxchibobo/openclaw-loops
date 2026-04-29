"""Process-local ephemeral keyword store.

Motivation: step2 populates kv with kw_hash only (so the raw keyword never
persists to sqlite / Slack files / logs). But step4's real executor (wiring
up art.myshell.ai through Playwright) *does* need the raw kw to set the
workshop bot title. These are in the same Python process — we can share
via a module-level dict without crossing any persistence boundary.

Rules (enforced by both writer and reader):
  * Only step2_demand_intake writes here (after pulling the approved JSON).
  * Only step4 / workshop_sop executors read here.
  * Data is keyed by demand_id.
  * Cleared at the end of each loop run to avoid cross-batch bleed.
  * kv.sqlite / Slack files / structured logs NEVER see these values.

This is *not* a NSFW safety bypass — NSFW kws stay in-memory and never
get uploaded or kv_set; the scrub layer in workshop_sop plus the
upload_bot_status._scrub continue to strip any leaks.
"""
from __future__ import annotations

_EPHEMERAL: dict[str, str] = {}


def set_kw(demand_id: str, kw: str) -> None:
    """Register the raw kw for this demand. Overwrites silently."""
    _EPHEMERAL[demand_id] = kw


def get_kw(demand_id: str) -> str | None:
    """Look up raw kw. Returns None if not registered (e.g. re-used after
    clear, or running without step2 setup)."""
    return _EPHEMERAL.get(demand_id)


def clear() -> None:
    """Wipe the store. Called between loop runs."""
    _EPHEMERAL.clear()


def snapshot_keys() -> list[str]:
    """For diagnostics only — returns demand_ids, never kws."""
    return list(_EPHEMERAL.keys())
