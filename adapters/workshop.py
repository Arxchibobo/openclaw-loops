"""art 站 workshop review adapter.

Two-layer review for bot demands:
  1. *Hard block*  — categories / tags that we will never build (csam,
     real-person-non-consensual, violence). These get a deterministic reject.
  2. *SOP routing* — everything else is routed by the demand's ``sop``
     field to the matching pipeline (sfw / nsfw-shellagent-encrypted).
     NSFW is *not* hard-blocked: Lucas's SOP requires shellagent-encrypted
     RH workflow + `hardcoded_target_video` handling, which lives in
     ``adapters.workshop_sop`` (P1-3).

Return shape (unchanged for back-compat with existing pipelines):
    {
      "approved":     [...],  # routed to step3/workshop_sop
      "rejected":     [...],  # reason stamped on each item
      "pending_human":[...],  # score < floor or unknown sop
    }

Config hooks (config/loops/bot_listing.yaml → adapters.workshop.review_rules):
    min_score:       0.7
    forbidden_tags:  ["csam", "violence", "non_consensual"]
    allowed_sops:    ["sfw_standard", "nsfw_shellagent_encrypted"]

NOTE: ``forbidden_tags`` must *not* include ``nsfw`` anymore — that used to
reject every porn-site demand before SOP routing existed. NSFW is a
legitimate pipeline now (2026-04-29, lucas-clawd GTM Loop Step 2).
"""
from __future__ import annotations

from typing import Any

from core.config import load_config

# Tags that will never make it through regardless of SOP. These are hard
# content-policy lines, not NSFW (which is handled by the encrypted SOP).
DEFAULT_HARD_FORBIDDEN = ("csam", "violence", "non_consensual", "minor")

# SOPs we know how to execute downstream. Unknown SOPs land in pending_human
# so a human decides whether to add a new pipeline.
DEFAULT_ALLOWED_SOPS = ("sfw_standard", "nsfw_shellagent_encrypted")


def _resolve_cfg() -> dict[str, Any]:
    try:
        return load_config().raw["adapters"]["workshop"]["review_rules"]
    except Exception:
        return {}


def review(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    cfg = _resolve_cfg()
    min_score = float(cfg.get("min_score", 0.7))
    forbidden = set(cfg.get("forbidden_tags", DEFAULT_HARD_FORBIDDEN))
    allowed_sops = set(cfg.get("allowed_sops", DEFAULT_ALLOWED_SOPS))

    approved, rejected, pending = [], [], []
    for it in items:
        tags = set(it.get("tags", []))
        category = it.get("category")
        sop = it.get("sop")
        score = float(it.get("score", 0.0))

        # 1. Hard content block — tag-level OR category-level.
        hard_hit = tags & forbidden
        if hard_hit or category in forbidden:
            rejected.append({**it, "reason": f"hard-forbidden: {hard_hit or {category}}"})
            continue

        # 2. SOP gating — only demands with a known SOP can be auto-routed.
        if sop and sop not in allowed_sops:
            pending.append({**it, "reason": f"unknown sop: {sop!r}"})
            continue

        # 3. Score floor (skip when demand has pre-approval from human gate).
        human_approved = it.get("human_approval_status") == "approved"
        if human_approved or score >= min_score:
            approved.append(it)
        else:
            pending.append({**it, "reason": f"score {score} < {min_score}"})

    return {"approved": approved, "rejected": rejected, "pending_human": pending}
