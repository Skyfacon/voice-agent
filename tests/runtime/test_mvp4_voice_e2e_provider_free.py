from __future__ import annotations

from copy import deepcopy
import inspect
import os
from pathlib import Path
import wave

import pytest

from voice_agent.replay.runner import run_replay_fixture
from voice_agent.runtime import mvp4_voice_e2e_orchestrator as mvp4


def test_synthetic_provider_free_voice_e2e_emits_fake_refs_and_router_outcomes() -> None:
    audio_input = mvp4.load_synthetic_wav_metadata(
        fixture_id="synthetic-voice-e2e-001",
        duration_ms=1000,
        sample_rate_hz=16000,
        channel_count=1,
    )

    result = mvp4.run_provider_free_voice_e2e(audio_input=audio_input)
    events = result.events
    events_by_id = {event["event_id"]: event for event in events}

    assert [event["router_decision"] for event in result.router_decision_events] == [
        "FAST_ONLY",
        "SPAWN_SLOW_TASK",
        "PATCH_ACTIVE_SLOW_TASK",
    ]
    assert all(event["output_mode"] == "mock" for event in result.asr_frame_events)
    assert all(event["output_mode"] == "mock" for event in result.thinker_frame_events)
    assert "ASR_TRANSCRIPT_OUTPUT_EMITTED" not in {event["event_name"] for event in events}
    assert "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED" not in {
        event["event_name"] for event in events
    }

    for router_event in result.router_decision_events:
        asr_event = events_by_id[router_event["asr_frame_event_id"]]
        thinker_event = events_by_id[router_event["thinker_frame_event_id"]]
        turn_event = events_by_id[router_event["turn_committed_event_id"]]

        assert turn_event["event_name"] == "TURN_INGRESS_COMMITTED"
        assert turn_event["input_modality"] == "audio"
        assert asr_event["event_name"] == "MOCK_ASR_FRAME_EMITTED"
        assert thinker_event["event_name"] == "MOCK_THINKER_FRAME_EMITTED"
        assert asr_event["caused_by_event_id"] == turn_event["event_id"]
        assert thinker_event["caused_by_event_id"] == turn_event["event_id"]
        assert asr_event["event_seq"] < router_event["event_seq"]
        assert thinker_event["event_seq"] < router_event["event_seq"]
        assert router_event["turn_id"] == turn_event["turn_id"]
        assert router_event["utterance_id"] == turn_event["utterance_id"]
        assert "asr_frame_ref" not in router_event
        assert "semantic_frame_ref" not in router_event
        assert "raw_transcript" not in router_event
        assert "provider_body" not in router_event

    fixture = result.to_replay_fixture()
    mvp4.validate_provider_free_fixture_safety(fixture)
    replay_result = run_replay_fixture(fixture)

    assert replay_result.result_status == "passed"
    assert replay_result.fixture_domain == "GITHUB_ALLOWED"
    assert replay_result.replay_mode == "deterministic"
    assert replay_result.task_focus_state.last_focus_decision == "ACTIVE_TASK_PATCH"


def test_provider_free_voice_e2e_does_not_read_env_or_import_provider_adapters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class EnvTrap(dict[str, str]):
        def get(self, key: object, default: object | None = None) -> object:
            pytest.fail(f"provider-free MVP4 path must not read env key {key!r}")

        def __getitem__(self, key: str) -> str:
            pytest.fail(f"provider-free MVP4 path must not read env key {key!r}")

        def __contains__(self, key: object) -> bool:
            pytest.fail(f"provider-free MVP4 path must not inspect env key {key!r}")

    monkeypatch.setattr(os, "environ", EnvTrap())

    result = mvp4.run_provider_free_voice_e2e(
        audio_input=mvp4.load_synthetic_wav_metadata(
            fixture_id="synthetic-no-env-001",
            duration_ms=750,
            sample_rate_hz=16000,
            channel_count=1,
        )
    )

    module_source = inspect.getsource(mvp4)
    forbidden_import_markers = (
        "asr_runtime_adapter",
        "asr_session_hook",
        "lalm_thinker_runtime_adapter",
        "lalm_thinker_audio_native_smoke",
        "DashScope",
        "DASHSCOPE_API_KEY",
        "os.environ",
        "getenv",
    )
    for marker in forbidden_import_markers:
        assert marker not in module_source
    serialized_fixture = repr(result.to_replay_fixture())
    assert "DASHSCOPE_API_KEY" not in serialized_fixture
    assert "runtime-credential-value-for-test-only" not in serialized_fixture
    assert "authorization_header" not in serialized_fixture


def test_local_wav_loader_requires_opt_in_and_redacts_path(tmp_path: Path) -> None:
    wav_path = tmp_path / "private-input.wav"
    with wave.open(str(wav_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x00\x00" * 1600)

    with pytest.raises(ValueError, match="opt-in"):
        mvp4.load_local_wav_metadata(wav_path)

    metadata = mvp4.load_local_wav_metadata(
        wav_path,
        allow_local_wav=True,
        fixture_id="redacted-local-wav-001",
    )

    public_metadata = metadata.to_public_metadata()
    serialized = repr(public_metadata)
    assert public_metadata["input_source"] == "local_opt_in"
    assert public_metadata["sample_rate_hz"] == 16000
    assert public_metadata["channel_count"] == 1
    assert public_metadata["duration_ms"] == 100
    assert public_metadata["replay_export_allowed"] is False
    assert str(wav_path) not in serialized
    assert wav_path.name not in serialized
    assert "RIFF" not in serialized
    assert "audio_bytes" not in serialized

    with pytest.raises(ValueError, match="data URI"):
        mvp4.load_local_wav_metadata(
            "data:audio/wav;base64,UklGRg==",
            allow_local_wav=True,
            fixture_id="data-uri-rejected",
        )


@pytest.mark.parametrize(
    ("event_name", "unsafe_field", "unsafe_value", "expected"),
    (
        ("AUDIO_SPAN_STARTED", "audio_bytes", "UklGRg==", "audio_bytes"),
        ("AUDIO_SPAN_STARTED", "audio_chunk_ref", "data:audio/wav;base64,UklGRg==", "data URI"),
        ("MOCK_ASR_FRAME_EMITTED", "raw_transcript", "turn on the light", "raw_transcript"),
        ("MOCK_THINKER_FRAME_EMITTED", "provider_body", {"candidate": "unsafe"}, "provider_body"),
        ("AUDIO_SPAN_STARTED", "audio_format_ref", "file:///Users/a123/private.wav", "file://"),
        ("MOCK_ASR_FRAME_EMITTED", "asr_frame_ref", "traces/mvp4/debug.jsonl", "traces/"),
        ("MOCK_THINKER_FRAME_EMITTED", "semantic_frame_ref", "/Users/a123/private/frame.json", "absolute"),
    ),
)
def test_provider_free_fixture_safety_rejects_raw_or_local_artifacts(
    event_name: str,
    unsafe_field: str,
    unsafe_value: object,
    expected: str,
) -> None:
    fixture = mvp4.run_provider_free_voice_e2e(
        audio_input=mvp4.load_synthetic_wav_metadata(
            fixture_id="synthetic-safety-001",
            duration_ms=1000,
            sample_rate_hz=16000,
            channel_count=1,
        )
    ).to_replay_fixture()
    bad_fixture = deepcopy(fixture)
    target_event = next(event for event in bad_fixture["events"] if event["event_name"] == event_name)
    target_event[unsafe_field] = unsafe_value

    with pytest.raises(mvp4.MVP4ArtifactSafetyError, match=expected):
        mvp4.validate_provider_free_fixture_safety(bad_fixture)
