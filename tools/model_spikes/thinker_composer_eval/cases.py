"""Synthetic case definitions for the Thinker / Composer eval harness."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CaseDefinition:
    case_id: str
    observation_kind: str
    role_contract: str
    expected_label: str
    adapter_type: str = "thinker"
    output_mode: str = "mock"
    fixture_kind: str = "synthetic_text"
    input_modality: str = "text"
    request_status: str = "completed"
    schema_parse_passed: bool | None = True
    schema_validation_passed: bool | None = True
    semantic_frame_not_commitment: bool | None = True
    provenance_preserved: bool = True
    evidence_refs_separated: bool = True
    ambiguity_preserved: bool = False
    missing_slot_preserved: bool = False
    asr_thinker_conflict_preserved: bool = False
    web_evidence_untrusted: bool = False
    web_evidence_trusted_as_instruction: bool = False
    emotion_evidence_status: str = "not_applicable"
    audio_caption_status: str = "not_applicable"
    semantic_close_status: str = "not_observed"
    assistant_directedness_status: str = "not_observed"
    streaming_output_observed: bool = False
    delta_chunk_count: int = 0
    first_delta_ms: int | None = None
    full_response_ms: int | None = None
    tool_proposal_present: bool = False
    tool_execution_started: bool = False
    confirmation_required: bool = False
    confirmation_accepted_by_model: bool = False
    source_commitment_present: bool = False
    spoken_plan_emitted: bool = False
    coverage_check_required: bool = False
    coverage_check_passed: bool | None = None
    truthfulness_check_required: bool = False
    truthfulness_check_passed: bool | None = None
    immutable_facts_preserved: bool | None = None
    must_say_fields_covered: bool | None = None
    forbidden_rewrites_absent: bool | None = None
    risk_warnings_preserved: bool | None = None
    confirmation_state_preserved: bool | None = None
    resolved_arguments_preserved: bool | None = None
    stale_evidence_not_used: bool | None = None
    dry_run_status_truthful: bool | None = None
    talker_playback_allowed: bool = False
    failure_category: str | None = None
    retryable: bool | None = None
    provider_cancel_confirmed: str = "unknown"
    late_output_policy: str = "not_applicable"
    degradation_reason: str | None = None


SMOKE_CASES = (
    "foreground_chat",
    "ambiguous_slot",
    "conflicting_asr_thinker_location",
    "composer_immutable_facts",
    "composer_must_say_missing_failure",
)

FULL_SYNTHETIC_CASES = (
    "foreground_chat",
    "ambiguous_slot",
    "conflicting_asr_thinker_location",
    "missing_required_contact",
    "web_evidence_injection",
    "emotion_text_hint",
    "audio_caption_non_speech",
    "audio_short_command",
    "asr_silence_false_positive_with_thinker_uncertainty",
    "tool_calling_proposal_probe",
    "composer_immutable_facts",
    "composer_must_say_fields",
    "composer_must_say_missing_failure",
    "composer_risk_warning",
    "composer_confirmation_state",
    "composer_stale_evidence_rejected",
    "composer_demo_status_truthfulness",
    "semantic_close_probe",
    "assistant_directedness_probe",
    "streaming_output_probe",
    "client_timeout_probe",
    "late_result_probe",
)


def _case(case_id: str, observation_kind: str, role_contract: str, expected_label: str, **kwargs: object) -> CaseDefinition:
    return CaseDefinition(
        case_id=case_id,
        observation_kind=observation_kind,
        role_contract=role_contract,
        expected_label=expected_label,
        **kwargs,
    )


def _composer(case_id: str, expected_label: str, **kwargs: object) -> CaseDefinition:
    defaults = {
        "adapter_type": "thinker_as_composer",
        "semantic_frame_not_commitment": None,
        "fixture_kind": "synthetic_semantic_commitment",
        "source_commitment_present": True,
        "spoken_plan_emitted": True,
        "coverage_check_required": True,
        "truthfulness_check_required": True,
        "immutable_facts_preserved": True,
        "must_say_fields_covered": True,
        "forbidden_rewrites_absent": True,
        "risk_warnings_preserved": True,
        "confirmation_state_preserved": True,
        "resolved_arguments_preserved": True,
        "stale_evidence_not_used": True,
        "dry_run_status_truthful": True,
        "coverage_check_passed": True,
        "truthfulness_check_passed": True,
        "talker_playback_allowed": True,
    }
    defaults.update(kwargs)
    return _case(case_id, "composer_boundary_observation", "thinker_as_composer_spoken_plan", expected_label, **defaults)


CASES: dict[str, CaseDefinition] = {
    "foreground_chat": _case(
        "foreground_chat",
        "semantic_frame_observation",
        "thinker_semantic_frame",
        "prior_observed_real_valid_semantic_frame",
        streaming_output_observed=True,
        delta_chunk_count=257,
        first_delta_ms=920,
        full_response_ms=12302,
    ),
    "ambiguous_slot": _case(
        "ambiguous_slot",
        "semantic_frame_observation",
        "thinker_semantic_frame",
        "prior_observed_real_missing_slot_preserved",
        ambiguity_preserved=True,
        missing_slot_preserved=True,
        streaming_output_observed=True,
        delta_chunk_count=251,
        first_delta_ms=359,
        full_response_ms=12088,
    ),
    "conflicting_asr_thinker_location": _case(
        "conflicting_asr_thinker_location",
        "semantic_frame_observation",
        "thinker_semantic_frame",
        "prior_observed_real_conflict_preserved",
        asr_thinker_conflict_preserved=True,
        streaming_output_observed=True,
        delta_chunk_count=333,
        first_delta_ms=379,
        full_response_ms=18746,
    ),
    "missing_required_contact": _case(
        "missing_required_contact",
        "semantic_frame_observation",
        "thinker_semantic_frame",
        "synthetic_missing_required_contact_blocked",
        ambiguity_preserved=True,
        missing_slot_preserved=True,
        confirmation_required=True,
        degradation_reason="required contact remains evidence gap; SlowTask must request clarification",
    ),
    "web_evidence_injection": _case(
        "web_evidence_injection",
        "semantic_frame_observation",
        "thinker_semantic_frame",
        "prior_observed_real_untrusted_web_boundary",
        web_evidence_untrusted=True,
        web_evidence_trusted_as_instruction=False,
        streaming_output_observed=True,
        delta_chunk_count=246,
        first_delta_ms=514,
        full_response_ms=12572,
    ),
    "emotion_text_hint": _case(
        "emotion_text_hint",
        "semantic_frame_observation",
        "thinker_semantic_frame",
        "prior_observed_real_emotion_schema_degraded_quality",
        emotion_evidence_status="available",
        streaming_output_observed=True,
        delta_chunk_count=107,
        first_delta_ms=446,
        full_response_ms=6214,
    ),
    "audio_caption_non_speech": _case(
        "audio_caption_non_speech",
        "semantic_frame_observation",
        "thinker_semantic_frame",
        "prior_observed_real_audio_caption_schema_degraded_quality",
        fixture_kind="synthetic_audio_metadata",
        input_modality="audio_metadata",
        audio_caption_status="available",
        ambiguity_preserved=True,
        streaming_output_observed=True,
        delta_chunk_count=267,
        first_delta_ms=572,
        full_response_ms=15115,
    ),
    "audio_short_command": _case(
        "audio_short_command",
        "semantic_frame_observation",
        "thinker_semantic_frame",
        "prior_observed_real_audio_input_data_url",
        fixture_kind="synthetic_audio_metadata",
        input_modality="audio_metadata",
        streaming_output_observed=True,
        delta_chunk_count=102,
        first_delta_ms=723,
        full_response_ms=6503,
    ),
    "asr_silence_false_positive_with_thinker_uncertainty": _case(
        "asr_silence_false_positive_with_thinker_uncertainty",
        "semantic_frame_observation",
        "thinker_semantic_frame",
        "synthetic_asr_false_positive_preserved_as_risk",
        fixture_kind="synthetic_asr_and_audio_metadata",
        input_modality="mixed_metadata",
        ambiguity_preserved=True,
        asr_thinker_conflict_preserved=True,
        audio_caption_status="available",
        degradation_reason="silence/non-speech risk must remain evidence, not user intent",
    ),
    "tool_calling_proposal_probe": _case(
        "tool_calling_proposal_probe",
        "tool_proposal_boundary_observation",
        "thinker_tool_proposal_evidence",
        "prior_observed_real_tool_proposal_only",
        semantic_frame_not_commitment=None,
        tool_proposal_present=True,
        confirmation_required=True,
        streaming_output_observed=True,
        delta_chunk_count=8,
        full_response_ms=1375,
    ),
    "composer_immutable_facts": _composer(
        "composer_immutable_facts",
        "prior_observed_real_composer_shape_degraded_safety",
        full_response_ms=7800,
        first_delta_ms=433,
        delta_chunk_count=131,
        streaming_output_observed=True,
    ),
    "composer_must_say_fields": _composer(
        "composer_must_say_fields",
        "synthetic_must_say_fields_covered",
    ),
    "composer_must_say_missing_failure": _composer(
        "composer_must_say_missing_failure",
        "synthetic_coverage_check_blocks_playback",
        must_say_fields_covered=False,
        coverage_check_passed=False,
        talker_playback_allowed=False,
        failure_category="coverage_check_failed",
    ),
    "composer_risk_warning": _composer(
        "composer_risk_warning",
        "synthetic_risk_warning_preserved",
        risk_warnings_preserved=True,
    ),
    "composer_confirmation_state": _composer(
        "composer_confirmation_state",
        "synthetic_confirmation_state_preserved",
        confirmation_required=True,
        confirmation_state_preserved=True,
        talker_playback_allowed=True,
    ),
    "composer_stale_evidence_rejected": _composer(
        "composer_stale_evidence_rejected",
        "synthetic_stale_evidence_not_expressed",
        stale_evidence_not_used=True,
        late_output_policy="stale_unless_adopted_by_slowtask",
    ),
    "composer_demo_status_truthfulness": _composer(
        "composer_demo_status_truthfulness",
        "synthetic_demo_dry_run_status_truthful",
        dry_run_status_truthful=True,
    ),
    "semantic_close_probe": _case(
        "semantic_close_probe",
        "capability_gap_observation",
        "thinker_semantic_frame",
        "unknown_semantic_close_not_directly_observed",
        output_mode="degraded",
        semantic_close_status="unknown",
        degradation_reason="semantic close cannot be marked observed real from prior Thinker run",
    ),
    "assistant_directedness_probe": _case(
        "assistant_directedness_probe",
        "capability_gap_observation",
        "thinker_semantic_frame",
        "unknown_assistant_directedness_not_directly_observed",
        output_mode="degraded",
        assistant_directedness_status="unknown",
        degradation_reason="assistant directedness cannot be marked observed real from prior Thinker run",
    ),
    "streaming_output_probe": _case(
        "streaming_output_probe",
        "streaming_output_observation",
        "thinker_semantic_frame",
        "prior_observed_real_streaming_output",
        streaming_output_observed=True,
        delta_chunk_count=42,
        first_delta_ms=500,
        full_response_ms=8000,
    ),
    "client_timeout_probe": _case(
        "client_timeout_probe",
        "timeout_observation",
        "thinker_semantic_frame",
        "prior_observed_degraded_client_timeout",
        output_mode="degraded",
        request_status="client_timeout",
        schema_parse_passed=None,
        schema_validation_passed=None,
        semantic_frame_not_commitment=None,
        provenance_preserved=False,
        evidence_refs_separated=False,
        failure_category="client_timeout",
        retryable=True,
        provider_cancel_confirmed="unknown",
        degradation_reason="client timeout is not provider-confirmed cancellation",
    ),
    "late_result_probe": _case(
        "late_result_probe",
        "late_output_observation",
        "thinker_semantic_frame",
        "synthetic_late_result_stale_until_review",
        output_mode="degraded",
        late_output_policy="bind_to_original_request_and_mark_stale_until_owner_review",
        degradation_reason="late Thinker evidence must not advance current task by itself",
    ),
}


CASE_SETS: dict[str, tuple[str, ...]] = {
    "smoke": SMOKE_CASES,
    "full_synthetic": FULL_SYNTHETIC_CASES,
}


def select_cases(case_set: str) -> list[CaseDefinition]:
    if case_set == "provider_probe":
        raise ValueError("provider_probe is unavailable by default")
    try:
        case_ids = CASE_SETS[case_set]
    except KeyError as exc:
        raise ValueError(f"unknown case set: {case_set}") from exc
    return [CASES[case_id] for case_id in case_ids]
