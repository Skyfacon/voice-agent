from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
import json
from typing import Any
from urllib.parse import unquote

from voice_agent.adapters.capabilities import CREDENTIAL_LIKE_REF_PATTERN
from voice_agent.adapters.event_harness import FakeRealAdapterEventHarness
from voice_agent.adapters.lalm_thinker_binding import (
    LALM_THINKER_CANDIDATE_SCHEMA_VERSION,
    LALMThinkerRequestBinding,
    build_lalm_thinker_request_metadata,
)
from voice_agent.adapters.lalm_thinker_live_transport import (
    LALMThinkerCredentialHandle,
    validate_lalm_thinker_credential_handle,
)
from voice_agent.adapters.thinker_contract import (
    ThinkerAdapterContract,
    ThinkerSemanticFrameEmission,
)
from voice_agent.runtime.adapter_callback_boundary import AdapterCallbackAppendBoundary


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
    task_like: bool | None = None
    complexity_hint: str | None = None
    focus_confidence: float | None = None
    evidence_uncertainty: str | None = None


@dataclass(frozen=True)
class LALMThinkerProviderTextCandidate:
    text: str
    adapter_request_id: str
    output_mode: str = "real"

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            _fail("content_not_text", "provider text must be a string")
        _require_safe_token(self.adapter_request_id, "adapter_request_id")
        if self.output_mode not in _OUTPUT_MODES:
            _fail("schema_shape", "output mode is unsupported")

    def __repr__(self) -> str:
        return (
            "LALMThinkerProviderTextCandidate("
            f"adapter_request_id={self.adapter_request_id!r}, "
            f"output_mode={self.output_mode!r}, text_present=True)"
        )

    def to_metadata(self) -> dict[str, Any]:
        return {
            "adapter_request_id": self.adapter_request_id,
            "output_mode": self.output_mode,
            "text_present": True,
            "raw_provider_request_included": False,
            "raw_provider_response_included": False,
        }


@dataclass(frozen=True)
class LALMThinkerProviderTextEmissionResult:
    success: bool
    adapter_request_id: str
    thinker_emission: ThinkerSemanticFrameEmission | None
    validation_failed_event: dict[str, Any] | None

    def to_metadata(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "success": self.success,
            "adapter_request_id": self.adapter_request_id,
            "raw_provider_request_included": False,
            "raw_provider_response_included": False,
        }
        if self.thinker_emission is not None:
            metadata["thinker_event_id"] = self.thinker_emission.thinker_event["event_id"]
        if self.validation_failed_event is not None:
            metadata["validation_failed_event_id"] = self.validation_failed_event["event_id"]
        return metadata


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

    task_like, complexity_hint, focus_confidence, evidence_uncertainty = _validate_task_focus_hint(
        candidate.get("task_focus_hint")
    )

    return LALMThinkerValidatedCandidate(
        adapter_request_id=expected_binding.adapter_request_id,
        output_mode=str(output_mode),
        semantic_frame_ref=semantic_frame_ref,
        semantic_summary_ref=semantic_summary_ref,
        optional_refs=optional_refs,
        optional_statuses=optional_statuses,
        missing_capabilities=tuple(missing_capabilities),
        validation_ref=validation_ref,
        task_like=task_like,
        complexity_hint=complexity_hint,
        focus_confidence=focus_confidence,
        evidence_uncertainty=evidence_uncertainty,
    )


def fake_lalm_thinker_transport(
    binding: LALMThinkerRequestBinding,
    *,
    optional_refs_available: bool = False,
) -> str:
    """Return deterministic synthetic candidate text without provider access."""

    slug = _slug(binding.turn_id)
    if optional_refs_available:
        output_mode = "real"
        optional_evidence_refs = {
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
        }
    else:
        output_mode = "degraded"
        optional_evidence_refs = {
            "semantic_close": {"status": "unavailable"},
            "assistant_directedness": {"status": "unavailable"},
            "emotion": {"status": "unavailable"},
            "audio_caption": {"status": "unavailable"},
        }

    candidate = {
        "schema_version": LALM_THINKER_CANDIDATE_SCHEMA_VERSION,
        "request_binding": binding.to_dict(),
        "candidate_role": "evidence_only",
        "output_mode": output_mode,
        "semantic_frame_ref": f"semantic-frame://synthetic/lalm-thinker/{slug}/frame",
        "semantic_summary_ref": f"summary://synthetic/lalm-thinker/{slug}/summary",
        "optional_evidence_refs": optional_evidence_refs,
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


def build_lalm_thinker_live_request_payload(
    *,
    binding: LALMThinkerRequestBinding,
) -> dict[str, Any]:
    request_metadata = build_lalm_thinker_request_metadata(binding)
    skeleton = {
        "schema_version": LALM_THINKER_CANDIDATE_SCHEMA_VERSION,
        "request_binding": binding.to_dict(),
        "candidate_role": "evidence_only",
        "output_mode": "degraded",
        "semantic_frame_ref": "semantic-frame://synthetic/lalm-thinker/live-eval/frame",
        "semantic_summary_ref": "summary://synthetic/lalm-thinker/live-eval/summary",
        "optional_evidence_refs": {
            "semantic_close": {"status": "unavailable"},
            "assistant_directedness": {"status": "unavailable"},
            "emotion": {"status": "unavailable"},
            "audio_caption": {"status": "unavailable"},
        },
        "task_focus_hint": {
            "task_like": True,
            "complexity_hint": "complex",
            "focus_confidence": 0.75,
            "evidence_uncertainty": "medium",
        },
        "boundary_assertions": dict(_BOUNDARY_ASSERTIONS),
        "artifact_policy": {
            "retention": "refs_only",
            "raw_artifacts_retained": False,
        },
        "validation_ref": "validation://synthetic/lalm-thinker/live-eval/candidate",
    }
    payload = {
        "request_metadata": request_metadata,
        "required_output_skeleton": skeleton,
        "output_rules": [
            "return exactly one JSON object",
            "copy required_output_skeleton.request_binding exactly",
            "use refs only and do not include raw provider request or response",
            "do not claim tool, playback, confirmation, commitment, or checker ownership",
        ],
    }
    _reject_unsafe_live_request_payload(payload)
    return payload


def request_lalm_thinker_provider_text(
    *,
    transport: object,
    credential_handle: LALMThinkerCredentialHandle,
    request_payload: Mapping[str, Any],
    adapter_request_id: str,
    timeout_ms: int,
    credential_value: str | None = None,
    model_alias: str | None = None,
) -> LALMThinkerProviderTextCandidate:
    credential_handle = validate_lalm_thinker_credential_handle(credential_handle)
    _require_safe_token(adapter_request_id, "adapter_request_id")
    if not isinstance(timeout_ms, int) or isinstance(timeout_ms, bool) or timeout_ms < 1:
        _fail("invalid_budget", "timeout_ms must be a positive integer")
    if credential_value is not None and credential_value == "":
        _fail("credential_missing", "credential value is missing")
    if model_alias is not None:
        _require_safe_token(model_alias, "model_alias")
    _reject_unsafe_live_request_payload(request_payload)

    complete = getattr(transport, "complete", None)
    if not callable(complete):
        _fail("transport_invalid", "transport must provide a complete method")
    complete_kwargs: dict[str, Any] = {
        "request_payload": deepcopy(dict(request_payload)),
        "credential_handle": credential_handle,
        "adapter_request_id": adapter_request_id,
        "timeout_ms": timeout_ms,
    }
    if credential_value is not None:
        complete_kwargs["credential_value"] = credential_value
    if model_alias is not None:
        complete_kwargs["model_alias"] = model_alias
    provider_text = complete(**complete_kwargs)
    if not isinstance(provider_text, str):
        _fail("provider_response_text_missing", "transport must return transient provider text")
    return LALMThinkerProviderTextCandidate(
        text=provider_text,
        adapter_request_id=adapter_request_id,
        output_mode="real",
    )


def emit_lalm_thinker_live_provider_result(
    *,
    transport: object,
    credential_handle: LALMThinkerCredentialHandle,
    credential_value: str,
    model_alias: str,
    timeout_ms: int,
    boundary: AdapterCallbackAppendBoundary,
    adapter_id: str,
    binding: LALMThinkerRequestBinding,
    success_event_id: str,
    validation_failed_event_id: str,
    caused_by_event_id: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
    turn_committed_event: Mapping[str, Any],
) -> LALMThinkerProviderTextEmissionResult:
    request_payload = build_lalm_thinker_live_request_payload(binding=binding)
    provider_text = request_lalm_thinker_provider_text(
        transport=transport,
        credential_handle=credential_handle,
        request_payload=request_payload,
        adapter_request_id=binding.adapter_request_id,
        timeout_ms=timeout_ms,
        credential_value=credential_value,
        model_alias=model_alias,
    )
    return emit_lalm_thinker_provider_text_result(
        boundary=boundary,
        adapter_id=adapter_id,
        provider_text=provider_text.text,
        expected_binding=binding,
        success_event_id=success_event_id,
        validation_failed_event_id=validation_failed_event_id,
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
        turn_committed_event=turn_committed_event,
    )


def emit_lalm_thinker_provider_text_result(
    *,
    boundary: AdapterCallbackAppendBoundary,
    adapter_id: str,
    provider_text: str,
    expected_binding: LALMThinkerRequestBinding,
    success_event_id: str,
    validation_failed_event_id: str,
    caused_by_event_id: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
    turn_committed_event: Mapping[str, Any],
) -> LALMThinkerProviderTextEmissionResult:
    try:
        parsed = parse_lalm_thinker_candidate_text(provider_text)
        validated = validate_lalm_thinker_candidate(parsed, expected_binding=expected_binding)
        emission = emit_lalm_thinker_semantic_frame(
            boundary=boundary,
            adapter_id=adapter_id,
            event_id=success_event_id,
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            turn_committed_event=turn_committed_event,
            validated_candidate=validated,
        )
    except LALMThinkerCandidateParseError as exc:
        validation_failed = _emit_lalm_thinker_output_validation_failed(
            boundary=boundary,
            adapter_id=adapter_id,
            event_id=validation_failed_event_id,
            caused_by_event_id=caused_by_event_id,
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            adapter_request_id=expected_binding.adapter_request_id,
            failure_reasons=(exc.category,),
        )
        return LALMThinkerProviderTextEmissionResult(
            success=False,
            adapter_request_id=expected_binding.adapter_request_id,
            thinker_emission=None,
            validation_failed_event=validation_failed,
        )
    except LALMThinkerCandidateValidationError as exc:
        validation_failed = _emit_lalm_thinker_output_validation_failed(
            boundary=boundary,
            adapter_id=adapter_id,
            event_id=validation_failed_event_id,
            caused_by_event_id=caused_by_event_id,
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            adapter_request_id=expected_binding.adapter_request_id,
            failure_reasons=exc.failure_reasons,
        )
        return LALMThinkerProviderTextEmissionResult(
            success=False,
            adapter_request_id=expected_binding.adapter_request_id,
            thinker_emission=None,
            validation_failed_event=validation_failed,
        )

    return LALMThinkerProviderTextEmissionResult(
        success=True,
        adapter_request_id=expected_binding.adapter_request_id,
        thinker_emission=emission,
        validation_failed_event=None,
    )


def emit_lalm_thinker_request_retrying(
    *,
    boundary: AdapterCallbackAppendBoundary,
    event_id: str,
    caused_by_event_id: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
    adapter_request_id: str,
    retry_count: int,
    retry_reason: str,
    timeout_ms: int | None = None,
    adapter_id: str = "lalm_thinker_provider_free",
) -> dict[str, Any]:
    return FakeRealAdapterEventHarness(
        boundary=boundary,
        adapter_id=adapter_id,
        adapter_type="thinker",
        output_mode="real",
        source_module="lalm_thinker_adapter",
    ).emit_request_retrying(
        event_id=event_id,
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
        adapter_request_id=_require_safe_token(adapter_request_id, "adapter_request_id"),
        retry_count=retry_count,
        retry_reason=_safe_failure_reason(retry_reason),
        timeout_ms=timeout_ms,
    )


def emit_lalm_thinker_request_failed(
    *,
    boundary: AdapterCallbackAppendBoundary,
    event_id: str,
    caused_by_event_id: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
    adapter_request_id: str,
    failure_reason: str,
    retryable: bool,
    timeout_ms: int | None = None,
    adapter_id: str = "lalm_thinker_provider_free",
) -> dict[str, Any]:
    if not isinstance(retryable, bool):
        _fail("schema_shape", "retryable must be a boolean")
    return FakeRealAdapterEventHarness(
        boundary=boundary,
        adapter_id=adapter_id,
        adapter_type="thinker",
        output_mode="real",
        source_module="lalm_thinker_adapter",
    ).emit_request_failed(
        event_id=event_id,
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
        adapter_request_id=_require_safe_token(adapter_request_id, "adapter_request_id"),
        failure_reason=_safe_failure_reason(failure_reason),
        retryable=retryable,
        timeout_ms=timeout_ms,
    )


def emit_lalm_thinker_semantic_frame(
    *,
    boundary: AdapterCallbackAppendBoundary,
    adapter_id: str,
    event_id: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
    turn_committed_event: Mapping[str, Any],
    validated_candidate: LALMThinkerValidatedCandidate,
    source_module: str = "lalm_thinker_adapter",
    trace_redaction_level: str = "metadata_only",
) -> ThinkerSemanticFrameEmission:
    """Emit a validated provider-free LALM Thinker candidate through the contract."""

    contract = ThinkerAdapterContract(
        boundary=boundary,
        adapter_id=adapter_id,
        output_mode=validated_candidate.output_mode,
        source_module=source_module,
        trace_redaction_level=trace_redaction_level,
    )
    return contract.emit_semantic_frame(
        event_id=event_id,
        caused_by_event_id=str(turn_committed_event["event_id"]),
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
        turn_committed_event=turn_committed_event,
        adapter_request_id=validated_candidate.adapter_request_id,
        semantic_frame_ref=validated_candidate.semantic_frame_ref,
        semantic_summary_ref=validated_candidate.semantic_summary_ref,
        semantic_close_ref=validated_candidate.optional_refs.get("semantic_close_ref"),
        assistant_directedness_ref=validated_candidate.optional_refs.get(
            "assistant_directedness_ref"
        ),
        emotion_ref=validated_candidate.optional_refs.get("emotion_ref"),
        audio_caption_ref=validated_candidate.optional_refs.get("audio_caption_ref"),
        task_like=validated_candidate.task_like,
        complexity_hint=validated_candidate.complexity_hint,
        focus_confidence=validated_candidate.focus_confidence,
        evidence_uncertainty=validated_candidate.evidence_uncertainty,
    )


def _emit_lalm_thinker_output_validation_failed(
    *,
    boundary: AdapterCallbackAppendBoundary,
    adapter_id: str,
    event_id: str,
    caused_by_event_id: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
    adapter_request_id: str,
    failure_reasons: Sequence[str],
) -> dict[str, Any]:
    return FakeRealAdapterEventHarness(
        boundary=boundary,
        adapter_id=adapter_id,
        adapter_type="thinker",
        output_mode="real",
        source_module="lalm_thinker_adapter",
    ).emit_output_validation_failed(
        event_id=event_id,
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
        adapter_request_id=_require_safe_token(adapter_request_id, "adapter_request_id"),
        schema_name=LALM_THINKER_CANDIDATE_SCHEMA_VERSION,
        failure_reasons=[_safe_failure_reason(reason) for reason in failure_reasons],
    )


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


def _validate_task_focus_hint(value: object) -> tuple[bool | None, str | None, float | None, str | None]:
    if value is None:
        return None, None, None, None
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
    return (
        bool(value["task_like"]),
        str(value["complexity_hint"]),
        float(confidence),
        str(value["evidence_uncertainty"]),
    )


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


def _reject_unsafe_live_request_payload(value: object) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                _fail("schema_shape", "request payload keys must be strings")
            _reject_unsafe_text(key)
            _reject_unsafe_live_request_payload(child)
    elif isinstance(value, str):
        _reject_unsafe_text(value)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _reject_unsafe_live_request_payload(item)


def _safe_failure_reason(value: object) -> str:
    if not isinstance(value, str) or value == "":
        return "unsafe_failure_reason_redacted"
    variants = {value, unquote(value)}
    for variant in variants:
        if CREDENTIAL_LIKE_REF_PATTERN.search(variant):
            return "unsafe_failure_reason_redacted"
        lowered = variant.lower()
        if any(marker in lowered for marker in _RAW_ARTIFACT_MARKERS):
            return "unsafe_failure_reason_redacted"
    return value


def _fail(category: str, reason: str) -> None:
    raise LALMThinkerCandidateValidationError(category, (reason,))


def _failure_ref(category: str) -> str:
    return f"validation://synthetic/lalm-thinker/{_slug(category)}"


def _slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-") or "unknown"
