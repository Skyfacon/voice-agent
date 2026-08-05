from __future__ import annotations

import pytest

from qwen_slice3b1_support import (
    SYNTHETIC_RELEASE_TOKEN_REF,
    base_canonical_event,
    valid_adr018_event,
    valid_asr_event,
    valid_legacy_candidate_event,
    valid_parallel_candidate_event,
    valid_parallel_fast_event,
)
from voice_agent.events.envelope import EventValidationError, validate_event_envelope
from voice_agent.events.registry import (
    PARALLEL_CANDIDATE_FIELDS,
    PARALLEL_FAST_OUTPUT_FIELDS,
    PARALLEL_GATE_FIELDS,
)


PARALLEL_GATE_FIELDS = {
    "candidate_check_policy_version": "candidate_check.synthetic.v1",
    "candidate_length_check": "PASS",
    "candidate_duration_check": "PASS",
    "candidate_terminal_check": "PASS",
    "native_pcm_capability_check": "PASS",
    "generation_check": "PASS",
    "context_snapshot_check": "PASS",
    "route_evidence_check": "PASS",
    "candidate_safety_check": "PASS",
    "transcript_digest_check": "PASS",
    "pcm_manifest_check": "PASS",
    "correlation_check": "PASS",
    "provider_session_generation": 1,
    "context_snapshot_id": "context_snapshot_synthetic_001",
    "route_evidence_event_id": "evt_route_evidence_synthetic",
    "candidate_safety_evidence_event_id": "evt_candidate_safety_synthetic",
}


def parallel_gate_event(event_name: str) -> dict[str, object]:
    terminal_fields: dict[str, object]
    if event_name == "FOREGROUND_ACT_GATE_PASSED":
        terminal_fields = {
            "foreground_act": "ANSWER",
            "risk_class": "LOW",
            "pass_reason": "synthetic_all_checks_passed",
            "release_token_ref": SYNTHETIC_RELEASE_TOKEN_REF,
        }
    else:
        terminal_fields = {
            "foreground_act": "CLARIFY",
            "risk_class": "UNKNOWN",
            "failure_reason": "synthetic_fail_closed",
        }
    return base_canonical_event(
        event_name,
        event_id=f"evt_{event_name.lower()}_synthetic",
        event_seq=6,
        caused_by_event_id="evt_router_decision_synthetic",
        gate_decision_id="gate_decision_synthetic_001",
        candidate_event_id="evt_parallel_candidate_synthetic",
        router_decision_event_id="evt_router_decision_synthetic",
        confidence=0.99,
        policy_version="fast_foreground_gate.synthetic.v1",
        fast_interaction_topology="speculative_candidate_parallel_route",
        **PARALLEL_GATE_FIELDS,
        **terminal_fields,
    )


def parallel_committed_event(*, channel: str) -> dict[str, object]:
    return base_canonical_event(
        "FOREGROUND_OUTPUT_COMMITTED",
        event_id="evt_parallel_foreground_output_synthetic",
        event_seq=7,
        caused_by_event_id="evt_foreground_gate_synthetic",
        foreground_output_id="foreground_output_synthetic_001",
        turn_id="turn_slice3b1_synthetic",
        utterance_id="utterance_slice3b1_synthetic",
        output_ref="foreground-output://synthetic/parallel/001",
        output_basis="reply_candidate",
        router_decision_event_id="evt_router_decision_synthetic",
        user_visible_channel=channel,
        gate_event_id="evt_foreground_gate_synthetic",
        fast_interaction_topology="speculative_candidate_parallel_route",
        release_token_ref=SYNTHETIC_RELEASE_TOKEN_REF,
    )


def playback_started_event(*, include_release_binding: bool) -> dict[str, object]:
    fields: dict[str, object] = {
        "playback_span_id": "playback_span_synthetic_001",
        "audio_ref": "audio://synthetic/parallel/001",
    }
    if include_release_binding:
        fields.update(
            release_token_ref=SYNTHETIC_RELEASE_TOKEN_REF,
            provider_session_generation=1,
            qwen_response_id="qwen_response_synthetic_001",
            qwen_output_item_id="qwen_output_item_synthetic_001",
            qwen_output_index=0,
            qwen_content_index=0,
            playback_epoch=0,
        )
    return base_canonical_event(
        "PLAYBACK_SPAN_STARTED",
        event_id="evt_playback_started_synthetic",
        event_seq=8,
        caused_by_event_id="evt_parallel_foreground_output_synthetic",
        **fields,
    )


def without_fields(
    event: dict[str, object], fields: tuple[str, ...]
) -> dict[str, object]:
    for field in fields:
        event.pop(field, None)
    return event


def topology_event_cases() -> tuple[dict[str, object], ...]:
    fast_output = without_fields(
        valid_parallel_fast_event(), PARALLEL_FAST_OUTPUT_FIELDS
    )
    candidate = valid_legacy_candidate_event()
    gate_passed = without_fields(
        parallel_gate_event("FOREGROUND_ACT_GATE_PASSED"),
        (*PARALLEL_GATE_FIELDS, "release_token_ref"),
    )
    gate_failed = without_fields(
        parallel_gate_event("FOREGROUND_ACT_GATE_FAILED"),
        PARALLEL_GATE_FIELDS,
    )
    committed = parallel_committed_event(channel="text")
    committed.pop("release_token_ref")
    return fast_output, candidate, gate_passed, gate_failed, committed


@pytest.mark.parametrize(
    "event",
    topology_event_cases(),
    ids=(
        "fast_output",
        "candidate",
        "gate_passed",
        "gate_failed",
        "committed_output",
    ),
)
def test_unknown_explicit_fast_interaction_topology_fails_closed(
    event: dict[str, object],
) -> None:
    event["fast_interaction_topology"] = "parallel_v2"

    with pytest.raises(EventValidationError, match="fast_interaction_topology"):
        validate_event_envelope(event)


@pytest.mark.parametrize(
    "event",
    topology_event_cases(),
    ids=(
        "fast_output",
        "candidate",
        "gate_passed",
        "gate_failed",
        "committed_output",
    ),
)
def test_explicit_atomic_topology_preserves_legacy_shapes(
    event: dict[str, object],
) -> None:
    event["fast_interaction_topology"] = "atomic_single_call"

    assert validate_event_envelope(event)["fast_interaction_topology"] == (
        "atomic_single_call"
    )


def test_parallel_fast_output_requires_separate_evidence_provenance() -> None:
    event = valid_parallel_fast_event()
    event.pop("candidate_safety_adapter_request_id")

    with pytest.raises(
        EventValidationError, match="candidate_safety_adapter_request_id"
    ):
        validate_event_envelope(event)


def test_parallel_candidate_requires_exact_provider_correlation() -> None:
    event = valid_parallel_candidate_event()
    event.pop("qwen_content_index")

    with pytest.raises(EventValidationError, match="qwen_content_index"):
        validate_event_envelope(event)


def test_legacy_candidate_without_topology_remains_valid() -> None:
    validated = validate_event_envelope(valid_legacy_candidate_event())

    assert validated["event_name"] == "FOREGROUND_REPLY_CANDIDATE_EMITTED"
    assert "fast_interaction_topology" not in validated


def test_qwen_asr_fields_are_all_or_none() -> None:
    event = valid_asr_event()
    event["provider_session_generation"] = 1

    with pytest.raises(EventValidationError, match="qwen_input_item_ref"):
        validate_event_envelope(event)


def test_qwen_asr_correlation_group_and_legacy_asr_both_validate() -> None:
    assert validate_event_envelope(valid_asr_event(qwen_backed=True))[
        "provider_session_generation"
    ] == 1
    assert "provider_session_generation" not in validate_event_envelope(
        valid_asr_event()
    )


@pytest.mark.parametrize(
    ("event_name", "field", "forged"),
    (
        ("ROUTE_EVIDENCE_OUTPUT_EMITTED", "adapter_type", "duplex_model"),
        ("ROUTE_EVIDENCE_OUTPUT_EMITTED", "schema_name", "forged.v1"),
        (
            "CANDIDATE_SAFETY_EVIDENCE_OUTPUT_EMITTED",
            "normalization_status",
            "raw",
        ),
        (
            "CANDIDATE_AUDIO_SHADOW_VERIFICATION_EMITTED",
            "adapter_type",
            "route_evidence",
        ),
    ),
)
def test_adr018_literals_fail_closed(
    event_name: str, field: str, forged: object
) -> None:
    event = valid_adr018_event(event_name)
    event[field] = forged

    with pytest.raises(EventValidationError, match=field):
        validate_event_envelope(event)


def test_adr018_enum_values_fail_closed() -> None:
    event = valid_adr018_event("ROUTE_EVIDENCE_OUTPUT_EMITTED")
    event["route_hint"] = "MODEL_DECIDES"

    with pytest.raises(EventValidationError, match="route_hint"):
        validate_event_envelope(event)


@pytest.mark.parametrize(
    "malformed",
    (
        ["unsafe-enum-marker"],
        {"unsafe-enum-marker": True},
    ),
)
def test_non_hashable_enum_value_fails_with_safe_validation_error(
    malformed: object,
) -> None:
    event = valid_adr018_event("ROUTE_EVIDENCE_OUTPUT_EMITTED")
    event["route_hint"] = malformed

    with pytest.raises(EventValidationError) as exc_info:
        validate_event_envelope(event)

    message = str(exc_info.value)
    assert "route_hint" in message
    assert "unsafe-enum-marker" not in message


def test_provider_rebuild_requires_controller_epoch_binding() -> None:
    event = valid_adr018_event("PROVIDER_CONTEXT_STATE_CHANGED")
    event.update(to_state="REBUILDING", playback_epoch=1)

    with pytest.raises(EventValidationError, match="interaction_state_version"):
        validate_event_envelope(event)

    event["interaction_state_version"] = 1
    assert validate_event_envelope(event)["playback_epoch"] == 1


def test_parallel_gate_pass_requires_opaque_release_authority() -> None:
    event = parallel_gate_event("FOREGROUND_ACT_GATE_PASSED")
    event.pop("release_token_ref")

    with pytest.raises(EventValidationError, match="release_token_ref"):
        validate_event_envelope(event)


def test_parallel_gate_failed_requires_checks_but_not_release_authority() -> None:
    event = parallel_gate_event("FOREGROUND_ACT_GATE_FAILED")

    assert "release_token_ref" not in validate_event_envelope(event)
    event.pop("correlation_check")
    with pytest.raises(EventValidationError, match="correlation_check"):
        validate_event_envelope(event)


def test_parallel_audio_pending_commit_requires_release_authority() -> None:
    event = parallel_committed_event(channel="audio_pending")
    event.pop("release_token_ref")

    with pytest.raises(EventValidationError, match="release_token_ref"):
        validate_event_envelope(event)


@pytest.mark.parametrize("topology", (None, "atomic_single_call"))
def test_atomic_audio_pending_commit_does_not_enter_parallel_release_authority(
    topology: str | None,
) -> None:
    event = parallel_committed_event(channel="audio_pending")
    event.pop("release_token_ref")
    if topology is None:
        event.pop("fast_interaction_topology")
    else:
        event["fast_interaction_topology"] = topology

    validated = validate_event_envelope(event)

    assert "release_token_ref" not in validated


@pytest.mark.parametrize("topology", (None, "atomic_single_call"))
def test_atomic_text_commit_keeps_release_authority_optional(
    topology: str | None,
) -> None:
    event = parallel_committed_event(channel="text")
    event.pop("release_token_ref")
    if topology is None:
        event.pop("fast_interaction_topology")
    else:
        event["fast_interaction_topology"] = topology

    assert "release_token_ref" not in validate_event_envelope(event)


def test_parallel_text_commit_keeps_release_authority_optional() -> None:
    event = parallel_committed_event(channel="text")
    event.pop("release_token_ref")

    assert "release_token_ref" not in validate_event_envelope(event)


def test_provider_native_playback_start_requires_exact_release_binding() -> None:
    event = playback_started_event(include_release_binding=True)
    event.pop("qwen_output_index")

    with pytest.raises(EventValidationError, match="qwen_output_index"):
        validate_event_envelope(event)

    assert validate_event_envelope(
        playback_started_event(include_release_binding=True)
    )["release_token_ref"] == SYNTHETIC_RELEASE_TOKEN_REF


def test_legacy_playback_start_without_release_binding_remains_valid() -> None:
    validated = validate_event_envelope(
        playback_started_event(include_release_binding=False)
    )

    assert "release_token_ref" not in validated
