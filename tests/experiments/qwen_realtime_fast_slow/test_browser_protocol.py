from __future__ import annotations

import json

import pytest

from experiments.qwen_realtime_fast_slow_web.browser_protocol import (
    BROWSER_CONTROL_TYPES,
    DEFAULT_MAX_CONTROL_FRAME_BYTES,
    DEFAULT_MAX_INPUT_FRAME_BYTES,
    OUTPUT_AUDIO_MAGIC,
    PROTOCOL_VERSION,
    SERVER_MESSAGE_TYPES,
    BrowserProtocolError,
    decode_browser_control,
    metadata_only_copy,
    pack_output_audio,
    safe_code,
    safe_error_message,
    server_message,
    unpack_output_audio,
    validate_input_audio_frame,
)
from voice_agent.events.registry import (
    FAST_FOREGROUND_EVENT_NAMES,
    MVP0_EVENT_NAMES,
    MVP1_EVENT_NAMES,
    MVP2_EVENT_NAMES,
)


def test_protocol_v2_declares_required_browser_and_server_messages() -> None:
    assert PROTOCOL_VERSION == 2
    assert {
        "session.configure",
        "microphone.start",
        "microphone.stop",
        "interrupt.request",
        "disconnect",
        "synthetic.turn",
    } <= BROWSER_CONTROL_TYPES
    assert {
        "session.ready",
        "state.changed",
        "transcript.user.delta",
        "transcript.user.final",
        "transcript.assistant.delta",
        "transcript.assistant.done",
        "route.proposed",
        "route.decided",
        "route.shadow.proposed",
        "route.shadow.validated",
        "route.shadow.compared",
        "route.shadow.degraded",
        "shadow.state",
        "gate.result",
        "slowtask.state",
        "userpatch.accepted",
        "playback.begin",
        "playback.clear",
        "playback.end",
        "degraded",
        "safe_error",
    } <= SERVER_MESSAGE_TYPES


def test_experiment_local_message_names_do_not_masquerade_as_canonical_events() -> None:
    canonical = (
        MVP0_EVENT_NAMES
        | MVP1_EVENT_NAMES
        | MVP2_EVENT_NAMES
        | FAST_FOREGROUND_EVENT_NAMES
    )

    assert SERVER_MESSAGE_TYPES.isdisjoint(canonical)
    assert BROWSER_CONTROL_TYPES.isdisjoint(canonical)
    assert all(name == name.lower() for name in SERVER_MESSAGE_TYPES)


@pytest.mark.parametrize(
    "payload",
    (
        {"type": "session.configure", "protocol_version": 2},
        {"type": "microphone.start", "protocol_version": 2},
        {"type": "microphone.stop", "protocol_version": 2},
        {"type": "interrupt.request", "protocol_version": 2},
        {"type": "disconnect", "protocol_version": 2},
        {
            "type": "synthetic.turn",
            "protocol_version": 2,
            "scenario": "fast",
        },
    ),
)
def test_decode_browser_control_accepts_protocol_v2(payload: dict[str, object]) -> None:
    assert decode_browser_control(json.dumps(payload)) == payload
    assert decode_browser_control(json.dumps(payload).encode()) == payload


@pytest.mark.parametrize(
    ("raw", "code"),
    (
        ("", "control_frame_size_invalid"),
        ("[]", "control_object_required"),
        ("{", "control_json_invalid"),
        (
            '{"type":"unknown","protocol_version":2}',
            "control_type_unsupported",
        ),
        (
            '{"type":"session.configure","protocol_version":1}',
            "protocol_version_unsupported",
        ),
        (
            '{"type":"synthetic.turn","protocol_version":2,"scenario":"real"}',
            "synthetic_scenario_unsupported",
        ),
    ),
)
def test_decode_browser_control_rejects_invalid_or_unsupported_frames(
    raw: str, code: str
) -> None:
    with pytest.raises(BrowserProtocolError) as exc_info:
        decode_browser_control(raw)
    assert exc_info.value.code == code


def test_control_and_audio_frames_are_strictly_bounded() -> None:
    oversized = b" " * (DEFAULT_MAX_CONTROL_FRAME_BYTES + 1)
    with pytest.raises(BrowserProtocolError, match="control_frame_size_invalid"):
        decode_browser_control(oversized)

    pcm = b"\x01\x00" * 1_600
    assert validate_input_audio_frame(pcm) is pcm
    for invalid in (
        b"",
        b"\x00",
        b"\x00\x00" * (DEFAULT_MAX_INPUT_FRAME_BYTES // 2 + 1),
    ):
        with pytest.raises(BrowserProtocolError, match="audio_frame_size_invalid"):
            validate_input_audio_frame(invalid)


def test_output_audio_round_trip_is_qfs2_plus_uint32_epoch() -> None:
    pcm = b"\x01\x00\x02\x00"
    packed = pack_output_audio(0x01020304, pcm)

    assert packed[:4] == OUTPUT_AUDIO_MAGIC == b"QFS2"
    assert packed[4:8] == b"\x01\x02\x03\x04"
    assert unpack_output_audio(packed) == (0x01020304, pcm)

    with pytest.raises(BrowserProtocolError, match="output_audio_magic_invalid"):
        unpack_output_audio(b"NOPE" + packed[4:])
    with pytest.raises(BrowserProtocolError, match="output_audio_frame_invalid"):
        unpack_output_audio(packed + b"\x00")


@pytest.mark.parametrize("epoch", (-1, 0x1_0000_0000, True, "1"))
def test_output_audio_rejects_invalid_epoch(epoch: object) -> None:
    with pytest.raises(BrowserProtocolError, match="playback_epoch_invalid"):
        pack_output_audio(epoch, b"\x00\x00")  # type: ignore[arg-type]


def test_server_message_reserves_type_and_version_fields() -> None:
    assert server_message("session.ready", output_mode="mock") == {
        "type": "session.ready",
        "protocol_version": 2,
        "output_mode": "mock",
    }
    with pytest.raises(BrowserProtocolError, match="server_message_type_unsupported"):
        server_message("canonical.event")
    with pytest.raises(BrowserProtocolError, match="server_message_reserved_field"):
        server_message("session.ready", type="overridden")


def test_safe_error_normalizes_untrusted_details_to_bounded_code() -> None:
    secret = "Bearer secret-token must not be reflected"
    message = safe_error_message(
        secret,
        terminal=True,
        retryable=False,
        playback_epoch=3,
    )

    assert message == {
        "type": "safe_error",
        "protocol_version": 2,
        "code": "internal_error",
        "terminal": True,
        "retryable": False,
        "playback_epoch": 3,
    }
    assert secret not in json.dumps(message)
    assert safe_code(" PROVIDER.DISCONNECTED ") == "provider.disconnected"
    assert safe_code("../../unsafe") == "internal_error"


def test_metadata_projection_is_allowlisted_and_excludes_sensitive_or_raw_data() -> None:
    source = {
        "scenario": "fast",
        "router_decision": "FAST_ONLY",
        "task_id": "task-safe",
        "plan_version": 1,
        "output_mode": "mock",
        "provider_mode": "qwen",
        "routing_mode": "shadow",
        "shadow_control_mode": "dual_session_shadow",
        "voice_session_status": "connected",
        "shadow_control_session_status": "connected",
        "safe_turn_ref": "shadow-turn-safe-ref",
        "qwen_task_focus_hint": "FOREGROUND_CHAT",
        "qwen_route_hint": "FAST_ONLY",
        "local_router_decision": "FAST_ONLY",
        "local_task_focus": "FOREGROUND_CHAT",
        "schema_status": "valid",
        "agreement": "yes",
        "control_timeout_count": 1,
        "context_delete_count": 2,
        "authorization": "Bearer secret",
        "api_key": "secret",
        "credential": "secret",
        "raw_audio": b"\x01\x00",
        "provider_payload": {"unsafe": True},
        "transcript": "unredacted real transcript",
    }

    projected = metadata_only_copy(source)
    serialized = json.dumps(projected, sort_keys=True)

    assert projected == {
        "scenario": "fast",
        "router_decision": "FAST_ONLY",
        "task_id": "task-safe",
        "plan_version": 1,
        "output_mode": "mock",
        "provider_mode": "qwen",
        "routing_mode": "shadow",
        "shadow_control_mode": "dual_session_shadow",
        "voice_session_status": "connected",
        "shadow_control_session_status": "connected",
        "safe_turn_ref": "shadow-turn-safe-ref",
        "qwen_task_focus_hint": "FOREGROUND_CHAT",
        "qwen_route_hint": "FAST_ONLY",
        "local_router_decision": "FAST_ONLY",
        "local_task_focus": "FOREGROUND_CHAT",
        "schema_status": "valid",
        "agreement": "yes",
        "control_timeout_count": 1,
        "context_delete_count": 2,
    }
    for marker in (
        "authorization",
        "api_key",
        "credential",
        "raw_audio",
        "provider_payload",
        "transcript",
        "secret",
    ):
        assert marker not in serialized.lower()


def test_metadata_projection_drops_sensitive_values_even_under_allowlisted_keys() -> None:
    projected = metadata_only_copy(
        {
            "provider_mode": "qwen",
            "routing_mode": "shadow",
            "qwen_route_hint": "FAST_ONLY",
            "safe_turn_ref": "Bearer private-credential",
            "degraded_code": "https://provider.invalid/private/body",
            "failure_reason": "/Users/private/provider-error",
            "task_id": "api_key=private-value",
        }
    )
    serialized = json.dumps(projected, sort_keys=True).lower()

    assert projected == {
        "provider_mode": "qwen",
        "routing_mode": "shadow",
        "qwen_route_hint": "FAST_ONLY",
    }
    for marker in (
        "bearer",
        "private-credential",
        "https://",
        "/users/",
        "api_key",
    ):
        assert marker not in serialized
