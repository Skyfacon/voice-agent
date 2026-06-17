from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from voice_agent.events.journal import InMemoryEventJournal


USER_PATCH_SOURCE_MODULE = "user_patch_pipeline"
ALLOWED_CANDIDATE_PATCH_TYPES = frozenset(
    {
        "slot_update_candidate",
        "constraint_update_candidate",
        "goal_rewrite_candidate",
        "confirmation_candidate",
        "cancel_candidate",
        "switch_task_candidate",
        "feedback_candidate",
        "irrelevant_candidate",
    }
)


@dataclass(frozen=True)
class UserPatchEvidencePack:
    evidence_ref: str
    authoritative_evidence: dict[str, Any]
    non_authoritative_hypothesis: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_ref": self.evidence_ref,
            "authoritative_evidence": deepcopy(self.authoritative_evidence),
            "non_authoritative_hypothesis": deepcopy(self.non_authoritative_hypothesis),
        }


@dataclass(frozen=True)
class UserPatchReceivedResult:
    evidence_pack: UserPatchEvidencePack
    user_patch_event: dict[str, Any]


class UserPatchEvidencePackRuntime:
    def __init__(self, journal: InMemoryEventJournal) -> None:
        self._journal = journal

    def receive_patch_from_router_decision(
        self,
        *,
        router_decision_event: Mapping[str, Any],
        turn_committed_event: Mapping[str, Any],
        task_id: str,
        current_plan_version: int,
        next_task_event_seq: int,
        patch_id: str,
        event_id: str,
        evidence_ref: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        text_input_event: Mapping[str, Any] | None = None,
        asr_frame_event: Mapping[str, Any] | None = None,
        thinker_frame_event: Mapping[str, Any] | None = None,
        asr_nbest: Sequence[Mapping[str, Any]] = (),
        transcript_hint_ref: str | None = None,
        semantic_summary_ref: str | None = None,
        audio_summary_ref: str | None = None,
        candidate_patch_types: Sequence[str] = (),
        patch_hint: str | None = None,
    ) -> UserPatchReceivedResult:
        _validate_patch_router_decision(router_decision_event, task_id=task_id)
        _validate_turn_binding(router_decision_event, turn_committed_event)
        evidence_pack = construct_user_patch_evidence_pack(
            router_decision_event=router_decision_event,
            turn_committed_event=turn_committed_event,
            text_input_event=text_input_event,
            asr_frame_event=asr_frame_event,
            thinker_frame_event=thinker_frame_event,
            evidence_ref=evidence_ref,
            asr_nbest=asr_nbest,
            transcript_hint_ref=transcript_hint_ref,
            semantic_summary_ref=semantic_summary_ref,
            audio_summary_ref=audio_summary_ref,
            candidate_patch_types=candidate_patch_types,
            patch_hint=patch_hint,
        )

        authoritative_refs = _authoritative_evidence_refs(evidence_pack.authoritative_evidence)
        hypothesis_refs = _non_authoritative_hypothesis_refs(evidence_pack.non_authoritative_hypothesis)
        normalized_candidate_types = list(
            evidence_pack.non_authoritative_hypothesis.get("candidate_patch_types", [])
        )

        event = self._journal.append(
            event_name="USER_PATCH_RECEIVED",
            event_id=event_id,
            source_module=USER_PATCH_SOURCE_MODULE,
            caused_by_event_id=str(router_decision_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            trace_redaction_level="redacted_fixture",
            patch_id=patch_id,
            task_id=task_id,
            plan_version=current_plan_version,
            observed_plan_version=current_plan_version,
            task_event_seq=next_task_event_seq,
            turn_id=str(turn_committed_event["turn_id"]),
            utterance_id=str(turn_committed_event["utterance_id"]),
            evidence_ref=evidence_ref,
            authoritative_evidence_refs=authoritative_refs,
            non_authoritative_hypothesis_refs=hypothesis_refs,
            candidate_patch_types=normalized_candidate_types,
            evidence_pack=evidence_pack.to_dict(),
        )
        return UserPatchReceivedResult(evidence_pack=evidence_pack, user_patch_event=event)


def construct_user_patch_evidence_pack(
    *,
    router_decision_event: Mapping[str, Any],
    turn_committed_event: Mapping[str, Any],
    evidence_ref: str,
    text_input_event: Mapping[str, Any] | None = None,
    asr_frame_event: Mapping[str, Any] | None = None,
    thinker_frame_event: Mapping[str, Any] | None = None,
    asr_nbest: Sequence[Mapping[str, Any]] = (),
    transcript_hint_ref: str | None = None,
    semantic_summary_ref: str | None = None,
    audio_summary_ref: str | None = None,
    candidate_patch_types: Sequence[str] = (),
    patch_hint: str | None = None,
) -> UserPatchEvidencePack:
    _validate_router_event(router_decision_event)
    _validate_committed_turn(turn_committed_event)
    _validate_turn_binding(router_decision_event, turn_committed_event)
    _validate_router_source_links(
        router_decision_event,
        turn_committed_event=turn_committed_event,
        asr_frame_event=asr_frame_event,
        thinker_frame_event=thinker_frame_event,
    )
    if text_input_event is not None:
        _validate_text_input_event(text_input_event, turn_committed_event=turn_committed_event)
    if asr_frame_event is not None:
        _validate_asr_frame(asr_frame_event, turn_committed_event)
    if thinker_frame_event is not None:
        _validate_thinker_frame(thinker_frame_event, turn_committed_event)
    semantic_summary_ref = _bind_thinker_semantic_summary_ref(
        thinker_frame_event,
        semantic_summary_ref,
    )

    normalized_candidates = _normalize_candidate_patch_types(candidate_patch_types)
    authoritative_evidence = _build_authoritative_evidence(
        turn_committed_event=turn_committed_event,
        text_input_event=text_input_event,
        asr_frame_event=asr_frame_event,
        asr_nbest=asr_nbest,
        transcript_hint_ref=transcript_hint_ref,
    )
    non_authoritative_hypothesis = _build_non_authoritative_hypothesis(
        router_decision_event=router_decision_event,
        thinker_frame_event=thinker_frame_event,
        semantic_summary_ref=semantic_summary_ref,
        audio_summary_ref=audio_summary_ref,
        candidate_patch_types=normalized_candidates,
        patch_hint=patch_hint,
    )
    return UserPatchEvidencePack(
        evidence_ref=evidence_ref,
        authoritative_evidence=authoritative_evidence,
        non_authoritative_hypothesis=non_authoritative_hypothesis,
    )


def _build_authoritative_evidence(
    *,
    turn_committed_event: Mapping[str, Any],
    text_input_event: Mapping[str, Any] | None,
    asr_frame_event: Mapping[str, Any] | None,
    asr_nbest: Sequence[Mapping[str, Any]],
    transcript_hint_ref: str | None,
) -> dict[str, Any]:
    source_event_ids = [str(turn_committed_event["event_id"])]
    evidence: dict[str, Any] = {
        "turn_id": str(turn_committed_event["turn_id"]),
        "utterance_id": str(turn_committed_event["utterance_id"]),
        "input_modality": str(turn_committed_event["input_modality"]),
        "source_event_ids": source_event_ids,
        "provenance": {},
    }
    for field in ("text_span_id", "audio_span_id", "language_hint"):
        if turn_committed_event.get(field) not in (None, ""):
            evidence[field] = str(turn_committed_event[field])

    if text_input_event is not None:
        source_event_ids.insert(0, str(text_input_event["event_id"]))
        if text_input_event.get("text_ref") not in (None, ""):
            evidence["text_ref"] = str(text_input_event["text_ref"])
        if text_input_event.get("redacted_text") not in (None, ""):
            evidence["redacted_text"] = str(text_input_event["redacted_text"])
        evidence["provenance"]["text_ref"] = {
            "source": "user_text",
            "source_event_id": str(text_input_event["event_id"]),
            "evidence_ref": _first_present(text_input_event, "text_ref", "text_span_id"),
        }

    if asr_frame_event is not None:
        source_event_ids.append(str(asr_frame_event["event_id"]))
        evidence["asr_frame_ref"] = str(asr_frame_event["asr_frame_ref"])
        if asr_frame_event.get("text_ref") not in (None, ""):
            evidence["asr_text_ref"] = str(asr_frame_event["text_ref"])
        evidence["asr_nbest"] = _normalize_asr_nbest(asr_nbest, asr_frame_event=asr_frame_event)
        evidence["provenance"]["asr_nbest"] = [
            {
                "source": "asr",
                "source_event_id": str(item.get("source_event_id", asr_frame_event["event_id"])),
                "evidence_ref": str(asr_frame_event["asr_frame_ref"]),
                "confidence": item.get("confidence"),
            }
            for item in evidence["asr_nbest"]
        ]
    else:
        evidence["asr_nbest"] = []

    if transcript_hint_ref is not None:
        evidence["transcript_hint_ref"] = transcript_hint_ref
    return evidence


def _build_non_authoritative_hypothesis(
    *,
    router_decision_event: Mapping[str, Any],
    thinker_frame_event: Mapping[str, Any] | None,
    semantic_summary_ref: str | None,
    audio_summary_ref: str | None,
    candidate_patch_types: list[str],
    patch_hint: str | None,
) -> dict[str, Any]:
    hypothesis: dict[str, Any] = {
        "task_focus": str(router_decision_event.get("task_focus", "")),
        "task_focus_confidence": router_decision_event.get("confidence"),
        "confidence": router_decision_event.get("confidence"),
        "candidate_patch_types": candidate_patch_types,
        "provenance": {
            "task_focus": {
                "source": "router",
                "source_event_id": str(router_decision_event["event_id"]),
                "evidence_ref": str(router_decision_event["event_id"]),
            }
        },
    }
    if router_decision_event.get("evidence_uncertainty") not in (None, ""):
        hypothesis["evidence_uncertainty"] = str(router_decision_event["evidence_uncertainty"])
    if patch_hint is not None:
        hypothesis["patch_hint"] = patch_hint

    if thinker_frame_event is not None:
        hypothesis["semantic_frame_ref"] = str(thinker_frame_event["semantic_frame_ref"])
    if semantic_summary_ref is not None:
        hypothesis["semantic_summary_ref"] = semantic_summary_ref
        if thinker_frame_event is not None:
            hypothesis["provenance"]["semantic_summary_ref"] = {
                "source": "thinker",
                "source_event_id": str(thinker_frame_event["event_id"]),
                "evidence_ref": str(thinker_frame_event["semantic_frame_ref"]),
            }
    if audio_summary_ref is not None:
        hypothesis["audio_summary_ref"] = audio_summary_ref
    return hypothesis


def _normalize_asr_nbest(
    asr_nbest: Sequence[Mapping[str, Any]],
    *,
    asr_frame_event: Mapping[str, Any],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in asr_nbest:
        candidate: dict[str, Any] = {
            "source_event_id": str(item.get("source_event_id", asr_frame_event["event_id"])),
        }
        if item.get("text_ref") not in (None, ""):
            candidate["text_ref"] = str(item["text_ref"])
        if item.get("redacted_text") not in (None, ""):
            candidate["redacted_text"] = str(item["redacted_text"])
        if item.get("confidence") not in (None, ""):
            candidate["confidence"] = float(item["confidence"])
        normalized.append(candidate)
    return normalized


def _normalize_candidate_patch_types(candidate_patch_types: Sequence[str]) -> list[str]:
    normalized = [str(candidate) for candidate in candidate_patch_types]
    invalid = sorted(set(normalized) - ALLOWED_CANDIDATE_PATCH_TYPES)
    if invalid:
        raise ValueError(f"Unknown UserPatch candidate_patch_types: {invalid}")
    return normalized


def _authoritative_evidence_refs(authoritative_evidence: Mapping[str, Any]) -> list[str]:
    refs: list[str] = []
    text_ref = authoritative_evidence.get("text_ref")
    if isinstance(text_ref, str) and text_ref:
        refs.append(text_ref)
    asr_frame_ref = authoritative_evidence.get("asr_frame_ref")
    if isinstance(asr_frame_ref, str) and asr_frame_ref:
        refs.append(asr_frame_ref)
    asr_text_ref = authoritative_evidence.get("asr_text_ref")
    if isinstance(asr_text_ref, str) and asr_text_ref:
        refs.append(asr_text_ref)
    audio_span_id = authoritative_evidence.get("audio_span_id")
    if isinstance(audio_span_id, str) and audio_span_id:
        refs.append(f"audio-span://{audio_span_id}")
    return refs


def _non_authoritative_hypothesis_refs(hypothesis: Mapping[str, Any]) -> list[str]:
    refs: list[str] = []
    for field in ("semantic_frame_ref", "semantic_summary_ref", "audio_summary_ref"):
        value = hypothesis.get(field)
        if isinstance(value, str) and value:
            refs.append(value)
    return refs


def _validate_patch_router_decision(event: Mapping[str, Any], *, task_id: str) -> None:
    _validate_router_event(event)
    if event.get("router_decision") != "PATCH_ACTIVE_SLOW_TASK":
        raise ValueError("UserPatch construction requires router_decision=PATCH_ACTIVE_SLOW_TASK")
    if event.get("active_task_id") != task_id:
        raise ValueError("PATCH_ACTIVE_SLOW_TASK requires active_task_id to match task_id")


def _validate_router_event(event: Mapping[str, Any]) -> None:
    if event.get("event_name") != "ROUTER_DECISION_EMITTED":
        raise ValueError("UserPatch construction requires a ROUTER_DECISION_EMITTED event")


def _validate_committed_turn(event: Mapping[str, Any]) -> None:
    if event.get("event_name") != "TURN_INGRESS_COMMITTED":
        raise ValueError("UserPatch evidence requires a TURN_INGRESS_COMMITTED event")


def _validate_turn_binding(
    router_decision_event: Mapping[str, Any],
    turn_committed_event: Mapping[str, Any],
) -> None:
    for field in ("turn_id", "utterance_id"):
        if router_decision_event.get(field) != turn_committed_event.get(field):
            raise ValueError(f"Router decision must match committed turn {field}")


def _validate_router_source_links(
    router_decision_event: Mapping[str, Any],
    *,
    turn_committed_event: Mapping[str, Any],
    asr_frame_event: Mapping[str, Any] | None,
    thinker_frame_event: Mapping[str, Any] | None,
) -> None:
    _require_router_source_event(
        router_decision_event,
        source_id_field="turn_committed_event_id",
        source_event=turn_committed_event,
    )
    if asr_frame_event is not None:
        _require_router_source_event(
            router_decision_event,
            source_id_field="asr_frame_event_id",
            source_event=asr_frame_event,
        )
    if thinker_frame_event is not None:
        _require_router_source_event(
            router_decision_event,
            source_id_field="thinker_frame_event_id",
            source_event=thinker_frame_event,
        )


def _require_router_source_event(
    router_decision_event: Mapping[str, Any],
    *,
    source_id_field: str,
    source_event: Mapping[str, Any],
) -> None:
    expected_event_id = router_decision_event.get(source_id_field)
    if expected_event_id in (None, ""):
        raise ValueError(f"Router decision must include {source_id_field}")
    if str(expected_event_id) != str(source_event.get("event_id")):
        raise ValueError(f"Router decision {source_id_field} must match provided evidence event_id")


def _validate_text_input_event(
    event: Mapping[str, Any],
    *,
    turn_committed_event: Mapping[str, Any],
) -> None:
    if event.get("event_name") != "TEXT_INPUT_RECEIVED":
        raise ValueError("text_input_event must be TEXT_INPUT_RECEIVED")
    if event.get("text_span_id") != turn_committed_event.get("text_span_id"):
        raise ValueError("TEXT_INPUT_RECEIVED must match committed turn text_span_id")


def _validate_mock_frame(
    event: Mapping[str, Any],
    expected_event_name: str,
    turn_committed_event: Mapping[str, Any],
) -> None:
    if event.get("event_name") != expected_event_name:
        raise ValueError(f"Expected {expected_event_name}")
    for field in ("turn_id", "utterance_id"):
        if event.get(field) != turn_committed_event.get(field):
            raise ValueError(f"{expected_event_name} must match committed turn {field}")


def _validate_asr_frame(
    event: Mapping[str, Any],
    turn_committed_event: Mapping[str, Any],
) -> None:
    event_name = str(event.get("event_name"))
    if event_name == "MOCK_ASR_FRAME_EMITTED":
        _validate_mock_frame(event, "MOCK_ASR_FRAME_EMITTED", turn_committed_event)
        return
    if event_name != "ASR_TRANSCRIPT_OUTPUT_EMITTED":
        raise ValueError("Expected MOCK_ASR_FRAME_EMITTED or ASR_TRANSCRIPT_OUTPUT_EMITTED")
    if event.get("output_mode") not in {"real", "fallback", "degraded"}:
        raise ValueError("ASR_TRANSCRIPT_OUTPUT_EMITTED must use output_mode=real, fallback, or degraded")
    if event.get("transcript_finality") != "final":
        raise ValueError("ASR_TRANSCRIPT_OUTPUT_EMITTED must be final before UserPatch use")
    for ref_field in ("asr_frame_ref", "text_ref"):
        if not isinstance(event.get(ref_field), str) or event.get(ref_field) == "":
            raise ValueError(f"ASR_TRANSCRIPT_OUTPUT_EMITTED requires {ref_field}")
    for field in ("turn_id", "utterance_id", "audio_span_id", "input_modality"):
        if event.get(field) != turn_committed_event.get(field):
            raise ValueError(f"ASR_TRANSCRIPT_OUTPUT_EMITTED must match committed turn {field}")


def _validate_thinker_frame(
    event: Mapping[str, Any],
    turn_committed_event: Mapping[str, Any],
) -> None:
    event_name = str(event.get("event_name"))
    if event_name == "MOCK_THINKER_FRAME_EMITTED":
        _validate_mock_frame(event, "MOCK_THINKER_FRAME_EMITTED", turn_committed_event)
        return
    if event_name != "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED":
        raise ValueError("Expected MOCK_THINKER_FRAME_EMITTED or THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED")
    if event.get("output_mode") not in {"real", "fallback", "degraded"}:
        raise ValueError("THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED must use output_mode=real, fallback, or degraded")
    if event.get("normalization_status") != "normalized":
        raise ValueError("THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED must be normalized before UserPatch use")
    if event.get("semantic_frame_schema") != "voice_agent.semantic_frame.v1":
        raise ValueError("THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED must use SemanticFrame-compatible schema")
    for field in ("turn_id", "utterance_id"):
        if event.get(field) != turn_committed_event.get(field):
            raise ValueError(f"THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED must match committed turn {field}")


def _bind_thinker_semantic_summary_ref(
    thinker_frame_event: Mapping[str, Any] | None,
    semantic_summary_ref: str | None,
) -> str | None:
    if thinker_frame_event is None:
        return semantic_summary_ref
    if thinker_frame_event.get("event_name") != "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED":
        return semantic_summary_ref

    event_summary_ref = thinker_frame_event.get("semantic_summary_ref")
    if event_summary_ref in (None, ""):
        raise ValueError("THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED requires semantic_summary_ref")
    event_summary_ref = str(event_summary_ref)
    if semantic_summary_ref is None:
        return event_summary_ref
    if str(semantic_summary_ref) != event_summary_ref:
        raise ValueError(
            "semantic_summary_ref must match THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED semantic_summary_ref"
        )
    return str(semantic_summary_ref)


def _first_present(event: Mapping[str, Any], *fields: str) -> str:
    for field in fields:
        value = event.get(field)
        if value not in (None, ""):
            return str(value)
    return ""
