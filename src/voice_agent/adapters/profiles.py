from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
import hashlib
import json
from typing import Any

from voice_agent.adapters.capabilities import (
    AdapterCapability,
    CapabilityValidationError,
    CREDENTIAL_LIKE_REF_PATTERN,
    validate_capability_matrix,
)


class AdapterProfileValidationError(ValueError):
    pass


MVP3_REQUIRED_REAL_ADAPTER_TYPES = ("asr", "thinker", "slow_llm", "tts")
MVP3_MINIMUM_REQUIRED_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "asr": ("supports_audio_input", "supports_structured_json"),
    "thinker": ("supports_structured_json",),
    "slow_llm": ("supports_structured_json",),
    "tts": ("supports_audio_output", "supports_tts"),
}


def validate_adapter_profile_set(
    profiles: Iterable[AdapterCapability | Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    matrices = tuple(_normalized_matrix(profile) for profile in profiles)
    if not matrices:
        raise AdapterProfileValidationError("adapter profile set must not be empty")
    _validate_unique_adapter_ids(matrices)
    return matrices


def validate_mvp3_adapter_profile_set(
    profiles: Iterable[AdapterCapability | Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    matrices = validate_adapter_profile_set(profiles)

    for adapter_type in MVP3_REQUIRED_REAL_ADAPTER_TYPES:
        real_profiles = [
            matrix
            for matrix in matrices
            if matrix["adapter_type"] == adapter_type and matrix["output_mode"] == "real"
        ]
        if not real_profiles:
            raise AdapterProfileValidationError(
                f"MVP3 requires a real adapter profile for adapter_type={adapter_type!r}"
            )
        for matrix in real_profiles:
            _validate_mvp3_real_profile(matrix)

    return matrices


def validate_slice3b1_adapter_profile_set(
    profiles: Iterable[AdapterCapability | Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    matrices = validate_adapter_profile_set(profiles)
    required_types = {
        "duplex_model",
        "asr",
        "route_evidence",
        "fast_interaction",
    }
    present_types = {str(matrix["adapter_type"]) for matrix in matrices}
    if not required_types <= present_types:
        raise AdapterProfileValidationError(
            f"Slice 3B.1 missing adapter types: {sorted(required_types - present_types)}"
        )
    for adapter_type in required_types:
        if sum(matrix["adapter_type"] == adapter_type for matrix in matrices) != 1:
            raise AdapterProfileValidationError(
                f"Slice 3B.1 requires exactly one {adapter_type} profile"
            )
    for matrix in matrices:
        if matrix["output_mode"] != "mock":
            raise AdapterProfileValidationError(
                "Slice 3B.1 profiles must use output_mode=mock"
            )
        if matrix["provider_free_test_support"] is not True:
            raise AdapterProfileValidationError(
                "Slice 3B.1 profiles require provider_free_test_support=true"
            )
        if matrix["real_live_support"] is not False:
            raise AdapterProfileValidationError(
                "Slice 3B.1 profiles require real_live_support=false"
            )
    qwen = next(matrix for matrix in matrices if matrix["adapter_type"] == "duplex_model")
    if qwen["supports_provider_native_audio_release"] is not False:
        raise AdapterProfileValidationError(
            "Slice 3B.1 native provider audio release must remain disabled"
        )
    return tuple(
        sorted(
            matrices,
            key=lambda matrix: (str(matrix["adapter_type"]), str(matrix["adapter_id"])),
        )
    )


def capability_matrix_digest(matrices: Iterable[Mapping[str, Any]]) -> str:
    canonical_matrices = sorted(
        (deepcopy(dict(matrix)) for matrix in matrices),
        key=lambda matrix: (str(matrix["adapter_type"]), str(matrix["adapter_id"])),
    )
    encoded = json.dumps(
        canonical_matrices,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def build_capability_snapshot(
    matrices: Iterable[Mapping[str, Any]],
    *,
    capability_snapshot_ref: str,
    capability_version: str,
) -> dict[str, Any]:
    normalized = tuple(deepcopy(dict(matrix)) for matrix in matrices)
    if not capability_snapshot_ref:
        raise AdapterProfileValidationError("capability_snapshot_ref must be non-empty")
    if CREDENTIAL_LIKE_REF_PATTERN.search(capability_snapshot_ref):
        raise AdapterProfileValidationError(
            "capability_snapshot_ref must not contain credential-like content"
        )
    if not capability_version:
        raise AdapterProfileValidationError("capability_version must be non-empty")
    return {
        "capability_snapshot_ref": capability_snapshot_ref,
        "adapter_ids": [matrix["adapter_id"] for matrix in normalized],
        "adapter_types": [matrix["adapter_type"] for matrix in normalized],
        "deployment_modes": [matrix["deployment_mode"] for matrix in normalized],
        "output_modes": [matrix["output_mode"] for matrix in normalized],
        "capability_version": capability_version,
    }


def _normalized_matrix(profile: AdapterCapability | Mapping[str, Any]) -> dict[str, Any]:
    try:
        if isinstance(profile, AdapterCapability):
            return profile.to_dict()
        return validate_capability_matrix(profile)
    except CapabilityValidationError as exc:
        raise AdapterProfileValidationError(str(exc)) from exc


def _validate_unique_adapter_ids(matrices: tuple[dict[str, Any], ...]) -> None:
    adapter_ids = [str(matrix["adapter_id"]) for matrix in matrices]
    duplicates = sorted({adapter_id for adapter_id in adapter_ids if adapter_ids.count(adapter_id) > 1})
    if duplicates:
        raise AdapterProfileValidationError(f"Duplicate adapter_id values in profile set: {duplicates}")


def _validate_mvp3_real_profile(matrix: Mapping[str, Any]) -> None:
    adapter_type = str(matrix["adapter_type"])
    if str(matrix["provider"]).lower() == "mock":
        raise AdapterProfileValidationError(f"MVP3 real adapter profile must not use mock provider: {adapter_type}")
    if str(matrix["deployment_mode"]).lower() == "mock":
        raise AdapterProfileValidationError(f"MVP3 real adapter profile must not use mock deployment: {adapter_type}")
    if str(matrix["endpoint"]).startswith("mock://"):
        raise AdapterProfileValidationError(f"MVP3 real adapter profile must not use mock endpoint: {adapter_type}")
    if matrix.get("mocked") is not False:
        raise AdapterProfileValidationError(f"MVP3 real adapter profile must declare mocked=false: {adapter_type}")
    if matrix.get("mock_profile_ref") not in ("", None):
        raise AdapterProfileValidationError(f"MVP3 real adapter profile must not use mock_profile_ref: {adapter_type}")
    if matrix.get("target_architecture_validation") is not True:
        raise AdapterProfileValidationError(
            f"MVP3 real adapter profile requires target_architecture_validation=true: {adapter_type}"
        )

    required_capabilities = MVP3_MINIMUM_REQUIRED_CAPABILITIES[adapter_type]
    missing = [capability for capability in required_capabilities if matrix.get(capability) is not True]
    if missing:
        raise AdapterProfileValidationError(
            f"MVP3 {adapter_type!r} real adapter profile missing required capability: {missing[0]}"
        )
