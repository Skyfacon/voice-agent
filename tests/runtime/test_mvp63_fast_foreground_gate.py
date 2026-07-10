from __future__ import annotations

import pytest

from voice_agent.events.journal import InMemoryEventJournal
from voice_agent.runtime.fast_foreground_gate import (
    FastForegroundGateConfig,
    FastForegroundGateError,
    run_fast_foreground_gate,
)


def test_gate_passes_only_fast_only_answer_low_risk_candidate() -> None:
    journal, candidate_event, output_event, router_event = _journal_with_fast_candidate(
        router_decision="FAST_ONLY",
        foreground_act="ANSWER",
        risk_class="LOW",
        confidence=0.91,
    )

    result = run_fast_foreground_gate(
        journal,
        candidate_event=candidate_event,
        fast_interaction_output_event=output_event,
        router_decision_event=router_event,
        config=FastForegroundGateConfig(confidence_threshold=0.8),
        event_id_prefix="evt_mvp63_gate_pass",
        created_monotonic_ms=50,
        created_wall_clock_ms=1700000000050,
    )

    assert result.gate_event["event_name"] == "FOREGROUND_ACT_GATE_PASSED"
    assert result.gate_event["pass_reason"] == "fast_only_answer_low_risk_confident"
    assert result.committed_event is not None
    assert result.committed_event["event_name"] == "FOREGROUND_OUTPUT_COMMITTED"
    assert result.committed_event["output_basis"] == "reply_candidate"
    assert result.committed_event["output_ref"] == candidate_event["candidate_ref"]
    assert result.committed_event["gate_event_id"] == result.gate_event["event_id"]
    assert result.discarded_event is None
    assert [event["event_name"] for event in journal.events()][-2:] == [
        "FOREGROUND_ACT_GATE_PASSED",
        "FOREGROUND_OUTPUT_COMMITTED",
    ]


def test_gate_discards_spawn_slow_task_candidate_and_commits_template_ack() -> None:
    journal, candidate_event, output_event, router_event = _journal_with_fast_candidate(
        router_decision="SPAWN_SLOW_TASK",
        foreground_act="ANSWER",
        risk_class="LOW",
        confidence=0.91,
    )

    result = run_fast_foreground_gate(
        journal,
        candidate_event=candidate_event,
        fast_interaction_output_event=output_event,
        router_decision_event=router_event,
        config=FastForegroundGateConfig(confidence_threshold=0.8),
        event_id_prefix="evt_mvp63_gate_discard",
        created_monotonic_ms=50,
        created_wall_clock_ms=1700000000050,
    )

    assert result.gate_event["event_name"] == "FOREGROUND_ACT_GATE_FAILED"
    assert result.gate_event["failure_reason"] == "router_decision_not_fast_only"
    assert result.gate_event["downgrade_policy"] == "template_ack"
    assert result.discarded_event is not None
    assert result.discarded_event["event_name"] == "FOREGROUND_OUTPUT_DISCARDED"
    assert result.discarded_event["discard_reason"] == "router_decision_not_fast_only"
    assert result.discarded_event["fast_interaction_output_event_id"] == output_event["event_id"]
    assert result.committed_event is not None
    assert result.committed_event["output_basis"] == "template_ack"
    assert result.committed_event["fallback_reason"] == "router_decision_not_fast_only"
    assert [event["event_name"] for event in journal.events()][-3:] == [
        "FOREGROUND_ACT_GATE_FAILED",
        "FOREGROUND_OUTPUT_DISCARDED",
        "FOREGROUND_OUTPUT_COMMITTED",
    ]


def test_gate_discards_ambiguous_candidate_and_commits_template_clarify() -> None:
    journal, candidate_event, output_event, router_event = _journal_with_fast_candidate(
        router_decision="FAST_ONLY",
        task_focus="AMBIGUOUS",
        foreground_act="ANSWER",
        risk_class="LOW",
        confidence=0.91,
    )

    result = run_fast_foreground_gate(
        journal,
        candidate_event=candidate_event,
        fast_interaction_output_event=output_event,
        router_decision_event=router_event,
        config=FastForegroundGateConfig(confidence_threshold=0.8),
        event_id_prefix="evt_mvp63_gate_ambiguous",
        created_monotonic_ms=50,
        created_wall_clock_ms=1700000000050,
    )

    assert router_event["router_decision"] == "FAST_ONLY"
    assert router_event["task_focus"] == "AMBIGUOUS"
    assert result.gate_event["event_name"] == "FOREGROUND_ACT_GATE_FAILED"
    assert result.gate_event["failure_reason"] == "task_focus_ambiguous"
    assert result.gate_event["downgrade_policy"] == "template_clarify"
    assert result.discarded_event is not None
    assert result.committed_event is not None
    assert result.committed_event["output_basis"] == "template_clarify"
    assert result.committed_event["fallback_policy_ref"].endswith("/template_clarify")


def test_gate_rejects_candidate_from_different_fast_output() -> None:
    journal, candidate_event, output_event, router_event = _journal_with_fast_candidate(
        router_decision="FAST_ONLY",
        foreground_act="ANSWER",
        risk_class="LOW",
        confidence=0.91,
    )
    mismatched_candidate = dict(
        candidate_event,
        fast_interaction_output_event_id="evt_mvp63_other_fast_output",
    )

    with pytest.raises(FastForegroundGateError, match="candidate must reference"):
        run_fast_foreground_gate(
            journal,
            candidate_event=mismatched_candidate,
            fast_interaction_output_event=output_event,
            router_decision_event=router_event,
            config=FastForegroundGateConfig(confidence_threshold=0.8),
            event_id_prefix="evt_mvp63_gate_mismatch",
            created_monotonic_ms=50,
            created_wall_clock_ms=1700000000050,
        )


@pytest.mark.parametrize(
    ("foreground_act", "risk_class", "confidence", "expected_reason"),
    (
        ("ACK_SLOW", "LOW", 0.91, "foreground_act_not_answer"),
        ("ANSWER", "MEDIUM", 0.91, "risk_class_not_low"),
        ("ANSWER", "LOW", 0.42, "confidence_below_threshold"),
    ),
)
def test_gate_fails_candidate_policy_without_slowtask_or_patch_mutation(
    foreground_act: str,
    risk_class: str,
    confidence: float,
    expected_reason: str,
) -> None:
    journal, candidate_event, output_event, router_event = _journal_with_fast_candidate(
        router_decision="FAST_ONLY",
        foreground_act=foreground_act,
        risk_class=risk_class,
        confidence=confidence,
    )

    result = run_fast_foreground_gate(
        journal,
        candidate_event=candidate_event,
        fast_interaction_output_event=output_event,
        router_decision_event=router_event,
        config=FastForegroundGateConfig(confidence_threshold=0.8),
        event_id_prefix=f"evt_mvp63_gate_fail_{expected_reason}",
        created_monotonic_ms=50,
        created_wall_clock_ms=1700000000050,
    )

    assert result.gate_event["event_name"] == "FOREGROUND_ACT_GATE_FAILED"
    assert result.gate_event["failure_reason"] == expected_reason
    assert result.discarded_event is not None
    assert result.discarded_event["discard_reason"] == expected_reason
    assert result.committed_event is not None
    assert result.committed_event["output_basis"] == "template_ack"
    event_names = [event["event_name"] for event in journal.events()]
    assert "SLOWTASK_CREATED" not in event_names
    assert "USER_PATCH_RECEIVED" not in event_names
    assert "SEMANTIC_COMMITMENT_EMITTED" not in event_names


def _journal_with_fast_candidate(
    *,
    router_decision: str,
    foreground_act: str,
    risk_class: str,
    confidence: float,
    task_focus: str | None = None,
) -> tuple[InMemoryEventJournal, dict[str, object], dict[str, object], dict[str, object]]:
    suffix = f"{router_decision}_{foreground_act}_{risk_class}_{int(confidence * 100)}".lower()
    journal = InMemoryEventJournal(
        session_id=f"sess_mvp63_fast_gate_{suffix}",
        conversation_id=f"conv_mvp63_fast_gate_{suffix}",
    )
    session_started = journal.append(
        event_name="SESSION_STARTED",
        event_id=f"evt_{suffix}_session_started",
        source_module="session_runtime",
        created_monotonic_ms=1,
        created_wall_clock_ms=1700000000001,
        trace_redaction_level="metadata_only",
        runtime_config_ref="config://synthetic/mvp63/fast-gate",
        capability_snapshot_ref="capability://synthetic/mvp63/fast-gate",
    )
    turn_committed = journal.append(
        event_name="TURN_INGRESS_COMMITTED",
        event_id=f"evt_{suffix}_turn_committed",
        source_module="interaction_controller",
        caused_by_event_id=str(session_started["event_id"]),
        created_monotonic_ms=10,
        created_wall_clock_ms=1700000000010,
        trace_redaction_level="metadata_only",
        turn_id=f"turn_mvp63_fast_gate_{suffix}",
        utterance_id=f"utt_mvp63_fast_gate_{suffix}",
        input_modality="audio",
        audio_span_id=f"audio_mvp63_fast_gate_{suffix}",
        directedness="ASSUMED_DIRECTED",
        semantic_close="ASSUMED_CLOSED",
        ingress_outcome="COMMITTED",
    )
    output_event = journal.append(
        event_name="FAST_INTERACTION_OUTPUT_EMITTED",
        event_id=f"evt_{suffix}_fast_interaction_output",
        source_module="fast_interaction_adapter",
        caused_by_event_id=str(turn_committed["event_id"]),
        created_monotonic_ms=20,
        created_wall_clock_ms=1700000000020,
        trace_redaction_level="metadata_only",
        adapter_id="mvp63_fast_interaction_runtime",
        adapter_type="fast_interaction",
        adapter_request_id=f"adapter_request_mvp63_fast_gate_{suffix}",
        turn_id=str(turn_committed["turn_id"]),
        utterance_id=str(turn_committed["utterance_id"]),
        input_modality="audio",
        source_event_ids=(str(turn_committed["event_id"]),),
        route_hint_ref=f"route-hint://synthetic/mvp63/fast-gate/{suffix}",
        route_prelude_ref=f"route-prelude://synthetic/mvp63/fast-gate/{suffix}",
        foreground_act=foreground_act,
        final_fast_evidence_ref=f"fast-evidence://synthetic/mvp63/fast-gate/{suffix}",
        schema_name="voice_agent.fast_interaction.output.v1",
        normalization_status="normalized",
        output_mode="real",
        input_mode="audio_native",
        fast_interaction_input_mode="audio_native",
        risk_tags=("low_risk",),
        risk_class=risk_class,
        confidence=confidence,
    )
    candidate_event = journal.append(
        event_name="FOREGROUND_REPLY_CANDIDATE_EMITTED",
        event_id=f"evt_{suffix}_foreground_candidate",
        source_module="fast_interaction_adapter",
        caused_by_event_id=str(output_event["event_id"]),
        created_monotonic_ms=30,
        created_wall_clock_ms=1700000000030,
        trace_redaction_level="metadata_only",
        candidate_id=f"candidate_mvp63_fast_gate_{suffix}",
        fast_interaction_output_event_id=str(output_event["event_id"]),
        turn_id=str(turn_committed["turn_id"]),
        utterance_id=str(turn_committed["utterance_id"]),
        candidate_ref=f"foreground-candidate://synthetic/mvp63/fast-gate/{suffix}",
        candidate_status="complete",
        input_mode="audio_native",
        fast_interaction_input_mode="audio_native",
        source_event_ids=(str(output_event["event_id"]),),
        risk_tags=("low_risk",),
        confidence=confidence,
    )
    router_task_focus = (
        task_focus
        if task_focus is not None
        else "FOREGROUND_CHAT"
        if router_decision == "FAST_ONLY"
        else "AMBIGUOUS"
        if router_decision == "AMBIGUOUS"
        else "NEW_TASK_CANDIDATE"
    )
    router_event = journal.append(
        event_name="ROUTER_DECISION_EMITTED",
        event_id=f"evt_{suffix}_router_decision",
        source_module="router",
        caused_by_event_id=str(turn_committed["event_id"]),
        created_monotonic_ms=40,
        created_wall_clock_ms=1700000000040,
        trace_redaction_level="metadata_only",
        turn_id=str(turn_committed["turn_id"]),
        utterance_id=str(turn_committed["utterance_id"]),
        router_decision=router_decision,
        task_focus=router_task_focus,
        confidence=0.91,
        evidence_uncertainty="low",
        fast_interaction_output_event_id=str(output_event["event_id"]),
    )
    return journal, candidate_event, output_event, router_event
