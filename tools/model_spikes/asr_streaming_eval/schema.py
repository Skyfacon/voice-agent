"""Manual validation helpers for ASR streaming eval observations."""

from __future__ import annotations

import json
import pathlib
from collections.abc import Iterable
from typing import Any


SCHEMA_VERSION = "asr_streaming_timestamp_cancellation_observation_v1"
OUTPUT_MODES = {"mock", "real", "degraded", "fallback"}
TIMESTAMP_STATUSES = {"normalized", "degraded", "unavailable"}

REQUIRED_TOP_LEVEL = {
    "schema_version",
    "contract_snapshot",
    "observation_id",
    "case_id",
    "adapter_type",
    "provider",
    "model_name",
    "deployment_mode",
    "endpoint_ref",
    "output_mode",
    "input_fixture",
    "request_observation",
    "transcript_observation",
    "streaming_observation",
    "timestamp_observation",
    "quality_flags",
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
    if record.get("adapter_type") != "asr":
        errors.append("adapter_type must be asr")
    if record.get("output_mode") not in OUTPUT_MODES:
        errors.append("output_mode must be mock, real, degraded, or fallback")

    input_fixture = _object(record, "input_fixture", errors)
    transcript = _object(record, "transcript_observation", errors)
    streaming = _object(record, "streaming_observation", errors)
    timestamps = _object(record, "timestamp_observation", errors)
    quality = _object(record, "quality_flags", errors)
    failure = _object(record, "failure_observation", errors)
    privacy = _object(record, "privacy", errors)

    _require_false(input_fixture, "contains_real_user_input", errors)
    _require_false(input_fixture, "contains_audio_in_report", errors)
    _require_false(privacy, "stored_audio", errors)
    _require_false(privacy, "stored_provider_body", errors)
    _require_false(privacy, "stored_sensitive_access_material", errors)

    if transcript:
        transcript_present = transcript.get("transcript_present")
        length = transcript.get("transcript_length_chars")
        if not isinstance(transcript_present, bool):
            errors.append("transcript_present must be boolean")
        if not isinstance(length, int) or length < 0:
            errors.append("transcript_length_chars must be a non-negative integer")
        if transcript_present is False and length != 0:
            errors.append("missing transcript must have length 0")
        _require_false(transcript, "stored_full_transcript", errors)
        if quality.get("expected_non_speech") and transcript_present:
            if quality.get("non_speech_transcript_risk") is not True:
                errors.append("non-speech transcript must set risk flag")
            if transcript.get("reliable_directed_user_input") is not False:
                errors.append("non-speech transcript cannot be reliable directed input")

    if streaming:
        for key in ("delta_chunk_count",):
            value = streaming.get(key)
            if not isinstance(value, int) or value < 0:
                errors.append(f"{key} must be a non-negative integer")

    if timestamps:
        status = timestamps.get("normalization_status")
        if status not in TIMESTAMP_STATUSES:
            errors.append("invalid timestamp normalization_status")
        for key in ("segment_count", "word_count"):
            value = timestamps.get(key)
            if not isinstance(value, int) or value < 0:
                errors.append(f"{key} must be a non-negative integer")
        normalized = timestamps.get("normalized")
        if status == "normalized" and normalized is not True:
            errors.append("normalized timestamp status must set normalized=true")
        if status == "unavailable" and normalized is not False:
            errors.append("unavailable timestamp status must set normalized=false")

    if failure:
        confirmed = failure.get("provider_confirmed_cancellation")
        if confirmed not in {"true", "false", "unknown"}:
            errors.append("provider_confirmed_cancellation must be true, false, or unknown")

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
