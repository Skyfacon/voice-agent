from __future__ import annotations

import pytest

from qwen_slice3b1_support import SYNTHETIC_RELEASE_TOKEN_REF
from voice_agent.privacy.redaction import (
    PayloadBlockedError,
    is_safe_release_token_id,
    is_safe_release_token_ref,
    sanitize_event_payload,
)


SAFE_RELEASE_TOKEN_ID = "release_token_0123456789abcdef0123456789abcdef"


def test_safe_opaque_release_authority_survives_nested_sanitization() -> None:
    payload = {
        "binding": {
            "release_token_id": SAFE_RELEASE_TOKEN_ID,
            "release_token_ref": SYNTHETIC_RELEASE_TOKEN_REF,
        }
    }

    sanitized, redacted_fields = sanitize_event_payload(payload)

    assert sanitized == payload
    assert redacted_fields == []
    assert is_safe_release_token_id(SAFE_RELEASE_TOKEN_ID)
    assert is_safe_release_token_ref(SYNTHETIC_RELEASE_TOKEN_REF)


def test_local_release_ref_can_be_rejected_for_shareable_artifacts() -> None:
    local_ref = f"release-token://local/{SAFE_RELEASE_TOKEN_ID}"

    assert is_safe_release_token_ref(local_ref)
    assert not is_safe_release_token_ref(local_ref, allow_local=False)


@pytest.mark.parametrize(
    "unsafe_value",
    (
        "release_token_sk-secret",
        "release-token://synthetic/release_token_sk-secret",
        f"release-token://synthetic/{SAFE_RELEASE_TOKEN_ID}?token=secret",
        f"release-token://synthetic/{SAFE_RELEASE_TOKEN_ID}%3Ftoken%3Dsecret",
        f"release-token://synthetic/{SAFE_RELEASE_TOKEN_ID}%253Ftoken%253Dsecret",
        f"release-token://user:pass@synthetic/{SAFE_RELEASE_TOKEN_ID}",
        "release-token://synthetic/%2FUsers%2Fa123%2Fdiagnostics%2Fsecret",
    ),
)
def test_unsafe_release_authority_is_blocked_without_value_echo(
    unsafe_value: str,
) -> None:
    assert not is_safe_release_token_id(unsafe_value)
    assert not is_safe_release_token_ref(unsafe_value)

    key = (
        "release_token_id"
        if unsafe_value.startswith("release_token_")
        else "release_token_ref"
    )
    with pytest.raises(PayloadBlockedError) as exc_info:
        sanitize_event_payload({"outer": {key: unsafe_value}})

    assert unsafe_value not in str(exc_info.value)
    assert key in str(exc_info.value)


def test_other_token_like_fields_remain_redacted() -> None:
    sanitized, redacted_fields = sanitize_event_payload(
        {"provider_token": "caller-selected-value"}
    )

    assert sanitized["provider_token"] == "[REDACTED_SECRET]"
    assert redacted_fields == ["provider_token"]


@pytest.mark.parametrize(
    "unsafe_id",
    (
        "release_token_0123456789ABCDEF0123456789ABCDEF",
        "release_token_0123456789abcdef",
        "caller_selected_0123456789abcdef0123456789abcdef",
        "release_token_0123456789abcdef0123456789abcdef00",
    ),
)
def test_release_token_id_requires_exact_internal_fixed_width_shape(
    unsafe_id: str,
) -> None:
    assert not is_safe_release_token_id(unsafe_id)

    with pytest.raises(PayloadBlockedError) as exc_info:
        sanitize_event_payload({"release_token_id": unsafe_id})

    assert unsafe_id not in str(exc_info.value)
