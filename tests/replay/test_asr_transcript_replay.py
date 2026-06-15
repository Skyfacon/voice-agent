from __future__ import annotations

import http.client
import random
import socket
import time
import urllib.request
from typing import Any

import pytest

from voice_agent.replay.runner import ReplayValidationError, run_replay_fixture


ASR_EVENT_ID = "evt_mvp3_goal_b_asr_output"
TURN_COMMITTED_EVENT_ID = "evt_mvp3_goal_b_turn_committed"


def test_asr_transcript_replay_accepts_matching_committed_turn_and_records_refs_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _block_runtime_execution(monkeypatch)

    fixture = _asr_fixture()
    result = run_replay_fixture(fixture)

    asr_event = _event_by_id(fixture["events"], ASR_EVENT_ID)
    turn_event = _event_by_id(fixture["events"], TURN_COMMITTED_EVENT_ID)

    assert result.result_status == "passed"
    assert asr_event["event_seq"] > turn_event["event_seq"]
    assert asr_event["caused_by_event_id"] == turn_event["event_id"]
    assert {
        field: asr_event[field]
        for field in ("turn_id", "utterance_id", "audio_span_id", "input_modality")
    } == {
        field: turn_event[field]
        for field in ("turn_id", "utterance_id", "audio_span_id", "input_modality")
    }
    assert result.adapter_health_state.output_event_modes == {ASR_EVENT_ID: "real"}
    assert _asr_data_plane_ref_fields(result.diagnostics) == [
        "asr_frame_ref",
        "audio_timestamps_ref",
        "text_ref",
    ]
    assert all(ref["status"] == "unavailable" for ref in result.diagnostics["data_plane_refs"])
    assert "raw_audio" not in repr(result.diagnostics)
    assert "provider_response" not in repr(result.diagnostics)


def test_asr_transcript_replay_requires_output_after_matching_turn_commit() -> None:
    fixture = _asr_fixture()
    asr_event = _event_by_id(fixture["events"], ASR_EVENT_ID)
    asr_event["event_seq"] = 8
    for event in fixture["events"]:
        if event["event_id"] != ASR_EVENT_ID and int(event["event_seq"]) >= 8:
            event["event_seq"] = int(event["event_seq"]) + 1

    with pytest.raises(
        ReplayValidationError,
        match="caused_by_event_id must reference an earlier event_seq",
    ):
        run_replay_fixture(fixture)


def test_asr_transcript_replay_requires_caused_by_matching_turn_commit() -> None:
    fixture = _asr_fixture()
    asr_event = _event_by_id(fixture["events"], ASR_EVENT_ID)
    asr_event["caused_by_event_id"] = "evt_mvp3_goal_b_turn_accepted"

    with pytest.raises(
        ReplayValidationError,
        match="ASR_TRANSCRIPT_OUTPUT_EMITTED.*TURN_INGRESS_COMMITTED",
    ):
        run_replay_fixture(fixture)


@pytest.mark.parametrize(
    ("field", "bad_value"),
    (
        ("turn_id", "turn_mvp3_goal_b_other"),
        ("utterance_id", "utt_mvp3_goal_b_other"),
        ("audio_span_id", "audio_mvp3_goal_b_other"),
        ("input_modality", "text"),
    ),
)
def test_asr_transcript_replay_requires_committed_turn_metadata_match(
    field: str,
    bad_value: str,
) -> None:
    fixture = _asr_fixture()
    asr_event = _event_by_id(fixture["events"], ASR_EVENT_ID)
    asr_event[field] = bad_value

    expected = (
        "input_modality=audio required"
        if field == "input_modality"
        else "ASR_TRANSCRIPT_OUTPUT_EMITTED"
    )
    with pytest.raises(ReplayValidationError, match=expected):
        run_replay_fixture(fixture)


@pytest.mark.parametrize(
    ("field", "unsafe_ref"),
    (
        ("asr_frame_ref", "asr-frame://synthetic/mvp3/goal-b?api_key=sk-synthetic"),
        ("text_ref", "file:///Users/a123/private/asr-transcript.txt"),
        ("audio_timestamps_ref", "https://api.openai.com/v1/audio/transcriptions"),
        ("audio_timestamps_ref", "timestamps://synthetic/mvp3/goal-b?token=secret-token"),
    ),
)
def test_asr_transcript_replay_rejects_unsafe_refs(field: str, unsafe_ref: str) -> None:
    fixture = _asr_fixture()
    asr_event = _event_by_id(fixture["events"], ASR_EVENT_ID)
    asr_event[field] = unsafe_ref

    with pytest.raises(
        ReplayValidationError,
        match=f"ASR_TRANSCRIPT_OUTPUT_EMITTED {field} must be a safe ref",
    ):
        run_replay_fixture(fixture)


def test_asr_timestamp_unavailable_requires_degraded_output_and_prior_degraded_event() -> None:
    fixture = _asr_fixture(
        asr_overrides={
            "event_id": "evt_mvp3_goal_b_asr_missing_timestamps_output",
            "adapter_request_id": "adapter_request_mvp3_goal_b_missing_timestamps",
            "timestamp_status": "unavailable",
            "output_mode": "degraded",
        },
        omitted_asr_fields=("audio_timestamps_ref",),
        degraded_events=[
            _asr_degraded_event(
                event_id="evt_mvp3_goal_b_asr_missing_timestamps_degraded",
                event_seq=10,
                adapter_request_id="adapter_request_mvp3_goal_b_missing_timestamps",
                missing_capability="supports_audio_timestamps",
            )
        ],
    )

    result = run_replay_fixture(fixture)

    assert result.adapter_health_state.output_event_modes[
        "evt_mvp3_goal_b_asr_missing_timestamps_output"
    ] == "degraded"
    assert result.adapter_health_state.adapters["mvp3_goal_b_asr"].missing_capabilities == (
        "supports_audio_timestamps",
    )


@pytest.mark.parametrize(
    "missing_degraded",
    (True, False),
)
def test_asr_timestamp_unavailable_rejects_non_degraded_or_missing_prior_degraded_event(
    missing_degraded: bool,
) -> None:
    fixture = _asr_fixture(
        asr_overrides={
            "event_id": "evt_mvp3_goal_b_asr_bad_timestamps_output",
            "adapter_request_id": "adapter_request_mvp3_goal_b_bad_timestamps",
            "timestamp_status": "unavailable",
            "output_mode": "degraded" if missing_degraded else "real",
        },
        omitted_asr_fields=("audio_timestamps_ref",),
        degraded_events=[],
    )

    expected = (
        "missing supports_audio_timestamps"
        if missing_degraded
        else "timestamp_status=unavailable requires output_mode=degraded"
    )
    with pytest.raises(ReplayValidationError, match=expected):
        run_replay_fixture(fixture)


def test_asr_final_only_streaming_requires_degraded_output_and_prior_degraded_event() -> None:
    fixture = _asr_fixture(
        asr_overrides={
            "event_id": "evt_mvp3_goal_b_asr_final_only_output",
            "adapter_request_id": "adapter_request_mvp3_goal_b_final_only",
            "streaming_status": "unsupported_final_only",
            "output_mode": "degraded",
        },
        degraded_events=[
            _asr_degraded_event(
                event_id="evt_mvp3_goal_b_asr_final_only_degraded",
                event_seq=10,
                adapter_request_id="adapter_request_mvp3_goal_b_final_only",
                missing_capability="supports_streaming_output",
            )
        ],
    )

    result = run_replay_fixture(fixture)

    assert result.adapter_health_state.output_event_modes[
        "evt_mvp3_goal_b_asr_final_only_output"
    ] == "degraded"
    assert result.adapter_health_state.adapters["mvp3_goal_b_asr"].missing_capabilities == (
        "supports_streaming_output",
    )


@pytest.mark.parametrize(
    "raw_field",
    (
        "raw_audio",
        "audio_bytes",
        "audio_payload",
        "raw_trace",
        "raw_transcript",
        "raw_text",
        "transcript_text",
        "provider_request",
        "provider_response",
        "provider_body",
        "provider_payload",
        "request_body",
        "response_body",
        "body",
        "payload",
    ),
)
def test_asr_transcript_replay_rejects_raw_payload_fields(raw_field: str) -> None:
    fixture = _asr_fixture()
    asr_event = _event_by_id(fixture["events"], ASR_EVENT_ID)
    asr_event[raw_field] = {"synthetic": "unsafe raw payload"}

    with pytest.raises(
        ReplayValidationError,
        match="ASR_TRANSCRIPT_OUTPUT_EMITTED must not contain raw audio, transcript, or provider payload",
    ):
        run_replay_fixture(fixture)


def _asr_fixture(
    *,
    asr_overrides: dict[str, Any] | None = None,
    omitted_asr_fields: tuple[str, ...] = (),
    degraded_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    degraded_events = degraded_events or []
    asr_event_seq = 10 + len(degraded_events)
    asr_event = _asr_output_event(event_seq=asr_event_seq)
    for field in omitted_asr_fields:
        asr_event.pop(field, None)
    if asr_overrides:
        asr_event.update(asr_overrides)

    return {
        "replay_manifest": {
            "manifest_schema_version": "1.0",
            "replay_id": "replay_mvp3_goal_b_asr_transcript",
            "source_trace_ref": "fixture://mvp3/goal-b-asr-transcript",
            "replay_mode": "deterministic",
            "event_schema_version_range": ["1.0"],
            "fixture_domain": "GITHUB_ALLOWED",
            "generated_from": "synthetic",
            "contains_raw_audio": False,
            "contains_raw_trace": False,
            "contains_real_user_input": False,
            "contains_secrets": False,
            "contains_unredacted_tool_result": False,
            "contains_large_raw_web_content": False,
            "allowed_re_eval_components": [],
        },
        "events": [
            *_audio_turn_events(),
            *degraded_events,
            asr_event,
        ],
    }


def _audio_turn_events() -> list[dict[str, Any]]:
    return [
        _event(
            event_name="SESSION_STARTED",
            event_id="evt_mvp3_goal_b_session_started",
            event_seq=1,
            source_module="session_runtime",
            runtime_config_ref="config://synthetic/mvp3/goal-b-asr",
            capability_snapshot_ref="capability://synthetic/mvp3/goal-b-asr",
        ),
        _event(
            event_name="ADAPTER_CAPABILITY_SNAPSHOT_RECORDED",
            event_id="evt_mvp3_goal_b_capability_snapshot",
            event_seq=2,
            source_module="adapter_registry",
            caused_by_event_id="evt_mvp3_goal_b_session_started",
            capability_snapshot_ref="capability://synthetic/mvp3/goal-b-asr",
            adapter_ids=["mvp3_goal_b_asr"],
            adapter_types=["asr"],
            deployment_modes=["remote_api"],
            output_modes=["real"],
            capability_version="mvp3.goal-b.asr.v1",
        ),
        _event(
            event_name="AUDIO_SPAN_STARTED",
            event_id="evt_mvp3_goal_b_audio_started",
            event_seq=3,
            source_module="access_layer",
            caused_by_event_id="evt_mvp3_goal_b_capability_snapshot",
            audio_span_id="audio_mvp3_goal_b_001",
            input_modality="audio",
            audio_sample_offset=0,
            audio_format_ref="audio-format://synthetic/mvp3/pcm-16khz-mono",
        ),
        _event(
            event_name="SPEECH_START_DETECTED",
            event_id="evt_mvp3_goal_b_speech_start",
            event_seq=4,
            source_module="duplex",
            caused_by_event_id="evt_mvp3_goal_b_audio_started",
            audio_span_id="audio_mvp3_goal_b_001",
            audio_sample_offset=1600,
            vad_confidence=0.94,
        ),
        _event(
            event_name="TURN_OPENED",
            event_id="evt_mvp3_goal_b_turn_opened",
            event_seq=5,
            source_module="interaction_controller",
            caused_by_event_id="evt_mvp3_goal_b_speech_start",
            turn_id="turn_mvp3_goal_b_001",
            audio_span_id="audio_mvp3_goal_b_001",
            turn_phase="COLLECTING_INPUT",
            input_modality="audio",
        ),
        _event(
            event_name="AUDIO_SPAN_ENDED",
            event_id="evt_mvp3_goal_b_audio_ended",
            event_seq=6,
            source_module="access_layer",
            caused_by_event_id="evt_mvp3_goal_b_speech_start",
            audio_span_id="audio_mvp3_goal_b_001",
            audio_sample_offset=9600,
            duration_ms=600,
            end_reason="synthetic_end_of_utterance",
        ),
        _event(
            event_name="SPEECH_END_DETECTED",
            event_id="evt_mvp3_goal_b_speech_end",
            event_seq=7,
            source_module="duplex",
            caused_by_event_id="evt_mvp3_goal_b_audio_ended",
            audio_span_id="audio_mvp3_goal_b_001",
            audio_sample_offset=9600,
            vad_confidence=0.92,
            silence_duration_ms=520,
        ),
        _event(
            event_name="TURN_INGRESS_ACCEPTED",
            event_id="evt_mvp3_goal_b_turn_accepted",
            event_seq=8,
            source_module="interaction_controller",
            caused_by_event_id="evt_mvp3_goal_b_speech_end",
            turn_id="turn_mvp3_goal_b_001",
            audio_span_id="audio_mvp3_goal_b_001",
            ingress_outcome="ACCEPTED",
        ),
        _event(
            event_name="TURN_INGRESS_COMMITTED",
            event_id=TURN_COMMITTED_EVENT_ID,
            event_seq=9,
            source_module="interaction_controller",
            caused_by_event_id="evt_mvp3_goal_b_turn_accepted",
            turn_id="turn_mvp3_goal_b_001",
            utterance_id="utt_mvp3_goal_b_001",
            input_modality="audio",
            audio_span_id="audio_mvp3_goal_b_001",
            directedness="ASSUMED_DIRECTED",
            semantic_close="ASSUMED_CLOSED",
            ingress_outcome="COMMITTED",
        ),
    ]


def _asr_output_event(*, event_seq: int) -> dict[str, Any]:
    return _event(
        event_name="ASR_TRANSCRIPT_OUTPUT_EMITTED",
        event_id=ASR_EVENT_ID,
        event_seq=event_seq,
        source_module="asr_adapter",
        caused_by_event_id=TURN_COMMITTED_EVENT_ID,
        adapter_id="mvp3_goal_b_asr",
        adapter_type="asr",
        adapter_request_id="adapter_request_mvp3_goal_b_asr_001",
        turn_id="turn_mvp3_goal_b_001",
        utterance_id="utt_mvp3_goal_b_001",
        input_modality="audio",
        audio_span_id="audio_mvp3_goal_b_001",
        asr_frame_ref="asr-frame://synthetic/mvp3/goal-b/final-output",
        text_ref="text://synthetic/mvp3/goal-b/final-output",
        audio_timestamps_ref="timestamps://synthetic/mvp3/goal-b/final-output",
        transcript_finality="final",
        timestamp_status="available",
        streaming_status="supported",
        output_mode="real",
    )


def _asr_degraded_event(
    *,
    event_id: str,
    event_seq: int,
    adapter_request_id: str,
    missing_capability: str,
) -> dict[str, Any]:
    return _event(
        event_name="ADAPTER_OUTPUT_DEGRADED",
        event_id=event_id,
        event_seq=event_seq,
        source_module="asr_adapter",
        caused_by_event_id=TURN_COMMITTED_EVENT_ID,
        adapter_id="mvp3_goal_b_asr",
        adapter_type="asr",
        adapter_request_id=adapter_request_id,
        degraded_reason=missing_capability,
        missing_capability=missing_capability,
        output_mode="degraded",
    )


def _event(
    *,
    event_name: str,
    event_id: str,
    event_seq: int,
    source_module: str,
    caused_by_event_id: str | None = None,
    **fields: Any,
) -> dict[str, Any]:
    event = {
        "event_name": event_name,
        "event_id": event_id,
        "event_seq": event_seq,
        "event_schema_version": "1.0",
        "session_id": "sess_mvp3_goal_b_asr",
        "conversation_id": "conv_mvp3_goal_b_asr",
        "source_module": source_module,
        "created_monotonic_ms": 100 + event_seq,
        "created_wall_clock_ms": 1700000100000 + event_seq,
        "trace_redaction_level": "metadata_only",
        **fields,
    }
    if caused_by_event_id is not None:
        event["caused_by_event_id"] = caused_by_event_id
    return event


def _event_by_id(events: list[dict[str, Any]], event_id: str) -> dict[str, Any]:
    return next(event for event in events if event["event_id"] == event_id)


def _asr_data_plane_ref_fields(diagnostics: dict[str, Any]) -> list[str]:
    refs = [
        ref
        for ref in diagnostics["data_plane_refs"]
        if ref["event_id"] == ASR_EVENT_ID
    ]
    return sorted({ref["field"] for ref in refs})


def _block_runtime_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "time", lambda: pytest.fail("ASR replay must not call wall clock"))
    monkeypatch.setattr(time, "monotonic", lambda: pytest.fail("ASR replay must not call monotonic clock"))
    monkeypatch.setattr(random, "random", lambda: pytest.fail("ASR replay must not call randomness"))
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *args, **kwargs: pytest.fail("ASR replay must not create sockets"),
    )
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *args, **kwargs: pytest.fail("ASR replay must not call HTTP"),
    )
    monkeypatch.setattr(
        http.client.HTTPConnection,
        "request",
        lambda *args, **kwargs: pytest.fail("ASR replay must not call HTTP clients"),
    )
    monkeypatch.setattr(
        http.client.HTTPSConnection,
        "request",
        lambda *args, **kwargs: pytest.fail("ASR replay must not call HTTPS clients"),
    )
