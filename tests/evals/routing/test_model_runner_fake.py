from __future__ import annotations

from copy import deepcopy
import json

import pytest

from voice_agent.evals.routing.case import (
    routing_case_to_model_input,
    validate_routing_case,
)
from voice_agent.evals.routing.model_runner import (
    FakeInjectedModelAdapter,
    ModelOutputValidationError,
    ModelProfileMetadata,
    ModelRunnerError,
    run_model_case,
)


PROFILE_HASH = "sha256:" + "a" * 64
PROFILE = ModelProfileMetadata(
    profile_id="routing-eval-test",
    profile_version="v1",
    profile_hash=PROFILE_HASH,
)


def _case() -> dict[str, object]:
    return {
        "schema_name": "voice_agent.routing_eval.case.v1",
        "case_id": "model_case_001",
        "scenario_family_id": "model_family_001",
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
        "tags": ["minimal_pair", "simple_explanation"],
        "criticality": "low",
        "annotation_status": "draft",
    }


def _output(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "task_focus_hint": "FOREGROUND_CHAT",
        "route_hint": "FAST_ONLY",
        "task_like": False,
        "complexity_hint": "simple",
        "evidence_uncertainty": "low",
        "directedness": "ASSUMED_DIRECTED",
        "foreground_act": "ANSWER",
        "risk": "LOW",
        "confidence": 0.91,
        "schema_valid": True,
        "output_mode": "mock",
        "latency_ms": 12.5,
        "profile_id": PROFILE.profile_id,
        "profile_version": PROFILE.profile_version,
        "profile_hash": PROFILE.profile_hash,
    }
    value.update(overrides)
    return value


def test_fake_model_runner_receives_only_gold_free_model_input() -> None:
    case = validate_routing_case(_case())
    adapter = FakeInjectedModelAdapter(_output())

    run = run_model_case(case, adapter, PROFILE)

    assert adapter.calls == [routing_case_to_model_input(case)]
    serialized_input = json.dumps(adapter.calls[0], ensure_ascii=False)
    for forbidden in (
        "gold",
        "task_focus_allowed",
        "router_decisions_allowed",
        "criticality",
        "annotation_status",
        "scenario_family_id",
    ):
        assert forbidden not in serialized_input
    assert run.output.task_focus_hint == "FOREGROUND_CHAT"
    assert run.output.route_hint == "FAST_ONLY"


def test_model_output_projects_to_router_evidence_and_unobserved_metrics_prediction() -> None:
    run = run_model_case(_case(), FakeInjectedModelAdapter(_output()), PROFILE)

    evidence = run.predicted_evidence
    assert evidence.task_focus_hint == "FOREGROUND_CHAT"
    assert evidence.route_decision_hint == "FAST_ONLY"
    assert evidence.emit_candidate is False
    prediction = run.prediction
    assert prediction.case_id == "model_case_001"
    assert prediction.foreground_policy is None
    assert prediction.slow_task_created is False
    assert prediction.user_patch_emitted is False
    assert prediction.external_side_effects is False
    assert prediction.answer_candidate_committed is False


def test_fake_output_is_explicit_and_never_defaulted_from_gold() -> None:
    injected = _output(
        task_focus_hint="NEW_TASK_CANDIDATE",
        route_hint="SPAWN_SLOW_TASK",
        task_like=True,
        complexity_hint="complex",
        foreground_act="ACK_SLOW",
    )

    run = run_model_case(_case(), FakeInjectedModelAdapter(injected), PROFILE)

    assert run.output.task_focus_hint == "NEW_TASK_CANDIDATE"
    assert run.prediction.router_decision == "SPAWN_SLOW_TASK"
    assert run.output.task_focus_hint not in _case()["gold"]["task_focus_allowed"]  # type: ignore[index]


@pytest.mark.parametrize(
    "overrides",
    (
        {"schema_valid": False},
        {"task_focus_hint": "NOT_A_FOCUS"},
        {"route_hint": "CLARIFY"},
        {"task_like": "false"},
        {"complexity_hint": "huge"},
        {"evidence_uncertainty": "maybe"},
        {"directedness": "MAYBE_DIRECTED"},
        {"foreground_act": "TOOL_CALL"},
        {"risk": "CRITICAL"},
        {"confidence": 1.1},
        {"latency_ms": -1},
        {"output_mode": "provider"},
    ),
)
def test_rejects_invalid_model_output_schema(overrides: dict[str, object]) -> None:
    adapter = FakeInjectedModelAdapter(_output(**overrides))

    with pytest.raises(ModelOutputValidationError):
        run_model_case(_case(), adapter, PROFILE)


def test_rejects_missing_or_extra_model_output_fields() -> None:
    missing = _output()
    del missing["route_hint"]
    extra = _output(provider_body={"unsafe": True})

    with pytest.raises(ModelOutputValidationError, match="exactly"):
        run_model_case(_case(), FakeInjectedModelAdapter(missing), PROFILE)
    with pytest.raises(ModelOutputValidationError, match="exactly"):
        run_model_case(_case(), FakeInjectedModelAdapter(extra), PROFILE)


def test_profile_metadata_must_be_safe_and_match_adapter_output() -> None:
    mismatch = _output(profile_hash="sha256:" + "b" * 64)
    with pytest.raises(ModelOutputValidationError, match="does not match"):
        run_model_case(_case(), FakeInjectedModelAdapter(mismatch), PROFILE)

    with pytest.raises(ModelRunnerError, match="sha256"):
        run_model_case(
            _case(),
            FakeInjectedModelAdapter(_output()),
            {
                "profile_id": "routing-eval-test",
                "profile_version": "v1",
                "profile_hash": "not-a-hash",
            },
        )


def test_accepts_existing_profile_to_metadata_shape_without_passing_it_to_adapter() -> None:
    metadata = {
        **PROFILE.to_dict(),
        "locale": "zh-CN",
        "candidate_schema_version": "candidate.v1",
    }
    adapter = FakeInjectedModelAdapter(_output())

    run = run_model_case(_case(), adapter, metadata)

    assert run.output.profile_hash == PROFILE_HASH
    assert "profile_id" not in adapter.calls[0]


def test_fake_run_reports_provider_free_flags_and_json_compatible_result() -> None:
    adapter = FakeInjectedModelAdapter(_output())

    run = run_model_case(_case(), adapter, PROFILE)
    result = run.to_dict()

    assert result["provider_call_used"] is False
    assert result["network_used"] is False
    assert result["credential_env_var_read"] is False
    assert result["gold_included_in_model_input"] is False
    assert result["raw_audio_included"] is False
    assert result["raw_provider_body_included"] is False
    assert result["prompt_dump_included"] is False
    assert result["secret_included"] is False
    json.dumps(result, ensure_ascii=False, allow_nan=False)


def test_fake_returns_defensive_copies_of_calls_and_injected_output() -> None:
    output = _output()
    adapter = FakeInjectedModelAdapter(output)
    output["route_hint"] = "IGNORE"
    case = _case()

    run = run_model_case(case, adapter, PROFILE)
    adapter.calls[0]["input"]["locale"] = "en-US"

    assert run.output.route_hint == "FAST_ONLY"
    assert case["input"]["locale"] == "zh-CN"  # type: ignore[index]
