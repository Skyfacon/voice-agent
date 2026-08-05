from __future__ import annotations

from collections.abc import Mapping
from typing import Any


_THINKER_TIMING_INT_OR_NONE_FIELDS = frozenset(
    {
        "thinker_adapter_start_offset_ms",
        "thinker_provider_request_start_offset_ms",
        "thinker_provider_first_chunk_offset_ms",
        "thinker_provider_full_response_offset_ms",
        "thinker_adapter_event_emit_offset_ms",
        "thinker_provider_ttft_ms",
        "thinker_provider_full_response_ms",
        "thinker_provider_generation_ms",
        "thinker_stream_decode_ms",
        "thinker_parse_validate_emit_ms",
        "thinker_total_ms",
    }
)
_THINKER_TIMING_BOOL_FIELDS = frozenset({"thinker_ttft_available"})
_THINKER_TIMING_STRING_VALUES = {
    "thinker_timing_mode": frozenset({"streaming", "non_streaming"}),
    "thinker_ttft_source": frozenset({"provider_stream_chunk", "not_available"}),
}
THINKER_TIMING_METADATA_FIELDS = frozenset(
    {
        *_THINKER_TIMING_INT_OR_NONE_FIELDS,
        *_THINKER_TIMING_BOOL_FIELDS,
        *_THINKER_TIMING_STRING_VALUES,
    }
)
THINKER_PROVIDER_TIMING_METADATA_FIELDS = frozenset(
    {
        "thinker_adapter_start_offset_ms",
        "thinker_provider_request_start_offset_ms",
        "thinker_provider_first_chunk_offset_ms",
        "thinker_provider_full_response_offset_ms",
        "thinker_provider_ttft_ms",
        "thinker_provider_full_response_ms",
        "thinker_provider_generation_ms",
        "thinker_stream_decode_ms",
        "thinker_timing_mode",
        "thinker_ttft_available",
        "thinker_ttft_source",
    }
)


def sanitize_thinker_timing_metadata(timing: object) -> dict[str, Any]:
    to_prefixed_metadata = getattr(timing, "to_prefixed_metadata", None)
    if not callable(to_prefixed_metadata):
        return {}
    try:
        raw_metadata = to_prefixed_metadata("thinker")
    except Exception:
        return {}
    return sanitize_thinker_timing_metadata_mapping(raw_metadata)


def sanitize_thinker_provider_timing_metadata(timing: object) -> dict[str, Any]:
    metadata = sanitize_thinker_timing_metadata(timing)
    return {
        key: value
        for key, value in metadata.items()
        if key in THINKER_PROVIDER_TIMING_METADATA_FIELDS
    }


def sanitize_thinker_timing_metadata_mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}

    sanitized: dict[str, Any] = {}
    for key, raw_value in value.items():
        if key in _THINKER_TIMING_INT_OR_NONE_FIELDS:
            if raw_value is None:
                sanitized[key] = None
            elif isinstance(raw_value, int) and not isinstance(raw_value, bool) and raw_value >= 0:
                sanitized[key] = raw_value
        elif key in _THINKER_TIMING_BOOL_FIELDS:
            if isinstance(raw_value, bool):
                sanitized[key] = raw_value
        elif key in _THINKER_TIMING_STRING_VALUES:
            if isinstance(raw_value, str) and raw_value in _THINKER_TIMING_STRING_VALUES[key]:
                sanitized[key] = raw_value
    return sanitized
