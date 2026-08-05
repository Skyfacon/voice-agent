from __future__ import annotations

from typing import Any

from voice_agent.adapters.capabilities import (
    AdapterCapability,
    BOOLEAN_CAPABILITY_FIELDS,
)


def build_parallel_fast_interaction_orchestrator_profile() -> AdapterCapability:
    """Return truthful metadata for the provider-free local evidence join."""

    fields: dict[str, Any] = {
        "adapter_id": "slice3b1_parallel_fast_interaction_orchestrator",
        "adapter_type": "fast_interaction",
        "provider": "local_parallel_orchestrator",
        "model_name": "no_model_local_evidence_join",
        "deployment_mode": "provider_free",
        "endpoint": "mock://slice3b1/local-parallel-orchestrator",
        "health_status": "healthy_mock",
        "capability_version": "slice3b1.parallel-fast-interaction.v1",
        "latency_class": "local_in_memory_join",
        "error_model": "error-model://synthetic/slice3b1/parallel-join",
        "timeout_policy": "timeout-policy://synthetic/slice3b1/parallel-join",
        "retry_policy": "retry-policy://synthetic/slice3b1/parallel-join",
        "status": "mock",
        "output_mode": "mock",
        "config_ref": "config://synthetic/slice3b1/parallel-join",
        "role_contract": "local_parallel_fast_interaction_join_v1",
        "prompt_profile": "not-applicable://local-parallel-orchestrator",
        "supports_streaming_input": False,
        "supports_streaming_output": False,
        "supports_audio_input": False,
        "supports_audio_output": False,
        "supports_audio_timestamps": False,
        "supports_structured_json": False,
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
        "supports_route_hint": False,
        "supports_route_prelude": False,
        "supports_foreground_act": False,
        "supports_reply_candidate": True,
        "supports_reply_delta_streaming": False,
        "supports_final_fast_evidence": True,
        "supports_schema_validation": True,
        "supports_risk_tags": False,
        "supports_confidence": False,
        "supports_asr_text_fallback": False,
        "supports_provider_stream_timing": False,
        "supports_ttft_observation": False,
        "documentation_support": True,
        "provider_free_test_support": True,
        "real_live_support": False,
        "max_audio_seconds": None,
        "max_context_tokens": None,
        "max_output_tokens": None,
        "expected_first_token_latency_ms": None,
        "expected_first_audio_latency_ms": None,
        "max_reply_candidate_tokens": 80,
        "expected_first_candidate_latency_ms": 0,
        "expected_final_gate_ready_latency_ms": 0,
        "mocked": True,
        "mock_profile_ref": "mock-profile://synthetic/slice3b1/parallel-join",
        "target_architecture_validation": False,
    }
    fields["unsupported_capabilities"] = tuple(
        field for field in BOOLEAN_CAPABILITY_FIELDS if fields[field] is False
    )
    return AdapterCapability(**fields)
