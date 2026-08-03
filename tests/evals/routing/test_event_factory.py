from __future__ import annotations

import json

import pytest

from voice_agent.evals.routing.case import ROUTING_CASE_SCHEMA_NAME, validate_routing_case
from voice_agent.evals.routing.event_factory import (
    PredictedRoutingEvidence,
    ScenarioEventFactory,
    ScenarioEventFactoryError,
)
from voice_agent.events.registry import EVENT_DEFINITIONS


def _active_task(
    *,
    lifecycle_phase: str = "PLANNING",
    pending_confirmation_scope: str | None = None,
) -> dict[str, object]:
    task: dict[str, object] = {
        "task_id": "task_trip_001",
        "task_type": "trip_planning",
        "summary": "规划上海三日游，当前预算一千元。",
        "lifecycle_phase": lifecycle_phase,
        "plan_version": 2,
    }
    if pending_confirmation_scope is not None:
        task["pending_confirmation_scope"] = pending_confirmation_scope
    return task


def _case(
    *,
    case_id: str = "routing_factory_001",
    modality: str = "text",
    context: dict[str, object] | None = None,
    tags: list[str] | None = None,
) -> object:
    input_payload: dict[str, object] = {"modality": modality, "locale": "zh-CN"}
    if modality == "text":
        input_payload["utterance_text"] = "请简单解释一下什么是回声。"
    else:
        input_payload["audio_ref"] = f"audio-eval://synthetic/{case_id}"
    return validate_routing_case(
        {
            "schema_name": ROUTING_CASE_SCHEMA_NAME,
            "case_id": case_id,
            "scenario_family_id": "routing_factory_family",
            "split": "prompt_dev",
            "input": input_payload,
            "context": context or {"template": "NO_ACTIVE_TASK"},
            "gold": {
                "task_focus_allowed": ["FOREGROUND_CHAT"],
                "router_decisions_allowed": ["FAST_ONLY"],
                "router_decisions_forbidden": [
                    "SPAWN_SLOW_TASK",
                    "PATCH_ACTIVE_SLOW_TASK",
                    "IGNORE",
                ],
                "foreground_policy": "ANSWER",
                "side_effect_expectations": {
                    "slow_task_created": False,
                    "user_patch_emitted": False,
                    "external_side_effects": "FORBIDDEN",
                },
            },
            "tags": tags or ["factory_test"],
            "criticality": "low",
            "annotation_status": "draft",
        }
    )


def _evidence(**overrides: object) -> PredictedRoutingEvidence:
    values: dict[str, object] = {
        "task_focus_hint": "FOREGROUND_CHAT",
        "route_decision_hint": "FAST_ONLY",
        "task_like": False,
        "complexity_hint": "simple",
        "evidence_uncertainty": "low",
        "foreground_act": "ANSWER",
        "confidence": 0.91,
    }
    values.update(overrides)
    return PredictedRoutingEvidence(**values)  # type: ignore[arg-type]


def test_factory_builds_deterministic_provider_free_canonical_events() -> None:
    case = _case()
    factory = ScenarioEventFactory()

    first = factory.build(case, predicted_evidence=_evidence())
    second = factory.build(case, predicted_evidence=_evidence())

    assert first.journal.events() == second.journal.events()
    event_names = tuple(event["event_name"] for event in first.journal.events())
    assert event_names == (
        "SESSION_STARTED",
        "ADAPTER_CAPABILITY_SNAPSHOT_RECORDED",
        "TURN_OPENED",
        "TURN_INGRESS_ACCEPTED",
        "TURN_INGRESS_COMMITTED",
        "FAST_INTERACTION_OUTPUT_EMITTED",
        "FOREGROUND_REPLY_CANDIDATE_EMITTED",
    )
    assert set(event_names) <= set(EVENT_DEFINITIONS)
    assert first.fast_interaction_event["output_mode"] == "mock"
    assert first.turn_committed_event["input_modality"] == "audio"
    assert first.fast_interaction_event["input_mode"] == "audio_native"


def test_audio_case_uses_audio_native_fast_interaction_without_asr() -> None:
    scenario = ScenarioEventFactory().build(
        _case(case_id="routing_audio_001", modality="audio"),
        predicted_evidence=_evidence(),
    )

    assert scenario.asr_event is None
    assert scenario.turn_committed_event["input_modality"] == "audio"
    assert scenario.fast_interaction_event["input_mode"] == "audio_native"
    assert scenario.fast_interaction_event["caused_by_event_id"] == scenario.turn_committed_event[
        "event_id"
    ]


@pytest.mark.parametrize(
    ("template", "active_task", "expected_active"),
    (
        ("NO_ACTIVE_TASK", None, False),
        ("ACTIVE_TASK_PLANNING", _active_task(), True),
        ("ACTIVE_TASK_WAITING_TOOL", _active_task(lifecycle_phase="EXECUTING"), True),
        (
            "ACTIVE_TASK_WAITING_CONFIRMATION",
            _active_task(
                lifecycle_phase="WAITING_FOR_USER_CONFIRMATION",
                pending_confirmation_scope="TASK_CANCEL",
            ),
            True,
        ),
        ("ACTIVE_TASK_WAITING_SLOT", _active_task(lifecycle_phase="WAITING_FOR_SLOT"), True),
        ("ACTIVE_TASK_FINALIZING", _active_task(lifecycle_phase="EXECUTING"), True),
        ("TERMINAL_TASK", _active_task(lifecycle_phase="COMPLETED"), False),
        ("NON_ASSISTANT_BACKGROUND", None, False),
    ),
)
def test_factory_maps_all_eight_context_templates_to_task_focus_snapshot(
    template: str,
    active_task: dict[str, object] | None,
    expected_active: bool,
) -> None:
    context: dict[str, object] = {"template": template}
    if active_task is not None:
        context["active_task"] = active_task
    case = _case(case_id=f"ctx_{template.lower()}", context=context)

    scenario = ScenarioEventFactory().build(case, predicted_evidence=_evidence())

    assert scenario.router_context.task_focus_snapshot.has_active_non_terminal_task is expected_active
    if template == "ACTIVE_TASK_WAITING_CONFIRMATION":
        assert (
            scenario.router_context.task_focus_snapshot.pending_confirmation_scope
            == "TASK_CANCEL"
        )
    if template == "TERMINAL_TASK":
        assert scenario.router_context.task_focus_snapshot.terminal_status == "COMPLETED"


def test_factory_never_writes_gold_or_evaluator_metadata_into_model_input_or_journal() -> None:
    case = _case(tags=["gold_leakage_canary"])

    scenario = ScenarioEventFactory().build(case, predicted_evidence=_evidence())

    model_serialized = json.dumps(scenario.model_input, ensure_ascii=False, sort_keys=True)
    journal_serialized = json.dumps(scenario.journal.events(), ensure_ascii=False, sort_keys=True)
    for forbidden in (
        "gold",
        "gold_leakage_canary",
        "task_focus_allowed",
        "router_decisions_allowed",
        "router_decisions_forbidden",
        "foreground_policy",
        "annotation_status",
        "criticality",
    ):
        assert forbidden not in model_serialized
        assert forbidden not in journal_serialized


def test_factory_does_not_write_synthetic_utterance_text_to_journal() -> None:
    case = _case()

    scenario = ScenarioEventFactory().build(case, predicted_evidence=_evidence())

    journal_serialized = json.dumps(scenario.journal.events(), ensure_ascii=False)
    assert case.input.utterance_text not in journal_serialized
    assert case.input.utterance_text == scenario.model_input["input"]["utterance_text"]


@pytest.mark.parametrize(
    "overrides",
    (
        {"task_focus_hint": "NOT_A_FOCUS"},
        {"route_decision_hint": "RUN_TOOL"},
        {"confidence": 1.1},
        {"directedness": "MAYBE_DIRECTED"},
    ),
)
def test_predicted_evidence_is_strictly_validated(overrides: dict[str, object]) -> None:
    with pytest.raises(ScenarioEventFactoryError):
        _evidence(**overrides)
