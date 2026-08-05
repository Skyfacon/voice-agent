from __future__ import annotations

import json

import pytest

from experiments.qwen_realtime_fast_slow_web.capability_profile import (
    fake_capability_profile,
    fake_shadow_capability_profile,
    qwen_shadow_capability_profile,
    qwen_voice_capability_profile,
)
from experiments.qwen_realtime_fast_slow_web.provider_context import (
    CredentialHandle,
    MODEL_NAME,
    ProviderConfigurationError,
    workspace_id_from_safe_base_url,
)


API_KEY_SENTINEL = "PRIVATE_DASHSCOPE_CREDENTIAL_SENTINEL"
WORKSPACE_SENTINEL = "ws-test-safe-123"


def test_credential_handle_resolves_workspace_in_required_precedence_order() -> None:
    environment = {
        "DASHSCOPE_API_KEY": API_KEY_SENTINEL,
        "QWEN_REALTIME_WORKSPACE_ID": "ws-from-environment",
        "QWEN_REALTIME_BASE_URL": (
            "https://ws-from-environment-url.cn-beijing.maas.aliyuncs.com/"
            "compatible-mode/v1"
        ),
    }

    from_environment = CredentialHandle.resolve(
        environment,
        safe_base_url=(
            "https://ws-from-explicit-url.cn-beijing.maas.aliyuncs.com/"
            "compatible-mode/v1"
        ),
        explicit_workspace_id="ws-from-cli",
        verified_workspace_id="ws-from-verified-fallback",
    )
    from_base_url = CredentialHandle.resolve(
        {"DASHSCOPE_API_KEY": API_KEY_SENTINEL},
        safe_base_url=(
            "https://ws-from-explicit-url.cn-beijing.maas.aliyuncs.com/"
            "compatible-mode/v1"
        ),
        explicit_workspace_id="ws-from-cli",
        verified_workspace_id="ws-from-verified-fallback",
    )
    from_cli = CredentialHandle.resolve(
        {"DASHSCOPE_API_KEY": API_KEY_SENTINEL},
        explicit_workspace_id="ws-from-cli",
        verified_workspace_id="ws-from-verified-fallback",
    )
    from_fallback = CredentialHandle.resolve(
        {"DASHSCOPE_API_KEY": API_KEY_SENTINEL},
        verified_workspace_id="ws-from-verified-fallback",
    )

    assert from_environment.to_metadata()["workspace_resolution_source"] == (
        "environment"
    )
    assert from_base_url.to_metadata()["workspace_resolution_source"] == (
        "safe_base_url"
    )
    assert from_cli.to_metadata()["workspace_resolution_source"] == "explicit_cli"
    assert from_fallback.to_metadata()["workspace_resolution_source"] == (
        "verified_fallback"
    )
    assert "ws-from-environment.cn-beijing" in from_environment._endpoint()
    assert "ws-from-explicit-url.cn-beijing" in from_base_url._endpoint()
    assert "ws-from-cli.cn-beijing" in from_cli._endpoint()
    assert "ws-from-verified-fallback.cn-beijing" in from_fallback._endpoint()


@pytest.mark.parametrize(
    "url",
    (
        (
            "https://ws-safe.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
        ),
        (
            "wss://ws-safe.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime"
            "?model=qwen-audio-3.0-realtime-plus"
        ),
    ),
)
def test_workspace_id_is_extracted_only_from_expected_beijing_host(url: str) -> None:
    assert workspace_id_from_safe_base_url(url) == "ws-safe"


@pytest.mark.parametrize(
    "url",
    (
        "http://ws-safe.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        "https://ws-safe.cn-shanghai.maas.aliyuncs.com/compatible-mode/v1",
        "https://nested.ws-safe.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        "https://user:pass@ws-safe.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        "https://ws-safe.cn-beijing.maas.aliyuncs.com:443/compatible-mode/v1",
        "https://evil.example/compatible-mode/v1",
        "not-a-url",
    ),
)
def test_workspace_base_url_parser_rejects_unsafe_hosts(url: str) -> None:
    with pytest.raises(
        ProviderConfigurationError, match="invalid_qwen_realtime_base_url"
    ):
        workspace_id_from_safe_base_url(url)


def test_credential_handle_fails_closed_when_required_values_are_missing() -> None:
    with pytest.raises(
        ProviderConfigurationError, match="missing_dashscope_api_key"
    ):
        CredentialHandle.resolve(
            {"QWEN_REALTIME_WORKSPACE_ID": WORKSPACE_SENTINEL}
        )
    with pytest.raises(
        ProviderConfigurationError, match="missing_qwen_realtime_workspace_id"
    ):
        CredentialHandle.resolve({"DASHSCOPE_API_KEY": API_KEY_SENTINEL})
    with pytest.raises(
        ProviderConfigurationError, match="invalid_qwen_realtime_workspace_id"
    ):
        CredentialHandle(API_KEY_SENTINEL, "unsafe.workspace.example")


def test_credential_handle_is_opaque_and_serializable_metadata_is_secret_free() -> None:
    handle = CredentialHandle(API_KEY_SENTINEL, WORKSPACE_SENTINEL)
    rendered = repr(handle)
    metadata = handle.to_metadata()
    serialized = json.dumps(metadata, sort_keys=True)

    assert rendered == (
        "CredentialHandle(api_key=<redacted>, workspace_id=<redacted>, "
        "workspace_source='explicit')"
    )
    assert API_KEY_SENTINEL not in rendered + serialized
    assert WORKSPACE_SENTINEL not in rendered + serialized
    assert metadata["api_key_configured"] is True
    assert metadata["workspace_id_configured"] is True
    assert metadata["workspace_ref"].startswith("workspace-")
    assert metadata["endpoint_ref"] == "aliyun-bailian/cn-beijing/realtime"
    assert metadata["model_name"] == MODEL_NAME
    assert handle._endpoint() == (
        "wss://ws-test-safe-123.cn-beijing.maas.aliyuncs.com/"
        "api-ws/v1/realtime?model=qwen-audio-3.0-realtime-plus"
    )
    assert handle._authorization_headers() == {
        "Authorization": f"Bearer {API_KEY_SENTINEL}"
    }
    with pytest.raises(TypeError):
        json.dumps(handle)
    with pytest.raises(TypeError):
        vars(handle)


def test_slice2_capability_matrix_is_explicit_and_does_not_overclaim() -> None:
    fake_enforced = fake_capability_profile()
    fake_shadow = fake_shadow_capability_profile()
    qwen_voice = qwen_voice_capability_profile()
    qwen_shadow = qwen_shadow_capability_profile()

    assert fake_enforced.routing_mode == "enforced"
    assert fake_enforced.shadow_control_mode == "none"
    assert fake_enforced.output_mode == "mock"
    assert fake_enforced.supports_real_provider is False

    assert fake_shadow.routing_mode == "shadow"
    assert fake_shadow.shadow_control_mode == "dual_session_shadow"
    assert fake_shadow.output_mode == "mock"
    assert fake_shadow.supports_real_provider is False
    assert fake_shadow.supports_function_calling is True

    assert qwen_voice.routing_mode == "shadow"
    assert qwen_voice.shadow_control_mode == "dual_session_shadow"
    assert qwen_voice.output_mode == "not_executed"
    assert qwen_voice.health_status == "not_executed"
    assert qwen_voice.verification_status == "not_executed"
    assert qwen_voice.protocol_declared is True
    assert qwen_voice.implementation_supported is True
    assert qwen_voice.provider_free_verified is True
    assert qwen_voice.real_live_verified is False
    assert qwen_voice.asr_item_correlation_verification == "not_executed"
    assert qwen_voice.response_cancel_verification == "not_executed"
    assert qwen_voice.supports_real_provider is True
    assert qwen_voice.supports_function_calling is False
    assert qwen_voice.supports_direct_provider_audio_before_gate is False
    assert qwen_voice.route_proposal_authority == "none"

    assert qwen_shadow.routing_mode == "shadow"
    assert qwen_shadow.shadow_control_mode == "dual_session_shadow"
    assert qwen_shadow.output_mode == "not_executed"
    assert qwen_shadow.health_status == "not_executed"
    assert qwen_shadow.verification_status == "not_executed"
    assert qwen_shadow.real_live_verified is False
    assert qwen_shadow.supports_real_provider is True
    assert qwen_shadow.supports_text_only_output is True
    assert qwen_shadow.supports_function_calling is True
    assert qwen_shadow.forced_route_function_call == (
        "unsupported_or_unverified"
    )
    assert qwen_shadow.function_call_schema_validation == (
        "strict_local_fail_closed"
    )
    assert qwen_shadow.route_proposal_authority == (
        "non_authoritative_provider_proposal"
    )
    assert qwen_shadow.supports_direct_provider_audio_before_gate is False
    assert qwen_shadow.output_audio_format == "none"
    assert qwen_shadow.persistence_enabled is False


@pytest.mark.parametrize(
    "factory",
    (qwen_voice_capability_profile, qwen_shadow_capability_profile),
)
def test_real_profiles_label_degraded_and_disconnected_output_distinctly(factory) -> None:
    assert factory(health_status="ready").output_mode == "real"
    assert factory(health_status="degraded").output_mode == "degraded"
    assert factory(health_status="disconnected").output_mode == "degraded"
    assert factory(health_status="unavailable").output_mode == "degraded"


def test_capability_metadata_has_no_credential_or_authorization_surface() -> None:
    serialized = json.dumps(
        {
            "fake": fake_capability_profile().to_metadata(),
            "fake_shadow": fake_shadow_capability_profile().to_metadata(),
            "qwen_voice": qwen_voice_capability_profile().to_metadata(),
            "qwen_shadow": qwen_shadow_capability_profile().to_metadata(),
        },
        sort_keys=True,
    ).lower()

    for marker in (
        "authorization",
        "api_key",
        "credential",
        "bearer",
        API_KEY_SENTINEL.lower(),
        WORKSPACE_SENTINEL.lower(),
    ):
        assert marker not in serialized
