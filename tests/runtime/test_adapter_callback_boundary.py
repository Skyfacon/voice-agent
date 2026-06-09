from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from voice_agent.events.journal import InMemoryEventJournal
from voice_agent.runtime.adapter_callback_boundary import (
    AdapterCallbackAppendBoundary,
    AdapterCallbackBoundaryError,
)


def make_started_journal() -> InMemoryEventJournal:
    journal = InMemoryEventJournal(
        session_id="sess_mvp3_callback_boundary_synthetic",
        conversation_id="conv_mvp3_callback_boundary_synthetic",
    )
    journal.append(
        event_name="SESSION_STARTED",
        event_id="evt_mvp3_callback_boundary_session_started",
        source_module="session_runtime",
        created_monotonic_ms=1,
        created_wall_clock_ms=1700000000001,
        trace_redaction_level="metadata_only",
        runtime_config_ref="config://synthetic/mvp3/callback-boundary",
        capability_snapshot_ref="capability://synthetic/mvp3/callback-boundary",
    )
    return journal


def append_adapter_failure(
    boundary: AdapterCallbackAppendBoundary,
    *,
    index: int,
    caused_by_event_id: str,
) -> dict[str, object]:
    return boundary.append_adapter_event(
        event_name="ADAPTER_REQUEST_FAILED",
        event_id=f"evt_mvp3_adapter_request_failed_{index:03d}",
        source_module="adapter_runtime",
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=10 + index,
        created_wall_clock_ms=1700000000010 + index,
        trace_redaction_level="metadata_only",
        adapter_id="mvp3_asr",
        adapter_type="asr",
        adapter_request_id=f"adapter_request_mvp3_asr_{index:03d}",
        failure_reason="synthetic_callback_failure",
        retryable=False,
        output_mode="real",
    )


def test_adapter_callback_boundary_serializes_concurrent_appends_per_session() -> None:
    journal = make_started_journal()
    root_event_id = str(journal.events()[0]["event_id"])
    boundary = AdapterCallbackAppendBoundary(journal)

    with ThreadPoolExecutor(max_workers=4) as pool:
        appended = list(
            pool.map(
                lambda index: append_adapter_failure(
                    boundary,
                    index=index,
                    caused_by_event_id=root_event_id,
                ),
                range(20),
            )
        )

    adapter_events = [
        event for event in journal.events() if event["event_name"] == "ADAPTER_REQUEST_FAILED"
    ]

    assert len(appended) == 20
    assert len(adapter_events) == 20
    assert sorted(event["event_seq"] for event in adapter_events) == list(range(2, 22))
    assert sorted(event["adapter_callback_seq"] for event in adapter_events) == list(range(1, 21))
    assert all(event["caused_by_event_id"] == root_event_id for event in adapter_events)


def test_adapter_callback_boundary_owns_callback_sequence_metadata() -> None:
    boundary = AdapterCallbackAppendBoundary(make_started_journal())

    with pytest.raises(AdapterCallbackBoundaryError, match="adapter_callback_seq"):
        boundary.append_adapter_event(
            event_name="ADAPTER_REQUEST_FAILED",
            event_id="evt_mvp3_adapter_request_failed_with_supplied_seq",
            source_module="adapter_runtime",
            caused_by_event_id="evt_mvp3_callback_boundary_session_started",
            created_monotonic_ms=10,
            created_wall_clock_ms=1700000000010,
            trace_redaction_level="metadata_only",
            adapter_id="mvp3_asr",
            adapter_type="asr",
            adapter_request_id="adapter_request_mvp3_asr_supplied_seq",
            failure_reason="synthetic_callback_failure",
            retryable=False,
            output_mode="real",
            adapter_callback_seq=99,
        )
