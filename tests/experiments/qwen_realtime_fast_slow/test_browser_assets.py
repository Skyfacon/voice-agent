from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
STATIC_ROOT = (
    REPO_ROOT / "experiments" / "qwen_realtime_fast_slow_web" / "static"
)
HARNESS = Path(__file__).with_name("worklet_harness.js")
APP_HARNESS = Path(__file__).with_name("app_harness.js")
NODE = shutil.which("node")


def run_worklet(scenario: str, filename: str) -> dict[str, object]:
    if NODE is None:
        pytest.skip("Node.js is not locally available for AudioWorklet execution")
    completed = subprocess.run(
        [NODE, str(HARNESS), scenario, str(STATIC_ROOT / filename)],
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


def run_app_scenario(scenario: str) -> dict[str, object]:
    if NODE is None:
        pytest.skip("Node.js is not locally available for browser projection checks")
    completed = subprocess.run(
        [NODE, str(APP_HARNESS), scenario, str(STATIC_ROOT / "app.js")],
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


def test_capture_worklet_emits_bounded_100ms_pcm16_mono_frames() -> None:
    result = run_worklet("capture_frame", "mic-worklet.js")

    assert result["emitted_frames"] == 1
    assert result["frame_bytes"] == 3_200


def test_player_worklet_clears_epoch_and_discards_late_audio() -> None:
    result = run_worklet("player_epoch", "player-worklet.js")

    assert result["epoch"] == 2
    assert result["late_dropped_frames"] == 1
    assert result["rendered_samples"] == 4_800


def test_player_worklet_has_bounded_capacity_without_evicting_fifo() -> None:
    result = run_worklet("player_capacity", "player-worklet.js")

    assert result["capacity_samples"] == 24_000 * 15
    assert result["dropped_frames"] == 1
    assert result["rendered_samples"] == 2_400


def test_browser_never_projects_provider_candidate_before_authorized_transcript() -> None:
    result = run_app_scenario("quarantine_visibility")

    assert result["assistant_rows_before_authorized"] == 0
    assert result["assistant_rows_after_authorized"] == 1


def test_browser_task_panel_changes_only_from_authoritative_state_messages() -> None:
    result = run_app_scenario("task_state_authority")

    assert result["task_id"] == "task-safe-1"
    assert result["plan_version"] == "2"


def test_browser_metadata_timeline_is_bounded_and_allowlisted() -> None:
    result = run_app_scenario("bounded_timeline")

    assert result["timeline_rows"] == 100


def test_shadow_panel_projects_comparison_without_touching_authoritative_ui() -> None:
    result = run_app_scenario("shadow_projection_isolation")

    assert result == {
        "status": "passed",
        "scenario": "shadow_projection_isolation",
        "provider": "qwen",
        "routing": "shadow",
        "schema": "valid",
        "agreement": "yes",
        "assistant_rows": 0,
    }


def test_shadow_degraded_projection_is_redacted_and_never_enters_qa() -> None:
    result = run_app_scenario("shadow_degraded_redaction")

    assert result == {
        "status": "passed",
        "scenario": "shadow_degraded_redaction",
        "evidence_mode": "degraded",
        "control_status": "degraded",
        "schema": "invalid",
        "assistant_rows": 0,
    }


def test_qwen_enforced_ui_requires_server_commit_and_blocks_all_binary_audio() -> None:
    result = run_app_scenario("enforced_control_zero_leak")

    assert result == {
        "status": "passed",
        "scenario": "enforced_control_zero_leak",
        "topology": "dual_session_enforced_control",
        "dispatch": "fast_text",
        "assistant_rows": 2,
        "audio_suppressed": "5",
        "binary_played": "0",
    }


def test_page_exposes_required_qa_controls_and_safe_status_panels() -> None:
    index = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")

    for label in (
        "Connect",
        "Disconnect",
        "Start microphone",
        "Stop microphone",
        "Interrupt",
        "QA 对话",
        "Qwen / Fake proposal",
        "Router &amp; Gate",
        "Active task",
        "Playback epoch",
        "Clear latency",
        "Shadow Routing",
        "NON-AUTHORITATIVE · TRANSIENT METADATA ONLY",
        "Dual-session runtime",
        "Qwen proposal",
        "Local comparison",
        "Control timeouts",
        "Context deletes",
        "Qwen Enforced Control",
        "EXPERIMENTAL · TEXT-ONLY · LOCAL AUTHORITY",
        "Provider-native audio",
        "Binary frames played",
        "Metadata timeline",
    ):
        assert label in index
    assert "SERVER-AUTHORIZED OUTPUT ONLY" in index
    assert "Fake" in index
    assert "不是 ADR-002 canonical Event Journal" in index


def test_static_code_uses_audio_worklets_and_never_requests_provider_secrets() -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(STATIC_ROOT.glob("*"))
        if path.is_file()
    )

    assert "AudioWorkletProcessor" in combined
    assert "TARGET_SAMPLE_RATE = 16_000" in combined
    assert "FRAME_SAMPLES = 1_600" in combined
    assert "SOURCE_SAMPLE_RATE = 24_000" in combined
    assert "late_audio_dropped" in combined
    assert "decodeAudioData" not in combined
    assert "DASHSCOPE_API_KEY" not in combined
    assert "QWEN_REALTIME_WORKSPACE_ID" not in combined
    assert "Authorization" not in combined
