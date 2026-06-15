from __future__ import annotations

import pytest

from voice_agent.adapters.lalm_thinker_binding import (
    LALM_THINKER_CANDIDATE_SCHEMA,
    LALM_THINKER_CANDIDATE_SCHEMA_VERSION,
    LALMThinkerBindingError,
    bind_lalm_thinker_request,
    build_lalm_thinker_request_metadata,
)
from voice_agent.events.registry import MVP0_EVENT_NAMES


def test_text_turn_binding_preserves_committed_turn_and_uses_safe_metadata_refs() -> None:
    binding = bind_lalm_thinker_request(
        turn_committed_event=_committed_text_turn(),
        adapter_request_id="adapter-request-lalm-thinker-001",
        request_metadata_ref="request-metadata://synthetic/lalm-thinker/text-001",
        input_ref="text://synthetic/lalm-thinker/input-001",
        policy_ref="policy://synthetic/lalm-thinker/evidence-only",
    )

    assert binding.to_dict() == {
        "adapter_request_id": "adapter-request-lalm-thinker-001",
        "turn_committed_event_id": "evt_turn_committed_text_001",
        "turn_id": "turn_text_001",
        "utterance_id": "utt_text_001",
        "input_modality": "text",
        "input_span_id": "input_text_001",
        "text_span_id": "text_span_001",
        "request_metadata_ref": "request-metadata://synthetic/lalm-thinker/text-001",
        "input_ref": "text://synthetic/lalm-thinker/input-001",
        "policy_ref": "policy://synthetic/lalm-thinker/evidence-only",
        "candidate_schema_version": LALM_THINKER_CANDIDATE_SCHEMA_VERSION,
    }

    metadata = build_lalm_thinker_request_metadata(binding)
    assert metadata["request_binding"] == binding.to_dict()
    assert metadata["instruction_boundary"] == {
        "candidate_role": "evidence_only",
        "candidate_schema_version": LALM_THINKER_CANDIDATE_SCHEMA_VERSION,
        "response_must_be_single_json_object": True,
        "markdown_or_prose_allowed": False,
        "provider_native_schema_allowed": False,
        "raw_payload_allowed": False,
        "native_tool_execution_allowed": False,
        "candidate_refs_allowed": False,
        "final_refs_owned_by_adapter": True,
        "evidence_hints_only": True,
        "may_emit_event_journal_events": False,
        "may_create_semantic_commitments": False,
        "may_accept_confirmation": False,
        "may_authorize_tools": False,
        "may_execute_tools": False,
        "may_control_playback": False,
        "may_emit_coverage_or_truthfulness_verdicts": False,
        "owns_semantic_commitment": False,
        "owns_confirmation_state": False,
        "owns_tool_authorization": False,
        "owns_tool_execution": False,
        "owns_playback": False,
        "owns_coverage_truthfulness_checks": False,
    }
    assert _forbidden_request_terms_are_absent(metadata)


def test_audio_turn_binding_preserves_audio_span_without_synthesizing_text_span() -> None:
    binding = bind_lalm_thinker_request(
        turn_committed_event=_committed_audio_turn(),
        adapter_request_id="adapter-request-lalm-thinker-audio-001",
        request_metadata_ref="request-metadata://synthetic/lalm-thinker/audio-001",
        input_ref="audio-span://synthetic/lalm-thinker/audio-001",
        policy_ref="policy://synthetic/lalm-thinker/evidence-only",
    )

    metadata = binding.to_dict()

    assert metadata["input_modality"] == "audio"
    assert metadata["audio_span_id"] == "audio_span_001"
    assert "text_span_id" not in metadata


def test_binding_rejects_non_committed_turn_and_causal_mismatch() -> None:
    non_committed = dict(_committed_text_turn(), event_name="TURN_INGRESS_ACCEPTED")

    with pytest.raises(LALMThinkerBindingError, match="TURN_INGRESS_COMMITTED"):
        bind_lalm_thinker_request(
            turn_committed_event=non_committed,
            adapter_request_id="adapter-request-lalm-thinker-001",
            request_metadata_ref="request-metadata://synthetic/lalm-thinker/text-001",
            input_ref="text://synthetic/lalm-thinker/input-001",
            policy_ref="policy://synthetic/lalm-thinker/evidence-only",
        )

    with pytest.raises(LALMThinkerBindingError, match="causal"):
        bind_lalm_thinker_request(
            turn_committed_event=_committed_text_turn(),
            adapter_request_id="adapter-request-lalm-thinker-001",
            request_metadata_ref="request-metadata://synthetic/lalm-thinker/text-001",
            input_ref="text://synthetic/lalm-thinker/input-001",
            policy_ref="policy://synthetic/lalm-thinker/evidence-only",
            expected_turn_committed_event_id="evt_other_turn",
        )


def test_binding_rejects_unsafe_refs_without_reading_secret_material() -> None:
    with pytest.raises(LALMThinkerBindingError, match="credential"):
        bind_lalm_thinker_request(
            turn_committed_event=_committed_text_turn(),
            adapter_request_id="adapter-request-lalm-thinker-001",
            request_metadata_ref="request-metadata://synthetic/lalm-thinker?token=synthetic",
            input_ref="text://synthetic/lalm-thinker/input-001",
            policy_ref="policy://synthetic/lalm-thinker/evidence-only",
        )


def test_adapter_local_candidate_schema_is_not_a_canonical_journal_event() -> None:
    assert LALM_THINKER_CANDIDATE_SCHEMA["schema_version"] == LALM_THINKER_CANDIDATE_SCHEMA_VERSION
    assert LALM_THINKER_CANDIDATE_SCHEMA["schema_kind"] == "adapter_local_candidate_schema"
    assert LALM_THINKER_CANDIDATE_SCHEMA["event_journal_event"] is False
    assert LALM_THINKER_CANDIDATE_SCHEMA["canonical_event_name"] is None
    assert LALM_THINKER_CANDIDATE_SCHEMA["candidate_final_ref_policy"] == (
        "adapter_owned_provider_neutral_refs_only"
    )
    assert LALM_THINKER_CANDIDATE_SCHEMA["artifact_policy"] == {
        "retention": "refs_only",
        "raw_artifacts_retained": False,
    }
    assert LALM_THINKER_CANDIDATE_SCHEMA_VERSION not in MVP0_EVENT_NAMES
    assert "event_name" not in LALM_THINKER_CANDIDATE_SCHEMA
    assert LALM_THINKER_CANDIDATE_SCHEMA["candidate_role"] == "evidence_only"
    assert LALM_THINKER_CANDIDATE_SCHEMA["forbidden_ownership"] == (
        "semantic_commitment",
        "confirmation_state",
        "tool_authorization",
        "tool_execution",
        "playback",
        "coverage_truthfulness_verdict",
    )


def _committed_text_turn() -> dict[str, object]:
    return {
        "event_name": "TURN_INGRESS_COMMITTED",
        "event_id": "evt_turn_committed_text_001",
        "event_seq": 4,
        "turn_id": "turn_text_001",
        "utterance_id": "utt_text_001",
        "input_modality": "text",
        "input_span_id": "input_text_001",
        "text_span_id": "text_span_001",
        "directedness": "ASSUMED_DIRECTED",
        "semantic_close": "ASSUMED_CLOSED",
        "ingress_outcome": "COMMITTED",
    }


def _committed_audio_turn() -> dict[str, object]:
    return {
        "event_name": "TURN_INGRESS_COMMITTED",
        "event_id": "evt_turn_committed_audio_001",
        "event_seq": 8,
        "turn_id": "turn_audio_001",
        "utterance_id": "utt_audio_001",
        "input_modality": "audio",
        "audio_span_id": "audio_span_001",
        "directedness": "DIRECTED",
        "semantic_close": "CLOSED",
        "ingress_outcome": "COMMITTED",
    }


def _forbidden_request_terms_are_absent(value: object) -> bool:
    rendered = repr(value).lower()
    forbidden_terms = (
        "prompt",
        "provider_payload",
        "provider_request",
        "provider_response",
        "raw_audio",
        "audio_bytes",
        "secret",
        "api_key",
        "authorization_header",
        "bearer ",
        "token=",
        "credential=",
    )
    return all(term not in rendered for term in forbidden_terms)
