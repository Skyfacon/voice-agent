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

    assert journal.events() == []
