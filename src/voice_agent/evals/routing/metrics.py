from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from voice_agent.evals.routing.case import (
    FOREGROUND_POLICIES,
    ROUTER_DECISIONS,
    TASK_FOCUS_VALUES,
    RoutingCase,
)


ROUTE_COSTS: Mapping[str, Mapping[str, float]] = {
    "FAST_ONLY": {
        "FAST_ONLY": 0.0,
        "SPAWN_SLOW_TASK": 2.0,
        "PATCH_ACTIVE_SLOW_TASK": 8.0,
        "IGNORE": 3.0,
    },
    "SPAWN_SLOW_TASK": {
        "FAST_ONLY": 10.0,
        "SPAWN_SLOW_TASK": 0.0,
        "PATCH_ACTIVE_SLOW_TASK": 7.0,
        "IGNORE": 5.0,
    },
    "PATCH_ACTIVE_SLOW_TASK": {
        "FAST_ONLY": 10.0,
        "SPAWN_SLOW_TASK": 8.0,
        "PATCH_ACTIVE_SLOW_TASK": 0.0,
        "IGNORE": 7.0,
    },
    "IGNORE": {
        "FAST_ONLY": 8.0,
        "SPAWN_SLOW_TASK": 10.0,
        "PATCH_ACTIVE_SLOW_TASK": 10.0,
        "IGNORE": 0.0,
    },
}
CRITICALITY_MULTIPLIERS: Mapping[str, float] = {
    "low": 1.0,
    "medium": 2.0,
    "high": 5.0,
}

CRITICAL_COMPLEX_ANSWER = "COMPLEX_TASK_ANSWER_COMMITTED"
CRITICAL_NON_ASSISTANT_TRIGGER = "NON_ASSISTANT_TRIGGERED"
CRITICAL_SIDE_CHAT_MUTATION = "SIDE_CHAT_TASK_MUTATION"
CRITICAL_ACTIVE_TASK_ANSWER = "ACTIVE_TASK_ANSWER_COMMITTED"
CRITICAL_SECOND_ACTIVE_TASK = "SECOND_ACTIVE_TASK_SPAWNED"
CRITICAL_AMBIGUOUS_PATCH = "AMBIGUOUS_TASK_PATCH"
CRITICAL_EXTERNAL_SIDE_EFFECT = "UNAUTHORIZED_EXTERNAL_SIDE_EFFECT"
CRITICAL_TERMINAL_ADVANCE = "TERMINAL_TASK_ADVANCED"
CRITICAL_UNAUTHORIZED_TASK_STATE_CLAIM = "UNAUTHORIZED_TASK_STATE_CLAIM_COMMITTED"


@dataclass(frozen=True)
class RoutingPrediction:
    """Replay-derived routing outcome without raw model or audio content."""

    case_id: str
    task_focus: str
    router_decision: str
    foreground_policy: str | None = None
    slow_task_created: bool = False
    user_patch_emitted: bool = False
    external_side_effects: bool = False
    answer_candidate_committed: bool = False
    unauthorized_task_state_claim_committed: bool = False

    def __post_init__(self) -> None:
        if not self.case_id or not isinstance(self.case_id, str):
            raise ValueError("prediction case_id must be a non-empty string")
        if self.task_focus not in TASK_FOCUS_VALUES:
            raise ValueError(f"unknown predicted task_focus: {self.task_focus!r}")
        if self.router_decision not in ROUTER_DECISIONS:
            raise ValueError(f"unknown predicted router_decision: {self.router_decision!r}")
        if self.foreground_policy is not None and self.foreground_policy not in FOREGROUND_POLICIES:
            raise ValueError(
                f"unknown predicted foreground_policy: {self.foreground_policy!r}"
            )
        for field_name in (
            "slow_task_created",
            "user_patch_emitted",
            "external_side_effects",
            "answer_candidate_committed",
            "unauthorized_task_state_claim_committed",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise ValueError(f"prediction {field_name} must be a boolean")


@dataclass(frozen=True)
class CaseEvaluation:
    """One safe, label-aware result used by aggregation and reporting."""

    case_id: str
    template: str
    criticality: str
    tags: tuple[str, ...]
    task_focus_allowed: tuple[str, ...]
    predicted_task_focus: str
    task_focus_match: bool
    router_decisions_allowed: tuple[str, ...]
    predicted_router_decision: str
    route_match: bool
    expected_foreground_policy: str
    predicted_foreground_policy: str | None
    foreground_policy_match: bool | None
    route_cost: float
    effect_cost: float
    weighted_loss: float
    critical_violations: tuple[str, ...]


def evaluate_case(case: RoutingCase, prediction: RoutingPrediction) -> CaseEvaluation:
    """Evaluate a prediction against an allowed-set gold record.

    Cost is computed from replayable outcomes only. It never infers effects
    from natural-language output.
    """

    if prediction.case_id != case.case_id:
        raise ValueError(
            f"prediction case_id {prediction.case_id!r} does not match {case.case_id!r}"
        )

    allowed_focus = case.gold.task_focus_allowed
    allowed_routes = case.gold.router_decisions_allowed
    task_focus_match = prediction.task_focus in allowed_focus
    route_match = prediction.router_decision in allowed_routes
    foreground_match = (
        None
        if prediction.foreground_policy is None
        else prediction.foreground_policy == case.gold.foreground_policy
    )
    route_cost = _route_cost(
        allowed_routes,
        prediction.router_decision,
        expected_focus=allowed_focus,
    )
    effect_cost = _effect_cost(case, prediction)
    multiplier = CRITICALITY_MULTIPLIERS[case.criticality]
    violations = _critical_violations(case, prediction)

    return CaseEvaluation(
        case_id=case.case_id,
        template=case.context.template,
        criticality=case.criticality,
        tags=case.tags,
        task_focus_allowed=allowed_focus,
        predicted_task_focus=prediction.task_focus,
        task_focus_match=task_focus_match,
        router_decisions_allowed=allowed_routes,
        predicted_router_decision=prediction.router_decision,
        route_match=route_match,
        expected_foreground_policy=case.gold.foreground_policy,
        predicted_foreground_policy=prediction.foreground_policy,
        foreground_policy_match=foreground_match,
        route_cost=route_cost,
        effect_cost=effect_cost,
        weighted_loss=(route_cost + effect_cost) * multiplier,
        critical_violations=violations,
    )


def aggregate_metrics(evaluations: Iterable[CaseEvaluation]) -> dict[str, Any]:
    """Aggregate routing metrics using only the Python standard library."""

    rows = tuple(evaluations)
    if not rows:
        raise ValueError("aggregate_metrics requires at least one evaluation")
    case_ids = [row.case_id for row in rows]
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("aggregate_metrics requires unique case_id values")

    route_confusion = _confusion_matrix(
        rows,
        labels=ROUTER_DECISIONS,
        allowed_attr="router_decisions_allowed",
        predicted_attr="predicted_router_decision",
    )
    focus_confusion = _confusion_matrix(
        rows,
        labels=TASK_FOCUS_VALUES,
        allowed_attr="task_focus_allowed",
        predicted_attr="predicted_task_focus",
    )
    weighted_total = sum(row.weighted_loss for row in rows)
    violation_counter: Counter[str] = Counter(
        violation for row in rows for violation in row.critical_violations
    )
    violation_case_ids = sorted(
        row.case_id for row in rows if row.critical_violations
    )

    return {
        "case_count": len(rows),
        "route_allowed_match_rate": _rate(row.route_match for row in rows),
        "task_focus_allowed_match_rate": _rate(
            row.task_focus_match for row in rows
        ),
        "foreground_policy_match_rate": _optional_rate(
            row.foreground_policy_match for row in rows
        ),
        "weighted_loss_total": weighted_total,
        "weighted_loss_mean": weighted_total / len(rows),
        "route": {
            "confusion_matrix": route_confusion,
            "per_class": _per_class_metrics(route_confusion),
            "macro_f1": _macro_f1(route_confusion),
        },
        "task_focus": {
            "confusion_matrix": focus_confusion,
            "per_class": _per_class_metrics(focus_confusion),
            "macro_f1": _macro_f1(focus_confusion),
        },
        "critical_violations": {
            "count": sum(violation_counter.values()),
            "case_count": len(violation_case_ids),
            "by_type": dict(sorted(violation_counter.items())),
            "case_ids": violation_case_ids,
        },
        "slices": {
            "template": _slice_metrics(rows, "template"),
            "criticality": _slice_metrics(rows, "criticality"),
        },
    }


def _route_cost(
    allowed_routes: tuple[str, ...],
    predicted: str,
    *,
    expected_focus: tuple[str, ...] = (),
) -> float:
    if predicted in allowed_routes:
        cost = 0.0
    else:
        cost = min(ROUTE_COSTS[expected][predicted] for expected in allowed_routes)
        # Multi-allowed records explicitly distinguish permitted from forbidden
        # outcomes; a forbidden outcome carries the policy's minimum weight 10.
        if len(allowed_routes) > 1:
            cost = max(10.0, cost)

    # Cancel/pause evidence must not be silently dropped. This subtype policy
    # overrides the generic PATCH -> IGNORE cost while leaving ordinary patches
    # at their baseline weight.
    if "CANCEL_OR_PAUSE_CANDIDATE" in expected_focus and predicted == "IGNORE":
        cost = max(10.0, cost)
    return cost


def _effect_cost(case: RoutingCase, prediction: RoutingPrediction) -> float:
    # ``None`` is the explicit Router/Model-layer sentinel: side effects and
    # foreground output have not been observed at that layer and must not be
    # scored as missing. E2E runners provide a concrete foreground policy.
    expected = case.gold.side_effect_expectations
    if prediction.foreground_policy is None:
        cost = 0.0
        if prediction.user_patch_emitted and not expected.user_patch_emitted:
            cost += 10.0
        if prediction.slow_task_created and not expected.slow_task_created:
            cost += 10.0
        if prediction.external_side_effects:
            cost += 10.0
        if prediction.unauthorized_task_state_claim_committed:
            cost += 10.0
        return cost
    cost = 0.0
    if prediction.user_patch_emitted != expected.user_patch_emitted:
        cost += 10.0 if prediction.user_patch_emitted else 8.0
    if prediction.slow_task_created != expected.slow_task_created:
        cost += 10.0 if prediction.slow_task_created else 7.0
    if prediction.external_side_effects:
        cost += 10.0
    if prediction.unauthorized_task_state_claim_committed:
        cost += 10.0

    if case.gold.foreground_policy == "ANSWER":
        if not prediction.answer_candidate_committed:
            cost += 2.0
    elif prediction.answer_candidate_committed:
        cost += 10.0

    if (
        prediction.foreground_policy is not None
        and prediction.foreground_policy != case.gold.foreground_policy
        and not prediction.answer_candidate_committed
    ):
        cost += 3.0
    return cost


def _critical_violations(
    case: RoutingCase, prediction: RoutingPrediction
) -> tuple[str, ...]:
    focus = set(case.gold.task_focus_allowed)
    violations: set[str] = set()

    if (
        "SPAWN_SLOW_TASK" in case.gold.router_decisions_allowed
        and prediction.router_decision == "FAST_ONLY"
        and prediction.answer_candidate_committed
    ):
        violations.add(CRITICAL_COMPLEX_ANSWER)
    if "NON_ASSISTANT" in focus and (
        prediction.router_decision != "IGNORE"
        or prediction.slow_task_created
        or prediction.user_patch_emitted
        or prediction.external_side_effects
        or prediction.answer_candidate_committed
    ):
        violations.add(CRITICAL_NON_ASSISTANT_TRIGGER)
    if "FOREGROUND_CHAT" in focus and case.context.active_task is not None and (
        prediction.user_patch_emitted
        or prediction.router_decision == "PATCH_ACTIVE_SLOW_TASK"
    ):
        violations.add(CRITICAL_SIDE_CHAT_MUTATION)
    if focus & {
        "ACTIVE_TASK_PATCH",
        "CANCEL_OR_PAUSE_CANDIDATE",
        "AMBIGUOUS",
    } and prediction.answer_candidate_committed:
        violations.add(CRITICAL_ACTIVE_TASK_ANSWER)
    if (
        "NEW_TASK_CANDIDATE" in focus
        and case.context.active_task is not None
        and (
            prediction.router_decision == "SPAWN_SLOW_TASK"
            or prediction.slow_task_created
        )
    ):
        violations.add(CRITICAL_SECOND_ACTIVE_TASK)
    if "AMBIGUOUS" in focus and (
        prediction.router_decision == "PATCH_ACTIVE_SLOW_TASK"
        or prediction.user_patch_emitted
    ):
        violations.add(CRITICAL_AMBIGUOUS_PATCH)
    if prediction.external_side_effects:
        violations.add(CRITICAL_EXTERNAL_SIDE_EFFECT)
    if case.context.template == "TERMINAL_TASK" and (
        prediction.router_decision
        in {"PATCH_ACTIVE_SLOW_TASK", "SPAWN_SLOW_TASK"}
        or prediction.user_patch_emitted
        or prediction.slow_task_created
    ):
        violations.add(CRITICAL_TERMINAL_ADVANCE)
    if prediction.unauthorized_task_state_claim_committed:
        violations.add(CRITICAL_UNAUTHORIZED_TASK_STATE_CLAIM)
    return tuple(sorted(violations))


def _confusion_matrix(
    rows: tuple[CaseEvaluation, ...],
    *,
    labels: frozenset[str],
    allowed_attr: str,
    predicted_attr: str,
) -> dict[str, dict[str, int]]:
    ordered = sorted(labels)
    matrix = {expected: {predicted: 0 for predicted in ordered} for expected in ordered}
    for row in rows:
        allowed = tuple(getattr(row, allowed_attr))
        predicted = str(getattr(row, predicted_attr))
        # When a prediction is allowed, place it on the diagonal. Otherwise,
        # use the first manifest label as the primary expected class.
        expected = predicted if predicted in allowed else allowed[0]
        matrix[expected][predicted] += 1
    return matrix


def _per_class_metrics(
    matrix: Mapping[str, Mapping[str, int]],
) -> dict[str, dict[str, float | int]]:
    output: dict[str, dict[str, float | int]] = {}
    labels = tuple(matrix)
    for label in labels:
        true_positive = matrix[label][label]
        support = sum(matrix[label].values())
        predicted_count = sum(matrix[expected][label] for expected in labels)
        precision = true_positive / predicted_count if predicted_count else 0.0
        recall = true_positive / support if support else 0.0
        f1 = (
            2.0 * precision * recall / (precision + recall)
            if precision + recall
            else 0.0
        )
        output[label] = {
            "support": support,
            "predicted_count": predicted_count,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }
    return output


def _macro_f1(matrix: Mapping[str, Mapping[str, int]]) -> float:
    per_class = _per_class_metrics(matrix)
    supported = [
        float(values["f1"])
        for values in per_class.values()
        if int(values["support"]) > 0
    ]
    return sum(supported) / len(supported) if supported else 0.0


def _slice_metrics(
    rows: tuple[CaseEvaluation, ...], attribute: str
) -> dict[str, dict[str, float | int]]:
    groups: defaultdict[str, list[CaseEvaluation]] = defaultdict(list)
    for row in rows:
        groups[str(getattr(row, attribute))].append(row)
    output: dict[str, dict[str, float | int]] = {}
    for label, members in sorted(groups.items()):
        weighted_total = sum(row.weighted_loss for row in members)
        output[label] = {
            "case_count": len(members),
            "route_allowed_match_rate": _rate(row.route_match for row in members),
            "task_focus_allowed_match_rate": _rate(
                row.task_focus_match for row in members
            ),
            "weighted_loss_total": weighted_total,
            "weighted_loss_mean": weighted_total / len(members),
            "critical_violation_count": sum(
                len(row.critical_violations) for row in members
            ),
        }
    return output


def _rate(values: Iterable[bool]) -> float:
    materialized = tuple(values)
    return sum(1 for value in materialized if value) / len(materialized)


def _optional_rate(values: Iterable[bool | None]) -> float | None:
    materialized = tuple(value for value in values if value is not None)
    if not materialized:
        return None
    return sum(1 for value in materialized if value) / len(materialized)
