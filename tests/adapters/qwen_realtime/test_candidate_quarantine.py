from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, replace

import pytest

from voice_agent.adapters.qwen_realtime.projections import (
    CandidateCompletionV1 as ProjectionCandidateCompletionV1,
)
from voice_agent.adapters.qwen_realtime.projections import (
    CandidateEligibilityFactsV1 as ProjectionCandidateEligibilityFactsV1,
)
from voice_agent.adapters.qwen_realtime.projections import (
    CandidateTranscriptCompleteV1 as ProjectionCandidateTranscriptCompleteV1,
)
from voice_agent.adapters.qwen_realtime.quarantine import (
    CandidateCompletionV1,
    CandidateEligibilityFactsV1,
    CandidateLimitsV1,
    CandidateQuarantine,
    CandidateQuarantineError,
    CandidateTranscriptCompleteV1,
    CommittedCandidateBinding,
    WipeablePCMBuffer,
)
from voice_agent.adapters.qwen_realtime.ephemeral_text_store import (
    EphemeralTextStore,
)


TEST_LIMITS = CandidateLimitsV1(
    max_transcript_unicode_scalars=80,
    max_pcm_bytes=4096,
    max_pcm_chunks=8,
    max_audio_duration_ms=2000,
)

_BINDING = CommittedCandidateBinding(
    turn_id="turn_1",
    utterance_id="utt_1",
    context_snapshot_id="context_1",
)


def apply_provider_order(
    quarantine: CandidateQuarantine,
    provider_order: str,
) -> None:
    assistant = {
        "event_id": "provider_evt_assistant_item",
        "generation": 1,
        "response_id": "resp_1",
        "item_id": "item_1",
        "item_type": "message",
        "role": "assistant",
    }
    output = {
        "event_id": "provider_evt_output_item",
        "generation": 1,
        "response_id": "resp_1",
        "item_id": "item_1",
        "output_index": 0,
        "item_type": "message",
    }
    if provider_order == "assistant_item_then_output_item":
        quarantine.accept_assistant_item(**assistant)
        quarantine.accept_output_item(**output)
    else:
        quarantine.accept_output_item(**output)
        quarantine.accept_assistant_item(**assistant)
    quarantine.accept_content_part(
        event_id="provider_evt_content",
        generation=1,
        response_id="resp_1",
        item_id="item_1",
        output_index=0,
        content_index=0,
        content_type="audio",
    )


def open_quarantine(
    *,
    provider_order: str = "assistant_item_then_output_item",
    text_store: EphemeralTextStore | None = None,
) -> CandidateQuarantine:
    quarantine = CandidateQuarantine(
        limits=TEST_LIMITS,
        text_store=text_store,
    )
    quarantine.open_response(
        event_id="provider_evt_response_created",
        generation=1,
        response_id="resp_1",
        candidate_id="cand_1",
        playback_epoch=4,
        provisional_ingress_id="ingress_1",
        input_item_ref="qwen-input://synthetic/1",
    )
    apply_provider_order(quarantine, provider_order)
    return quarantine


def append_interleaved_candidate(
    quarantine: CandidateQuarantine,
    interleaving: str,
) -> None:
    transcript_frames = (
        {
            "event_id": "provider_evt_transcript_1",
            "normalized_delta": "brief ",
        },
        {
            "event_id": "provider_evt_transcript_2",
            "normalized_delta": "answer",
        },
    )
    audio_frames = (
        {
            "event_id": "provider_evt_audio_1",
            "pcm_chunk": b"\x01\x02" * 48,
        },
        {
            "event_id": "provider_evt_audio_2",
            "pcm_chunk": b"\x03\x04" * 48,
        },
    )
    common = {
        "generation": 1,
        "response_id": "resp_1",
        "item_id": "item_1",
        "output_index": 0,
        "content_index": 0,
    }
    audio_common = {
        **common,
        "audio_format_ref": "audio-format://pcm16le-24000-mono",
        "sample_rate_hz": 24_000,
        "channels": 1,
    }
    if interleaving == "transcript_audio_transcript_audio":
        quarantine.append_transcript_delta(**common, **transcript_frames[0])
        quarantine.append_pcm_delta(**audio_common, **audio_frames[0])
        quarantine.append_transcript_delta(**common, **transcript_frames[1])
        quarantine.append_pcm_delta(**audio_common, **audio_frames[1])
    else:
        quarantine.append_pcm_delta(**audio_common, **audio_frames[0])
        quarantine.append_transcript_delta(**common, **transcript_frames[0])
        quarantine.append_pcm_delta(**audio_common, **audio_frames[1])
        quarantine.append_transcript_delta(**common, **transcript_frames[1])


def mark_transcript_terminal(quarantine: CandidateQuarantine) -> None:
    quarantine.mark_transcript_done(
        event_id="provider_evt_transcript_done",
        generation=1,
        response_id="resp_1",
        item_id="item_1",
        output_index=0,
        content_index=0,
    )


def mark_remaining_terminals(quarantine: CandidateQuarantine) -> None:
    common = {
        "generation": 1,
        "response_id": "resp_1",
        "item_id": "item_1",
        "output_index": 0,
        "content_index": 0,
    }
    quarantine.mark_audio_done(
        event_id="provider_evt_audio_done",
        **common,
    )
    quarantine.mark_content_done(
        event_id="provider_evt_content_done",
        content_type="audio",
        **common,
    )
    quarantine.mark_output_item_done(
        event_id="provider_evt_output_done",
        generation=1,
        response_id="resp_1",
        item_id="item_1",
        output_index=0,
        item_type="message",
    )
    quarantine.mark_response_done(
        event_id="provider_evt_response_done",
        generation=1,
        response_id="resp_1",
        status="completed",
        output_item_ids=("item_1",),
    )


@pytest.mark.parametrize(
    "provider_order",
    ("assistant_item_then_output_item", "output_item_then_assistant_item"),
)
def test_response_can_start_before_commit_and_join_exactly_once(
    provider_order: str,
) -> None:
    quarantine = open_quarantine(provider_order=provider_order)
    quarantine.bind_committed_turn(_BINDING)

    with pytest.raises(CandidateQuarantineError, match="immutable"):
        quarantine.bind_committed_turn(
            CommittedCandidateBinding(
                turn_id="turn_2",
                utterance_id="utt_2",
                context_snapshot_id="context_2",
            )
        )
    with pytest.raises(CandidateQuarantineError, match="immutable"):
        quarantine.bind_committed_turn(_BINDING)


@pytest.mark.parametrize(
    "provider_order",
    ("assistant_item_then_output_item", "output_item_then_assistant_item"),
)
@pytest.mark.parametrize(
    "commit_schedule",
    ("before_provider_output", "after_transcript_terminal"),
)
@pytest.mark.parametrize(
    "interleaving",
    (
        "transcript_audio_transcript_audio",
        "audio_transcript_audio_transcript",
    ),
)
def test_transcript_completion_precedes_full_completion_for_all_legal_orders(
    provider_order: str,
    commit_schedule: str,
    interleaving: str,
) -> None:
    text_store = EphemeralTextStore()
    quarantine = CandidateQuarantine(limits=TEST_LIMITS, text_store=text_store)
    quarantine.open_response(
        event_id="provider_evt_response_created",
        generation=1,
        response_id="resp_1",
        candidate_id="cand_1",
        playback_epoch=4,
        provisional_ingress_id="ingress_1",
        input_item_ref="qwen-input://synthetic/1",
    )
    if commit_schedule == "before_provider_output":
        quarantine.bind_committed_turn(_BINDING)
    apply_provider_order(quarantine, provider_order)
    append_interleaved_candidate(quarantine, interleaving)
    mark_transcript_terminal(quarantine)

    if commit_schedule == "after_transcript_terminal":
        assert quarantine.transcript_completion() is None
        quarantine.bind_committed_turn(_BINDING)

    transcript = quarantine.transcript_completion()
    assert isinstance(transcript, CandidateTranscriptCompleteV1)
    assert transcript is quarantine.transcript_completion()
    assert transcript.candidate_unicode_scalar_count == 12
    assert quarantine.completion() is None
    with text_store.resolve(
        transcript.candidate_ref,
        expected_kind="candidate",
        expected_digest=transcript.candidate_transcript_digest,
        max_unicode_scalars=80,
    ) as lease:
        assert lease.text == "brief answer"

    mark_remaining_terminals(quarantine)
    completion = quarantine.completion()
    assert isinstance(completion, CandidateCompletionV1)
    assert completion is quarantine.completion()
    assert completion.candidate_ref == transcript.candidate_ref
    assert (
        completion.eligibility_facts.candidate_transcript_digest
        == transcript.candidate_transcript_digest
    )
    assert (
        completion.eligibility_facts.candidate_unicode_scalar_count
        == transcript.candidate_unicode_scalar_count
    )


def _completed_digests(
    provider_order: str,
    interleaving: str,
) -> tuple[str, str]:
    quarantine = open_quarantine(provider_order=provider_order)
    quarantine.bind_committed_turn(_BINDING)
    append_interleaved_candidate(quarantine, interleaving)
    mark_transcript_terminal(quarantine)
    mark_remaining_terminals(quarantine)
    completion = quarantine.completion()
    assert completion is not None
    return (
        completion.eligibility_facts.candidate_transcript_digest,
        completion.eligibility_facts.candidate_pcm_manifest_digest,
    )


def test_digests_are_stable_across_legal_provider_partial_orders() -> None:
    assert _completed_digests(
        "assistant_item_then_output_item",
        "transcript_audio_transcript_audio",
    ) == _completed_digests(
        "output_item_then_assistant_item",
        "audio_transcript_audio_transcript",
    )


def test_spawn_successor_preserves_limits_and_shared_text_store() -> None:
    text_store = EphemeralTextStore()
    first = open_quarantine(text_store=text_store)
    first.discard(reason="discarded")

    successor = first.spawn_successor()

    assert successor is not first
    assert successor._limits == TEST_LIMITS
    assert successor._text_store is text_store


def test_provider_response_terminal_waits_for_late_committed_binding() -> None:
    quarantine = open_quarantine()
    append_interleaved_candidate(
        quarantine,
        "transcript_audio_transcript_audio",
    )
    mark_transcript_terminal(quarantine)
    mark_remaining_terminals(quarantine)

    assert quarantine.disposition.status == "OPEN"
    assert quarantine.transcript_completion() is None
    assert quarantine.completion() is None

    quarantine.bind_committed_turn(_BINDING)
    transcript = quarantine.transcript_completion()
    completion = quarantine.completion()
    assert transcript is not None
    assert completion is not None
    assert (
        quarantine.require_current_transcript_completion(transcript)
        is transcript
    )
    assert quarantine.require_current_completion(completion) is completion


def test_quarantine_reexports_task3_projection_types_without_redefinition() -> None:
    assert CandidateCompletionV1 is ProjectionCandidateCompletionV1
    assert CandidateEligibilityFactsV1 is ProjectionCandidateEligibilityFactsV1
    assert (
        CandidateTranscriptCompleteV1
        is ProjectionCandidateTranscriptCompleteV1
    )


def test_completion_is_frozen_metadata_and_contains_no_content_handles() -> None:
    quarantine = open_quarantine()
    quarantine.bind_committed_turn(_BINDING)
    append_interleaved_candidate(
        quarantine,
        "transcript_audio_transcript_audio",
    )
    mark_transcript_terminal(quarantine)
    mark_remaining_terminals(quarantine)
    completion = quarantine.completion()
    assert completion is not None

    projection_field_names = {
        definition.name
        for definition in fields(completion.eligibility_facts)
    } | {definition.name for definition in fields(completion)}
    assert not projection_field_names & {
        "pcm",
        "pcm_buffer",
        "text",
        "resolver",
        "text_store",
    }
    with pytest.raises(FrozenInstanceError):
        completion.eligibility_facts.candidate_id = "replacement"  # type: ignore[misc]


def test_currentness_guards_return_exact_cached_projections() -> None:
    quarantine = open_quarantine()
    quarantine.bind_committed_turn(_BINDING)
    append_interleaved_candidate(
        quarantine,
        "transcript_audio_transcript_audio",
    )
    mark_transcript_terminal(quarantine)
    transcript = quarantine.transcript_completion()
    assert transcript is not None

    assert quarantine.require_current_transcript_completion(transcript) is transcript

    mark_remaining_terminals(quarantine)
    completion = quarantine.completion()
    assert completion is not None
    assert quarantine.require_current_completion(completion) is completion


def test_currentness_guards_reject_equal_but_different_projection_objects() -> None:
    transcript_quarantine = open_quarantine()
    transcript_quarantine.bind_committed_turn(_BINDING)
    append_interleaved_candidate(
        transcript_quarantine,
        "transcript_audio_transcript_audio",
    )
    mark_transcript_terminal(transcript_quarantine)
    transcript = transcript_quarantine.transcript_completion()
    assert transcript is not None
    forged_transcript = replace(transcript)
    assert forged_transcript == transcript
    assert forged_transcript is not transcript

    with pytest.raises(CandidateQuarantineError, match="not_current"):
        transcript_quarantine.require_current_transcript_completion(
            forged_transcript
        )

    completion_quarantine = open_quarantine()
    completion_quarantine.bind_committed_turn(_BINDING)
    append_interleaved_candidate(
        completion_quarantine,
        "transcript_audio_transcript_audio",
    )
    mark_transcript_terminal(completion_quarantine)
    mark_remaining_terminals(completion_quarantine)
    completion = completion_quarantine.completion()
    assert completion is not None
    forged_completion = replace(completion)
    assert forged_completion == completion
    assert forged_completion is not completion

    with pytest.raises(CandidateQuarantineError, match="not_current"):
        completion_quarantine.require_current_completion(forged_completion)


def test_old_transcript_projection_is_rejected_after_late_invalid_frame() -> None:
    quarantine = open_quarantine()
    quarantine.bind_committed_turn(_BINDING)
    append_interleaved_candidate(
        quarantine,
        "transcript_audio_transcript_audio",
    )
    mark_transcript_terminal(quarantine)
    transcript = quarantine.transcript_completion()
    assert transcript is not None
    with pytest.raises(CandidateQuarantineError, match="generation"):
        quarantine.append_pcm_delta(
            event_id="provider_evt_late_wrong_generation",
            generation=2,
            response_id="resp_1",
            item_id="item_1",
            output_index=0,
            content_index=0,
            pcm_chunk=b"\x01\x02",
            audio_format_ref="audio-format://pcm16le-24000-mono",
            sample_rate_hz=24_000,
            channels=1,
        )

    with pytest.raises(CandidateQuarantineError, match="not_current"):
        quarantine.require_current_transcript_completion(transcript)


def test_old_full_projection_is_rejected_after_late_invalid_frame() -> None:
    quarantine = open_quarantine()
    quarantine.bind_committed_turn(_BINDING)
    append_interleaved_candidate(
        quarantine,
        "transcript_audio_transcript_audio",
    )
    mark_transcript_terminal(quarantine)
    mark_remaining_terminals(quarantine)
    completion = quarantine.completion()
    assert completion is not None
    with pytest.raises(CandidateQuarantineError, match="response_terminal"):
        quarantine.append_pcm_delta(
            event_id="provider_evt_late_after_completion",
            generation=1,
            response_id="resp_1",
            item_id="item_1",
            output_index=0,
            content_index=0,
            pcm_chunk=b"\x01\x02",
            audio_format_ref="audio-format://pcm16le-24000-mono",
            sample_rate_hz=24_000,
            channels=1,
        )

    with pytest.raises(CandidateQuarantineError, match="not_current"):
        quarantine.require_current_completion(completion)


def test_wipeable_pcm_buffer_releases_and_zeros_storage_in_place() -> None:
    pcm = WipeablePCMBuffer()
    pcm.append(b"pcm-secret-sentinel")
    controlled_storage_observation = pcm._storage

    assert bytes(controlled_storage_observation) == b"pcm-secret-sentinel"
    assert "pcm-secret-sentinel" not in repr(pcm)
    pcm.release()

    assert pcm.released is True
    assert all(value == 0 for value in controlled_storage_observation)
    with pytest.raises(CandidateQuarantineError, match="released"):
        pcm.append(b"late")
