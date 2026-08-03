"""Capability declarations for the isolated Qwen realtime web spike.

These profiles describe the spike-local provider boundary.  They are not
runtime adapter registrations and deliberately do not emit ADR-002 events.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Literal


OutputMode = Literal["real", "mock", "fallback", "degraded"]
HealthStatus = Literal[
    "ready",
    "not_executed",
    "degraded",
    "unavailable",
    "closed",
]


@dataclass(frozen=True, slots=True)
class CapabilityProfile:
    """JSON-safe, secret-free capability snapshot for one spike provider."""

    adapter_id: str
    adapter_type: str
    provider: str
    model_name: str
    deployment_mode: str
    endpoint_ref: str
    health_status: HealthStatus
    capability_version: str
    latency_class: str
    error_model: tuple[str, ...]
    timeout_policy: str
    retry_policy: str
    output_mode: OutputMode
    mocked: bool

    supports_streaming_input: bool
    supports_streaming_output: bool
    supports_audio_input: bool
    supports_audio_output: bool
    supports_audio_timestamps: bool
    supports_structured_json: bool
    supports_tool_calling: bool
    supports_cancellation: bool
    supports_emotion: bool
    supports_audio_caption: bool
    supports_tts: bool
    supports_tts_truncate: bool
    supports_tts_pause_resume: bool
    supports_semantic_close: bool
    supports_assistant_directedness: bool

    # Spike-specific distinctions keep local playback safety from being
    # mistaken for ADR-003 target-architecture truncate/AEC validation.
    supports_provider_response_cancel: bool
    supports_local_playback_clear: bool
    supports_playback_epoch: bool
    supports_playback_reference_aec: bool

    input_audio_format: str
    output_audio_format: str
    turn_detection: str
    tools_enabled: bool
    max_audio_seconds: int | None
    max_context_tokens: int | None
    max_output_tokens: int | None
    expected_first_token_latency_ms: int | None
    expected_first_audio_latency_ms: int | None

    def to_metadata(self) -> dict[str, Any]:
        """Return a JSON-serializable snapshot containing no credentials."""

        metadata = asdict(self)
        metadata["error_model"] = list(self.error_model)
        return metadata

    def with_health(self, health_status: HealthStatus) -> "CapabilityProfile":
        return replace(self, health_status=health_status)


def fake_capability_profile() -> CapabilityProfile:
    return CapabilityProfile(
        adapter_id="qwen_audio_realtime_web.fake.v1",
        adapter_type="duplex_model_spike",
        provider="spike_local_fake",
        model_name="synthetic-qwen-realtime-fake",
        deployment_mode="mock",
        endpoint_ref="local-memory-only",
        health_status="ready",
        capability_version="qwen-audio-realtime-web-spike.v1",
        latency_class="synthetic_configurable",
        error_model=("synthetic_error", "synthetic_disconnect"),
        timeout_policy="bridge-owned bounded async waits",
        retry_policy="none; never replay buffered microphone audio",
        output_mode="mock",
        mocked=True,
        supports_streaming_input=True,
        supports_streaming_output=True,
        supports_audio_input=True,
        supports_audio_output=True,
        supports_audio_timestamps=False,
        supports_structured_json=False,
        supports_tool_calling=False,
        supports_cancellation=True,
        supports_emotion=False,
        supports_audio_caption=False,
        supports_tts=True,
        supports_tts_truncate=False,
        supports_tts_pause_resume=False,
        supports_semantic_close=False,
        supports_assistant_directedness=False,
        supports_provider_response_cancel=True,
        supports_local_playback_clear=True,
        supports_playback_epoch=True,
        supports_playback_reference_aec=False,
        input_audio_format="pcm16le/16000/mono",
        output_audio_format="pcm16le/24000/mono",
        turn_detection="synthetic_energy_and_frame_count",
        tools_enabled=False,
        max_audio_seconds=None,
        max_context_tokens=None,
        max_output_tokens=None,
        expected_first_token_latency_ms=None,
        expected_first_audio_latency_ms=None,
    )


def qwen_capability_profile(
    *, health_status: HealthStatus = "not_executed"
) -> CapabilityProfile:
    return CapabilityProfile(
        adapter_id="qwen_audio_realtime_web.qwen_remote.v1",
        adapter_type="duplex_model_spike",
        provider="aliyun_bailian",
        model_name="qwen-audio-3.0-realtime-plus",
        deployment_mode="remote_api",
        endpoint_ref="aliyun-bailian/cn-beijing/realtime",
        health_status=health_status,
        capability_version="qwen-audio-realtime-web-spike.v1",
        latency_class="remote_realtime_unmeasured",
        error_model=(
            "credential_configuration",
            "connect_timeout",
            "provider_timeout",
            "provider_error",
            "provider_disconnect",
            "invalid_provider_event",
        ),
        timeout_policy="10s connect; bounded receive idle timeout",
        retry_policy="none mid-turn; reconnect only via a fresh browser session",
        output_mode="real",
        mocked=False,
        supports_streaming_input=True,
        supports_streaming_output=True,
        supports_audio_input=True,
        supports_audio_output=True,
        supports_audio_timestamps=False,
        supports_structured_json=False,
        supports_tool_calling=False,
        supports_cancellation=True,
        supports_emotion=False,
        supports_audio_caption=False,
        supports_tts=True,
        # response.cancel plus local buffer clearing is useful for this spike,
        # but it is not the Talker-confirmed truncate contract from ADR-003.
        supports_tts_truncate=False,
        supports_tts_pause_resume=False,
        supports_semantic_close=True,
        supports_assistant_directedness=False,
        supports_provider_response_cancel=True,
        supports_local_playback_clear=True,
        supports_playback_epoch=True,
        supports_playback_reference_aec=False,
        input_audio_format="pcm16le/16000/mono",
        output_audio_format="pcm16le/24000/mono",
        turn_detection="smart_turn",
        tools_enabled=False,
        # Official guide documents up to 300 seconds of accumulated audio
        # context (and separately up to 50 rounds); this is not a turn limit.
        max_audio_seconds=300,
        max_context_tokens=None,
        max_output_tokens=None,
        expected_first_token_latency_ms=None,
        expected_first_audio_latency_ms=None,
    )


__all__ = [
    "CapabilityProfile",
    "HealthStatus",
    "OutputMode",
    "fake_capability_profile",
    "qwen_capability_profile",
]
