"""SEO keyword scrape adapter. Replace the http call with the real CLAWbo
endpoint when ready; until then, returns a stub set so the loop can advance."""
from __future__ import annotations

from datetime import date
from typing import Any

from core.config import env
from core.state import kv_set


def scrape(provider: str = "clawbo", limit: int = 100) -> list[dict[str, Any]]:
    base_url = env("SEO_BASE_URL")
    if not base_url:
        # fallback stub keeps pipeline observable in dev. Includes realistic
        # duplicates (case, punct, plural, substring) so the v2 cleaner has
        # something meaningful to remove.
        bases = ["ai agent", "ai-agent", "AI Agent", "agentic ai", "llm app",
                 "LLM Apps", "rag pipeline", "rag pipelines", "vector db",
                 "vector database", "prompt engineering", "prompt-engineering"]
        keywords: list[dict[str, Any]] = []
        for i in range(min(limit, 80)):
            base = bases[i % len(bases)]
            keywords.append({
                "kw": base if i < len(bases) * 4 else f"{base} {i}",
                "volume": 1000 - i * 7,
                "trend": "rising" if i % 3 else "flat",
            })
        kv_set("seo", f"snapshot:{date.today().isoformat()}", keywords)
        return keywords
    raise NotImplementedError(
        f"real SEO scrape via {provider} at {base_url} not wired yet — set adapter.")
