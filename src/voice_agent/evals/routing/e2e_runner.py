from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any

from voice_agent.evals.routing.case import RoutingCase, validate_routing_case
from voice_agent.evals.routing.event_factory import PredictedRoutingEvidence
from voice_agent.evals.routing.router_runner import (
    RouterPolicyRun,
    run_router_policy_case,
)
from voice_agent.replay.runner import run_replay_fixture
from voice_agent.runtime.fast_foreground_gate import (
    CandidatePolicyDecision,
    FastForegroundGateContext,
    FastForegroundGateResult,
    commit_deferred_foreground_template,
    run_fast_foreground_gate,
)
from voice_agent.slowtask.mock_runtime import MockSlowTaskRuntime
from voice_agent.user_patch.evidence_pack import UserPatchEvidencePackRuntime


class RoutingE2EError(ValueError):
    pass


@dataclass(frozen=True)
class E2EEvaluation:
    """Stable routing prediction populated from actual canonical outcomes."""

    case_id: str
    task_focus: str
    router_decision: str
    foreground_policy: str | None
    slow_task_created: bool
    user_patch_emitted: bool
    external_side_effects: bool
    answer_candidate_committed: bool
    allowed_match: bool
    gate_event_id: str
    foreground_output_event_id: str | None
    slowtask_event_ids: tuple[str, ...]
    user_patch_event_id: str | None
    replay_status: str
    replay_digest: str
    replay_event_count: int
    provider_call_used: bool = False
    gold_written_to_journal: bool = False

    def to_prediction_dict(self) -> dict[str, Any]:
        fields = (
            "case_id",
            "task_focus",
            "router_decision",
            "foreground_policy",
            "slow_task_created",
            "user_patch_emitted",
            "external_side_effects",
            "answer_candidate_committed",
        )
        values = asdict(self)
        return {field: values[field] for field in fields}


@dataclass(frozen=True)
class RoutingE2ERun:
    router_run: RouterPolicyRun
    gate_result: FastForegroundGateResult
    evaluation: E2EEvaluation
    replay_fixture: dict[str, Any]


def run_routing_e2e_case(
    case: RoutingCase | Mapping[str, Any],
    *,
    predicted_evidence: PredictedRoutingEvidence,
) -> RoutingE2ERun:
    normalized = case if isinstance(case, RoutingCase) else validate_routing_case(case)
    router_run = run_router_policy_case(
        normalized,
        predicted_evidence=predicted_evidence,
    )
    return run_routing_e2e_from_router_policy_run(normalized, router_run=router_run)


def run_routing_e2e_from_router_policy_run(
    case: RoutingCase,
    *,
    router_run: RouterPolicyRun,
) -> RoutingE2ERun:
    """Execute gate and state effects from an already-produced Router run."""

    if router_run.evaluation.case_id != case.case_id:
        raise RoutingE2EError("router run case_id must match routing case")
    scenario = router_run.scenario
    if scenario.candidate_event is None:
        raise RoutingE2EError("E2E routing evaluation requires a foreground candidate")
    router_event = _event_by_id(
        scenario.journal.events(),
        router_run.evaluation.router_decision_event_id,
    )
    active_task = case.context.active_task
    active_non_terminal = bool(
        active_task is not None
        and active_task.lifecycle_phase not in {"COMPLETED", "CANCELLED", "FAILED"}
    )
    pending_confirmation = bool(
        active_non_terminal
        and active_task is not None
        and active_task.pending_confirmation_scope is not None
    )
    gate_result = run_fast_foreground_gate(
        scenario.journal,
        candidate_event=scenario.candidate_event,
        fast_interaction_output_event=scenario.fast_interaction_event,
        router_decision_event=router_event,
        context=FastForegroundGateContext(
            authority_mode="trusted_synthetic_eval",
            authority_binding_status="bound",
            interaction_state="TURN_COMMITTED",
            interaction_state_ref=(
                f"interaction-state://synthetic/routing-eval/{case.case_id}"
            ),
            task_focus=str(router_event.get("task_focus", "AMBIGUOUS")),
            task_focus_snapshot_ref=(
                f"task-focus://synthetic/routing-eval/{case.case_id}"
            ),
            has_active_slowtask=active_non_terminal,
            active_task_id=(
                active_task.task_id
                if active_non_terminal and active_task is not None
                else None
            ),
            active_slowtask_lifecycle=(
                active_task.lifecycle_phase
                if active_non_terminal and active_task is not None
                else None
            ),
            active_plan_version=(
                active_task.plan_version
                if active_non_terminal and active_task is not None
                else None
            ),
            active_task_event_seq=(
                2
                if active_non_terminal and active_task is not None
                else None
            ),
            pending_confirmation=pending_confirmation,
            pending_confirmation_id=(
                f"confirmation_routing_eval_{case.case_id}"
                if pending_confirmation
                else None
            ),
            pending_confirmation_scope=(
                active_task.pending_confirmation_scope
                if pending_confirmation and active_task is not None
                else None
            ),
            capability_snapshot_ref=(
                f"capability://synthetic/routing-eval/{case.case_id}"
            ),
            capability_health_status="ready",
            capability_output_mode=str(
                scenario.fast_interaction_event.get("output_mode", "mock")
            ),
            capability_verification_status="provider_free_verified",
            candidate_policy_decision=CandidatePolicyDecision.trusted_synthetic(),
            schema_valid=True,
            confidence_threshold=0.8,
        ),
        event_id_prefix=f"evt_routing_eval_{case.case_id}_foreground_gate",
        created_monotonic_ms=1_040,
        created_wall_clock_ms=1_700_000_001_040,
    )

    slowtask_events: tuple[dict[str, Any], ...] = ()
    user_patch_event: dict[str, Any] | None = None
    patch_completion_event: dict[str, Any] | None = None
    actual_route = router_run.evaluation.router_decision
    if actual_route == "SPAWN_SLOW_TASK":
        spawn = MockSlowTaskRuntime(scenario.journal).create_from_router_spawn(
            router_decision_event=router_event,
            task_id=f"task_routing_eval_spawn_{case.case_id}",
            initial_goal_ref=f"goal://synthetic/routing-eval/{case.case_id}",
            event_id_prefix=f"evt_routing_eval_{case.case_id}_slowtask",
            created_monotonic_ms=1_050,
            created_wall_clock_ms=1_700_000_001_050,
            source_evidence_refs=(
                str(scenario.turn_committed_event["event_id"]),
                str(scenario.fast_interaction_event["event_id"]),
            ),
        )
        slowtask_events = spawn.produced_events
    elif actual_route == "PATCH_ACTIVE_SLOW_TASK":
        snapshot = scenario.router_context.task_focus_snapshot
        if not snapshot.has_active_non_terminal_task:
            raise RoutingE2EError("PATCH route requires active non-terminal task context")
        if snapshot.current_plan_version is None:
            raise RoutingE2EError("PATCH route requires current plan_version")
        patch = UserPatchEvidencePackRuntime(scenario.journal).receive_patch_from_router_decision(
            router_decision_event=router_event,
            turn_committed_event=scenario.turn_committed_event,
            task_id=str(snapshot.active_task_id),
            current_plan_version=snapshot.current_plan_version,
            next_task_event_seq=3,
            patch_id=f"patch_routing_eval_{case.case_id}",
            event_id=f"evt_routing_eval_{case.case_id}_user_patch_received",
            evidence_ref=f"evidence://synthetic/routing-eval/{case.case_id}/patch",
            created_monotonic_ms=1_050,
            created_wall_clock_ms=1_700_000_001_050,
            audio_summary_ref=(
                f"audio-summary://synthetic/routing-eval/{case.case_id}/fast-interaction"
            ),
            candidate_patch_types=_candidate_patch_types(router_run.evaluation.task_focus),
        )
        user_patch_event = patch.user_patch_event
        interpreted_patch = MockSlowTaskRuntime(
            scenario.journal
        ).interpret_user_patch(
            user_patch_event=user_patch_event,
            event_id_prefix=f"evt_routing_eval_{case.case_id}_patch_mutation",
            created_monotonic_ms=1_051,
            created_wall_clock_ms=1_700_000_001_051,
            # The replay fixture materializes every active-task snapshot as a
            # canonical PLANNING prelude. Mutation events must extend that
            # recorded authority rather than a caller-only lifecycle hint.
            current_lifecycle_state="PLANNING",
        )
        patch_completion_event = next(
            (
                event
                for event in interpreted_patch.produced_events
                if event.get("event_name") == "SLOWTASK_STATE_CHANGED"
                and event.get("to_state") == "PLANNING"
                and event.get("task_event_seq")
                == user_patch_event.get("task_event_seq", 0) + 5
                and event.get("plan_version")
                == user_patch_event.get("plan_version", 0) + 1
            ),
            None,
        )

    if actual_route in {"SPAWN_SLOW_TASK", "PATCH_ACTIVE_SLOW_TASK"}:
        mutation_event = (
            next(
                (
                    event
                    for event in slowtask_events
                    if event.get("event_name") == "SLOWTASK_CREATED"
                ),
                None,
            )
            if actual_route == "SPAWN_SLOW_TASK"
            else user_patch_event
        )
        output_basis = (
            "template_clarify"
            if scenario.fast_interaction_event.get("foreground_act") == "CLARIFY"
            else "template_ack"
        )
        if (
            actual_route == "PATCH_ACTIVE_SLOW_TASK"
            and output_basis == "template_ack"
            and patch_completion_event is None
        ):
            # A confirmation-required or otherwise non-material patch is not
            # a completed canonical mutation and cannot truthfully ACK.
            output_basis = "template_clarify"
        gate_result = commit_deferred_foreground_template(
            scenario.journal,
            gate_result=gate_result,
            router_decision_event=router_event,
            output_basis=output_basis,
            mutation_event=(
                mutation_event if output_basis == "template_ack" else None
            ),
            mutation_completion_event=(
                patch_completion_event
                if output_basis == "template_ack"
                and actual_route == "PATCH_ACTIVE_SLOW_TASK"
                else None
            ),
            fallback_reason=(
                "routing_eval_mutation_completed"
                if output_basis == "template_ack"
                else "routing_eval_clarification_required"
            ),
            event_id_prefix=(
                f"evt_routing_eval_{case.case_id}_deferred_foreground"
            ),
            created_monotonic_ms=1_060,
            created_wall_clock_ms=1_700_000_001_060,
        )

    foreground_policy, answer_committed, output_event_id = _foreground_outcome(
        gate_result,
        router_decision=actual_route,
    )
    fixture = _github_allowed_replay_fixture(case, scenario.journal.events())
    replay_result = run_replay_fixture(fixture)
    slow_task_created = bool(slowtask_events)
    user_patch_emitted = user_patch_event is not None
    allowed_match = _matches_gold(
        case,
        task_focus=router_run.evaluation.task_focus,
        router_decision=actual_route,
        foreground_policy=foreground_policy,
        slow_task_created=slow_task_created,
        user_patch_emitted=user_patch_emitted,
        answer_candidate_committed=answer_committed,
    )
    evaluation = E2EEvaluation(
        case_id=case.case_id,
        task_focus=router_run.evaluation.task_focus,
        router_decision=actual_route,
        foreground_policy=foreground_policy,
        slow_task_created=slow_task_created,
        user_patch_emitted=user_patch_emitted,
        external_side_effects=False,
        answer_candidate_committed=answer_committed,
        allowed_match=allowed_match,
        gate_event_id=str(gate_result.gate_event["event_id"]),
        foreground_output_event_id=output_event_id,
        slowtask_event_ids=tuple(str(event["event_id"]) for event in slowtask_events),
        user_patch_event_id=(
            str(user_patch_event["event_id"]) if user_patch_event is not None else None
        ),
        replay_status=replay_result.result_status,
        replay_digest=str(replay_result.state_digest["overall_digest"]),
        replay_event_count=len(replay_result.ordered_events),
    )
    return RoutingE2ERun(
        router_run=router_run,
        gate_result=gate_result,
        evaluation=evaluation,
        replay_fixture=fixture,
    )


def _foreground_outcome(
    gate_result: FastForegroundGateResult,
    *,
    router_decision: str,
) -> tuple[str, bool, str | None]:
    committed = gate_result.committed_event
    if committed is None:
        return "SILENCE", False, None
    output_basis = str(committed["output_basis"])
    if output_basis == "reply_candidate":
        return "ANSWER", True, str(committed["event_id"])
    if output_basis == "template_clarify":
        return "CLARIFY", False, str(committed["event_id"])
    if output_basis == "template_ack":
        if router_decision == "SPAWN_SLOW_TASK":
            return "ACK_SLOW", False, str(committed["event_id"])
        if router_decision == "PATCH_ACTIVE_SLOW_TASK":
            return "ACK_PATCH", False, str(committed["event_id"])
        return "CLARIFY", False, str(committed["event_id"])
    raise RoutingE2EError(f"unsupported foreground output_basis: {output_basis}")


def _candidate_patch_types(task_focus: str) -> tuple[str, ...]:
    if task_focus == "CANCEL_OR_PAUSE_CANDIDATE":
        return ("cancel_candidate",)
    if task_focus == "NEW_TASK_CANDIDATE":
        return ("switch_task_candidate",)
    return ("constraint_update_candidate",)


def _matches_gold(
    case: RoutingCase,
    *,
    task_focus: str,
    router_decision: str,
    foreground_policy: str,
    slow_task_created: bool,
    user_patch_emitted: bool,
    answer_candidate_committed: bool,
) -> bool:
    expected = case.gold.side_effect_expectations
    return (
        task_focus in case.gold.task_focus_allowed
        and router_decision in case.gold.router_decisions_allowed
        and foreground_policy == case.gold.foreground_policy
        and slow_task_created is expected.slow_task_created
        and user_patch_emitted is expected.user_patch_emitted
        and answer_candidate_committed is (case.gold.foreground_policy == "ANSWER")
        and expected.external_side_effects == "FORBIDDEN"
    )


def _github_allowed_replay_fixture(
    case: RoutingCase,
    journal_events: list[dict[str, Any]],
) -> dict[str, Any]:
    events = _events_with_active_task_context(case, journal_events)
    return {
        "replay_manifest": {
            "manifest_schema_version": "1.0",
            "replay_id": f"replay_routing_eval_{case.case_id}",
            "source_trace_ref": f"fixture://routing-eval/{case.case_id}",
            "replay_mode": "deterministic",
            "event_schema_version_range": ["1.0"],
            "fixture_domain": "GITHUB_ALLOWED",
            "generated_from": "synthetic",
            "contains_raw_audio": False,
            "contains_raw_trace": False,
            "contains_real_user_input": False,
            "contains_secrets": False,
            "contains_unredacted_tool_result": False,
            "contains_large_raw_web_content": False,
            "allowed_re_eval_components": [],
        },
        "events": events,
    }


def _events_with_active_task_context(
    case: RoutingCase,
    journal_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Materialize the pre-existing active-task snapshot for replay only.

    Wave-2 policy scenarios carry prior task state as ``TaskFocusSnapshot`` and
    intentionally do not fabricate history in the live journal.  Deterministic
    replay needs that prior state as canonical events before the evaluated turn,
    so this fixture view inserts a minimal synthetic context prelude.
    """

    active_task = case.context.active_task
    if active_task is None or active_task.lifecycle_phase in {"COMPLETED", "CANCELLED", "FAILED"}:
        return _resequence(journal_events)
    events = deepcopy(journal_events)
    capability_index = next(
        index
        for index, event in enumerate(events)
        if event["event_name"] == "ADAPTER_CAPABILITY_SNAPSHOT_RECORDED"
    )
    capability_event = events[capability_index]
    common = {
        "event_schema_version": "1.0",
        "session_id": capability_event["session_id"],
        "conversation_id": capability_event["conversation_id"],
        "source_module": "routing_eval_context_factory",
        "trace_redaction_level": "metadata_only",
    }
    turn_opened = {
        **common,
        "event_name": "TURN_OPENED",
        "event_id": f"evt_routing_eval_{case.case_id}_context_turn_opened",
        "event_seq": 0,
        "caused_by_event_id": capability_event["event_id"],
        "created_monotonic_ms": 1_002,
        "created_wall_clock_ms": 1_700_000_001_002,
        "turn_id": f"turn_routing_eval_{case.case_id}_context",
        "turn_phase": "COLLECTING_INPUT",
        "input_modality": "audio",
        "audio_span_id": f"audio_span_routing_eval_{case.case_id}_context",
    }
    accepted = {
        **common,
        "event_name": "TURN_INGRESS_ACCEPTED",
        "event_id": f"evt_routing_eval_{case.case_id}_context_ingress_accepted",
        "event_seq": 0,
        "caused_by_event_id": turn_opened["event_id"],
        "created_monotonic_ms": 1_003,
        "created_wall_clock_ms": 1_700_000_001_003,
        "turn_id": turn_opened["turn_id"],
        "ingress_outcome": "ACCEPTED",
        "audio_span_id": turn_opened["audio_span_id"],
    }
    committed = {
        **common,
        "event_name": "TURN_INGRESS_COMMITTED",
        "event_id": f"evt_routing_eval_{case.case_id}_context_ingress_committed",
        "event_seq": 0,
        "caused_by_event_id": accepted["event_id"],
        "created_monotonic_ms": 1_004,
        "created_wall_clock_ms": 1_700_000_001_004,
        "turn_id": turn_opened["turn_id"],
        "utterance_id": f"utt_routing_eval_{case.case_id}_context",
        "input_modality": "audio",
        "audio_span_id": turn_opened["audio_span_id"],
        "directedness": "ASSUMED_DIRECTED",
        "semantic_close": "ASSUMED_CLOSED",
        "ingress_outcome": "COMMITTED",
    }
    fast = {
        **common,
        "event_name": "FAST_INTERACTION_OUTPUT_EMITTED",
        "event_id": f"evt_routing_eval_{case.case_id}_context_fast_interaction",
        "event_seq": 0,
        "caused_by_event_id": committed["event_id"],
        "created_monotonic_ms": 1_005,
        "created_wall_clock_ms": 1_700_000_001_005,
        "adapter_id": "routing_eval_context_fast_interaction",
        "adapter_type": "fast_interaction",
        "adapter_request_id": f"req_routing_eval_{case.case_id}_context_fast",
        "turn_id": committed["turn_id"],
        "utterance_id": committed["utterance_id"],
        "input_modality": "audio",
        "input_mode": "audio_native",
        "fast_interaction_input_mode": "audio_native",
        "source_event_ids": [committed["event_id"]],
        "route_hint_ref": f"route-hint://synthetic/routing-eval/{case.case_id}/context",
        "route_prelude_ref": f"route-prelude://synthetic/routing-eval/{case.case_id}/context",
        "route_decision_hint": "SPAWN_SLOW_TASK",
        "task_focus_hint": "NEW_TASK_CANDIDATE",
        "foreground_act": "ACK_SLOW",
        "final_fast_evidence_ref": f"fast-evidence://synthetic/routing-eval/{case.case_id}/context",
        "risk_tags": ["synthetic_eval", "no_external_side_effects"],
        "risk_class": "LOW",
        "confidence": 0.99,
        "schema_name": "voice_agent.fast_interaction.output.v1",
        "normalization_status": "normalized",
        "output_mode": "mock",
    }
    router = {
        **common,
        "source_module": "router",
        "event_name": "ROUTER_DECISION_EMITTED",
        "event_id": f"evt_routing_eval_{case.case_id}_context_router_spawn",
        "event_seq": 0,
        "caused_by_event_id": fast["event_id"],
        "created_monotonic_ms": 1_006,
        "created_wall_clock_ms": 1_700_000_001_006,
        "turn_id": committed["turn_id"],
        "utterance_id": committed["utterance_id"],
        "router_decision": "SPAWN_SLOW_TASK",
        "task_focus": "NEW_TASK_CANDIDATE",
        "confidence": 0.99,
        "evidence_uncertainty": "low",
        "turn_committed_event_id": committed["event_id"],
        "fast_interaction_output_event_id": fast["event_id"],
    }
    created = {
        **common,
        "source_module": "slowtask_runtime",
        "event_name": "SLOWTASK_CREATED",
        "event_id": f"evt_routing_eval_{case.case_id}_context_slowtask_created",
        "event_seq": 0,
        "caused_by_event_id": router["event_id"],
        "created_monotonic_ms": 1_007,
        "created_wall_clock_ms": 1_700_000_001_007,
        "task_id": active_task.task_id,
        "plan_version": active_task.plan_version,
        "task_event_seq": 1,
        "initial_goal_ref": f"goal://synthetic/routing-eval/{case.case_id}/context",
        "source_evidence_refs": [],
    }
    state = {
        **common,
        "source_module": "slowtask_runtime",
        "event_name": "SLOWTASK_STATE_CHANGED",
        "event_id": f"evt_routing_eval_{case.case_id}_context_state_planning",
        "event_seq": 0,
        "caused_by_event_id": created["event_id"],
        "created_monotonic_ms": 1_008,
        "created_wall_clock_ms": 1_700_000_001_008,
        "task_id": active_task.task_id,
        "plan_version": active_task.plan_version,
        "task_event_seq": 2,
        "from_state": "CREATED",
        "to_state": "PLANNING",
        "reason": "synthetic_eval_context_snapshot",
    }
    events[capability_index + 1 : capability_index + 1] = [
        turn_opened,
        accepted,
        committed,
        fast,
        router,
        created,
        state,
    ]
    return _resequence(events)


def _resequence(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    copied = deepcopy(events)
    for event_seq, event in enumerate(copied, start=1):
        event["event_seq"] = event_seq
    return copied


def _event_by_id(events: list[dict[str, Any]], event_id: str) -> dict[str, Any]:
    matches = [event for event in events if event.get("event_id") == event_id]
    if len(matches) != 1:
        raise RoutingE2EError(f"expected exactly one event_id={event_id!r}")
    return matches[0]
