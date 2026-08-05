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
HARNESS = Path(__file__).with_name("qwen_app_capacity_harness.js")
NODE = shutil.which("node")


def run_capacity_scenario(scenario: str) -> dict:
    if NODE is None:
        pytest.skip("Node.js is required to execute the capacity UI harness")
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


def test_soft_backlog_is_visible_without_cancel_clear_or_terminal_error() -> None:
    result = run_capacity_scenario("soft_backlog")

    assert result["assistant_status"] == "streaming"
    assert result["cancel_count"] == 0
    assert result["clear_delta"] == 0
    assert result["playback_buffer"] == "12500 / 12500 / 12000 / 60000 ms"
    assert result["quality"] == "degraded"


def test_hard_capacity_still_fails_coherently_with_clear_and_cancel() -> None:
    result = run_capacity_scenario("hard_capacity")

    assert result["assistant_status"] == "error"
    assert result["cancel_count"] == 1
    assert result["epoch_after"] == result["epoch_before"] + 1
    assert result["output_drop"] == "9600 samples / 400 ms"


def test_response_start_resumes_an_existing_suspended_player_context() -> None:
    result = run_capacity_scenario("suspended_resume")

    assert result["resume_calls"] == 1
    assert result["context_state"] == "running"
