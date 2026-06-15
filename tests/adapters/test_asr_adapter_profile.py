from __future__ import annotations

import http.client
import os
import socket
import urllib.request

import pytest

from tests.adapters.test_mvp3_adapter_profiles import valid_mvp3_real_profiles
from voice_agent.adapters.asr_profile import (
    AsrProfileValidationError,
    build_asr_capability_profile,
)
from voice_agent.adapters.capabilities import validate_capability_matrix
from voice_agent.adapters.profiles import validate_mvp3_adapter_profile_set


def test_provider_free_asr_profile_builds_safe_real_metadata_without_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocked_calls: list[object] = []

    def fail_if_called(*args: object, **kwargs: object) -> None:
        blocked_calls.append((args, kwargs))
        raise AssertionError("ASR profile builder must not probe providers or secrets")

    monkeypatch.setattr(socket, "create_connection", fail_if_called)
    monkeypatch.setattr(http.client.HTTPConnection, "connect", fail_if_called)
    monkeypatch.setattr(http.client.HTTPSConnection, "connect", fail_if_called)
    monkeypatch.setattr(urllib.request, "urlopen", fail_if_called)
    monkeypatch.setattr(os, "getenv", fail_if_called)

    profile = build_asr_capability_profile(
        adapter_id="mvp3_asr_provider_free",
        provider="synthetic_provider",
        model_name="synthetic_asr_model",
        endpoint_ref="endpoint://synthetic/mvp3/asr/provider-free",
        config_ref="config://synthetic/mvp3/asr/provider-free",
        output_mode="real",
        supports_audio_timestamps=True,
        supports_streaming_output=True,
    )

    matrix = profile.to_dict()
    assert matrix == validate_capability_matrix(matrix)
    assert matrix["adapter_type"] == "asr"
    assert matrix["output_mode"] == "real"
    assert matrix["supports_audio_input"] is True
    assert matrix["supports_structured_json"] is True
    assert matrix["supports_tool_calling"] is False
    assert matrix["supports_tts"] is False
    assert matrix["supports_semantic_close"] is False
    assert matrix["supports_assistant_directedness"] is False
    assert "supports_tool_calling" in matrix["unsupported_capabilities"]
    assert blocked_calls == []


@pytest.mark.parametrize("output_mode", ("real", "fallback", "degraded"))
def test_asr_profile_builder_accepts_explicit_real_fallback_and_degraded_modes(
    output_mode: str,
) -> None:
    profile = build_asr_capability_profile(
        adapter_id=f"mvp3_asr_{output_mode}",
        provider="synthetic_provider",
        model_name="synthetic_asr_model",
        endpoint_ref=f"endpoint://synthetic/mvp3/asr/{output_mode}",
        config_ref=f"config://synthetic/mvp3/asr/{output_mode}",
        output_mode=output_mode,
    )

    assert profile.to_dict()["output_mode"] == output_mode


@pytest.mark.parametrize(
    ("field", "unsafe_ref"),
    (
        ("endpoint_ref", "https://provider.example.test/v1?api_key=sk-synthetic"),
        ("config_ref", "config://synthetic/mvp3/asr?token=synthetic"),
    ),
)
def test_asr_profile_builder_fails_closed_for_credential_like_refs(
    field: str,
    unsafe_ref: str,
) -> None:
    kwargs = {
        "adapter_id": "mvp3_asr_unsafe",
        "provider": "synthetic_provider",
        "model_name": "synthetic_asr_model",
        "endpoint_ref": "endpoint://synthetic/mvp3/asr/safe",
        "config_ref": "config://synthetic/mvp3/asr/safe",
        "output_mode": "real",
    }
    kwargs[field] = unsafe_ref

    with pytest.raises(AsrProfileValidationError, match="credential"):
        build_asr_capability_profile(**kwargs)


def test_asr_profile_builder_rejects_unsupported_capability_mismatch() -> None:
    with pytest.raises(AsrProfileValidationError, match="Unsupported capabilities"):
        build_asr_capability_profile(
            adapter_id="mvp3_asr_bad_unsupported",
            provider="synthetic_provider",
            model_name="synthetic_asr_model",
            endpoint_ref="endpoint://synthetic/mvp3/asr/bad-unsupported",
            config_ref="config://synthetic/mvp3/asr/bad-unsupported",
            output_mode="real",
            supports_streaming_output=False,
            unsupported_capabilities=("supports_streaming_input",),
        )


def test_asr_profile_builder_rejects_mock_only_real_readiness() -> None:
    with pytest.raises(AsrProfileValidationError, match="mock"):
        build_asr_capability_profile(
            adapter_id="mvp3_asr_mock_labeled_real",
            provider="mock",
            model_name="synthetic_asr_mock",
            deployment_mode="mock",
            endpoint_ref="mock://synthetic/mvp3/asr",
            config_ref="config://synthetic/mvp3/asr/mock",
            output_mode="real",
            mocked=True,
            mock_profile_ref="mock-profile://synthetic/mvp3/asr",
        )


def test_asr_profile_builder_output_can_satisfy_existing_mvp3_profile_set_gate() -> None:
    asr_profile = build_asr_capability_profile(
        adapter_id="mvp3_asr_provider_free_gate",
        provider="synthetic_provider",
        model_name="synthetic_asr_model",
        endpoint_ref="endpoint://synthetic/mvp3/asr/gate",
        config_ref="config://synthetic/mvp3/asr/gate",
        output_mode="real",
    )
    other_profiles = tuple(
        profile
        for profile in valid_mvp3_real_profiles()
        if profile.adapter_type != "asr"
    )

    matrices = validate_mvp3_adapter_profile_set((asr_profile, *other_profiles))

    assert [matrix["adapter_type"] for matrix in matrices] == [
        "asr",
        "thinker",
        "slow_llm",
        "tts",
    ]
