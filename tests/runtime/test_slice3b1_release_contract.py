from __future__ import annotations

import ast
from dataclasses import fields, replace
from pathlib import Path
from threading import RLock
from typing import Callable

import pytest

from qwen_slice3b1_support import gate_event_ids, parallel_gate_fixture
from voice_agent.events.journal import (
    InMemoryEventJournal,
    JournalAppendRequest,
)
from voice_agent.runtime.slice3b1_release import (
    ForegroundReleaseTokenV1,
    InMemoryPlaybackOutbox,
    ParallelForegroundReleaseError,
    PlaybackOutboxItemV1,
    _compare_authorize_and_enqueue_contract_only,
    build_slice3b1_gate_context,
)


TOKEN_BINDING_FIELDS = (
    "release_token_id",
    "session_id",
    "provider_session_generation",
    "context_snapshot_id",
    "source_event_seq",
    "turn_id",
    "utterance_id",
    "qwen_response_id",
    "qwen_output_item_id",
    "qwen_output_index",
    "qwen_content_index",
    "candidate_id",
    "candidate_transcript_digest",
    "candidate_pcm_manifest_digest",
    "candidate_audio_format_ref",
    "candidate_audio_duration_ms",
    "candidate_audio_shadow_verification_event_id",
    "router_decision_event_id",
    "route_evidence_event_id",
    "candidate_safety_evidence_event_id",
    "playback_epoch",
    "gate_policy_version",
)


def _valid_token(**overrides: object) -> ForegroundReleaseTokenV1:
    values: dict[str, object] = {
        "release_token_id": "release_token_0123456789abcdef0123456789abcdef",
        "session_id": "sess_slice3b1_synthetic",
        "provider_session_generation": 1,
        "context_snapshot_id": "context_snapshot_synthetic_001",
        "source_event_seq": 12,
        "turn_id": "turn_slice3b1_synthetic",
        "utterance_id": "utterance_slice3b1_synthetic",
        "qwen_response_id": "qwen_response_synthetic_001",
        "qwen_output_item_id": "qwen_output_item_synthetic_001",
        "qwen_output_index": 0,
        "qwen_content_index": 0,
        "candidate_id": "candidate_parallel_synthetic",
        "candidate_transcript_digest": "sha256:" + "1" * 64,
        "candidate_pcm_manifest_digest": "sha256:" + "2" * 64,
        "candidate_audio_format_ref": (
            "audio-format://synthetic/pcm16-mono-24000"
        ),
        "candidate_audio_duration_ms": 500,
        "candidate_audio_shadow_verification_event_id": None,
        "router_decision_event_id": "evt_router_decision_synthetic",
        "route_evidence_event_id": "evt_route_evidence_synthetic",
        "candidate_safety_evidence_event_id": "evt_candidate_safety_synthetic",
        "playback_epoch": 0,
        "gate_policy_version": "slice3b1.parallel_gate.v1",
    }
    values.update(overrides)
    return ForegroundReleaseTokenV1(**values)


class _SyntheticPCMHandle:
    __slots__ = ("_buffer", "released")

    def __init__(self) -> None:
        self._buffer = bytearray((index % 251 for index in range(64)))
        self.released = False

    def release(self) -> None:
        self._buffer.clear()
        self.released = True

    def __repr__(self) -> str:
        return "<SyntheticPCMHandle redacted>"


def _fixture_context(fixture):
    return build_slice3b1_gate_context(
        journal=fixture.journal,
        assembly_result=fixture.assembly_result,
        assembly_stage="slice3b1_mock",
        capability_snapshot_event=fixture.capability_snapshot_event,
        eligibility_facts=fixture.eligibility_facts,
        fast_interaction_output_event=fixture.fast_interaction_output_event,
        candidate_event=fixture.candidate_event,
        router_decision_event=fixture.router_decision_event,
        route_evidence_event=fixture.route_evidence_event,
        candidate_safety_event=fixture.candidate_safety_event,
        provider_context_state="CLEAN",
        interaction_state="TURN_COMMITTED",
    )


def _token_for_fixture(fixture, *, case_id: str) -> ForegroundReleaseTokenV1:
    context = _fixture_context(fixture)
    return ForegroundReleaseTokenV1(
        release_token_id=gate_event_ids(case_id)["release_token_id"],
        session_id=context.session_id,
        provider_session_generation=context.provider_session_generation,
        context_snapshot_id=context.context_snapshot_id,
        source_event_seq=context.source_event_seq,
        turn_id=context.turn_id,
        utterance_id=context.utterance_id,
        qwen_response_id=context.qwen_response_id,
        qwen_output_item_id=context.qwen_output_item_id,
        qwen_output_index=context.qwen_output_index,
        qwen_content_index=context.qwen_content_index,
        candidate_id=context.candidate_id,
        candidate_transcript_digest=context.candidate_transcript_digest,
        candidate_pcm_manifest_digest=context.candidate_pcm_manifest_digest,
        candidate_audio_format_ref=context.candidate_audio_format_ref,
        candidate_audio_duration_ms=context.candidate_audio_duration_ms,
        candidate_audio_shadow_verification_event_id=(
            context.candidate_audio_shadow_verification_event_id
        ),
        router_decision_event_id=context.router_decision_event_id,
        route_evidence_event_id=context.route_evidence_event_id,
        candidate_safety_evidence_event_id=(
            context.candidate_safety_evidence_event_id
        ),
        playback_epoch=context.playback_epoch,
        gate_policy_version=context.gate_policy_version,
    )


def _release_ref(token: ForegroundReleaseTokenV1) -> str:
    return f"release-token://synthetic/{token.release_token_id}"


def _authorize(
    *,
    journal,
    fixture,
    token: ForegroundReleaseTokenV1,
    current_binding_reader: Callable[[], ForegroundReleaseTokenV1],
    outbox: InMemoryPlaybackOutbox,
    handle: _SyntheticPCMHandle,
    case_id: str,
    release_token_ref: str | None = None,
    event_ids: dict[str, str] | None = None,
):
    return _compare_authorize_and_enqueue_contract_only(
        journal=journal,
        expected_token=token,
        current_binding_reader=current_binding_reader,
        candidate_eligibility_facts=fixture.eligibility_facts,
        candidate_event=fixture.candidate_event,
        fast_interaction_output_event=fixture.fast_interaction_output_event,
        release_token_ref=(
            _release_ref(token)
            if release_token_ref is None
            else release_token_ref
        ),
        outbox=outbox,
        pcm_handle=handle,
        event_ids=(
            gate_event_ids(case_id)
            if event_ids is None
            else event_ids
        ),
        created_monotonic_ms=200,
        created_wall_clock_ms=1_700_000_000_200,
    )


def test_release_token_has_exact_adr018_field_set_and_is_immutable() -> None:
    token = _valid_token()

    assert tuple(field.name for field in fields(token)) == TOKEN_BINDING_FIELDS
    with pytest.raises(AttributeError):
        token.playback_epoch = 1  # type: ignore[misc]


def test_contract_only_authorizes_exact_binding_as_one_atomic_batch() -> None:
    fixture = parallel_gate_fixture()
    token = _token_for_fixture(fixture, case_id="contract_success")
    handle = _SyntheticPCMHandle()
    outbox = InMemoryPlaybackOutbox(max_items=2)
    before_last_seq = int(fixture.journal.events()[-1]["event_seq"])

    result = _authorize(
        journal=fixture.journal,
        fixture=fixture,
        token=token,
        current_binding_reader=lambda: token,
        outbox=outbox,
        handle=handle,
        case_id="contract_success",
    )

    assert result.release_token == token
    assert result.discarded_event is None
    assert result.gate_event["event_name"] == "FOREGROUND_ACT_GATE_PASSED"
    assert result.committed_event is not None
    assert result.committed_event["event_name"] == "FOREGROUND_OUTPUT_COMMITTED"
    assert result.gate_event["event_seq"] == before_last_seq + 1
    assert result.committed_event["event_seq"] == before_last_seq + 2
    assert result.committed_event["caused_by_event_id"] == (
        result.gate_event["event_id"]
    )
    assert result.gate_event["release_token_ref"] == _release_ref(token)
    assert result.committed_event["release_token_ref"] == _release_ref(token)
    assert result.committed_event["user_visible_channel"] == "audio_pending"
    assert result.committed_event["authority_mode"] == "mock_contract_only"
    assert result.committed_event["output_mode"] == "mock"
    assert result.committed_event["qualification_status"] == "not_qualification"
    assert len(outbox.items()) == 1
    assert outbox.items()[0].release_token_ref == _release_ref(token)
    assert handle.released is False


def _mismatched_token(
    token: ForegroundReleaseTokenV1,
    field_name: str,
) -> ForegroundReleaseTokenV1:
    valid_changes: dict[str, object] = {
        "release_token_id": "release_token_fedcba9876543210fedcba9876543210",
        "session_id": "sess_slice3b1_stale",
        "provider_session_generation": 2,
        "context_snapshot_id": "context_snapshot_stale_002",
        "source_event_seq": token.source_event_seq + 1,
        "turn_id": "turn_slice3b1_stale",
        "utterance_id": "utterance_slice3b1_stale",
        "qwen_response_id": "qwen_response_stale_002",
        "qwen_output_item_id": "qwen_output_item_stale_002",
        "qwen_output_index": 1,
        "qwen_content_index": 1,
        "candidate_id": "candidate_parallel_stale",
        "candidate_transcript_digest": "sha256:" + "3" * 64,
        "candidate_pcm_manifest_digest": "sha256:" + "4" * 64,
        "candidate_audio_format_ref": (
            "audio-format://synthetic/pcm16-mono-16000"
        ),
        "candidate_audio_duration_ms": 501,
        "candidate_audio_shadow_verification_event_id": (
            "evt_shadow_verification_stale"
        ),
        "router_decision_event_id": "evt_router_decision_stale",
        "route_evidence_event_id": "evt_route_evidence_stale",
        "candidate_safety_evidence_event_id": (
            "evt_candidate_safety_stale"
        ),
        "playback_epoch": 1,
        "gate_policy_version": "slice3b1.parallel_gate.stale.v1",
    }
    return replace(token, **{field_name: valid_changes[field_name]})


@pytest.mark.parametrize("field_name", TOKEN_BINDING_FIELDS)
def test_every_release_token_field_mismatch_fails_before_authority_append(
    field_name: str,
) -> None:
    fixture = parallel_gate_fixture()
    token = _token_for_fixture(fixture, case_id=f"mismatch_{field_name}")
    current = _mismatched_token(token, field_name)
    handle = _SyntheticPCMHandle()
    outbox = InMemoryPlaybackOutbox(max_items=2)
    before = fixture.journal.events()

    with pytest.raises(
        ParallelForegroundReleaseError,
        match=f"binding mismatch: {field_name}",
    ):
        _authorize(
            journal=fixture.journal,
            fixture=fixture,
            token=token,
            current_binding_reader=lambda: current,
            outbox=outbox,
            handle=handle,
            case_id=f"mismatch_{field_name}",
        )

    assert fixture.journal.events() == before
    assert outbox.items() == ()
    assert handle.released is True


@pytest.mark.parametrize(
    "field_name",
    ("provider_session_generation", "playback_epoch"),
)
def test_rebuild_or_barge_in_current_binding_fails_closed(
    field_name: str,
) -> None:
    fixture = parallel_gate_fixture()
    token = _token_for_fixture(fixture, case_id=f"stale_{field_name}")
    current = _mismatched_token(token, field_name)
    handle = _SyntheticPCMHandle()

    with pytest.raises(ParallelForegroundReleaseError, match="binding mismatch"):
        _authorize(
            journal=fixture.journal,
            fixture=fixture,
            token=token,
            current_binding_reader=lambda: current,
            outbox=InMemoryPlaybackOutbox(max_items=1),
            handle=handle,
            case_id=f"stale_{field_name}",
        )

    assert handle.released is True


def test_release_token_ref_is_exactly_derived_not_caller_chosen() -> None:
    fixture = parallel_gate_fixture()
    token = _token_for_fixture(fixture, case_id="bad_release_ref")
    handle = _SyntheticPCMHandle()
    before = fixture.journal.events()

    with pytest.raises(ParallelForegroundReleaseError, match="release_token_ref"):
        _authorize(
            journal=fixture.journal,
            fixture=fixture,
            token=token,
            current_binding_reader=lambda: token,
            outbox=InMemoryPlaybackOutbox(max_items=1),
            handle=handle,
            case_id="bad_release_ref",
            release_token_ref=(
                "release-token://synthetic/"
                "release_token_ffffffffffffffffffffffffffffffff"
            ),
        )

    assert fixture.journal.events() == before
    assert handle.released is True


def test_duplicate_outbox_reservation_prevents_second_atomic_batch() -> None:
    fixture = parallel_gate_fixture()
    token = _token_for_fixture(fixture, case_id="duplicate_outbox_first")
    outbox = InMemoryPlaybackOutbox(max_items=4)
    _authorize(
        journal=fixture.journal,
        fixture=fixture,
        token=token,
        current_binding_reader=lambda: token,
        outbox=outbox,
        handle=_SyntheticPCMHandle(),
        case_id="duplicate_outbox_first",
    )
    before_second = fixture.journal.events()
    second_handle = _SyntheticPCMHandle()
    second_event_ids = gate_event_ids("duplicate_outbox_second")
    second_event_ids["release_token_id"] = token.release_token_id

    with pytest.raises(ParallelForegroundReleaseError, match="duplicate"):
        _authorize(
            journal=fixture.journal,
            fixture=fixture,
            token=token,
            current_binding_reader=lambda: token,
            outbox=outbox,
            handle=second_handle,
            case_id="duplicate_outbox_second",
            event_ids=second_event_ids,
        )

    assert fixture.journal.events() == before_second
    assert len(outbox.items()) == 1
    assert second_handle.released is True


def test_outbox_capacity_preflight_prevents_atomic_batch() -> None:
    fixture = parallel_gate_fixture()
    first = _token_for_fixture(fixture, case_id="capacity_first")
    outbox = InMemoryPlaybackOutbox(max_items=1)
    _authorize(
        journal=fixture.journal,
        fixture=fixture,
        token=first,
        current_binding_reader=lambda: first,
        outbox=outbox,
        handle=_SyntheticPCMHandle(),
        case_id="capacity_first",
    )
    second = replace(
        first,
        release_token_id=gate_event_ids("capacity_second")["release_token_id"],
    )
    before_second = fixture.journal.events()
    second_handle = _SyntheticPCMHandle()

    with pytest.raises(ParallelForegroundReleaseError, match="capacity"):
        _authorize(
            journal=fixture.journal,
            fixture=fixture,
            token=second,
            current_binding_reader=lambda: second,
            outbox=outbox,
            handle=second_handle,
            case_id="capacity_second",
        )

    assert fixture.journal.events() == before_second
    assert len(outbox.items()) == 1
    assert second_handle.released is True


class _CorruptSecondEnvelopeJournal:
    def __init__(self, journal: InMemoryEventJournal) -> None:
        self._journal = journal

    def events(self):
        return self._journal.events()

    def has_event_id(self, event_id: str) -> bool:
        return self._journal.has_event_id(event_id)

    def append_atomic_batch(self, requests):
        first, second = requests
        malformed_fields = dict(second.fields)
        malformed_fields.pop("output_basis")
        return self._journal.append_atomic_batch(
            (
                first,
                replace(second, fields=malformed_fields),
            )
        )


def test_second_staged_envelope_failure_rolls_back_and_keeps_outbox_empty() -> None:
    fixture = parallel_gate_fixture()
    token = _token_for_fixture(fixture, case_id="bad_second_envelope")
    handle = _SyntheticPCMHandle()
    outbox = InMemoryPlaybackOutbox(max_items=1)
    before = fixture.journal.events()

    with pytest.raises(Exception, match="output_basis"):
        _authorize(
            journal=_CorruptSecondEnvelopeJournal(fixture.journal),
            fixture=fixture,
            token=token,
            current_binding_reader=lambda: token,
            outbox=outbox,
            handle=handle,
            case_id="bad_second_envelope",
        )

    assert fixture.journal.events() == before
    assert outbox.items() == ()
    assert handle.released is True


def test_fault_while_validating_second_envelope_preserves_next_sequence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = parallel_gate_fixture()
    token = _token_for_fixture(fixture, case_id="fault_second_envelope")
    handle = _SyntheticPCMHandle()
    outbox = InMemoryPlaybackOutbox(max_items=1)
    before = fixture.journal.events()
    import voice_agent.events.journal as journal_module

    real_validate = journal_module.validate_event_envelope
    validation_count = 0

    def fail_second(event):
        nonlocal validation_count
        validation_count += 1
        if validation_count == 2:
            raise RuntimeError("fault while validating second staged envelope")
        return real_validate(event)

    monkeypatch.setattr(journal_module, "validate_event_envelope", fail_second)
    with pytest.raises(RuntimeError, match="second staged envelope"):
        _authorize(
            journal=fixture.journal,
            fixture=fixture,
            token=token,
            current_binding_reader=lambda: token,
            outbox=outbox,
            handle=handle,
            case_id="fault_second_envelope",
        )
    monkeypatch.setattr(
        journal_module,
        "validate_event_envelope",
        real_validate,
    )

    assert fixture.journal.events() == before
    assert outbox.items() == ()
    assert handle.released is True
    retry_handle = _SyntheticPCMHandle()
    retry = _authorize(
        journal=fixture.journal,
        fixture=fixture,
        token=token,
        current_binding_reader=lambda: token,
        outbox=outbox,
        handle=retry_handle,
        case_id="fault_second_envelope",
    )
    assert retry.gate_event["event_seq"] == int(before[-1]["event_seq"]) + 1


def test_outbox_and_result_repr_never_expose_pcm_or_payload_fields() -> None:
    fixture = parallel_gate_fixture()
    token = _token_for_fixture(fixture, case_id="repr_safe")
    handle = _SyntheticPCMHandle()
    outbox = InMemoryPlaybackOutbox(max_items=1)

    result = _authorize(
        journal=fixture.journal,
        fixture=fixture,
        token=token,
        current_binding_reader=lambda: token,
        outbox=outbox,
        handle=handle,
        case_id="repr_safe",
    )

    item = outbox.items()[0]
    assert isinstance(item, PlaybackOutboxItemV1)
    assert "SyntheticPCMHandle" not in repr(item)
    assert "_buffer" not in repr(item)
    assert "pcm_handle" not in repr(item)
    event_keys = set(result.gate_event)
    assert result.committed_event is not None
    event_keys.update(result.committed_event)
    assert not {
        "text",
        "transcript",
        "candidate_text",
        "pcm",
        "audio_bytes",
        "provider_payload",
    } & event_keys


def _valid_outbox_item(
    *,
    release_token_ref: str = (
        "release-token://synthetic/"
        "release_token_0123456789abcdef0123456789abcdef"
    ),
    pcm_handle: object | None = None,
) -> PlaybackOutboxItemV1:
    return PlaybackOutboxItemV1(
        outbox_item_id="playback_outbox_0123456789abcdef0123456789abcdef",
        release_token_ref=release_token_ref,
        provider_session_generation=1,
        qwen_response_id="qwen_response_synthetic_001",
        qwen_output_item_id="qwen_output_item_synthetic_001",
        qwen_output_index=0,
        qwen_content_index=0,
        candidate_id="candidate_parallel_synthetic",
        playback_epoch=0,
        pcm_handle=(
            _SyntheticPCMHandle()
            if pcm_handle is None
            else pcm_handle
        ),
    )


@pytest.mark.parametrize(
    "release_token_ref",
    (
        "https://example.invalid/release-token",
        "release-token://local/release_token_0123456789abcdef0123456789abcdef",
        "release-token://synthetic/release_token_not_hex",
    ),
)
def test_outbox_item_requires_exact_synthetic_release_token_ref(
    release_token_ref: str,
) -> None:
    with pytest.raises(ParallelForegroundReleaseError, match="release_token_ref"):
        _valid_outbox_item(release_token_ref=release_token_ref)


def test_outbox_item_rejects_unusable_pcm_handle() -> None:
    with pytest.raises(ParallelForegroundReleaseError, match="pcm_handle"):
        _valid_outbox_item(pcm_handle=object())


def test_outbox_cannot_be_subclassed_to_break_infallible_commit() -> None:
    with pytest.raises(TypeError, match="final"):

        class _ThrowingCommitOutbox(InMemoryPlaybackOutbox):
            def _commit_locked(self, reservation) -> None:
                raise RuntimeError("post-journal failure")


def test_outbox_instance_cannot_override_infallible_commit() -> None:
    outbox = InMemoryPlaybackOutbox(max_items=1)

    assert not hasattr(outbox, "__dict__")
    with pytest.raises(AttributeError):
        outbox._commit_locked = lambda reservation: None  # type: ignore[method-assign]


def _append_alternate_cross_turn_evidence(fixture):
    envelope_fields = {
        "event_name",
        "event_id",
        "event_seq",
        "event_schema_version",
        "session_id",
        "conversation_id",
        "source_module",
        "created_monotonic_ms",
        "created_wall_clock_ms",
        "trace_redaction_level",
        "caused_by_event_id",
    }
    route_fields = {
        key: value
        for key, value in fixture.route_evidence_event.items()
        if key not in envelope_fields
    }
    route_fields.update(
        turn_id="turn_cross_session_stale",
        utterance_id="utterance_cross_session_stale",
        provider_session_generation=2,
    )
    route = fixture.journal.append(
        event_name="ROUTE_EVIDENCE_OUTPUT_EMITTED",
        event_id="evt_route_evidence_cross_turn",
        source_module="route_evidence_adapter",
        caused_by_event_id=str(
            fixture.route_evidence_event["caused_by_event_id"]
        ),
        created_monotonic_ms=150,
        created_wall_clock_ms=1_700_000_000_150,
        trace_redaction_level="metadata_only",
        **route_fields,
    )
    safety_fields = {
        key: value
        for key, value in fixture.candidate_safety_event.items()
        if key not in envelope_fields
    }
    safety_fields.update(
        turn_id="turn_cross_session_stale",
        utterance_id="utterance_cross_session_stale",
        provider_session_generation=2,
        candidate_transcript_digest="sha256:" + "f" * 64,
        route_evidence_event_id=str(route["event_id"]),
    )
    safety = fixture.journal.append(
        event_name="CANDIDATE_SAFETY_EVIDENCE_OUTPUT_EMITTED",
        event_id="evt_candidate_safety_cross_turn",
        source_module="route_evidence_adapter",
        caused_by_event_id=str(
            fixture.candidate_safety_event["caused_by_event_id"]
        ),
        created_monotonic_ms=151,
        created_wall_clock_ms=1_700_000_000_151,
        trace_redaction_level="metadata_only",
        **safety_fields,
    )
    return route, safety


def test_contract_rejects_agreeing_token_pair_bound_to_cross_turn_evidence() -> None:
    fixture = parallel_gate_fixture()
    base = _token_for_fixture(fixture, case_id="cross_turn_evidence")
    route, safety = _append_alternate_cross_turn_evidence(fixture)
    token = replace(
        base,
        route_evidence_event_id=str(route["event_id"]),
        candidate_safety_evidence_event_id=str(safety["event_id"]),
        source_event_seq=int(safety["event_seq"]),
    )
    handle = _SyntheticPCMHandle()
    before = fixture.journal.events()

    with pytest.raises(ParallelForegroundReleaseError, match="cross-event"):
        _authorize(
            journal=fixture.journal,
            fixture=fixture,
            token=token,
            current_binding_reader=lambda: token,
            outbox=InMemoryPlaybackOutbox(max_items=1),
            handle=handle,
            case_id="cross_turn_evidence",
        )

    assert fixture.journal.events() == before
    assert handle.released is True


@pytest.mark.parametrize(
    "fixture_overrides",
    (
        {"router_turn_id": "turn_slice3b1_other"},
        {"router_utterance_id": "utterance_slice3b1_other"},
    ),
)
def test_contract_rejects_router_from_another_turn_or_utterance(
    fixture_overrides: dict[str, object],
) -> None:
    fixture = parallel_gate_fixture(**fixture_overrides)
    event_ids = gate_event_ids("wrong_turn_router")
    source_event_seq = max(
        int(event["event_seq"])
        for event in (
            fixture.candidate_event,
            fixture.fast_interaction_output_event,
            fixture.router_decision_event,
            fixture.route_evidence_event,
            fixture.candidate_safety_event,
        )
    )
    token = replace(
        _valid_token(),
        release_token_id=event_ids["release_token_id"],
        source_event_seq=source_event_seq,
        router_decision_event_id=str(
            fixture.router_decision_event["event_id"]
        ),
    )
    handle = _SyntheticPCMHandle()
    outbox = InMemoryPlaybackOutbox(max_items=1)
    before = fixture.journal.events()

    with pytest.raises(ParallelForegroundReleaseError, match="cross-event"):
        _authorize(
            journal=fixture.journal,
            fixture=fixture,
            token=token,
            current_binding_reader=lambda: token,
            outbox=outbox,
            handle=handle,
            case_id="wrong_turn_router",
        )

    assert fixture.journal.events() == before
    assert outbox.items() == ()
    assert handle.released is True


@pytest.mark.parametrize(
    "fixture_overrides",
    (
        {"candidate_status": "partial"},
        {"candidate_unicode_scalar_count": 81},
        {"route_confidence": 0.79},
        {"route_evidence_uncertainty": "HIGH"},
    ),
)
def test_contract_never_claims_pass_for_non_authorizing_candidate_or_route(
    fixture_overrides: dict[str, object],
) -> None:
    fixture = parallel_gate_fixture(**fixture_overrides)
    token = _token_for_fixture(fixture, case_id="non_authorizing_contract")
    handle = _SyntheticPCMHandle()
    outbox = InMemoryPlaybackOutbox(max_items=1)
    before = fixture.journal.events()

    with pytest.raises(ParallelForegroundReleaseError, match="not authorizing"):
        _authorize(
            journal=fixture.journal,
            fixture=fixture,
            token=token,
            current_binding_reader=lambda: token,
            outbox=outbox,
            handle=handle,
            case_id="non_authorizing_contract",
        )

    assert fixture.journal.events() == before
    assert outbox.items() == ()
    assert handle.released is True


def _append_contract_candidate_variant(
    fixture,
    *,
    field_name: str,
    value: object,
):
    envelope_fields = {
        "event_name",
        "event_id",
        "event_seq",
        "event_schema_version",
        "session_id",
        "conversation_id",
        "source_module",
        "created_monotonic_ms",
        "created_wall_clock_ms",
        "trace_redaction_level",
        "caused_by_event_id",
    }
    candidate_fields = {
        key: field_value
        for key, field_value in fixture.candidate_event.items()
        if key not in envelope_fields
    }
    candidate_fields.update(
        candidate_id="candidate_parallel_contract_variant",
        **{field_name: value},
    )
    return fixture.journal.append(
        event_name="FOREGROUND_REPLY_CANDIDATE_EMITTED",
        event_id=f"evt_contract_candidate_variant_{field_name}",
        source_module="slice3b1_candidate_quarantine",
        caused_by_event_id=str(
            fixture.fast_interaction_output_event["event_id"]
        ),
        created_monotonic_ms=180,
        created_wall_clock_ms=1_700_000_000_180,
        trace_redaction_level="metadata_only",
        **candidate_fields,
    )


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("risk_tags", ("different",)),
        ("confidence", 0.5),
        (
            "source_event_ids",
            ("evt_parallel_fast_output_synthetic",),
        ),
    ),
)
def test_contract_rejects_candidate_evidence_join_forgery(
    field_name: str,
    value: object,
) -> None:
    fixture = parallel_gate_fixture()
    base = _token_for_fixture(fixture, case_id="candidate_join_forgery")
    candidate = _append_contract_candidate_variant(
        fixture,
        field_name=field_name,
        value=value,
    )
    token = replace(
        base,
        candidate_id=str(candidate["candidate_id"]),
        source_event_seq=int(candidate["event_seq"]),
    )
    variant_fixture = replace(
        fixture,
        candidate_event=candidate,
        eligibility_facts=replace(
            fixture.eligibility_facts,
            candidate_id=str(candidate["candidate_id"]),
        ),
    )
    handle = _SyntheticPCMHandle()
    before = fixture.journal.events()

    with pytest.raises(ParallelForegroundReleaseError, match="cross-event"):
        _authorize(
            journal=fixture.journal,
            fixture=variant_fixture,
            token=token,
            current_binding_reader=lambda: token,
            outbox=InMemoryPlaybackOutbox(max_items=1),
            handle=handle,
            case_id="candidate_join_forgery",
        )

    assert fixture.journal.events() == before
    assert handle.released is True


def test_contract_primitive_is_private_and_absent_from_runtime_cli_imports() -> None:
    import voice_agent.runtime.slice3b1_release as release_module

    private_name = "_compare_authorize_and_enqueue_contract_only"
    assert private_name not in release_module.__all__
    import voice_agent.runtime.slice3b1 as slice3b1_namespace

    assert not hasattr(slice3b1_namespace, private_name)
    source_root = Path(__file__).resolve().parents[2] / "src" / "voice_agent"
    runtime_files = tuple((source_root / "runtime").rglob("*.py"))
    cli_files = tuple(source_root.rglob("*cli*.py"))
    for source_path in (*runtime_files, *cli_files):
        if source_path.name == "slice3b1_release.py":
            continue
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        referenced_names = {
            node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
        }
        referenced_attributes = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
        }
        imported_names = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        assert private_name not in referenced_names
        assert private_name not in referenced_attributes
        assert private_name not in imported_names
