from __future__ import annotations

from voice_agent.adapters.capabilities import AdapterCapability, ALL_BOOLEAN_CAPABILITY_FIELDS

FAST_INTERACTION_RUNTIME_ADAPTER_ID = "mvp63_fast_interaction_runtime"
FAST_INTERACTION_RUNTIME_MODEL_ALIAS = "qwen3.5-fast-interaction"


def build_fast_interaction_capability(
    *,
    adapter_id: str = FAST_INTERACTION_RUNTIME_ADAPTER_ID,
    model_name: str = FAST_INTERACTION_RUNTIME_MODEL_ALIAS,
    endpoint: str = "provider-url://dashscope/openai-compatible-chat-completions",
    config_ref: str = "config://runtime/fast-interaction/dashscope",
    output_mode: str = "real",
) -> AdapterCapability:
    """Build safe live Fast Interaction runtime capability metadata.

    This is metadata only: no provider probe, SDK import, transport construction,
    credential read, prompt materialization, or runtime integration.
    """

    fields: dict[str, object] = {
        "adapter_id": adapter_id,
        "adapter_type": "fast_interaction",
        "provider": "dashscope_bailian",
        "model_name": model_name,
        "deployment_mode": "remote_api",
        "endpoint": endpoint,
        "health_status": "configured",
        "capability_version": "mvp6.3.fast-interaction.runtime.v1",
        "latency_class": "remote_api_http_audio_native_fast_interaction",
        "error_model": "error-model://runtime/fast-interaction/dashscope",
        "timeout_policy": "timeout-policy://runtime/fast-interaction/dashscope",
        "retry_policy": "retry-policy://runtime/fast-interaction/dashscope",
        "output_mode": output_mode,
        "config_ref": config_ref,
        "role_contract": "live_fast_interaction_audio_native_v1",
        "prompt_profile": "mvp6.3.fast_interaction.audio_native.v1",
        "supports_streaming_input": False,
        "supports_streaming_output": False,
        "supports_audio_input": True,
        "supports_audio_output": False,
        "supports_audio_timestamps": False,
        "supports_structured_json": True,
        "supports_tool_calling": False,
        "supports_cancellation": False,
        "supports_emotion": False,
        "supports_audio_caption": False,
        "supports_tts": False,
        "supports_tts_truncate": False,
        "supports_tts_pause_resume": False,
        "supports_semantic_close": False,
        "supports_assistant_directedness": False,
        "supports_fast_interaction_output": True,
        "supports_route_hint": True,
        "supports_route_prelude": True,
        "supports_foreground_act": True,
        "supports_reply_candidate": True,
        "supports_reply_delta_streaming": False,
        "supports_final_fast_evidence": True,
        "supports_schema_validation": True,
        "supports_risk_tags": True,
        "supports_confidence": True,
        "supports_asr_text_fallback": True,
        "supports_provider_stream_timing": True,
        "supports_ttft_observation": True,
        "max_audio_seconds": None,
        "max_context_tokens": 8192,
        "max_output_tokens": 900,
        "expected_first_token_latency_ms": None,
        "expected_first_audio_latency_ms": None,
        "max_reply_candidate_tokens": 220,
        "expected_first_candidate_latency_ms": 1200,
        "expected_final_gate_ready_latency_ms": 1600,
        "mocked": False,
        "mock_profile_ref": "",
        "target_architecture_validation": True,
    }
    fields["unsupported_capabilities"] = tuple(
        field for field in ALL_BOOLEAN_CAPABILITY_FIELDS if fields[field] is False
    )
    return AdapterCapability(**fields)  # type: ignore[arg-type]
