"""Tests for adapters.workshop_sop (P1-3) + step4 SOP routing."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("OPENCLAW_TEST", "1")

import pytest  # noqa: E402

from adapters import workshop_sop  # noqa: E402
from loops.bot_listing import step4_acceptance  # noqa: E402


# ---------- routing table ----------

def test_route_sfw_text2image():
    d = {"sop": "sfw_standard", "workflow_type": "text2image"}
    r = workshop_sop.resolve_route(d)
    assert r["kind"] == "genimage"
    assert r["backend"] == "rh"


def test_route_nsfw_face_swap_requires_encrypted_and_probe():
    d = {"sop": "nsfw_shellagent_encrypted", "workflow_type": "face_swap"}
    r = workshop_sop.resolve_route(d)
    assert r["kind"] == "rh_webapp"
    assert r["requires_encrypted_refs"] is True
    assert r["requires_sfw_probe"] is True


def test_route_unknown_returns_empty():
    r = workshop_sop.resolve_route({"sop": "bogus", "workflow_type": "text2image"})
    assert r == {}


# ---------- run_pipeline dry ----------

def _demand(**kw):
    base = {
        "id": "D-001", "kw": "sample", "category": "sfw",
        "workflow_type": "text2image", "sop": "sfw_standard",
    }
    base.update(kw)
    return base


def test_run_pipeline_dry_sfw_emits_bot_status():
    status = workshop_sop.run_pipeline(_demand(), dry_run=True)
    assert isinstance(status, workshop_sop.BotStatus)
    assert status.demand_id == "D-001"
    assert status.status == "dev_in_progress"
    assert "sfw" in status.notes


def test_run_pipeline_dry_nsfw_uses_nsfw_pipeline_and_webapp():
    d = _demand(id="D-NSFW", category="nsfw",
                sop="nsfw_shellagent_encrypted", workflow_type="face_swap",
                kw="SECRET_NSFW_TOKEN")
    status = workshop_sop.run_pipeline(d, dry_run=True)
    assert status.status == "dev_in_progress"
    assert status.rh_workflow_id == "1892125635609845761"
    assert "nsfw" in status.notes
    # status object must not echo back the raw kw anywhere
    assert "SECRET_NSFW_TOKEN" not in repr(status)


def test_run_pipeline_unknown_route_blocks():
    d = _demand(sop="sfw_standard", workflow_type="unsupported_thing")
    status = workshop_sop.run_pipeline(d, dry_run=True)
    assert status.status == "blocked"
    assert "no RH route" in status.notes


def test_run_pipeline_logs_never_leak_raw_nsfw_kw():
    captured: list[dict] = []

    def fake_send(kind, msg, meta=None):
        captured.append({"kind": kind, "msg": msg, "meta": meta or {}})

    d = _demand(id="D-LEAK", category="nsfw",
                sop="nsfw_shellagent_encrypted", workflow_type="face_swap",
                kw="REAL_NSFW_KW_SHOULD_NOT_LEAK")
    with patch.object(workshop_sop.bridge, "send", side_effect=fake_send):
        workshop_sop.run_pipeline(d, dry_run=True)
    dump = repr(captured)
    assert "REAL_NSFW_KW_SHOULD_NOT_LEAK" not in dump
    assert "D-LEAK" in dump


# ---------- executor injection ----------

def test_set_executor_overrides_dry_fallback():
    calls = []

    def fake_exec(demand, pipeline_ctx):
        calls.append((demand["id"], pipeline_ctx["pipeline"]))
        return workshop_sop.BotStatus(
            demand_id=demand["id"],
            status="ready_for_landing_page",
            bot_id="1776123456.0",
            bot_name="Fancy Text Generator",
        )

    workshop_sop.set_executor(fake_exec)
    try:
        status = workshop_sop.run_pipeline(_demand(id="D-Q"), dry_run=False)
    finally:
        workshop_sop.set_executor(None)

    assert calls == [("D-Q", "sfw")]
    assert status.status == "ready_for_landing_page"
    assert status.bot_id == "1776123456.0"


def test_dry_run_ignores_registered_executor():
    """dry_run=True must bypass any registered real executor."""
    def should_not_run(demand, pipeline_ctx):
        raise AssertionError("real executor must NOT fire in dry_run=True")

    workshop_sop.set_executor(should_not_run)
    try:
        status = workshop_sop.run_pipeline(_demand(id="D-DRY"), dry_run=True)
    finally:
        workshop_sop.set_executor(None)
    assert status.status == "dev_in_progress"


# ---------- run_batch ----------

def test_run_batch_preserves_order():
    batch = [_demand(id="D-1"), _demand(id="D-2"), _demand(id="D-3")]
    out = workshop_sop.run_batch(batch, dry_run=True)
    assert [s.demand_id for s in out] == ["D-1", "D-2", "D-3"]


# ---------- defensive: lucas PR#2 review ----------

def test_rh_workflow_id_is_none_not_empty_string_when_route_lacks_id():
    """image2video route has workflow_id=None and no webapp_id.
    Downstream consumers distinguish None (not-yet-picked) from a real id,
    NOT from empty string. Ref: lucas-clawd PR#2 review."""
    d = _demand(workflow_type="image2video")  # route has workflow_id=None
    status = workshop_sop.run_pipeline(d, dry_run=True)
    assert status.rh_workflow_id is None, (
        f"expected None for not-yet-picked workflow, got {status.rh_workflow_id!r}"
    )


def test_rh_workflow_id_preserved_when_route_has_id():
    d = _demand(workflow_type="face_swap")
    status = workshop_sop.run_pipeline(d, dry_run=True)
    assert status.rh_workflow_id == "1838819177871339522"


def test_notes_scrubs_raw_nsfw_kw_from_buggy_executor():
    """If a real executor accidentally embeds the raw NSFW kw in notes,
    run_pipeline must strip it before the status is returned."""
    def leaky_exec(demand, pipeline_ctx):
        # simulate f-string leak
        return workshop_sop.BotStatus(
            demand_id=demand["id"],
            status="ready_for_landing_page",
            notes=f"processed prompt: {demand['kw']!r} successfully",
        )

    d = _demand(id="D-LEAK2", category="nsfw",
                sop="nsfw_shellagent_encrypted", workflow_type="face_swap",
                kw="NSFW_LEAK_VIA_NOTES_FIELD")
    workshop_sop.set_executor(leaky_exec)
    try:
        status = workshop_sop.run_pipeline(d, dry_run=False)
    finally:
        workshop_sop.set_executor(None)
    assert "NSFW_LEAK_VIA_NOTES_FIELD" not in status.notes
    assert "[REDACTED]" in status.notes


def test_notes_scrub_skips_sfw_demands():
    """SFW kw is safe to surface; scrub must not touch SFW notes."""
    def echoing_exec(demand, pipeline_ctx):
        return workshop_sop.BotStatus(
            demand_id=demand["id"],
            status="ready_for_landing_page",
            notes=f"used kw: {demand['kw']}",
        )

    d = _demand(id="D-SFW", category="sfw", kw="fancy text generator")
    workshop_sop.set_executor(echoing_exec)
    try:
        status = workshop_sop.run_pipeline(d, dry_run=False)
    finally:
        workshop_sop.set_executor(None)
    assert "fancy text generator" in status.notes


# ---------- step4 integration ----------

def test_step4_routes_sop_demands_to_workshop_sop():
    """step4 should dispatch approved demands with sop through workshop_sop
    and still emit `acceptance_passed` metric."""
    from core.state import kv_get, kv_set  # noqa: E402

    kv_set("bot_listing", "review_result", {
        "approved": [
            {"id": "D-1", "sop": "sfw_standard", "workflow_type": "text2image"},
            {"id": "D-2", "sop": "nsfw_shellagent_encrypted",
             "workflow_type": "face_swap"},
        ],
        "rejected": [],
        "pending_human": [],
    })

    step = step4_acceptance.Step()
    # provide in-memory demands with raw kw — step4 must prefer these
    ctx = {
        "demands": [
            {"id": "D-1", "kw": "visible", "sop": "sfw_standard",
             "workflow_type": "text2image", "category": "sfw"},
            {"id": "D-2", "kw": "NSFW_SECRET_IN_CTX", "kw_redacted": "[RED]",
             "sop": "nsfw_shellagent_encrypted",
             "workflow_type": "face_swap", "category": "nsfw"},
        ],
        "dry_run": True,
    }
    out = step.execute(ctx)

    assert out["metrics"]["via_sop"] == 2
    assert out["metrics"]["acceptance_passed"] is True
    # kv persisted BotStatus dicts
    statuses = kv_get("bot_listing", "bot_statuses") or []
    assert len(statuses) == 2
    assert {s["demand_id"] for s in statuses} == {"D-1", "D-2"}


def test_step4_falls_back_to_legacy_stub_when_no_sop():
    """Without sop the step should behave exactly like the old stub."""
    from core.state import kv_set  # noqa: E402

    kv_set("bot_listing", "review_result", {
        "approved": [{"id": "LEGACY-1"}],  # no sop
        "rejected": [],
        "pending_human": [],
    })
    step = step4_acceptance.Step()
    out = step.execute({"dry_run": True})
    assert out["metrics"]["acceptance_passed"] is True
    assert out["metrics"]["via_sop"] == 0
    assert out["results"][0]["checks"]  # 4-item stub still there


def test_step4_real_executor_injection_path():
    """When a real executor is registered, step4 non-dry runs use it."""
    from core.state import kv_set  # noqa: E402

    captured = []

    def real(demand, pipeline_ctx):
        captured.append(demand["id"])
        return workshop_sop.BotStatus(
            demand_id=demand["id"],
            status="ready_for_landing_page",
            bot_id="999.0",
        )

    kv_set("bot_listing", "review_result", {
        "approved": [{"id": "D-EXEC", "sop": "sfw_standard",
                      "workflow_type": "text2image"}],
        "rejected": [],
        "pending_human": [],
    })

    workshop_sop.set_executor(real)
    try:
        out = step4_acceptance.Step().execute({
            "demands": [{"id": "D-EXEC", "kw": "k", "sop": "sfw_standard",
                          "workflow_type": "text2image", "category": "sfw"}],
            "dry_run": False,
        })
    finally:
        workshop_sop.set_executor(None)

    assert captured == ["D-EXEC"]
    assert out["bot_statuses"][0]["status"] == "ready_for_landing_page"
    assert out["bot_statuses"][0]["bot_id"] == "999.0"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
