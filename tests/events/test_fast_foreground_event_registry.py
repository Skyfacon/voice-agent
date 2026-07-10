from __future__ import annotations

from pathlib import Path

import pytest

from voice_agent.events.envelope import EventValidationError, validate_event_envelope
from voice_agent.events.journal import InMemoryEventJournal
from voice_agent.events.registry import EVENT_DEFINITIONS


FAST_FOREGROUND_EVENTS: dict[str, dict[str, object]] = {
    "FAST_INTERACTION_OUTPUT_EMITTED": {
        "category": "adapter_output",
        "required_fields": (
            "adapter_id",
            "adapter_type",
            "adapter_request_id",
            "turn_id",
            "utterance_id",
            "route_hint_ref",
            "route_prelude_ref",
            "foreground_act",
            "final_fast_evidence_ref",
            "schema_name",
            "normalization_status",
            "output_mode",
            "input_mode",
            "fast_interaction_input_mode",
            "source_event_ids",
        ),
        "literal_fields": {
            "adapter_type": "fast_interaction",
            "normalization_status": "normalized",
        },
    },
    "FOREGROUND_REPLY_CANDIDATE_EMITTED": {
        "category": "reply_candidate",
        "required_fields": (
            "candidate_id",
            "fast_interaction_output_event_id",
            "turn_id",
            "utterance_id",
            "candidate_status",
            "input_mode",
            "fast_interaction_input_mode",
            "source_event_ids",
            "risk_tags",
            "confidence",
            "trace_redaction_level",
        ),
        "one_of_fields": (("candidate_ref", "reply_delta_stream_ref"),),
    },
    "FOREGROUND_ACT_GATE_PASSED": {
        "category": "gate_decision",
        "required_fields": (
            "gate_decision_id",
            "candidate_event_id",
            "router_decision_event_id",
            "foreground_act",
            "risk_class",
            "confidence",
            "policy_version",
            "pass_reason",
        ),
        "literal_fields": {
            "foreground_act": "ANSWER",
            "risk_class": "LOW",
        },
    },
    "FOREGROUND_ACT_GATE_FAILED": {
        "category": "gate_decision",
        "required_fields": (
            "gate_decision_id",
            "router_decision_event_id",
            "foreground_act",
            "risk_class",
            "confidence",
            "policy_version",
            "failure_reason",
        ),
    },
    "FOREGROUND_OUTPUT_COMMITTED": {
        "category": "foreground_output",
        "required_fields": (
            "foreground_output_id",
            "turn_id",
            "utterance_id",
            "output_ref",
            "output_basis",
            "router_decision_event_id",
            "user_visible_channel",
        ),
        "any_of_field_sets": (("gate_event_id",), ("fallback_policy_ref", "fallback_reason")),
    },
    "FOREGROUND_OUTPUT_DISCARDED": {
        "category": "foreground_output",
        "required_fields": (
            "discard_id",
            "candidate_event_id",
            "fast_interaction_output_event_id",
            "router_decision_event_id",
            "discard_reason",
        ),
    },
}


def test_adr_017_fast_foreground_events_are_registered_with_expected_metadata() -> None:
    for event_name, expected in FAST_FOREGROUND_EVENTS.items():
        definition = EVENT_DEFINITIONS[event_name]

        assert definition.domain == "fast_foreground"
        assert definition.category == expected["category"]
        assert definition.required_fields == expected["required_fields"]
        assert definition.one_of_fields == expected.get("one_of_fields", ())
        assert definition.any_of_field_sets == expected.get("any_of_field_sets", ())
        assert definition.literal_fields == expected.get("literal_fields", {})


def foreground_event(event_name: str, **overrides: object) -> dict[str, object]:
    event: dict[str, object] = {
        "event_name": event_name,
        "event_id": f"evt_synthetic_{event_name.lower()}",
        "event_seq": 2,
        "event_schema_version": "1.0",
        "session_id": "sess_fast_foreground_registry_synthetic",
        "conversation_id": "conv_fast_foreground_registry_synthetic",
        "source_module": "fast_foreground_registry_test",
        "created_monotonic_ms": 20,
        "created_wall_clock_ms": 1700000000020,
        "caused_by_event_id": "evt_synthetic_prior",
        "trace_redaction_level": "metadata_only",
        "adapter_id": "fast_interaction_synthetic",
        "adapter_request_id": "adapter_request_fast_001",
        "adapter_type": "fast_interaction",
        "candidate_id": "candidate_fast_001",
        "candidate_ref": "candidate://synthetic/fast/001",
        "candidate_event_id": "evt_synthetic_foreground_reply_candidate_emitted",
        "candidate_status": "complete",
        "confidence": 0.91,
        "discard_id": "discard_fast_001",
        "discard_reason": "synthetic_gate_failed",
        "failure_reason": "synthetic_not_fast_only",
        "fast_interaction_output_event_id": "evt_synthetic_fast_interaction_output_emitted",
        "final_fast_evidence_ref": "evidence://synthetic/fast/final",
        "foreground_act": "ANSWER",
        "foreground_output_id": "foreground_output_fast_001",
        "fast_interaction_input_mode": "audio_native",
        "gate_decision_id": "gate_fast_001",
        "gate_event_id": "evt_synthetic_foreground_act_gate_passed",
        "normalization_status": "normalized",
        "output_basis": "reply_candidate",
        "output_mode": "mock",
        "input_mode": "audio_native",
        "output_ref": "foreground-output://synthetic/fast/001",
        "pass_reason": "synthetic_low_risk_fast_only",
        "policy_version": "fast_foreground_gate.synthetic.v1",
        "risk_class": "LOW",
        "risk_tags": ["low_risk"],
        "route_hint_ref": "route-hint://synthetic/fast/001",
        "route_prelude_ref": "route-prelude://synthetic/fast/001",
        "router_decision_event_id": "evt_synthetic_router_decision_emitted",
        "schema_name": "voice_agent.fast_interaction.output.v1",
        "source_event_ids": ("evt_synthetic_turn_ingress_committed",),
        "turn_id": "turn_fast_001",
        "user_visible_channel": "text",
        "utterance_id": "utt_fast_001",
    }
    event.update(overrides)
    return event


@pytest.mark.parametrize("event_name", sorted(FAST_FOREGROUND_EVENTS))
def test_adr_017_fast_foreground_events_validate_with_required_fields(event_name: str) -> None:
    validated = validate_event_envelope(foreground_event(event_name))

    assert validated["event_name"] == event_name


def test_foreground_output_committed_requires_fallback_reason_with_fallback_policy_ref() -> None:
    event = foreground_event(
        "FOREGROUND_OUTPUT_COMMITTED",
        gate_event_id=None,
        fallback_policy_ref="fallback-policy://synthetic/fast/template-ack",
    )

    with pytest.raises(EventValidationError, match="fallback_policy_ref and fallback_reason"):
        validate_event_envelope(event)


def test_adr_017_fast_foreground_events_are_append_only_canonical_journal_events() -> None:
    journal = InMemoryEventJournal(
        session_id="sess_fast_foreground_registry_synthetic",
        conversation_id="conv_fast_foreground_registry_synthetic",
    )
    session_started = journal.append(
        event_name="SESSION_STARTED",
        event_id="evt_fast_foreground_session_started",
        source_module="session_runtime",
        created_monotonic_ms=1,
        created_wall_clock_ms=1700000000001,
        trace_redaction_level="metadata_only",
        runtime_config_ref="config://synthetic/fast-foreground",
        capability_snapshot_ref="capability://synthetic/fast-foreground",
    )
    turn_committed = journal.append(
        event_name="TURN_INGRESS_COMMITTED",
        event_id="evt_fast_foreground_turn_committed",
        source_module="interaction_controller",
        caused_by_event_id=str(session_started["event_id"]),
        created_monotonic_ms=2,
        created_wall_clock_ms=1700000000002,
        trace_redaction_level="metadata_only",
        turn_id="turn_fast_001",
        utterance_id="utt_fast_001",
        input_modality="text",
        text_span_id="text_span_fast_001",
        directedness="ASSUMED_DIRECTED",
        semantic_close="ASSUMED_CLOSED",
        ingress_outcome="COMMITTED",
    )
    fast_output = journal.append(
        event_name="FAST_INTERACTION_OUTPUT_EMITTED",
        event_id="evt_fast_interaction_output_emitted",
        source_module="fast_interaction_adapter",
        caused_by_event_id=str(turn_committed["event_id"]),
        created_monotonic_ms=3,
        created_wall_clock_ms=1700000000003,
        trace_redaction_level="metadata_only",
        adapter_id="fast_interaction_synthetic",
        adapter_type="fast_interaction",
        adapter_request_id="adapter_request_fast_001",
        turn_id="turn_fast_001",
        utterance_id="utt_fast_001",
        route_hint_ref="route-hint://synthetic/fast/001",
        route_prelude_ref="route-prelude://synthetic/fast/001",
        foreground_act="ANSWER",
        final_fast_evidence_ref="evidence://synthetic/fast/final",
        schema_name="voice_agent.fast_interaction.output.v1",
        normalization_status="normalized",
        output_mode="mock",
        input_mode="audio_native",
        fast_interaction_input_mode="audio_native",
        source_event_ids=(str(turn_committed["event_id"]),),
    )
    candidate = journal.append(
        event_name="FOREGROUND_REPLY_CANDIDATE_EMITTED",
        event_id="evt_foreground_reply_candidate_emitted",
        source_module="foreground_buffer",
        caused_by_event_id=str(fast_output["event_id"]),
        created_monotonic_ms=4,
        created_wall_clock_ms=1700000000004,
        trace_redaction_level="metadata_only",
        candidate_id="candidate_fast_001",
        fast_interaction_output_event_id=str(fast_output["event_id"]),
        turn_id="turn_fast_001",
        utterance_id="utt_fast_001",
        candidate_ref="candidate://synthetic/fast/001",
        candidate_status="complete",
        input_mode="audio_native",
        fast_interaction_input_mode="audio_native",
        source_event_ids=(str(turn_committed["event_id"]),),
        risk_tags=["low_risk"],
        confidence=0.91,
    )
    router_decision = journal.append(
        event_name="ROUTER_DECISION_EMITTED",
        event_id="evt_foreground_router_decision_emitted",
        source_module="router",
        caused_by_event_id=str(turn_committed["event_id"]),
        created_monotonic_ms=5,
        created_wall_clock_ms=1700000000005,
        trace_redaction_level="metadata_only",
        turn_id="turn_fast_001",
        utterance_id="utt_fast_001",
        router_decision="FAST_ONLY",
    )
    gate_passed = journal.append(
        event_name="FOREGROUND_ACT_GATE_PASSED",
        event_id="evt_foreground_act_gate_passed",
        source_module="fast_foreground_gate",
        caused_by_event_id=str(router_decision["event_id"]),
        created_monotonic_ms=6,
        created_wall_clock_ms=1700000000006,
        trace_redaction_level="metadata_only",
        gate_decision_id="gate_fast_passed_001",
        candidate_event_id=str(candidate["event_id"]),
        router_decision_event_id=str(router_decision["event_id"]),
        foreground_act="ANSWER",
        risk_class="LOW",
        confidence=0.91,
        policy_version="fast_foreground_gate.synthetic.v1",
        pass_reason="synthetic_low_risk_fast_only",
    )
    committed = journal.append(
        event_name="FOREGROUND_OUTPUT_COMMITTED",
        event_id="evt_foreground_output_committed",
        source_module="foreground_output_runtime",
        caused_by_event_id=str(gate_passed["event_id"]),
        created_monotonic_ms=7,
        created_wall_clock_ms=1700000000007,
        trace_redaction_level="metadata_only",
        foreground_output_id="foreground_output_fast_001",
        turn_id="turn_fast_001",
        utterance_id="utt_fast_001",
        output_ref="foreground-output://synthetic/fast/001",
        output_basis="reply_candidate",
        gate_event_id=str(gate_passed["event_id"]),
        router_decision_event_id=str(router_decision["event_id"]),
        user_visible_channel="text",
    )
    gate_failed = journal.append(
        event_name="FOREGROUND_ACT_GATE_FAILED",
        event_id="evt_foreground_act_gate_failed",
        source_module="fast_foreground_gate",
        caused_by_event_id=str(router_decision["event_id"]),
        created_monotonic_ms=8,
        created_wall_clock_ms=1700000000008,
        trace_redaction_level="metadata_only",
        gate_decision_id="gate_fast_failed_001",
        candidate_event_id=str(candidate["event_id"]),
        router_decision_event_id=str(router_decision["event_id"]),
        foreground_act="ACK_SLOW",
        risk_class="MEDIUM",
        confidence=0.42,
        policy_version="fast_foreground_gate.synthetic.v1",
        failure_reason="synthetic_non_answer_act",
    )
    discarded = journal.append(
        event_name="FOREGROUND_OUTPUT_DISCARDED",
        event_id="evt_foreground_output_discarded",
        source_module="foreground_buffer",
        caused_by_event_id=str(gate_failed["event_id"]),
        created_monotonic_ms=9,
        created_wall_clock_ms=1700000000009,
        trace_redaction_level="metadata_only",
        discard_id="discard_fast_001",
        candidate_event_id=str(candidate["event_id"]),
        fast_interaction_output_event_id=str(fast_output["event_id"]),
        router_decision_event_id=str(router_decision["event_id"]),
        discard_reason="synthetic_non_answer_act",
        replacement_output_event_id=str(committed["event_id"]),
    )

    assert [event["event_seq"] for event in journal.events()] == list(range(1, 10))
    assert discarded["event_name"] == "FOREGROUND_OUTPUT_DISCARDED"


def test_event_registry_spec_lists_adr_017_fast_foreground_events() -> None:
    spec = Path("docs/specs/event-registry.md").read_text(encoding="utf-8")

    assert "ADR-017" in spec
    assert "### Fast foreground events" in spec
    for event_name in FAST_FOREGROUND_EVENTS:
        assert f"`{event_name}`" in spec
    for required_text in (
        "`input_mode`",
        "`fast_interaction_input_mode`",
        "`source_event_ids`",
        "`fast_interaction_provider_ttft_ms`",
        "safe `fast_interaction_*` timing metadata",
    ):
        assert required_text in spec
