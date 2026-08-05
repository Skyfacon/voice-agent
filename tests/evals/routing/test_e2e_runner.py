from __future__ import annotations

import json

import pytest

from voice_agent.evals.routing.case import ROUTING_CASE_SCHEMA_NAME, RoutingCase, validate_routing_case
from voice_agent.evals.routing.e2e_runner import run_routing_e2e_case
from voice_agent.evals.routing.event_factory import PredictedRoutingEvidence


ALL_ROUTES = {"FAST_ONLY", "SPAWN_SLOW_TASK", "PATCH_ACTIVE_SLOW_TASK", "IGNORE"}


def _case(
    *,
    case_id: str,
    focus: str,
    route: str,
    policy: str,
    context: dict[str, object] | None = None,
) -> RoutingCase:
    return validate_routing_case(
        {
            "schema_name": ROUTING_CASE_SCHEMA_NAME,
            "case_id": case_id,
            "scenario_family_id": f"family_{case_id}",
            "split": "prompt_dev",
            "input": {
                "modality": "text",
                "locale": "zh-CN",
                "utterance_text": "这是合成的端到端路由评测输入。",
            },
            "context": context or {"template": "NO_ACTIVE_TASK"},
            "gold": {
                "task_focus_allowed": [focus],
                "router_decisions_allowed": [route],
                "router_decisions_forbidden": sorted(ALL_ROUTES - {route}),
                "foreground_policy": policy,
                "side_effect_expectations": {
                    "slow_task_created": route == "SPAWN_SLOW_TASK",
                    "user_patch_emitted": route == "PATCH_ACTIVE_SLOW_TASK",
                    "external_side_effects": "FORBIDDEN",
                },
            },
            "tags": ["e2e_test"],
            "criticality": "high",
            "annotation_status": "draft",
        }
    )


def _active_context(
    *, lifecycle_phase: str = "PLANNING", plan_version: int = 2
) -> dict[str, object]:
    return {
        "template": "ACTIVE_TASK_PLANNING",
        "active_task": {
            "task_id": "task_existing_trip",
            "task_type": "trip_planning",
            "summary": "规划上海三日游。",
            "lifecycle_phase": lifecycle_phase,
            "plan_version": plan_version,
        },
    }


def _terminal_context() -> dict[str, object]:
    return {
        "template": "TERMINAL_TASK",
        "active_task": {
            "task_id": "task_completed_trip",
            "task_type": "trip_planning",
            "summary": "已完成上海三日游规划。",
            "lifecycle_phase": "COMPLETED",
            "plan_version": 3,
        },
    }


def _evidence(
    *,
    focus: str | None,
    route: str,
    act: str,
    directedness: str = "ASSUMED_DIRECTED",
    confidence: float = 0.95,
) -> PredictedRoutingEvidence:
    return PredictedRoutingEvidence(
        task_focus_hint=focus,
        route_decision_hint=route,
        task_like=focus
        in {"NEW_TASK_CANDIDATE", "ACTIVE_TASK_PATCH", "CANCEL_OR_PAUSE_CANDIDATE"},
        complexity_hint=(
            "task"
            if focus
            in {"NEW_TASK_CANDIDATE", "ACTIVE_TASK_PATCH", "CANCEL_OR_PAUSE_CANDIDATE"}
            else "simple"
        ),
        evidence_uncertainty="high" if focus == "AMBIGUOUS" else "low",
        directedness=directedness,
        foreground_act=act,
        confidence=confidence,
    )


def test_fast_e2e_commits_answer_candidate_without_task_side_effects() -> None:
    case = _case(
        case_id="e2e_fast",
        focus="FOREGROUND_CHAT",
        route="FAST_ONLY",
        policy="ANSWER",
    )

    run = run_routing_e2e_case(
        case,
        predicted_evidence=_evidence(
            focus="FOREGROUND_CHAT", route="FAST_ONLY", act="ANSWER"
        ),
    )

    assert run.evaluation.foreground_policy == "ANSWER"
    assert run.evaluation.answer_candidate_committed is True
    assert run.evaluation.slow_task_created is False
    assert run.evaluation.user_patch_emitted is False
    assert run.evaluation.external_side_effects is False
    assert run.evaluation.allowed_match is True
    assert run.gate_result.gate_event["event_name"] == "FOREGROUND_ACT_GATE_PASSED"
    assert run.evaluation.replay_status == "passed"
    assert run.evaluation.replay_digest


def test_spawn_e2e_uses_mock_slowtask_runtime_and_template_ack() -> None:
    case = _case(
        case_id="e2e_spawn",
        focus="NEW_TASK_CANDIDATE",
        route="SPAWN_SLOW_TASK",
        policy="ACK_SLOW",
    )

    run = run_routing_e2e_case(
        case,
        predicted_evidence=_evidence(
            focus="NEW_TASK_CANDIDATE",
            route="SPAWN_SLOW_TASK",
            act="ACK_SLOW",
        ),
    )

    names = [event["event_name"] for event in run.router_run.scenario.journal.events()]
    assert names[-3:] == [
        "SLOWTASK_CREATED",
        "SLOWTASK_STATE_CHANGED",
        "FOREGROUND_OUTPUT_COMMITTED",
    ]
    assert run.evaluation.slow_task_created is True
    assert run.evaluation.slowtask_event_ids
    assert run.evaluation.foreground_policy == "ACK_SLOW"
    assert run.evaluation.answer_candidate_committed is False
    assert run.evaluation.allowed_match is True
    assert run.evaluation.replay_status == "passed"


def test_patch_e2e_emits_user_patch_from_turn_and_safe_audio_summary() -> None:
    case = _case(
        case_id="e2e_patch",
        focus="ACTIVE_TASK_PATCH",
        route="PATCH_ACTIVE_SLOW_TASK",
        policy="ACK_PATCH",
        context=_active_context(plan_version=2),
    )

    run = run_routing_e2e_case(
        case,
        predicted_evidence=_evidence(
            focus="ACTIVE_TASK_PATCH",
            route="PATCH_ACTIVE_SLOW_TASK",
            act="ACK_PATCH",
        ),
    )

    patch_events = [
        event
        for event in run.router_run.scenario.journal.events()
        if event["event_name"] == "USER_PATCH_RECEIVED"
    ]
    names = [
        event["event_name"]
        for event in run.router_run.scenario.journal.events()
    ]
    assert len(patch_events) == 1
    patch = patch_events[0]
    assert patch["plan_version"] == 2
    assert patch["task_event_seq"] == 3
    assert patch["authoritative_evidence_refs"] == [
        "audio-span://audio_span_routing_eval_e2e_patch"
    ]
    assert patch["non_authoritative_hypothesis_refs"] == [
        "audio-summary://synthetic/routing-eval/e2e_patch/fast-interaction"
    ]
    assert names[names.index("USER_PATCH_RECEIVED") :] == [
        "USER_PATCH_RECEIVED",
        "USER_PATCH_INTERPRETED",
        "PLAN_VERSION_ADVANCED",
        "PLANNING_RESTARTED",
        "TASK_REPLANNED",
        "SLOWTASK_STATE_CHANGED",
        "FOREGROUND_OUTPUT_COMMITTED",
    ]
    assert run.evaluation.user_patch_emitted is True
    assert run.evaluation.foreground_policy == "ACK_PATCH"
    assert run.evaluation.allowed_match is True
    assert run.evaluation.replay_status == "passed"


def test_patch_clarify_e2e_emits_patch_and_canonical_clarification_template() -> None:
    case = _case(
        case_id="e2e_patch_clarify",
        focus="CANCEL_OR_PAUSE_CANDIDATE",
        route="PATCH_ACTIVE_SLOW_TASK",
        policy="CLARIFY",
        context=_active_context(plan_version=2),
    )

    run = run_routing_e2e_case(
        case,
        predicted_evidence=_evidence(
            focus="CANCEL_OR_PAUSE_CANDIDATE",
            route="PATCH_ACTIVE_SLOW_TASK",
            act="CLARIFY",
        ),
    )

    assert run.gate_result.gate_event["event_name"] == "FOREGROUND_ACT_GATE_FAILED"
    assert (
        run.gate_result.gate_event["downgrade_policy"]
        == "deferred_mutation_outcome"
    )
    assert run.gate_result.discarded_event is not None
    assert run.gate_result.committed_event is not None
    assert run.gate_result.committed_event["event_name"] == "FOREGROUND_OUTPUT_COMMITTED"
    assert run.gate_result.committed_event["output_basis"] == "template_clarify"
    assert run.gate_result.committed_event["caused_by_event_id"] == run.gate_result.gate_event["event_id"]
    assert run.evaluation.foreground_policy == "CLARIFY"
    assert run.evaluation.answer_candidate_committed is False
    assert run.evaluation.user_patch_emitted is True
    assert run.evaluation.allowed_match is True
    assert run.evaluation.replay_status == "passed"


def test_ignore_e2e_discards_candidate_and_remains_silent() -> None:
    case = _case(
        case_id="e2e_ignore",
        focus="NON_ASSISTANT",
        route="IGNORE",
        policy="SILENCE",
        context={"template": "NON_ASSISTANT_BACKGROUND"},
    )

    run = run_routing_e2e_case(
        case,
        predicted_evidence=_evidence(
            focus=None,
            route="IGNORE",
            act="SILENCE",
            directedness="NOT_DIRECTED",
        ),
    )

    assert run.gate_result.discarded_event is not None
    assert run.gate_result.committed_event is None
    assert run.evaluation.foreground_policy == "SILENCE"
    assert run.evaluation.answer_candidate_committed is False
    assert run.evaluation.slow_task_created is False
    assert run.evaluation.user_patch_emitted is False
    assert run.evaluation.allowed_match is True
    assert run.evaluation.replay_status == "passed"


def test_ambiguous_e2e_uses_clarify_template_without_task_mutation() -> None:
    case = _case(
        case_id="e2e_ambiguous",
        focus="AMBIGUOUS",
        route="FAST_ONLY",
        policy="CLARIFY",
    )

    run = run_routing_e2e_case(
        case,
        predicted_evidence=_evidence(
            focus="AMBIGUOUS", route="FAST_ONLY", act="CLARIFY"
        ),
    )

    assert run.gate_result.gate_event["event_name"] == "FOREGROUND_ACT_GATE_FAILED"
    assert run.gate_result.committed_event is not None
    assert run.gate_result.committed_event["output_basis"] == "template_clarify"
    assert run.evaluation.foreground_policy == "CLARIFY"
    assert run.evaluation.answer_candidate_committed is False
    assert run.evaluation.allowed_match is True
    assert run.evaluation.replay_status == "passed"


def test_terminal_task_context_does_not_patch_and_can_spawn_new_task() -> None:
    case = _case(
        case_id="e2e_terminal_spawn",
        focus="NEW_TASK_CANDIDATE",
        route="SPAWN_SLOW_TASK",
        policy="ACK_SLOW",
        context=_terminal_context(),
    )

    run = run_routing_e2e_case(
        case,
        predicted_evidence=_evidence(
            focus="NEW_TASK_CANDIDATE",
            route="SPAWN_SLOW_TASK",
            act="ACK_SLOW",
        ),
    )

    assert run.router_run.scenario.router_context.task_focus_snapshot.has_active_non_terminal_task is False
    assert run.evaluation.router_decision == "SPAWN_SLOW_TASK"
    assert run.evaluation.slow_task_created is True
    assert run.evaluation.user_patch_emitted is False
    assert run.evaluation.allowed_match is True
    assert run.evaluation.replay_status == "passed"


def test_wrong_fast_prediction_never_uses_spawn_gold_to_create_task() -> None:
    case = _case(
        case_id="e2e_wrong_fast",
        focus="NEW_TASK_CANDIDATE",
        route="SPAWN_SLOW_TASK",
        policy="ACK_SLOW",
    )

    run = run_routing_e2e_case(
        case,
        predicted_evidence=_evidence(
            focus="FOREGROUND_CHAT", route="FAST_ONLY", act="ANSWER"
        ),
    )

    assert run.evaluation.router_decision == "FAST_ONLY"
    assert run.evaluation.slow_task_created is False
    assert run.evaluation.answer_candidate_committed is True
    assert run.evaluation.allowed_match is False
    assert run.evaluation.replay_status == "passed"


def test_e2e_prediction_contract_and_replay_are_deterministic() -> None:
    case = _case(
        case_id="e2e_deterministic",
        focus="FOREGROUND_CHAT",
        route="FAST_ONLY",
        policy="ANSWER",
    )
    evidence = _evidence(focus="FOREGROUND_CHAT", route="FAST_ONLY", act="ANSWER")

    first = run_routing_e2e_case(case, predicted_evidence=evidence)
    second = run_routing_e2e_case(case, predicted_evidence=evidence)

    assert first.evaluation.to_prediction_dict() == {
        "case_id": "e2e_deterministic",
        "task_focus": "FOREGROUND_CHAT",
        "router_decision": "FAST_ONLY",
        "foreground_policy": "ANSWER",
        "slow_task_created": False,
        "user_patch_emitted": False,
        "external_side_effects": False,
        "answer_candidate_committed": True,
    }
    assert first.evaluation.replay_digest == second.evaluation.replay_digest
    assert first.replay_fixture == second.replay_fixture


def test_e2e_journal_and_replay_fixture_do_not_contain_gold_or_provider_payload() -> None:
    case = _case(
        case_id="e2e_safety",
        focus="FOREGROUND_CHAT",
        route="FAST_ONLY",
        policy="ANSWER",
    )

    run = run_routing_e2e_case(
        case,
        predicted_evidence=_evidence(
            focus="FOREGROUND_CHAT", route="FAST_ONLY", act="ANSWER"
        ),
    )

    serialized = json.dumps(
        {
            "journal": run.router_run.scenario.journal.events(),
            "fixture": run.replay_fixture,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    for forbidden in (
        "task_focus_allowed",
        "router_decisions_allowed",
        "router_decisions_forbidden",
        "foreground_policy",
        "provider_body",
        "provider_payload",
        "raw_audio_ref",
        "raw_audio_bytes",
    ):
        assert forbidden not in serialized
    assert run.replay_fixture["replay_manifest"]["contains_raw_audio"] is False
    assert run.evaluation.provider_call_used is False
    assert run.evaluation.gold_written_to_journal is False
