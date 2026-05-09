from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass
import re
from typing import Any


class CapabilityValidationError(ValueError):
    pass


OUTPUT_MODES = frozenset({"real", "mock", "fallback", "degraded"})

REQUIRED_IDENTITY_FIELDS = (
    "adapter_id",
    "adapter_type",
    "provider",
    "model_name",
    "deployment_mode",
    "endpoint",
    "health_status",
    "capability_version",
    "latency_class",
    "error_model",
    "timeout_policy",
    "retry_policy",
    "output_mode",
    "config_ref",
)

BOOLEAN_CAPABILITY_FIELDS = (
    "supports_streaming_input",
    "supports_streaming_output",
    "supports_audio_input",
    "supports_audio_output",
    "supports_audio_timestamps",
    "supports_structured_json",
    "supports_tool_calling",
    "supports_cancellation",
    "supports_emotion",
    "supports_audio_caption",
    "supports_tts",
    "supports_tts_truncate",
    "supports_tts_pause_resume",
    "supports_semantic_close",
    "supports_assistant_directedness",
)

NUMERIC_CAPABILITY_FIELDS = (
    "max_audio_seconds",
    "max_context_tokens",
    "max_output_tokens",
    "expected_first_token_latency_ms",
    "expected_first_audio_latency_ms",
)

REQUIRED_CAPABILITY_FIELDS = (
    *BOOLEAN_CAPABILITY_FIELDS,
    "latency_class",
    *NUMERIC_CAPABILITY_FIELDS,
)
MOCK_SPECIFIC_FIELDS = (
    "mocked",
    "mock_profile_ref",
    "target_architecture_validation",
    "unsupported_capabilities",
)
ALLOWED_CAPABILITY_FIELDS = frozenset(
    (
        *REQUIRED_IDENTITY_FIELDS,
        *BOOLEAN_CAPABILITY_FIELDS,
        *NUMERIC_CAPABILITY_FIELDS,
        *MOCK_SPECIFIC_FIELDS,
    )
)

CREDENTIAL_LIKE_REF_PATTERN = re.compile(
    r"(sk-[A-Za-z0-9_-]+|Bearer\s+\S+|api[_-]?key=|authorization=|credential=|token=|password=)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class AdapterCapability:
    adapter_id: str
    adapter_type: str
    provider: str
    model_name: str
    deployment_mode: str
    endpoint: str
    health_status: str
    capability_version: str
    latency_class: str
    error_model: str
    timeout_policy: str
    retry_policy: str
    output_mode: str
    config_ref: str
    supports_streaming_input: bool
    supports_streaming_output: bool
    supports_audio_input: bool
    supports_audio_output: bool
    supports_audio_timestamps: bool
    supports_structured_json: bool
    supports_tool_calling: bool
    supports_cancellation: bool
    supports_emotion: bool
    supports_audio_caption: bool
    supports_tts: bool
    supports_tts_truncate: bool
    supports_tts_pause_resume: bool
    supports_semantic_close: bool
    supports_assistant_directedness: bool
    max_audio_seconds: int | None
    max_context_tokens: int | None
    max_output_tokens: int | None
    expected_first_token_latency_ms: int | None
    expected_first_audio_latency_ms: int | None
    mocked: bool
    mock_profile_ref: str
    target_architecture_validation: bool
    unsupported_capabilities: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return validate_capability_matrix(asdict(self))


def validate_capability_matrix(matrix: Mapping[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(dict(matrix))

    unknown_fields = set(normalized) - ALLOWED_CAPABILITY_FIELDS
    if unknown_fields:
        raise CapabilityValidationError(f"Unknown capability matrix fields: {sorted(unknown_fields)}")

    for field in REQUIRED_IDENTITY_FIELDS:
        _require_non_empty_string(normalized, field)
    for field in BOOLEAN_CAPABILITY_FIELDS:
        _require_bool(normalized, field)
    for field in NUMERIC_CAPABILITY_FIELDS:
        _require_optional_non_negative_int(normalized, field)

    if normalized["output_mode"] not in OUTPUT_MODES:
        raise CapabilityValidationError(f"Unsupported output_mode: {normalized['output_mode']!r}")

    _validate_credential_safe_refs(normalized)
    _validate_mock_fields(normalized)
    _validate_unsupported_capabilities(normalized)

    return normalized


def _require_non_empty_string(matrix: Mapping[str, Any], field: str) -> None:
    value = matrix.get(field)
    if not isinstance(value, str) or value == "":
        raise CapabilityValidationError(f"{field} must be a non-empty string")


def _require_bool(matrix: Mapping[str, Any], field: str) -> None:
    if field not in matrix or not isinstance(matrix[field], bool):
        raise CapabilityValidationError(f"{field} must be a boolean")


def _require_optional_non_negative_int(matrix: Mapping[str, Any], field: str) -> None:
    value = matrix.get(field)
    if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
        raise CapabilityValidationError(f"{field} must be a non-negative integer or null")


def _validate_credential_safe_refs(matrix: Mapping[str, Any]) -> None:
    for field in ("endpoint", "config_ref", "mock_profile_ref"):
        value = matrix.get(field)
        if isinstance(value, str) and CREDENTIAL_LIKE_REF_PATTERN.search(value):
            raise CapabilityValidationError(f"{field} must not contain credential-like content")


def _validate_mock_fields(matrix: Mapping[str, Any]) -> None:
    if matrix["output_mode"] != "mock":
        return
    if matrix.get("mocked") is not True:
        raise CapabilityValidationError("mock output_mode requires mocked=true")
    _require_non_empty_string(matrix, "mock_profile_ref")
    if not isinstance(matrix.get("target_architecture_validation"), bool):
        raise CapabilityValidationError("target_architecture_validation must be explicit for mocks")


def _validate_unsupported_capabilities(matrix: Mapping[str, Any]) -> None:
    unsupported = matrix.get("unsupported_capabilities")
    if not _is_string_sequence(unsupported):
        raise CapabilityValidationError("unsupported_capabilities must explicitly list unsupported fields")

    unsupported_set = set(unsupported)
    unknown = unsupported_set - set(BOOLEAN_CAPABILITY_FIELDS)
    if unknown:
        raise CapabilityValidationError(f"Unknown unsupported capabilities: {sorted(unknown)}")

    false_capabilities = {field for field in BOOLEAN_CAPABILITY_FIELDS if matrix[field] is False}
    missing = false_capabilities - unsupported_set
    if missing:
        raise CapabilityValidationError(f"Unsupported capabilities must be explicit: {sorted(missing)}")
    contradictions = {field for field in unsupported_set if matrix[field] is True}
    if contradictions:
        raise CapabilityValidationError(
            f"Unsupported capabilities contradict declared support: {sorted(contradictions)}"
        )


def _is_string_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and all(
        isinstance(item, str) for item in value
    )
