from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from voice_agent.adapters.capabilities import (
    BOOLEAN_CAPABILITY_FIELDS,
    CapabilityValidationError,
    validate_capability_matrix,
)
from voice_agent.adapters.mock_adapters import mvp0_mock_adapter_capabilities
from voice_agent.adapters.profiles import (
    AdapterProfileValidationError,
    MVP3_REQUIRED_REAL_ADAPTER_TYPES,
    validate_mvp3_adapter_profile_set,
)
from voice_agent.runtime.assembly import RuntimeAdapterAssemblyConfig, assemble_runtime_adapters


SPEC_PATH = Path("docs/specs/adapter-capability-profiles.md")


def unsupported_capabilities(profile: dict[str, object]) -> tuple[str, ...]:
    return tuple(field for field in BOOLEAN_CAPABILITY_FIELDS if profile[field] is False)


def mvp3_profile(
    adapter_type: str,
    output_mode: str = "real",
    **overrides: object,
) -> dict[str, object]:
    profile: dict[str, object] = {
        "adapter_id": f"mvp3_{adapter_type}_{output_mode}",
        "adapter_type": adapter_type,
        "provider": "synthetic_provider",
        "model_name": f"synthetic_{adapter_type}_model",
        "deployment_mode": "remote_api",
        "endpoint": f"endpoint://synthetic/mvp3/{adapter_type}/{output_mode}",
        "health_status": "configured",
        "capability_version": "mvp3.profile.v1",
        "latency_class": "profile_contract",
        "error_model": "error-model://synthetic/mvp3/profile",
        "timeout_policy": "timeout-policy://synthetic/mvp3/profile",
        "retry_policy": "retry-policy://synthetic/mvp3/profile",
        "output_mode": output_mode,
        "config_ref": f"config://synthetic/mvp3/{adapter_type}/{output_mode}",
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
        "max_audio_seconds": None,
        "max_context_tokens": 4096,
        "max_output_tokens": 1024,
        "expected_first_token_latency_ms": 600,
        "expected_first_audio_latency_ms": None,
        "mocked": False,
        "mock_profile_ref": "",
        "target_architecture_validation": True,
    }
    if adapter_type == "asr":
        profile.update(
            supports_audio_input=True,
            supports_structured_json=True,
            max_audio_seconds=30,
            max_output_tokens=256,
        )
    elif adapter_type in {"thinker", "slow_llm"}:
        profile.update(supports_structured_json=True)
    elif adapter_type == "tts":
        profile.update(
            supports_audio_output=True,
            supports_tts=True,
            expected_first_audio_latency_ms=700,
        )
    profile.update(overrides)
    profile["unsupported_capabilities"] = unsupported_capabilities(profile)
    return profile


def real_profiles() -> tuple[dict[str, object], ...]:
    return tuple(mvp3_profile(adapter_type) for adapter_type in MVP3_REQUIRED_REAL_ADAPTER_TYPES)


def test_adapter_profile_spec_exists_and_names_required_contracts() -> None:
    assert SPEC_PATH.exists()
    content = SPEC_PATH.read_text(encoding="utf-8")

    for required_text in (
        "ASR",
        "Thinker",
        "Slow LLM",
        "TTS",
        "validate_mvp3_adapter_profile_set",
        "assemble_runtime_adapters",
        "fallback",
        "degraded",
        "credential",
    ):
        assert required_text in content


def test_provider_agnostic_real_profiles_validate_against_existing_gates() -> None:
    profiles = real_profiles()

    matrices = tuple(validate_capability_matrix(profile) for profile in profiles)
    validated = validate_mvp3_adapter_profile_set(matrices)
    assembly = assemble_runtime_adapters(
        RuntimeAdapterAssemblyConfig(
            stage="mvp3",
            capability_snapshot_ref="capability://synthetic/mvp3/profile-spec",
            capability_version="mvp3.profile.v1",
        ),
        validated,
    )

    assert [matrix["adapter_type"] for matrix in validated] == list(MVP3_REQUIRED_REAL_ADAPTER_TYPES)
    assert assembly.capability_snapshot["adapter_types"] == ["asr", "thinker", "slow_llm", "tts"]
    assert assembly.capability_snapshot["deployment_modes"] == [
        "remote_api",
        "remote_api",
        "remote_api",
        "remote_api",
    ]
    assert assembly.capability_snapshot["output_modes"] == ["real", "real", "real", "real"]
    assert assembly.capability_snapshot["capability_version"] == "mvp3.profile.v1"


def test_fallback_and_degraded_profiles_are_explicit_but_do_not_satisfy_real_readiness() -> None:
    fallback = mvp3_profile("slow_llm", output_mode="fallback", provider="synthetic_fallback")
    degraded = mvp3_profile(
        "tts",
        output_mode="degraded",
        supports_tts_truncate=False,
        provider="synthetic_degraded",
    )

    assert validate_capability_matrix(fallback)["output_mode"] == "fallback"
    assert validate_capability_matrix(degraded)["output_mode"] == "degraded"

    with pytest.raises(AdapterProfileValidationError, match="real adapter profile"):
        validate_mvp3_adapter_profile_set((fallback, degraded))


@pytest.mark.parametrize(
    ("unsafe_field", "unsafe_ref"),
    (
        ("endpoint", "https://provider.example.test/v1?api_key=sk-synthetic"),
        ("config_ref", "config://synthetic/mvp3/asr?token=synthetic"),
    ),
)
def test_profile_examples_fail_closed_for_credential_like_refs(
    unsafe_field: str,
    unsafe_ref: str,
) -> None:
    unsafe = deepcopy(mvp3_profile("asr"))
    unsafe[unsafe_field] = unsafe_ref

    with pytest.raises(CapabilityValidationError, match="credential"):
        validate_capability_matrix(unsafe)


def test_missing_required_capabilities_fail_closed() -> None:
    missing_required = deepcopy(mvp3_profile("slow_llm"))
    missing_required["supports_structured_json"] = False
    missing_required["unsupported_capabilities"] = unsupported_capabilities(missing_required)

    with pytest.raises(AdapterProfileValidationError, match="supports_structured_json"):
        validate_mvp3_adapter_profile_set((*real_profiles()[:2], missing_required, real_profiles()[3]))


def test_mock_only_profiles_remain_outside_mvp3_real_readiness() -> None:
    with pytest.raises(AdapterProfileValidationError, match="real adapter profile"):
        validate_mvp3_adapter_profile_set(mvp0_mock_adapter_capabilities())
