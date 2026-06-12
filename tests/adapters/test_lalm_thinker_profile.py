from __future__ import annotations

from copy import deepcopy

import pytest

from tests.adapters.test_mvp3_adapter_profiles import mvp3_real_capability
from voice_agent.adapters.capabilities import (
    BOOLEAN_CAPABILITY_FIELDS,
    CapabilityValidationError,
    validate_capability_matrix,
)
from voice_agent.adapters.lalm_thinker_profile import (
    build_lalm_thinker_capability,
)
from voice_agent.adapters.profiles import (
    AdapterProfileValidationError,
    validate_mvp3_adapter_profile_set,
)


def test_lalm_thinker_profile_is_provider_free_real_readiness_metadata() -> None:
    capability = build_lalm_thinker_capability()
    matrix = validate_capability_matrix(capability.to_dict())

    assert matrix["adapter_type"] == "thinker"
    assert matrix["provider"] == "lalm_provider_neutral"
    assert matrix["deployment_mode"] == "remote_api"
    assert matrix["output_mode"] == "real"
    assert matrix["supports_structured_json"] is True
    assert matrix["endpoint"] == "endpoint://synthetic/lalm-thinker/provider-free"
    assert matrix["config_ref"] == "config://synthetic/lalm-thinker/provider-free"
    assert matrix["mocked"] is False
    assert matrix["mock_profile_ref"] == ""
    assert matrix["target_architecture_validation"] is True

    unsupported = set(matrix["unsupported_capabilities"])
    expected_unsupported = {
        "supports_streaming_input",
        "supports_streaming_output",
        "supports_audio_input",
        "supports_audio_output",
        "supports_audio_timestamps",
        "supports_tool_calling",
        "supports_cancellation",
        "supports_emotion",
        "supports_audio_caption",
        "supports_tts",
        "supports_tts_truncate",
        "supports_tts_pause_resume",
        "supports_semantic_close",
        "supports_assistant_directedness",
    }
    assert expected_unsupported <= unsupported
    assert unsupported == {field for field in BOOLEAN_CAPABILITY_FIELDS if matrix[field] is False}

    rendered = repr(matrix).lower()
    assert "api_key" not in rendered
    assert "authorization" not in rendered
    assert "bearer " not in rendered
    assert "token=" not in rendered
    assert "credential=" not in rendered


def test_lalm_thinker_profile_can_replace_required_mvp3_thinker_profile_without_provider_probe() -> None:
    profiles = (
        mvp3_real_capability("asr"),
        build_lalm_thinker_capability(),
        mvp3_real_capability("slow_llm"),
        mvp3_real_capability("tts"),
    )

    validated = validate_mvp3_adapter_profile_set(profiles)

    assert [matrix["adapter_type"] for matrix in validated] == [
        "asr",
        "thinker",
        "slow_llm",
        "tts",
    ]
    assert validated[1]["adapter_id"] == "lalm_thinker_provider_free"
    assert validated[1]["supports_structured_json"] is True


def test_lalm_thinker_fallback_and_degraded_profiles_do_not_satisfy_required_real_readiness() -> None:
    fallback = build_lalm_thinker_capability(
        adapter_id="lalm_thinker_provider_free_fallback",
        output_mode="fallback",
    )
    degraded = build_lalm_thinker_capability(
        adapter_id="lalm_thinker_provider_free_degraded",
        output_mode="degraded",
    )

    assert validate_capability_matrix(fallback.to_dict())["output_mode"] == "fallback"
    assert validate_capability_matrix(degraded.to_dict())["output_mode"] == "degraded"

    with pytest.raises(AdapterProfileValidationError, match="adapter_type='thinker'"):
        validate_mvp3_adapter_profile_set(
            (
                mvp3_real_capability("asr"),
                fallback,
                degraded,
                mvp3_real_capability("slow_llm"),
                mvp3_real_capability("tts"),
            )
        )


@pytest.mark.parametrize(
    ("field", "unsafe_ref"),
    (
        ("endpoint", "endpoint://synthetic/lalm-thinker?api_key=sk-synthetic"),
        ("config_ref", "config://synthetic/lalm-thinker?authorization=Bearer%20synthetic"),
    ),
)
def test_lalm_thinker_profile_fails_closed_for_credential_like_refs(
    field: str,
    unsafe_ref: str,
) -> None:
    capability = build_lalm_thinker_capability(**{field: unsafe_ref})

    with pytest.raises(CapabilityValidationError, match="credential"):
        validate_capability_matrix(capability.to_dict())


def test_lalm_thinker_profile_requires_explicit_unsupported_capabilities() -> None:
    matrix = build_lalm_thinker_capability().to_dict()
    invalid = deepcopy(matrix)
    invalid["unsupported_capabilities"] = tuple(
        field
        for field in matrix["unsupported_capabilities"]
        if field != "supports_audio_caption"
    )

    with pytest.raises(CapabilityValidationError, match="supports_audio_caption"):
        validate_capability_matrix(invalid)
