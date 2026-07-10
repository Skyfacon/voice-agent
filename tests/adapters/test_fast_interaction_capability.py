from __future__ import annotations

import pytest

from voice_agent.adapters.capabilities import (
    ALL_BOOLEAN_CAPABILITY_FIELDS,
    CapabilityValidationError,
    validate_capability_matrix,
)
from voice_agent.adapters.fast_interaction_profile import (
    FAST_INTERACTION_RUNTIME_ADAPTER_ID,
    FAST_INTERACTION_RUNTIME_MODEL_ALIAS,
    build_fast_interaction_capability,
)


def test_live_fast_interaction_capability_declares_adr017_fields() -> None:
    capability = build_fast_interaction_capability().to_dict()

    assert capability["adapter_id"] == FAST_INTERACTION_RUNTIME_ADAPTER_ID
    assert capability["adapter_type"] == "fast_interaction"
    assert capability["provider"] == "dashscope_bailian"
    assert capability["model_name"] == FAST_INTERACTION_RUNTIME_MODEL_ALIAS
    assert capability["deployment_mode"] == "remote_api"
    assert capability["endpoint"] == "provider-url://dashscope/openai-compatible-chat-completions"
    assert capability["config_ref"] == "config://runtime/fast-interaction/dashscope"
    assert capability["output_mode"] == "real"
    assert capability["capability_version"] == "mvp6.3.fast-interaction.runtime.v1"
    assert capability["latency_class"] == "remote_api_http_audio_native_fast_interaction"
    assert capability["role_contract"] == "live_fast_interaction_audio_native_v1"
    assert capability["prompt_profile"] == "mvp6.3.fast_interaction.audio_native.v1"

    assert capability["supports_fast_interaction_output"] is True
    assert capability["supports_route_hint"] is True
    assert capability["supports_route_prelude"] is True
    assert capability["supports_foreground_act"] is True
    assert capability["supports_reply_candidate"] is True
    assert capability["supports_reply_delta_streaming"] is False
    assert capability["supports_final_fast_evidence"] is True
    assert capability["supports_risk_tags"] is True
    assert capability["supports_confidence"] is True
    assert capability["supports_structured_json"] is True
    assert capability["supports_schema_validation"] is True
    assert capability["supports_asr_text_fallback"] is True
    assert capability["supports_provider_stream_timing"] is True
    assert capability["supports_ttft_observation"] is True

    assert capability["supports_audio_input"] is True
    assert capability["supports_audio_output"] is False
    assert capability["supports_tool_calling"] is False
    assert capability["supports_tts"] is False
    assert capability["supports_semantic_close"] is False
    assert capability["supports_assistant_directedness"] is False

    assert capability["max_reply_candidate_tokens"] == 220
    assert capability["expected_first_candidate_latency_ms"] == 1200
    assert capability["expected_final_gate_ready_latency_ms"] == 1600
    assert "supports_reply_delta_streaming" in capability["unsupported_capabilities"]


@pytest.mark.parametrize(
    ("field", "unsafe_ref"),
    (
        ("endpoint", "https://provider.example.test/v1?api_key=sk-synthetic"),
        ("config_ref", "config://runtime/fast-interaction?authorization=Bearer%20synthetic"),
    ),
)
def test_fast_interaction_capability_rejects_credential_like_refs(
    field: str,
    unsafe_ref: str,
) -> None:
    capability = build_fast_interaction_capability(**{field: unsafe_ref})

    with pytest.raises(CapabilityValidationError, match="credential"):
        validate_capability_matrix(capability.to_dict())


@pytest.mark.parametrize("output_mode", ("fallback", "degraded"))
def test_fast_interaction_capability_can_declare_fallback_or_degraded_modes(
    output_mode: str,
) -> None:
    capability = build_fast_interaction_capability(output_mode=output_mode).to_dict()

    assert validate_capability_matrix(capability)["output_mode"] == output_mode


def test_fast_interaction_capability_rejects_invalid_output_mode() -> None:
    capability = build_fast_interaction_capability(output_mode="experimental")

    with pytest.raises(CapabilityValidationError, match="Unsupported output_mode"):
        validate_capability_matrix(capability.to_dict())


@pytest.mark.parametrize(
    ("adapter_type", "field"),
    (
        ("thinker", "supports_route_hint"),
        ("thinker", "supports_foreground_act"),
        ("slow_llm", "supports_reply_candidate"),
        ("asr", "supports_final_fast_evidence"),
        ("tts", "supports_risk_tags"),
        ("slow_llm", "supports_confidence"),
        ("thinker", "supports_fast_interaction_output"),
        ("thinker", "supports_reply_delta_streaming"),
        ("asr", "supports_asr_text_fallback"),
    ),
)
def test_non_fast_interaction_adapters_cannot_claim_fast_interaction_owned_fields(
    adapter_type: str,
    field: str,
) -> None:
    matrix = build_fast_interaction_capability().to_dict()
    matrix["adapter_id"] = f"synthetic_{adapter_type}_bad_fast_claim"
    matrix["adapter_type"] = adapter_type
    matrix[field] = True
    matrix["unsupported_capabilities"] = tuple(
        capability
        for capability in ALL_BOOLEAN_CAPABILITY_FIELDS
        if matrix[capability] is False
    )

    with pytest.raises(CapabilityValidationError, match=rf"(fast_interaction|{field})"):
        validate_capability_matrix(matrix)


def test_unsupported_capabilities_are_returned_in_canonical_boolean_field_order() -> None:
    matrix = build_fast_interaction_capability().to_dict()
    canonical_unsupported = tuple(
        field for field in ALL_BOOLEAN_CAPABILITY_FIELDS if matrix[field] is False
    )
    matrix["unsupported_capabilities"] = tuple(reversed(canonical_unsupported))

    validated = validate_capability_matrix(matrix)

    assert validated["unsupported_capabilities"] == canonical_unsupported


def test_duplicate_unsupported_capabilities_are_canonicalized_without_snapshot_instability() -> None:
    matrix = build_fast_interaction_capability().to_dict()
    canonical_unsupported = tuple(
        field for field in ALL_BOOLEAN_CAPABILITY_FIELDS if matrix[field] is False
    )
    matrix["unsupported_capabilities"] = (
        canonical_unsupported[0],
        *reversed(canonical_unsupported),
        canonical_unsupported[0],
    )

    validated = validate_capability_matrix(matrix)

    assert validated["unsupported_capabilities"] == canonical_unsupported
