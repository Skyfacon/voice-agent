from __future__ import annotations

from dataclasses import replace

import pytest

from voice_agent.adapters.capabilities import (
    ADR018_BOOLEAN_CAPABILITY_FIELDS,
    CapabilityValidationError,
    validate_capability_matrix,
)
from voice_agent.adapters.qwen_realtime.profile import (
    build_qwen_realtime_asr_fake_profile,
    build_qwen_realtime_fake_profile,
)


def test_qwen_slice3b1_profile_is_provider_free_and_native_pcm_disabled() -> None:
    matrix = build_qwen_realtime_fake_profile().to_dict()

    assert matrix["adapter_type"] == "duplex_model"
    assert matrix["provider"] == "scripted_fake_qwen"
    assert matrix["deployment_mode"] == "provider_free"
    assert matrix["endpoint"].startswith("mock://")
    assert matrix["status"] == "mock"
    assert matrix["output_mode"] == "mock"
    assert matrix["documentation_support"] is True
    assert matrix["provider_free_test_support"] is True
    assert matrix["real_live_support"] is False
    assert matrix["supports_smart_turn"] is True
    assert matrix["supports_streaming_asr"] is True
    assert matrix["supports_candidate_quarantine"] is True
    assert matrix["supports_provider_native_audio_release"] is False


def test_qwen_asr_projection_is_mock_shadow_verification_metadata_only() -> None:
    matrix = build_qwen_realtime_asr_fake_profile().to_dict()

    assert matrix["adapter_type"] == "asr"
    assert matrix["deployment_mode"] == "provider_free"
    assert matrix["output_mode"] == "mock"
    assert matrix["mocked"] is True
    assert matrix["provider_free_test_support"] is True
    assert matrix["real_live_support"] is False
    assert matrix["supports_candidate_output_audio_shadow_verification"] is True
    assert matrix["supports_provider_native_audio_release"] is False


def test_qwen_session_capabilities_are_owned_only_by_duplex_model() -> None:
    matrix = build_qwen_realtime_fake_profile().to_dict()
    matrix["adapter_type"] = "asr"

    with pytest.raises(CapabilityValidationError, match="duplex_model"):
        validate_capability_matrix(matrix)


def test_new_adr018_profile_requires_explicit_support_facts() -> None:
    matrix = build_qwen_realtime_fake_profile().to_dict()
    matrix.pop("provider_free_test_support")

    with pytest.raises(CapabilityValidationError, match="support facts"):
        validate_capability_matrix(matrix)


def _matrix_without_adr018_declarations() -> dict[str, object]:
    matrix = build_qwen_realtime_fake_profile().to_dict()
    for field in ADR018_BOOLEAN_CAPABILITY_FIELDS:
        matrix.pop(field)
    matrix["unsupported_capabilities"] = tuple(
        field
        for field in matrix["unsupported_capabilities"]
        if field not in ADR018_BOOLEAN_CAPABILITY_FIELDS
    )
    return matrix


@pytest.mark.parametrize(
    ("declaration", "value"),
    (
        ("provider_free_test_support", True),
        ("documentation_support", True),
        ("supports_smart_turn", False),
    ),
)
def test_partial_adr018_declaration_requires_all_support_facts(
    declaration: str,
    value: bool,
) -> None:
    matrix = _matrix_without_adr018_declarations()
    matrix[declaration] = value

    with pytest.raises(CapabilityValidationError, match="support facts"):
        validate_capability_matrix(matrix)


def test_complete_legacy_adr018_omission_still_normalizes_to_false() -> None:
    matrix = _matrix_without_adr018_declarations()

    validated = validate_capability_matrix(matrix)

    assert all(
        validated[field] is False for field in ADR018_BOOLEAN_CAPABILITY_FIELDS
    )


def test_native_pcm_claim_does_not_become_real_live_support() -> None:
    profile = replace(
        build_qwen_realtime_fake_profile(),
        supports_provider_native_audio_release=True,
    )

    matrix = profile.to_dict()

    assert matrix["supports_provider_native_audio_release"] is True
    assert matrix["real_live_support"] is False
