from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import json
import math
import re
from typing import Any

from voice_agent.runtime.local_debug_text_safety import contains_likely_credential


SAFE_REPORT_SCHEMA_NAME = "voice_agent.routing_eval.report.safe.v1"
SAFE_RUN_METADATA_FIELDS = frozenset(
    {
        "run_id",
        "dataset_id",
        "dataset_version",
        "profile_id",
        "profile_version",
        "profile_hash",
        "model_id",
        "mode",
        "layer",
    }
)
_METRIC_FIELDS = frozenset(
    {
        "case_count",
        "route_allowed_match_rate",
        "task_focus_allowed_match_rate",
        "foreground_policy_match_rate",
        "weighted_loss_total",
        "weighted_loss_mean",
        "route",
        "task_focus",
        "critical_violations",
        "slices",
    }
)
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")
_SAFE_CASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_UNSAFE_KEY = re.compile(
    r"(?:raw|audio|prompt|provider|transcript|utterance|request|response|"
    r"secret|credential|password|authorization|cookie|model_input|event_payload)",
    re.IGNORECASE,
)
_LOCAL_PATH = re.compile(
    r"(?:^|\s)(?:/Users/|/home/|/var/|/private/|[A-Za-z]:[\\/])|"
    r"(?:^|[/\\])\.\.(?:[/\\]|$)|file://",
    re.IGNORECASE,
)
_RAW_AUDIO_SUFFIX = re.compile(
    r"\.(?:aac|aiff|flac|m4a|mp3|ogg|opus|wav|weba)(?:$|[?#])",
    re.IGNORECASE,
)


class RoutingReportSafetyError(ValueError):
    """Raised when a report input could expose local or provider artifacts."""


def build_safe_report(
    metrics: Mapping[str, Any],
    run_metadata: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Project aggregate metrics into a repository-safe report.

    The projection deliberately has no per-case prediction section. The only
    case-level values it may expose are opaque synthetic case identifiers for
    critical violations.
    """

    if not isinstance(metrics, Mapping):
        raise RoutingReportSafetyError("metrics must be a mapping")
    unexpected_metrics = set(metrics) - _METRIC_FIELDS
    missing_metrics = _METRIC_FIELDS - set(metrics)
    if unexpected_metrics or missing_metrics:
        raise RoutingReportSafetyError(
            "metrics must contain only aggregate routing metric fields"
        )
    metadata = _safe_run_metadata(run_metadata or {})
    _reject_unsafe_content(metrics, path="metrics")
    _validate_critical_case_ids(metrics["critical_violations"])
    _validate_json_numbers(metrics)

    return {
        "schema_name": SAFE_REPORT_SCHEMA_NAME,
        "run_metadata": metadata,
        "summary": {
            "case_count": metrics["case_count"],
            "route_allowed_match_rate": metrics["route_allowed_match_rate"],
            "task_focus_allowed_match_rate": metrics[
                "task_focus_allowed_match_rate"
            ],
            "foreground_policy_match_rate": metrics[
                "foreground_policy_match_rate"
            ],
            "weighted_loss_total": metrics["weighted_loss_total"],
            "weighted_loss_mean": metrics["weighted_loss_mean"],
        },
        "route": deepcopy(metrics["route"]),
        "task_focus": deepcopy(metrics["task_focus"]),
        "critical_violations": deepcopy(metrics["critical_violations"]),
        "slices": deepcopy(metrics["slices"]),
    }


def safe_report_json(
    metrics: Mapping[str, Any],
    run_metadata: Mapping[str, str] | None = None,
) -> str:
    """Serialize a safe projection deterministically without raw artifacts."""

    return json.dumps(
        build_safe_report(metrics, run_metadata),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _safe_run_metadata(metadata: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(metadata, Mapping):
        raise RoutingReportSafetyError("run_metadata must be a mapping")
    unexpected = set(metadata) - SAFE_RUN_METADATA_FIELDS
    if unexpected:
        raise RoutingReportSafetyError(
            f"unsafe or unsupported run metadata fields: {sorted(unexpected)}"
        )
    output: dict[str, str] = {}
    for key, value in metadata.items():
        if not isinstance(value, str) or _SAFE_TOKEN.fullmatch(value) is None:
            raise RoutingReportSafetyError(
                f"run_metadata.{key} must be an opaque safe token"
            )
        _reject_unsafe_string(value, f"run_metadata.{key}")
        output[key] = value
    return dict(sorted(output.items()))


def _validate_critical_case_ids(value: object) -> None:
    if not isinstance(value, Mapping):
        raise RoutingReportSafetyError("critical_violations must be aggregate data")
    allowed = {"count", "case_count", "by_type", "case_ids"}
    if set(value) != allowed:
        raise RoutingReportSafetyError(
            "critical_violations contains non-aggregate or unsafe fields"
        )
    case_ids = value["case_ids"]
    if not isinstance(case_ids, Sequence) or isinstance(case_ids, (str, bytes)):
        raise RoutingReportSafetyError("critical case_ids must be a list of safe tokens")
    for case_id in case_ids:
        if not isinstance(case_id, str) or _SAFE_CASE_ID.fullmatch(case_id) is None:
            raise RoutingReportSafetyError("critical case_ids must be opaque safe tokens")


def _reject_unsafe_content(value: object, *, path: str) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise RoutingReportSafetyError(f"{path} contains a non-string key")
            child_path = f"{path}.{key}"
            if _UNSAFE_KEY.search(key):
                raise RoutingReportSafetyError(f"unsafe report field: {child_path}")
            _reject_unsafe_content(child, path=child_path)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            _reject_unsafe_content(child, path=f"{path}[{index}]")
        return
    if isinstance(value, str):
        _reject_unsafe_string(value, path)
        return
    if value is not None and not isinstance(value, (bool, int, float)):
        raise RoutingReportSafetyError(f"unsupported report value at {path}")


def _reject_unsafe_string(value: str, path: str) -> None:
    if contains_likely_credential(value):
        raise RoutingReportSafetyError(f"likely credential detected at {path}")
    if _LOCAL_PATH.search(value):
        raise RoutingReportSafetyError(f"local path detected at {path}")
    if _RAW_AUDIO_SUFFIX.search(value) or "audio-eval://local/" in value.lower():
        raise RoutingReportSafetyError(f"raw or local audio reference detected at {path}")


def _validate_json_numbers(value: object, path: str = "metrics") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            _validate_json_numbers(child, f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            _validate_json_numbers(child, f"{path}[{index}]")
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise RoutingReportSafetyError(f"non-finite number at {path}")
