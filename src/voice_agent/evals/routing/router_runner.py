from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from voice_agent.evals.routing.case import RoutingCase, validate_routing_case
from voice_agent.evals.routing.event_factory import (
    PredictedRoutingEvidence,
    ScenarioEventBundle,
    ScenarioEventFactory,
)
from voice_agent.router.router import MVP1Router


@dataclass(frozen=True)
class RouterPolicyEvaluation:
    """Stable policy-layer prediction plus evaluator-only match metadata."""

    case_id: str
    task_focus: str
    router_decision: str
    foreground_policy: str | None
    slow_task_created: bool
    user_patch_emitted: bool
    external_side_effects: bool
    answer_candidate_committed: bool
    router_decision_event_id: str
    task_focus_state_event_id: str
    fast_interaction_event_id: str
    candidate_event_id: str | None
    task_focus_allowed_match: bool
    router_decision_allowed_match: bool
    allowed_match: bool
    event_ids: tuple[str, ...]

    @property
    def actual_task_focus(self) -> str:
        return self.task_focus

    @property
    def actual_router_decision(self) -> str:
        return self.router_decision

    def to_prediction_dict(self) -> dict[str, Any]:
        """Return fields compatible with the routing metrics prediction contract."""

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
class RouterPolicyRun:
    scenario: ScenarioEventBundle
    evaluation: RouterPolicyEvaluation


def run_router_policy_case(
    case: RoutingCase | Mapping[str, Any],
    *,
    predicted_evidence: PredictedRoutingEvidence,
    event_factory: ScenarioEventFactory | None = None,
) -> RouterPolicyRun:
    """Run Router policy using only explicitly injected predicted evidence.

    Gold labels are consulted only after Router events have been emitted, and
    only to calculate allowed-set matches.  This function intentionally has no
    implicit or default prediction path.
    """

    normalized = case if isinstance(case, RoutingCase) else validate_routing_case(case)
    factory = event_factory or ScenarioEventFactory()
    scenario = factory.build(normalized, predicted_evidence=predicted_evidence)
    result = MVP1Router(scenario.journal).emit_decision(
        turn_committed_event=scenario.turn_committed_event,
        asr_frame_event=scenario.asr_event,
        fast_interaction_output_event=scenario.fast_interaction_event,
        router_context=scenario.router_context,
        event_id=f"evt_routing_eval_{normalized.case_id}_router_decision",
        task_focus_state_event_id=f"evt_routing_eval_{normalized.case_id}_task_focus_state",
        created_monotonic_ms=ScenarioEventFactory.BASE_MONOTONIC_MS + 30,
        created_wall_clock_ms=ScenarioEventFactory.BASE_WALL_CLOCK_MS + 30,
    )
    router_event = result.router_decision_event
    actual_focus = str(router_event["task_focus"])
    actual_route = str(router_event["router_decision"])
    focus_match = actual_focus in normalized.gold.task_focus_allowed
    route_match = actual_route in normalized.gold.router_decisions_allowed
    events = scenario.journal.events()
    evaluation = RouterPolicyEvaluation(
        case_id=normalized.case_id,
        task_focus=actual_focus,
        router_decision=actual_route,
        foreground_policy=None,
        slow_task_created=False,
        user_patch_emitted=False,
        external_side_effects=False,
        answer_candidate_committed=False,
        router_decision_event_id=str(router_event["event_id"]),
        task_focus_state_event_id=str(result.task_focus_state_event["event_id"]),
        fast_interaction_event_id=str(scenario.fast_interaction_event["event_id"]),
        candidate_event_id=(
            str(scenario.candidate_event["event_id"])
            if scenario.candidate_event is not None
            else None
        ),
        task_focus_allowed_match=focus_match,
        router_decision_allowed_match=route_match,
        allowed_match=focus_match and route_match,
        event_ids=tuple(str(event["event_id"]) for event in events),
    )
    return RouterPolicyRun(scenario=scenario, evaluation=evaluation)


def oracle_policy_evidence_from_gold(case: RoutingCase) -> PredictedRoutingEvidence:
    """Build label-derived evidence for deterministic Router policy tests only.

    The explicit ``oracle`` and ``from_gold`` naming is intentional: model
    capability evaluation must inject actual adapter predictions instead.
    Ambiguous multi-label cases select the manifest's first allowed value, whose
    order is part of the reviewed fixture.
    """

    focus = case.gold.task_focus_allowed[0]
    route = case.gold.router_decisions_allowed[0]
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
        directedness="NOT_DIRECTED" if focus == "NON_ASSISTANT" else "ASSUMED_DIRECTED",
        foreground_act=case.gold.foreground_policy,
        risk_class="LOW",
        confidence=0.99,
        emit_candidate=True,
    )
