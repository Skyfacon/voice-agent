"""Experiment-local browser WebSocket protocol v2.

These message names are UI transport messages, not ADR-002 canonical events.
The module contains no provider integration and never serializes raw input audio.
"""

from __future__ import annotations

import json
import math
import re
import struct
from collections.abc import Mapping
from typing import Any


PROTOCOL_VERSION = 2
OUTPUT_AUDIO_MAGIC = b"QFS2"
OUTPUT_AUDIO_HEADER_BYTES = 8
INPUT_SAMPLE_RATE = 16_000
OUTPUT_SAMPLE_RATE = 24_000
INPUT_CHANNELS = 1
OUTPUT_CHANNELS = 1
EXPECTED_INPUT_FRAME_MS = 100
EXPECTED_INPUT_FRAME_BYTES = 3_200
DEFAULT_MAX_CONTROL_FRAME_BYTES = 16_384
DEFAULT_MAX_INPUT_FRAME_BYTES = 32_000

BROWSER_CONTROL_TYPES = frozenset(
    {
        "session.configure",
        "microphone.start",
        "microphone.stop",
        "interrupt.request",
        "disconnect",
        "synthetic.turn",
    }
)

SERVER_MESSAGE_TYPES = frozenset(
    {
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
        "control.state",
        "gate.result",
        "dispatch.result",
        "slowtask.state",
        "userpatch.accepted",
        "playback.begin",
        "playback.clear",
        "playback.end",
        "degraded",
        "safe_error",
        "flow.changed",
        "timeline.metadata",
    }
)

FAKE_SCENARIOS = frozenset(
    {
        "fast",
        "spawn",
        "patch",
        "ignore",
        "ambiguous",
        "cancel",
        "confirm",
        "reject_confirmation",
        "provider_error",
        "provider_disconnect",
        "late_audio",
    }
)

# Error/disconnect are explicit test controls, not microphone turn defaults;
# they have no transcript/route fixtures for microphone.stop.
MICROPHONE_FAKE_SCENARIOS = FAKE_SCENARIOS - {
    "provider_error",
    "provider_disconnect",
}

_SAFE_CODE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,95}$")
_UNSAFE_CODE_MARKERS = (
    "authorization",
    "bearer",
    "cookie",
    "credential",
    "api_key",
    "apikey",
    "secret",
    "session_key",
    "token",
    "http://",
    "https://",
    "file://",
    "/users/",
    "\\users\\",
    ".env",
)
_SAFE_METADATA_STRING = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}$")


class BrowserProtocolError(ValueError):
    """Raised for a bounded, client-visible protocol violation."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = safe_code(code, fallback="invalid_control_message")


def decode_browser_control(
    raw: str | bytes,
    *,
    max_bytes: int = DEFAULT_MAX_CONTROL_FRAME_BYTES,
) -> dict[str, Any]:
    """Decode and minimally validate one JSON control frame."""

    if isinstance(raw, str):
        encoded = raw.encode("utf-8", errors="strict")
    elif isinstance(raw, bytes):
        encoded = raw
    else:
        raise BrowserProtocolError("control_frame_type_invalid")
    if not encoded or len(encoded) > max_bytes:
        raise BrowserProtocolError("control_frame_size_invalid")
    try:
        payload = json.loads(encoded)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise BrowserProtocolError("control_json_invalid") from exc
    if not isinstance(payload, dict):
        raise BrowserProtocolError("control_object_required")
    message_type = payload.get("type")
    if message_type not in BROWSER_CONTROL_TYPES:
        raise BrowserProtocolError("control_type_unsupported")
    version = payload.get("protocol_version", PROTOCOL_VERSION)
    if version != PROTOCOL_VERSION:
        raise BrowserProtocolError("protocol_version_unsupported")
    if message_type == "synthetic.turn" and payload.get("scenario") not in FAKE_SCENARIOS:
        raise BrowserProtocolError("synthetic_scenario_unsupported")
    return payload


def validate_input_audio_frame(
    pcm16le: bytes,
    *,
    max_bytes: int = DEFAULT_MAX_INPUT_FRAME_BYTES,
) -> bytes:
    if not isinstance(pcm16le, bytes):
        raise BrowserProtocolError("audio_frame_type_invalid")
    if not pcm16le or len(pcm16le) > max_bytes or len(pcm16le) % 2:
        raise BrowserProtocolError("audio_frame_size_invalid")
    return pcm16le


def server_message(message_type: str, **fields: Any) -> dict[str, Any]:
    """Build a protocol-v2 JSON message without accepting arbitrary types."""

    if message_type not in SERVER_MESSAGE_TYPES:
        raise BrowserProtocolError("server_message_type_unsupported")
    if "type" in fields or "protocol_version" in fields:
        raise BrowserProtocolError("server_message_reserved_field")
    return {"type": message_type, "protocol_version": PROTOCOL_VERSION, **fields}


def pack_output_audio(playback_epoch: int, pcm16le: bytes) -> bytes:
    if not isinstance(playback_epoch, int) or isinstance(playback_epoch, bool) or playback_epoch < 0:
        raise BrowserProtocolError("playback_epoch_invalid")
    if playback_epoch > 0xFFFF_FFFF:
        raise BrowserProtocolError("playback_epoch_invalid")
    if not isinstance(pcm16le, bytes) or not pcm16le or len(pcm16le) % 2:
        raise BrowserProtocolError("output_audio_frame_invalid")
    return OUTPUT_AUDIO_MAGIC + struct.pack(">I", playback_epoch) + pcm16le


def unpack_output_audio(frame: bytes) -> tuple[int, bytes]:
    if not isinstance(frame, bytes) or len(frame) <= OUTPUT_AUDIO_HEADER_BYTES:
        raise BrowserProtocolError("output_audio_frame_invalid")
    if frame[:4] != OUTPUT_AUDIO_MAGIC:
        raise BrowserProtocolError("output_audio_magic_invalid")
    pcm16le = frame[OUTPUT_AUDIO_HEADER_BYTES:]
    if len(pcm16le) % 2:
        raise BrowserProtocolError("output_audio_frame_invalid")
    return struct.unpack(">I", frame[4:8])[0], pcm16le


def safe_error_message(
    code: object,
    *,
    terminal: bool,
    retryable: bool = False,
    playback_epoch: int = 0,
) -> dict[str, Any]:
    return server_message(
        "safe_error",
        code=safe_code(code),
        terminal=bool(terminal),
        retryable=bool(retryable),
        playback_epoch=max(0, int(playback_epoch)),
    )


def safe_code(value: object, *, fallback: str = "internal_error") -> str:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if (
            _SAFE_CODE.fullmatch(normalized)
            and not any(marker in normalized for marker in _UNSAFE_CODE_MARKERS)
        ):
            return normalized
    return fallback


def metadata_only_copy(value: Mapping[str, Any]) -> dict[str, Any]:
    """Keep a small allowlist for experiment-local timeline projection."""

    allowed = {
        "scenario",
        "route_hint",
        "task_focus_hint",
        "router_decision",
        "task_focus",
        "foreground_act",
        "risk_class",
        "confidence",
        "gate_status",
        "failure_reason",
        "task_id",
        "lifecycle",
        "plan_version",
        "playback_epoch",
        "dropped_input_frames",
        "dropped_output_frames",
        "discarded_late_audio_frames",
        "clear_latency_ms",
        "output_mode",
        "degraded",
        "provider_mode",
        "routing_mode",
        "audio_output",
        "shadow_control_mode",
        "control_topology",
        "actual_dispatch",
        "stale_status",
        "voice_session_status",
        "shadow_control_session_status",
        "safe_turn_ref",
        "qwen_task_focus_hint",
        "qwen_route_hint",
        "local_router_decision",
        "local_task_focus",
        "local_foreground_act",
        "schema_status",
        "agreement",
        "route_agreement",
        "task_focus_agreement",
        "foreground_act_agreement",
        "proposal_available",
        "asr_to_shadow_request_ms",
        "shadow_request_to_first_delta_ms",
        "shadow_request_to_done_ms",
        "function_done_to_local_router_ms",
        "control_timeout_count",
        "control_error_count",
        "control_cancel_count",
        "control_cancel_terminal_count",
        "context_delete_count",
        "context_rebuild_count",
        "shadow_drop_count",
        "context_tainted",
        "voice_cancel_count",
        "voice_cancel_terminal_count",
        "voice_cancel_terminal_timeout_count",
        "voice_unsafe_cancel_terminal_count",
        "voice_completed_after_cancel_count",
        "voice_failed_after_cancel_count",
        "voice_context_delete_count",
        "voice_context_rebuild_count",
        "voice_rebuild_pcm_drop_count",
        "voice_audio_send_failure_count",
        "voice_rebuild_coalesced_count",
        "voice_cancel_terminal_outcome",
        "voice_context_tainted",
        "assistant_text_suppression_count",
        "audio_suppression_count",
        "binary_playback_frame_count",
        "router_gate_latency_ms",
        "degraded_code",
        "recovery_status",
        "recovery_code",
        "active_task_present",
        "pending_confirmation_present",
        "isolated_event_count",
    }
    projected: dict[str, Any] = {}
    for key in allowed:
        if key not in value:
            continue
        candidate = value[key]
        if _metadata_scalar_is_safe(candidate):
            projected[key] = candidate
    return projected


def _metadata_scalar_is_safe(value: Any) -> bool:
    """Fail closed for the flat, enum/ref/counter-only timeline schema."""

    if isinstance(value, bool):
        return True
    if isinstance(value, int):
        return value >= 0
    if isinstance(value, float):
        return math.isfinite(value) and value >= 0.0
    if not isinstance(value, str) or not _SAFE_METADATA_STRING.fullmatch(value):
        return False
    lowered = value.lower()
    return not any(marker in lowered for marker in _UNSAFE_CODE_MARKERS)


__all__ = [
    "BROWSER_CONTROL_TYPES",
    "BrowserProtocolError",
    "DEFAULT_MAX_CONTROL_FRAME_BYTES",
    "DEFAULT_MAX_INPUT_FRAME_BYTES",
    "EXPECTED_INPUT_FRAME_BYTES",
    "EXPECTED_INPUT_FRAME_MS",
    "FAKE_SCENARIOS",
    "INPUT_CHANNELS",
    "INPUT_SAMPLE_RATE",
    "MICROPHONE_FAKE_SCENARIOS",
    "OUTPUT_AUDIO_HEADER_BYTES",
    "OUTPUT_AUDIO_MAGIC",
    "OUTPUT_CHANNELS",
    "OUTPUT_SAMPLE_RATE",
    "PROTOCOL_VERSION",
    "SERVER_MESSAGE_TYPES",
    "decode_browser_control",
    "metadata_only_copy",
    "pack_output_audio",
    "safe_code",
    "safe_error_message",
    "server_message",
    "unpack_output_audio",
    "validate_input_audio_frame",
]
