"""Tests for scripts.upload_bot_status (P1-4)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("OPENCLAW_TEST", "1")

from scripts import upload_bot_status as ubs  # noqa: E402


def test_build_payload_shape_matches_spec():
    """Must match gtm-loop.bot-status.v1 schema lucas-clawd pull expects."""
    statuses = [{"demand_id": "D-1", "status": "ready_for_landing_page",
                 "bot_id": "999.0", "bot_name": "Fancy Text Gen",
                 "workshop_url": "https://art.myshell.ai/workshop/detail?id=abc",
                 "rh_workflow_id": "pngtuber_base",
                 "acceptance_result": {"trigger_works": True},
                 "notes": "ok", "updated_at": "2026-04-29T10:00:00+00:00"}]
    p = ubs.build_payload("20260429T104806Z", statuses)
    assert p["schema"] == "gtm-loop.bot-status.v1"
    assert p["batch_id"] == "20260429T104806Z"
    assert p["source"] == "bobo-clawd"
    assert "generated_at" in p
    assert p["statuses"] == statuses


def test_scrub_removes_kw_key_from_top_level_and_acceptance_result():
    statuses = [
        {"demand_id": "D-1", "status": "ready_for_landing_page",
         "kw": "NSFW_LEAK",  # buggy executor wrote it
         "acceptance_result": {"trigger_works": True, "kw": "ALSO_LEAK"}},
    ]
    cleaned = ubs._scrub(statuses)
    assert "kw" not in cleaned[0]
    assert "kw" not in cleaned[0]["acceptance_result"]
    assert cleaned[0]["acceptance_result"]["trigger_works"] is True


def test_summary_line_groups_by_status():
    payload = {
        "batch_id": "B1",
        "statuses": [
            {"status": "ready_for_landing_page"},
            {"status": "ready_for_landing_page"},
            {"status": "dev_in_progress"},
            {"status": "blocked"},
        ],
    }
    line = ubs._summary_line(payload)
    assert "B1" in line
    assert "blocked=1" in line
    assert "dev_in_progress=1" in line
    assert "ready_for_landing_page=2" in line
    assert "4 status" in line


def test_upload_calls_slack_with_thread_ts():
    """Full upload path with Slack API mocked; verify thread_ts propagates."""
    get_url_resp = type("R", (), {
        "status_code": 200,
        "raise_for_status": lambda self: None,
        "json": lambda self: {"ok": True,
                              "upload_url": "https://files.slack.com/up",
                              "file_id": "F_TEST"},
    })()
    put_resp = type("R", (), {
        "status_code": 200,
        "raise_for_status": lambda self: None,
    })()
    complete_resp = type("R", (), {
        "status_code": 200,
        "raise_for_status": lambda self: None,
        "json": lambda self: {"ok": True, "files": [{"id": "F_TEST"}]},
    })()

    calls = []

    def fake_post(url, **kw):
        calls.append({"url": url, "data": kw.get("data"),
                      "content": kw.get("content")})
        if "getUploadURLExternal" in url:
            return get_url_resp
        if url == "https://files.slack.com/up":
            return put_resp
        if "completeUploadExternal" in url:
            return complete_resp
        raise AssertionError(f"unexpected url: {url}")

    payload = ubs.build_payload("B-TEST", [{"demand_id": "D-1",
                                             "status": "ready_for_landing_page"}])
    with patch.dict(os.environ, {"SLACK_BOT_TOKEN": "xoxb-t"}):
        with patch.object(ubs.httpx, "post", side_effect=fake_post):
            out = ubs.upload(payload, channel="C_T",
                             thread_ts="1777350243.248729",
                             comment="test")
    assert out["file_id"] == "F_TEST"
    complete_call = [c for c in calls if "completeUploadExternal" in c["url"]][0]
    # thread_ts must be in the complete payload body
    body = json.loads(complete_call["content"].decode("utf-8"))
    assert body["thread_ts"] == "1777350243.248729"
    assert body["channel_id"] == "C_T"
    assert body["files"][0]["id"] == "F_TEST"


def test_upload_without_thread_ts_omits_it():
    get_url_resp = type("R", (), {
        "status_code": 200, "raise_for_status": lambda self: None,
        "json": lambda self: {"ok": True, "upload_url": "u", "file_id": "F"}})()
    put_resp = type("R", (), {"status_code": 200,
                               "raise_for_status": lambda self: None})()
    complete_resp = type("R", (), {
        "status_code": 200, "raise_for_status": lambda self: None,
        "json": lambda self: {"ok": True, "files": []}})()

    captured_bodies = []

    def fake_post(url, **kw):
        if "getUploadURLExternal" in url:
            return get_url_resp
        if url == "u":
            return put_resp
        if "completeUploadExternal" in url:
            captured_bodies.append(kw.get("content"))
            return complete_resp
        raise AssertionError(url)

    payload = ubs.build_payload("B-NT", [{"demand_id": "D", "status": "blocked"}])
    with patch.dict(os.environ, {"SLACK_BOT_TOKEN": "xoxb-t"}):
        with patch.object(ubs.httpx, "post", side_effect=fake_post):
            ubs.upload(payload, channel="C_T", thread_ts=None, comment="c")
    body = json.loads(captured_bodies[0].decode("utf-8"))
    assert "thread_ts" not in body


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
