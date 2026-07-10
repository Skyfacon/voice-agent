from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from voice_agent.adapters.capabilities import (
    AdapterCapability,
    BOOLEAN_CAPABILITY_FIELDS,
    CapabilityValidationError,
    validate_capability_matrix,
)


class AsrProfileValidationError(ValueError):
    pass


ASR_PROFILE_OUTPUT_MODES = frozenset({"real", "fallback", "degraded"})
ASR_FORBIDDEN_OWNERSHIP_CAPABILITIES = frozenset(
    {
        "supports_audio_output",
        "supports_tool_calling",
        "supports_emotion",
        "supports_audio_caption",
        "supports_tts",
        "supports_tts_truncate",
        "supports_tts_pause_resume",
        "supports_semantic_close",
        "supports_assistant_directedness",
        "supports_fast_interaction_output",
        "supports_route_hint",
        "supports_route_prelude",
        "supports_foreground_act",
        "supports_reply_candidate",
        "supports_reply_delta_streaming",
        "supports_final_fast_evidence",
        "supports_risk_tags",
        "supports_confidence",
        "supports_asr_text_fallback",
    }
)


@dataclass(frozen=True)
class AsrProfileDefaults:
    health_status: str = "configured"
    capability_version: str = "mvp3.asr.profile.v1"
    latency_class: str = "provider_free_contract"
    error_model: str = "error-model://synthetic/mvp3/asr/provider-free"
    timeout_policy: str = "timeout-policy://synthetic/mvp3/asr/provider-free"
    retry_policy: str = "retry-policy://synthetic/mvp3/asr/provider-free"
    max_audio_seconds: int | None = 30
    max_context_tokens: int | None = None
    max_output_tokens: int | None = 256
    expected_first_token_latency_ms: int | None = None
    expected_first_audio_latency_ms: int | None = None


def build_asr_capability_profile(
    *,
    adapter_id: str,
    provider: str,
    model_name: str,
    endpoint_ref: str,
    config_ref: str,
    output_mode: str,
    deployment_mode: str = "remote_api",
    supports_streaming_input: bool = False,
    supports_streaming_output: bool = False,
    supports_audio_timestamps: bool = False,
    supports_cancellation: bool = False,
    health_status: str | None = None,
    capability_version: str | None = None,
    latency_class: str | None = None,
    error_model: str | None = None,
    timeout_policy: str | None = None,
    retry_policy: str | None = None,
    max_audio_seconds: int | None = 30,
    max_context_tokens: int | None = None,
    max_output_tokens: int | None = 256,
    expected_first_token_latency_ms: int | None = None,
    expected_first_audio_latency_ms: int | None = None,
    mocked: bool = False,
    mock_profile_ref: str = "",
    target_architecture_validation: bool = True,
    unsupported_capabilities: tuple[str, ...] | None = None,
) -> AdapterCapability:
    defaults = AsrProfileDefaults()
    if output_mode not in ASR_PROFILE_OUTPUT_MODES:
        raise AsrProfileValidationError(
            f"ASR profile output_mode must be one of {sorted(ASR_PROFILE_OUTPUT_MODES)}"
        )
    if output_mode == "real":
        _reject_mock_only_real_readiness(
            provider=provider,
            deployment_mode=deployment_mode,
            endpoint_ref=endpoint_ref,
            mocked=mocked,
            mock_profile_ref=mock_profile_ref,
        )

    fields: dict[str, Any] = {
        "adapter_id": adapter_id,
        "adapter_type": "asr",
        "provider": provider,
        "model_name": model_name,
        "deployment_mode": deployment_mode,
        "endpoint": endpoint_ref,
        "health_status": health_status or defaults.health_status,
        "capability_version": capability_version or defaults.capability_version,
        "latency_class": latency_class or defaults.latency_class,
        "error_model": error_model or defaults.error_model,
        "timeout_policy": timeout_policy or defaults.timeout_policy,
        "retry_policy": retry_policy or defaults.retry_policy,
        "output_mode": output_mode,
        "config_ref": config_ref,
        "role_contract": "",
        "prompt_profile": "",
        "supports_streaming_input": supports_streaming_input,
        "supports_streaming_output": supports_streaming_output,
        "supports_audio_input": True,
        "supports_audio_output": False,
        "supports_audio_timestamps": supports_audio_timestamps,
        "supports_structured_json": True,
        "supports_tool_calling": False,
        "supports_cancellation": supports_cancellation,
        "supports_emotion": False,
        "supports_audio_caption": False,
        "supports_tts": False,
        "supports_tts_truncate": False,
        "supports_tts_pause_resume": False,
        "supports_semantic_close": False,
        "supports_assistant_directedness": False,
        "supports_fast_interaction_output": False,
        "supports_route_hint": False,
        "supports_route_prelude": False,
        "supports_foreground_act": False,
        "supports_reply_candidate": False,
        "supports_reply_delta_streaming": False,
        "supports_final_fast_evidence": False,
        "supports_schema_validation": True,
        "supports_risk_tags": False,
        "supports_confidence": False,
        "supports_asr_text_fallback": False,
        "supports_provider_stream_timing": False,
        "supports_ttft_observation": False,
        "max_audio_seconds": max_audio_seconds,
        "max_context_tokens": max_context_tokens,
        "max_output_tokens": max_output_tokens,
        "expected_first_token_latency_ms": expected_first_token_latency_ms,
        "expected_first_audio_latency_ms": expected_first_audio_latency_ms,
        "max_reply_candidate_tokens": None,
        "expected_first_candidate_latency_ms": None,
        "expected_final_gate_ready_latency_ms": None,
        "mocked": mocked,
        "mock_profile_ref": mock_profile_ref,
        "target_architecture_validation": target_architecture_validation,
    }

    for capability in ASR_FORBIDDEN_OWNERSHIP_CAPABILITIES:
        if fields[capability] is not False:
            raise AsrProfileValidationError(f"ASR profile must not claim {capability}")

    fields["unsupported_capabilities"] = (
        unsupported_capabilities
        if unsupported_capabilities is not None
        else tuple(field for field in BOOLEAN_CAPABILITY_FIELDS if fields[field] is False)
    )

    try:
        validated = validate_capability_matrix(fields)
    except CapabilityValidationError as exc:
        raise AsrProfileValidationError(str(exc)) from exc
    return AdapterCapability(**validated)


def _reject_mock_only_real_readiness(
    *,
    provider: str,
    deployment_mode: str,
    endpoint_ref: str,
    mocked: bool,
    mock_profile_ref: str,
) -> None:
    if provider.lower() == "mock":
        raise AsrProfileValidationError("ASR real readiness must not use mock provider")
    if deployment_mode.lower() == "mock":
        raise AsrProfileValidationError("ASR real readiness must not use mock deployment")
    if endpoint_ref.startswith("mock://"):
        raise AsrProfileValidationError("ASR real readiness must not use mock endpoint")
    if mocked:
        raise AsrProfileValidationError("ASR real readiness must declare mocked=false")
    if mock_profile_ref not in ("", None):
        raise AsrProfileValidationError("ASR real readiness must not use mock_profile_ref")
