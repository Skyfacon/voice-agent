from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, replace
from typing import get_args

import pytest

from voice_agent.adapters import qwen_realtime
from voice_agent.adapters.qwen_realtime.projections import (
    AmbientTerminalProjectionV1,
    CandidateCompletionV1,
    CandidateEligibilityFactsV1,
    CandidateObservationProjectionV1,
    CandidateTranscriptCompleteV1,
    FinalASRReadyProjectionV1,
    ProviderContextProjectionV1,
    QwenProjectionFrameV1,
    RebuildRequestedProjectionV1,
    SpeechBoundaryProjectionV1,
)
from voice_agent.adapters.qwen_realtime.protocol import (
    CLIENT_EVENT_TYPES,
    SERVER_EVENT_TYPES,
    ConversationItemDeleteClientEvent,
    ErrorServerEvent,
    InputAudioBufferAppendClientEvent,
    InputAudioCommittedServerEvent,
    InputTranscriptionFailedServerEvent,
    QwenClientEvent,
    QwenProtocolError,
    QwenServerEvent,
    QwenSessionConfiguration,
    ResponseCancelClientEvent,
    ResponseDoneServerEvent,
    SessionUpdateClientEvent,
    SpeechStoppedServerEvent,
    encode_client_event,
    parse_server_event,
    response_audio_delta,
    safe_wire_metadata,
)


SLICE3B1_CLIENT_EVENT_TYPES = frozenset(
    {
        "session.update",
        "input_audio_buffer.append",
        "response.cancel",
        "conversation.item.delete",
    }
)
SLICE3B1_SERVER_EVENT_TYPES = frozenset(
    {
        "session.created",
        "session.updated",
        "input_audio_buffer.speech_started",
        "input_audio_buffer.speech_stopped",
        "input_audio_buffer.committed",
        "conversation.item.created",
        "conversation.item.deleted",
        "conversation.item.input_audio_transcription.delta",
        "conversation.item.input_audio_transcription.completed",
        "conversation.item.input_audio_transcription.failed",
        "conversation.item.ambient_audio_transcription.delta",
        "conversation.item.ambient_audio_transcription.completed",
        "response.created",
        "response.output_item.added",
        "response.content_part.added",
        "response.audio_transcript.delta",
        "response.audio.delta",
        "response.audio_transcript.done",
        "response.audio.done",
        "response.content_part.done",
        "response.output_item.done",
        "response.done",
        "error",
    }
)

TEST_CONFIGURATION = QwenSessionConfiguration(
    turn_detection_type="smart_turn",
    modalities=("text", "audio"),
    voice="synthetic_voice",
    input_audio_transcription=(("model", "synthetic_asr"),),
    tools=(),
    fast_role_profile="fast-role://synthetic/v1",
)

VALID_SERVER_PAYLOADS: dict[str, dict[str, object]] = {
    "session.created": {
        "event_id": "evt_session_created",
        "type": "session.created",
        "session": {"id": "sess_1"},
    },
    "session.updated": {
        "event_id": "evt_session_updated",
        "type": "session.updated",
        "session": {
            "id": "sess_1",
            "turn_detection": {"type": "smart_turn"},
            "modalities": ["text", "audio"],
            "voice": "synthetic_voice",
            "input_audio_transcription": {"model": "synthetic_asr"},
            "tools": [],
            "fast_role_profile": "fast-role://synthetic/v1",
        },
    },
    "input_audio_buffer.speech_started": {
        "event_id": "evt_speech_started",
        "type": "input_audio_buffer.speech_started",
        "audio_start_ms": 12,
        "item_id": "input_item_1",
    },
    "input_audio_buffer.speech_stopped": {
        "event_id": "evt_speech_stopped",
        "type": "input_audio_buffer.speech_stopped",
        "audio_end_ms": 48,
        "item_id": "input_item_1",
    },
    "input_audio_buffer.committed": {
        "event_id": "evt_committed",
        "type": "input_audio_buffer.committed",
        "previous_item_id": "prior_item_1",
        "item_id": "input_item_1",
    },
    "conversation.item.created": {
        "event_id": "evt_item_created",
        "type": "conversation.item.created",
        "previous_item_id": "input_item_1",
        "item": {
            "id": "output_item_1",
            "type": "message",
            "status": "in_progress",
            "role": "assistant",
            "content": [],
        },
    },
    "conversation.item.deleted": {
        "event_id": "evt_item_deleted",
        "type": "conversation.item.deleted",
        "item_id": "output_item_1",
    },
    "conversation.item.input_audio_transcription.delta": {
        "event_id": "evt_input_delta",
        "type": "conversation.item.input_audio_transcription.delta",
        "item_id": "input_item_1",
        "content_index": 0,
        "text": "SENTINEL_INPUT_TEXT",
        "stash": "SENTINEL_INPUT_STASH",
    },
    "conversation.item.input_audio_transcription.completed": {
        "event_id": "evt_input_completed",
        "type": "conversation.item.input_audio_transcription.completed",
        "item_id": "input_item_1",
        "content_index": 0,
        "transcript": "SENTINEL_INPUT_TRANSCRIPT",
    },
    "conversation.item.input_audio_transcription.failed": {
        "event_id": "evt_input_failed",
        "type": "conversation.item.input_audio_transcription.failed",
        "item_id": "input_item_1",
        "content_index": 0,
        "error": {
            "type": "transcription_error",
            "code": "transcription_failed",
            "message": "SENTINEL_PROVIDER_MESSAGE",
        },
    },
    "conversation.item.ambient_audio_transcription.delta": {
        "event_id": "evt_ambient_delta",
        "type": "conversation.item.ambient_audio_transcription.delta",
        "item_id": "temporary_item_1",
        "content_index": 0,
        "text": "SENTINEL_AMBIENT_TEXT",
        "stash": "SENTINEL_AMBIENT_STASH",
    },
    "conversation.item.ambient_audio_transcription.completed": {
        "event_id": "evt_ambient_completed",
        "type": "conversation.item.ambient_audio_transcription.completed",
        "item_id": "temporary_item_1",
        "content_index": 0,
        "transcript": "SENTINEL_AMBIENT_TRANSCRIPT",
    },
    "response.created": {
        "event_id": "evt_response_created",
        "type": "response.created",
        "response": {"id": "resp_1", "status": "in_progress", "output": []},
    },
    "response.output_item.added": {
        "event_id": "evt_output_added",
        "type": "response.output_item.added",
        "response_id": "resp_1",
        "output_index": 0,
        "item": {
            "id": "output_item_1",
            "type": "message",
            "status": "in_progress",
            "role": "assistant",
            "content": [],
        },
    },
    "response.content_part.added": {
        "event_id": "evt_content_added",
        "type": "response.content_part.added",
        "response_id": "resp_1",
        "item_id": "output_item_1",
        "output_index": 0,
        "content_index": 0,
        "part": {"type": "audio", "text": ""},
    },
    "response.audio_transcript.delta": {
        "event_id": "evt_transcript_delta",
        "type": "response.audio_transcript.delta",
        "response_id": "resp_1",
        "item_id": "output_item_1",
        "output_index": 0,
        "content_index": 0,
        "delta": "SENTINEL_CANDIDATE_DELTA",
    },
    "response.audio.delta": {
        "event_id": "evt_audio_delta",
        "type": "response.audio.delta",
        "response_id": "resp_1",
        "item_id": "output_item_1",
        "output_index": 0,
        "content_index": 0,
        "pcm": bytearray(b"\x13\x37"),
    },
    "response.audio_transcript.done": {
        "event_id": "evt_transcript_done",
        "type": "response.audio_transcript.done",
        "response_id": "resp_1",
        "item_id": "output_item_1",
        "output_index": 0,
        "content_index": 0,
        "transcript": "SENTINEL_CANDIDATE_TRANSCRIPT",
    },
    "response.audio.done": {
        "event_id": "evt_audio_done",
        "type": "response.audio.done",
        "response_id": "resp_1",
        "item_id": "output_item_1",
        "output_index": 0,
        "content_index": 0,
    },
    "response.content_part.done": {
        "event_id": "evt_content_done",
        "type": "response.content_part.done",
        "response_id": "resp_1",
        "item_id": "output_item_1",
        "output_index": 0,
        "content_index": 0,
        "part": {"type": "audio", "text": "SENTINEL_PART_TEXT"},
    },
    "response.output_item.done": {
        "event_id": "evt_output_done",
        "type": "response.output_item.done",
        "response_id": "resp_1",
        "output_index": 0,
        "item": {
            "id": "output_item_1",
            "type": "message",
            "status": "completed",
            "role": "assistant",
            "content": [
                {
                    "type": "audio",
                    "transcript": "SENTINEL_OUTPUT_TRANSCRIPT",
                }
            ],
        },
    },
    "response.done": {
        "event_id": "evt_response_done",
        "type": "response.done",
        "response": {
            "id": "resp_1",
            "status": "completed",
            "output": [
                {
                    "id": "output_item_1",
                    "type": "message",
                    "status": "completed",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "audio",
                            "transcript": "SENTINEL_RESPONSE_TRANSCRIPT",
                        }
                    ],
                }
            ],
        },
    },
    "error": {
        "event_id": "evt_error",
        "type": "error",
        "error": {
            "type": "invalid_request_error",
            "code": "invalid_value",
            "message": "SENTINEL_ERROR_BODY",
            "param": "response.create",
        },
    },
}


def test_exact_slice3b1_event_type_allowlists_are_closed() -> None:
    assert CLIENT_EVENT_TYPES == SLICE3B1_CLIENT_EVENT_TYPES
    assert SERVER_EVENT_TYPES == SLICE3B1_SERVER_EVENT_TYPES
    assert {
        member.type for member in get_args(QwenClientEvent)
    } == SLICE3B1_CLIENT_EVENT_TYPES
    assert {
        member.type for member in get_args(QwenServerEvent)
    } == SLICE3B1_SERVER_EVENT_TYPES
    assert {
        "input_audio_buffer.commit",
        "response.create",
        "conversation.item.create",
    }.isdisjoint(CLIENT_EVENT_TYPES)


@pytest.mark.parametrize("event_type", sorted(SLICE3B1_SERVER_EVENT_TYPES))
def test_every_allowlisted_server_event_parses_to_typed_event(
    event_type: str,
) -> None:
    event = parse_server_event(VALID_SERVER_PAYLOADS[event_type])
    assert event.type == event_type
    assert type(event) in get_args(QwenServerEvent)


@pytest.mark.parametrize("event_type", sorted(SLICE3B1_SERVER_EVENT_TYPES))
@pytest.mark.parametrize("bad_event_id", [None, "", "   "])
def test_every_server_event_requires_nonempty_event_id(
    event_type: str,
    bad_event_id: object,
) -> None:
    payload = dict(VALID_SERVER_PAYLOADS[event_type])
    if bad_event_id is None:
        payload.pop("event_id")
    else:
        payload["event_id"] = bad_event_id
    with pytest.raises(QwenProtocolError, match="invalid_event_id"):
        parse_server_event(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"event_id": "evt_unknown", "type": "route.proposed"},
        {"event_id": "evt_unknown", "type": "response.create"},
        {"event_id": "evt_unknown", "type": "input_audio_buffer.commit"},
        {"event_id": "evt_unknown", "type": "conversation.item.create"},
    ],
)
def test_unknown_or_out_of_conformance_types_fail_closed(
    payload: dict[str, object],
) -> None:
    with pytest.raises(QwenProtocolError, match="unsupported_server_event"):
        parse_server_event(payload)


@pytest.mark.parametrize(
    ("event_type", "mutate"),
    [
        (
            "response.created",
            lambda payload: payload.update(response={"id": "", "status": "in_progress"}),
        ),
        (
            "response.output_item.added",
            lambda payload: payload.update(response_id=""),
        ),
        (
            "response.output_item.added",
            lambda payload: payload.update(output_index=-1),
        ),
        (
            "response.content_part.added",
            lambda payload: payload.update(item_id=""),
        ),
        (
            "response.audio.delta",
            lambda payload: payload.update(content_index=True),
        ),
        (
            "response.done",
            lambda payload: payload.update(response={"status": "completed", "output": []}),
        ),
    ],
)
def test_malformed_response_item_or_index_identity_fails_closed(
    event_type: str,
    mutate: object,
) -> None:
    payload = dict(VALID_SERVER_PAYLOADS[event_type])
    mutate(payload)  # type: ignore[operator]
    with pytest.raises(QwenProtocolError, match="invalid_"):
        parse_server_event(payload)


def test_public_server_event_constructors_reject_none_required_identities() -> None:
    required_identity_families = (
        ("session.created", "session_id"),
        ("input_audio_buffer.speech_started", "item_id"),
        (
            "conversation.item.input_audio_transcription.completed",
            "item_id",
        ),
        ("response.created", "response_id"),
        ("response.output_item.added", "response_id"),
        ("response.output_item.added", "item_id"),
        ("response.content_part.added", "response_id"),
        ("response.content_part.added", "item_id"),
        ("response.audio.delta", "response_id"),
        ("response.audio.delta", "item_id"),
        ("response.done", "response_id"),
    )
    for event_type, field_name in required_identity_families:
        event = parse_server_event(VALID_SERVER_PAYLOADS[event_type])
        with pytest.raises(QwenProtocolError) as caught:
            replace(event, **{field_name: None})
        assert str(caught.value) == f"invalid_{field_name}"
        assert "None" not in str(caught.value)


def test_public_server_event_constructors_preserve_truly_optional_fields() -> None:
    committed = InputAudioCommittedServerEvent(
        event_id="evt_committed",
        item_id="input_item_1",
    )
    stopped = SpeechStoppedServerEvent(
        event_id="evt_stopped",
        item_id="input_item_1",
        audio_end_ms=40,
    )
    done = ResponseDoneServerEvent(
        event_id="evt_done",
        response_id="resp_1",
        terminal_status="completed",
    )
    error = ErrorServerEvent(
        event_id="evt_error",
        error_type="invalid_request_error",
        error_code="invalid_value",
    )
    assert committed.previous_item_id is None
    assert stopped.stop_reason is None
    assert done.response_terminal_reason is None
    assert error.error_param is None


@pytest.mark.parametrize("reason", ["", "client_cancelled", "unknown"])
def test_speech_stopped_rejects_invalid_reason(reason: str) -> None:
    payload = dict(
        VALID_SERVER_PAYLOADS["input_audio_buffer.speech_stopped"]
    )
    payload["reason"] = reason
    with pytest.raises(QwenProtocolError, match="invalid_stop_reason"):
        parse_server_event(payload)


def test_speech_stopped_accepts_absent_or_turn_invalid_reason() -> None:
    valid = dict(VALID_SERVER_PAYLOADS["input_audio_buffer.speech_stopped"])
    assert parse_server_event(valid).stop_reason is None
    invalid_turn = dict(valid)
    invalid_turn["reason"] = "turn_invalid"
    assert parse_server_event(invalid_turn).stop_reason == "turn_invalid"


def test_session_configuration_round_trips_as_exact_normalized_echo() -> None:
    encoded = encode_client_event(
        SessionUpdateClientEvent(configuration=TEST_CONFIGURATION)
    )
    assert encoded == {
        "type": "session.update",
        "session": {
            "turn_detection": {"type": "smart_turn"},
            "modalities": ["text", "audio"],
            "voice": "synthetic_voice",
            "input_audio_transcription": {"model": "synthetic_asr"},
            "tools": [],
            "fast_role_profile": "fast-role://synthetic/v1",
        },
    }
    updated = parse_server_event(VALID_SERVER_PAYLOADS["session.updated"])
    assert updated.configuration == TEST_CONFIGURATION


def test_tagged_json_round_trip_preserves_nested_empty_objects_and_arrays() -> None:
    session = {
        "turn_detection": {"type": "smart_turn"},
        "modalities": ["text", "audio"],
        "voice": "synthetic_voice",
        "input_audio_transcription": {
            "model": "synthetic_asr",
            "options": {
                "empty_object": {},
                "empty_array": [],
                "mixed": [
                    {"nested_empty_object": {}},
                    [],
                ],
            },
        },
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "synthetic_tool",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                        "examples": [{}, []],
                    },
                },
            }
        ],
        "fast_role_profile": "fast-role://synthetic/v1",
    }
    configuration = QwenSessionConfiguration.from_session_mapping(session)
    assert configuration.to_session_mapping() == session


def test_tagged_json_rejects_non_string_mapping_keys_with_bounded_error() -> None:
    session = {
        "turn_detection": {"type": "smart_turn"},
        "modalities": ["text", "audio"],
        "voice": "synthetic_voice",
        "input_audio_transcription": {
            "mixed_keys": {
                1: "SENTINEL_NON_STRING_KEY",
                "valid": "value",
            }
        },
        "tools": [],
        "fast_role_profile": "fast-role://synthetic/v1",
    }
    with pytest.raises(QwenProtocolError) as caught:
        QwenSessionConfiguration.from_session_mapping(session)
    assert str(caught.value) == "invalid_input_audio_transcription"
    assert "SENTINEL_NON_STRING_KEY" not in str(caught.value)


def test_tagged_json_rejects_non_mapping_tool_entry_with_bounded_error() -> None:
    session = {
        "turn_detection": {"type": "smart_turn"},
        "modalities": ["text", "audio"],
        "voice": "synthetic_voice",
        "input_audio_transcription": {"model": "synthetic_asr"},
        "tools": ["SENTINEL_NOT_A_TOOL_MAPPING"],
        "fast_role_profile": "fast-role://synthetic/v1",
    }
    with pytest.raises(QwenProtocolError) as caught:
        QwenSessionConfiguration.from_session_mapping(session)
    assert str(caught.value) == "invalid_tools"
    assert "SENTINEL_NOT_A_TOOL_MAPPING" not in str(caught.value)


def test_all_four_client_events_encode_to_provider_shape() -> None:
    assert encode_client_event(
        InputAudioBufferAppendClientEvent(pcm16le=bytearray(b"\x00\x01"))
    ) == {
        "type": "input_audio_buffer.append",
        "audio": "AAE=",
    }
    assert encode_client_event(ResponseCancelClientEvent()) == {
        "type": "response.cancel"
    }
    assert encode_client_event(
        ConversationItemDeleteClientEvent(item_id="item_1")
    ) == {
        "type": "conversation.item.delete",
        "item_id": "item_1",
    }


def test_payloads_are_absent_from_repr_and_safe_metadata() -> None:
    event = response_audio_delta(
        event_id="provider_evt_1",
        response_id="resp_1",
        item_id="item_1",
        output_index=0,
        content_index=0,
        pcm=bytearray(b"\x13\x37"),
    )
    metadata = safe_wire_metadata(event)
    assert "1337" not in repr(event)
    assert "pcm" not in repr(event).lower()
    assert "audio" not in metadata
    assert metadata == {
        "type": "response.audio.delta",
        "provider_event_id_ref": "provider_evt_1",
        "qwen_response_id": "resp_1",
        "qwen_item_ref": "item_1",
        "qwen_output_index": 0,
        "qwen_content_index": 0,
        "byte_count": 2,
    }

    transcript = parse_server_event(
        VALID_SERVER_PAYLOADS["response.audio_transcript.done"]
    )
    assert "SENTINEL_CANDIDATE_TRANSCRIPT" not in repr(transcript)
    assert "SENTINEL_CANDIDATE_TRANSCRIPT" not in repr(
        safe_wire_metadata(transcript)
    )


def test_provider_error_payloads_are_absent_from_repr_and_safe_metadata() -> None:
    provider_error = ErrorServerEvent(
        event_id="evt_error",
        error_type="invalid_request_error",
        error_code="SENTINEL_PROVIDER_ERROR_CODE",
        error_param="SENTINEL_PROVIDER_ERROR_PARAM",
        error_message="SENTINEL_PROVIDER_ERROR_MESSAGE",
    )
    transcription_error = InputTranscriptionFailedServerEvent(
        event_id="evt_transcription_error",
        item_id="input_item_1",
        content_index=0,
        error_type="SENTINEL_TRANSCRIPTION_ERROR_TYPE",
        error_code="SENTINEL_TRANSCRIPTION_ERROR_CODE",
        error_message="SENTINEL_TRANSCRIPTION_ERROR_MESSAGE",
    )
    provider_repr = repr(provider_error)
    transcription_repr = repr(transcription_error)
    metadata = safe_wire_metadata(provider_error)

    for sentinel in (
        "invalid_request_error",
        "SENTINEL_PROVIDER_ERROR_CODE",
        "SENTINEL_PROVIDER_ERROR_PARAM",
        "SENTINEL_PROVIDER_ERROR_MESSAGE",
    ):
        assert sentinel not in provider_repr
        assert sentinel not in repr(metadata)
    for sentinel in (
        "SENTINEL_TRANSCRIPTION_ERROR_TYPE",
        "SENTINEL_TRANSCRIPTION_ERROR_CODE",
        "SENTINEL_TRANSCRIPTION_ERROR_MESSAGE",
    ):
        assert sentinel not in transcription_repr
    assert metadata == {
        "type": "error",
        "provider_event_id_ref": "evt_error",
        "terminal_status": "non_terminal",
    }


def test_session_nested_payloads_are_absent_from_repr() -> None:
    configuration = QwenSessionConfiguration(
        turn_detection_type="smart_turn",
        modalities=("text", "audio"),
        voice="synthetic_voice",
        input_audio_transcription=(
            ("model", "SENTINEL_TRANSCRIPTION_CONFIGURATION"),
        ),
        tools=(
            (
                ("description", "SENTINEL_TOOL_DESCRIPTION"),
                ("type", "function"),
            ),
        ),
        fast_role_profile="fast-role://synthetic/v1",
    )
    event = SessionUpdateClientEvent(configuration=configuration)
    assert "SENTINEL_TRANSCRIPTION_CONFIGURATION" not in repr(configuration)
    assert "SENTINEL_TOOL_DESCRIPTION" not in repr(configuration)
    assert "SENTINEL_TOOL_DESCRIPTION" not in repr(event)


def test_package_exports_every_public_union_member() -> None:
    for member in (*get_args(QwenClientEvent), *get_args(QwenServerEvent)):
        assert getattr(qwen_realtime, member.__name__) is member


def test_wire_union_fields_exclude_local_control_plane_authority() -> None:
    forbidden = {
        "provider_session_generation",
        "turn_id",
        "utterance_id",
        "playback_epoch",
        "context_snapshot_id",
        "route",
        "gate",
    }
    for member in (*get_args(QwenClientEvent), *get_args(QwenServerEvent)):
        assert forbidden.isdisjoint(field.name for field in fields(member))


def _valid_projection_instances() -> tuple[object, ...]:
    eligibility = CandidateEligibilityFactsV1(
        provider_session_generation=1,
        qwen_response_id="resp_1",
        qwen_output_item_id="item_1",
        qwen_output_index=0,
        qwen_content_index=0,
        candidate_id="cand_1",
        turn_id="turn_1",
        utterance_id="utterance_1",
        context_snapshot_id="context_1",
        bound_playback_epoch=0,
        candidate_transcript_digest="sha256:transcript",
        candidate_unicode_scalar_count=1,
        candidate_pcm_manifest_digest="sha256:pcm",
        candidate_audio_format_ref="audio-format://pcm16le/24k/mono",
        candidate_audio_duration_ms=1,
        provider_terminal_status="completed",
    )
    return (
        SpeechBoundaryProjectionV1(
            provider_session_generation=1,
            boundary="STARTED",
            qwen_input_item_ref="input_item_1",
            observed_audio_sample_offset=0,
        ),
        FinalASRReadyProjectionV1(
            provider_session_generation=1,
            qwen_input_item_ref="input_item_1",
            qwen_input_content_index=0,
            turn_id="turn_1",
            utterance_id="utterance_1",
            transcript_ref="transcript://synthetic/1",
            transcript_digest="sha256:asr",
            transcript_unicode_scalar_count=1,
        ),
        AmbientTerminalProjectionV1(
            provider_session_generation=1,
            temporary_item_ref="temporary_item_1",
            terminal_status="completed",
        ),
        ProviderContextProjectionV1(
            provider_session_generation=1,
            playback_epoch=0,
            interaction_state_version=0,
            from_state="CONNECTING",
            to_state="CLEAN",
            reason="session_updated",
            dropped_audio_frame_count=0,
        ),
        RebuildRequestedProjectionV1(
            provider_session_generation=1,
            reason="protocol_error",
            source_event_id_refs=("evt_1",),
        ),
        CandidateObservationProjectionV1(
            provider_session_generation=1,
            candidate_id="cand_1",
            qwen_response_id="resp_1",
            observation="OPENED",
        ),
        eligibility,
        CandidateTranscriptCompleteV1(
            provider_session_generation=1,
            qwen_response_id="resp_1",
            candidate_id="cand_1",
            turn_id="turn_1",
            utterance_id="utterance_1",
            context_snapshot_id="context_1",
            candidate_ref="candidate://synthetic/1",
            candidate_transcript_digest="sha256:transcript",
            candidate_unicode_scalar_count=1,
        ),
        CandidateCompletionV1(
            candidate_ref="candidate://synthetic/1",
            eligibility_facts=eligibility,
        ),
    )


def test_projection_runtime_validation_accepts_every_minimal_valid_type() -> None:
    instances = _valid_projection_instances()
    assert {type(instance) for instance in instances} == {
        SpeechBoundaryProjectionV1,
        FinalASRReadyProjectionV1,
        AmbientTerminalProjectionV1,
        ProviderContextProjectionV1,
        RebuildRequestedProjectionV1,
        CandidateObservationProjectionV1,
        CandidateEligibilityFactsV1,
        CandidateTranscriptCompleteV1,
        CandidateCompletionV1,
    }


@pytest.mark.parametrize(
    ("instance_index", "field_name", "bad_value", "error_code"),
    [
        (0, "provider_session_generation", True, "invalid_provider_session_generation"),
        (0, "provider_session_generation", 0, "invalid_provider_session_generation"),
        (0, "qwen_input_item_ref", None, "invalid_qwen_input_item_ref"),
        (0, "observed_audio_sample_offset", True, "invalid_observed_audio_sample_offset"),
        (0, "observed_audio_sample_offset", -1, "invalid_observed_audio_sample_offset"),
        (0, "boundary", "UNKNOWN", "invalid_boundary"),
        (0, "stop_reason", "not_allowed_on_started", "invalid_stop_reason"),
        (1, "qwen_input_content_index", True, "invalid_qwen_input_content_index"),
        (1, "turn_id", None, "invalid_turn_id"),
        (1, "transcript_digest", None, "invalid_transcript_digest"),
        (
            1,
            "transcript_unicode_scalar_count",
            0,
            "invalid_transcript_unicode_scalar_count",
        ),
        (2, "temporary_item_ref", None, "invalid_temporary_item_ref"),
        (2, "terminal_status", "unknown", "invalid_terminal_status"),
        (3, "from_state", None, "invalid_from_state"),
        (3, "dropped_audio_frame_count", True, "invalid_dropped_audio_frame_count"),
        (4, "reason", None, "invalid_reason"),
        (4, "source_event_id_refs", (), "invalid_source_event_id_refs"),
        (5, "candidate_id", None, "invalid_candidate_id"),
        (5, "observation", "UNKNOWN", "invalid_observation"),
        (6, "qwen_output_index", -1, "invalid_qwen_output_index"),
        (6, "candidate_pcm_manifest_digest", None, "invalid_candidate_pcm_manifest_digest"),
        (6, "candidate_audio_duration_ms", 0, "invalid_candidate_audio_duration_ms"),
        (6, "provider_terminal_status", "failed", "invalid_provider_terminal_status"),
        (7, "candidate_ref", None, "invalid_candidate_ref"),
        (
            7,
            "candidate_unicode_scalar_count",
            0,
            "invalid_candidate_unicode_scalar_count",
        ),
        (8, "candidate_ref", None, "invalid_candidate_ref"),
        (8, "eligibility_facts", object(), "invalid_eligibility_facts"),
    ],
)
def test_projection_runtime_validation_rejects_malformed_direct_construction(
    instance_index: int,
    field_name: str,
    bad_value: object,
    error_code: str,
) -> None:
    instance = _valid_projection_instances()[instance_index]
    expected_error = TypeError if error_code == "invalid_eligibility_facts" else ValueError
    with pytest.raises(expected_error) as caught:
        replace(instance, **{field_name: bad_value})
    assert str(caught.value) == error_code
    assert repr(bad_value) not in str(caught.value)


def test_projection_union_is_exact_frozen_and_payload_free() -> None:
    expected = {
        SpeechBoundaryProjectionV1,
        FinalASRReadyProjectionV1,
        AmbientTerminalProjectionV1,
        ProviderContextProjectionV1,
        RebuildRequestedProjectionV1,
        CandidateObservationProjectionV1,
        CandidateTranscriptCompleteV1,
        CandidateCompletionV1,
    }
    assert set(get_args(QwenProjectionFrameV1)) == expected

    facts = CandidateEligibilityFactsV1(
        provider_session_generation=1,
        qwen_response_id="resp_1",
        qwen_output_item_id="item_1",
        qwen_output_index=0,
        qwen_content_index=0,
        candidate_id="cand_1",
        turn_id="turn_1",
        utterance_id="utterance_1",
        context_snapshot_id="context_1",
        bound_playback_epoch=3,
        candidate_transcript_digest="sha256:transcript",
        candidate_unicode_scalar_count=12,
        candidate_pcm_manifest_digest="sha256:pcm",
        candidate_audio_format_ref="audio-format://pcm16le/24k/mono",
        candidate_audio_duration_ms=160,
        provider_terminal_status="completed",
    )
    completion = CandidateCompletionV1(
        candidate_ref="candidate://sensitive/1",
        eligibility_facts=facts,
    )
    assert "candidate://sensitive/1" not in repr(completion)
    assert not hasattr(completion, "__dict__")
    with pytest.raises(FrozenInstanceError):
        completion.candidate_ref = "candidate://mutated"  # type: ignore[misc]

    for member in (*expected, CandidateEligibilityFactsV1):
        assert {"transcript", "pcm", "resolver", "handle"}.isdisjoint(
            field.name for field in fields(member)
        )
