from __future__ import annotations

import json

import pytest

from voice_agent.evals.routing.case import ROUTING_CASE_SCHEMA_NAME, RoutingCase, validate_routing_case
from voice_agent.evals.routing.event_factory import PredictedRoutingEvidence
from voice_agent.evals.routing.router_runner import (
    oracle_policy_evidence_from_gold,
    run_router_policy_case,
)


ALL_ROUTES = {"FAST_ONLY", "SPAWN_SLOW_TASK", "PATCH_ACTIVE_SLOW_TASK", "IGNORE"}


def _case(
    *,
    case_id: str,
    task_focus: str,
    route: str,
    context: dict[str, object] | None = None,
    foreground_policy: str = "ANSWER",
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
                "utterance_text": "这是一个完全合成的路由评测输入。",
            },
            "context": context or {"template": "NO_ACTIVE_TASK"},
            "gold": {
                "task_focus_allowed": [task_focus],
                "router_decisions_allowed": [route],
                "router_decisions_forbidden": sorted(ALL_ROUTES - {route}),
                "foreground_policy": foreground_policy,
                "side_effect_expectations": {
                    "slow_task_created": route == "SPAWN_SLOW_TASK",
                    "user_patch_emitted": route == "PATCH_ACTIVE_SLOW_TASK",
                    "external_side_effects": "FORBIDDEN",
                },
            },
            "tags": ["router_policy_test"],
            "criticality": "medium",
            "annotation_status": "draft",
        }
    )


def _active_context() -> dict[str, object]:
    return {
        "template": "ACTIVE_TASK_PLANNING",
        "active_task": {
            "task_id": "task_trip_001",
            "task_type": "trip_planning",
            "summary": "规划上海三日游。",
            "lifecycle_phase": "PLANNING",
            "plan_version": 1,
        },
    }


@pytest.mark.parametrize(
    ("case", "evidence", "expected_focus", "expected_route"),
    (
        (
            _case(
                case_id="route_fast",
                task_focus="FOREGROUND_CHAT",
                route="FAST_ONLY",
            ),
            PredictedRoutingEvidence(
                task_focus_hint="FOREGROUND_CHAT",
                route_decision_hint="FAST_ONLY",
                task_like=False,
                complexity_hint="simple",
                evidence_uncertainty="low",
                foreground_act="ANSWER",
            ),
            "FOREGROUND_CHAT",
            "FAST_ONLY",
        ),
        (
            _case(
                case_id="route_spawn",
                task_focus="NEW_TASK_CANDIDATE",
                route="SPAWN_SLOW_TASK",
                foreground_policy="ACK_SLOW",
            ),
            PredictedRoutingEvidence(
                task_focus_hint="NEW_TASK_CANDIDATE",
                route_decision_hint="SPAWN_SLOW_TASK",
                task_like=True,
                complexity_hint="complex",
                evidence_uncertainty="low",
                foreground_act="ACK_SLOW",
            ),
            "NEW_TASK_CANDIDATE",
            "SPAWN_SLOW_TASK",
        ),
        (
            _case(
                case_id="route_patch",
                task_focus="ACTIVE_TASK_PATCH",
                route="PATCH_ACTIVE_SLOW_TASK",
                context=_active_context(),
                foreground_policy="ACK_PATCH",
            ),
            PredictedRoutingEvidence(
                task_focus_hint="ACTIVE_TASK_PATCH",
                route_decision_hint="PATCH_ACTIVE_SLOW_TASK",
                task_like=True,
                complexity_hint="task",
                evidence_uncertainty="low",
                foreground_act="ACK_PATCH",
            ),
            "ACTIVE_TASK_PATCH",
            "PATCH_ACTIVE_SLOW_TASK",
        ),
        (
            _case(
                case_id="route_ignore",
                task_focus="NON_ASSISTANT",
                route="IGNORE",
                context={"template": "NON_ASSISTANT_BACKGROUND"},
                foreground_policy="SILENCE",
            ),
            PredictedRoutingEvidence(
                task_focus_hint=None,
                route_decision_hint="IGNORE",
                task_like=False,
                complexity_hint="simple",
                evidence_uncertainty="low",
                directedness="NOT_DIRECTED",
                foreground_act="SILENCE",
            ),
            "NON_ASSISTANT",
            "IGNORE",
        ),
    ),
)
def test_router_runner_covers_all_four_routes_using_explicit_prediction(
    case: RoutingCase,
    evidence: PredictedRoutingEvidence,
    expected_focus: str,
    expected_route: str,
) -> None:
    run = run_router_policy_case(case, predicted_evidence=evidence)

    assert run.evaluation.task_focus == expected_focus
    assert run.evaluation.router_decision == expected_route
    assert run.evaluation.allowed_match is True
    assert run.evaluation.router_decision_event_id in run.evaluation.event_ids
    assert run.evaluation.task_focus_state_event_id in run.evaluation.event_ids


def test_runner_does_not_derive_prediction_from_gold() -> None:
    spawn_gold = _case(
        case_id="wrong_prediction_must_fail",
        task_focus="NEW_TASK_CANDIDATE",
        route="SPAWN_SLOW_TASK",
        foreground_policy="ACK_SLOW",
    )
    deliberately_wrong_prediction = PredictedRoutingEvidence(
        task_focus_hint="FOREGROUND_CHAT",
        route_decision_hint="FAST_ONLY",
        task_like=False,
        complexity_hint="simple",
        evidence_uncertainty="low",
        foreground_act="ANSWER",
    )

    run = run_router_policy_case(
        spawn_gold,
        predicted_evidence=deliberately_wrong_prediction,
    )

    assert run.evaluation.task_focus == "FOREGROUND_CHAT"
    assert run.evaluation.router_decision == "FAST_ONLY"
    assert run.evaluation.task_focus_allowed_match is False
    assert run.evaluation.router_decision_allowed_match is False
    assert run.evaluation.allowed_match is False


def test_runner_requires_predicted_evidence_as_keyword_argument() -> None:
    case = _case(
        case_id="prediction_required",
        task_focus="FOREGROUND_CHAT",
        route="FAST_ONLY",
    )

    with pytest.raises(TypeError, match="predicted_evidence"):
        run_router_policy_case(case)  # type: ignore[call-arg]


def test_oracle_helper_is_explicit_and_limited_to_policy_layer() -> None:
    case = _case(
        case_id="oracle_policy_only",
        task_focus="NEW_TASK_CANDIDATE",
        route="SPAWN_SLOW_TASK",
        foreground_policy="ACK_SLOW",
    )

    oracle = oracle_policy_evidence_from_gold(case)
    run = run_router_policy_case(case, predicted_evidence=oracle)

    assert oracle.task_focus_hint == "NEW_TASK_CANDIDATE"
    assert oracle.route_decision_hint == "SPAWN_SLOW_TASK"
    assert run.evaluation.allowed_match is True


def test_router_layer_exposes_metrics_compatible_prediction_without_claiming_side_effects() -> None:
    case = _case(
        case_id="metrics_compatible",
        task_focus="NEW_TASK_CANDIDATE",
        route="SPAWN_SLOW_TASK",
        foreground_policy="ACK_SLOW",
    )

    prediction = run_router_policy_case(
        case,
        predicted_evidence=oracle_policy_evidence_from_gold(case),
    ).evaluation.to_prediction_dict()

    assert prediction == {
        "case_id": "metrics_compatible",
        "task_focus": "NEW_TASK_CANDIDATE",
        "router_decision": "SPAWN_SLOW_TASK",
        "foreground_policy": None,
        "slow_task_created": False,
        "user_patch_emitted": False,
        "external_side_effects": False,
        "answer_candidate_committed": False,
    }


def test_router_events_do_not_contain_gold_structures() -> None:
    case = _case(
        case_id="runner_gold_leakage",
        task_focus="FOREGROUND_CHAT",
        route="FAST_ONLY",
    )

    run = run_router_policy_case(
        case,
        predicted_evidence=PredictedRoutingEvidence(
            task_focus_hint="FOREGROUND_CHAT",
            route_decision_hint="FAST_ONLY",
            task_like=False,
            complexity_hint="simple",
            evidence_uncertainty="low",
            foreground_act="ANSWER",
        ),
    )

    serialized = json.dumps(run.scenario.journal.events(), ensure_ascii=False, sort_keys=True)
    assert "task_focus_allowed" not in serialized
    assert "router_decisions_allowed" not in serialized
    assert "router_decisions_forbidden" not in serialized
    assert "foreground_policy" not in serialized
