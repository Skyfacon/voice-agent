from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from voice_agent.evals.routing.case import (
    ROUTER_DECISIONS,
    ROUTING_CASE_SCHEMA_NAME,
    RoutingCaseValidationError,
    routing_case_to_model_input,
    validate_routing_case,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = REPO_ROOT / "evals" / "routing" / "schema" / "routing_case.schema.json"


def _case(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_name": ROUTING_CASE_SCHEMA_NAME,
        "case_id": "routing_fast_001",
        "scenario_family_id": "simple_explanation_001",
        "split": "prompt_dev",
        "input": {
            "modality": "text",
            "locale": "zh-CN",
            "utterance_text": "请简单解释一下什么是回声。",
        },
        "context": {"template": "NO_ACTIVE_TASK"},
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
        "tags": ["foreground_chat", "simple_explanation"],
        "criticality": "low",
        "annotation_status": "draft",
    }
    value.update(overrides)
    return value


def _active_task() -> dict[str, object]:
    return {
        "task_id": "task_trip_001",
        "task_type": "trip_planning",
        "summary": "规划上海三日游，预算一千元。",
        "lifecycle_phase": "PLANNING",
        "plan_version": 2,
    }


def test_schema_document_is_valid_json_and_declares_strict_v1_contract() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert schema["title"] == ROUTING_CASE_SCHEMA_NAME
    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema_name"]["const"] == ROUTING_CASE_SCHEMA_NAME
    assert schema["$defs"]["gold"]["additionalProperties"] is False


def test_validate_text_case_returns_immutable_typed_record() -> None:
    case = validate_routing_case(_case())

    assert case.case_id == "routing_fast_001"
    assert case.input.utterance_text == "请简单解释一下什么是回声。"
    assert case.input.audio_ref is None
    assert case.gold.router_decisions_allowed == ("FAST_ONLY",)
    assert case.gold.side_effect_expectations.external_side_effects == "FORBIDDEN"


def test_validate_safe_audio_case() -> None:
    raw = _case(
        input={
            "modality": "audio",
            "locale": "zh-CN",
            "audio_ref": "audio-eval://synthetic/routing-fast-001-v1",
        }
    )

    case = validate_routing_case(raw)

    assert case.input.audio_ref == "audio-eval://synthetic/routing-fast-001-v1"
    assert case.input.utterance_text is None


def test_model_input_physically_excludes_all_evaluator_fields_and_is_a_copy() -> None:
    case = validate_routing_case(_case())

    model_input = routing_case_to_model_input(case)

    assert set(model_input) == {"input", "context"}
    serialized = json.dumps(model_input, ensure_ascii=False)
    for forbidden in (
        "gold",
        "task_focus",
        "router_decisions",
        "criticality",
        "annotation_status",
        "scenario_family_id",
        "foreground_chat",
    ):
        assert forbidden not in serialized
    model_input["input"]["locale"] = "en-US"
    assert case.input.locale == "zh-CN"


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("split", "train"),
        ("criticality", "urgent"),
        ("annotation_status", "approved"),
    ),
)
def test_rejects_unknown_top_level_enum_values(field: str, value: str) -> None:
    with pytest.raises(RoutingCaseValidationError, match=field):
        validate_routing_case(_case(**{field: value}))


def test_rejects_unexpected_fields_at_every_boundary() -> None:
    raw = _case()
    raw["gold"] = {**raw["gold"], "model_hint": "FAST_ONLY"}  # type: ignore[arg-type]

    with pytest.raises(RoutingCaseValidationError, match="unexpected fields"):
        validate_routing_case(raw)


@pytest.mark.parametrize(
    "audio_ref",
    (
        "/tmp/private.wav",
        "audio-eval://local/private.wav",
        "audio-eval://local/../private",
        "file:///tmp/private.wav",
        "https://provider.example/audio/1",
        "provider://response/audio",
    ),
)
def test_rejects_raw_audio_paths_and_unsafe_audio_refs(audio_ref: str) -> None:
    raw = _case(
        input={"modality": "audio", "locale": "zh-CN", "audio_ref": audio_ref}
    )

    with pytest.raises(RoutingCaseValidationError, match="audio_ref"):
        validate_routing_case(raw)


@pytest.mark.parametrize(
    ("unsafe_field", "unsafe_value"),
    (
        ("provider_body", {"result": "FAST_ONLY"}),
        ("raw_audio", "base64data"),
        ("authorization", "Bearer example"),
        ("api_key", "not-even-a-real-key"),
    ),
)
def test_rejects_raw_provider_secret_or_audio_fields(
    unsafe_field: str, unsafe_value: object
) -> None:
    raw = _case()
    raw[unsafe_field] = unsafe_value

    with pytest.raises(RoutingCaseValidationError, match="unsafe"):
        validate_routing_case(raw)


def test_rejects_likely_secret_value_even_in_an_allowed_text_field() -> None:
    raw = _case(
        input={
            "modality": "text",
            "locale": "zh-CN",
            "utterance_text": "api_key=abcdefghijklmnop",
        }
    )

    with pytest.raises(RoutingCaseValidationError, match="credential"):
        validate_routing_case(raw)


def test_requires_audio_text_xor_by_modality() -> None:
    raw = _case(
        input={
            "modality": "audio",
            "locale": "zh-CN",
            "utterance_text": "不应内嵌转写。",
            "audio_ref": "audio-eval://synthetic/ref-001",
        }
    )

    with pytest.raises(RoutingCaseValidationError, match="must not include utterance_text"):
        validate_routing_case(raw)


def test_active_task_template_requires_typed_active_task() -> None:
    raw = _case(
        context={"template": "ACTIVE_TASK_PLANNING", "active_task": _active_task()},
        gold={
            "task_focus_allowed": ["ACTIVE_TASK_PATCH"],
            "router_decisions_allowed": ["PATCH_ACTIVE_SLOW_TASK"],
            "router_decisions_forbidden": ["FAST_ONLY", "SPAWN_SLOW_TASK", "IGNORE"],
            "foreground_policy": "ACK_PATCH",
            "side_effect_expectations": {
                "slow_task_created": False,
                "user_patch_emitted": True,
                "external_side_effects": "FORBIDDEN",
            },
        },
    )

    case = validate_routing_case(raw)

    assert case.context.active_task is not None
    assert case.context.active_task.plan_version == 2
    assert case.gold.side_effect_expectations.user_patch_emitted is True


def test_active_task_patch_focus_is_invalid_without_active_task() -> None:
    raw = _case()
    raw["gold"] = {
        "task_focus_allowed": ["ACTIVE_TASK_PATCH"],
        "router_decisions_allowed": ["PATCH_ACTIVE_SLOW_TASK"],
        "router_decisions_forbidden": ["FAST_ONLY", "SPAWN_SLOW_TASK", "IGNORE"],
        "foreground_policy": "ACK_PATCH",
        "side_effect_expectations": {
            "slow_task_created": False,
            "user_patch_emitted": True,
            "external_side_effects": "FORBIDDEN",
        },
    }

    with pytest.raises(RoutingCaseValidationError, match="requires an active task"):
        validate_routing_case(raw)


def test_waiting_confirmation_requires_scope_and_matching_lifecycle() -> None:
    active_task = _active_task()
    active_task["lifecycle_phase"] = "WAITING_FOR_USER_CONFIRMATION"
    raw = _case(
        context={
            "template": "ACTIVE_TASK_WAITING_CONFIRMATION",
            "active_task": active_task,
        }
    )

    with pytest.raises(RoutingCaseValidationError, match="pending_confirmation_scope"):
        validate_routing_case(raw)


@pytest.mark.parametrize(
    "scope",
    (
        "DEMO_DESTRUCTIVE_ACTION",
        "TASK_CANCEL",
        "SWITCH_TASK",
        "RISK_ACKNOWLEDGEMENT",
        "FINAL_ARGUMENT_CONFIRMATION",
    ),
)
def test_waiting_confirmation_accepts_only_adr016_scopes(scope: str) -> None:
    active_task = _active_task()
    active_task.update(
        lifecycle_phase="WAITING_FOR_USER_CONFIRMATION",
        pending_confirmation_scope=scope,
    )
    raw = _case(
        context={
            "template": "ACTIVE_TASK_WAITING_CONFIRMATION",
            "active_task": active_task,
        }
    )

    case = validate_routing_case(raw)

    assert case.context.active_task is not None
    assert case.context.active_task.pending_confirmation_scope == scope


@pytest.mark.parametrize("scope", ("PLAN_APPROVAL", "DEMO_ACTION"))
def test_waiting_confirmation_rejects_non_adr016_scopes(scope: str) -> None:
    active_task = _active_task()
    active_task.update(
        lifecycle_phase="WAITING_FOR_USER_CONFIRMATION",
        pending_confirmation_scope=scope,
    )
    raw = _case(
        context={
            "template": "ACTIVE_TASK_WAITING_CONFIRMATION",
            "active_task": active_task,
        }
    )

    with pytest.raises(RoutingCaseValidationError, match="pending_confirmation_scope"):
        validate_routing_case(raw)


def test_allowed_and_forbidden_decisions_must_be_a_complete_partition() -> None:
    raw = _case()
    gold = deepcopy(raw["gold"])
    assert isinstance(gold, dict)
    gold["router_decisions_forbidden"] = ["SPAWN_SLOW_TASK", "IGNORE"]
    raw["gold"] = gold

    with pytest.raises(RoutingCaseValidationError, match="partition"):
        validate_routing_case(raw)


def test_gold_router_partition_covers_current_router_contract() -> None:
    case = validate_routing_case(_case())

    assert set(case.gold.router_decisions_allowed) | set(
        case.gold.router_decisions_forbidden
    ) == ROUTER_DECISIONS


def test_external_side_effects_are_always_forbidden() -> None:
    raw = _case()
    gold = deepcopy(raw["gold"])
    assert isinstance(gold, dict)
    side_effects = deepcopy(gold["side_effect_expectations"])
    assert isinstance(side_effects, dict)
    side_effects["external_side_effects"] = "ALLOWED"
    gold["side_effect_expectations"] = side_effects
    raw["gold"] = gold

    with pytest.raises(RoutingCaseValidationError, match="must be 'FORBIDDEN'"):
        validate_routing_case(raw)
