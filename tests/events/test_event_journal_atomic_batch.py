from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from voice_agent.events import journal as journal_module
from voice_agent.events.envelope import EventValidationError
from voice_agent.privacy.redaction import (
    PayloadBlockedError,
    REDACTED_SECRET_VALUE,
)


InMemoryEventJournal = journal_module.InMemoryEventJournal


SESSION_ID = "sess_atomic_batch_synthetic_001"
CONVERSATION_ID = "conv_atomic_batch_synthetic_001"


def make_journal() -> InMemoryEventJournal:
    return InMemoryEventJournal(
        session_id=SESSION_ID,
        conversation_id=CONVERSATION_ID,
    )


def session_started_request(
    *,
    event_id: str = "evt_atomic_session_started_001",
    **fields: object,
) -> journal_module.JournalAppendRequest:
    event_fields: dict[str, object] = {
        "runtime_config_ref": "config://synthetic/atomic/default",
        "capability_snapshot_ref": "capability://synthetic/atomic/pending",
    }
    event_fields.update(fields)
    return journal_module.JournalAppendRequest(
        event_name="SESSION_STARTED",
        event_id=event_id,
        source_module="session_runtime",
        created_monotonic_ms=10,
        created_wall_clock_ms=1_700_000_000_010,
        trace_redaction_level="metadata_only",
        fields=event_fields,
    )


def capability_snapshot_request(
    *,
    event_id: str = "evt_atomic_capability_snapshot_001",
    caused_by_event_id: str = "evt_atomic_session_started_001",
    **fields: object,
) -> journal_module.JournalAppendRequest:
    event_fields: dict[str, object] = {
        "capability_snapshot_ref": "capability://synthetic/atomic/snapshot-001",
        "adapter_ids": ["mock_asr", "mock_thinker"],
        "adapter_types": ["asr", "thinker"],
        "deployment_modes": ["mock", "mock"],
        "output_modes": ["mock", "mock"],
    }
    event_fields.update(fields)
    return journal_module.JournalAppendRequest(
        event_name="ADAPTER_CAPABILITY_SNAPSHOT_RECORDED",
        event_id=event_id,
        source_module="adapter_registry",
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=20,
        created_wall_clock_ms=1_700_000_000_020,
        trace_redaction_level="metadata_only",
        fields=event_fields,
    )


def playback_started_request(
    *,
    event_id: str,
    caused_by_event_id: str,
    playback_span_id: str,
) -> journal_module.JournalAppendRequest:
    return journal_module.JournalAppendRequest(
        event_name="PLAYBACK_SPAN_STARTED",
        event_id=event_id,
        source_module="mock_talker",
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=30,
        created_wall_clock_ms=1_700_000_000_030,
        trace_redaction_level="metadata_only",
        fields={
            "playback_span_id": playback_span_id,
            "audio_ref": f"audio://synthetic/atomic/{event_id}",
        },
    )


def healthcheck_failed_request(
    *,
    event_id: str,
    caused_by_event_id: str,
) -> journal_module.JournalAppendRequest:
    return journal_module.JournalAppendRequest(
        event_name="ADAPTER_HEALTHCHECK_FAILED",
        event_id=event_id,
        source_module="adapter_registry",
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=40,
        created_wall_clock_ms=1_700_000_000_040,
        trace_redaction_level="metadata_only",
        fields={
            "adapter_id": "mock_asr",
            "adapter_type": "asr",
            "health_status": "failed",
            "failure_reason": "synthetic_failure",
            "output_mode": "mock",
        },
    )


def test_journal_append_request_is_frozen_and_slotted() -> None:
    request = session_started_request()

    with pytest.raises(FrozenInstanceError):
        request.event_id = "evt_mutated"  # type: ignore[misc]

    assert not hasattr(request, "__dict__")


def test_atomic_batch_assigns_consecutive_sequences_and_resolves_earlier_cause() -> None:
    journal = make_journal()

    appended = journal.append_atomic_batch(
        (
            session_started_request(),
            capability_snapshot_request(),
        )
    )

    assert isinstance(appended, tuple)
    assert [event["event_seq"] for event in appended] == [1, 2]
    assert appended[1]["caused_by_event_id"] == appended[0]["event_id"]
    assert journal.events() == list(appended)


def test_atomic_batch_rolls_back_first_event_when_second_envelope_is_malformed() -> None:
    journal = make_journal()

    with pytest.raises(EventValidationError, match="adapter_ids"):
        journal.append_atomic_batch(
            (
                session_started_request(),
                capability_snapshot_request(adapter_ids=None),
            )
        )

    assert journal.events() == []
    reused = journal.append(
        event_name="SESSION_STARTED",
        event_id="evt_atomic_session_started_001",
        source_module="session_runtime",
        created_monotonic_ms=30,
        created_wall_clock_ms=1_700_000_000_030,
        trace_redaction_level="metadata_only",
        runtime_config_ref="config://synthetic/atomic/reused-after-rollback",
        capability_snapshot_ref="capability://synthetic/atomic/reused-after-rollback",
    )
    assert reused["event_seq"] == 1


def test_atomic_batch_rejects_duplicate_request_ids_without_consuming_state() -> None:
    journal = make_journal()

    with pytest.raises(ValueError, match="Duplicate event_id"):
        journal.append_atomic_batch(
            (
                session_started_request(),
                capability_snapshot_request(
                    event_id="evt_atomic_session_started_001",
                ),
            )
        )

    assert journal.events() == []
    reused = journal.append_atomic_batch((session_started_request(),))
    assert reused[0]["event_seq"] == 1


def test_atomic_batch_rejects_id_already_committed_before_batch() -> None:
    journal = make_journal()
    root = journal.append_atomic_batch((session_started_request(),))[0]

    with pytest.raises(ValueError, match="Duplicate event_id"):
        journal.append_atomic_batch(
            (
                capability_snapshot_request(
                    event_id=str(root["event_id"]),
                    caused_by_event_id=str(root["event_id"]),
                ),
            )
        )

    assert [event["event_id"] for event in journal.events()] == [root["event_id"]]
    appended = journal.append_atomic_batch(
        (
            capability_snapshot_request(
                event_id="evt_atomic_capability_after_duplicate",
                caused_by_event_id=str(root["event_id"]),
            ),
        )
    )
    assert appended[0]["event_seq"] == 2


def test_atomic_batch_rejects_forward_causal_reference() -> None:
    journal = make_journal()

    with pytest.raises(ValueError, match="caused_by_event_id"):
        journal.append_atomic_batch(
            (
                capability_snapshot_request(
                    caused_by_event_id="evt_atomic_session_started_later",
                ),
                session_started_request(
                    event_id="evt_atomic_session_started_later",
                ),
            )
        )

    assert journal.events() == []


def test_atomic_batch_accepts_earlier_supersedes_reference() -> None:
    journal = make_journal()
    request = capability_snapshot_request()
    request = journal_module.JournalAppendRequest(
        event_name=request.event_name,
        event_id=request.event_id,
        source_module=request.source_module,
        created_monotonic_ms=request.created_monotonic_ms,
        created_wall_clock_ms=request.created_wall_clock_ms,
        trace_redaction_level=request.trace_redaction_level,
        caused_by_event_id=request.caused_by_event_id,
        supersedes_event_id="evt_atomic_session_started_001",
        fields=request.fields,
    )

    appended = journal.append_atomic_batch((session_started_request(), request))

    assert appended[1]["supersedes_event_id"] == appended[0]["event_id"]


def test_atomic_batch_rejects_missing_supersedes_reference() -> None:
    journal = make_journal()
    request = capability_snapshot_request()
    request = journal_module.JournalAppendRequest(
        event_name=request.event_name,
        event_id=request.event_id,
        source_module=request.source_module,
        created_monotonic_ms=request.created_monotonic_ms,
        created_wall_clock_ms=request.created_wall_clock_ms,
        trace_redaction_level=request.trace_redaction_level,
        caused_by_event_id=request.caused_by_event_id,
        supersedes_event_id="evt_atomic_missing_superseded",
        fields=request.fields,
    )

    with pytest.raises(ValueError, match="supersedes_event_id"):
        journal.append_atomic_batch((session_started_request(), request))

    assert journal.events() == []


def test_atomic_batch_rejects_duplicate_playback_span_within_batch() -> None:
    journal = make_journal()

    with pytest.raises(ValueError, match="unique playback_span_id"):
        journal.append_atomic_batch(
            (
                session_started_request(),
                playback_started_request(
                    event_id="evt_atomic_playback_started_001",
                    caused_by_event_id="evt_atomic_session_started_001",
                    playback_span_id="playback_atomic_001",
                ),
                playback_started_request(
                    event_id="evt_atomic_playback_started_002",
                    caused_by_event_id="evt_atomic_session_started_001",
                    playback_span_id="playback_atomic_001",
                ),
            )
        )

    assert journal.events() == []


def test_atomic_batch_rejects_playback_span_committed_before_batch() -> None:
    journal = make_journal()
    root = journal.append_atomic_batch((session_started_request(),))[0]
    existing = journal.append(
        event_name="PLAYBACK_SPAN_STARTED",
        event_id="evt_atomic_playback_started_existing",
        source_module="mock_talker",
        caused_by_event_id=str(root["event_id"]),
        created_monotonic_ms=30,
        created_wall_clock_ms=1_700_000_000_030,
        trace_redaction_level="metadata_only",
        playback_span_id="playback_atomic_existing",
        audio_ref="audio://synthetic/atomic/existing",
    )

    with pytest.raises(ValueError, match="unique playback_span_id"):
        journal.append_atomic_batch(
            (
                playback_started_request(
                    event_id="evt_atomic_playback_started_duplicate",
                    caused_by_event_id=str(root["event_id"]),
                    playback_span_id=str(existing["playback_span_id"]),
                ),
            )
        )

    assert [event["event_id"] for event in journal.events()] == [
        root["event_id"],
        existing["event_id"],
    ]


def test_atomic_batch_stages_redaction_audit_but_returns_only_requested_events() -> None:
    journal = make_journal()

    appended = journal.append_atomic_batch(
        (
            session_started_request(),
            capability_snapshot_request(api_key="sk-synthetic-secret"),
        )
    )

    assert len(appended) == 2
    assert appended[1]["api_key"] == REDACTED_SECRET_VALUE
    assert appended[1]["redaction_metadata"] == {
        "redacted_fields": ["api_key"],
        "redaction_reason": "secret-like payload field",
    }
    events = journal.events()
    assert [event["event_name"] for event in events] == [
        "SESSION_STARTED",
        "ADAPTER_CAPABILITY_SNAPSHOT_RECORDED",
        "TRACE_SECRET_REDACTION_APPLIED",
    ]
    assert [event["event_seq"] for event in events] == [1, 2, 3]
    assert events[2]["event_id"] == "evt_trace_redaction_applied_00000003"
    assert events[2]["caused_by_event_id"] == appended[1]["event_id"]
    assert events[2]["payload_ref"] == (
        "payload://redacted/evt_atomic_capability_snapshot_001"
    )
    assert events[2]["redacted_fields"] == ["api_key"]


def test_atomic_batch_redaction_audit_id_avoids_later_request_id() -> None:
    journal = make_journal()
    reserved_audit_id = "evt_trace_redaction_applied_00000003"

    appended = journal.append_atomic_batch(
        (
            session_started_request(),
            capability_snapshot_request(api_key="sk-synthetic-secret"),
            healthcheck_failed_request(
                event_id=reserved_audit_id,
                caused_by_event_id="evt_atomic_capability_snapshot_001",
            ),
        )
    )

    assert [event["event_id"] for event in appended] == [
        "evt_atomic_session_started_001",
        "evt_atomic_capability_snapshot_001",
        reserved_audit_id,
    ]
    events = journal.events()
    assert [event["event_seq"] for event in events] == [1, 2, 3, 4]
    assert events[2]["event_name"] == "TRACE_SECRET_REDACTION_APPLIED"
    assert events[2]["event_id"] == "evt_trace_redaction_applied_00000003_1"
    assert events[3]["event_id"] == reserved_audit_id
    assert len({str(event["event_id"]) for event in events}) == len(events)


def test_atomic_batch_deepcopies_request_fields_storage_and_return_values() -> None:
    journal = make_journal()
    mutable_adapter_ids = ["mock_asr", "mock_thinker"]
    request = capability_snapshot_request(adapter_ids=mutable_adapter_ids)

    appended = journal.append_atomic_batch((session_started_request(), request))

    mutable_adapter_ids.append("mutated_input")
    appended[1]["adapter_ids"].append("mutated_return")
    assert journal.events()[1]["adapter_ids"] == ["mock_asr", "mock_thinker"]


def test_atomic_empty_batch_does_not_consume_sequence() -> None:
    journal = make_journal()

    assert journal.append_atomic_batch(()) == ()
    appended = journal.append_atomic_batch((session_started_request(),))

    assert appended[0]["event_seq"] == 1


def test_atomic_batch_later_blocked_secret_rolls_back_staged_main_and_audit() -> None:
    journal = make_journal()
    staged_event_id = "evt_trace_write_blocked_00000001"

    with pytest.raises(PayloadBlockedError):
        journal.append_atomic_batch(
            (
                session_started_request(
                    event_id=staged_event_id,
                    api_key="sk-synthetic-secret",
                ),
                capability_snapshot_request(
                    caused_by_event_id=staged_event_id,
                    notes="Bearer synthetic-token",
                ),
            )
        )

    events = journal.events()
    assert [event["event_name"] for event in events] == [
        "TRACE_WRITE_BLOCKED_SECRET_DETECTED",
    ]
    assert events[0]["event_id"] == "evt_trace_write_blocked_00000001_1"
    assert events[0]["event_seq"] == 1
    assert events[0]["blocked_payload_ref"] == "payload://blocked/00000001"
    assert "caused_by_event_id" not in events[0]
    assert "Bearer synthetic-token" not in repr(events)
    assert "SESSION_STARTED" not in repr(events)
    reused = journal.append_atomic_batch(
        (
            session_started_request(event_id=staged_event_id),
        )
    )
    assert reused[0]["event_seq"] == 2


def test_atomic_batch_blocked_audit_preserves_only_prebatch_causal_reference() -> None:
    journal = make_journal()
    root = journal.append_atomic_batch((session_started_request(),))[0]

    with pytest.raises(PayloadBlockedError):
        journal.append_atomic_batch(
            (
                healthcheck_failed_request(
                    event_id="evt_atomic_healthcheck_rolled_back",
                    caused_by_event_id=str(root["event_id"]),
                ),
                capability_snapshot_request(
                    event_id="evt_atomic_capability_blocked",
                    caused_by_event_id=str(root["event_id"]),
                    notes="Bearer synthetic-token",
                ),
            )
        )

    events = journal.events()
    assert [event["event_name"] for event in events] == [
        "SESSION_STARTED",
        "TRACE_WRITE_BLOCKED_SECRET_DETECTED",
    ]
    assert events[1]["event_seq"] == 2
    assert events[1]["event_id"] == "evt_trace_write_blocked_00000002"
    assert events[1]["caused_by_event_id"] == root["event_id"]
    assert "evt_atomic_healthcheck_rolled_back" not in {
        str(event["event_id"]) for event in events
    }


@pytest.mark.parametrize(
    ("owned_field", "owned_value"),
    [
        ("event_name", "ADAPTER_HEALTHCHECK_FAILED"),
        ("event_id", "evt_atomic_overridden"),
        ("event_seq", 99),
        ("event_schema_version", "9.9"),
        ("session_id", "sess_atomic_overridden"),
        ("conversation_id", "conv_atomic_overridden"),
        ("source_module", "overridden_module"),
        ("created_monotonic_ms", 999),
        ("created_wall_clock_ms", 999),
        ("trace_redaction_level", "local_debug"),
        ("caused_by_event_id", "evt_atomic_overridden"),
        ("supersedes_event_id", "evt_atomic_overridden"),
    ],
)
def test_atomic_batch_rejects_fields_owned_by_journal_append_request(
    owned_field: str,
    owned_value: object,
) -> None:
    journal = make_journal()
    base_request = session_started_request()
    request = journal_module.JournalAppendRequest(
        event_name=base_request.event_name,
        event_id=base_request.event_id,
        source_module=base_request.source_module,
        created_monotonic_ms=base_request.created_monotonic_ms,
        created_wall_clock_ms=base_request.created_wall_clock_ms,
        trace_redaction_level=base_request.trace_redaction_level,
        caused_by_event_id=base_request.caused_by_event_id,
        supersedes_event_id=base_request.supersedes_event_id,
        fields={**base_request.fields, owned_field: owned_value},
    )

    with pytest.raises(ValueError, match=owned_field):
        journal.append_atomic_batch((request,))

    assert journal.events() == []


def test_atomic_batch_validator_fault_on_second_staged_envelope_leaves_state_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = make_journal()
    original_validator = journal_module.validate_event_envelope

    def fail_on_second_staged_envelope(event: dict[str, object]) -> dict[str, object]:
        if event.get("event_id") == "evt_atomic_capability_snapshot_001":
            raise RuntimeError("injected validator fault")
        return original_validator(event)

    with monkeypatch.context() as patch:
        patch.setattr(
            journal_module,
            "validate_event_envelope",
            fail_on_second_staged_envelope,
        )
        with pytest.raises(RuntimeError, match="injected validator fault"):
            journal.append_atomic_batch(
                (
                    session_started_request(),
                    capability_snapshot_request(),
                )
            )

    assert journal.events() == []
    reused = journal.append(
        event_name="SESSION_STARTED",
        event_id="evt_atomic_session_started_001",
        source_module="session_runtime",
        created_monotonic_ms=40,
        created_wall_clock_ms=1_700_000_000_040,
        trace_redaction_level="metadata_only",
        runtime_config_ref="config://synthetic/atomic/reused-after-fault",
        capability_snapshot_ref="capability://synthetic/atomic/reused-after-fault",
    )
    assert reused["event_seq"] == 1
