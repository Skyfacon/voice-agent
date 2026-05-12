from __future__ import annotations

import pytest

from voice_agent.events.journal import InMemoryEventJournal
from voice_agent.privacy.redaction import PayloadBlockedError, REDACTED_SECRET_VALUE


def make_journal() -> InMemoryEventJournal:
    return InMemoryEventJournal(
        session_id="sess_mvp0_synthetic_001",
        conversation_id="conv_mvp0_synthetic_001",
    )


def append_session_started(journal: InMemoryEventJournal, **fields: object) -> dict[str, object]:
    event_fields: dict[str, object] = {
        "event_name": "SESSION_STARTED",
        "event_id": "evt_mvp0_session_started_001",
        "source_module": "session_runtime",
        "created_monotonic_ms": 10,
        "created_wall_clock_ms": 1700000000010,
        "trace_redaction_level": "metadata_only",
        "runtime_config_ref": "config://synthetic/mvp0/default",
        "capability_snapshot_ref": "capability://synthetic/mvp0/not-recorded-yet",
    }
    event_fields.update(fields)
    return journal.append(**event_fields)


def append_capability_snapshot(
    journal: InMemoryEventJournal,
    caused_by_event_id: str,
    **fields: object,
) -> dict[str, object]:
    event_fields: dict[str, object] = {
        "event_name": "ADAPTER_CAPABILITY_SNAPSHOT_RECORDED",
        "event_id": "evt_mvp0_capability_snapshot_001",
        "source_module": "adapter_registry",
        "caused_by_event_id": caused_by_event_id,
        "created_monotonic_ms": 5,
        "created_wall_clock_ms": 1700000000005,
        "trace_redaction_level": "metadata_only",
        "capability_snapshot_ref": "capability://synthetic/mvp0/snapshot-001",
        "adapter_ids": ["mock_asr", "mock_thinker", "mock_talker"],
        "adapter_types": ["asr", "thinker", "tts"],
        "deployment_modes": ["mock", "mock", "mock"],
        "output_modes": ["mock", "mock", "mock"],
    }
    event_fields.update(fields)
    return journal.append(**event_fields)


def append_playback_span_started(
    journal: InMemoryEventJournal,
    caused_by_event_id: str,
    **fields: object,
) -> dict[str, object]:
    event_fields: dict[str, object] = {
        "event_name": "PLAYBACK_SPAN_STARTED",
        "event_id": "evt_mvp0_playback_started_001",
        "source_module": "mock_talker",
        "caused_by_event_id": caused_by_event_id,
        "created_monotonic_ms": 20,
        "created_wall_clock_ms": 1700000000020,
        "trace_redaction_level": "metadata_only",
        "playback_span_id": "playback_mvp0_001",
        "audio_ref": "audio://synthetic/mvp0/mock-playback-001",
    }
    event_fields.update(fields)
    return journal.append(**event_fields)


def append_confirmation_accepted(
    journal: InMemoryEventJournal,
    caused_by_event_id: str,
    **fields: object,
) -> dict[str, object]:
    event_fields: dict[str, object] = {
        "event_name": "CONFIRMATION_ACCEPTED",
        "event_id": "evt_mvp1_confirmation_accepted_001",
        "source_module": "slowtask_runtime",
        "caused_by_event_id": caused_by_event_id,
        "created_monotonic_ms": 30,
        "created_wall_clock_ms": 1700000000030,
        "trace_redaction_level": "metadata_only",
        "confirmation_id": "confirmation_mvp1_synthetic_001",
        "task_id": "task_mvp1_synthetic_001",
        "plan_version": 1,
        "task_event_seq": 4,
        "accepted_scope": "TASK_CANCEL",
        "authorization_ref": "authorization://synthetic/mvp1/current-plan-confirmation",
    }
    event_fields.update(fields)
    return journal.append(**event_fields)


def test_journal_allocates_strictly_increasing_event_seq_per_session() -> None:
    journal = make_journal()

    first = append_session_started(journal)
    second = append_capability_snapshot(journal, caused_by_event_id=str(first["event_id"]))

    assert first["event_seq"] == 1
    assert second["event_seq"] == 2
    assert [event["event_seq"] for event in journal.events()] == [1, 2]


def test_journal_rejects_duplicate_event_id() -> None:
    journal = make_journal()
    append_session_started(journal, event_id="evt_duplicate")

    with pytest.raises(ValueError, match="event_id"):
        append_capability_snapshot(
            journal,
            caused_by_event_id="evt_duplicate",
            event_id="evt_duplicate",
        )

    assert [event["event_id"] for event in journal.events()] == ["evt_duplicate"]


def test_journal_rejects_duplicate_playback_span_id() -> None:
    journal = make_journal()
    first = append_session_started(journal)
    append_playback_span_started(journal, caused_by_event_id=str(first["event_id"]))

    with pytest.raises(ValueError, match="unique playback_span_id"):
        append_playback_span_started(
            journal,
            caused_by_event_id=str(first["event_id"]),
            event_id="evt_mvp0_playback_started_duplicate_span",
            playback_span_id="playback_mvp0_001",
            audio_ref="audio://synthetic/mvp0/mock-playback-duplicate-span",
        )

    assert [
        event["event_id"]
        for event in journal.events()
        if event["event_name"] == "PLAYBACK_SPAN_STARTED"
    ] == ["evt_mvp0_playback_started_001"]


def test_journal_rejects_causal_link_to_missing_event() -> None:
    journal = make_journal()

    with pytest.raises(ValueError, match="caused_by_event_id"):
        append_capability_snapshot(journal, caused_by_event_id="evt_missing")

    assert journal.events() == []


def test_journal_does_not_reorder_by_wall_clock_or_monotonic_time() -> None:
    journal = make_journal()

    first = append_session_started(journal, created_monotonic_ms=100, created_wall_clock_ms=2000)
    second = append_capability_snapshot(
        journal,
        caused_by_event_id=str(first["event_id"]),
        created_monotonic_ms=50,
        created_wall_clock_ms=1000,
    )

    assert [event["event_id"] for event in journal.events()] == [
        first["event_id"],
        second["event_id"],
    ]
    assert second["event_seq"] > first["event_seq"]


def test_journal_event_seq_is_session_local() -> None:
    first_journal = make_journal()
    second_journal = InMemoryEventJournal(
        session_id="sess_mvp0_synthetic_002",
        conversation_id="conv_mvp0_synthetic_002",
    )

    assert append_session_started(first_journal)["event_seq"] == 1
    assert append_session_started(second_journal, event_id="evt_mvp0_session_started_002")["event_seq"] == 1


def test_journal_is_append_only_from_callers_perspective() -> None:
    journal = make_journal()
    event = append_session_started(journal)

    event["event_seq"] = 999
    returned_events = journal.events()
    returned_events[0]["event_seq"] = 777

    assert journal.events()[0]["event_seq"] == 1


def test_journal_rejects_caller_supplied_event_seq() -> None:
    journal = make_journal()

    with pytest.raises(ValueError, match="event_seq"):
        append_session_started(journal, event_seq=10)


def test_journal_redacts_secret_like_payload_fields_before_append() -> None:
    journal = make_journal()

    event = append_session_started(
        journal,
        api_key="sk-synthetic-secret",
        secret_key="plain-secret",
    )

    assert event["api_key"] == REDACTED_SECRET_VALUE
    assert event["secret_key"] == REDACTED_SECRET_VALUE
    assert event["redaction_metadata"] == {
        "redacted_fields": ["api_key", "secret_key"],
        "redaction_reason": "secret-like payload field",
    }
    assert journal.events()[0]["api_key"] == REDACTED_SECRET_VALUE
    assert "sk-synthetic-secret" not in repr(journal.events()[0])
    assert journal.events()[1]["event_name"] == "TRACE_SECRET_REDACTION_APPLIED"
    assert journal.events()[1]["caused_by_event_id"] == event["event_id"]
    assert journal.events()[1]["payload_ref"] == "payload://redacted/evt_mvp0_session_started_001"
    assert journal.events()[1]["redacted_fields"] == ["api_key", "secret_key"]


def test_journal_preserves_safe_authorization_ref_without_redaction_audit() -> None:
    journal = make_journal()
    root_event = append_session_started(journal)

    event = append_confirmation_accepted(journal, caused_by_event_id=str(root_event["event_id"]))

    assert event["authorization_ref"] == "authorization://synthetic/mvp1/current-plan-confirmation"
    assert "redaction_metadata" not in event
    assert [journal_event["event_name"] for journal_event in journal.events()] == [
        "SESSION_STARTED",
        "CONFIRMATION_ACCEPTED",
    ]


@pytest.mark.parametrize(
    "authorization_ref",
    [
        "authorization://sk-live-secret",
        "authorization://synthetic/mvp1/current?token=abc123",
        "authorization://synthetic/mvp1/current?access_token=abc123",
        "authorization://synthetic/mvp1/current#token=abc123",
        "authorization://synthetic/mvp1/%3Faccess_token=abc123",
        "authorization://synthetic/mvp1/%23token=abc123",
        "authorization://synthetic/mvp1/%26token=abc123",
        "authorization://synthetic/mvp1/bearer abc123",
    ],
)
def test_journal_blocks_secret_like_authorization_ref_before_append(authorization_ref: str) -> None:
    journal = make_journal()
    root_event = append_session_started(journal)

    with pytest.raises(PayloadBlockedError):
        append_confirmation_accepted(
            journal,
            caused_by_event_id=str(root_event["event_id"]),
            authorization_ref=authorization_ref,
        )

    events = journal.events()
    assert [event["event_name"] for event in events] == [
        "SESSION_STARTED",
        "TRACE_WRITE_BLOCKED_SECRET_DETECTED",
    ]
    assert authorization_ref not in repr(events)


def test_journal_redaction_audit_id_collision_does_not_make_append_partial() -> None:
    journal = make_journal()
    old_generated_audit_id = "evt_trace_redaction_applied_evt_mvp0_capability_snapshot_001"
    root_event = append_session_started(journal, event_id=old_generated_audit_id)

    event = append_capability_snapshot(
        journal,
        caused_by_event_id=str(root_event["event_id"]),
        api_key="sk-synthetic-secret",
    )

    events = journal.events()
    assert event["event_id"] == "evt_mvp0_capability_snapshot_001"
    assert [journal_event["event_name"] for journal_event in events] == [
        "SESSION_STARTED",
        "ADAPTER_CAPABILITY_SNAPSHOT_RECORDED",
        "TRACE_SECRET_REDACTION_APPLIED",
    ]
    assert events[2]["event_id"] != old_generated_audit_id
    assert events[2]["event_id"] == "evt_trace_redaction_applied_00000003"
    assert events[2]["caused_by_event_id"] == event["event_id"]
    assert events[2]["payload_ref"] == "payload://redacted/evt_mvp0_capability_snapshot_001"


def test_journal_records_blocked_secret_trace_event_for_non_root_attempt() -> None:
    journal = make_journal()
    root_event = append_session_started(journal)

    with pytest.raises(PayloadBlockedError):
        append_capability_snapshot(
            journal,
            caused_by_event_id=str(root_event["event_id"]),
            notes="Bearer synthetic-token",
        )

    events = journal.events()
    assert [event["event_name"] for event in events] == [
        "SESSION_STARTED",
        "TRACE_WRITE_BLOCKED_SECRET_DETECTED",
    ]
    assert events[1]["caused_by_event_id"] == root_event["event_id"]
    assert events[1]["source_module"] == "trace_runtime"
    assert events[1]["event_id"] == "evt_trace_write_blocked_00000002"
    assert events[1]["blocked_payload_ref"] == "payload://blocked/00000002"
    assert events[1]["secret_kind"] == "secret_like_payload"
    assert events[1]["blocking_reason"] == "blocked before journal append"


def test_journal_records_blocked_secret_trace_event_for_root_attempt() -> None:
    journal = make_journal()

    with pytest.raises(PayloadBlockedError):
        append_session_started(journal, notes="Bearer synthetic-token")

    events = journal.events()
    assert [event["event_name"] for event in events] == [
        "TRACE_WRITE_BLOCKED_SECRET_DETECTED",
    ]
    assert events[0]["event_id"] == "evt_trace_write_blocked_00000001"
    assert events[0]["event_seq"] == 1
    assert "caused_by_event_id" not in events[0]
    assert events[0]["source_module"] == "trace_runtime"
    assert events[0]["blocked_payload_ref"] == "payload://blocked/00000001"
    assert events[0]["secret_kind"] == "secret_like_payload"
    assert events[0]["blocking_reason"] == "blocked before journal append"
    assert "Bearer synthetic-token" not in repr(events)


def test_journal_blocked_secret_audit_does_not_copy_secret_like_event_metadata() -> None:
    journal = make_journal()
    root_event = append_session_started(journal)

    with pytest.raises(PayloadBlockedError):
        append_capability_snapshot(
            journal,
            caused_by_event_id=str(root_event["event_id"]),
            event_id="evt_sk-test-secret",
            source_module="Bearer synthetic-token",
        )

    events = journal.events()
    assert [event["event_name"] for event in events] == [
        "SESSION_STARTED",
        "TRACE_WRITE_BLOCKED_SECRET_DETECTED",
    ]
    assert events[1]["event_id"] == "evt_trace_write_blocked_00000002"
    assert events[1]["blocked_payload_ref"] == "payload://blocked/00000002"
    assert events[1]["blocking_reason"] == "blocked before journal append"
    assert "sk-test-secret" not in repr(events)
    assert "Bearer synthetic-token" not in repr(events)


def test_journal_blocked_secret_audit_uses_safe_schema_version_for_blocked_envelope_secret() -> None:
    journal = make_journal()
    root_event = append_session_started(journal)

    with pytest.raises(PayloadBlockedError):
        append_capability_snapshot(
            journal,
            caused_by_event_id=str(root_event["event_id"]),
            event_schema_version="Bearer synthetic-token",
        )

    events = journal.events()
    assert [event["event_name"] for event in events] == [
        "SESSION_STARTED",
        "TRACE_WRITE_BLOCKED_SECRET_DETECTED",
    ]
    assert events[1]["event_schema_version"] == "1.0"
    assert "Bearer synthetic-token" not in repr(events)


@pytest.mark.parametrize(
    "unsafe_field",
    [
        {"raw_audio_ref": "audio/raw/sess.wav"},
        {"raw_trace_payload": {"debug": "trace must stay local"}},
        {"raw_user_text": "unredacted user text"},
        {"notes": "audio/raw/sess.wav"},
        {"notes": "traces/session.jsonl"},
        {"notes": "leaked key sk-test-secret"},
        {"notes": "prefix Bearer synthetic-token"},
        {"notes": "Bearer synthetic-token"},
    ],
)
def test_journal_blocks_raw_or_unredactable_sensitive_payloads(unsafe_field: dict[str, object]) -> None:
    journal = make_journal()

    with pytest.raises(PayloadBlockedError):
        append_session_started(journal, **unsafe_field)

    events = journal.events()
    assert [event["event_name"] for event in events] == [
        "TRACE_WRITE_BLOCKED_SECRET_DETECTED",
    ]
    assert events[0]["event_id"] == "evt_trace_write_blocked_00000001"
    assert events[0]["trace_redaction_level"] == "metadata_only"
    assert "audio/raw/sess.wav" not in repr(events)
    assert "traces/session.jsonl" not in repr(events)
    assert "sk-test-secret" not in repr(events)
    assert "Bearer synthetic-token" not in repr(events)
