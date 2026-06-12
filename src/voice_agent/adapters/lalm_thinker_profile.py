from __future__ import annotations

from voice_agent.adapters.capabilities import AdapterCapability, BOOLEAN_CAPABILITY_FIELDS


def build_lalm_thinker_capability(
    *,
    adapter_id: str = "lalm_thinker_provider_free",
    model_name: str = "lalm-thinker-provider-free-skeleton",
    endpoint: str = "endpoint://synthetic/lalm-thinker/provider-free",
    config_ref: str = "config://synthetic/lalm-thinker/provider-free",
    output_mode: str = "real",
) -> AdapterCapability:
    """Build provider-free LALM Thinker capability metadata.

    This builder performs no provider probe, credential lookup, SDK import, or
    runtime adapter assembly. Validation remains with the shared capability
    matrix/profile gates.
    """

    fields: dict[str, object] = {
        "adapter_id": adapter_id,
        "adapter_type": "thinker",
        "provider": "lalm_provider_neutral",
        "model_name": model_name,
        "deployment_mode": "remote_api",
        "endpoint": endpoint,
        "health_status": "configured",
        "capability_version": "mvp3.lalm-thinker.provider-free.v1",
        "latency_class": "provider_free_metadata_only",
        "error_model": "error-model://synthetic/lalm-thinker/provider-free",
        "timeout_policy": "timeout-policy://synthetic/lalm-thinker/provider-free",
        "retry_policy": "retry-policy://synthetic/lalm-thinker/provider-free",
        "output_mode": output_mode,
        "config_ref": config_ref,
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
        "max_audio_seconds": None,
        "max_context_tokens": 8192,
        "max_output_tokens": 2048,
        "expected_first_token_latency_ms": None,
        "expected_first_audio_latency_ms": None,
        "mocked": False,
        "mock_profile_ref": "",
        "target_architecture_validation": True,
    }
    fields["unsupported_capabilities"] = tuple(
        field for field in BOOLEAN_CAPABILITY_FIELDS if fields[field] is False
    )
    return AdapterCapability(**fields)  # type: ignore[arg-type]
