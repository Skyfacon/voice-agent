from __future__ import annotations

import json

import pytest

from voice_agent.evals.routing.report import (
    SAFE_REPORT_SCHEMA_NAME,
    RoutingReportSafetyError,
    build_safe_report,
    safe_report_json,
)


def _metrics() -> dict[str, object]:
    classes = {
        "FAST_ONLY": {
            "support": 1,
            "predicted_count": 1,
            "precision": 1.0,
            "recall": 1.0,
            "f1": 1.0,
        }
    }
    route = {
        "confusion_matrix": {"FAST_ONLY": {"FAST_ONLY": 1}},
        "per_class": classes,
        "macro_f1": 1.0,
    }
    return {
        "case_count": 1,
        "route_allowed_match_rate": 1.0,
        "task_focus_allowed_match_rate": 1.0,
        "foreground_policy_match_rate": 1.0,
        "weighted_loss_total": 0.0,
        "weighted_loss_mean": 0.0,
        "route": route,
        "task_focus": {
            "confusion_matrix": {"FOREGROUND_CHAT": {"FOREGROUND_CHAT": 1}},
            "per_class": {
                "FOREGROUND_CHAT": {
                    "support": 1,
                    "predicted_count": 1,
                    "precision": 1.0,
                    "recall": 1.0,
                    "f1": 1.0,
                }
            },
            "macro_f1": 1.0,
        },
        "critical_violations": {
            "count": 1,
            "case_count": 1,
            "by_type": {"SYNTHETIC_FAILURE": 1},
            "case_ids": ["synthetic_case_001"],
        },
        "slices": {
            "template": {
                "NO_ACTIVE_TASK": {
                    "case_count": 1,
                    "route_allowed_match_rate": 1.0,
                    "task_focus_allowed_match_rate": 1.0,
                    "weighted_loss_total": 0.0,
                    "weighted_loss_mean": 0.0,
                    "critical_violation_count": 1,
                }
            },
            "criticality": {},
        },
    }


def test_safe_report_contains_only_aggregate_data_and_synthetic_case_ids() -> None:
    report = build_safe_report(
        _metrics(),
        {
            "run_id": "run-001",
            "dataset_id": "routing-synthetic-v1",
            "profile_hash": "abc123",
            "model_id": "model-synthetic",
            "mode": "mock",
            "layer": "router",
        },
    )

    assert report["schema_name"] == SAFE_REPORT_SCHEMA_NAME
    assert report["summary"]["case_count"] == 1
    assert report["critical_violations"]["case_ids"] == ["synthetic_case_001"]
    serialized = safe_report_json(_metrics(), report["run_metadata"])
    assert json.loads(serialized)["schema_name"] == SAFE_REPORT_SCHEMA_NAME
    for forbidden in (
        "utterance_text",
        "transcript",
        "audio_ref",
        "prompt_body",
        "provider_body",
        "prediction_by_case",
    ):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    "unsafe_field",
    (
        "raw_audio",
        "prompt_body",
        "provider_body",
        "provider_response",
        "real_transcript",
        "utterance_text",
    ),
)
def test_safe_report_rejects_raw_prompt_provider_audio_and_transcript_fields(
    unsafe_field: str,
) -> None:
    with pytest.raises(RoutingReportSafetyError, match="unsafe|unsupported"):
        build_safe_report(_metrics(), {unsafe_field: "synthetic"})

    metrics = _metrics()
    metrics["route"][unsafe_field] = "must not be emitted"
    with pytest.raises(RoutingReportSafetyError, match="unsafe report field"):
        build_safe_report(metrics)


@pytest.mark.parametrize(
    "unsafe_value",
    (
        "/Users/person/audio/sample.wav",
        "../local/recording.wav",
        "audio-eval://local/private-recording",
        "api_key=not-a-real-but-unsafe-value",
        "authorization: bearer abcdefghijk",
    ),
)
def test_safe_report_rejects_local_paths_audio_refs_and_credentials(
    unsafe_value: str,
) -> None:
    with pytest.raises(RoutingReportSafetyError):
        build_safe_report(_metrics(), {"model_id": unsafe_value})


def test_safe_report_rejects_non_opaque_case_ids_and_non_finite_numbers() -> None:
    metrics = _metrics()
    metrics["critical_violations"]["case_ids"] = ["../real-transcript"]
    with pytest.raises(RoutingReportSafetyError, match="case_ids"):
        build_safe_report(metrics)

    metrics = _metrics()
    metrics["weighted_loss_mean"] = float("nan")
    with pytest.raises(RoutingReportSafetyError, match="non-finite"):
        build_safe_report(metrics)
