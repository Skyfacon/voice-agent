from __future__ import annotations

from copy import deepcopy
import json
import os
import random
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
import wave

import pytest

from conftest import REPO_ROOT, load_json_fixture
from tests.runtime.test_asr_runtime_integration import _approved_packet
from tests.runtime.test_mvp4_voice_e2e_real_evidence_paths import (
    _FakeMVP4AsrTransport,
    _FakeMVP4ThinkerAudioTransport,
)
from voice_agent.replay.runner import run_replay_fixture
from voice_agent.runtime import mvp4_voice_e2e_orchestrator as mvp4


MVP4_FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "replay" / "mvp4"
MANIFEST_INDEX = MVP4_FIXTURE_DIR / "manifest.index.json"
PROVIDER_FREE_FIXTURE = MVP4_FIXTURE_DIR / "000-provider-free-voice-e2e.fixture.json"
REPLAY_SAFETY_FIXTURE = MVP4_FIXTURE_DIR / "008-replay-safety.fixture.json"
SCENARIO_SPEC = REPO_ROOT / "docs" / "specs" / "mvp4-acceptance-scenarios.md"
MVP4_CLOSEOUT = REPO_ROOT / "docs" / "implementation" / "mvp4-closeout.md"
SMOKE_COMMAND = REPO_ROOT / "scripts" / "mvp4-voice-e2e-smoke"

REQUIRED_MVP4_SCENARIOS = [
    "MVP4-VOICE-E2E-PROVIDER-FREE-001",
    "MVP4-VOICE-E2E-THINKER-AUDIO-001",
    "MVP4-VOICE-E2E-ASR-PARALLEL-001",
    "MVP4-VOICE-E2E-ROUTER-FAST-001",
    "MVP4-VOICE-E2E-ROUTER-SPAWN-SLOWTASK-001",
    "MVP4-VOICE-E2E-ROUTER-PATCH-SLOWTASK-001",
    "MVP4-VOICE-E2E-TEXT-RESPONSE-001",
    "MVP4-VOICE-E2E-REPLAY-SAFETY-001",
    "MVP4-VOICE-E2E-RAW-ARTIFACT-BLOCK-001",
]


def test_mvp4_required_scenarios_are_declared_in_spec_manifest_and_closeout() -> None:
    manifest = load_json_fixture(MANIFEST_INDEX)
    spec_ids = re.findall(
        r"^### (MVP4-VOICE-E2E-[A-Z0-9-]+)$",
        SCENARIO_SPEC.read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    )

    assert spec_ids == REQUIRED_MVP4_SCENARIOS
    assert manifest["required_scenarios"] == REQUIRED_MVP4_SCENARIOS
    assert {entry["scenario_id"] for entry in manifest["scenario_coverage"]} == set(
        REQUIRED_MVP4_SCENARIOS
    )

    closeout = MVP4_CLOSEOUT.read_text(encoding="utf-8")
    for scenario_id in REQUIRED_MVP4_SCENARIOS:
        assert scenario_id in closeout
    for required_text in (
        "scripts/mvp4-voice-e2e-smoke --route fast",
        "scripts/mvp4-voice-e2e-smoke --route spawn",
        "scripts/mvp4-voice-e2e-smoke --route patch",
        "--local-wav",
        "none encountered",
        "no realtime mic",
        "no real TTS / voice out",
        "no real Slow LLM loop",
        "no production privacy claim",
    ):
        assert required_text in closeout


def test_provider_free_acceptance_replays_fake_asr_and_thinker_without_provider_or_secret_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _guard_provider_free_default(monkeypatch)

    result = mvp4.run_provider_free_voice_e2e()
    event_names = [event["event_name"] for event in result.events]
    router_events = result.router_decision_events
    events_by_id = _events_by_id(result.events)

    assert [event["router_decision"] for event in router_events] == [
        "FAST_ONLY",
        "SPAWN_SLOW_TASK",
        "PATCH_ACTIVE_SLOW_TASK",
    ]
    assert "ASR_TRANSCRIPT_OUTPUT_EMITTED" not in event_names
    assert "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED" not in event_names
    assert all(event["output_mode"] == "mock" for event in result.asr_frame_events)
    assert all(event["output_mode"] == "mock" for event in result.thinker_frame_events)

    for router_event in router_events:
        turn = events_by_id[str(router_event["turn_committed_event_id"])]
        asr = events_by_id[str(router_event["asr_frame_event_id"])]
        thinker = events_by_id[str(router_event["thinker_frame_event_id"])]
        assert turn["input_modality"] == "audio"
        assert asr["event_name"] == "MOCK_ASR_FRAME_EMITTED"
        assert thinker["event_name"] == "MOCK_THINKER_FRAME_EMITTED"
        assert asr["caused_by_event_id"] == turn["event_id"]
        assert thinker["caused_by_event_id"] == turn["event_id"]
        assert asr["audio_span_id"] == turn["audio_span_id"]
        assert thinker["audio_span_id"] == turn["audio_span_id"]

    fixture = result.to_replay_fixture()
    mvp4.validate_provider_free_fixture_safety(fixture)
    replay_result = run_replay_fixture(fixture)

    assert replay_result.result_status == "passed"
    assert replay_result.fixture_domain == "GITHUB_ALLOWED"
    assert replay_result.replay_mode == "deterministic"


def test_thinker_audio_and_asr_parallel_acceptance_use_fake_transport_refs_without_commitment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(os, "environ", _FailingEnviron())
    thinker_transport = _FakeMVP4ThinkerAudioTransport()
    asr_transport = _FakeMVP4AsrTransport()

    result = mvp4.run_real_evidence_voice_e2e(
        thinker_transport=thinker_transport,
        thinker_credential_value="synthetic-credential-value",
        asr_transport=asr_transport,
        asr_approval_packet=_approved_packet(max_request_count=1, retry_budget=0),
        asr_env={"MVP4_FAKE_ASR_CREDENTIAL": "synthetic-credential-value"},
        asr_credential_env_var="MVP4_FAKE_ASR_CREDENTIAL",
    )

    event_names = [event["event_name"] for event in result.events]
    turn = result.turn_committed_event
    thinker = result.thinker_frame_event
    asr = result.asr_frame_event
    router = result.router_decision_event

    assert thinker_transport.call_count == 1
    assert asr_transport.call_count == 1
    assert thinker["event_name"] == "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED"
    assert asr["event_name"] == "ASR_TRANSCRIPT_OUTPUT_EMITTED"
    assert "SEMANTIC_COMMITMENT_EMITTED" not in event_names
    assert thinker["input_modality"] == "audio"
    assert asr["input_modality"] == "audio"
    assert thinker["turn_id"] == asr["turn_id"] == turn["turn_id"]
    assert thinker["utterance_id"] == asr["utterance_id"] == turn["utterance_id"]
    assert thinker["audio_span_id"] == asr["audio_span_id"] == turn["audio_span_id"]
    assert router["thinker_frame_event_id"] == thinker["event_id"]
    assert router["asr_frame_event_id"] == asr["event_id"]

    fixture = result.to_replay_fixture()
    mvp4.validate_mvp4_fixture_safety(fixture)
    _guard_replay_against_runtime_reruns(monkeypatch)
    replay_result = run_replay_fixture(fixture)

    assert replay_result.result_status == "passed"
    assert thinker_transport.call_count == 1
    assert asr_transport.call_count == 1


def test_router_outcome_acceptance_covers_fast_spawn_patch_and_metadata_only_responses() -> None:
    fast = mvp4.run_mvp4_router_fast_only_voice_e2e()
    spawn = mvp4.run_mvp4_router_spawn_slowtask_voice_e2e()
    patch = mvp4.run_mvp4_router_patch_active_slowtask_voice_e2e()

    assert fast.router_decision_event["router_decision"] == "FAST_ONLY"
    assert "SLOWTASK_CREATED" not in _event_names(fast.events)
    assert "USER_PATCH_RECEIVED" not in _event_names(fast.events)

    assert spawn.router_decision_event["router_decision"] == "SPAWN_SLOW_TASK"
    spawn_created = _single(spawn.events, "SLOWTASK_CREATED")
    spawn_reviewed = _single(spawn.events, "EVIDENCE_REVIEWED")
    spawn_expected_refs = [
        spawn.asr_frame_event["asr_frame_ref"],
        spawn.thinker_frame_event["semantic_frame_ref"],
    ]
    assert spawn_created["source_evidence_refs"] == spawn_expected_refs
    assert spawn_reviewed["evidence_refs"] == spawn_expected_refs

    assert patch.router_decision_event["router_decision"] == "PATCH_ACTIVE_SLOW_TASK"
    user_patch = _single(patch.events, "USER_PATCH_RECEIVED")
    assert user_patch["task_id"] == patch.control_plane_summary["active_task_id"]
    assert user_patch["plan_version"] == patch.control_plane_summary["plan_version"]
    assert user_patch["observed_plan_version"] == patch.control_plane_summary["plan_version"]
    assert user_patch["task_event_seq"] == patch.control_plane_summary["task_event_seq"]
    assert patch.asr_frame_event["asr_frame_ref"] in user_patch["authoritative_evidence_refs"]
    assert patch.thinker_frame_event["semantic_frame_ref"] in user_patch[
        "non_authoritative_hypothesis_refs"
    ]
    assert "USER_PATCH_INTERPRETED" not in _event_names(patch.events)
    assert "PLAN_VERSION_ADVANCED" not in _event_names(patch.events)

    for result in (fast, spawn, patch):
        event_names = _event_names(result.events)
        assert "TTS_SYNTHESIS_OUTPUT_EMITTED" not in event_names
        assert not any(name.startswith("PLAYBACK_") for name in event_names)
        assert result.response_summary["response_text_ref"].startswith("response-text://synthetic/")
        assert result.response_summary["real_tts_used"] is False
        assert result.response_summary["voice_output"] == "none"


def test_replay_safety_acceptance_uses_committed_fixtures_and_runtime_guards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _guard_replay_against_runtime_reruns(monkeypatch)

    for fixture_path in (PROVIDER_FREE_FIXTURE, REPLAY_SAFETY_FIXTURE):
        fixture = load_json_fixture(fixture_path)
        mvp4.validate_mvp4_fixture_safety(fixture)
        result = run_replay_fixture(fixture)
        assert result.result_status == "passed"
        assert result.fixture_domain == "GITHUB_ALLOWED"
        assert result.replay_mode == "deterministic"


def test_raw_artifact_block_acceptance_rejects_unsafe_fields_and_refs() -> None:
    fixture = mvp4.run_provider_free_voice_e2e().to_replay_fixture()

    unsafe_field_fixture = deepcopy(fixture)
    unsafe_field_fixture["events"][0]["provider_body"] = {"unsafe": True}
    with pytest.raises(mvp4.MVP4ArtifactSafetyError, match="provider_body"):
        mvp4.validate_mvp4_fixture_safety(unsafe_field_fixture)

    unsafe_ref_fixture = deepcopy(fixture)
    unsafe_ref_fixture["events"][0]["audio_input_ref"] = "file:///Users/a123/private.wav"
    with pytest.raises(mvp4.MVP4ArtifactSafetyError, match="file://"):
        mvp4.validate_mvp4_fixture_safety(unsafe_ref_fixture)


@pytest.mark.parametrize("route", ["provider-free", "fast", "spawn", "patch"])
def test_mvp4_smoke_command_emits_safe_metadata_only_json_for_default_routes(route: str) -> None:
    completed = _run_smoke("--route", route)
    payload = _json_stdout(completed)

    assert payload["route"] == route
    assert payload["status"] == "passed"
    assert payload["input_source"] == "synthetic"
    assert payload["fixture_id"].startswith("synthetic-")
    assert isinstance(payload["duration_ms"], int)
    assert payload["sample_rate_hz"] == 16000
    assert payload["channel_count"] == 1
    assert payload["safe_audio_ref"].startswith("audio://synthetic/mvp4/")
    assert payload["raw_audio_included"] is False
    assert payload["raw_transcript_included"] is False
    assert payload["provider_call_used"] is False
    assert payload["real_tts_used"] is False
    assert payload["voice_output"] == "none"
    assert payload["response_summary"]["response_text_ref"].startswith(
        "response-text://synthetic/mvp4/"
    )
    assert not _contains_unsafe_output_marker(completed.stdout)


def test_mvp4_smoke_command_local_wav_requires_opt_in_and_redacts_path(tmp_path: Path) -> None:
    wav_path = tmp_path / "private-input.wav"
    _write_wav(wav_path)

    denied = _run_smoke("--route", "fast", "--local-wav", str(wav_path), check=False)
    assert denied.returncode != 0
    assert str(wav_path) not in denied.stdout
    assert str(wav_path) not in denied.stderr
    assert wav_path.name not in denied.stdout
    assert wav_path.name not in denied.stderr

    allowed = _run_smoke(
        "--route",
        "fast",
        "--local-wav",
        str(wav_path),
        "--allow-local-wav",
    )
    payload = _json_stdout(allowed)

    assert payload["route"] == "fast"
    assert payload["status"] == "passed"
    assert payload["input_source"] == "local_opt_in"
    assert payload["fixture_id"] == "redacted-local-wav"
    assert payload["safe_audio_ref"] == "audio://redacted/mvp4/redacted-local-wav"
    assert payload["raw_audio_included"] is False
    assert payload["raw_transcript_included"] is False
    assert payload["provider_call_used"] is False
    assert str(wav_path) not in allowed.stdout
    assert wav_path.name not in allowed.stdout
    assert not _contains_unsafe_output_marker(allowed.stdout)


def _run_smoke(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        [str(SMOKE_COMMAND), *args],
        cwd=REPO_ROOT,
        env={**os.environ, "VOICE_AGENT_PYTHON": sys.executable},
        text=True,
        capture_output=True,
        check=False,
    )
    if check and completed.returncode != 0:
        pytest.fail(f"smoke command failed: stdout={completed.stdout!r} stderr={completed.stderr!r}")
    return completed


def _json_stdout(completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    payload = json.loads(completed.stdout)
    assert isinstance(payload, dict)
    return payload


def _write_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x00\x00" * 1600)


def _guard_provider_free_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "environ", _FailingEnviron())
    _guard_replay_against_runtime_reruns(monkeypatch)


def _guard_replay_against_runtime_reruns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "time", lambda: pytest.fail("MVP-4 replay must not call wall clock"))
    monkeypatch.setattr(
        time,
        "monotonic",
        lambda: pytest.fail("MVP-4 replay must not call monotonic clock"),
    )
    monkeypatch.setattr(random, "random", lambda: pytest.fail("MVP-4 replay must not call random"))
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *args, **kwargs: pytest.fail("MVP-4 replay must not call network"),
    )
    _guard_optional_runtime_function(
        monkeypatch,
        "voice_agent.runtime.asr_session_hook",
        "run_asr_for_committed_audio_turn",
    )
    _guard_optional_runtime_function(
        monkeypatch,
        "voice_agent.adapters.lalm_thinker_audio_native_runtime",
        "emit_lalm_thinker_audio_native_evidence_for_turn",
    )


def _guard_optional_runtime_function(
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
    function_name: str,
) -> None:
    module = pytest.importorskip(module_name)
    if not hasattr(module, function_name):
        return

    def _fail(*_args: object, **_kwargs: object) -> None:
        pytest.fail(f"MVP-4 replay must not call {module_name}.{function_name}")

    monkeypatch.setattr(module, function_name, _fail)


class _FailingEnviron(dict[str, str]):
    def __getitem__(self, key: str) -> str:
        pytest.fail(f"MVP-4 provider-free path must not read env var {key}")

    def get(self, key: str, default: object = None) -> object:
        pytest.fail(f"MVP-4 provider-free path must not read env var {key}")

    def keys(self):  # type: ignore[override]
        pytest.fail("MVP-4 provider-free path must not enumerate env vars")

    def items(self):  # type: ignore[override]
        pytest.fail("MVP-4 provider-free path must not enumerate env vars")

    def values(self):  # type: ignore[override]
        pytest.fail("MVP-4 provider-free path must not enumerate env vars")


def _events_by_id(events: tuple[dict[str, Any], ...]) -> dict[str, dict[str, Any]]:
    return {str(event["event_id"]): event for event in events}


def _event_names(events: tuple[dict[str, Any], ...]) -> set[str]:
    return {str(event["event_name"]) for event in events}


def _single(events: tuple[dict[str, Any], ...], event_name: str) -> dict[str, Any]:
    matches = [event for event in events if event["event_name"] == event_name]
    assert len(matches) == 1
    return matches[0]


def _unsafe_output_markers() -> set[str]:
    return {
        "RIFF",
        "data:audio",
        "provider_body",
        "provider_response",
        "provider_payload",
        "provider_request",
        "prompt_dump",
        "raw_transcript:",
        "DASHSCOPE_API_KEY",
        "authorization_header",
        "Bearer ",
        "sk-test",
        "synthetic-credential-value",
    }


def _contains_unsafe_output_marker(output: str) -> bool:
    return any(marker in output for marker in _unsafe_output_markers())
