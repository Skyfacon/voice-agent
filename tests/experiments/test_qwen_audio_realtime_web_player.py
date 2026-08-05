from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKLET = (
    REPO_ROOT
    / "experiments"
    / "qwen_audio_realtime_web"
    / "static"
    / "player-worklet.js"
)
HARNESS = Path(__file__).with_name("qwen_player_worklet_harness.js")
NODE = shutil.which("node")


def run_player_scenario(scenario: str, *, sample_rate: int | None = None) -> dict:
    if NODE is None:
        pytest.skip("Node.js is required to execute the AudioWorklet regression harness")
    command = [NODE, str(HARNESS), scenario, str(WORKLET)]
    if sample_rate is not None:
        command.append(str(sample_rate))
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "passed"
    assert payload["scenario"] == scenario
    return payload


def test_physical_run_39_by_19200_byte_burst_warns_soft_and_keeps_fifo() -> None:
    result = run_player_scenario("observed_burst")

    assert result["chunks"] == 39
    assert result["buffered_peak_samples"] >= 39 * 9_600
    assert result["rendered_samples"] == 39 * 9_600
    assert result["soft_capacity_samples"] == 24_000 * 12
    assert result["capacity_samples"] == 24_000 * 60
    assert result["soft_high_events_during_burst"] == 1
    assert result["soft_high_events_after_rearm"] == 2
    assert result["soft_recovery_events"] == 1


def test_cumulative_audio_beyond_capacity_rotates_queue_without_reordering() -> None:
    result = run_player_scenario("queue_rotation")

    assert result["chunks"] == 35
    assert result["rendered_samples"] == 35 * 9_600


def test_clear_epoch_discards_buffer_and_rejects_late_old_epoch_audio() -> None:
    result = run_player_scenario("clear_epoch")

    assert result["epoch"] == 4
    assert result["late_samples"] == 9_600


@pytest.mark.parametrize("sample_rate", (24_000, 44_100, 48_000))
def test_player_renders_24khz_pcm_at_supported_device_sample_rates(
    sample_rate: int,
) -> None:
    result = run_player_scenario("sample_rate", sample_rate=sample_rate)

    assert result["output_sample_rate"] == sample_rate
    assert result["rendered_samples"] == sample_rate


def test_underflow_counts_once_while_response_active_but_not_on_normal_drain() -> None:
    result = run_player_scenario("underflow")

    assert result["active_underflows"] == 1
    assert result["inactive_underflows"] == 0


def test_hard_capacity_rejects_new_frame_without_deleting_queued_audio() -> None:
    result = run_player_scenario("bounded_capacity")

    assert result["soft_capacity_samples"] == 24_000 * 12
    assert result["capacity_samples"] == 24_000 * 60
    assert result["capacity_samples"] >= 39 * 9_600
    assert result["rejected_samples"] == result["capacity_samples"]
    assert result["rendered_samples"] == 9_600
