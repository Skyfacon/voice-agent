from __future__ import annotations

import math

import pytest

from voice_agent.evals.routing.case import validate_routing_case
from voice_agent.evals.routing.metrics import (
    CRITICAL_ACTIVE_TASK_ANSWER,
    CRITICAL_AMBIGUOUS_PATCH,
    CRITICAL_COMPLEX_ANSWER,
    CRITICAL_EXTERNAL_SIDE_EFFECT,
    CRITICAL_NON_ASSISTANT_TRIGGER,
    CRITICAL_SECOND_ACTIVE_TASK,
    CRITICAL_SIDE_CHAT_MUTATION,
    CRITICAL_TERMINAL_ADVANCE,
    CRITICAL_UNAUTHORIZED_TASK_STATE_CLAIM,
    RoutingPrediction,
    aggregate_metrics,
    evaluate_case,
)


def _case(
    case_id: str,
    *,
    focus: tuple[str, ...],
    allowed_routes: tuple[str, ...],
    forbidden_routes: tuple[str, ...],
    foreground_policy: str,
    criticality: str = "low",
    context: dict[str, object] | None = None,
    slow_task_created: bool = False,
    user_patch_emitted: bool = False,
):
    return validate_routing_case(
        {
            "schema_name": "voice_agent.routing_eval.case.v1",
            "case_id": case_id,
            "scenario_family_id": f"family_{case_id}",
            "split": "prompt_dev",
            "input": {
                "modality": "text",
                "locale": "zh-CN",
                "utterance_text": "这是一个完全合成的评测句子。",
            },
            "context": context or {"template": "NO_ACTIVE_TASK"},
            "gold": {
                "task_focus_allowed": list(focus),
                "router_decisions_allowed": list(allowed_routes),
                "router_decisions_forbidden": list(forbidden_routes),
                "foreground_policy": foreground_policy,
                "side_effect_expectations": {
                    "slow_task_created": slow_task_created,
                    "user_patch_emitted": user_patch_emitted,
                    "external_side_effects": "FORBIDDEN",
                },
            },
            "tags": ["synthetic"],
            "criticality": criticality,
            "annotation_status": "draft",
        }
    )


def _active_context(template: str = "ACTIVE_TASK_PLANNING") -> dict[str, object]:
    phase = "PLANNING"
    task: dict[str, object] = {
        "task_id": "task_synthetic_001",
        "task_type": "planning",
        "summary": "合成任务上下文",
        "lifecycle_phase": phase,
        "plan_version": 2,
    }
    if template == "TERMINAL_TASK":
        task["lifecycle_phase"] = "COMPLETED"
    return {"template": template, "active_task": task}


def test_aggregate_metrics_matches_hand_calculated_three_case_sample() -> None:
    fast = _case(
        "synthetic_fast_001",
        focus=("FOREGROUND_CHAT",),
        allowed_routes=("FAST_ONLY",),
        forbidden_routes=("SPAWN_SLOW_TASK", "PATCH_ACTIVE_SLOW_TASK", "IGNORE"),
        foreground_policy="ANSWER",
    )
    spawn = _case(
        "synthetic_spawn_001",
        focus=("NEW_TASK_CANDIDATE",),
        allowed_routes=("SPAWN_SLOW_TASK",),
        forbidden_routes=("FAST_ONLY", "PATCH_ACTIVE_SLOW_TASK", "IGNORE"),
        foreground_policy="ACK_SLOW",
        criticality="medium",
        slow_task_created=True,
    )
    ignore = _case(
        "synthetic_ignore_001",
        focus=("NON_ASSISTANT",),
        allowed_routes=("IGNORE",),
        forbidden_routes=("FAST_ONLY", "SPAWN_SLOW_TASK", "PATCH_ACTIVE_SLOW_TASK"),
        foreground_policy="SILENCE",
        criticality="high",
        context={"template": "NON_ASSISTANT_BACKGROUND"},
    )

    evaluations = (
        evaluate_case(
            fast,
            RoutingPrediction(
                case_id=fast.case_id,
                task_focus="FOREGROUND_CHAT",
                router_decision="FAST_ONLY",
                foreground_policy="ANSWER",
                answer_candidate_committed=True,
            ),
        ),
        evaluate_case(
            spawn,
            RoutingPrediction(
                case_id=spawn.case_id,
                task_focus="FOREGROUND_CHAT",
                router_decision="FAST_ONLY",
                foreground_policy="ANSWER",
                answer_candidate_committed=True,
            ),
        ),
        evaluate_case(
            ignore,
            RoutingPrediction(
                case_id=ignore.case_id,
                task_focus="NEW_TASK_CANDIDATE",
                router_decision="SPAWN_SLOW_TASK",
                foreground_policy="ACK_SLOW",
                slow_task_created=True,
            ),
        ),
    )

    metrics = aggregate_metrics(evaluations)

    assert metrics["case_count"] == 3
    assert metrics["route_allowed_match_rate"] == pytest.approx(1 / 3)
    assert metrics["task_focus_allowed_match_rate"] == pytest.approx(1 / 3)
    assert metrics["weighted_loss_total"] == 169.0
    assert metrics["weighted_loss_mean"] == pytest.approx(169 / 3)
    route = metrics["route"]
    assert route["confusion_matrix"]["FAST_ONLY"]["FAST_ONLY"] == 1
    assert route["confusion_matrix"]["SPAWN_SLOW_TASK"]["FAST_ONLY"] == 1
    assert route["confusion_matrix"]["IGNORE"]["SPAWN_SLOW_TASK"] == 1
    assert route["per_class"]["FAST_ONLY"]["precision"] == pytest.approx(0.5)
    assert route["per_class"]["FAST_ONLY"]["recall"] == 1.0
    assert route["per_class"]["FAST_ONLY"]["f1"] == pytest.approx(2 / 3)
    assert route["macro_f1"] == pytest.approx(2 / 9)
    assert metrics["critical_violations"] == {
        "count": 2,
        "case_count": 2,
        "by_type": {
            CRITICAL_COMPLEX_ANSWER: 1,
            CRITICAL_NON_ASSISTANT_TRIGGER: 1,
        },
        "case_ids": ["synthetic_ignore_001", "synthetic_spawn_001"],
    }
    assert metrics["slices"]["criticality"]["medium"]["weighted_loss_total"] == 54.0
    assert metrics["slices"]["criticality"]["high"]["weighted_loss_total"] == 115.0


def test_multi_allowed_gold_matches_as_a_set_and_confusion_uses_diagonal() -> None:
    case = _case(
        "synthetic_ambiguous_001",
        focus=("AMBIGUOUS",),
        allowed_routes=("FAST_ONLY", "IGNORE"),
        forbidden_routes=("SPAWN_SLOW_TASK", "PATCH_ACTIVE_SLOW_TASK"),
        foreground_policy="CLARIFY",
    )
    evaluation = evaluate_case(
        case,
        RoutingPrediction(
            case_id=case.case_id,
            task_focus="AMBIGUOUS",
            router_decision="IGNORE",
            foreground_policy="CLARIFY",
        ),
    )

    assert evaluation.route_match is True
    assert evaluation.route_cost == 0.0
    assert evaluation.weighted_loss == 0.0
    metrics = aggregate_metrics((evaluation,))
    assert metrics["route"]["confusion_matrix"]["IGNORE"]["IGNORE"] == 1
    assert metrics["route"]["macro_f1"] == 1.0


def test_router_layer_does_not_score_unobserved_e2e_effects_as_missing() -> None:
    case = _case(
        "synthetic_router_only_001",
        focus=("NEW_TASK_CANDIDATE",),
        allowed_routes=("SPAWN_SLOW_TASK",),
        forbidden_routes=("FAST_ONLY", "PATCH_ACTIVE_SLOW_TASK", "IGNORE"),
        foreground_policy="ACK_SLOW",
        slow_task_created=True,
    )
    evaluation = evaluate_case(
        case,
        RoutingPrediction(
            case_id=case.case_id,
            task_focus="NEW_TASK_CANDIDATE",
            router_decision="SPAWN_SLOW_TASK",
            foreground_policy=None,
        ),
    )

    assert evaluation.route_match is True
    assert evaluation.effect_cost == 0.0
    assert evaluation.weighted_loss == 0.0
    assert evaluation.foreground_policy_match is None
    assert aggregate_metrics((evaluation,))["foreground_policy_match_rate"] is None


def test_cancel_pause_ignore_cost_override_does_not_change_ordinary_patch_cost() -> None:
    ordinary_patch = _case(
        "synthetic_ordinary_patch_ignore_001",
        focus=("ACTIVE_TASK_PATCH",),
        allowed_routes=("PATCH_ACTIVE_SLOW_TASK",),
        forbidden_routes=("FAST_ONLY", "SPAWN_SLOW_TASK", "IGNORE"),
        foreground_policy="ACK_PATCH",
        context=_active_context(),
        user_patch_emitted=True,
    )
    cancel_pause = _case(
        "synthetic_cancel_pause_ignore_001",
        focus=("CANCEL_OR_PAUSE_CANDIDATE",),
        allowed_routes=("PATCH_ACTIVE_SLOW_TASK",),
        forbidden_routes=("FAST_ONLY", "SPAWN_SLOW_TASK", "IGNORE"),
        foreground_policy="CLARIFY",
        context=_active_context(),
        user_patch_emitted=True,
    )

    ordinary_evaluation = evaluate_case(
        ordinary_patch,
        RoutingPrediction(
            case_id=ordinary_patch.case_id,
            task_focus="ACTIVE_TASK_PATCH",
            router_decision="IGNORE",
        ),
    )
    cancel_pause_evaluation = evaluate_case(
        cancel_pause,
        RoutingPrediction(
            case_id=cancel_pause.case_id,
            task_focus="CANCEL_OR_PAUSE_CANDIDATE",
            router_decision="IGNORE",
        ),
    )

    assert ordinary_evaluation.route_cost == 7.0
    assert cancel_pause_evaluation.route_cost == 10.0


def test_unauthorized_paused_or_cancelled_claim_costs_ten_and_is_critical() -> None:
    case = _case(
        "synthetic_false_task_state_claim_001",
        focus=("CANCEL_OR_PAUSE_CANDIDATE",),
        allowed_routes=("PATCH_ACTIVE_SLOW_TASK",),
        forbidden_routes=("FAST_ONLY", "SPAWN_SLOW_TASK", "IGNORE"),
        foreground_policy="ACK_PATCH",
        context=_active_context(),
        user_patch_emitted=True,
    )

    evaluation = evaluate_case(
        case,
        RoutingPrediction(
            case_id=case.case_id,
            task_focus="CANCEL_OR_PAUSE_CANDIDATE",
            router_decision="PATCH_ACTIVE_SLOW_TASK",
            foreground_policy="ACK_PATCH",
            user_patch_emitted=True,
            unauthorized_task_state_claim_committed=True,
        ),
    )

    assert evaluation.route_cost == 0.0
    assert evaluation.effect_cost == 10.0
    assert evaluation.weighted_loss == 10.0
    assert evaluation.critical_violations == (
        CRITICAL_UNAUTHORIZED_TASK_STATE_CLAIM,
    )


def test_critical_violation_taxonomy_covers_task_ownership_and_safety() -> None:
    side_chat = _case(
        "synthetic_side_chat_001",
        focus=("FOREGROUND_CHAT",),
        allowed_routes=("FAST_ONLY",),
        forbidden_routes=("SPAWN_SLOW_TASK", "PATCH_ACTIVE_SLOW_TASK", "IGNORE"),
        foreground_policy="ANSWER",
        criticality="high",
        context=_active_context(),
    )
    ambiguous = _case(
        "synthetic_ambiguous_002",
        focus=("AMBIGUOUS",),
        allowed_routes=("FAST_ONLY",),
        forbidden_routes=("SPAWN_SLOW_TASK", "PATCH_ACTIVE_SLOW_TASK", "IGNORE"),
        foreground_policy="CLARIFY",
        context=_active_context(),
    )
    switch = _case(
        "synthetic_switch_001",
        focus=("NEW_TASK_CANDIDATE",),
        allowed_routes=("PATCH_ACTIVE_SLOW_TASK",),
        forbidden_routes=("FAST_ONLY", "SPAWN_SLOW_TASK", "IGNORE"),
        foreground_policy="ACK_PATCH",
        context=_active_context(),
        user_patch_emitted=True,
    )
    terminal = _case(
        "synthetic_terminal_001",
        focus=("FOREGROUND_CHAT",),
        allowed_routes=("FAST_ONLY",),
        forbidden_routes=("SPAWN_SLOW_TASK", "PATCH_ACTIVE_SLOW_TASK", "IGNORE"),
        foreground_policy="ANSWER",
        context=_active_context("TERMINAL_TASK"),
    )

    evaluations = (
        evaluate_case(
            side_chat,
            RoutingPrediction(
                side_chat.case_id,
                "FOREGROUND_CHAT",
                "PATCH_ACTIVE_SLOW_TASK",
                "ANSWER",
                user_patch_emitted=True,
                answer_candidate_committed=True,
            ),
        ),
        evaluate_case(
            ambiguous,
            RoutingPrediction(
                ambiguous.case_id,
                "AMBIGUOUS",
                "PATCH_ACTIVE_SLOW_TASK",
                "ANSWER",
                user_patch_emitted=True,
                answer_candidate_committed=True,
            ),
        ),
        evaluate_case(
            switch,
            RoutingPrediction(
                switch.case_id,
                "NEW_TASK_CANDIDATE",
                "SPAWN_SLOW_TASK",
                "ACK_SLOW",
                slow_task_created=True,
            ),
        ),
        evaluate_case(
            terminal,
            RoutingPrediction(
                terminal.case_id,
                "FOREGROUND_CHAT",
                "SPAWN_SLOW_TASK",
                "ANSWER",
                slow_task_created=True,
                external_side_effects=True,
                answer_candidate_committed=True,
            ),
        ),
    )

    all_violations = {
        violation for row in evaluations for violation in row.critical_violations
    }
    assert all_violations == {
        CRITICAL_ACTIVE_TASK_ANSWER,
        CRITICAL_AMBIGUOUS_PATCH,
        CRITICAL_EXTERNAL_SIDE_EFFECT,
        CRITICAL_SECOND_ACTIVE_TASK,
        CRITICAL_SIDE_CHAT_MUTATION,
        CRITICAL_TERMINAL_ADVANCE,
    }


def test_prediction_validation_and_aggregate_preconditions() -> None:
    with pytest.raises(ValueError, match="unknown predicted router_decision"):
        RoutingPrediction("synthetic_bad_001", "FOREGROUND_CHAT", "MAYBE")
    with pytest.raises(ValueError, match="at least one"):
        aggregate_metrics(())

    case = _case(
        "synthetic_dup_001",
        focus=("FOREGROUND_CHAT",),
        allowed_routes=("FAST_ONLY",),
        forbidden_routes=("SPAWN_SLOW_TASK", "PATCH_ACTIVE_SLOW_TASK", "IGNORE"),
        foreground_policy="ANSWER",
    )
    row = evaluate_case(
        case,
        RoutingPrediction(
            case.case_id,
            "FOREGROUND_CHAT",
            "FAST_ONLY",
            "ANSWER",
            answer_candidate_committed=True,
        ),
    )
    with pytest.raises(ValueError, match="unique case_id"):
        aggregate_metrics((row, row))
    assert math.isfinite(row.weighted_loss)
