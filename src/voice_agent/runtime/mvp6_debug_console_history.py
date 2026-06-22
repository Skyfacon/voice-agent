from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any


class MVP6QAHistoryError(ValueError):
    """Raised when MVP-6 QA history would persist unsafe debug data."""


@dataclass(frozen=True)
class MVP6QAHistoryEntry:
    run_id: str
    created_at: str
    provider_mode: str
    question_source: str
    question_text: str
    answer_kind: str
    answer_display: str
    actual_route: str | None
    router_decision: str | None
    route_result_kind: str | None
    asr_output_mode: str | None
    thinker_output_mode: str | None
    provider_call_used: bool
    fake_transport_used: bool
    event_ids: tuple[str, ...] = field(default_factory=tuple)
    safe_refs: tuple[str, ...] = field(default_factory=tuple)


_UNSAFE_KEYS = frozenset(
    {
        "audio_bytes",
        "raw_audio",
        "raw_audio_bytes",
        "wav_bytes",
        "pcm_samples",
        "local_path",
        "local_wav_path",
        "temp_audio_path",
        "file_name",
        "filename",
        "approval_packet_path",
        "provider_body",
        "provider_payload",
        "provider_request",
        "provider_response",
        "prompt_dump",
        "authorization_header",
        "authorization",
        "cookie",
        "credential",
        "secret",
        "password",
        "token",
        "access_token",
        "refresh_token",
        "api_key",
    }
)

_UNSAFE_STRING_MARKERS = tuple(
    marker.lower()
    for marker in (
        "file://",
        "data:",
        "/Users/",
        "\\Users\\",
        "/private/",
        "audio/raw/",
        "diagnostics/",
        "traces/",
        "replays/local/",
        ".env",
        "authorization:",
        "cookie:",
        "api_key=",
        "token=",
        "bearer ",
        "provider body",
        "provider payload",
        "prompt dump",
    )
)

_SAFETY_FLAGS = {
    "raw_audio_saved": False,
    "provider_body_saved": False,
    "secret_saved": False,
    "local_path_saved": False,
}


def append_mvp6_qa_history(path: str | Path, entry: MVP6QAHistoryEntry) -> dict[str, Any]:
    history_path = Path(path)
    record = _record_from_entry(entry)
    validate_mvp6_history_record(record)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    rendered_record = json.dumps(record, separators=(",", ":"), sort_keys=True)
    with history_path.open("a", encoding="utf-8") as history_file:
        history_file.write(rendered_record)
        history_file.write("\n")
    persisted_record = json.loads(rendered_record)
    if not isinstance(persisted_record, dict):
        raise MVP6QAHistoryError("persisted QA history record must be an object")
    return persisted_record


def read_mvp6_qa_history(path: str | Path, limit: int = 20) -> list[dict[str, Any]]:
    history_path = Path(path)
    if not history_path.exists():
        return []
    if limit <= 0:
        return []

    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(history_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            loaded = json.loads(line)
        except json.JSONDecodeError as exc:
            raise MVP6QAHistoryError(f"invalid QA history JSONL at line {line_number}") from exc
        if not isinstance(loaded, dict):
            raise MVP6QAHistoryError(f"invalid QA history record at line {line_number}")
        record = dict(loaded)
        validate_mvp6_history_record(record)
        records.append(record)
    return records[-limit:]


def clear_mvp6_qa_history(path: str | Path) -> None:
    history_path = Path(path)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text("", encoding="utf-8")


def validate_mvp6_history_record(record: Mapping[str, Any]) -> None:
    _validate_no_unsafe_content(record)
    for flag, expected_value in _SAFETY_FLAGS.items():
        if record.get(flag) is not expected_value:
            raise MVP6QAHistoryError(f"unsafe QA history flag: {flag}")


def _record_from_entry(entry: MVP6QAHistoryEntry) -> dict[str, Any]:
    record = asdict(entry)
    record["event_ids"] = list(entry.event_ids)
    record["safe_refs"] = list(entry.safe_refs)
    record.update(_SAFETY_FLAGS)
    return record


def _validate_no_unsafe_content(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, nested_value in value.items():
            _validate_no_unsafe_content(key)
            key_text = str(key)
            if key_text.lower() in _UNSAFE_KEYS:
                raise MVP6QAHistoryError(f"unsafe QA history key: {key_text}")
            _validate_no_unsafe_content(nested_value)
        return

    if isinstance(value, (bytes, bytearray)):
        raise MVP6QAHistoryError("unsafe QA history bytes")

    if isinstance(value, str):
        value_lower = value.lower()
        for marker in _UNSAFE_STRING_MARKERS:
            if marker in value_lower:
                raise MVP6QAHistoryError(f"unsafe QA history string marker: {marker}")
        return

    if isinstance(value, Sequence):
        for item in value:
            _validate_no_unsafe_content(item)
