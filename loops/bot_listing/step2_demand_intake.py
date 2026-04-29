"""Step 2 · bot demand intake.

Pulls ``bot_demands_*.approved.json`` files that lucas-clawd uploads into a
tracked Slack thread, keeps only ``human_approval_status == "approved"``
entries, and exposes them to downstream steps.

Designed contract (cross-lobster, 2026-04-29):
  * Transport: Slack files API (reuses ``adapters.lobster._fetch_slack_file``)
  * Channel:   ``LUCAS_DEMAND_CHANNEL`` (default: ``LOBSTER_SLACK_CHANNEL``)
  * Thread:    ``LUCAS_DEMAND_THREAD`` (optional; when set we filter to that
               thread only to keep the exchange tidy)
  * Filename:  ``bot_demands_*.approved.json`` > ``bot_demands_*.json``
               (approved suffix wins; unapproved batches are ignored)
  * Schema:    ``gtm-loop.bot-demands.v1``

NSFW privacy rules (hard):
  * The JSON file carries the raw ``kw`` (NSFW real terms). This process
    reads it into memory only.
  * ``kv_set`` persists only ``{id, kw_hash, category, sop, priority,
    human_approval_status, workflow_type, target_site}`` — the real ``kw``
    is stripped before any store / log / bridge message.
  * Bridge + log messages use ``kw_redacted`` or the demand ``id``.
  * Raw payload is fetched via ``_fetch_slack_file`` (returns parsed JSON)
    and never written to disk.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from adapters import lobster
from core import bridge
from core.config import env
from adapters import ephemeral_kw
from core.state import kv_get, kv_set
from loops.base import BaseStep

SCHEMA = "gtm-loop.bot-demands.v1"
APPROVED_STATUS = "approved"

# Fields that are safe to persist across loop runs. Anything else (most
# importantly raw `kw` for NSFW) lives only in the per-run process memory.
SAFE_KV_FIELDS = (
    "id",
    "kw_hash",
    "category",
    "sop",
    "priority",
    "human_approval_status",
    "workflow_type",
    "target_site",
    "created_at",
)


def _redact(demand: dict[str, Any]) -> str:
    """Return a log-safe identifier (D-id + kw_redacted when available)."""
    did = demand.get("id", "?")
    if demand.get("category") == "nsfw":
        return f"{did} [{demand.get('kw_redacted', '[REDACTED]')}]"
    # SFW is safe to surface
    return f"{did} [{demand.get('kw', '?')}]"


def _safe_payload(demand: dict[str, Any]) -> dict[str, Any]:
    """Strip raw `kw` / requirements for persistent storage."""
    return {k: demand.get(k) for k in SAFE_KV_FIELDS if k in demand}


def _pull_approved(channel: str, thread_ts: str | None) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Fetch the most recent ``bot_demands_*`` batch from the Slack thread.

    Filename doesn't matter: ``_fetch_slack_file`` grabs whatever starts with
    the prefix (plain or ``.approved.json`` suffix), and we filter on the
    ``human_approval_status`` field of each demand — which is the source of
    truth. This means lucas can upload unapproved batches as pending state
    without them polluting the intake; only demands with status=='approved'
    surface here.

    Returns (demands, meta). ``meta`` is the top-level batch dict minus the
    ``demands`` list (batch_id, source, schema, generated_at) — useful for
    traceability + status callbacks later.
    """
    payload = lobster._fetch_slack_file(
        "bot_demands_", channel=channel, thread_ts=thread_ts, unwrap=False,
    )
    if not isinstance(payload, dict):
        return [], None
    if payload.get("schema") != SCHEMA:
        bridge.send("log", "[demand-intake] skipped file: schema mismatch",
                    meta={"schema": payload.get("schema")})
        return [], None
    demands = payload.get("demands") or []
    approved = [d for d in demands if d.get("human_approval_status") == APPROVED_STATUS]
    meta = {k: v for k, v in payload.items() if k != "demands"}
    return approved, meta


class Step(BaseStep):
    LOOP = "bot_listing"
    KEY = "demand_intake"

    def plan(self, ctx: dict[str, Any]) -> str:
        return ("poll lucas-clawd Slack thread for approved bot_demands_*.json, "
                "filter human_approval_status==approved, expose to downstream "
                "steps via ctx (in-memory) and kv_set (kw-stripped).")

    def synthetic_metrics(self, ctx: dict[str, Any]) -> dict[str, Any]:
        return {"demands_recorded": True, "draft_count": 4}

    def execute(self, ctx: dict[str, Any]) -> dict[str, Any]:
        dry_run = bool(ctx.get("dry_run"))
        channel = env("LUCAS_DEMAND_CHANNEL") or env("LOBSTER_SLACK_CHANNEL")
        thread_ts = env("LUCAS_DEMAND_THREAD")  # optional
        if not channel:
            bridge.send("log", "[demand-intake] LUCAS_DEMAND_CHANNEL / "
                        "LOBSTER_SLACK_CHANNEL not configured; skipping.")
            return {"demands": [], "metrics": {"demands_recorded": False, "draft_count": 0}}

        demands, meta = _pull_approved(channel, thread_ts)

        # Priority ordering: high > medium > low, then by (volume desc).
        priority_rank = {"high": 0, "medium": 1, "low": 2}
        demands.sort(key=lambda d: (
            priority_rank.get(d.get("priority") or "low", 3),
            -int(d.get("volume", 0) or 0),
        ))

        # Persist only the kw-stripped slice for cross-run visibility.
        safe_rows = [_safe_payload(d) for d in demands]
        if not dry_run:
            kv_set("bot_listing", "demands", safe_rows)
            if meta:
                kv_set("bot_listing", "demand_batch_meta", meta)
            kv_set("bot_listing", "demand_intake_last_run",
                   datetime.now(timezone.utc).isoformat())

        # In-memory handoff to downstream steps (step3_workshop_review).
        # These contain the real kw — must not be serialized past loop end.
        ctx["demands"] = demands
        ctx["demand_batch_meta"] = meta

        # Per-process ephemeral store keyed by demand_id. This is the ONLY
        # path by which step4's real executor (cyber-developer-cron) can
        # recover the raw kw without it crossing sqlite / Slack / logs.
        # Wiped at clear() — callers control lifecycle.
        if not dry_run:
            ephemeral_kw.clear()  # fresh batch, no stale bleed
            for d in demands:
                if d.get("id") and d.get("kw"):
                    ephemeral_kw.set_kw(d["id"], d["kw"])

        redacted_ids = [_redact(d) for d in demands]
        bridge.send("log",
                    f"[demand-intake] pulled {len(demands)} approved demands "
                    f"(dry_run={dry_run})",
                    meta={
                        "count": len(demands),
                        "dry_run": dry_run,
                        "batch_id": (meta or {}).get("batch_id"),
                        "ids": redacted_ids,
                    })

        return {
            "demands": safe_rows,  # return kw-stripped view (not raw)
            "demand_batch_meta": meta,
            "metrics": {
                "demands_recorded": bool(demands),
                "draft_count": len(demands),
                "nsfw_count": sum(1 for d in demands if d.get("category") == "nsfw"),
                "sfw_count": sum(1 for d in demands if d.get("category") == "sfw"),
            },
        }

    def read_metrics(self, ctx: dict[str, Any]) -> dict[str, Any]:
        demands = kv_get("bot_listing", "demands", []) or []
        return {
            "demands_recorded": bool(demands),
            "draft_count": len(demands),
            "nsfw_count": sum(1 for d in demands if d.get("category") == "nsfw"),
            "sfw_count": sum(1 for d in demands if d.get("category") == "sfw"),
        }
