"""Manual validation helpers for TTS playback eval observations."""

from __future__ import annotations

import json
import pathlib
from collections.abc import Iterable
from typing import Any


SCHEMA_VERSION = "tts_playback_proof_observation.v1"
OUTPUT_MODES = {"mock", "real", "degraded", "fallback"}
OWNER_FIELDS = {
    "talker_playback_owns_playback_state",
    "interaction_owns_truncate_request",
    "tts_adapter_only_provides_audio_metadata",
}

REQUIRED_TOP_LEVEL = {
    "schema_version",
    "contract_snapshot",
    "observation_id",
    "case_id",
    "observation_kind",
    "output_mode",
    "adapter_observation",
    "request_metadata",
    "stream_metadata",
    "playback_metadata",
    "control_metadata",
    "privacy",
    "boundary_assertions",
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
    if record.get("output_mode") not in OUTPUT_MODES:
        errors.append("output_mode must be mock, real, degraded, or fallback")

    adapter = _object(record, "adapter_observation", errors)
    stream = _object(record, "stream_metadata", errors)
    playback = _object(record, "playback_metadata", errors)
    control = _object(record, "control_metadata", errors)
    privacy = _object(record, "privacy", errors)
    boundary = _object(record, "boundary_assertions", errors)

    if adapter.get("adapter_type") != "tts_talker":
        errors.append("adapter_type must be tts_talker")

    _require_false(privacy, "generated_audio_stored", errors)
    _require_false(privacy, "provider_response_body_stored", errors)
    _require_false(privacy, "request_secret_material_stored", errors)
    _require_false(privacy, "deterministic_replay_reruns_tts", errors)

    for key in OWNER_FIELDS:
        if boundary.get(key) is not True:
            errors.append(f"{key} must be true")
    for key in (
        "tts_output_is_user_acknowledgement",
        "tts_output_is_semantic_commitment",
        "tts_decides_confirmation",
        "tts_authorizes_tools",
        "tts_decides_task_completion",
    ):
        if boundary.get(key) is not False:
            errors.append(f"{key} must be false")

    offsets = playback.get("progress_offsets_ms", [])
    if not isinstance(offsets, list) or not all(isinstance(value, int) for value in offsets):
        errors.append("progress_offsets_ms must be a list of integers")
    elif offsets != sorted(offsets):
        errors.append("progress_offsets_ms must be monotonic")

    if playback.get("playback_committed") and playback.get("commit_basis") is None:
        errors.append("playback_committed requires commit_basis")
    if playback.get("playback_committed") and boundary.get("tts_output_is_user_acknowledgement") is not False:
        errors.append("playback committed cannot be acknowledgement")

    if control.get("truncate_requested"):
        if control.get("cutoff_playback_offset_ms") is None:
            errors.append("truncate_requested requires cutoff_playback_offset_ms")
    if control.get("tts_truncated"):
        if control.get("actual_stop_offset_ms") is None:
            errors.append("tts_truncated requires actual_stop_offset_ms")
        if control.get("truncate_request_event_id") is None:
            errors.append("tts_truncated requires truncate_request_event_id")

    for key in ("chunk_count", "audio_byte_count"):
        value = stream.get(key)
        if not isinstance(value, int) or value < 0:
            errors.append(f"{key} must be a non-negative integer")
    if stream.get("provider_cancel_confirmed") not in {"true", "false", "unknown"}:
        errors.append("provider_cancel_confirmed must be true, false, or unknown")

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
