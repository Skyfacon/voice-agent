from __future__ import annotations

import pytest

from voice_agent.adapters.capabilities import (
    CapabilityValidationError,
    validate_capability_matrix,
)
from voice_agent.adapters.route_evidence_profile import (
    build_route_evidence_fake_profile,
)


def test_route_evidence_profile_claims_only_its_role_contract() -> None:
    matrix = build_route_evidence_fake_profile().to_dict()

    assert matrix["adapter_type"] == "route_evidence"
    assert matrix["deployment_mode"] == "provider_free"
    assert matrix["endpoint"].startswith("mock://")
    assert matrix["status"] == "mock"
    assert matrix["output_mode"] == "mock"
    assert matrix["supports_route_schema"] is True
    assert matrix["supports_candidate_safety_schema"] is True
    assert matrix["supports_prohibited_claim_detection"] is True
    assert matrix["supports_strict_json_validation"] is True
    assert matrix["supports_risk_tags"] is True
    assert matrix["supports_confidence"] is True
    assert matrix["supports_fast_interaction_output"] is False
    assert matrix["supports_reply_candidate"] is False
    assert matrix["provider_free_test_support"] is True
    assert matrix["real_live_support"] is False


def test_route_evidence_capabilities_are_owned_only_by_route_evidence() -> None:
    matrix = build_route_evidence_fake_profile().to_dict()
    matrix["adapter_type"] = "fast_interaction"

    with pytest.raises(CapabilityValidationError, match="route_evidence"):
        validate_capability_matrix(matrix)
