from __future__ import annotations

from typing import Any

from voice_agent.adapters.capabilities import (
    AdapterCapability,
    BOOLEAN_CAPABILITY_FIELDS,
)


def build_route_evidence_fake_profile() -> AdapterCapability:
    """Return provider-free Route Evidence and candidate-safety metadata."""

    fields: dict[str, Any] = {
        "adapter_id": "slice3b1_route_evidence_fake",
        "adapter_type": "route_evidence",
        "provider": "scripted_fake_route_evidence",
        "model_name": "scripted_route_evidence_protocol_fake",
        "deployment_mode": "provider_free",
        "endpoint": "mock://slice3b1/route-evidence",
        "health_status": "healthy_mock",
        "capability_version": "slice3b1.route-evidence.fake.v1",
        "latency_class": "provider_free_scripted_text",
        "error_model": "error-model://synthetic/slice3b1/route-evidence",
        "timeout_policy": "timeout-policy://synthetic/slice3b1/route-evidence",
        "retry_policy": "retry-policy://synthetic/slice3b1/route-evidence",
        "status": "mock",
        "output_mode": "mock",
        "config_ref": "config://synthetic/slice3b1/route-evidence",
        "role_contract": "route_evidence_and_candidate_safety_fake_v1",
        "prompt_profile": "slice3b1.route_evidence.fake.v1",
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
        "supports_risk_tags": True,
        "supports_confidence": True,
        "supports_asr_text_fallback": False,
        "supports_provider_stream_timing": False,
        "supports_ttft_observation": False,
        "supports_route_schema": True,
        "supports_task_focus": True,
        "supports_foreground_act_hint": True,
        "supports_ack_kind": True,
        "supports_candidate_safety_schema": True,
        "supports_prohibited_claim_detection": True,
        "supports_strict_json_validation": True,
        "documentation_support": True,
        "provider_free_test_support": True,
        "real_live_support": False,
        "max_audio_seconds": None,
        "max_context_tokens": 4096,
        "max_output_tokens": 256,
        "expected_first_token_latency_ms": 0,
        "expected_first_audio_latency_ms": None,
        "max_reply_candidate_tokens": None,
        "expected_first_candidate_latency_ms": None,
        "expected_final_gate_ready_latency_ms": 0,
        "mocked": True,
        "mock_profile_ref": "mock-profile://synthetic/slice3b1/route-evidence",
        "target_architecture_validation": False,
    }
    fields["unsupported_capabilities"] = tuple(
        field for field in BOOLEAN_CAPABILITY_FIELDS if fields[field] is False
    )
    return AdapterCapability(**fields)
