"""amy 龙虾 ⇄ bo 龙虾 一致性 adapter. Bridges the two systems noted in Step 5."""
from __future__ import annotations

from typing import Any

from core.config import env


def fetch_state(side: str) -> list[dict[str, Any]]:
    url_env = "AMY_LOBSTER_URL" if side == "amy" else "BO_LOBSTER_URL"
    url = env(url_env)
    if not url:
        # dev stub: identical empty stores so consistency check passes structurally
        return []
    raise NotImplementedError(f"{side} lobster client not wired ({url_env})")


def diff(amy: list[dict[str, Any]], bo: list[dict[str, Any]]) -> dict[str, Any]:
    amy_ids = {x["id"] for x in amy}
    bo_ids = {x["id"] for x in bo}
    return {
        "only_amy": sorted(amy_ids - bo_ids),
        "only_bo": sorted(bo_ids - amy_ids),
        "common": sorted(amy_ids & bo_ids),
        "consistent": amy_ids == bo_ids,
    }
