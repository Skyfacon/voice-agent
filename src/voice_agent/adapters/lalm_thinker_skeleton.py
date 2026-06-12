from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from typing import Any
from urllib.parse import unquote

from voice_agent.adapters.capabilities import CREDENTIAL_LIKE_REF_PATTERN
from voice_agent.adapters.lalm_thinker_binding import (
    LALM_THINKER_CANDIDATE_SCHEMA_VERSION,
    LALMThinkerRequestBinding,
)


class LALMThinkerCandidateParseError(ValueError):
    def __init__(self, category: str) -> None:
        self.category = category
        self.failure_ref = _failure_ref(category)
        super().__init__(
            "lalm_thinker_candidate_parse_failed "
            f"category={self.category} failure_ref={self.failure_ref}"
        )


class LALMThinkerCandidateValidationError(ValueError):
    def __init__(self, category: str, failure_reasons: Sequence[str]) -> None:
        self.category = category
        self.failure_ref = _failure_ref(category)
        self.failure_reasons = tuple(failure_reasons)
        super().__init__(
            "lalm_thinker_candidate_validation_failed "
            f"category={self.category} failure_ref={self.failure_ref}"
        )


@dataclass(frozen=True)
class LALMThinkerValidatedCandidate:
    adapter_request_id: str
    output_mode: str
    semantic_frame_ref: str
    semantic_summary_ref: str
    optional_refs: dict[str, str]
    optional_statuses: dict[str, str]
    missing_capabilities: tuple[str, ...]
    validation_ref: str
    evidence_only: bool = True
    may_emit_contract_event: bool = False


OPTIONAL_EVIDENCE_FIELDS = {
    "semantic_close": ("semantic_close_ref", "semantic_close_status", "supports_semantic_close"),
    "assistant_directedness": (
        "assistant_directedness_ref",
        "assistant_directedness_status",
        "supports_assistant_directedness",
    ),
    "emotion": ("emotion_ref", "emotion_status", "supports_emotion"),
    "audio_caption": ("audio_caption_ref", "audio_caption_status", "supports_audio_caption"),
}

_OUTPUT_MODES = frozenset({"real", "fallback", "degraded"})
_BOUNDARY_ASSERTIONS = {
    "candidate_is_evidence_only": True,
    "may_emit_event_journal_events": False,
    "may_create_semantic_commitments": False,
    "may_accept_confirmation": False,
    "may_authorize_tools": False,
    "may_execute_tools": False,
    "may_control_playback": False,
    "may_emit_coverage_or_truthfulness_verdicts": False,
}
_FORBIDDEN_OWNERSHIP_FIELDS = frozenset(
    {
        "event_name",
        "semantic_commitment",
        "semantic_commitment_event",
        "commitment",
        "confirmation",
        "confirmation_state",
        "tool_authorization",
        "tool_execution",
        "tool_result",
        "playback",
        "playback_action",
        "spoken_plan",
        "coverage_check",
        "truthfulness_check",
        "checker_verdict",
    }
)
_PROVIDER_TOOL_FIELDS = frozenset(
    {
        "tool_calls",
        "provider_tool_calls",
        "function_call",
        "tool_choice",
        "native_tool_execution",
    }
)
_RAW_ARTIFACT_FIELDS = frozenset(
    {
        "prompt",
        "messages",
        "headers",
        "authorization",
        "cookies",
        "raw_audio",
        "audio_bytes",
        "audio_payload",
        "raw_trace",
        "raw_provider_body",
        "raw_provider_request",
        "raw_provider_response",
        "provider_request",
        "provider_response",
        "provider_payload",
        "provider_schema",
        "provider_sdk_response",
        "raw_request_body",
        "raw_response_body",
        "raw_semantic_frame",
        "raw_semantic_summary",
        "semantic_frame",
        "semantic_summary",
        "large_raw_web_content",
    }
)
_RAW_ARTIFACT_MARKERS = (
    "raw_audio",
    "audio_bytes",
    "audio_payload",
    "raw_trace",
    "raw_provider",
    "provider_request",
    "provider_response",
    "provider_payload",
    "provider_schema",
    "audio/raw/",
    "diagnostics/",
    "traces/",
    "replays/local/",
    "local replay cache",
)


def parse_lalm_thinker_candidate_text(content: str) -> dict[str, Any]:
    if not isinstance(content, str):
        raise LALMThinkerCandidateParseError("content_not_text")

    stripped = content.strip()
    if not stripped:
        raise LALMThinkerCandidateParseError("empty_content")
    if "```" in stripped:
        raise LALMThinkerCandidateParseError("fenced_markdown")
    if not stripped.startswith("{") or not stripped.endswith("}"):
        raise LALMThinkerCandidateParseError("prose_wrapper")

    decoder = json.JSONDecoder()
    try:
        parsed, index = decoder.raw_decode(stripped)
    except json.JSONDecodeError as exc:
        raise LALMThinkerCandidateParseError("invalid_json") from exc
    if stripped[index:].strip():
        raise LALMThinkerCandidateParseError("multiple_objects")
    if not isinstance(parsed, dict):
        raise LALMThinkerCandidateParseError("candidate_not_object")
    return parsed


def validate_lalm_thinker_candidate(
    candidate: Mapping[str, Any],
    *,
    expected_binding: LALMThinkerRequestBinding,
) -> LALMThinkerValidatedCandidate:
    if not isinstance(candidate, Mapping):
        _fail("schema_shape", "candidate must be an object")

    _reject_forbidden_candidate_content(candidate)

    if candidate.get("schema_version") != LALM_THINKER_CANDIDATE_SCHEMA_VERSION:
        _fail("schema_version", "unsupported candidate schema version")
    if candidate.get("candidate_role") != "evidence_only":
        _fail("ownership_claim", "candidate role must remain evidence only")

    request_binding = candidate.get("request_binding")
    if not isinstance(request_binding, Mapping):
        _fail("binding_mismatch", "request binding is missing")
    if dict(request_binding) != expected_binding.to_dict():
        _fail("binding_mismatch", "candidate binding does not match request binding")

    output_mode = candidate.get("output_mode")
    if output_mode not in _OUTPUT_MODES:
        _fail("schema_shape", "output mode is unsupported")

    boundary_assertions = candidate.get("boundary_assertions")
    if not isinstance(boundary_assertions, Mapping):
        _fail("ownership_claim", "boundary assertions are missing")
    for assertion, expected in _BOUNDARY_ASSERTIONS.items():
        if boundary_assertions.get(assertion) is not expected:
            _fail("ownership_claim", f"boundary assertion failed: {assertion}")

    artifact_policy = candidate.get("artifact_policy")
    if not isinstance(artifact_policy, Mapping):
        _fail("raw_artifact_retention", "artifact policy is missing")
    if artifact_policy.get("retention") != "refs_only":
        _fail("raw_artifact_retention", "artifact retention must use refs only")
    if artifact_policy.get("raw_artifacts_retained") is not False:
        _fail("raw_artifact_retention", "candidate must not retain raw artifacts")

    semantic_frame_ref = _require_safe_ref(candidate.get("semantic_frame_ref"), "semantic_frame_ref")
    semantic_summary_ref = _require_safe_ref(
        candidate.get("semantic_summary_ref"),
        "semantic_summary_ref",
    )
    validation_ref = _require_safe_ref(candidate.get("validation_ref"), "validation_ref")

    optional_refs, optional_statuses, missing_capabilities = _validate_optional_evidence_refs(
        candidate.get("optional_evidence_refs")
    )
    if missing_capabilities and output_mode != "degraded":
        _fail("degraded_mode_required", "missing optional evidence requires degraded output mode")

    _validate_task_focus_hint(candidate.get("task_focus_hint"))

    return LALMThinkerValidatedCandidate(
        adapter_request_id=expected_binding.adapter_request_id,
        output_mode=str(output_mode),
        semantic_frame_ref=semantic_frame_ref,
        semantic_summary_ref=semantic_summary_ref,
        optional_refs=optional_refs,
        optional_statuses=optional_statuses,
        missing_capabilities=tuple(missing_capabilities),
        validation_ref=validation_ref,
    )


def fake_lalm_thinker_transport(binding: LALMThinkerRequestBinding) -> str:
    """Return deterministic synthetic candidate text without provider access."""

    slug = _slug(binding.turn_id)
    candidate = {
        "schema_version": LALM_THINKER_CANDIDATE_SCHEMA_VERSION,
        "request_binding": binding.to_dict(),
        "candidate_role": "evidence_only",
        "output_mode": "real",
        "semantic_frame_ref": f"semantic-frame://synthetic/lalm-thinker/{slug}/frame",
        "semantic_summary_ref": f"summary://synthetic/lalm-thinker/{slug}/summary",
        "optional_evidence_refs": {
            "semantic_close": {
                "status": "available",
                "ref": f"semantic-close://synthetic/lalm-thinker/{slug}/closed",
            },
            "assistant_directedness": {
                "status": "available",
                "ref": f"assistant-directedness://synthetic/lalm-thinker/{slug}/directed",
            },
            "emotion": {
                "status": "available",
                "ref": f"emotion://synthetic/lalm-thinker/{slug}/calm",
            },
            "audio_caption": {
                "status": "available",
                "ref": f"audio-caption://synthetic/lalm-thinker/{slug}/caption",
            },
        },
        "task_focus_hint": {
            "task_like": True,
            "complexity_hint": "complex",
            "focus_confidence": 0.82,
            "evidence_uncertainty": "medium",
        },
        "boundary_assertions": dict(_BOUNDARY_ASSERTIONS),
        "artifact_policy": {
            "retention": "refs_only",
            "raw_artifacts_retained": False,
        },
        "validation_ref": f"validation://synthetic/lalm-thinker/{slug}/candidate",
    }
    return json.dumps(candidate, separators=(",", ":"), sort_keys=True)


def _validate_optional_evidence_refs(value: object) -> tuple[dict[str, str], dict[str, str], list[str]]:
    if not isinstance(value, Mapping):
        _fail("schema_shape", "optional evidence refs are missing")

    optional_refs: dict[str, str] = {}
    optional_statuses: dict[str, str] = {}
    missing_capabilities: list[str] = []
    for evidence_name, (ref_field, status_field, missing_capability) in OPTIONAL_EVIDENCE_FIELDS.items():
        entry = value.get(evidence_name)
        if not isinstance(entry, Mapping):
            _fail("schema_shape", f"optional evidence entry is missing: {evidence_name}")
        status = entry.get("status")
        if status not in {"available", "unavailable"}:
            _fail("schema_shape", f"optional evidence status is invalid: {evidence_name}")
        optional_statuses[status_field] = str(status)
        ref_value = entry.get("ref")
        if status == "available":
            optional_refs[ref_field] = _require_safe_ref(ref_value, ref_field)
        else:
            if ref_value not in (None, ""):
                _fail("schema_shape", f"unavailable evidence must not include ref: {evidence_name}")
            missing_capabilities.append(missing_capability)
    return optional_refs, optional_statuses, missing_capabilities


def _validate_task_focus_hint(value: object) -> None:
    if value is None:
        return
    if not isinstance(value, Mapping):
        _fail("schema_shape", "task focus hint must be an object")
    if not isinstance(value.get("task_like"), bool):
        _fail("schema_shape", "task_like must be a boolean")
    confidence = value.get("focus_confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        _fail("schema_shape", "focus_confidence must be numeric")
    if float(confidence) < 0.0 or float(confidence) > 1.0:
        _fail("schema_shape", "focus_confidence must be between 0 and 1")
    for field in ("complexity_hint", "evidence_uncertainty"):
        _require_safe_token(value.get(field), field)


def _reject_forbidden_candidate_content(value: object) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                _fail("schema_shape", "candidate object keys must be strings")
            if key in _FORBIDDEN_OWNERSHIP_FIELDS:
                _fail("ownership_claim", f"forbidden ownership field present: {key}")
            if key in _PROVIDER_TOOL_FIELDS:
                _fail("provider_tool_execution_claim", f"provider tool field present: {key}")
            if key in _RAW_ARTIFACT_FIELDS:
                _fail("raw_artifact_retention", f"raw artifact field present: {key}")
            _reject_forbidden_candidate_content(child)
    elif isinstance(value, str):
        _reject_unsafe_text(value)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _reject_forbidden_candidate_content(item)


def _require_safe_ref(value: object, field: str) -> str:
    token = _require_safe_token(value, field)
    if "://" not in token:
        _fail("unsafe_ref", f"{field} must be a safe ref")
    return token


def _require_safe_token(value: object, field: str) -> str:
    if not isinstance(value, str) or value == "":
        _fail("schema_shape", f"{field} must be a non-empty string")
    _reject_unsafe_text(value)
    return value


def _reject_unsafe_text(value: str) -> None:
    variants = {value, unquote(value)}
    for variant in variants:
        if CREDENTIAL_LIKE_REF_PATTERN.search(variant):
            _fail("unsafe_ref", "credential-like content is not allowed")
        lowered = variant.lower()
        if any(marker in lowered for marker in _RAW_ARTIFACT_MARKERS):
            _fail("raw_artifact_retention", "local-only artifact refs are not allowed")


def _fail(category: str, reason: str) -> None:
    raise LALMThinkerCandidateValidationError(category, (reason,))


def _failure_ref(category: str) -> str:
    return f"validation://synthetic/lalm-thinker/{_slug(category)}"


def _slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-") or "unknown"
