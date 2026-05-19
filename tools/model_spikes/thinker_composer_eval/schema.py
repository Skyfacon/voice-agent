"""Manual validation helpers for Thinker / Composer eval observations."""

from __future__ import annotations

import json
import pathlib
from collections.abc import Iterable
from typing import Any


SCHEMA_VERSION = "thinker_composer_boundary_observation.v1"
OUTPUT_MODES = {"mock", "real", "degraded", "fallback"}
ADAPTER_TYPES = {"thinker", "thinker_as_composer"}
BOOLEAN_OR_NULL = {True, False, None}

REQUIRED_TOP_LEVEL = {
    "schema_version",
    "contract_snapshot",
    "observation_id",
    "case_id",
    "observation_kind",
    "expected_evidence_label",
    "candidate",
    "input_fixture",
    "request_observation",
    "semantic_frame_observation",
    "composer_observation",
    "boundary_observation",
    "streaming_observation",
    "failure_observation",
    "privacy",
}


def load_jsonl(path: pathlib.Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.expanduser().resolve().open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                value = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"line {line_number}: invalid JSON") from exc
            if not isinstance(value, dict):
                raise ValueError(f"line {line_number}: expected JSON object")
            records.append(value)
    return records


def validate_observation(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    missing = sorted(REQUIRED_TOP_LEVEL.difference(record))
    if missing:
        errors.append(f"missing top-level fields: {missing}")

    if record.get("schema_version") != SCHEMA_VERSION:
        errors.append("invalid schema_version")

    candidate = _object(record, "candidate", errors)
    fixture = _object(record, "input_fixture", errors)
    request = _object(record, "request_observation", errors)
    semantic = _object(record, "semantic_frame_observation", errors)
    composer = _object(record, "composer_observation", errors)
    boundary = _object(record, "boundary_observation", errors)
    streaming = _object(record, "streaming_observation", errors)
    failure = _object(record, "failure_observation", errors)
    privacy = _object(record, "privacy", errors)

    if candidate.get("adapter_type") not in ADAPTER_TYPES:
        errors.append("candidate.adapter_type must be thinker or thinker_as_composer")
    if candidate.get("output_mode") not in OUTPUT_MODES:
        errors.append("candidate.output_mode must be mock, real, degraded, or fallback")
    if candidate.get("deployment_mode") != "synthetic":
        errors.append("candidate.deployment_mode must be synthetic for dry-run")

    for key in (
        "contains_real_user_input",
        "contains_raw_audio_in_report",
        "contains_provider_body_in_report",
    ):
        _require_false(fixture, key, errors)

    if request.get("calls_provider") is not False:
        errors.append("dry-run must not call provider")
    if request.get("executes_tools") is not False:
        errors.append("dry-run must not execute tools")
    if request.get("imports_main_runtime") is not False:
        errors.append("dry-run must not import main runtime")

    for key in ("schema_parse_passed", "schema_validation_passed", "semantic_frame_not_commitment"):
        if semantic.get(key) not in BOOLEAN_OR_NULL:
            errors.append(f"semantic_frame_observation.{key} must be boolean or null")

    if semantic.get("web_evidence_trusted_as_instruction") is not False:
        errors.append("web evidence must not be trusted as instruction")
    if semantic.get("semantic_frame_not_commitment") is False:
        errors.append("SemanticFrame observation cannot be a SemanticCommitment")

    is_composer = candidate.get("adapter_type") == "thinker_as_composer"
    if is_composer:
        if composer.get("source_commitment_present") is not True:
            errors.append("composer case requires source commitment metadata")
        if composer.get("coverage_check_required") is not True:
            errors.append("composer case requires coverage check")
        if composer.get("coverage_check_passed") is False and boundary.get("talker_playback_allowed") is not False:
            errors.append("failed coverage must block Talker playback")
        if composer.get("confirmation_state_preserved") is False:
            errors.append("composer must not change confirmation state")
        if composer.get("resolved_arguments_preserved") is False:
            errors.append("composer must not rewrite resolved arguments")

    if boundary.get("router_selected_winner") is not False:
        errors.append("Thinker eval must not select Router winner")
    if boundary.get("slowtask_commitment_owner") is not True:
        errors.append("SlowTask must remain SemanticCommitment owner")
    if boundary.get("interaction_ingress_owner") is not True:
        errors.append("Interaction Controller must remain ingress owner")
    if boundary.get("tool_executor_required") is not True:
        errors.append("Tool Executor must remain required for execution")
    if boundary.get("model_accepts_confirmation") is not False:
        errors.append("model cannot accept confirmation")
    if boundary.get("model_authorizes_tools") is not False:
        errors.append("model cannot authorize tools")
    if boundary.get("tool_execution_started") is not False:
        errors.append("eval observation must not start tool execution")

    if streaming.get("delta_chunk_count", 0) < 0:
        errors.append("delta_chunk_count must be non-negative")
    if streaming.get("full_response_suitable_for_duplex_hot_path") is not False:
        errors.append("full structured Thinker response must not be treated as Duplex hot path")

    if failure.get("provider_cancel_confirmed") not in {"true", "false", "unknown"}:
        errors.append("provider_cancel_confirmed must be true, false, or unknown")
    if failure.get("failure_category") and candidate.get("output_mode") == "real":
        errors.append("failure observations must not be marked real")

    for key in (
        "stored_audio",
        "stored_provider_body",
        "stored_trace",
        "stored_secret_material",
        "deterministic_replay_reruns_provider",
    ):
        _require_false(privacy, key, errors)

    return errors


def validate_records(records: Iterable[dict[str, Any]]) -> tuple[int, list[str]]:
    count = 0
    errors: list[str] = []
    for count, record in enumerate(records, start=1):
        for error in validate_observation(record):
            errors.append(f"record {count} {record.get('case_id', '<unknown>')}: {error}")
    return count, errors


def _object(record: dict[str, Any], key: str, errors: list[str]) -> dict[str, Any]:
    value = record.get(key)
    if isinstance(value, dict):
        return value
    if key in record:
        errors.append(f"{key} must be an object")
    return {}


def _require_false(record: dict[str, Any], key: str, errors: list[str]) -> None:
    if record.get(key) is not False:
        errors.append(f"{key} must be false")
