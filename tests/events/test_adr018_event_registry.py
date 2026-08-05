from __future__ import annotations

from qwen_slice3b1_support import valid_adr018_event
from voice_agent.events.envelope import validate_event_envelope
from voice_agent.events.registry import ADR018_EVENT_NAMES, get_event_definition


ADR018_REQUIRED_FIELDS = {
    "ROUTE_EVIDENCE_OUTPUT_EMITTED": {
        "adapter_id", "adapter_type", "adapter_request_id", "turn_id",
        "utterance_id", "final_asr_event_id", "context_projection_event_id",
        "route_hint", "task_focus_hint", "foreground_act_hint", "ack_kind",
        "risk_class", "risk_tags", "evidence_uncertainty", "confidence",
        "schema_name", "normalization_status", "output_mode",
    },
    "CANDIDATE_SAFETY_EVIDENCE_OUTPUT_EMITTED": {
        "adapter_id", "adapter_type", "adapter_request_id", "turn_id",
        "utterance_id", "qwen_response_id", "candidate_transcript_digest",
        "context_projection_event_id", "decision", "semantic_categories",
        "prohibited_flags", "confidence", "schema_name",
        "normalization_status", "output_mode",
    },
    "MODEL_CONTEXT_PROJECTION_EMITTED": {
        "projection_id", "target_role", "source_event_ids",
        "context_snapshot_id", "source_event_seq",
        "provider_session_generation", "projection_ref", "policy_version",
        "redaction_status", "output_mode",
    },
    "SLOW_TO_FAST_HANDOFF_EMITTED": {
        "handoff_id", "kind", "delivery_mode", "task_id", "plan_version",
        "task_event_seq", "source_event_ids", "facts_ref",
        "must_say_fields_ref", "forbidden_claims_ref", "priority",
        "expiry_status", "redaction_status",
    },
    "SLOW_TO_FAST_HANDOFF_DISPOSITIONED": {
        "handoff_id", "disposition", "reason",
    },
    "RESPONSE_ARBITRATION_DECIDED": {
        "arbitration_id", "selected_source_type",
        "superseded_source_event_ids", "provider_session_generation",
        "playback_epoch", "interaction_state_version", "decision_reason",
    },
    "PROVIDER_CONTEXT_STATE_CHANGED": {
        "adapter_id", "provider_session_generation", "from_state", "to_state",
        "reason", "source_event_ids", "output_mode",
    },
    "CANDIDATE_AUDIO_SHADOW_VERIFICATION_EMITTED": {
        "adapter_id", "adapter_type", "adapter_request_id", "turn_id",
        "utterance_id", "qwen_response_id", "candidate_transcript_digest",
        "candidate_pcm_manifest_digest", "audio_format_ref",
        "decoded_duration_ms", "independent_transcript_ref",
        "normalized_transcript_digest", "exact_numbers_entities_units_match",
        "equivalence", "output_mode",
    },
    "ASSISTANT_DELIVERY_DISPOSITIONED": {
        "assistant_item_ref", "source_output_event_id", "from_status",
        "to_status", "delivery_offset_status",
        "provider_item_cleanup_status", "source_event_ids",
    },
}

ADR018_ENUM_FIELDS = {
    "ROUTE_EVIDENCE_OUTPUT_EMITTED": {
        "route_hint": frozenset({
            "FAST_ONLY", "SPAWN_SLOW_TASK",
            "PATCH_ACTIVE_SLOW_TASK", "IGNORE",
        }),
        "task_focus_hint": frozenset({
            "ACTIVE_TASK_PATCH", "FOREGROUND_CHAT", "NEW_TASK_CANDIDATE",
            "CANCEL_OR_PAUSE_CANDIDATE", "NON_ASSISTANT", "AMBIGUOUS",
        }),
        "foreground_act_hint": frozenset({
            "ANSWER", "ACK_SLOW", "ACK_PATCH", "SILENCE", "CLARIFY",
        }),
        "ack_kind": frozenset({
            "CHAT", "SEARCH_ACCEPTED", "COMPARE_ACCEPTED", "PLAN_ACCEPTED",
            "PATCH_RECEIVED", "CLARIFY_NEEDED",
            "WAITING_CONFIRMATION", "SILENCE",
        }),
        "risk_class": frozenset({"LOW", "MEDIUM", "HIGH", "UNKNOWN"}),
        "evidence_uncertainty": frozenset({"LOW", "MEDIUM", "HIGH"}),
    },
    "CANDIDATE_SAFETY_EVIDENCE_OUTPUT_EMITTED": {
        "decision": frozenset({"SAFE", "UNSAFE", "UNCERTAIN"}),
    },
    "MODEL_CONTEXT_PROJECTION_EMITTED": {
        "target_role": frozenset({
            "route_evidence", "candidate_safety",
            "fast_candidate", "composer",
        }),
    },
    "SLOW_TO_FAST_HANDOFF_EMITTED": {
        "kind": frozenset({
            "PROGRESS", "CLARIFICATION", "CONFIRMATION",
            "FINAL", "DEGRADED", "FAILED",
        }),
        "delivery_mode": frozenset({"CONTEXT_ONLY", "SPEAK_WHEN_IDLE"}),
        "expiry_status": frozenset({"CURRENT", "EXPIRED"}),
    },
    "SLOW_TO_FAST_HANDOFF_DISPOSITIONED": {
        "disposition": frozenset({
            "QUEUED", "COALESCED", "SELECTED", "STALE",
            "EXPIRED", "CANCELLED", "DISCARDED",
        }),
    },
    "RESPONSE_ARBITRATION_DECIDED": {
        "selected_source_type": frozenset({
            "user_fast", "confirmation", "clarification",
            "progress", "final", "none",
        }),
    },
    "PROVIDER_CONTEXT_STATE_CHANGED": {
        "from_state": frozenset({
            "CLEAN", "CLEANUP_PENDING", "TAINTED", "REBUILDING", "CLOSED",
        }),
        "to_state": frozenset({
            "CLEAN", "CLEANUP_PENDING", "TAINTED", "REBUILDING", "CLOSED",
        }),
    },
    "CANDIDATE_AUDIO_SHADOW_VERIFICATION_EMITTED": {
        "equivalence": frozenset({"MATCH", "MISMATCH", "UNCERTAIN"}),
    },
    "ASSISTANT_DELIVERY_DISPOSITIONED": {
        "from_status": frozenset({"PENDING"}),
        "to_status": frozenset({"FULL", "TRUNCATED", "NOT_STARTED"}),
        "delivery_offset_status": frozenset({
            "KNOWN", "UNKNOWN", "NOT_APPLICABLE",
        }),
        "provider_item_cleanup_status": frozenset({
            "NOT_REQUIRED", "ACKNOWLEDGED", "TAINTED",
        }),
    },
}

ADR018_LITERAL_FIELDS = {
    "ROUTE_EVIDENCE_OUTPUT_EMITTED": {
        "adapter_type": "route_evidence",
        "schema_name": "voice_agent.route_evidence.output.v1",
        "normalization_status": "normalized",
    },
    "CANDIDATE_SAFETY_EVIDENCE_OUTPUT_EMITTED": {
        "adapter_type": "route_evidence",
        "schema_name": "voice_agent.candidate_safety.output.v1",
        "normalization_status": "normalized",
    },
    "CANDIDATE_AUDIO_SHADOW_VERIFICATION_EMITTED": {
        "adapter_type": "asr",
    },
    "ASSISTANT_DELIVERY_DISPOSITIONED": {
        "from_status": "PENDING",
    },
}


def test_adr018_runtime_registry_has_exact_required_fields() -> None:
    assert ADR018_EVENT_NAMES == frozenset(ADR018_REQUIRED_FIELDS)
    for name, expected in ADR018_REQUIRED_FIELDS.items():
        assert set(get_event_definition(name).required_fields) == expected


def test_adr018_runtime_registry_has_exact_enum_fields() -> None:
    for name, expected in ADR018_ENUM_FIELDS.items():
        assert get_event_definition(name).enum_fields == expected


def test_adr018_runtime_registry_has_exact_literals() -> None:
    for name, expected in ADR018_LITERAL_FIELDS.items():
        assert get_event_definition(name).literal_fields == expected


def test_all_adr018_synthetic_events_validate() -> None:
    for event_name in ADR018_REQUIRED_FIELDS:
        validated = validate_event_envelope(valid_adr018_event(event_name))
        assert validated["event_name"] == event_name
