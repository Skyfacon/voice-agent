from __future__ import annotations

import pytest

from voice_agent.adapters.adapter_timing import AdapterTimingRecorder


def test_streaming_timing_records_ttft_full_response_and_generation() -> None:
    now_values = iter([1000, 1010, 1040, 1125, 1140])
    recorder = AdapterTimingRecorder(
        turn_ingress_monotonic_ms=900,
        now_ms=lambda: next(now_values),
    )

    recorder.mark_adapter_started()
    recorder.mark_provider_request_started()
    recorder.mark_provider_first_chunk()
    recorder.mark_provider_full_response()
    snapshot = recorder.finish(parse_validate_emit_ms=15)

    assert snapshot.provider_request_start_offset_ms == 110
    assert snapshot.provider_first_chunk_offset_ms == 140
    assert snapshot.provider_full_response_offset_ms == 225
    assert snapshot.adapter_event_emit_offset_ms == 240
    assert snapshot.provider_ttft_ms == 30
    assert snapshot.provider_full_response_ms == 115
    assert snapshot.provider_generation_ms == 85
    assert snapshot.parse_validate_emit_ms == 15
    assert snapshot.total_ms == 140
    assert snapshot.ttft_available is True
    assert snapshot.ttft_source == "provider_stream_chunk"


def test_non_streaming_timing_does_not_invent_ttft() -> None:
    now_values = iter([2000, 2010, 2300, 2320])
    recorder = AdapterTimingRecorder(
        turn_ingress_monotonic_ms=1900,
        now_ms=lambda: next(now_values),
    )

    recorder.mark_adapter_started()
    recorder.mark_provider_request_started()
    recorder.mark_provider_full_response()
    snapshot = recorder.finish(parse_validate_emit_ms=20)

    assert snapshot.provider_ttft_ms is None
    assert snapshot.provider_generation_ms is None
    assert snapshot.ttft_available is False
    assert snapshot.ttft_source == "not_available"
    assert snapshot.provider_full_response_ms == 290
    assert snapshot.total_ms == 320


def test_timing_metadata_is_scalar_and_prefixed() -> None:
    now_values = iter([10, 20, 25, 40, 45])
    recorder = AdapterTimingRecorder(turn_ingress_monotonic_ms=0, now_ms=lambda: next(now_values))
    recorder.mark_adapter_started()
    recorder.mark_provider_request_started()
    recorder.mark_provider_first_chunk()
    recorder.mark_provider_full_response()

    metadata = recorder.finish(parse_validate_emit_ms=5).to_prefixed_metadata("thinker")

    assert metadata["thinker_provider_ttft_ms"] == 5
    assert metadata["thinker_provider_full_response_ms"] == 20
    assert metadata["thinker_provider_generation_ms"] == 15
    assert metadata["thinker_ttft_available"] is True
    assert metadata["thinker_ttft_source"] == "provider_stream_chunk"
    assert all(not isinstance(value, (dict, list, tuple, bytes, bytearray)) for value in metadata.values())


def test_timing_metadata_rejects_unknown_prefix() -> None:
    now_values = iter([10, 20])
    recorder = AdapterTimingRecorder(turn_ingress_monotonic_ms=0, now_ms=lambda: next(now_values))
    recorder.mark_adapter_started()

    with pytest.raises(ValueError):
        recorder.finish(parse_validate_emit_ms=0).to_prefixed_metadata("slow_llm")
