from __future__ import annotations

import http.client
import random
import socket
import time
import urllib.request

import pytest

from conftest import MVP3_REPLAY_FIXTURE_DIR, load_json_fixture
from voice_agent.replay.runner import run_replay_fixture


SLICE8_FIXTURE = MVP3_REPLAY_FIXTURE_DIR / "008-fallback-degraded-replay.fixture.json"


def test_mvp3_slice8_fixture_is_registered_for_fallback_degraded_replay() -> None:
    manifest = load_json_fixture(MVP3_REPLAY_FIXTURE_DIR / "manifest.index.json")

    assert {
        "fixture": SLICE8_FIXTURE.name,
        "purpose": "fallback/degraded adapter replay with recorded real/fallback/degraded outcomes",
    } in manifest["fixture_checks"]
    assert {
        "scenario_id": "MVP3-FALLBACK-DEGRADED-REPLAY-001",
        "fixture": SLICE8_FIXTURE.name,
        "assertion": (
            "Slice 8 replay distinguishes real/fallback/degraded adapter outcomes, "
            "canonical retry/failure/validation/degraded paths, and old-plan adapter output "
            "without provider rerun."
        ),
    } in manifest["scenarios"]


def test_mvp3_slice8_replays_recorded_adapter_outcomes_without_runtime_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _block_runtime_execution(monkeypatch)

    fixture = load_json_fixture(SLICE8_FIXTURE)
    result = run_replay_fixture(fixture)

    assert result.result_status == "passed"
    assert result.replay_mode == "deterministic"
    assert result.fixture_domain == "GITHUB_ALLOWED"
    assert result.diagnostics["ignored_events"] == []

    expected_output_modes = {
        "evt_mvp3_slice8_asr_real_output": "real",
        "evt_mvp3_slice8_thinker_fallback_output": "fallback",
        "evt_mvp3_slice8_slow_llm_fallback_output": "fallback",
        "evt_mvp3_slice8_tts_degraded_output": "degraded",
    }
    assert result.adapter_health_state.output_event_modes == expected_output_modes
    assert result.diagnostics["adapter_outcomes"]["output_event_modes"] == expected_output_modes

    adapters = result.adapter_health_state.adapters
    assert adapters["mvp3_slice8_asr"].output_mode == "real"
    assert adapters["mvp3_slice8_thinker"].output_mode == "fallback"
    assert adapters["mvp3_slice8_slow_llm"].output_mode == "fallback"
    assert adapters["mvp3_slice8_tts"].output_mode == "degraded"

    assert adapters["mvp3_slice8_slow_llm"].retry_count == 1
    assert adapters["mvp3_slice8_slow_llm"].failure_count == 2
    assert adapters["mvp3_slice8_slow_llm"].latest_degradation_reason == "fallback_after_validation_failure"
    assert adapters["mvp3_slice8_tts"].missing_capabilities == ("supports_tts_truncate",)

    task = result.slowtask_state.tasks["task_mvp3_slice8"]
    assert task.current_plan_version == 2
    assert task.resolved_arguments_refs == ()
    assert task.argument_provenance_refs == ()


def _block_runtime_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "time", lambda: pytest.fail("replay must not call wall clock"))
    monkeypatch.setattr(time, "monotonic", lambda: pytest.fail("replay must not call monotonic clock"))
    monkeypatch.setattr(random, "random", lambda: pytest.fail("replay must not call randomness"))
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *args, **kwargs: pytest.fail("replay must not create sockets"),
    )
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *args, **kwargs: pytest.fail("replay must not call HTTP"),
    )
    monkeypatch.setattr(
        http.client.HTTPConnection,
        "request",
        lambda *args, **kwargs: pytest.fail("replay must not call HTTP clients"),
    )
