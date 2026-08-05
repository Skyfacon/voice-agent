from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import re
from typing import Any

from voice_agent.adapters.parallel_fast_interaction_profile import (
    build_parallel_fast_interaction_orchestrator_profile,
)
from voice_agent.adapters.qwen_realtime.profile import (
    build_qwen_realtime_asr_fake_profile,
    build_qwen_realtime_fake_profile,
)
from voice_agent.adapters.qwen_realtime.projections import (
    CandidateCompletionV1,
    CandidateEligibilityFactsV1,
)
from voice_agent.events.envelope import EventValidationError, validate_event_envelope
from voice_agent.runtime.adapter_callback_boundary import (
    AdapterCallbackAppendBoundary,
    AdapterCallbackBoundaryError,
)


_SAFE_ID = re.compile(r"\A[A-Za-z0-9._~-]{1,160}\Z")
_CANDIDATE_REF = re.compile(
    r"\Acandidate-ref://(?:synthetic|local)/[A-Za-z0-9._~-]+"
    r"(?:/[A-Za-z0-9._~-]+)*\Z"
)
_CANDIDATE_AUDIO_FORMAT_REF_V1 = re.compile(
    r"\A(?=.{1,240}\Z)audio-format://(?:synthetic|local)/"
    r"[A-Za-z0-9][A-Za-z0-9._~-]{0,79}"
    r"(?:/[A-Za-z0-9][A-Za-z0-9._~-]{0,79})*\Z"
)
_SAFE_REF = re.compile(r"\A[a-z][a-z0-9-]{0,31}://[A-Za-z0-9._~/-]{1,240}\Z")
_SHA256_DIGEST = re.compile(r"\A(?:sha256:)?[0-9a-f]{64}\Z")
_PARALLEL_TOPOLOGY = "speculative_candidate_parallel_route"
_ROUTE_SCHEMA = "voice_agent.route_evidence.output.v1"
_SAFETY_SCHEMA = "voice_agent.candidate_safety.output.v1"
_FAST_SCHEMA = "voice_agent.fast_interaction.output.v1"
_MAX_CANDIDATE_UNICODE_SCALARS = 80
_MAX_CANDIDATE_AUDIO_DURATION_MS = 2_000
_FORBIDDEN_EVIDENCE_FIELDS = frozenset(
    {
        "audio_bytes",
        "audio_payload",
        "candidate_ref",
        "candidate_text",
        "pcm",
        "prompt",
        "provider_body",
        "provider_payload",
        "provider_request",
        "provider_response",
        "raw_audio",
        "raw_pcm",
        "raw_prompt",
        "raw_text",
        "text",
        "transcript",
        "transcript_text",
        "tool_result",
        "private_reasoning",
    }
)


class ParallelFastInteractionOrchestratorError(ValueError):
    """Sanitized fail-closed error at the local evidence-join boundary."""


@dataclass(frozen=True, slots=True)
class ParallelEmissionEventIds:
    fast_interaction_output_event_id: str
    candidate_event_id: str

    def __post_init__(self) -> None:
        _require_id(
            self.fast_interaction_output_event_id,
            "fast_interaction_output_event_id",
        )
        _require_id(self.candidate_event_id, "candidate_event_id")
        if self.fast_interaction_output_event_id == self.candidate_event_id:
            raise ParallelFastInteractionOrchestratorError(
                "parallel emission event IDs must be distinct"
            )


@dataclass(frozen=True, slots=True)
class ParallelFastInteractionEmissionV1:
    fast_interaction_output_event: dict[str, Any]
    candidate_event: dict[str, Any]


class ParallelFastInteractionOrchestrator:
    """Join already-recorded evidence without model, Router, Gate, or release authority."""

    def __init__(
        self,
        *,
        boundary: AdapterCallbackAppendBoundary,
        adapter_request_id: str,
        qwen_candidate_adapter_request_id: str,
    ) -> None:
        if not isinstance(boundary, AdapterCallbackAppendBoundary):
            raise ParallelFastInteractionOrchestratorError("invalid_boundary")
        self._boundary = boundary
        self._adapter_request_id = _require_id(
            adapter_request_id,
            "adapter_request_id",
        )
        self._qwen_candidate_adapter_request_id = _require_id(
            qwen_candidate_adapter_request_id,
            "qwen_candidate_adapter_request_id",
        )
        self._profile = build_parallel_fast_interaction_orchestrator_profile()
        self._qwen_profile = build_qwen_realtime_fake_profile()
        self._qwen_asr_profile = build_qwen_realtime_asr_fake_profile()

    def emit(
        self,
        *,
        final_asr_event: Mapping[str, Any],
        route_evidence_event: Mapping[str, Any],
        candidate_safety_event: Mapping[str, Any],
        candidate: CandidateCompletionV1,
        event_ids: ParallelEmissionEventIds,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
    ) -> ParallelFastInteractionEmissionV1:
        if not isinstance(event_ids, ParallelEmissionEventIds):
            raise ParallelFastInteractionOrchestratorError("invalid_event_ids")
        _require_nonnegative_int(created_monotonic_ms, "created_monotonic_ms")
        _require_nonnegative_int(created_wall_clock_ms, "created_wall_clock_ms")

        final_asr = self._validated_final_asr(final_asr_event)
        route = _validated_evidence_event(
            route_evidence_event,
            event_name="ROUTE_EVIDENCE_OUTPUT_EMITTED",
            schema_name=_ROUTE_SCHEMA,
            label="route_evidence",
        )
        safety = _validated_evidence_event(
            candidate_safety_event,
            event_name="CANDIDATE_SAFETY_EVIDENCE_OUTPUT_EMITTED",
            schema_name=_SAFETY_SCHEMA,
            label="candidate_safety",
        )
        facts = _validated_candidate(candidate)

        self._validate_join(
            final_asr=final_asr,
            route=route,
            safety=safety,
            candidate=candidate,
            facts=facts,
        )
        try:
            self._boundary.require_recorded_event(final_asr)
            self._boundary.require_recorded_event(route)
            self._boundary.require_recorded_event(safety)
        except AdapterCallbackBoundaryError as exc:
            raise ParallelFastInteractionOrchestratorError(
                "recorded_predecessor_mismatch"
            ) from exc
        try:
            self._boundary.require_event_ids_available(
                event_ids.fast_interaction_output_event_id,
                event_ids.candidate_event_id,
            )
        except AdapterCallbackBoundaryError as exc:
            raise ParallelFastInteractionOrchestratorError(str(exc)) from exc

        route_event_id = _event_id(route, "route_evidence")
        safety_event_id = _event_id(safety, "candidate_safety")
        final_asr_event_id = _event_id(final_asr, "final_asr")
        evidence_events = sorted(
            (route, safety),
            key=lambda event: _positive_event_seq(event, "evidence"),
        )
        source_event_ids = (
            final_asr_event_id,
            *(_event_id(event, "evidence") for event in evidence_events),
        )
        caused_by_event_id = _event_id(evidence_events[-1], "evidence")
        evidence_digest = _safe_join_digest(
            (
                final_asr_event_id,
                route_event_id,
                safety_event_id,
                facts.candidate_transcript_digest,
                facts.candidate_pcm_manifest_digest,
            )
        )
        route_digest = _safe_join_digest((route_event_id,))
        confidence = min(
            _confidence(route.get("confidence"), "route_evidence"),
            _confidence(safety.get("confidence"), "candidate_safety"),
        )
        risk_tags = _safe_string_tuple(route.get("risk_tags"), "risk_tags")

        try:
            output_event = self._boundary.append_adapter_event(
                event_name="FAST_INTERACTION_OUTPUT_EMITTED",
                event_id=event_ids.fast_interaction_output_event_id,
                source_module="slice3b1_parallel_fast_interaction_orchestrator",
                caused_by_event_id=caused_by_event_id,
                created_monotonic_ms=created_monotonic_ms,
                created_wall_clock_ms=created_wall_clock_ms,
                trace_redaction_level="metadata_only",
                adapter_id=self._profile.adapter_id,
                adapter_type="fast_interaction",
                adapter_request_id=self._adapter_request_id,
                turn_id=facts.turn_id,
                utterance_id=facts.utterance_id,
                route_hint_ref=f"route-hint://slice3b1/{route_digest}",
                route_prelude_ref=f"route-prelude://slice3b1/{route_digest}",
                foreground_act=str(route["foreground_act_hint"]),
                final_fast_evidence_ref=f"fast-evidence://slice3b1/{evidence_digest}",
                schema_name=_FAST_SCHEMA,
                normalization_status="normalized",
                output_mode="mock",
                input_mode="audio_native",
                fast_interaction_input_mode="audio_native",
                source_event_ids=source_event_ids,
                risk_tags=risk_tags,
                risk_class=str(route["risk_class"]),
                confidence=confidence,
                fast_interaction_topology=_PARALLEL_TOPOLOGY,
                qwen_candidate_adapter_id=self._qwen_profile.adapter_id,
                qwen_candidate_adapter_request_id=(
                    self._qwen_candidate_adapter_request_id
                ),
                route_evidence_event_id=route_event_id,
                route_evidence_adapter_request_id=_event_string(
                    route,
                    "adapter_request_id",
                    "route_evidence",
                ),
                candidate_safety_evidence_event_id=safety_event_id,
                candidate_safety_adapter_request_id=_event_string(
                    safety,
                    "adapter_request_id",
                    "candidate_safety",
                ),
                context_snapshot_id=facts.context_snapshot_id,
                provider_session_generation=facts.provider_session_generation,
            )
            candidate_event = self._boundary.append_adapter_event(
                event_name="FOREGROUND_REPLY_CANDIDATE_EMITTED",
                event_id=event_ids.candidate_event_id,
                source_module="slice3b1_candidate_quarantine",
                caused_by_event_id=str(output_event["event_id"]),
                created_monotonic_ms=created_monotonic_ms + 1,
                created_wall_clock_ms=created_wall_clock_ms + 1,
                trace_redaction_level="metadata_only",
                candidate_id=facts.candidate_id,
                fast_interaction_output_event_id=str(output_event["event_id"]),
                turn_id=facts.turn_id,
                utterance_id=facts.utterance_id,
                candidate_ref=candidate.candidate_ref,
                candidate_status="complete",
                input_mode="audio_native",
                fast_interaction_input_mode="audio_native",
                source_event_ids=(
                    *source_event_ids,
                    str(output_event["event_id"]),
                ),
                risk_tags=risk_tags,
                confidence=confidence,
                fast_interaction_topology=_PARALLEL_TOPOLOGY,
                qwen_response_id=facts.qwen_response_id,
                qwen_output_item_id=facts.qwen_output_item_id,
                qwen_output_index=facts.qwen_output_index,
                qwen_content_index=facts.qwen_content_index,
                candidate_transcript_digest=facts.candidate_transcript_digest,
                candidate_pcm_manifest_digest=facts.candidate_pcm_manifest_digest,
                candidate_audio_format_ref=facts.candidate_audio_format_ref,
                candidate_audio_duration_ms=facts.candidate_audio_duration_ms,
                provider_session_generation=facts.provider_session_generation,
                context_snapshot_id=facts.context_snapshot_id,
                route_evidence_event_id=route_event_id,
                candidate_safety_evidence_event_id=safety_event_id,
            )
        except (AdapterCallbackBoundaryError, EventValidationError, ValueError) as exc:
            raise ParallelFastInteractionOrchestratorError(
                "parallel_evidence_append_failed"
            ) from exc
        return ParallelFastInteractionEmissionV1(
            fast_interaction_output_event=output_event,
            candidate_event=candidate_event,
        )

    def _validated_final_asr(
        self,
        event: Mapping[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(event, Mapping):
            raise ParallelFastInteractionOrchestratorError("invalid_final_asr_event")
        _reject_forbidden_fields(event, "final_asr")
        try:
            validated = validate_event_envelope(event)
        except (EventValidationError, TypeError, ValueError) as exc:
            raise ParallelFastInteractionOrchestratorError(
                "invalid_final_asr_event"
            ) from exc
        if validated.get("event_name") != "ASR_TRANSCRIPT_OUTPUT_EMITTED":
            raise ParallelFastInteractionOrchestratorError(
                "final_asr_event_name_mismatch"
            )
        if validated.get("adapter_id") != self._qwen_asr_profile.adapter_id:
            raise ParallelFastInteractionOrchestratorError(
                "final_asr_adapter_id_mismatch"
            )
        if (
            validated.get("adapter_type") != "asr"
            or validated.get("transcript_finality") != "final"
            or validated.get("output_mode") != "mock"
        ):
            raise ParallelFastInteractionOrchestratorError(
                "invalid_final_asr_normalization"
            )
        _positive_int_field(
            validated,
            "provider_session_generation",
            "final_asr_generation",
        )
        _event_ref(validated, "qwen_input_item_ref", "final_asr")
        _nonnegative_int_field(
            validated,
            "qwen_input_content_index",
            "final_asr",
        )
        return validated

    @staticmethod
    def _validate_join(
        *,
        final_asr: Mapping[str, Any],
        route: Mapping[str, Any],
        safety: Mapping[str, Any],
        candidate: CandidateCompletionV1,
        facts: CandidateEligibilityFactsV1,
    ) -> None:
        turn_id = facts.turn_id
        utterance_id = facts.utterance_id
        for event, label in (
            (final_asr, "final_asr"),
            (route, "route_evidence"),
            (safety, "candidate_safety"),
        ):
            if event.get("turn_id") != turn_id:
                raise ParallelFastInteractionOrchestratorError(
                    f"{label}_turn_id_mismatch"
                )
            if event.get("utterance_id") != utterance_id:
                raise ParallelFastInteractionOrchestratorError(
                    f"{label}_utterance_id_mismatch"
                )

        final_asr_event_id = _event_id(final_asr, "final_asr")
        if route.get("final_asr_event_id") != final_asr_event_id:
            raise ParallelFastInteractionOrchestratorError(
                "route_evidence_final_asr_event_id_mismatch"
            )
        if safety.get("qwen_response_id") != facts.qwen_response_id:
            raise ParallelFastInteractionOrchestratorError(
                "candidate_safety_qwen_response_id_mismatch"
            )
        route_event_id = _event_id(route, "route_evidence")
        if safety.get("route_evidence_event_id") not in (
            None,
            route_event_id,
        ):
            raise ParallelFastInteractionOrchestratorError(
                "candidate_safety_route_evidence_event_id_mismatch"
            )
        if (
            safety.get("candidate_transcript_digest")
            != facts.candidate_transcript_digest
        ):
            raise ParallelFastInteractionOrchestratorError(
                "candidate_safety_transcript_digest_mismatch"
            )
        if candidate.candidate_ref != candidate.candidate_ref.strip():
            raise ParallelFastInteractionOrchestratorError(
                "candidate_ref_not_canonical"
            )

        final_generation = _positive_int_field(
            final_asr,
            "provider_session_generation",
            "final_asr",
        )
        for event, label in (
            (route, "route_evidence"),
            (safety, "candidate_safety"),
        ):
            if (
                _positive_int_field(
                    event,
                    "provider_session_generation",
                    label,
                )
                != facts.provider_session_generation
            ):
                raise ParallelFastInteractionOrchestratorError(
                    f"{label}_generation_mismatch"
                )
            if event.get("context_snapshot_id") != facts.context_snapshot_id:
                raise ParallelFastInteractionOrchestratorError(
                    f"{label}_context_snapshot_mismatch"
                )
            if _positive_event_seq(event, label) <= _positive_event_seq(
                final_asr,
                "final_asr",
            ):
                raise ParallelFastInteractionOrchestratorError(
                    f"{label}_must_follow_final_asr"
                )
        if final_generation != facts.provider_session_generation:
            raise ParallelFastInteractionOrchestratorError(
                "final_asr_generation_mismatch"
            )
        if (
            route.get("context_projection_event_id")
            == safety.get("context_projection_event_id")
        ):
            raise ParallelFastInteractionOrchestratorError(
                "route_and_safety_context_projections_must_be_distinct"
            )
        if route.get("adapter_id") != safety.get("adapter_id"):
            raise ParallelFastInteractionOrchestratorError(
                "route_evidence_adapter_id_mismatch"
            )


def _validated_evidence_event(
    event: Mapping[str, Any],
    *,
    event_name: str,
    schema_name: str,
    label: str,
) -> dict[str, Any]:
    if not isinstance(event, Mapping):
        raise ParallelFastInteractionOrchestratorError(f"invalid_{label}_event")
    _reject_forbidden_fields(event, label)
    try:
        validated = validate_event_envelope(event)
    except (EventValidationError, TypeError, ValueError) as exc:
        raise ParallelFastInteractionOrchestratorError(
            f"invalid_{label}_event"
        ) from exc
    if validated.get("event_name") != event_name:
        raise ParallelFastInteractionOrchestratorError(
            f"{label}_event_name_mismatch"
        )
    if (
        validated.get("adapter_type") != "route_evidence"
        or validated.get("schema_name") != schema_name
        or validated.get("normalization_status") != "normalized"
        or validated.get("output_mode") != "mock"
    ):
        raise ParallelFastInteractionOrchestratorError(
            f"{label}_normalization_or_schema_mismatch"
        )
    _event_id(validated, label)
    _positive_event_seq(validated, label)
    _event_string(validated, "context_projection_event_id", label)
    _event_string(validated, "context_snapshot_id", label)
    _positive_int_field(validated, "provider_session_generation", label)
    _confidence(validated.get("confidence"), label)
    if label == "route_evidence":
        _safe_string_tuple(validated.get("risk_tags"), "risk_tags")
    else:
        _safe_string_tuple(
            validated.get("semantic_categories"),
            "semantic_categories",
            max_items=8,
        )
        _safe_string_tuple(
            validated.get("prohibited_flags"),
            "prohibited_flags",
            max_items=8,
        )
    return validated


def _validated_candidate(candidate: object) -> CandidateEligibilityFactsV1:
    if not isinstance(candidate, CandidateCompletionV1):
        raise ParallelFastInteractionOrchestratorError(
            "candidate must be CandidateCompletionV1"
        )
    if _CANDIDATE_REF.fullmatch(candidate.candidate_ref) is None:
        raise ParallelFastInteractionOrchestratorError(
            "invalid_candidate_ref"
        )
    facts = candidate.eligibility_facts
    if not isinstance(facts, CandidateEligibilityFactsV1):
        raise ParallelFastInteractionOrchestratorError(
            "invalid_candidate_eligibility_facts"
        )
    for field in (
        "qwen_response_id",
        "qwen_output_item_id",
        "candidate_id",
        "turn_id",
        "utterance_id",
        "context_snapshot_id",
    ):
        _require_id(getattr(facts, field), field)
    _require_positive_int(
        facts.provider_session_generation,
        "provider_session_generation",
    )
    _require_nonnegative_int(facts.qwen_output_index, "qwen_output_index")
    _require_nonnegative_int(facts.qwen_content_index, "qwen_content_index")
    _require_nonnegative_int(facts.bound_playback_epoch, "bound_playback_epoch")
    if (
        facts.candidate_unicode_scalar_count < 1
        or facts.candidate_unicode_scalar_count
        > _MAX_CANDIDATE_UNICODE_SCALARS
    ):
        raise ParallelFastInteractionOrchestratorError(
            "candidate_unicode_scalar_count exceeds 80"
        )
    if (
        facts.candidate_audio_duration_ms < 1
        or facts.candidate_audio_duration_ms
        > _MAX_CANDIDATE_AUDIO_DURATION_MS
    ):
        raise ParallelFastInteractionOrchestratorError(
            "candidate_audio_duration_ms exceeds 2000"
        )
    _require_digest(
        facts.candidate_transcript_digest,
        "candidate_transcript_digest",
    )
    _require_digest(
        facts.candidate_pcm_manifest_digest,
        "candidate_pcm_manifest_digest",
    )
    if (
        _CANDIDATE_AUDIO_FORMAT_REF_V1.fullmatch(
            facts.candidate_audio_format_ref
        )
        is None
    ):
        raise ParallelFastInteractionOrchestratorError(
            "invalid_candidate_audio_format_ref"
        )
    if facts.provider_terminal_status != "completed":
        raise ParallelFastInteractionOrchestratorError(
            "candidate_provider_terminal_not_completed"
        )
    return facts


def _reject_forbidden_fields(event: Mapping[str, Any], label: str) -> None:
    if any(str(field).lower() in _FORBIDDEN_EVIDENCE_FIELDS for field in event):
        raise ParallelFastInteractionOrchestratorError(
            f"{label}_contains_forbidden_payload"
        )


def _event_id(event: Mapping[str, Any], label: str) -> str:
    return _event_string(event, "event_id", label)


def _event_string(event: Mapping[str, Any], field: str, label: str) -> str:
    value = event.get(field)
    try:
        return _require_id(value, field)
    except ParallelFastInteractionOrchestratorError as exc:
        raise ParallelFastInteractionOrchestratorError(
            f"invalid_{label}_{field}"
        ) from exc


def _event_ref(event: Mapping[str, Any], field: str, label: str) -> str:
    value = event.get(field)
    if (
        not isinstance(value, str)
        or (
            _SAFE_ID.fullmatch(value) is None
            and _SAFE_REF.fullmatch(value) is None
        )
        or value.lower().startswith(("http://", "https://", "file://"))
    ):
        raise ParallelFastInteractionOrchestratorError(
            f"invalid_{label}_{field}"
        )
    return value


def _positive_event_seq(event: Mapping[str, Any], label: str) -> int:
    return _positive_int_field(event, "event_seq", label)


def _positive_int_field(
    event: Mapping[str, Any],
    field: str,
    label: str,
) -> int:
    value = event.get(field)
    try:
        return _require_positive_int(value, field)
    except ParallelFastInteractionOrchestratorError as exc:
        raise ParallelFastInteractionOrchestratorError(
            f"invalid_{label}_{field}"
        ) from exc


def _nonnegative_int_field(
    event: Mapping[str, Any],
    field: str,
    label: str,
) -> int:
    value = event.get(field)
    try:
        return _require_nonnegative_int(value, field)
    except ParallelFastInteractionOrchestratorError as exc:
        raise ParallelFastInteractionOrchestratorError(
            f"invalid_{label}_{field}"
        ) from exc


def _require_id(value: object, field: str) -> str:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise ParallelFastInteractionOrchestratorError(f"invalid_{field}")
    return value


def _require_positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ParallelFastInteractionOrchestratorError(f"invalid_{field}")
    return value


def _require_nonnegative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ParallelFastInteractionOrchestratorError(f"invalid_{field}")
    return value


def _require_digest(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256_DIGEST.fullmatch(value) is None:
        raise ParallelFastInteractionOrchestratorError(f"invalid_{field}")
    return value


def _confidence(value: object, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or float(value) < 0.0
        or float(value) > 1.0
    ):
        raise ParallelFastInteractionOrchestratorError(
            f"invalid_{label}_confidence"
        )
    return float(value)


def _safe_string_tuple(
    value: object,
    field: str,
    *,
    max_items: int = 16,
) -> tuple[str, ...]:
    if (
        isinstance(value, (str, bytes))
        or not isinstance(value, Sequence)
        or len(value) > max_items
    ):
        raise ParallelFastInteractionOrchestratorError(f"invalid_{field}")
    result = tuple(_require_id(item, field) for item in value)
    return result


def _safe_join_digest(values: tuple[str, ...]) -> str:
    encoded = "\x1f".join(values).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "ParallelEmissionEventIds",
    "ParallelFastInteractionEmissionV1",
    "ParallelFastInteractionOrchestrator",
    "ParallelFastInteractionOrchestratorError",
]
