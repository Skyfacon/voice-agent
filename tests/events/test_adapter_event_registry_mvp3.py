from __future__ import annotations

from voice_agent.events.journal import InMemoryEventJournal


def make_journal() -> InMemoryEventJournal:
    journal = InMemoryEventJournal(
        session_id="sess_mvp3_adapter_events_synthetic",
        conversation_id="conv_mvp3_adapter_events_synthetic",
    )
    journal.append(
        event_name="SESSION_STARTED",
        event_id="evt_mvp3_adapter_events_session_started",
        source_module="session_runtime",
        created_monotonic_ms=1,
        created_wall_clock_ms=1700000000001,
        trace_redaction_level="metadata_only",
        runtime_config_ref="config://synthetic/mvp3/adapter-events",
        capability_snapshot_ref="capability://synthetic/mvp3/adapter-events",
    )
    return journal


def test_adapter_health_and_error_events_are_registered_and_appendable() -> None:
    journal = make_journal()
    root_event_id = str(journal.events()[0]["event_id"])

    health_failed = journal.append(
        event_name="ADAPTER_HEALTHCHECK_FAILED",
        event_id="evt_mvp3_adapter_healthcheck_failed",
        source_module="adapter_runtime",
        caused_by_event_id=root_event_id,
        created_monotonic_ms=2,
        created_wall_clock_ms=1700000000002,
        trace_redaction_level="metadata_only",
        adapter_id="mvp3_asr",
        adapter_type="asr",
        health_status="unhealthy",
        failure_reason="synthetic_healthcheck_failure",
        output_mode="real",
    )
    retrying = journal.append(
        event_name="ADAPTER_REQUEST_RETRYING",
        event_id="evt_mvp3_adapter_request_retrying",
        source_module="adapter_runtime",
        caused_by_event_id=str(health_failed["event_id"]),
        created_monotonic_ms=3,
        created_wall_clock_ms=1700000000003,
        trace_redaction_level="metadata_only",
        adapter_id="mvp3_asr",
        adapter_type="asr",
        adapter_request_id="adapter_request_mvp3_asr_001",
        retry_count=1,
        retry_reason="synthetic_retryable_timeout",
        timeout_ms=500,
    )
    failed = journal.append(
        event_name="ADAPTER_REQUEST_FAILED",
        event_id="evt_mvp3_adapter_request_failed",
        source_module="adapter_runtime",
        caused_by_event_id=str(retrying["event_id"]),
        created_monotonic_ms=4,
        created_wall_clock_ms=1700000000004,
        trace_redaction_level="metadata_only",
        adapter_id="mvp3_asr",
        adapter_type="asr",
        adapter_request_id="adapter_request_mvp3_asr_001",
        failure_reason="synthetic_final_failure",
        retryable=False,
        output_mode="real",
    )
    validation_failed = journal.append(
        event_name="ADAPTER_OUTPUT_VALIDATION_FAILED",
        event_id="evt_mvp3_adapter_output_validation_failed",
        source_module="adapter_runtime",
        caused_by_event_id=str(failed["event_id"]),
        created_monotonic_ms=5,
        created_wall_clock_ms=1700000000005,
        trace_redaction_level="metadata_only",
        adapter_id="mvp3_slow_llm",
        adapter_type="slow_llm",
        adapter_request_id="adapter_request_mvp3_slow_llm_001",
        schema_name="SlowTaskPlan",
        failure_reasons=["missing_required_field"],
        output_mode="real",
    )
    degraded = journal.append(
        event_name="ADAPTER_OUTPUT_DEGRADED",
        event_id="evt_mvp3_adapter_output_degraded",
        source_module="adapter_runtime",
        caused_by_event_id=str(validation_failed["event_id"]),
        created_monotonic_ms=6,
        created_wall_clock_ms=1700000000006,
        trace_redaction_level="metadata_only",
        adapter_id="mvp3_tts",
        adapter_type="tts",
        adapter_request_id="adapter_request_mvp3_tts_001",
        degraded_reason="missing_tts_truncate",
        missing_capability="supports_tts_truncate",
        fallback_adapter_id="mock_talker",
        output_mode="degraded",
    )

    assert [event["event_seq"] for event in journal.events()] == [1, 2, 3, 4, 5, 6]
    assert degraded["output_mode"] == "degraded"
