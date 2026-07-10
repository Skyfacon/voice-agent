from __future__ import annotations

import pytest

from voice_agent.adapters.capabilities import AdapterCapability, ALL_BOOLEAN_CAPABILITY_FIELDS
from voice_agent.adapters.mock_adapters import mvp0_mock_adapter_capabilities
from voice_agent.adapters.profiles import (
    AdapterProfileValidationError,
    MVP3_REQUIRED_REAL_ADAPTER_TYPES,
    validate_mvp3_adapter_profile_set,
)


def mvp3_real_capability(adapter_type: str, **overrides: object) -> AdapterCapability:
    fields: dict[str, object] = {
        "adapter_id": f"mvp3_{adapter_type}",
        "adapter_type": adapter_type,
        "provider": "synthetic_provider",
        "model_name": f"synthetic_{adapter_type}_model",
        "deployment_mode": "remote_api",
        "endpoint": f"endpoint://synthetic/mvp3/{adapter_type}",
        "health_status": "configured",
        "capability_version": "mvp3.contract.v1",
        "latency_class": "contract_test",
        "error_model": "error-model://synthetic/mvp3/provider",
        "timeout_policy": "timeout-policy://synthetic/mvp3/default",
        "retry_policy": "retry-policy://synthetic/mvp3/default",
        "output_mode": "real",
        "config_ref": f"config://synthetic/mvp3/{adapter_type}",
        "role_contract": "",
        "prompt_profile": "",
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
        "supports_fast_interaction_output": False,
        "supports_route_hint": False,
        "supports_route_prelude": False,
        "supports_foreground_act": False,
        "supports_reply_candidate": False,
        "supports_reply_delta_streaming": False,
        "supports_final_fast_evidence": False,
        "supports_schema_validation": False,
        "supports_risk_tags": False,
        "supports_confidence": False,
        "supports_asr_text_fallback": False,
        "supports_provider_stream_timing": False,
        "supports_ttft_observation": False,
        "max_audio_seconds": None,
        "max_context_tokens": 4096,
        "max_output_tokens": 1024,
        "expected_first_token_latency_ms": 500,
        "expected_first_audio_latency_ms": None,
        "max_reply_candidate_tokens": None,
        "expected_first_candidate_latency_ms": None,
        "expected_final_gate_ready_latency_ms": None,
        "mocked": False,
        "mock_profile_ref": "",
        "target_architecture_validation": True,
    }
    if adapter_type == "asr":
        fields.update(
            supports_audio_input=True,
            supports_structured_json=True,
            max_audio_seconds=30,
            max_output_tokens=256,
        )
    elif adapter_type in {"thinker", "slow_llm"}:
        fields.update(supports_structured_json=True, supports_schema_validation=True)
    elif adapter_type == "tts":
        fields.update(
            supports_streaming_output=True,
            supports_audio_output=True,
            supports_tts=True,
            expected_first_audio_latency_ms=700,
        )
    fields.update(overrides)
    fields["unsupported_capabilities"] = tuple(
        field for field in ALL_BOOLEAN_CAPABILITY_FIELDS if fields[field] is False
    )
    return AdapterCapability(**fields)  # type: ignore[arg-type]


def valid_mvp3_real_profiles() -> tuple[AdapterCapability, ...]:
    return tuple(
        mvp3_real_capability(adapter_type)
        for adapter_type in MVP3_REQUIRED_REAL_ADAPTER_TYPES
    )


def test_mvp3_profile_set_requires_real_profiles_for_each_required_adapter_type() -> None:
    incomplete_profiles = tuple(
        capability
        for capability in valid_mvp3_real_profiles()
        if capability.adapter_type != "slow_llm"
    )

    with pytest.raises(AdapterProfileValidationError, match="slow_llm"):
        validate_mvp3_adapter_profile_set(incomplete_profiles)


def test_mvp3_profile_set_does_not_count_mock_profiles_as_real_readiness() -> None:
    with pytest.raises(AdapterProfileValidationError, match="real adapter profile"):
        validate_mvp3_adapter_profile_set(mvp0_mock_adapter_capabilities())


def test_mvp3_profile_set_rejects_real_label_on_mock_provider_or_endpoint() -> None:
    profiles = (
        *valid_mvp3_real_profiles()[:-1],
        mvp3_real_capability(
            "tts",
            provider="mock",
            endpoint="mock://mvp3/tts",
        ),
    )

    with pytest.raises(AdapterProfileValidationError, match="mock"):
        validate_mvp3_adapter_profile_set(profiles)


def test_mvp3_profile_set_rejects_missing_minimum_required_capability() -> None:
    profiles = (
        mvp3_real_capability("asr", supports_structured_json=False),
        *valid_mvp3_real_profiles()[1:],
    )

    with pytest.raises(AdapterProfileValidationError, match="supports_structured_json"):
        validate_mvp3_adapter_profile_set(profiles)


def test_valid_mvp3_profile_set_returns_validated_matrices_without_provider_probe() -> None:
    matrices = validate_mvp3_adapter_profile_set(valid_mvp3_real_profiles())

    assert [matrix["adapter_type"] for matrix in matrices] == list(MVP3_REQUIRED_REAL_ADAPTER_TYPES)
    assert {matrix["output_mode"] for matrix in matrices} == {"real"}
    assert {matrix["target_architecture_validation"] for matrix in matrices} == {True}
