from __future__ import annotations

from typing import Any

from voice_agent.adapters.asr_profile import build_asr_capability_profile
from voice_agent.adapters.capabilities import (
    AdapterCapability,
    BOOLEAN_CAPABILITY_FIELDS,
)


def build_qwen_realtime_fake_profile() -> AdapterCapability:
    """Return provider-free Slice 3B.1 session capability metadata."""

    fields: dict[str, Any] = {
        "adapter_id": "slice3b1_qwen_realtime_fake",
        "adapter_type": "duplex_model",
        "provider": "scripted_fake_qwen",
        "model_name": "scripted_qwen_realtime_protocol_fake",
        "deployment_mode": "provider_free",
        "endpoint": "mock://slice3b1/qwen-realtime/session",
        "health_status": "healthy_mock",
        "capability_version": "slice3b1.qwen-realtime.fake.v1",
        "latency_class": "provider_free_scripted_realtime",
        "error_model": "error-model://synthetic/slice3b1/qwen-realtime",
        "timeout_policy": "timeout-policy://synthetic/slice3b1/qwen-realtime",
        "retry_policy": "retry-policy://synthetic/slice3b1/qwen-realtime",
        "status": "mock",
        "output_mode": "mock",
        "config_ref": "config://synthetic/slice3b1/qwen-realtime",
        "role_contract": "qwen_realtime_session_fake_v1",
        "prompt_profile": "slice3b1.qwen_realtime.fake.v1",
        "supports_streaming_input": True,
        "supports_streaming_output": True,
        "supports_audio_input": True,
        "supports_audio_output": True,
        "supports_audio_timestamps": False,
        "supports_structured_json": False,
        "supports_tool_calling": False,
        "supports_cancellation": True,
        "supports_emotion": False,
        "supports_audio_caption": False,
        "supports_tts": False,
        "supports_tts_truncate": False,
        "supports_tts_pause_resume": False,
        "supports_semantic_close": True,
        "supports_assistant_directedness": True,
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
        "supports_smart_turn": True,
        "supports_streaming_asr": True,
        "supports_provider_response_cancellation": True,
        "supports_provider_item_create": False,
        "supports_provider_item_delete_ack": True,
        "supports_manual_response_while_idle": False,
        "supports_text_only_response_override": False,
        "supports_candidate_quarantine": True,
        "supports_provider_native_audio_release": False,
        "supports_provider_context_readiness": True,
        "supports_context_rebuild": True,
        "documentation_support": True,
        "provider_free_test_support": True,
        "real_live_support": False,
        "max_audio_seconds": 30,
        "max_context_tokens": 8192,
        "max_output_tokens": 256,
        "expected_first_token_latency_ms": 0,
        "expected_first_audio_latency_ms": 0,
        "max_reply_candidate_tokens": 80,
        "expected_first_candidate_latency_ms": 0,
        "expected_final_gate_ready_latency_ms": None,
        "mocked": True,
        "mock_profile_ref": "mock-profile://synthetic/slice3b1/qwen-realtime",
        "target_architecture_validation": False,
    }
    fields["unsupported_capabilities"] = tuple(
        field for field in BOOLEAN_CAPABILITY_FIELDS if fields[field] is False
    )
    return AdapterCapability(**fields)


def build_qwen_realtime_asr_fake_profile() -> AdapterCapability:
    """Return the logical ASR projection used by the scripted Qwen session."""

    return build_asr_capability_profile(
        adapter_id="slice3b1_qwen_realtime_asr_projection",
        provider="scripted_fake_qwen",
        model_name="scripted_qwen_realtime_asr_projection",
        endpoint_ref="mock://slice3b1/qwen-realtime/asr-projection",
        config_ref="config://synthetic/slice3b1/qwen-realtime/asr-projection",
        output_mode="mock",
        deployment_mode="provider_free",
        supports_streaming_input=True,
        supports_streaming_output=True,
        supports_cancellation=True,
        supports_candidate_output_audio_shadow_verification=True,
        documentation_support=True,
        provider_free_test_support=True,
        real_live_support=False,
        mocked=True,
        mock_profile_ref=(
            "mock-profile://synthetic/slice3b1/qwen-realtime/asr-projection"
        ),
        target_architecture_validation=False,
    )
