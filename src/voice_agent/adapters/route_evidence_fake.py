from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Any

from voice_agent.adapters.qwen_realtime.ephemeral_text_store import (
    EphemeralTextRefV1,
    EphemeralTextStore,
    EphemeralTextStoreError,
)
from voice_agent.adapters.qwen_realtime.projections import (
    CandidateTranscriptCompleteV1,
)
from voice_agent.adapters.route_evidence_contract import (
    CANDIDATE_SAFETY_CONFIDENCE_THRESHOLD,
    MAX_ASR_UNICODE_SCALARS,
    MAX_CANDIDATE_UNICODE_SCALARS,
    ROUTE_CONFIDENCE_THRESHOLD,
    CandidateSafetyEvidenceV1,
    CandidateSafetyRequestV1,
    RouteEvidenceContractError,
    RouteEvidenceOutputV1,
    RouteEvidenceRequestV1,
)


class RouteEvidenceFakeDirective(str, Enum):
    FAST_ONLY = "FAST_ONLY"
    SPAWN_SLOW_TASK = "SPAWN_SLOW_TASK"
    PATCH_ACTIVE_SLOW_TASK = "PATCH_ACTIVE_SLOW_TASK"
    IGNORE = "IGNORE"
    ACTIVE_TASK_FOREGROUND_CHAT = "ACTIVE_TASK_FOREGROUND_CHAT"
    ACTIVE_TASK_NEW_TASK = "ACTIVE_TASK_NEW_TASK"
    ACTIVE_TASK_CANCEL_OR_CONFIRMATION = "ACTIVE_TASK_CANCEL_OR_CONFIRMATION"
    ACTIVE_TASK_AMBIGUOUS = "ACTIVE_TASK_AMBIGUOUS"
    TIMEOUT = "TIMEOUT"
    MALFORMED_JSON = "MALFORMED_JSON"
    UNKNOWN_ENUM = "UNKNOWN_ENUM"
    OVERSIZED_OUTPUT = "OVERSIZED_OUTPUT"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    PROHIBITED_RISK = "PROHIBITED_RISK"


class CandidateSafetyFakeDirective(str, Enum):
    SAFE = "SAFE"
    UNSAFE = "UNSAFE"
    UNCERTAIN = "UNCERTAIN"
    TIMEOUT = "TIMEOUT"
    MALFORMED_JSON = "MALFORMED_JSON"
    UNKNOWN_ENUM = "UNKNOWN_ENUM"
    OVERSIZED_OUTPUT = "OVERSIZED_OUTPUT"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    PROHIBITED_RISK = "PROHIBITED_RISK"


_ROUTE_OUTPUT_FIELDS = frozenset(
    {
        "route_hint",
        "task_focus_hint",
        "foreground_act_hint",
        "ack_kind",
        "risk_class",
        "risk_tags",
        "evidence_uncertainty",
        "confidence",
        "schema_name",
        "normalization_status",
        "output_mode",
    }
)
_CANDIDATE_SAFETY_OUTPUT_FIELDS = frozenset(
    {
        "decision",
        "semantic_categories",
        "prohibited_flags",
        "confidence",
        "candidate_transcript_digest",
        "schema_name",
        "normalization_status",
        "output_mode",
    }
)


class FakeRouteEvidenceAdapter:
    """Deterministic provider-free evidence adapter with scoped text leases."""

    __slots__ = (
        "_candidate_safety_directive",
        "_candidate_transcripts",
        "_route_directive",
        "_route_text_metadata",
        "_text_store",
    )

    def __init__(
        self,
        *,
        text_store: EphemeralTextStore,
        route_text_refs: Sequence[EphemeralTextRefV1] = (),
        candidate_transcript_completions: Sequence[
            CandidateTranscriptCompleteV1
        ] = (),
        route_directive: RouteEvidenceFakeDirective = RouteEvidenceFakeDirective.FAST_ONLY,
        candidate_safety_directive: CandidateSafetyFakeDirective = (
            CandidateSafetyFakeDirective.SAFE
        ),
    ) -> None:
        if not isinstance(text_store, EphemeralTextStore):
            raise RouteEvidenceContractError("invalid_ephemeral_text_store")
        if not isinstance(route_directive, RouteEvidenceFakeDirective):
            raise RouteEvidenceContractError("invalid_route_fake_directive")
        if not isinstance(candidate_safety_directive, CandidateSafetyFakeDirective):
            raise RouteEvidenceContractError(
                "invalid_candidate_safety_fake_directive"
            )
        if isinstance(route_text_refs, (str, bytes)) or not isinstance(
            route_text_refs,
            Sequence,
        ):
            raise RouteEvidenceContractError("invalid_route_text_refs")
        metadata_by_ref: dict[str, EphemeralTextRefV1] = {}
        for metadata in route_text_refs:
            if not isinstance(metadata, EphemeralTextRefV1):
                raise RouteEvidenceContractError("invalid_route_text_ref_metadata")
            if metadata.ref in metadata_by_ref:
                raise RouteEvidenceContractError("duplicate_route_text_ref")
            metadata_by_ref[metadata.ref] = metadata
        if isinstance(candidate_transcript_completions, (str, bytes)) or not isinstance(
            candidate_transcript_completions,
            Sequence,
        ):
            raise RouteEvidenceContractError(
                "invalid_candidate_transcript_completions"
            )
        transcripts_by_ref: dict[str, CandidateTranscriptCompleteV1] = {}
        for transcript in candidate_transcript_completions:
            if not isinstance(transcript, CandidateTranscriptCompleteV1):
                raise RouteEvidenceContractError(
                    "invalid_candidate_transcript_completion"
                )
            if transcript.candidate_ref in transcripts_by_ref:
                raise RouteEvidenceContractError(
                    "duplicate_candidate_transcript_completion"
                )
            transcripts_by_ref[transcript.candidate_ref] = transcript

        self._text_store = text_store
        self._route_text_metadata = metadata_by_ref
        self._candidate_transcripts = transcripts_by_ref
        self._route_directive = route_directive
        self._candidate_safety_directive = candidate_safety_directive

    async def classify_route(
        self,
        request: RouteEvidenceRequestV1,
    ) -> RouteEvidenceOutputV1:
        if not isinstance(request, RouteEvidenceRequestV1):
            return RouteEvidenceOutputV1.fail_closed("invalid_route_request")
        metadata = self._route_text_metadata.get(request.transcript_ref)
        if metadata is None:
            return RouteEvidenceOutputV1.fail_closed(
                "text_ref_not_registered"
            )
        try:
            with self._text_store.resolve(
                request.transcript_ref,
                expected_kind="asr",
                expected_digest=metadata.digest,
                max_unicode_scalars=MAX_ASR_UNICODE_SCALARS,
            ) as lease:
                if not lease.text:
                    return RouteEvidenceOutputV1.fail_closed("empty_transcript")
                raw_output = _route_output_for(self._route_directive)
        except EphemeralTextStoreError as exc:
            return RouteEvidenceOutputV1.fail_closed(str(exc))

        if self._route_directive is RouteEvidenceFakeDirective.TIMEOUT:
            return RouteEvidenceOutputV1.fail_closed("route_timeout")
        try:
            output = _parse_route_output(raw_output)
        except RouteEvidenceContractError as exc:
            return RouteEvidenceOutputV1.fail_closed(
                str(exc),
                prohibited_risk=(
                    self._route_directive
                    is RouteEvidenceFakeDirective.PROHIBITED_RISK
                ),
            )
        if output.confidence < ROUTE_CONFIDENCE_THRESHOLD:
            return RouteEvidenceOutputV1.fail_closed(
                "route_confidence_below_threshold"
            )
        if output.risk_class in {"HIGH", "UNKNOWN"}:
            return RouteEvidenceOutputV1.fail_closed(
                "prohibited_risk",
                prohibited_risk=True,
            )
        return output

    async def classify_candidate_safety(
        self,
        request: CandidateSafetyRequestV1,
    ) -> CandidateSafetyEvidenceV1:
        if not isinstance(request, CandidateSafetyRequestV1):
            return CandidateSafetyEvidenceV1.fail_closed(
                "0" * 64,
                "invalid_candidate_safety_request",
            )
        completion = self._candidate_transcripts.get(request.candidate_ref)
        if completion is None:
            return CandidateSafetyEvidenceV1.fail_closed(
                request.candidate_transcript_digest,
                "candidate_transcript_not_registered",
            )
        completion_failure = _candidate_completion_failure(request, completion)
        if completion_failure is not None:
            return CandidateSafetyEvidenceV1.fail_closed(
                request.candidate_transcript_digest,
                completion_failure,
            )
        try:
            with self._text_store.resolve(
                request.candidate_ref,
                expected_kind="candidate",
                expected_digest=request.candidate_transcript_digest,
                max_unicode_scalars=MAX_CANDIDATE_UNICODE_SCALARS,
            ) as lease:
                if not lease.text:
                    return CandidateSafetyEvidenceV1.fail_closed(
                        request.candidate_transcript_digest,
                        "empty_candidate",
                    )
                if (
                    len(lease.text)
                    != completion.candidate_unicode_scalar_count
                ):
                    return CandidateSafetyEvidenceV1.fail_closed(
                        request.candidate_transcript_digest,
                        "candidate_transcript_scalar_count_mismatch",
                    )
                raw_output = _candidate_safety_output_for(
                    self._candidate_safety_directive,
                    request.candidate_transcript_digest,
                )
        except EphemeralTextStoreError as exc:
            return CandidateSafetyEvidenceV1.fail_closed(
                request.candidate_transcript_digest,
                str(exc),
            )

        if self._candidate_safety_directive is CandidateSafetyFakeDirective.TIMEOUT:
            return CandidateSafetyEvidenceV1.fail_closed(
                request.candidate_transcript_digest,
                "candidate_safety_timeout",
            )
        try:
            output = _parse_candidate_safety_output(raw_output)
        except RouteEvidenceContractError as exc:
            return CandidateSafetyEvidenceV1.fail_closed(
                request.candidate_transcript_digest,
                str(exc),
            )
        if (
            output.decision == "SAFE"
            and output.confidence < CANDIDATE_SAFETY_CONFIDENCE_THRESHOLD
        ):
            return CandidateSafetyEvidenceV1.fail_closed(
                request.candidate_transcript_digest,
                "candidate_safety_confidence_below_threshold",
            )
        return output


def _candidate_completion_failure(
    request: CandidateSafetyRequestV1,
    completion: CandidateTranscriptCompleteV1,
) -> str | None:
    mismatch_reasons = {
        "turn_id": "candidate_transcript_turn_id_mismatch",
        "utterance_id": "candidate_transcript_utterance_id_mismatch",
        "qwen_response_id": "candidate_transcript_qwen_response_id_mismatch",
        "context_snapshot_id": (
            "candidate_transcript_context_snapshot_id_mismatch"
        ),
        "candidate_ref": "candidate_transcript_ref_mismatch",
        "candidate_transcript_digest": "candidate_transcript_digest_mismatch",
    }
    for field_name, reason in mismatch_reasons.items():
        if getattr(completion, field_name) != getattr(request, field_name):
            return reason
    if completion.candidate_unicode_scalar_count > MAX_CANDIDATE_UNICODE_SCALARS:
        return "candidate_transcript_scalar_count_over_bound"
    return None


def _parse_route_output(raw_output: Mapping[str, Any]) -> RouteEvidenceOutputV1:
    _require_exact_fields(raw_output, _ROUTE_OUTPUT_FIELDS, "route_output")
    return RouteEvidenceOutputV1(
        route_hint=raw_output["route_hint"],
        task_focus_hint=raw_output["task_focus_hint"],
        foreground_act_hint=raw_output["foreground_act_hint"],
        ack_kind=raw_output["ack_kind"],
        risk_class=raw_output["risk_class"],
        risk_tags=raw_output["risk_tags"],
        evidence_uncertainty=raw_output["evidence_uncertainty"],
        confidence=raw_output["confidence"],
        schema_name=raw_output["schema_name"],
        normalization_status=raw_output["normalization_status"],
        output_mode=raw_output["output_mode"],
    )


def _parse_candidate_safety_output(
    raw_output: Mapping[str, Any],
) -> CandidateSafetyEvidenceV1:
    _require_exact_fields(
        raw_output,
        _CANDIDATE_SAFETY_OUTPUT_FIELDS,
        "candidate_safety_output",
    )
    return CandidateSafetyEvidenceV1(
        decision=raw_output["decision"],
        semantic_categories=raw_output["semantic_categories"],
        prohibited_flags=raw_output["prohibited_flags"],
        confidence=raw_output["confidence"],
        candidate_transcript_digest=raw_output["candidate_transcript_digest"],
        schema_name=raw_output["schema_name"],
        normalization_status=raw_output["normalization_status"],
        output_mode=raw_output["output_mode"],
    )


def _require_exact_fields(
    raw_output: Mapping[str, Any],
    expected: frozenset[str],
    name: str,
) -> None:
    if not isinstance(raw_output, Mapping):
        raise RouteEvidenceContractError(f"{name}_malformed")
    actual = frozenset(raw_output)
    if actual != expected:
        raise RouteEvidenceContractError(f"{name}_schema_mismatch")


def _route_output_for(
    directive: RouteEvidenceFakeDirective,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "route_hint": "FAST_ONLY",
        "task_focus_hint": "FOREGROUND_CHAT",
        "foreground_act_hint": "ANSWER",
        "ack_kind": "CHAT",
        "risk_class": "LOW",
        "risk_tags": ("low_risk",),
        "evidence_uncertainty": "LOW",
        "confidence": 0.98,
        "schema_name": "voice_agent.route_evidence.output.v1",
        "normalization_status": "normalized",
        "output_mode": "mock",
    }
    updates: dict[RouteEvidenceFakeDirective, dict[str, Any]] = {
        RouteEvidenceFakeDirective.SPAWN_SLOW_TASK: {
            "route_hint": "SPAWN_SLOW_TASK",
            "task_focus_hint": "NEW_TASK_CANDIDATE",
            "foreground_act_hint": "ACK_SLOW",
            "ack_kind": "PLAN_ACCEPTED",
        },
        RouteEvidenceFakeDirective.PATCH_ACTIVE_SLOW_TASK: {
            "route_hint": "PATCH_ACTIVE_SLOW_TASK",
            "task_focus_hint": "ACTIVE_TASK_PATCH",
            "foreground_act_hint": "ACK_PATCH",
            "ack_kind": "PATCH_RECEIVED",
        },
        RouteEvidenceFakeDirective.IGNORE: {
            "route_hint": "IGNORE",
            "task_focus_hint": "NON_ASSISTANT",
            "foreground_act_hint": "SILENCE",
            "ack_kind": "SILENCE",
        },
        RouteEvidenceFakeDirective.ACTIVE_TASK_FOREGROUND_CHAT: {},
        RouteEvidenceFakeDirective.ACTIVE_TASK_NEW_TASK: {
            "route_hint": "SPAWN_SLOW_TASK",
            "task_focus_hint": "NEW_TASK_CANDIDATE",
            "foreground_act_hint": "ACK_SLOW",
            "ack_kind": "PLAN_ACCEPTED",
        },
        RouteEvidenceFakeDirective.ACTIVE_TASK_CANCEL_OR_CONFIRMATION: {
            "route_hint": "PATCH_ACTIVE_SLOW_TASK",
            "task_focus_hint": "CANCEL_OR_PAUSE_CANDIDATE",
            "foreground_act_hint": "CLARIFY",
            "ack_kind": "WAITING_CONFIRMATION",
        },
        RouteEvidenceFakeDirective.ACTIVE_TASK_AMBIGUOUS: {
            "route_hint": "IGNORE",
            "task_focus_hint": "AMBIGUOUS",
            "foreground_act_hint": "CLARIFY",
            "ack_kind": "CLARIFY_NEEDED",
            "evidence_uncertainty": "HIGH",
        },
        RouteEvidenceFakeDirective.UNKNOWN_ENUM: {
            "route_hint": "UNKNOWN_ROUTE",
        },
        RouteEvidenceFakeDirective.OVERSIZED_OUTPUT: {
            "risk_tags": tuple(f"risk_{index}" for index in range(9)),
        },
        RouteEvidenceFakeDirective.LOW_CONFIDENCE: {
            "confidence": 0.20,
            "evidence_uncertainty": "HIGH",
        },
        RouteEvidenceFakeDirective.PROHIBITED_RISK: {
            "risk_class": "HIGH",
            "risk_tags": ("prohibited_risk",),
        },
        RouteEvidenceFakeDirective.TIMEOUT: {},
        RouteEvidenceFakeDirective.FAST_ONLY: {},
    }
    if directive is RouteEvidenceFakeDirective.MALFORMED_JSON:
        return {"route_hint": "FAST_ONLY"}
    base.update(updates[directive])
    return base


def _candidate_safety_output_for(
    directive: CandidateSafetyFakeDirective,
    candidate_transcript_digest: str,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "decision": "SAFE",
        "semantic_categories": ("general_assistance",),
        "prohibited_flags": (),
        "confidence": 0.99,
        "candidate_transcript_digest": candidate_transcript_digest,
        "schema_name": "voice_agent.candidate_safety.output.v1",
        "normalization_status": "normalized",
        "output_mode": "mock",
    }
    updates: dict[CandidateSafetyFakeDirective, dict[str, Any]] = {
        CandidateSafetyFakeDirective.UNSAFE: {
            "decision": "UNSAFE",
            "semantic_categories": ("unsafe_claim",),
            "prohibited_flags": ("unsafe_claim",),
        },
        CandidateSafetyFakeDirective.UNCERTAIN: {
            "decision": "UNCERTAIN",
            "semantic_categories": ("uncertain_claim",),
        },
        CandidateSafetyFakeDirective.UNKNOWN_ENUM: {
            "decision": "MAYBE",
        },
        CandidateSafetyFakeDirective.OVERSIZED_OUTPUT: {
            "semantic_categories": tuple(
                f"category_{index}" for index in range(9)
            ),
        },
        CandidateSafetyFakeDirective.LOW_CONFIDENCE: {
            "confidence": 0.20,
        },
        CandidateSafetyFakeDirective.PROHIBITED_RISK: {
            "decision": "UNSAFE",
            "semantic_categories": ("prohibited_risk",),
            "prohibited_flags": ("prohibited_risk",),
        },
        CandidateSafetyFakeDirective.TIMEOUT: {},
        CandidateSafetyFakeDirective.SAFE: {},
    }
    if directive is CandidateSafetyFakeDirective.MALFORMED_JSON:
        return {"decision": "SAFE"}
    base.update(updates[directive])
    return base


__all__ = [
    "CandidateSafetyFakeDirective",
    "FakeRouteEvidenceAdapter",
    "RouteEvidenceFakeDirective",
]
