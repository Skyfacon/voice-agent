from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
APP = (
    REPO_ROOT
    / "experiments"
    / "qwen_audio_realtime_web"
    / "static"
    / "app.js"
)
INDEX = APP.with_name("index.html")
HARNESS = Path(__file__).with_name("qwen_app_transcript_harness.js")
NODE = shutil.which("node")


def test_page_exposes_one_accessible_unified_conversation_log() -> None:
    index = INDEX.read_text(encoding="utf-8")

    assert 'id="conversationTranscript"' in index
    assert 'role="log"' in index
    assert 'aria-live="polite"' in index
    assert 'id="conversationLatestBtn"' in index


def run_transcript_scenario(scenario: str) -> dict:
    if NODE is None:
        pytest.skip("Node.js is required to execute the browser transcript harness")
    completed = subprocess.run(
        [NODE, str(HARNESS), scenario, str(APP)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["status"] == "passed"
    assert result["scenario"] == scenario
    return result


def test_user_delta_replaces_confirmed_and_stash_before_final() -> None:
    result = run_transcript_scenario("user_projection")

    assert result == {
        "status": "passed",
        "scenario": "user_projection",
        "turn_count": 1,
        "user_text": "你好世界",
    }


def test_assistant_deltas_append_and_done_closes_draft() -> None:
    result = run_transcript_scenario("assistant_projection")

    assert result["assistant_text"] == "答案"
    assert result["assistant_status"] == "text_done"


def test_three_rounds_render_in_user_then_assistant_order() -> None:
    assert run_transcript_scenario("three_rounds")["turn_count"] == 3


def test_assistant_first_and_missing_user_boundaries_stay_structured() -> None:
    result = run_transcript_scenario("assistant_boundary")

    assert result["turn_count"] == 2
    assert result["orphan_user_status"] == "unavailable"


def test_barge_in_cancel_and_error_preserve_prior_visible_text() -> None:
    result = run_transcript_scenario("terminal_states")

    assert result["statuses"] == ["interrupted", "cancelled", "error"]


def test_duplicate_done_is_idempotent_and_late_delta_cannot_reopen_turn() -> None:
    result = run_transcript_scenario("duplicate_done")

    assert result["turn_count"] == 1
    assert result["assistant_text"] == "唯一答案"


def test_conversation_history_turns_text_and_timeline_are_bounded() -> None:
    result = run_transcript_scenario("bounded_history")

    assert result["turn_count"] <= 32
    assert result["total_text_chars"] <= 32_000


def test_transcript_renders_untrusted_text_with_text_content_only() -> None:
    assert run_transcript_scenario("text_content_safety")["inner_html_writes"] == 0


def test_disconnect_preserves_review_history_but_reset_clears_it() -> None:
    result = run_transcript_scenario("reset_disconnect")

    assert result["disconnect_preserved"] is True
    assert result["disconnect_status"] == "cancelled"
    assert result["reset_turn_count"] == 0
