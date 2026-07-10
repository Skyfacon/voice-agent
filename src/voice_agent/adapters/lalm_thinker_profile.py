from __future__ import annotations

from voice_agent.adapters.capabilities import AdapterCapability, BOOLEAN_CAPABILITY_FIELDS

LALM_THINKER_RUNTIME_ADAPTER_ID = "lalm_thinker_runtime"
LALM_THINKER_RUNTIME_MODEL_ALIAS = "qwen3.5-omni-plus"


def build_lalm_thinker_capability(
    *,
    adapter_id: str = LALM_THINKER_RUNTIME_ADAPTER_ID,
    model_name: str = LALM_THINKER_RUNTIME_MODEL_ALIAS,
    endpoint: str = "provider-url://dashscope/openai-compatible-chat-completions",
    config_ref: str = "config://runtime/lalm-thinker/dashscope",
    output_mode: str = "real",
) -> AdapterCapability:
    """Build default real LALM Thinker runtime capability metadata.

    The profile is safe startup metadata only: it does not probe the provider,
    read credentials, import an SDK, or materialize any secret value.
    """

    fields: dict[str, object] = {
        "adapter_id": adapter_id,
        "adapter_type": "thinker",
        "provider": "dashscope_bailian",
        "model_name": model_name,
        "deployment_mode": "remote_api",
        "endpoint": endpoint,
        "health_status": "configured",
        "capability_version": "mvp3.lalm-thinker.runtime.v1",
        "latency_class": "remote_api_http",
        "error_model": "error-model://runtime/lalm-thinker/dashscope",
        "timeout_policy": "timeout-policy://runtime/lalm-thinker/dashscope",
        "retry_policy": "retry-policy://runtime/lalm-thinker/dashscope",
        "output_mode": output_mode,
        "config_ref": config_ref,
        "role_contract": "",
        "prompt_profile": "",
        "supports_streaming_input": False,
        "supports_streaming_output": False,
        "supports_audio_input": False,
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
        "supports_provider_stream_timing": True,
        "supports_ttft_observation": True,
        "max_audio_seconds": None,
        "max_context_tokens": 8192,
        "max_output_tokens": 2048,
        "expected_first_token_latency_ms": None,
        "expected_first_audio_latency_ms": None,
        "max_reply_candidate_tokens": None,
        "expected_first_candidate_latency_ms": None,
        "expected_final_gate_ready_latency_ms": None,
        "mocked": False,
        "mock_profile_ref": "",
        "target_architecture_validation": True,
    }
    fields["unsupported_capabilities"] = tuple(
        field for field in BOOLEAN_CAPABILITY_FIELDS if fields[field] is False
    )
    return AdapterCapability(**fields)  # type: ignore[arg-type]
