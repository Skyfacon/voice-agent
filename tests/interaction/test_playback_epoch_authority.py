from __future__ import annotations

import pytest

from voice_agent.events.journal import InMemoryEventJournal
from voice_agent.interaction.controller import InteractionController


def _journal() -> InMemoryEventJournal:
    return InMemoryEventJournal(
        session_id="sess_epoch_authority_synthetic",
        conversation_id="conv_epoch_authority_synthetic",
    )


def test_only_controller_advances_provider_rebuild_epoch_and_version() -> None:
    controller = InteractionController(_journal())

    initial = controller.current_epoch_snapshot()
    advanced = controller.advance_playback_epoch_for_provider_rebuild(
        provider_session_generation=2,
        reason="synthetic_rebuild",
    )

    assert initial.playback_epoch == 0
    assert initial.interaction_state_version == 0
    assert advanced.playback_epoch == 1
    assert advanced.interaction_state_version == 1
    assert controller.current_epoch_snapshot() == advanced


def test_provider_cancel_does_not_advance_controller_epoch() -> None:
    controller = InteractionController(_journal())

    before = controller.current_epoch_snapshot()
    after = controller.current_epoch_snapshot()

    assert after == before


def test_rejected_barge_in_does_not_consume_epoch() -> None:
    controller = InteractionController(_journal())

    with pytest.raises(ValueError, match="appended BARGE_IN_CANDIDATE"):
        controller.request_truncate_for_barge_in(
            {
                "event_name": "BARGE_IN_CANDIDATE",
                "event_id": "evt_barge_invalid",
                "audio_span_id": "audio_epoch_synthetic",
                "playback_span_id": "playback_not_active",
                "playback_offset_ms": 0,
                "echo_likelihood": "low",
                "vad_confidence": 0.9,
                "barge_in_confidence": 0.9,
            },
            interrupt_event_id="evt_interrupt_invalid",
            truncate_request_event_id="evt_truncate_invalid",
            created_monotonic_ms=1,
            created_wall_clock_ms=1_700_000_000_001,
            cutoff_playback_offset_ms=0,
        )

    assert controller.current_epoch_snapshot().playback_epoch == 0
    assert controller.current_epoch_snapshot().interaction_state_version == 0


def _active_barge_in_candidate(
    journal: InMemoryEventJournal,
) -> dict[str, object]:
    session_started = journal.append(
        event_name="SESSION_STARTED",
        event_id="evt_epoch_authority_session_started",
        source_module="session_runtime",
        created_monotonic_ms=0,
        created_wall_clock_ms=1_700_000_000_000,
        trace_redaction_level="metadata_only",
        runtime_config_ref="config://synthetic/slice3b1/epoch-authority",
        capability_snapshot_ref="capability://synthetic/slice3b1/epoch-authority",
    )
    playback_started = journal.append(
        event_name="PLAYBACK_SPAN_STARTED",
        event_id="evt_epoch_authority_playback_started",
        source_module="mock_talker",
        caused_by_event_id=str(session_started["event_id"]),
        created_monotonic_ms=10,
        created_wall_clock_ms=1_700_000_000_010,
        trace_redaction_level="metadata_only",
        playback_span_id="playback_epoch_authority_001",
        audio_ref="audio://synthetic/slice3b1/epoch-authority",
    )
    return journal.append(
        event_name="BARGE_IN_CANDIDATE",
        event_id="evt_epoch_authority_barge_candidate",
        source_module="mock_duplex",
        caused_by_event_id=str(playback_started["event_id"]),
        created_monotonic_ms=20,
        created_wall_clock_ms=1_700_000_000_020,
        trace_redaction_level="metadata_only",
        audio_span_id="audio_epoch_authority_001",
        playback_span_id="playback_epoch_authority_001",
        playback_offset_ms=10,
        echo_likelihood="low",
        vad_confidence=0.96,
        barge_in_confidence=0.94,
    )


@pytest.mark.parametrize(
    ("mutation", "error_match"),
    (
        ("unjournaled_candidate", "appended BARGE_IN_CANDIDATE"),
        ("duplicate_interrupt_id", "interrupt_event_id"),
        ("duplicate_output_ids", "distinct"),
        ("invalid_monotonic_timestamp", "created_monotonic_ms"),
        ("invalid_wall_timestamp", "created_wall_clock_ms"),
    ),
)
def test_expected_barge_in_append_failures_do_not_advance_epoch(
    mutation: str,
    error_match: str,
) -> None:
    journal = _journal()
    candidate = _active_barge_in_candidate(journal)
    controller = InteractionController(journal)
    before_epoch = controller.current_epoch_snapshot()
    before_events = journal.events()
    interrupt_event_id = "evt_epoch_authority_interrupt_candidate"
    truncate_request_event_id = "evt_epoch_authority_truncate_requested"
    created_monotonic_ms: object = 30
    created_wall_clock_ms: object = 1_700_000_000_030

    if mutation == "unjournaled_candidate":
        candidate = dict(candidate)
        candidate["event_id"] = "evt_unjournaled_barge_candidate"
    elif mutation == "duplicate_interrupt_id":
        interrupt_event_id = str(candidate["event_id"])
    elif mutation == "duplicate_output_ids":
        truncate_request_event_id = interrupt_event_id
    elif mutation == "invalid_monotonic_timestamp":
        created_monotonic_ms = -1
    elif mutation == "invalid_wall_timestamp":
        created_wall_clock_ms = True

    with pytest.raises(ValueError, match=error_match):
        controller.request_truncate_for_barge_in(
            candidate,
            interrupt_event_id=interrupt_event_id,
            truncate_request_event_id=truncate_request_event_id,
            created_monotonic_ms=created_monotonic_ms,  # type: ignore[arg-type]
            created_wall_clock_ms=created_wall_clock_ms,  # type: ignore[arg-type]
            cutoff_playback_offset_ms=20,
        )

    assert controller.current_epoch_snapshot() == before_epoch
    assert journal.events() == before_events
