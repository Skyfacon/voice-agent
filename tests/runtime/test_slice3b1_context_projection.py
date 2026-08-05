from __future__ import annotations

from dataclasses import replace

import pytest

from voice_agent.events.journal import InMemoryEventJournal
from voice_agent.runtime.slice3b1 import context_projection as context_projection_module
from voice_agent.runtime.slice3b1.context_projection import (
    ContextProjectionError,
    ContextProjectionLimitsV1,
    ContextProjectionSourceV1,
    ROUTE_CONTEXT_POLICY_V1,
    build_context_projection,
)


def _journal() -> InMemoryEventJournal:
    journal = InMemoryEventJournal(
        session_id="sess_context_projection_synthetic",
        conversation_id="conv_context_projection_synthetic",
    )
    journal.append(
        event_name="SESSION_STARTED",
        event_id="evt_context_session_started",
        source_module="test",
        created_monotonic_ms=0,
        created_wall_clock_ms=1_700_000_000_000,
        trace_redaction_level="metadata_only",
        runtime_config_ref="config://synthetic/context-projection",
        capability_snapshot_ref="capability://synthetic/context-projection",
    )
    journal.append(
        event_name="TURN_INGRESS_COMMITTED",
        event_id="evt_context_turn_committed",
        caused_by_event_id="evt_context_session_started",
        source_module="test",
        created_monotonic_ms=1,
        created_wall_clock_ms=1_700_000_000_001,
        trace_redaction_level="metadata_only",
        turn_id="turn_context_synthetic",
        utterance_id="utt_context_synthetic",
        audio_span_id="audio_context_synthetic",
        input_modality="audio",
        directedness="ASSUMED_DIRECTED",
        semantic_close="ASSUMED_CLOSED",
        ingress_outcome="COMMITTED",
    )
    return journal


def _source() -> ContextProjectionSourceV1:
    return ContextProjectionSourceV1(
        session_id="sess_context_projection_synthetic",
        current_transcript_ref="text-ref://synthetic/asr/context-001",
        current_transcript_char_count=42,
        recent_committed_item_refs=(
            "committed-item://synthetic/one",
            "committed-item://synthetic/two",
        ),
        recent_dialogue_summary_ref="dialogue-summary://synthetic/one",
        recent_dialogue_summary_char_count=30,
        active_task_public_summary_ref="task-public-summary://synthetic/one",
        active_task_public_summary_char_count=20,
        session_memory_hint_refs=("memory-hint://synthetic/one",),
        session_memory_hint_char_count=10,
        source_event_ids=(
            "evt_context_session_started",
            "evt_context_turn_committed",
        ),
        source_event_seq=2,
        provider_session_generation=1,
        context_snapshot_id="context_snapshot_synthetic_001",
        target_role="route_evidence",
    )


def test_route_context_policy_is_frozen_at_accepted_limits() -> None:
    assert ROUTE_CONTEXT_POLICY_V1 == ContextProjectionLimitsV1(
        current_transcript_chars=2_000,
        recent_committed_items=4,
        recent_dialogue_summary_chars=2_000,
        active_task_public_summary_chars=1_000,
        session_memory_hint_count=5,
        session_memory_hint_chars=1_000,
        total_serialized_chars=8_192,
    )
    with pytest.raises(Exception):
        ROUTE_CONTEXT_POLICY_V1.current_transcript_chars = 1  # type: ignore[misc]


def test_projection_appends_safe_canonical_metadata_without_text() -> None:
    journal = _journal()
    source = _source()
    authority = _register_source_authority(journal, source)

    projection = build_context_projection(
        journal=journal,
        event_id="evt_context_projection",
        source=source,
        source_authority=authority,
        created_monotonic_ms=2,
        created_wall_clock_ms=1_700_000_000_002,
    )

    assert projection.event["event_name"] == "MODEL_CONTEXT_PROJECTION_EMITTED"
    assert projection.event["caused_by_event_id"] == "evt_context_turn_committed"
    assert projection.event["source_event_ids"] == (
        "evt_context_session_started",
        "evt_context_turn_committed",
    )
    assert projection.event["context_snapshot_id"] == "context_snapshot_synthetic_001"
    assert projection.event["source_event_seq"] == 2
    assert projection.event["provider_session_generation"] == 1
    assert projection.event["policy_version"] == "route_context.v1"
    serialized = repr(projection.event)
    assert "raw_text" not in serialized
    assert "transcript" not in projection.event
    assert "prompt" not in serialized


def test_projection_rejects_cross_session_uncommitted_or_over_bound_input() -> None:
    source = _source()
    journal = _journal()
    authority = _register_source_authority(journal, source)
    with pytest.raises(ContextProjectionError, match="session"):
        build_context_projection(
            journal=journal, event_id="evt_context_cross_session",
            source=replace(source, session_id="sess_other"),
            source_authority=authority,
            created_monotonic_ms=2, created_wall_clock_ms=1_700_000_000_002,
        )

    with pytest.raises(ContextProjectionError, match="recent_committed_item_refs"):
        ContextProjectionSourceV1(
            **{
                "session_id": source.session_id,
                "current_transcript_ref": source.current_transcript_ref,
                "current_transcript_char_count": source.current_transcript_char_count,
                "recent_committed_item_refs": tuple("committed-item://synthetic/x" for _ in range(5)),
                "recent_dialogue_summary_ref": None,
                "recent_dialogue_summary_char_count": 0,
                "active_task_public_summary_ref": None,
                "active_task_public_summary_char_count": 0,
                "session_memory_hint_refs": (),
                "session_memory_hint_char_count": 0,
                "source_event_ids": source.source_event_ids,
                "source_event_seq": source.source_event_seq,
                "provider_session_generation": source.provider_session_generation,
                "context_snapshot_id": source.context_snapshot_id,
                "target_role": source.target_role,
            }
        )


def test_projection_rejects_raw_text_and_stale_source_sequence() -> None:
    source = _source()
    with pytest.raises(ContextProjectionError, match="current_transcript_ref"):
        ContextProjectionSourceV1(
            **{
                "session_id": source.session_id,
                "current_transcript_ref": "the raw user utterance must not enter this schema",
                "current_transcript_char_count": 42,
                "recent_committed_item_refs": source.recent_committed_item_refs,
                "recent_dialogue_summary_ref": source.recent_dialogue_summary_ref,
                "recent_dialogue_summary_char_count": source.recent_dialogue_summary_char_count,
                "active_task_public_summary_ref": source.active_task_public_summary_ref,
                "active_task_public_summary_char_count": source.active_task_public_summary_char_count,
                "session_memory_hint_refs": source.session_memory_hint_refs,
                "session_memory_hint_char_count": source.session_memory_hint_char_count,
                "source_event_ids": source.source_event_ids,
                "source_event_seq": source.source_event_seq,
                "provider_session_generation": source.provider_session_generation,
                "context_snapshot_id": source.context_snapshot_id,
                "target_role": source.target_role,
            }
        )
    journal = _journal()
    authority = _register_source_authority(journal, source)
    with pytest.raises(ContextProjectionError, match="source_event_seq"):
        build_context_projection(
            journal=journal,
            event_id="evt_context_stale_sequence",
            source=replace(source, source_event_seq=1),
            source_authority=authority,
            created_monotonic_ms=2,
            created_wall_clock_ms=1_700_000_000_002,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("current_transcript_ref", "https://provider.example/raw-transcript"),
        (
            "recent_committed_item_refs",
            ("file://local/private/conversation-item",),
        ),
        (
            "session_memory_hint_refs",
            ("provider://remote/private-memory",),
        ),
    ),
)
def test_projection_rejects_external_or_noncanonical_context_refs(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ContextProjectionError, match=field):
        replace(_source(), **{field: value})


def test_projection_requires_unique_monotonic_source_predecessors() -> None:
    source = _source()
    journal = _journal()
    authority = _register_source_authority(journal, source)

    with pytest.raises(ContextProjectionError, match="source_event"):
        build_context_projection(
            journal=journal,
            event_id="evt_context_reversed_sources",
            source=replace(
                source,
                source_event_ids=tuple(reversed(source.source_event_ids)),
                source_event_seq=1,
            ),
            source_authority=authority,
            created_monotonic_ms=2,
            created_wall_clock_ms=1_700_000_000_002,
        )

    with pytest.raises(ContextProjectionError, match="source_event"):
        build_context_projection(
            journal=journal,
            event_id="evt_context_duplicate_sources",
            source=replace(
                source,
                source_event_ids=(
                    "evt_context_turn_committed",
                    "evt_context_turn_committed",
                ),
            ),
            source_authority=authority,
            created_monotonic_ms=2,
            created_wall_clock_ms=1_700_000_000_002,
        )


def test_projection_identity_binds_role_and_all_bounded_source_metadata() -> None:
    journal = _journal()
    route_source = _source()
    authority = _register_source_authority(journal, route_source)
    route = build_context_projection(
        journal=journal,
        event_id="evt_context_projection_route",
        source=route_source,
        source_authority=authority,
        created_monotonic_ms=2,
        created_wall_clock_ms=1_700_000_000_002,
    )
    safety_source = replace(
        route_source,
        target_role="candidate_safety",
        current_transcript_ref="text-ref://synthetic/asr/context-002",
        source_event_ids=(
            *route_source.source_event_ids,
            "evt_context_projection_route",
        ),
        source_event_seq=3,
    )
    authority.register(
        kind="current_transcript",
        ref=safety_source.current_transcript_ref,
        normalized_text="t" * 42,
        source_event_id="evt_context_projection_route",
    )
    safety = build_context_projection(
        journal=journal,
        event_id="evt_context_projection_safety",
        source=safety_source,
        source_authority=authority,
        created_monotonic_ms=3,
        created_wall_clock_ms=1_700_000_000_003,
    )

    assert route.projection_id != safety.projection_id
    assert route.projection_ref != safety.projection_ref


def test_total_serialized_limit_counts_every_bounded_ref() -> None:
    long_segment = "x" * 180
    with pytest.raises(ContextProjectionError, match="total_serialized_chars"):
        replace(
            _source(),
            current_transcript_char_count=2_000,
            current_transcript_ref=f"text-ref://synthetic/{long_segment}",
            recent_committed_item_refs=tuple(
                f"committed-item://synthetic/{index}-{long_segment}"
                for index in range(4)
            ),
            recent_dialogue_summary_ref=(
                f"dialogue-summary://synthetic/{long_segment}"
            ),
            recent_dialogue_summary_char_count=2_000,
            active_task_public_summary_ref=(
                f"task-public-summary://synthetic/{long_segment}"
            ),
            active_task_public_summary_char_count=1_000,
            session_memory_hint_refs=tuple(
                f"memory-hint://synthetic/{index}-{long_segment}"
                for index in range(5)
            ),
            session_memory_hint_char_count=1_000,
        )


def _register_source_authority(
    journal: InMemoryEventJournal,
    source: ContextProjectionSourceV1,
):
    authority = context_projection_module.ContextProjectionSourceAuthorityV1(
        journal=journal
    )
    registrations = (
        (
            "current_transcript",
            source.current_transcript_ref,
            "t" * 42,
            "evt_context_turn_committed",
        ),
        (
            "committed_item",
            source.recent_committed_item_refs[0],
            "committed one",
            "evt_context_session_started",
        ),
        (
            "committed_item",
            source.recent_committed_item_refs[1],
            "committed two",
            "evt_context_turn_committed",
        ),
        (
            "dialogue_summary",
            source.recent_dialogue_summary_ref,
            "d" * 30,
            "evt_context_turn_committed",
        ),
        (
            "task_public_summary",
            source.active_task_public_summary_ref,
            "a" * 20,
            "evt_context_turn_committed",
        ),
        (
            "memory_hint",
            source.session_memory_hint_refs[0],
            "m" * 10,
            "evt_context_turn_committed",
        ),
    )
    for kind, ref, normalized_text, source_event_id in registrations:
        assert ref is not None
        authority.register(
            kind=kind,
            ref=ref,
            normalized_text=normalized_text,
            source_event_id=source_event_id,
        )
    return authority


def test_projection_rejects_old_source_subset_after_new_journal_terminal() -> None:
    journal = _journal()
    source = _source()
    authority = _register_source_authority(journal, source)
    journal.append(
        event_name="TURN_INGRESS_COMMITTED",
        event_id="evt_context_later_turn_committed",
        caused_by_event_id="evt_context_turn_committed",
        source_module="test",
        created_monotonic_ms=2,
        created_wall_clock_ms=1_700_000_000_002,
        trace_redaction_level="metadata_only",
        turn_id="turn_context_later_synthetic",
        utterance_id="utt_context_later_synthetic",
        audio_span_id="audio_context_later_synthetic",
        input_modality="audio",
        directedness="ASSUMED_DIRECTED",
        semantic_close="ASSUMED_CLOSED",
        ingress_outcome="COMMITTED",
    )

    with pytest.raises(ContextProjectionError, match="terminal"):
        build_context_projection(
            journal=journal,
            event_id="evt_context_stale_subset",
            source=source,
            source_authority=authority,
            created_monotonic_ms=3,
            created_wall_clock_ms=1_700_000_000_003,
        )


def test_projection_rejects_canonical_but_unregistered_foreign_ref() -> None:
    journal = _journal()
    source = _source()
    authority = _register_source_authority(journal, source)
    foreign_ref = "committed-item://synthetic/foreign-session-item"

    with pytest.raises(ContextProjectionError, match="unregistered"):
        build_context_projection(
            journal=journal,
            event_id="evt_context_foreign_ref",
            source=replace(
                source,
                recent_committed_item_refs=(
                    source.recent_committed_item_refs[0],
                    foreign_ref,
                ),
            ),
            source_authority=authority,
            created_monotonic_ms=2,
            created_wall_clock_ms=1_700_000_000_002,
        )


def test_source_authority_retains_metadata_but_not_registered_text() -> None:
    journal = _journal()
    authority = context_projection_module.ContextProjectionSourceAuthorityV1(
        journal=journal
    )
    registered_text = "unique sensitive synthetic source text"

    authority.register(
        kind="current_transcript",
        ref="text-ref://synthetic/metadata-only",
        normalized_text=registered_text,
        source_event_id="evt_context_turn_committed",
    )

    assert registered_text not in repr(authority)
    assert registered_text not in repr(authority._entries)


@pytest.mark.parametrize("declared_count", (0, 41, 43))
def test_projection_rejects_zero_or_forged_count_for_registered_nonempty_ref(
    declared_count: int,
) -> None:
    journal = _journal()
    source = _source()
    authority = _register_source_authority(journal, source)

    with pytest.raises(ContextProjectionError, match="count"):
        build_context_projection(
            journal=journal,
            event_id=f"evt_context_forged_count_{declared_count}",
            source=replace(
                source,
                current_transcript_char_count=declared_count,
            ),
            source_authority=authority,
            created_monotonic_ms=2,
            created_wall_clock_ms=1_700_000_000_002,
        )


def test_projection_rejects_actual_full_serialized_context_over_limit() -> None:
    journal = _journal()
    source = replace(
        _source(),
        current_transcript_char_count=1,
        recent_committed_item_refs=("committed-item://synthetic/large",),
        recent_dialogue_summary_ref=None,
        recent_dialogue_summary_char_count=0,
        active_task_public_summary_ref=None,
        active_task_public_summary_char_count=0,
        session_memory_hint_refs=(),
        session_memory_hint_char_count=0,
    )
    authority = context_projection_module.ContextProjectionSourceAuthorityV1(
        journal=journal
    )
    authority.register(
        kind="current_transcript",
        ref=source.current_transcript_ref,
        normalized_text="t",
        source_event_id="evt_context_turn_committed",
    )
    authority.register(
        kind="committed_item",
        ref=source.recent_committed_item_refs[0],
        # 4,000 Unicode scalars, but 8,002 canonical JSON characters because
        # every newline is escaped. A scalar-only sum would incorrectly pass.
        normalized_text="\n" * 4_000,
        source_event_id="evt_context_turn_committed",
    )

    with pytest.raises(ContextProjectionError, match="total_serialized_chars"):
        build_context_projection(
            journal=journal,
            event_id="evt_context_actual_serialized_overflow",
            source=source,
            source_authority=authority,
            created_monotonic_ms=2,
            created_wall_clock_ms=1_700_000_000_002,
        )


@pytest.mark.parametrize(
    ("optional_ref", "declared_count"),
    (
        (None, 1),
        ("dialogue-summary://synthetic/one", 0),
    ),
)
def test_projection_requires_optional_ref_and_count_consistency(
    optional_ref: str | None,
    declared_count: int,
) -> None:
    with pytest.raises(ContextProjectionError, match="recent_dialogue_summary"):
        replace(
            _source(),
            recent_dialogue_summary_ref=optional_ref,
            recent_dialogue_summary_char_count=declared_count,
        )


def test_projection_rejects_ref_whose_registered_source_is_not_in_snapshot() -> None:
    journal = _journal()
    source = replace(
        _source(),
        recent_committed_item_refs=(),
        recent_dialogue_summary_ref=None,
        recent_dialogue_summary_char_count=0,
        active_task_public_summary_ref=None,
        active_task_public_summary_char_count=0,
        source_event_ids=("evt_context_turn_committed",),
        source_event_seq=2,
    )
    authority = context_projection_module.ContextProjectionSourceAuthorityV1(
        journal=journal
    )
    authority.register(
        kind="current_transcript",
        ref=source.current_transcript_ref,
        normalized_text="t" * 42,
        source_event_id="evt_context_session_started",
    )
    authority.register(
        kind="memory_hint",
        ref=source.session_memory_hint_refs[0],
        normalized_text="m" * 10,
        source_event_id="evt_context_session_started",
    )

    with pytest.raises(ContextProjectionError, match="source ownership"):
        build_context_projection(
            journal=journal,
            event_id="evt_context_missing_registered_source",
            source=source,
            source_authority=authority,
            created_monotonic_ms=2,
            created_wall_clock_ms=1_700_000_000_002,
        )
