from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass


_ALLOWED_METADATA_PREFIXES = frozenset({"thinker", "fast_interaction"})


@dataclass(frozen=True)
class AdapterTimingSnapshot:
    adapter_start_offset_ms: int
    provider_request_start_offset_ms: int | None
    provider_first_chunk_offset_ms: int | None
    provider_full_response_offset_ms: int | None
    adapter_event_emit_offset_ms: int
    provider_ttft_ms: int | None
    provider_full_response_ms: int | None
    provider_generation_ms: int | None
    stream_decode_ms: int
    parse_validate_emit_ms: int
    total_ms: int
    timing_mode: str
    ttft_available: bool
    ttft_source: str

    def to_prefixed_metadata(self, prefix: str) -> dict[str, int | bool | str | None]:
        if prefix not in _ALLOWED_METADATA_PREFIXES:
            allowed = ", ".join(sorted(_ALLOWED_METADATA_PREFIXES))
            raise ValueError(f"unsupported adapter timing metadata prefix {prefix!r}; expected one of: {allowed}")

        return {
            f"{prefix}_adapter_start_offset_ms": self.adapter_start_offset_ms,
            f"{prefix}_provider_request_start_offset_ms": self.provider_request_start_offset_ms,
            f"{prefix}_provider_first_chunk_offset_ms": self.provider_first_chunk_offset_ms,
            f"{prefix}_provider_full_response_offset_ms": self.provider_full_response_offset_ms,
            f"{prefix}_adapter_event_emit_offset_ms": self.adapter_event_emit_offset_ms,
            f"{prefix}_provider_ttft_ms": self.provider_ttft_ms,
            f"{prefix}_provider_full_response_ms": self.provider_full_response_ms,
            f"{prefix}_provider_generation_ms": self.provider_generation_ms,
            f"{prefix}_stream_decode_ms": self.stream_decode_ms,
            f"{prefix}_parse_validate_emit_ms": self.parse_validate_emit_ms,
            f"{prefix}_total_ms": self.total_ms,
            f"{prefix}_timing_mode": self.timing_mode,
            f"{prefix}_ttft_available": self.ttft_available,
            f"{prefix}_ttft_source": self.ttft_source,
        }


class AdapterTimingRecorder:
    def __init__(
        self,
        *,
        turn_ingress_monotonic_ms: int,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self._turn_ingress_monotonic_ms = int(turn_ingress_monotonic_ms)
        self._now_ms = now_ms if now_ms is not None else _monotonic_ms
        self._adapter_started_ms: int | None = None
        self._provider_request_started_ms: int | None = None
        self._provider_first_chunk_ms: int | None = None
        self._provider_full_response_ms: int | None = None

    def mark_adapter_started(self) -> None:
        self._adapter_started_ms = self._read_now_ms()

    def mark_provider_request_started(self) -> None:
        self._provider_request_started_ms = self._read_now_ms()

    def mark_provider_first_chunk(self) -> None:
        first_chunk_ms = self._read_now_ms()
        if self._provider_first_chunk_ms is None:
            self._provider_first_chunk_ms = first_chunk_ms

    def mark_provider_full_response(self) -> None:
        self._provider_full_response_ms = self._read_now_ms()

    def finish(self, *, parse_validate_emit_ms: int, stream_decode_ms: int = 0) -> AdapterTimingSnapshot:
        adapter_event_emit_ms = self._read_now_ms()
        adapter_started_ms = self._adapter_started_ms if self._adapter_started_ms is not None else adapter_event_emit_ms
        request_started_ms = self._provider_request_started_ms
        first_chunk_ms = self._provider_first_chunk_ms
        full_response_ms = self._provider_full_response_ms

        provider_ttft_ms = None
        if request_started_ms is not None and first_chunk_ms is not None:
            provider_ttft_ms = first_chunk_ms - request_started_ms

        provider_generation_ms = None
        if first_chunk_ms is not None and full_response_ms is not None:
            provider_generation_ms = full_response_ms - first_chunk_ms

        provider_full_response_ms = None
        if request_started_ms is not None and full_response_ms is not None:
            provider_full_response_ms = full_response_ms - request_started_ms

        ttft_available = provider_ttft_ms is not None

        return AdapterTimingSnapshot(
            adapter_start_offset_ms=self._offset_from_turn_ingress(adapter_started_ms),
            provider_request_start_offset_ms=self._optional_offset_from_turn_ingress(request_started_ms),
            provider_first_chunk_offset_ms=self._optional_offset_from_turn_ingress(first_chunk_ms),
            provider_full_response_offset_ms=self._optional_offset_from_turn_ingress(full_response_ms),
            adapter_event_emit_offset_ms=self._offset_from_turn_ingress(adapter_event_emit_ms),
            provider_ttft_ms=provider_ttft_ms,
            provider_full_response_ms=provider_full_response_ms,
            provider_generation_ms=provider_generation_ms,
            stream_decode_ms=int(stream_decode_ms),
            parse_validate_emit_ms=int(parse_validate_emit_ms),
            total_ms=adapter_event_emit_ms - adapter_started_ms,
            timing_mode="streaming" if ttft_available else "non_streaming",
            ttft_available=ttft_available,
            ttft_source="provider_stream_chunk" if ttft_available else "not_available",
        )

    def _read_now_ms(self) -> int:
        return int(self._now_ms())

    def _offset_from_turn_ingress(self, monotonic_ms: int) -> int:
        return monotonic_ms - self._turn_ingress_monotonic_ms

    def _optional_offset_from_turn_ingress(self, monotonic_ms: int | None) -> int | None:
        if monotonic_ms is None:
            return None
        return self._offset_from_turn_ingress(monotonic_ms)


def _monotonic_ms() -> int:
    return int(time.monotonic() * 1000)
