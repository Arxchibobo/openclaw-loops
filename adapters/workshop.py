"""art站 workshop 审核 adapter. Combines rule engine + LLM second-pass.

This is the documented bottleneck (人肉审核). The flow:
  1. rules layer: forbidden tags / score floor → fast deterministic reject.
  2. (optional) llm layer: when configured, ambiguous items go to LLM.
  3. anything still ambiguous lands in `pending_human` queue; openclaw notifies.
"""
from __future__ import annotations

from typing import Any

from core.config import load_config


def review(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    cfg = load_config().raw["adapters"]["workshop"]["review_rules"]
    min_score = float(cfg.get("min_score", 0.7))
    forbidden = set(cfg.get("forbidden_tags", []))

    approved, rejected, pending = [], [], []
    for it in items:
        tags = set(it.get("tags", []))
        score = float(it.get("score", 0.0))
        if tags & forbidden:
            rejected.append({**it, "reason": f"forbidden tags: {tags & forbidden}"})
        elif score >= min_score:
            approved.append(it)
        else:
            pending.append({**it, "reason": f"score {score} < {min_score}"})
    return {"approved": approved, "rejected": rejected, "pending_human": pending}
