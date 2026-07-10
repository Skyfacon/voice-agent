from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from voice_agent.adapters.lalm_thinker_routing_profiles import (
    get_default_lalm_thinker_routing_profile,
)
from voice_agent.router.router import MVP1Router, RouterContext, TaskFocusSnapshot
from voice_agent.runtime.fast_foreground_gate import run_fast_foreground_gate
from voice_agent.runtime.session import start_mvp0_session


@dataclass(frozen=True)
class RoutingGoldenCase:
    case_id: str
    expected_task_focus: str
    expected_router_decision: str
    thinker_task_focus_hint: str | None
    task_like: bool
    complexity_hint: str
    evidence_uncertainty: str
    focus_confidence: float = 0.86
    active_task: bool = False
    directedness: str = "ASSUMED_DIRECTED"
    use_fast_interaction: bool = False
    expected_foreground_gate_decision: str | None = None
    expected_output_basis: str | None = None


def run_mvp6_routing_golden_eval() -> dict[str, Any]:
    profile = get_default_lalm_thinker_routing_profile()
    cases = [_evaluate_case(case) for case in _golden_cases()]
    passed_count = sum(1 for case in cases if case["passed"])
    failed_count = len(cases) - passed_count
    return {
        "status": "passed" if failed_count == 0 else "failed",
        "profile_id": profile.profile_id,
        "profile_version": profile.version,
        "profile_hash": profile.profile_hash,
        "case_count": len(cases),
        "passed_count": passed_count,
        "failed_count": failed_count,
        "cases": cases,
        "provider_call_used": False,
        "network_used": False,
        "credential_env_var_read": False,
        "raw_audio_included": False,
        "raw_provider_body_included": False,
        "prompt_dump_included": False,
        "secret_included": False,
    }


def main() -> int:
    summary = run_mvp6_routing_golden_eval()
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["status"] == "passed" else 1


def _golden_cases() -> tuple[RoutingGoldenCase, ...]:
    return (
        RoutingGoldenCase(
            case_id="zh_foreground_simple",
            expected_task_focus="FOREGROUND_CHAT",
            expected_router_decision="FAST_ONLY",
            thinker_task_focus_hint="FOREGROUND_CHAT",
            task_like=False,
            complexity_hint="simple",
            evidence_uncertainty="low",
        ),
        RoutingGoldenCase(
            case_id="zh_foreground_story_fast_interaction",
            expected_task_focus="FOREGROUND_CHAT",
            expected_router_decision="FAST_ONLY",
            thinker_task_focus_hint=None,
            task_like=False,
            complexity_hint="simple",
            evidence_uncertainty="low",
            use_fast_interaction=True,
            expected_foreground_gate_decision="passed",
            expected_output_basis="reply_candidate",
        ),
        RoutingGoldenCase(
            case_id="zh_complex_new_task",
            expected_task_focus="NEW_TASK_CANDIDATE",
            expected_router_decision="SPAWN_SLOW_TASK",
            thinker_task_focus_hint="NEW_TASK_CANDIDATE",
            task_like=True,
            complexity_hint="complex",
            evidence_uncertainty="low",
        ),
        RoutingGoldenCase(
            case_id="zh_active_task_patch",
            expected_task_focus="ACTIVE_TASK_PATCH",
            expected_router_decision="PATCH_ACTIVE_SLOW_TASK",
            thinker_task_focus_hint="ACTIVE_TASK_PATCH",
            task_like=True,
            complexity_hint="task",
            evidence_uncertainty="low",
            active_task=True,
        ),
        RoutingGoldenCase(
            case_id="zh_ambiguous",
            expected_task_focus="AMBIGUOUS",
            expected_router_decision="FAST_ONLY",
            thinker_task_focus_hint="AMBIGUOUS",
            task_like=False,
            complexity_hint="unknown",
            evidence_uncertainty="high",
            focus_confidence=0.52,
        ),
        RoutingGoldenCase(
            case_id="zh_non_assistant",
            expected_task_focus="NON_ASSISTANT",
            expected_router_decision="IGNORE",
            thinker_task_focus_hint=None,
            task_like=False,
            complexity_hint="simple",
            evidence_uncertainty="low",
            directedness="NOT_DIRECTED",
        ),
        RoutingGoldenCase(
            case_id="zh_active_task_new_task_candidate",
            expected_task_focus="NEW_TASK_CANDIDATE",
            expected_router_decision="PATCH_ACTIVE_SLOW_TASK",
            thinker_task_focus_hint="NEW_TASK_CANDIDATE",
            task_like=True,
            complexity_hint="complex",
            evidence_uncertainty="low",
            active_task=True,
        ),
    )


def _evaluate_case(case: RoutingGoldenCase) -> dict[str, Any]:
    startup = start_mvp0_session(
        session_id=f"sess_mvp6_routing_eval_{case.case_id}",
        conversation_id=f"conv_mvp6_routing_eval_{case.case_id}",
        runtime_config_ref="config://synthetic/mvp6/routing-eval",
        created_monotonic_ms=1000,
        created_wall_clock_ms=1700000001000,
    )
    turn = _append_synthetic_audio_turn(startup.journal, case)
    asr_event = None
    thinker_event = None
    fast_event = None
    candidate_event = None
    if case.use_fast_interaction:
        fast_event = _append_synthetic_fast_interaction_event(startup.journal, turn, case)
        candidate_event = _append_synthetic_foreground_candidate_event(
            startup.journal,
            fast_event,
            case,
        )
    else:
        asr_event = _append_synthetic_asr_event(startup.journal, turn, case)
        thinker_event = _append_synthetic_thinker_event(startup.journal, turn, case)
    result = MVP1Router(startup.journal).emit_decision(
        turn_committed_event=turn,
        asr_frame_event=asr_event,
        thinker_frame_event=thinker_event,
        fast_interaction_output_event=fast_event,
        router_context=_router_context(case),
        event_id=f"evt_mvp6_routing_eval_{case.case_id}_router_decision",
        task_focus_state_event_id=f"evt_mvp6_routing_eval_{case.case_id}_focus_state",
        created_monotonic_ms=1300,
        created_wall_clock_ms=1700000001300,
    )
    gate_result = None
    if fast_event is not None and candidate_event is not None:
        gate_result = run_fast_foreground_gate(
            startup.journal,
            candidate_event=candidate_event,
            fast_interaction_output_event=fast_event,
            router_decision_event=result.router_decision_event,
            event_id_prefix=f"evt_mvp6_routing_eval_{case.case_id}_foreground_gate",
            created_monotonic_ms=1302,
            created_wall_clock_ms=1700000001302,
        )

    actual_task_focus = str(result.router_decision_event["task_focus"])
    actual_router_decision = str(result.router_decision_event["router_decision"])
    actual_gate_decision = _foreground_gate_decision(gate_result)
    actual_output_basis = (
        str(gate_result.committed_event["output_basis"])
        if gate_result is not None and gate_result.committed_event is not None
        else None
    )
    event_names = [str(event["event_name"]) for event in startup.journal.events()]
    passed = (
        actual_task_focus == case.expected_task_focus
        and actual_router_decision == case.expected_router_decision
        and actual_gate_decision == case.expected_foreground_gate_decision
        and actual_output_basis == case.expected_output_basis
    )
    return {
        "case_id": case.case_id,
        "expected_task_focus": case.expected_task_focus,
        "actual_task_focus": actual_task_focus,
        "expected_router_decision": case.expected_router_decision,
        "actual_router_decision": actual_router_decision,
        "expected_foreground_gate_decision": case.expected_foreground_gate_decision,
        "actual_foreground_gate_decision": actual_gate_decision,
        "expected_output_basis": case.expected_output_basis,
        "actual_output_basis": actual_output_basis,
        "fast_interaction_output_mode": (
            str(fast_event["output_mode"]) if fast_event is not None else None
        ),
        "event_names": event_names,
        "passed": passed,
    }


def _append_synthetic_audio_turn(journal: Any, case: RoutingGoldenCase) -> dict[str, Any]:
    suffix = case.case_id
    caused_by_event_id = str(journal.events()[-1]["event_id"])
    turn_opened = journal.append(
        event_name="TURN_OPENED",
        event_id=f"evt_mvp6_routing_eval_{suffix}_turn_opened",
        source_module="interaction_controller",
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=1100,
        created_wall_clock_ms=1700000001100,
        trace_redaction_level="metadata_only",
        turn_id=f"turn_mvp6_routing_eval_{suffix}",
        audio_span_id=f"audio_span_mvp6_routing_eval_{suffix}",
        turn_phase="COLLECTING_INPUT",
        input_modality="audio",
    )
    accepted = journal.append(
        event_name="TURN_INGRESS_ACCEPTED",
        event_id=f"evt_mvp6_routing_eval_{suffix}_ingress_accepted",
        source_module="interaction_controller",
        caused_by_event_id=str(turn_opened["event_id"]),
        created_monotonic_ms=1101,
        created_wall_clock_ms=1700000001101,
        trace_redaction_level="metadata_only",
        turn_id=str(turn_opened["turn_id"]),
        audio_span_id=str(turn_opened["audio_span_id"]),
        ingress_outcome="ACCEPTED",
    )
    return journal.append(
        event_name="TURN_INGRESS_COMMITTED",
        event_id=f"evt_mvp6_routing_eval_{suffix}_ingress_committed",
        source_module="interaction_controller",
        caused_by_event_id=str(accepted["event_id"]),
        created_monotonic_ms=1102,
        created_wall_clock_ms=1700000001102,
        trace_redaction_level="metadata_only",
        turn_id=str(turn_opened["turn_id"]),
        utterance_id=f"utt_mvp6_routing_eval_{suffix}",
        audio_span_id=str(turn_opened["audio_span_id"]),
        input_modality="audio",
        directedness=case.directedness,
        semantic_close="ASSUMED_CLOSED",
        ingress_outcome="COMMITTED",
    )


def _append_synthetic_asr_event(
    journal: Any,
    turn: dict[str, Any],
    case: RoutingGoldenCase,
) -> dict[str, Any]:
    suffix = case.case_id
    return journal.append(
        event_name="ASR_TRANSCRIPT_OUTPUT_EMITTED",
        event_id=f"evt_mvp6_routing_eval_{suffix}_asr",
        source_module="asr_adapter",
        caused_by_event_id=str(turn["event_id"]),
        created_monotonic_ms=1200,
        created_wall_clock_ms=1700000001200,
        trace_redaction_level="metadata_only",
        adapter_id="mvp6_routing_eval_asr",
        adapter_type="asr",
        adapter_request_id=f"adapter_request_mvp6_routing_eval_{suffix}_asr",
        turn_id=str(turn["turn_id"]),
        utterance_id=str(turn["utterance_id"]),
        input_modality="audio",
        audio_span_id=str(turn["audio_span_id"]),
        asr_frame_ref=f"asr-frame://synthetic/mvp6/routing-eval/{suffix}",
        text_ref=f"text://synthetic/mvp6/routing-eval/{suffix}",
        transcript_finality="final",
        timestamp_status="available",
        streaming_status="supported",
        output_mode="degraded",
    )


def _append_synthetic_thinker_event(
    journal: Any,
    turn: dict[str, Any],
    case: RoutingGoldenCase,
) -> dict[str, Any]:
    suffix = case.case_id
    fields: dict[str, Any] = {}
    if case.thinker_task_focus_hint is not None:
        fields["task_focus_hint"] = case.thinker_task_focus_hint
    return journal.append(
        event_name="THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED",
        event_id=f"evt_mvp6_routing_eval_{suffix}_thinker",
        source_module="thinker_adapter",
        caused_by_event_id=str(turn["event_id"]),
        created_monotonic_ms=1201,
        created_wall_clock_ms=1700000001201,
        trace_redaction_level="metadata_only",
        adapter_id="mvp6_routing_eval_thinker",
        adapter_type="thinker",
        adapter_request_id=f"adapter_request_mvp6_routing_eval_{suffix}_thinker",
        turn_id=str(turn["turn_id"]),
        utterance_id=str(turn["utterance_id"]),
        input_modality="audio",
        audio_span_id=str(turn["audio_span_id"]),
        semantic_frame_schema="voice_agent.semantic_frame.v1",
        normalization_status="normalized",
        semantic_frame_ref=f"semantic-frame://synthetic/mvp6/routing-eval/{suffix}",
        semantic_summary_ref=f"summary://synthetic/mvp6/routing-eval/{suffix}",
        semantic_close_status="available",
        assistant_directedness_status="available",
        emotion_status="available",
        audio_caption_status="available",
        semantic_close_ref=f"semantic-close://synthetic/mvp6/routing-eval/{suffix}",
        assistant_directedness_ref=f"assistant-directedness://synthetic/mvp6/routing-eval/{suffix}",
        emotion_ref=f"emotion://synthetic/mvp6/routing-eval/{suffix}",
        audio_caption_ref=f"audio-caption://synthetic/mvp6/routing-eval/{suffix}",
        output_mode="degraded",
        task_like=case.task_like,
        complexity_hint=case.complexity_hint,
        focus_confidence=case.focus_confidence,
        evidence_uncertainty=case.evidence_uncertainty,
        **fields,
    )


def _append_synthetic_fast_interaction_event(
    journal: Any,
    turn: dict[str, Any],
    case: RoutingGoldenCase,
) -> dict[str, Any]:
    suffix = case.case_id
    return journal.append(
        event_name="FAST_INTERACTION_OUTPUT_EMITTED",
        event_id=f"evt_mvp6_routing_eval_{suffix}_fast_interaction",
        source_module="fast_interaction_adapter",
        caused_by_event_id=str(turn["event_id"]),
        created_monotonic_ms=1201,
        created_wall_clock_ms=1700000001201,
        trace_redaction_level="metadata_only",
        adapter_id="mvp63_fast_interaction_runtime",
        adapter_type="fast_interaction",
        adapter_request_id=f"adapter_request_mvp6_routing_eval_{suffix}_fast_interaction",
        turn_id=str(turn["turn_id"]),
        utterance_id=str(turn["utterance_id"]),
        input_modality="audio",
        input_mode="audio_native",
        fast_interaction_input_mode="audio_native",
        source_event_ids=(str(turn["event_id"]),),
        route_hint_ref=f"route-hint://synthetic/mvp6/routing-eval/{suffix}",
        route_prelude_ref=f"route-prelude://synthetic/mvp6/routing-eval/{suffix}",
        route_decision_hint="FAST_ONLY",
        task_focus_hint="FOREGROUND_CHAT",
        foreground_act="ANSWER",
        final_fast_evidence_ref=f"fast-evidence://synthetic/mvp6/routing-eval/{suffix}",
        risk_tags=("low_risk", "no_side_effects"),
        risk_class="LOW",
        confidence=case.focus_confidence,
        schema_name="voice_agent.fast_interaction.output.v1",
        normalization_status="normalized",
        output_mode="real",
    )


def _append_synthetic_foreground_candidate_event(
    journal: Any,
    fast_event: dict[str, Any],
    case: RoutingGoldenCase,
) -> dict[str, Any]:
    suffix = case.case_id
    return journal.append(
        event_name="FOREGROUND_REPLY_CANDIDATE_EMITTED",
        event_id=f"evt_mvp6_routing_eval_{suffix}_foreground_candidate",
        source_module="foreground_buffer",
        caused_by_event_id=str(fast_event["event_id"]),
        created_monotonic_ms=1202,
        created_wall_clock_ms=1700000001202,
        trace_redaction_level="metadata_only",
        candidate_id=f"candidate_mvp6_routing_eval_{suffix}",
        fast_interaction_output_event_id=str(fast_event["event_id"]),
        turn_id=str(fast_event["turn_id"]),
        utterance_id=str(fast_event["utterance_id"]),
        input_mode=str(fast_event["input_mode"]),
        fast_interaction_input_mode=str(fast_event["fast_interaction_input_mode"]),
        source_event_ids=(str(fast_event["event_id"]),),
        candidate_ref=f"foreground-candidate://synthetic/mvp6/routing-eval/{suffix}",
        candidate_status="complete",
        risk_tags=("low_risk", "no_side_effects"),
        confidence=case.focus_confidence,
    )


def _foreground_gate_decision(gate_result: Any) -> str | None:
    if gate_result is None:
        return None
    event_name = gate_result.gate_event.get("event_name")
    if event_name == "FOREGROUND_ACT_GATE_PASSED":
        return "passed"
    if event_name == "FOREGROUND_ACT_GATE_FAILED":
        return "failed"
    return None


def _router_context(case: RoutingGoldenCase) -> RouterContext:
    if not case.active_task:
        return RouterContext(task_focus_snapshot=TaskFocusSnapshot())
    return RouterContext(
        task_focus_snapshot=TaskFocusSnapshot(
            active_task_id=f"task_mvp6_routing_eval_{case.case_id}",
            lifecycle_phase="PLANNING",
            current_plan_version=1,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
