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

PROFILE_DESCRIPTOR_FIELDS = (
    "role_contract",
    "prompt_profile",
)

BASE_BOOLEAN_CAPABILITY_FIELDS = (
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

FAST_INTERACTION_BOOLEAN_CAPABILITY_FIELDS = (
    "supports_fast_interaction_output",
    "supports_route_hint",
    "supports_route_prelude",
    "supports_foreground_act",
    "supports_reply_candidate",
    "supports_reply_delta_streaming",
    "supports_final_fast_evidence",
    "supports_schema_validation",
    "supports_risk_tags",
    "supports_confidence",
    "supports_asr_text_fallback",
)

TIMING_BOOLEAN_CAPABILITY_FIELDS = (
    "supports_provider_stream_timing",
    "supports_ttft_observation",
)

ADR018_ROUTE_EVIDENCE_BOOLEAN_FIELDS = (
    "supports_route_schema",
    "supports_task_focus",
    "supports_foreground_act_hint",
    "supports_ack_kind",
    "supports_candidate_safety_schema",
    "supports_prohibited_claim_detection",
    "supports_strict_json_validation",
)

ADR018_ASR_BOOLEAN_FIELDS = (
    "supports_candidate_output_audio_shadow_verification",
)

ADR018_QWEN_SESSION_BOOLEAN_FIELDS = (
    "supports_smart_turn",
    "supports_streaming_asr",
    "supports_provider_response_cancellation",
    "supports_provider_item_create",
    "supports_provider_item_delete_ack",
    "supports_manual_response_while_idle",
    "supports_text_only_response_override",
    "supports_candidate_quarantine",
    "supports_provider_native_audio_release",
    "supports_provider_context_readiness",
    "supports_context_rebuild",
)

ADR018_SUPPORT_FACT_FIELDS = (
    "documentation_support",
    "provider_free_test_support",
    "real_live_support",
)

ADR018_BOOLEAN_CAPABILITY_FIELDS = (
    *ADR018_ROUTE_EVIDENCE_BOOLEAN_FIELDS,
    *ADR018_ASR_BOOLEAN_FIELDS,
    *ADR018_QWEN_SESSION_BOOLEAN_FIELDS,
    *ADR018_SUPPORT_FACT_FIELDS,
)

FAST_INTERACTION_OWNED_BOOLEAN_CAPABILITY_FIELDS = (
    "supports_fast_interaction_output",
    "supports_route_hint",
    "supports_route_prelude",
    "supports_foreground_act",
    "supports_reply_candidate",
    "supports_reply_delta_streaming",
    "supports_final_fast_evidence",
    "supports_risk_tags",
    "supports_confidence",
    "supports_asr_text_fallback",
)

BOOLEAN_CAPABILITY_FIELDS = (
    *BASE_BOOLEAN_CAPABILITY_FIELDS,
    *FAST_INTERACTION_BOOLEAN_CAPABILITY_FIELDS,
    *TIMING_BOOLEAN_CAPABILITY_FIELDS,
)
# Stable aliases for callers/tests that need the full canonical field order.
ALL_BOOLEAN_CAPABILITY_FIELDS = BOOLEAN_CAPABILITY_FIELDS
CANONICAL_BOOLEAN_CAPABILITY_FIELDS = (
    *BOOLEAN_CAPABILITY_FIELDS,
    *ADR018_BOOLEAN_CAPABILITY_FIELDS,
)

BASE_NUMERIC_CAPABILITY_FIELDS = (
    "max_audio_seconds",
    "max_context_tokens",
    "max_output_tokens",
    "expected_first_token_latency_ms",
    "expected_first_audio_latency_ms",
)

FAST_INTERACTION_NUMERIC_CAPABILITY_FIELDS = (
    "max_reply_candidate_tokens",
    "expected_first_candidate_latency_ms",
    "expected_final_gate_ready_latency_ms",
)

NUMERIC_CAPABILITY_FIELDS = (
    *BASE_NUMERIC_CAPABILITY_FIELDS,
    *FAST_INTERACTION_NUMERIC_CAPABILITY_FIELDS,
)
ALL_NUMERIC_CAPABILITY_FIELDS = NUMERIC_CAPABILITY_FIELDS

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
        "status",
        *PROFILE_DESCRIPTOR_FIELDS,
        *CANONICAL_BOOLEAN_CAPABILITY_FIELDS,
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
    role_contract: str
    prompt_profile: str
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
    supports_fast_interaction_output: bool
    supports_route_hint: bool
    supports_route_prelude: bool
    supports_foreground_act: bool
    supports_reply_candidate: bool
    supports_reply_delta_streaming: bool
    supports_final_fast_evidence: bool
    supports_schema_validation: bool
    supports_risk_tags: bool
    supports_confidence: bool
    supports_asr_text_fallback: bool
    supports_provider_stream_timing: bool
    supports_ttft_observation: bool
    max_audio_seconds: int | None
    max_context_tokens: int | None
    max_output_tokens: int | None
    expected_first_token_latency_ms: int | None
    expected_first_audio_latency_ms: int | None
    max_reply_candidate_tokens: int | None
    expected_first_candidate_latency_ms: int | None
    expected_final_gate_ready_latency_ms: int | None
    mocked: bool
    mock_profile_ref: str
    target_architecture_validation: bool
    unsupported_capabilities: tuple[str, ...]
    status: str = ""
    supports_route_schema: bool = False
    supports_task_focus: bool = False
    supports_foreground_act_hint: bool = False
    supports_ack_kind: bool = False
    supports_candidate_safety_schema: bool = False
    supports_prohibited_claim_detection: bool = False
    supports_strict_json_validation: bool = False
    supports_candidate_output_audio_shadow_verification: bool = False
    supports_smart_turn: bool = False
    supports_streaming_asr: bool = False
    supports_provider_response_cancellation: bool = False
    supports_provider_item_create: bool = False
    supports_provider_item_delete_ack: bool = False
    supports_manual_response_while_idle: bool = False
    supports_text_only_response_override: bool = False
    supports_candidate_quarantine: bool = False
    supports_provider_native_audio_release: bool = False
    supports_provider_context_readiness: bool = False
    supports_context_rebuild: bool = False
    documentation_support: bool = False
    provider_free_test_support: bool = False
    real_live_support: bool = False

    def to_dict(self) -> dict[str, Any]:
        return validate_capability_matrix(asdict(self))


def validate_capability_matrix(matrix: Mapping[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(dict(matrix))

    unknown_fields = set(normalized) - ALLOWED_CAPABILITY_FIELDS
    if unknown_fields:
        raise CapabilityValidationError(f"Unknown capability matrix fields: {sorted(unknown_fields)}")

    _normalize_adr018_fields(normalized)
    for field in REQUIRED_IDENTITY_FIELDS:
        _require_non_empty_string(normalized, field)
    if normalized["output_mode"] not in OUTPUT_MODES:
        raise CapabilityValidationError(f"Unsupported output_mode: {normalized['output_mode']!r}")
    if not normalized.get("status"):
        normalized["status"] = normalized["output_mode"]
    if normalized["status"] not in OUTPUT_MODES:
        raise CapabilityValidationError(f"Unsupported status: {normalized['status']!r}")
    _validate_profile_descriptors(normalized)
    for field in CANONICAL_BOOLEAN_CAPABILITY_FIELDS:
        _require_bool(normalized, field)
    for field in NUMERIC_CAPABILITY_FIELDS:
        _require_optional_non_negative_int(normalized, field)

    _validate_credential_safe_refs(normalized)
    _validate_mock_fields(normalized)
    _validate_fast_interaction_owned_fields(normalized)
    _validate_adr018_owned_fields(normalized)
    normalized["unsupported_capabilities"] = _canonical_unsupported_capabilities(normalized)

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


def _validate_profile_descriptors(matrix: dict[str, Any]) -> None:
    for field in PROFILE_DESCRIPTOR_FIELDS:
        value = matrix.get(field, "")
        if not isinstance(value, str):
            raise CapabilityValidationError(f"{field} must be a string")
        matrix[field] = value

    if matrix.get("adapter_type") == "fast_interaction":
        for field in PROFILE_DESCRIPTOR_FIELDS:
            _require_non_empty_string(matrix, field)


def _validate_fast_interaction_owned_fields(matrix: Mapping[str, Any]) -> None:
    adapter_type = matrix["adapter_type"]
    if adapter_type == "fast_interaction":
        return

    claimed = [
        field
        for field in FAST_INTERACTION_OWNED_BOOLEAN_CAPABILITY_FIELDS
        if matrix[field] is True
        and not (
            adapter_type == "route_evidence"
            and field in {"supports_risk_tags", "supports_confidence"}
        )
    ]
    if claimed:
        raise CapabilityValidationError(
            "Only adapter_type='fast_interaction' may claim Fast Interaction capabilities: "
            f"{claimed}"
        )


def _normalize_adr018_fields(matrix: dict[str, Any]) -> None:
    declares_adr018_field = any(
        field in matrix for field in ADR018_BOOLEAN_CAPABILITY_FIELDS
    )
    if declares_adr018_field:
        missing_support_facts = [
            field for field in ADR018_SUPPORT_FACT_FIELDS if field not in matrix
        ]
        if missing_support_facts:
            raise CapabilityValidationError(
                "ADR-018 profiles must explicitly declare all support facts: "
                f"{missing_support_facts}"
            )

    for field in ADR018_BOOLEAN_CAPABILITY_FIELDS:
        matrix.setdefault(field, False)


def _validate_adr018_owned_fields(matrix: Mapping[str, Any]) -> None:
    owned_fields_by_adapter_type = {
        "route_evidence": ADR018_ROUTE_EVIDENCE_BOOLEAN_FIELDS,
        "asr": ADR018_ASR_BOOLEAN_FIELDS,
        "duplex_model": ADR018_QWEN_SESSION_BOOLEAN_FIELDS,
    }
    adapter_type = str(matrix["adapter_type"])
    for owner, fields in owned_fields_by_adapter_type.items():
        if adapter_type == owner:
            continue
        claimed = [field for field in fields if matrix[field] is True]
        if claimed:
            raise CapabilityValidationError(
                f"Only adapter_type={owner!r} may claim ADR-018 capabilities: {claimed}"
            )


def _canonical_unsupported_capabilities(matrix: Mapping[str, Any]) -> tuple[str, ...]:
    unsupported = matrix.get("unsupported_capabilities")
    if not _is_string_sequence(unsupported):
        raise CapabilityValidationError("unsupported_capabilities must explicitly list unsupported fields")

    unsupported_set = set(unsupported)
    unknown = unsupported_set - set(CANONICAL_BOOLEAN_CAPABILITY_FIELDS)
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
    applicable_adr018_fields = _applicable_adr018_fields(matrix)
    return tuple(
        field
        for field in (*BOOLEAN_CAPABILITY_FIELDS, *applicable_adr018_fields)
        if matrix[field] is False
    )


def _applicable_adr018_fields(matrix: Mapping[str, Any]) -> tuple[str, ...]:
    if not any(matrix[field] is True for field in ADR018_BOOLEAN_CAPABILITY_FIELDS):
        return ()

    adapter_fields: tuple[str, ...]
    if matrix["adapter_type"] == "route_evidence":
        adapter_fields = ADR018_ROUTE_EVIDENCE_BOOLEAN_FIELDS
    elif matrix["adapter_type"] == "asr":
        adapter_fields = ADR018_ASR_BOOLEAN_FIELDS
    elif matrix["adapter_type"] == "duplex_model":
        adapter_fields = ADR018_QWEN_SESSION_BOOLEAN_FIELDS
    else:
        adapter_fields = ()
    return (*adapter_fields, *ADR018_SUPPORT_FACT_FIELDS)


def _is_string_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and all(
        isinstance(item, str) for item in value
    )
