from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import re
from typing import Any, Protocol, runtime_checkable

from voice_agent.adapters.qwen_realtime.projections import (
    CandidateTranscriptCompleteV1,
)
from voice_agent.runtime.adapter_callback_boundary import (
    AdapterCallbackAppendBoundary,
    AdapterCallbackBoundaryError,
)


ROUTE_EVIDENCE_SCHEMA_NAME = "voice_agent.route_evidence.output.v1"
CANDIDATE_SAFETY_SCHEMA_NAME = "voice_agent.candidate_safety.output.v1"

ROUTE_HINTS = frozenset(
    {"FAST_ONLY", "SPAWN_SLOW_TASK", "PATCH_ACTIVE_SLOW_TASK", "IGNORE"}
)
TASK_FOCUS_HINTS = frozenset(
    {
        "ACTIVE_TASK_PATCH",
        "FOREGROUND_CHAT",
        "NEW_TASK_CANDIDATE",
        "CANCEL_OR_PAUSE_CANDIDATE",
        "NON_ASSISTANT",
        "AMBIGUOUS",
    }
)
FOREGROUND_ACT_HINTS = frozenset(
    {"ANSWER", "ACK_SLOW", "ACK_PATCH", "SILENCE", "CLARIFY"}
)
ACK_KINDS = frozenset(
    {
        "CHAT",
        "SEARCH_ACCEPTED",
        "COMPARE_ACCEPTED",
        "PLAN_ACCEPTED",
        "PATCH_RECEIVED",
        "CLARIFY_NEEDED",
        "WAITING_CONFIRMATION",
        "SILENCE",
    }
)
RISK_CLASSES = frozenset({"LOW", "MEDIUM", "HIGH", "UNKNOWN"})
EVIDENCE_UNCERTAINTIES = frozenset({"LOW", "MEDIUM", "HIGH"})
CANDIDATE_SAFETY_DECISIONS = frozenset({"SAFE", "UNSAFE", "UNCERTAIN"})

ROUTE_CONFIDENCE_THRESHOLD = 0.80
CANDIDATE_SAFETY_CONFIDENCE_THRESHOLD = 0.90
MAX_ASR_UNICODE_SCALARS = 2_000
MAX_CANDIDATE_UNICODE_SCALARS = 80
MAX_SYMBOLIC_ITEMS = 8
MAX_SYMBOLIC_ITEM_CHARS = 64

_DIGEST = re.compile(r"\A(?:sha256:)?[0-9a-f]{64}\Z")
_CREDENTIAL_LIKE_VALUE = re.compile(
    r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{8,}"
    r"|Bearer\s+\S+"
    r"|api[_-]?key="
    r"|authorization="
    r"|credential="
    r"|token="
    r"|password=",
    re.IGNORECASE,
)
_SYMBOLIC_TOKEN = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._~:/-]{0,255}\Z")
_SYMBOLIC_ITEM = re.compile(r"\A[A-Za-z][A-Za-z0-9._~-]{0,63}\Z")
_EPHEMERAL_TEXT_REF = re.compile(
    r"\A(?:text-ref|candidate-ref)://(?:synthetic|local)/"
    r"[A-Za-z0-9._~-]+(?:/[A-Za-z0-9._~-]+)*\Z"
)
_SAFE_REF = re.compile(
    r"\A[a-z][a-z0-9-]{0,47}://[A-Za-z0-9._~:/-]{1,384}\Z"
)
_FORBIDDEN_VALUE_TERMS = (
    "raw_prompt",
    "raw_transcript",
    "raw_audio",
    "provider_body",
    "provider_payload",
    "provider_state",
    "private_reasoning",
    "tool_result",
    "audio/raw",
    "diagnostics/",
    "traces/",
    "replays/local/",
    "http://",
    "https://",
    "file://",
)
_FORBIDDEN_EVENT_FIELDS = frozenset(
    {
        "candidate_ref",
        "candidate_text",
        "candidate_transcript",
        "audio_bytes",
        "pcm_bytes",
        "prompt",
        "provider_request",
        "provider_response",
        "reasoning",
        "redacted_text",
        "raw_text",
        "text",
        "transcript",
        "transcript_ref",
        "transcript_text",
        "resolved_text",
        "raw_prompt",
        "raw_transcript",
        "raw_audio",
        "pcm",
        "provider_body",
        "provider_payload",
        "provider_state",
        "private_reasoning",
        "tool_result",
        "tool_output",
    }
)


class RouteEvidenceContractError(ValueError):
    """Sanitized fail-closed error at the Route Evidence contract boundary."""


@dataclass(frozen=True, slots=True)
class RouteEvidenceRequestV1:
    adapter_request_id: str
    turn_id: str
    utterance_id: str
    final_asr_event_id: str
    transcript_ref: str
    asr_confidence: float | None
    duplex_hints_ref: str | None
    qwen_semantic_hints_ref: str | None
    context_projection_event_id: str
    context_snapshot_id: str
    active_task_public_snapshot_ref: str | None
    last_assistant_act: str
    expected_user_response: str | None
    policy_version: str

    def __post_init__(self) -> None:
        _require_token(self.adapter_request_id, "adapter_request_id")
        _require_token(self.turn_id, "turn_id")
        _require_token(self.utterance_id, "utterance_id")
        _require_token(self.final_asr_event_id, "final_asr_event_id")
        _require_ephemeral_text_ref(self.transcript_ref, "transcript_ref")
        if self.asr_confidence is not None:
            _require_confidence(self.asr_confidence, "asr_confidence")
        _require_optional_ref(self.duplex_hints_ref, "duplex_hints_ref")
        _require_optional_ref(
            self.qwen_semantic_hints_ref,
            "qwen_semantic_hints_ref",
        )
        _require_token(
            self.context_projection_event_id,
            "context_projection_event_id",
        )
        _require_token(self.context_snapshot_id, "context_snapshot_id")
        _require_optional_ref(
            self.active_task_public_snapshot_ref,
            "active_task_public_snapshot_ref",
        )
        _require_token(self.last_assistant_act, "last_assistant_act")
        if self.expected_user_response is not None:
            _require_token(
                self.expected_user_response,
                "expected_user_response",
            )
        _require_token(self.policy_version, "policy_version")


@dataclass(frozen=True, slots=True)
class CandidateSafetyRequestV1:
    adapter_request_id: str
    turn_id: str
    utterance_id: str
    qwen_response_id: str
    candidate_ref: str = field(repr=False)
    candidate_transcript_digest: str
    context_projection_event_id: str
    context_snapshot_id: str
    route_evidence_event_id: str | None
    task_focus_state_ref: str
    active_task_public_snapshot_ref: str | None
    policy_version: str

    def __post_init__(self) -> None:
        _require_token(self.adapter_request_id, "adapter_request_id")
        _require_token(self.turn_id, "turn_id")
        _require_token(self.utterance_id, "utterance_id")
        _require_token(self.qwen_response_id, "qwen_response_id")
        _require_ephemeral_text_ref(self.candidate_ref, "candidate_ref")
        _require_digest(
            self.candidate_transcript_digest,
            "candidate_transcript_digest",
        )
        _require_token(
            self.context_projection_event_id,
            "context_projection_event_id",
        )
        _require_token(self.context_snapshot_id, "context_snapshot_id")
        if self.route_evidence_event_id is not None:
            _require_token(
                self.route_evidence_event_id,
                "route_evidence_event_id",
            )
        _require_ref(self.task_focus_state_ref, "task_focus_state_ref")
        _require_optional_ref(
            self.active_task_public_snapshot_ref,
            "active_task_public_snapshot_ref",
        )
        _require_token(self.policy_version, "policy_version")


@dataclass(frozen=True, slots=True)
class RouteEvidenceOutputV1:
    route_hint: str
    task_focus_hint: str
    foreground_act_hint: str
    ack_kind: str
    risk_class: str
    risk_tags: tuple[str, ...]
    evidence_uncertainty: str
    confidence: float
    schema_name: str = ROUTE_EVIDENCE_SCHEMA_NAME
    normalization_status: str = "normalized"
    output_mode: str = "mock"

    def __post_init__(self) -> None:
        _require_enum(self.route_hint, ROUTE_HINTS, "route_hint")
        _require_enum(self.task_focus_hint, TASK_FOCUS_HINTS, "task_focus_hint")
        _require_enum(
            self.foreground_act_hint,
            FOREGROUND_ACT_HINTS,
            "foreground_act_hint",
        )
        _require_enum(self.ack_kind, ACK_KINDS, "ack_kind")
        _require_enum(self.risk_class, RISK_CLASSES, "risk_class")
        object.__setattr__(
            self,
            "risk_tags",
            _require_symbolic_items(self.risk_tags, "risk_tags"),
        )
        _require_enum(
            self.evidence_uncertainty,
            EVIDENCE_UNCERTAINTIES,
            "evidence_uncertainty",
        )
        object.__setattr__(
            self,
            "confidence",
            _require_confidence(self.confidence, "confidence"),
        )
        if self.schema_name != ROUTE_EVIDENCE_SCHEMA_NAME:
            raise RouteEvidenceContractError("invalid_schema_name")
        if self.normalization_status != "normalized":
            raise RouteEvidenceContractError("invalid_normalization_status")
        if self.output_mode != "mock":
            raise RouteEvidenceContractError("invalid_output_mode")

    @classmethod
    def fail_closed(
        cls,
        reason: str,
        *,
        prohibited_risk: bool = False,
    ) -> RouteEvidenceOutputV1:
        tag = _normalize_failure_symbol(reason)
        return cls(
            route_hint="IGNORE",
            task_focus_hint="AMBIGUOUS",
            foreground_act_hint="CLARIFY",
            ack_kind="CLARIFY_NEEDED",
            risk_class="HIGH" if prohibited_risk else "UNKNOWN",
            risk_tags=(tag,),
            evidence_uncertainty="HIGH",
            confidence=0.0,
        )


@dataclass(frozen=True, slots=True)
class CandidateSafetyEvidenceV1:
    decision: str
    semantic_categories: tuple[str, ...]
    prohibited_flags: tuple[str, ...]
    confidence: float
    candidate_transcript_digest: str
    schema_name: str = CANDIDATE_SAFETY_SCHEMA_NAME
    normalization_status: str = "normalized"
    output_mode: str = "mock"

    def __post_init__(self) -> None:
        _require_enum(self.decision, CANDIDATE_SAFETY_DECISIONS, "decision")
        object.__setattr__(
            self,
            "semantic_categories",
            _require_symbolic_items(
                self.semantic_categories,
                "semantic_categories",
            ),
        )
        object.__setattr__(
            self,
            "prohibited_flags",
            _require_symbolic_items(self.prohibited_flags, "prohibited_flags"),
        )
        object.__setattr__(
            self,
            "confidence",
            _require_confidence(self.confidence, "confidence"),
        )
        _require_digest(
            self.candidate_transcript_digest,
            "candidate_transcript_digest",
        )
        if self.schema_name != CANDIDATE_SAFETY_SCHEMA_NAME:
            raise RouteEvidenceContractError("invalid_schema_name")
        if self.normalization_status != "normalized":
            raise RouteEvidenceContractError("invalid_normalization_status")
        if self.output_mode != "mock":
            raise RouteEvidenceContractError("invalid_output_mode")
        if self.decision == "SAFE" and self.prohibited_flags:
            raise RouteEvidenceContractError(
                "SAFE candidate evidence cannot contain prohibited_flags"
            )

    @classmethod
    def fail_closed(
        cls,
        candidate_transcript_digest: str,
        reason: str,
    ) -> CandidateSafetyEvidenceV1:
        symbol = _normalize_failure_symbol(reason)
        return cls(
            decision="UNCERTAIN",
            semantic_categories=("validation_failure",),
            prohibited_flags=(symbol,),
            confidence=0.0,
            candidate_transcript_digest=candidate_transcript_digest,
        )


@runtime_checkable
class RouteEvidenceAdapter(Protocol):
    async def classify_route(
        self,
        request: RouteEvidenceRequestV1,
    ) -> RouteEvidenceOutputV1: ...

    async def classify_candidate_safety(
        self,
        request: CandidateSafetyRequestV1,
    ) -> CandidateSafetyEvidenceV1: ...


def emit_route_evidence_output_event(
    *,
    boundary: AdapterCallbackAppendBoundary,
    adapter_id: str,
    request: RouteEvidenceRequestV1,
    output: RouteEvidenceOutputV1,
    final_asr_event: Mapping[str, Any],
    context_projection_event: Mapping[str, Any],
    event_id: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
    source_module: str = "route_evidence_adapter",
) -> dict[str, Any]:
    _require_boundary(boundary)
    if not isinstance(request, RouteEvidenceRequestV1):
        raise RouteEvidenceContractError("invalid_route_request")
    if not isinstance(output, RouteEvidenceOutputV1):
        raise RouteEvidenceContractError("invalid_route_output")
    adapter_id = _require_token(adapter_id, "adapter_id")
    event_id = _require_token(event_id, "event_id")
    source_module = _require_token(source_module, "source_module")
    _require_timestamp(created_monotonic_ms, "created_monotonic_ms")
    _require_timestamp(created_wall_clock_ms, "created_wall_clock_ms")

    generation = _validate_final_asr_event(final_asr_event, request)
    _validate_context_projection_event(
        context_projection_event,
        request_event_id=request.context_projection_event_id,
        context_snapshot_id=request.context_snapshot_id,
        target_role="route_evidence",
        provider_session_generation=generation,
    )
    _validate_route_projection_causality(
        final_asr_event,
        context_projection_event,
    )
    _require_recorded_predecessor(boundary, final_asr_event)
    _require_recorded_predecessor(boundary, context_projection_event)
    _preflight(boundary, event_id)

    return boundary.append_adapter_event(
        event_name="ROUTE_EVIDENCE_OUTPUT_EMITTED",
        event_id=event_id,
        source_module=source_module,
        caused_by_event_id=request.context_projection_event_id,
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
        trace_redaction_level="metadata_only",
        adapter_id=adapter_id,
        adapter_type="route_evidence",
        adapter_request_id=request.adapter_request_id,
        turn_id=request.turn_id,
        utterance_id=request.utterance_id,
        final_asr_event_id=request.final_asr_event_id,
        context_projection_event_id=request.context_projection_event_id,
        context_snapshot_id=request.context_snapshot_id,
        provider_session_generation=generation,
        route_hint=output.route_hint,
        task_focus_hint=output.task_focus_hint,
        foreground_act_hint=output.foreground_act_hint,
        ack_kind=output.ack_kind,
        risk_class=output.risk_class,
        risk_tags=output.risk_tags,
        evidence_uncertainty=output.evidence_uncertainty,
        confidence=output.confidence,
        schema_name=output.schema_name,
        normalization_status=output.normalization_status,
        output_mode=output.output_mode,
    )


def emit_candidate_safety_evidence_output_event(
    *,
    boundary: AdapterCallbackAppendBoundary,
    adapter_id: str,
    request: CandidateSafetyRequestV1,
    output: CandidateSafetyEvidenceV1,
    candidate_transcript: CandidateTranscriptCompleteV1,
    context_projection_event: Mapping[str, Any],
    event_id: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
    source_module: str = "route_evidence_adapter",
) -> dict[str, Any]:
    _require_boundary(boundary)
    if not isinstance(request, CandidateSafetyRequestV1):
        raise RouteEvidenceContractError("invalid_candidate_safety_request")
    if not isinstance(output, CandidateSafetyEvidenceV1):
        raise RouteEvidenceContractError("invalid_candidate_safety_output")
    if not isinstance(candidate_transcript, CandidateTranscriptCompleteV1):
        raise RouteEvidenceContractError("invalid_candidate_transcript")
    adapter_id = _require_token(adapter_id, "adapter_id")
    event_id = _require_token(event_id, "event_id")
    source_module = _require_token(source_module, "source_module")
    _require_timestamp(created_monotonic_ms, "created_monotonic_ms")
    _require_timestamp(created_wall_clock_ms, "created_wall_clock_ms")

    _validate_candidate_transcript(request, output, candidate_transcript)
    generation = candidate_transcript.provider_session_generation
    _validate_context_projection_event(
        context_projection_event,
        request_event_id=request.context_projection_event_id,
        context_snapshot_id=request.context_snapshot_id,
        target_role="candidate_safety",
        provider_session_generation=generation,
    )
    if (
        request.route_evidence_event_id is not None
        and request.route_evidence_event_id
        not in context_projection_event["source_event_ids"]
    ):
        raise RouteEvidenceContractError(
            "route_evidence_event_id must be bound by the context projection"
        )
    _require_recorded_predecessor(boundary, context_projection_event)
    _preflight(boundary, event_id)

    optional_fields: dict[str, Any] = {}
    if request.route_evidence_event_id is not None:
        optional_fields["route_evidence_event_id"] = (
            request.route_evidence_event_id
        )
    return boundary.append_adapter_event(
        event_name="CANDIDATE_SAFETY_EVIDENCE_OUTPUT_EMITTED",
        event_id=event_id,
        source_module=source_module,
        caused_by_event_id=request.context_projection_event_id,
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
        trace_redaction_level="metadata_only",
        adapter_id=adapter_id,
        adapter_type="route_evidence",
        adapter_request_id=request.adapter_request_id,
        turn_id=request.turn_id,
        utterance_id=request.utterance_id,
        qwen_response_id=request.qwen_response_id,
        candidate_transcript_digest=output.candidate_transcript_digest,
        context_projection_event_id=request.context_projection_event_id,
        context_snapshot_id=request.context_snapshot_id,
        provider_session_generation=generation,
        decision=output.decision,
        semantic_categories=output.semantic_categories,
        prohibited_flags=output.prohibited_flags,
        confidence=output.confidence,
        schema_name=output.schema_name,
        normalization_status=output.normalization_status,
        output_mode=output.output_mode,
        **optional_fields,
    )


def _validate_final_asr_event(
    event: Mapping[str, Any],
    request: RouteEvidenceRequestV1,
) -> int:
    _require_mapping(event, "final_asr_event")
    _validate_canonical_envelope(event, "final_asr_event")
    _reject_forbidden_event_fields(event, allowed=frozenset({"text_ref"}))
    expected = {
        "event_name": "ASR_TRANSCRIPT_OUTPUT_EMITTED",
        "event_id": request.final_asr_event_id,
        "turn_id": request.turn_id,
        "utterance_id": request.utterance_id,
        "text_ref": request.transcript_ref,
        "transcript_finality": "final",
        "output_mode": "mock",
    }
    for name, value in expected.items():
        if event.get(name) != value:
            raise RouteEvidenceContractError(f"final_asr_event {name} mismatch")
    _require_token(
        event.get("qwen_input_item_ref"),
        "qwen_input_item_ref",
    )
    content_index = event.get("qwen_input_content_index")
    if isinstance(content_index, bool) or not isinstance(content_index, int) or content_index < 0:
        raise RouteEvidenceContractError(
            "final_asr_event qwen_input_content_index mismatch"
        )
    generation = event.get("provider_session_generation")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
        raise RouteEvidenceContractError(
            "final_asr_event provider_session_generation mismatch"
        )
    return generation


def _validate_candidate_transcript(
    request: CandidateSafetyRequestV1,
    output: CandidateSafetyEvidenceV1,
    transcript: CandidateTranscriptCompleteV1,
) -> None:
    expected = {
        "turn_id": request.turn_id,
        "utterance_id": request.utterance_id,
        "qwen_response_id": request.qwen_response_id,
        "candidate_ref": request.candidate_ref,
        "candidate_transcript_digest": request.candidate_transcript_digest,
        "context_snapshot_id": request.context_snapshot_id,
    }
    for name, value in expected.items():
        if getattr(transcript, name) != value:
            raise RouteEvidenceContractError(f"candidate_transcript {name} mismatch")
    if output.candidate_transcript_digest != request.candidate_transcript_digest:
        raise RouteEvidenceContractError(
            "candidate_safety output candidate_transcript_digest mismatch"
        )
    if transcript.candidate_unicode_scalar_count > MAX_CANDIDATE_UNICODE_SCALARS:
        raise RouteEvidenceContractError(
            "candidate_transcript candidate_unicode_scalar_count exceeds policy"
        )


def _validate_context_projection_event(
    event: Mapping[str, Any],
    *,
    request_event_id: str,
    context_snapshot_id: str,
    target_role: str,
    provider_session_generation: int,
) -> None:
    _require_mapping(event, "context_projection_event")
    _validate_canonical_envelope(event, "context_projection_event")
    _reject_forbidden_event_fields(event)
    expected = {
        "event_name": "MODEL_CONTEXT_PROJECTION_EMITTED",
        "event_id": request_event_id,
        "context_snapshot_id": context_snapshot_id,
        "target_role": target_role,
        "provider_session_generation": provider_session_generation,
        "redaction_status": "metadata_only",
        "output_mode": "mock",
    }
    for name, value in expected.items():
        if event.get(name) != value:
            raise RouteEvidenceContractError(
                f"context_projection_event {name} mismatch"
            )
    _require_ref(str(event.get("projection_ref", "")), "projection_ref")
    _require_token(str(event.get("policy_version", "")), "context_policy_version")
    source_event_seq = event.get("source_event_seq")
    if (
        isinstance(source_event_seq, bool)
        or not isinstance(source_event_seq, int)
        or source_event_seq < 1
    ):
        raise RouteEvidenceContractError(
            "context_projection_event source_event_seq mismatch"
        )
    source_event_ids = event.get("source_event_ids")
    if (
        not isinstance(source_event_ids, (tuple, list))
        or not source_event_ids
        or any(
            not isinstance(item, str) or _SYMBOLIC_TOKEN.fullmatch(item) is None
            for item in source_event_ids
        )
    ):
        raise RouteEvidenceContractError(
            "context_projection_event source_event_ids mismatch"
        )


def _validate_route_projection_causality(
    final_asr_event: Mapping[str, Any],
    context_projection_event: Mapping[str, Any],
) -> None:
    for field_name in ("session_id", "conversation_id"):
        if final_asr_event.get(field_name) != context_projection_event.get(
            field_name
        ):
            raise RouteEvidenceContractError(
                f"context_projection_event {field_name} mismatch"
            )
    final_seq = int(final_asr_event["event_seq"])
    context_seq = int(context_projection_event["event_seq"])
    if final_seq >= context_seq:
        raise RouteEvidenceContractError(
            "context_projection_event event_seq must follow final ASR"
        )
    if final_asr_event["event_id"] not in context_projection_event[
        "source_event_ids"
    ]:
        raise RouteEvidenceContractError(
            "context_projection_event source_event_ids must include final ASR"
        )


def _validate_canonical_envelope(
    event: Mapping[str, Any],
    label: str,
) -> None:
    for field_name in (
        "event_id",
        "event_schema_version",
        "session_id",
        "conversation_id",
        "source_module",
    ):
        try:
            _require_token(event.get(field_name), field_name)
        except RouteEvidenceContractError as exc:
            raise RouteEvidenceContractError(
                f"{label} {field_name} mismatch"
            ) from exc
    event_seq = event.get("event_seq")
    if isinstance(event_seq, bool) or not isinstance(event_seq, int) or event_seq < 1:
        raise RouteEvidenceContractError(f"{label} event_seq mismatch")
    for timestamp_field in (
        "created_monotonic_ms",
        "created_wall_clock_ms",
    ):
        try:
            _require_timestamp(event.get(timestamp_field), timestamp_field)
        except RouteEvidenceContractError as exc:
            raise RouteEvidenceContractError(
                f"{label} {timestamp_field} mismatch"
            ) from exc
    if event.get("trace_redaction_level") != "metadata_only":
        raise RouteEvidenceContractError(
            f"{label} trace_redaction_level mismatch"
        )


def _reject_forbidden_event_fields(
    event: Mapping[str, Any],
    *,
    allowed: frozenset[str] = frozenset(),
) -> None:
    forbidden = (_FORBIDDEN_EVENT_FIELDS - allowed).intersection(event)
    if forbidden:
        raise RouteEvidenceContractError(
            f"event contains forbidden field {sorted(forbidden)[0]}"
        )


def _require_mapping(value: object, name: str) -> None:
    if not isinstance(value, Mapping):
        raise RouteEvidenceContractError(f"invalid_{name}")


def _require_boundary(boundary: object) -> None:
    if not isinstance(boundary, AdapterCallbackAppendBoundary):
        raise RouteEvidenceContractError("invalid_adapter_callback_boundary")


def _preflight(boundary: AdapterCallbackAppendBoundary, event_id: str) -> None:
    try:
        boundary.require_event_ids_available(event_id)
    except AdapterCallbackBoundaryError as exc:
        raise RouteEvidenceContractError(str(exc)) from exc


def _require_recorded_predecessor(
    boundary: AdapterCallbackAppendBoundary,
    event: Mapping[str, Any],
) -> None:
    try:
        boundary.require_recorded_event(event)
    except AdapterCallbackBoundaryError as exc:
        raise RouteEvidenceContractError(str(exc)) from exc


def _require_token(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or _SYMBOLIC_TOKEN.fullmatch(value) is None
        or _contains_forbidden_value(value)
    ):
        raise RouteEvidenceContractError(f"invalid_{name}")
    return value


def _require_ref(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or _SAFE_REF.fullmatch(value) is None
        or _contains_forbidden_value(value)
    ):
        raise RouteEvidenceContractError(f"invalid_{name}")
    return value


def _require_ephemeral_text_ref(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or _EPHEMERAL_TEXT_REF.fullmatch(value) is None
        or _contains_forbidden_value(value)
    ):
        raise RouteEvidenceContractError(f"invalid_{name}")
    return value


def _require_optional_ref(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _require_ref(value, name)


def _require_digest(value: object, name: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise RouteEvidenceContractError(f"invalid_{name}")
    return value


def _require_confidence(value: object, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 0.0 <= float(value) <= 1.0
    ):
        raise RouteEvidenceContractError(f"invalid_{name}")
    return float(value)


def _require_enum(value: object, allowed: frozenset[str], name: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise RouteEvidenceContractError(f"invalid_{name}")
    return value


def _require_symbolic_items(
    value: Sequence[str],
    name: str,
) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise RouteEvidenceContractError(f"invalid_{name}")
    normalized = tuple(value)
    if len(normalized) > MAX_SYMBOLIC_ITEMS:
        raise RouteEvidenceContractError(f"{name} exceeds policy")
    if any(
        not isinstance(item, str)
        or len(item) > MAX_SYMBOLIC_ITEM_CHARS
        or _SYMBOLIC_ITEM.fullmatch(item) is None
        or _contains_forbidden_value(item)
        for item in normalized
    ):
        raise RouteEvidenceContractError(f"invalid_{name}")
    if len(set(normalized)) != len(normalized):
        raise RouteEvidenceContractError(f"duplicate_{name}")
    return normalized


def _normalize_failure_symbol(reason: object) -> str:
    if not isinstance(reason, str):
        return "validation_failure"
    symbol = re.sub(r"[^A-Za-z0-9._~-]+", "_", reason).strip("_").lower()
    if not symbol or len(symbol) > MAX_SYMBOLIC_ITEM_CHARS:
        return "validation_failure"
    if _contains_forbidden_value(symbol):
        return "validation_failure"
    return symbol


def _require_timestamp(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RouteEvidenceContractError(f"invalid_{name}")
    return value


def _contains_forbidden_value(value: str) -> bool:
    lowered = value.lower()
    return bool(
        _CREDENTIAL_LIKE_VALUE.search(value)
        or any(term in lowered for term in _FORBIDDEN_VALUE_TERMS)
    )


__all__ = [
    "ACK_KINDS",
    "CANDIDATE_SAFETY_CONFIDENCE_THRESHOLD",
    "CANDIDATE_SAFETY_DECISIONS",
    "CANDIDATE_SAFETY_SCHEMA_NAME",
    "CandidateSafetyEvidenceV1",
    "CandidateSafetyRequestV1",
    "EVIDENCE_UNCERTAINTIES",
    "FOREGROUND_ACT_HINTS",
    "MAX_ASR_UNICODE_SCALARS",
    "MAX_CANDIDATE_UNICODE_SCALARS",
    "RISK_CLASSES",
    "ROUTE_CONFIDENCE_THRESHOLD",
    "ROUTE_EVIDENCE_SCHEMA_NAME",
    "ROUTE_HINTS",
    "RouteEvidenceAdapter",
    "RouteEvidenceContractError",
    "RouteEvidenceOutputV1",
    "RouteEvidenceRequestV1",
    "TASK_FOCUS_HINTS",
    "emit_candidate_safety_evidence_output_event",
    "emit_route_evidence_output_event",
]
