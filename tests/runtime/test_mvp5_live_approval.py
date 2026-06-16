from __future__ import annotations

import json

import pytest

from voice_agent.runtime.mvp5_live_approval import (
    LiveProviderApprovalError,
    MVP5LiveProviderApprovalRequest,
    validate_mvp5_live_provider_approval,
)


def test_live_provider_gate_fails_closed_by_default() -> None:
    request = MVP5LiveProviderApprovalRequest()

    with pytest.raises(LiveProviderApprovalError, match="live_provider"):
        validate_mvp5_live_provider_approval(request, env={})


def test_live_provider_gate_requires_approval_packet_before_provider_calls() -> None:
    request = MVP5LiveProviderApprovalRequest(
        live_provider=True,
        credential_env_var_name="MVP5_TEST_PROVIDER_KEY",
        requested_provider_calls=1,
        max_provider_calls=2,
        allow_local_wav=True,
    )

    with pytest.raises(LiveProviderApprovalError, match="approval packet"):
        validate_mvp5_live_provider_approval(request, env={"MVP5_TEST_PROVIDER_KEY": "DUMMY_TEST_CREDENTIAL"})


def test_live_provider_gate_requires_credential_env_var_presence_without_returning_secret_value() -> None:
    request = MVP5LiveProviderApprovalRequest(
        live_provider=True,
        approval_packet=_approval_packet(),
        credential_env_var_name="MVP5_TEST_PROVIDER_KEY",
        requested_provider_calls=1,
        max_provider_calls=2,
        allow_local_wav=True,
    )

    with pytest.raises(LiveProviderApprovalError) as captured:
        validate_mvp5_live_provider_approval(request, env={})

    assert "MVP5_TEST_PROVIDER_KEY" in str(captured.value)
    assert "DUMMY_TEST_CREDENTIAL" not in repr(captured.value)


def test_live_provider_gate_allows_only_safe_metadata_after_explicit_opt_in() -> None:
    request = MVP5LiveProviderApprovalRequest(
        live_provider=True,
        approval_packet=_approval_packet(),
        credential_env_var_name="MVP5_TEST_PROVIDER_KEY",
        requested_provider_calls=2,
        max_provider_calls=2,
        timeout_ms=30_000,
        allow_local_wav=True,
        provider_adapter_ids=("mvp5_asr_adapter", "mvp5_thinker_adapter"),
        safe_refs=("summary://mvp5/live-redacted-placeholder",),
    )

    grant = validate_mvp5_live_provider_approval(
        request,
        env={"MVP5_TEST_PROVIDER_KEY": "DUMMY_TEST_CREDENTIAL_THAT_MUST_NOT_LEAK"},
    )

    metadata = grant.to_metadata()
    rendered = json.dumps(metadata, sort_keys=True)
    assert metadata["live_provider_allowed"] is True
    assert metadata["credential_env_var_name"] == "MVP5_TEST_PROVIDER_KEY"
    assert metadata["credential_value_included"] is False
    assert metadata["metadata_only_output"] is True
    assert metadata["requested_provider_calls"] == 2
    assert metadata["max_provider_calls"] == 2
    assert metadata["timeout_ms"] == 30_000
    assert metadata["provider_adapter_ids"] == ["mvp5_asr_adapter", "mvp5_thinker_adapter"]
    assert "DUMMY_TEST_CREDENTIAL_THAT_MUST_NOT_LEAK" not in rendered
    assert "DUMMY_TEST_CREDENTIAL_THAT_MUST_NOT_LEAK" not in repr(grant)


def test_live_provider_gate_rejects_request_budget_overflow_before_provider_calls() -> None:
    request = MVP5LiveProviderApprovalRequest(
        live_provider=True,
        approval_packet=_approval_packet(max_provider_calls=2),
        credential_env_var_name="MVP5_TEST_PROVIDER_KEY",
        requested_provider_calls=3,
        max_provider_calls=2,
        allow_local_wav=True,
    )

    with pytest.raises(LiveProviderApprovalError, match="request budget"):
        validate_mvp5_live_provider_approval(request, env={"MVP5_TEST_PROVIDER_KEY": "DUMMY_TEST_CREDENTIAL"})


def test_live_provider_gate_rejects_unsafe_refs_and_invalid_credential_names() -> None:
    request = MVP5LiveProviderApprovalRequest(
        live_provider=True,
        approval_packet=_approval_packet(),
        credential_env_var_name="MVP5_TEST_PROVIDER_KEY",
        requested_provider_calls=1,
        max_provider_calls=2,
        allow_local_wav=True,
        safe_refs=("file://redacted-local-wav",),
    )

    with pytest.raises(LiveProviderApprovalError, match="unsafe ref"):
        validate_mvp5_live_provider_approval(request, env={"MVP5_TEST_PROVIDER_KEY": "DUMMY_TEST_CREDENTIAL"})

    request = MVP5LiveProviderApprovalRequest(
        live_provider=True,
        approval_packet=_approval_packet(),
        credential_env_var_name="MVP5_TEST_PROVIDER_KEY=DUMMY_TEST_CREDENTIAL",
        requested_provider_calls=1,
        max_provider_calls=2,
        allow_local_wav=True,
    )

    with pytest.raises(LiveProviderApprovalError, match="credential env var name"):
        validate_mvp5_live_provider_approval(
            request,
            env={"MVP5_TEST_PROVIDER_KEY=DUMMY_TEST_CREDENTIAL": "DUMMY_TEST_CREDENTIAL"},
        )


def test_live_provider_gate_rejects_approval_packet_that_weakens_safety_policy() -> None:
    weakened_packet = _approval_packet()
    weakened_packet["metadata_only_output"] = False

    request = MVP5LiveProviderApprovalRequest(
        live_provider=True,
        approval_packet=weakened_packet,
        credential_env_var_name="MVP5_TEST_PROVIDER_KEY",
        requested_provider_calls=1,
        max_provider_calls=2,
        allow_local_wav=True,
    )

    with pytest.raises(LiveProviderApprovalError, match="metadata-only"):
        validate_mvp5_live_provider_approval(request, env={"MVP5_TEST_PROVIDER_KEY": "DUMMY_TEST_CREDENTIAL"})


def _approval_packet(
    *,
    credential_env_var_name: str = "MVP5_TEST_PROVIDER_KEY",
    max_provider_calls: int = 2,
) -> dict[str, object]:
    return {
        "approval_id": "mvp5-live-eval-template",
        "live_provider_opt_in": True,
        "local_wav_opt_in": True,
        "metadata_only_output": True,
        "replay_reruns_provider": False,
        "provider_adapter_ids": ["mvp5_asr_adapter", "mvp5_thinker_adapter"],
        "credential_env_var_name": credential_env_var_name,
        "max_provider_calls": max_provider_calls,
        "timeout_ms": 30_000,
        "safe_output_ref": "summary://mvp5/live-redacted-placeholder",
    }
