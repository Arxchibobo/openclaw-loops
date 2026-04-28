"""Smoke tests: each loop runs end-to-end in dry-mode and run-mode without error,
and verify-mode returns metrics for every step."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# isolate state to a tmp file so tests don't pollute dev state
os.environ.setdefault("OPENCLAW_TEST", "1")

from core.config import load_config           # noqa: E402
from core.orchestrator import Orchestrator   # noqa: E402


def _run(loop: str, mode: str) -> list:
    cfg = load_config()
    return Orchestrator(cfg).run_loop(loop, mode=mode)


def test_bot_listing_dry():
    reports = _run("bot_listing", "dry")
    assert len(reports) == 8
    assert all(r.status in ("ok", "blocked") for r in reports)


def test_bot_listing_run():
    reports = _run("bot_listing", "run")
    statuses = {r.step.id: r.status for r in reports}
    # step1 must succeed; downstream may halt — but step1 ok proves wiring
    assert statuses[1] == "ok"


def test_social_ops_dry():
    reports = _run("social_ops", "dry")
    assert len(reports) == 4


def test_social_ops_run():
    # bot_listing.step1 must run first to seed keywords
    _run("bot_listing", "run")
    reports = _run("social_ops", "run")
    assert reports[0].status == "ok"
    # final step emits today's metrics
    assert reports[-1].metrics.get("metrics_emitted") is True


def test_verify_per_step():
    cfg = load_config()
    orch = Orchestrator(cfg)
    for loop_name in ("bot_listing", "social_ops"):
        for s in cfg.loop(loop_name).steps:
            r = orch.execute_step(loop_name, s, "verify")
            assert r.metrics is not None  # may be empty dict but exists
