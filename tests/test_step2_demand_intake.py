"""Tests for the Step 2 bot demand intake + workshop review refactor (2026-04-29).

Covers:
  * adapters.workshop.review no longer hard-rejects category=nsfw
  * adapters.workshop.review hard-rejects csam / violence
  * adapters.workshop.review routes by sop and defers unknown sops to pending
  * adapters.workshop.review honors human_approval_status=approved below score
  * loops.bot_listing.step2_demand_intake strips raw kw before kv_set
  * loops.bot_listing.step2_demand_intake filters to approved-only
  * loops.bot_listing.step2_demand_intake priority sort (high>med>low)
  * adapters.lobster._fetch_slack_file back-compat shim works
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("OPENCLAW_TEST", "1")

from adapters import lobster, workshop  # noqa: E402
from loops.bot_listing import step2_demand_intake  # noqa: E402


# ---------- workshop.review ----------

def test_workshop_review_allows_nsfw_with_valid_sop():
    items = [{
        "id": "D-001",
        "category": "nsfw",
        "sop": "nsfw_shellagent_encrypted",
        "score": 0.9,
        "tags": [],
        "human_approval_status": "approved",
    }]
    out = workshop.review(items)
    assert len(out["approved"]) == 1
    assert out["approved"][0]["id"] == "D-001"
    assert out["rejected"] == []


def test_workshop_review_hard_rejects_csam():
    items = [{"id": "D-002", "category": "nsfw", "sop": "nsfw_shellagent_encrypted",
              "score": 0.9, "tags": ["csam"]}]
    out = workshop.review(items)
    assert len(out["rejected"]) == 1
    assert "hard-forbidden" in out["rejected"][0]["reason"]


def test_workshop_review_hard_rejects_violence():
    items = [{"id": "D-003", "category": "nsfw", "sop": "nsfw_shellagent_encrypted",
              "score": 0.9, "tags": ["violence"]}]
    out = workshop.review(items)
    assert len(out["rejected"]) == 1


def test_workshop_review_defers_unknown_sop_to_pending():
    items = [{"id": "D-004", "category": "sfw", "sop": "freaky_new_sop",
              "score": 0.9, "tags": []}]
    out = workshop.review(items)
    assert out["approved"] == []
    assert len(out["pending_human"]) == 1
    assert "unknown sop" in out["pending_human"][0]["reason"]


def test_workshop_review_human_approval_bypasses_score_floor():
    items = [{"id": "D-005", "category": "sfw", "sop": "sfw_standard",
              "score": 0.1, "tags": [], "human_approval_status": "approved"}]
    out = workshop.review(items)
    assert len(out["approved"]) == 1


def test_workshop_review_low_score_without_human_approval_pending():
    items = [{"id": "D-006", "category": "sfw", "sop": "sfw_standard",
              "score": 0.1, "tags": []}]
    out = workshop.review(items)
    assert out["approved"] == []
    assert len(out["pending_human"]) == 1


# ---------- step2_demand_intake ----------

_SAMPLE_PAYLOAD = {
    "schema": "gtm-loop.bot-demands.v1",
    "source": "lucas-clawd",
    "batch_id": "20260429T051904Z",
    "demands": [
        {"id": "D-001", "kw": "fancy text generator", "kw_hash": "abc",
         "category": "sfw", "workflow_type": "text2image", "sop": "sfw_standard",
         "priority": "high", "target_site": "art", "volume": 60500,
         "human_approval_status": "approved"},
        {"id": "D-002", "kw": "rejected kw", "kw_hash": "def",
         "category": "sfw", "workflow_type": "text2image", "sop": "sfw_standard",
         "priority": "high", "target_site": "art", "volume": 27000,
         "human_approval_status": "rejected"},
        {"id": "D-003", "kw": "low priority sfw", "kw_hash": "ghi",
         "category": "sfw", "workflow_type": "text2image", "sop": "sfw_standard",
         "priority": "low", "target_site": "art", "volume": 5000,
         "human_approval_status": "approved"},
        {"id": "D-004", "kw": "REAL_NSFW_KW_SHOULD_NOT_LEAK", "kw_hash": "jkl",
         "kw_redacted": "[REDACTED_NSFW_KEYWORD]",
         "category": "nsfw", "workflow_type": "face_swap",
         "sop": "nsfw_shellagent_encrypted", "priority": "high",
         "target_site": "porn", "volume": 18100,
         "human_approval_status": "approved"},
        {"id": "D-005", "kw": "pending", "kw_hash": "mno",
         "category": "sfw", "sop": "sfw_standard", "priority": "medium",
         "volume": 8000, "human_approval_status": "pending_review"},
    ],
}


def test_step2_pulls_approved_only_and_sorts_by_priority():
    step = step2_demand_intake.Step()
    ctx: dict = {}
    with patch.object(lobster, "_fetch_slack_file", return_value=_SAMPLE_PAYLOAD):
        with patch.dict(os.environ, {"LUCAS_DEMAND_CHANNEL": "C_TEST"}):
            with patch.object(step2_demand_intake, "kv_set") as mock_kv_set:
                out = step.execute(ctx)
    # only approved (D-001, D-003, D-004) — not D-002 (rejected), D-005 (pending)
    ids = [d["id"] for d in ctx["demands"]]
    assert ids == ["D-001", "D-004", "D-003"], ids  # high(vol desc) then low
    assert out["metrics"]["draft_count"] == 3
    assert out["metrics"]["nsfw_count"] == 1
    assert out["metrics"]["sfw_count"] == 2
    # kv_set called with kw-stripped rows
    kv_calls = [c for c in mock_kv_set.call_args_list if c.args[:2] == ("bot_listing", "demands")]
    assert kv_calls, "kv_set('bot_listing', 'demands', ...) not called"
    persisted = kv_calls[0].args[2]
    for row in persisted:
        assert "kw" not in row, f"raw kw leaked to kv store: {row}"
        assert "id" in row and "kw_hash" in row


def test_step2_dry_run_does_not_persist():
    step = step2_demand_intake.Step()
    ctx: dict = {"dry_run": True}
    with patch.object(lobster, "_fetch_slack_file", return_value=_SAMPLE_PAYLOAD):
        with patch.dict(os.environ, {"LUCAS_DEMAND_CHANNEL": "C_TEST"}):
            with patch.object(step2_demand_intake, "kv_set") as mock_kv_set:
                out = step.execute(ctx)
    assert mock_kv_set.call_count == 0
    # but ctx still populated so downstream can inspect
    assert len(ctx["demands"]) == 3
    assert out["metrics"]["draft_count"] == 3


def test_step2_nsfw_kw_redaction_in_log_meta():
    step = step2_demand_intake.Step()
    ctx: dict = {}
    captured: list = []

    def fake_bridge_send(kind, msg, meta=None):
        captured.append({"kind": kind, "msg": msg, "meta": meta or {}})

    with patch.object(lobster, "_fetch_slack_file", return_value=_SAMPLE_PAYLOAD):
        with patch.dict(os.environ, {"LUCAS_DEMAND_CHANNEL": "C_TEST"}):
            with patch.object(step2_demand_intake.bridge, "send", side_effect=fake_bridge_send):
                with patch.object(step2_demand_intake, "kv_set"):
                    step.execute(ctx)
    # raw NSFW kw must not appear anywhere in bridge log meta
    all_text = repr(captured)
    assert "REAL_NSFW_KW_SHOULD_NOT_LEAK" not in all_text, \
        "raw NSFW kw leaked into bridge.send log"
    # but D-004 id should show up via _redact output
    assert "D-004" in all_text


def test_step2_skips_unknown_schema():
    step = step2_demand_intake.Step()
    ctx: dict = {}
    bad_payload = {"schema": "something-else.v1", "demands": [_SAMPLE_PAYLOAD["demands"][0]]}
    with patch.object(lobster, "_fetch_slack_file", return_value=bad_payload):
        with patch.dict(os.environ, {"LUCAS_DEMAND_CHANNEL": "C_TEST"}):
            with patch.object(step2_demand_intake, "kv_set"):
                out = step.execute(ctx)
    assert out["metrics"]["draft_count"] == 0


def test_step2_no_config_returns_empty_not_raise():
    step = step2_demand_intake.Step()
    ctx: dict = {}
    with patch.dict(os.environ, {}, clear=False):
        for k in ("LUCAS_DEMAND_CHANNEL", "LOBSTER_SLACK_CHANNEL"):
            os.environ.pop(k, None)
        out = step.execute(ctx)
    assert out["demands"] == []


# ---------- lobster adapter back-compat ----------

def test_fetch_slack_latest_backcompat_shim():
    # Old callers use _fetch_slack_latest(side); verify it still resolves
    # to the generalized helper with the right prefix.
    with patch.object(lobster, "_fetch_slack_file") as mock:
        mock.return_value = []
        lobster._fetch_slack_latest("amy")
        assert mock.call_args.args[0] == "amy-listings-snapshot"
