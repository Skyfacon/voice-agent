from __future__ import annotations

import pytest

from voice_agent.adapters.capabilities import (
    BOOLEAN_CAPABILITY_FIELDS,
    REQUIRED_CAPABILITY_FIELDS,
    REQUIRED_IDENTITY_FIELDS,
    CapabilityValidationError,
    validate_capability_matrix,
)
from voice_agent.adapters.mock_adapters import (
    MVP0_MOCK_CAPABILITY_SNAPSHOT_REF,
    mvp0_capability_snapshot,
    mvp0_mock_adapter_capabilities,
)


def test_mvp0_mock_adapters_declare_required_capability_fields() -> None:
    capabilities = mvp0_mock_adapter_capabilities()

    assert {capability.adapter_id for capability in capabilities} == {
        "mock_asr",
        "mock_thinker",
        "mock_talker",
    }
    assert {capability.adapter_type for capability in capabilities} == {"asr", "thinker", "tts"}

    for capability in capabilities:
        matrix = capability.to_dict()

        assert set(REQUIRED_IDENTITY_FIELDS) <= set(matrix)
        assert set(REQUIRED_CAPABILITY_FIELDS) <= set(matrix)
        assert matrix["provider"] == "mock"
        assert matrix["deployment_mode"] == "mock"
        assert matrix["output_mode"] == "mock"
        assert matrix["mocked"] is True
        assert matrix["mock_profile_ref"].startswith("mock-profile://synthetic/mvp0/")
        assert isinstance(matrix["target_architecture_validation"], bool)
        assert validate_capability_matrix(matrix) == matrix


def test_unsupported_mock_capabilities_are_explicit_not_assumed() -> None:
    for capability in mvp0_mock_adapter_capabilities():
        matrix = capability.to_dict()
        unsupported = set(matrix["unsupported_capabilities"])
        false_capabilities = {
            field for field in BOOLEAN_CAPABILITY_FIELDS if matrix[field] is False
        }

        assert false_capabilities
        assert false_capabilities <= unsupported


def test_capability_refs_reject_credential_like_values() -> None:
    safe_matrices = [capability.to_dict() for capability in mvp0_mock_adapter_capabilities()]

    for matrix in safe_matrices:
        assert validate_capability_matrix(matrix)["endpoint"].startswith("mock://")
        assert validate_capability_matrix(matrix)["config_ref"].startswith("config://synthetic/")

    unsafe_endpoint = dict(safe_matrices[0])
    unsafe_endpoint["endpoint"] = "https://provider.example.test/v1?api_key=sk-synthetic"
    with pytest.raises(CapabilityValidationError, match="credential"):
        validate_capability_matrix(unsafe_endpoint)

    unsafe_config_ref = dict(safe_matrices[0])
    unsafe_config_ref["config_ref"] = "config://synthetic/mvp0/Bearer synthetic-token"
    with pytest.raises(CapabilityValidationError, match="credential"):
        validate_capability_matrix(unsafe_config_ref)


def test_capability_matrix_rejects_unknown_fields_before_trace_exposure() -> None:
    matrix = mvp0_mock_adapter_capabilities()[0].to_dict()
    matrix["authorization_header"] = "Bearer synthetic-token"

    with pytest.raises(CapabilityValidationError, match="Unknown capability matrix fields"):
        validate_capability_matrix(matrix)


def test_unsupported_capabilities_cannot_contradict_declared_support() -> None:
    matrix = mvp0_mock_adapter_capabilities()[0].to_dict()
    matrix["unsupported_capabilities"] = (
        *matrix["unsupported_capabilities"],
        "supports_audio_input",
    )

    with pytest.raises(CapabilityValidationError, match="contradict declared support"):
        validate_capability_matrix(matrix)


def test_startup_snapshot_records_modes_needed_for_replay_without_adapter_probe() -> None:
    capabilities = mvp0_mock_adapter_capabilities()

    snapshot = mvp0_capability_snapshot(capabilities)

    assert snapshot == {
        "capability_snapshot_ref": MVP0_MOCK_CAPABILITY_SNAPSHOT_REF,
        "adapter_ids": ["mock_asr", "mock_thinker", "mock_talker"],
        "adapter_types": ["asr", "thinker", "tts"],
        "deployment_modes": ["mock", "mock", "mock"],
        "output_modes": ["mock", "mock", "mock"],
        "capability_version": "mvp0.mock.v1",
    }
