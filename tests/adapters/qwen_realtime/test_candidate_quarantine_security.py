from __future__ import annotations

import inspect

import pytest

from voice_agent.adapters.qwen_realtime.ephemeral_text_store import (
    EphemeralTextStore,
    EphemeralTextStoreError,
)
from voice_agent.adapters.qwen_realtime.quarantine import (
    CandidateLimitsV1,
    CandidateQuarantine,
    CandidateQuarantineError,
    CommittedCandidateBinding,
)


CORRELATION_FAILURE_CASES = (
    "wrong_response_id",
    "wrong_output_item_id",
    "wrong_output_index",
    "wrong_content_index",
    "duplicate_provider_audio_event_id",
    "audio_delta_after_audio_done",
    "cross_content_audio_delta",
    "extra_output_item",
    "extra_content_part",
    "function_call_output_ineligible",
    "response_done_output_item_mismatch",
    "missing_audio_done",
    "missing_response_terminal",
    "response_failed",
    "quarantine_overflow",
)

SECURITY_LIMITS = CandidateLimitsV1(
    max_transcript_unicode_scalars=80,
    max_pcm_bytes=128,
    max_pcm_chunks=4,
    max_audio_duration_ms=2000,
)
_PCM_SENTINEL = b"pcm-private-sentinel"
_TEXT_SENTINEL = "private-transcript-sentinel"
_BINDING = CommittedCandidateBinding(
    turn_id="turn_1",
    utterance_id="utt_1",
    context_snapshot_id="context_1",
)


def _open_bound_candidate(
    *,
    limits: CandidateLimitsV1 = SECURITY_LIMITS,
    text_store: EphemeralTextStore | None = None,
) -> CandidateQuarantine:
    quarantine = CandidateQuarantine(limits=limits, text_store=text_store)
    quarantine.open_response(
        event_id="evt_response_created",
        generation=1,
        response_id="resp_1",
        candidate_id="cand_1",
        playback_epoch=4,
        provisional_ingress_id="ingress_1",
        input_item_ref="qwen-input://synthetic/1",
    )
    quarantine.bind_committed_turn(_BINDING)
    quarantine.accept_assistant_item(
        event_id="evt_assistant",
        generation=1,
        response_id="resp_1",
        item_id="item_1",
        item_type="message",
        role="assistant",
    )
    quarantine.accept_output_item(
        event_id="evt_output",
        generation=1,
        response_id="resp_1",
        item_id="item_1",
        output_index=0,
        item_type="message",
    )
    quarantine.accept_content_part(
        event_id="evt_content",
        generation=1,
        response_id="resp_1",
        item_id="item_1",
        output_index=0,
        content_index=0,
        content_type="audio",
    )
    quarantine.append_transcript_delta(
        event_id="evt_text_seed",
        generation=1,
        response_id="resp_1",
        item_id="item_1",
        output_index=0,
        content_index=0,
        normalized_delta=_TEXT_SENTINEL,
    )
    quarantine.append_pcm_delta(
        event_id="evt_pcm_seed",
        generation=1,
        response_id="resp_1",
        item_id="item_1",
        output_index=0,
        content_index=0,
        pcm_chunk=_PCM_SENTINEL,
        audio_format_ref="audio-format://pcm16le-1000-mono",
        sample_rate_hz=1000,
        channels=1,
    )
    return quarantine


def _mark_transcript_done(
    quarantine: CandidateQuarantine,
    *,
    event_id: str = "evt_text_done",
) -> None:
    quarantine.mark_transcript_done(
        event_id=event_id,
        generation=1,
        response_id="resp_1",
        item_id="item_1",
        output_index=0,
        content_index=0,
    )


def _mark_audio_done(
    quarantine: CandidateQuarantine,
    *,
    event_id: str = "evt_audio_done",
) -> None:
    quarantine.mark_audio_done(
        event_id=event_id,
        generation=1,
        response_id="resp_1",
        item_id="item_1",
        output_index=0,
        content_index=0,
    )


def _mark_content_done(quarantine: CandidateQuarantine) -> None:
    quarantine.mark_content_done(
        event_id="evt_content_done",
        generation=1,
        response_id="resp_1",
        item_id="item_1",
        output_index=0,
        content_index=0,
        content_type="audio",
    )


def _mark_output_done(quarantine: CandidateQuarantine) -> None:
    quarantine.mark_output_item_done(
        event_id="evt_output_done",
        generation=1,
        response_id="resp_1",
        item_id="item_1",
        output_index=0,
        item_type="message",
    )


def _mark_response_done(
    quarantine: CandidateQuarantine,
    *,
    status: str = "completed",
    output_item_ids: tuple[str, ...] = ("item_1",),
) -> None:
    quarantine.mark_response_done(
        event_id="evt_response_done",
        generation=1,
        response_id="resp_1",
        status=status,
        output_item_ids=output_item_ids,
    )


def _invoke_failure_case(
    quarantine: CandidateQuarantine,
    case_id: str,
) -> str:
    common = {
        "generation": 1,
        "response_id": "resp_1",
        "item_id": "item_1",
        "output_index": 0,
        "content_index": 0,
    }
    audio = {
        **common,
        "pcm_chunk": b"\x01\x02",
        "audio_format_ref": "audio-format://pcm16le-1000-mono",
        "sample_rate_hz": 1000,
        "channels": 1,
    }

    try:
        if case_id == "wrong_response_id":
            quarantine.append_transcript_delta(
                event_id="evt_corrupt",
                normalized_delta="ignored",
                **{**common, "response_id": "raw-response-secret"},
            )
        elif case_id == "wrong_output_item_id":
            quarantine.append_pcm_delta(
                event_id="evt_corrupt",
                **{**audio, "item_id": "raw-item-secret"},
            )
        elif case_id == "wrong_output_index":
            quarantine.append_pcm_delta(
                event_id="evt_corrupt",
                **{**audio, "output_index": 9},
            )
        elif case_id in {"wrong_content_index", "cross_content_audio_delta"}:
            quarantine.append_pcm_delta(
                event_id="evt_corrupt",
                **{**audio, "content_index": 7},
            )
        elif case_id == "duplicate_provider_audio_event_id":
            quarantine.append_pcm_delta(event_id="evt_pcm_seed", **audio)
        elif case_id == "audio_delta_after_audio_done":
            _mark_audio_done(quarantine)
            quarantine.append_pcm_delta(event_id="evt_corrupt", **audio)
        elif case_id == "extra_output_item":
            quarantine.accept_output_item(
                event_id="evt_extra_output",
                generation=1,
                response_id="resp_1",
                item_id="item_2",
                output_index=1,
                item_type="message",
            )
        elif case_id == "extra_content_part":
            quarantine.accept_content_part(
                event_id="evt_extra_content",
                generation=1,
                response_id="resp_1",
                item_id="item_1",
                output_index=0,
                content_index=1,
                content_type="audio",
            )
        elif case_id == "function_call_output_ineligible":
            quarantine.accept_output_item(
                event_id="evt_function_call",
                generation=1,
                response_id="resp_1",
                item_id="function_item",
                output_index=1,
                item_type="function_call",
            )
        elif case_id == "response_done_output_item_mismatch":
            _mark_transcript_done(quarantine)
            _mark_audio_done(quarantine)
            _mark_content_done(quarantine)
            _mark_output_done(quarantine)
            _mark_response_done(
                quarantine,
                output_item_ids=("raw-output-secret",),
            )
        elif case_id == "missing_audio_done":
            _mark_transcript_done(quarantine)
            _mark_content_done(quarantine)
            _mark_output_done(quarantine)
            _mark_response_done(quarantine)
        elif case_id == "missing_response_terminal":
            _mark_transcript_done(quarantine)
            _mark_audio_done(quarantine)
            _mark_content_done(quarantine)
            _mark_output_done(quarantine)
            quarantine.discard(reason="missing_response_terminal")
            return ""
        elif case_id == "response_failed":
            _mark_response_done(quarantine, status="failed")
        elif case_id == "quarantine_overflow":
            quarantine.append_pcm_delta(
                event_id="evt_overflow",
                **{**audio, "pcm_chunk": b"\x05\x06" * 65},
            )
        else:  # pragma: no cover - table and dispatcher must stay synchronized
            raise AssertionError(f"unhandled case {case_id}")
    except CandidateQuarantineError as error:
        return str(error)
    raise AssertionError(f"{case_id} did not fail closed")


@pytest.mark.parametrize("case_id", CORRELATION_FAILURE_CASES, ids=lambda value: value)
def test_full_correlation_failure_matrix_wipes_and_disqualifies(
    case_id: str,
) -> None:
    quarantine = _open_bound_candidate()
    controlled_pcm = quarantine._pcm
    controlled_storage = controlled_pcm._storage

    error_text = _invoke_failure_case(quarantine, case_id)

    assert quarantine.completion() is None
    assert quarantine.disposition.status in {"DISCARDED", "INELIGIBLE"}
    assert controlled_pcm.released is True
    assert all(value == 0 for value in controlled_storage)
    observable_text = " ".join(
        (
            error_text,
            repr(quarantine),
            repr(quarantine.disposition),
            repr(controlled_pcm),
        )
    )
    assert _TEXT_SENTINEL not in observable_text
    assert _PCM_SENTINEL.decode("ascii") not in observable_text
    assert "raw-response-secret" not in observable_text
    assert "raw-item-secret" not in observable_text
    assert "raw-output-secret" not in observable_text


@pytest.mark.parametrize(
    ("event_id", "generation", "expected_error"),
    (
        ("", 1, "event_id"),
        ("evt_wrong_generation", 2, "generation"),
    ),
)
def test_every_provider_frame_requires_current_generation_and_nonempty_event_id(
    event_id: str,
    generation: int,
    expected_error: str,
) -> None:
    quarantine = _open_bound_candidate()
    controlled_storage = quarantine._pcm._storage

    with pytest.raises(CandidateQuarantineError, match=expected_error):
        quarantine.append_transcript_delta(
            event_id=event_id,
            generation=generation,
            response_id="resp_1",
            item_id="item_1",
            output_index=0,
            content_index=0,
            normalized_delta="not retained",
        )

    assert quarantine.disposition.status == "INELIGIBLE"
    assert quarantine._pcm.released is True
    assert all(value == 0 for value in controlled_storage)


def test_provider_event_ids_are_unique_across_frame_types() -> None:
    quarantine = _open_bound_candidate()
    controlled_storage = quarantine._pcm._storage

    with pytest.raises(CandidateQuarantineError, match="duplicate_event_id"):
        quarantine.mark_transcript_done(
            event_id="evt_pcm_seed",
            generation=1,
            response_id="resp_1",
            item_id="item_1",
            output_index=0,
            content_index=0,
        )

    assert quarantine.disposition.status == "INELIGIBLE"
    assert all(value == 0 for value in controlled_storage)


def test_every_provider_method_requires_generation_and_event_id_arguments() -> None:
    provider_method_names = (
        "open_response",
        "accept_assistant_item",
        "accept_output_item",
        "accept_content_part",
        "append_transcript_delta",
        "append_pcm_delta",
        "mark_transcript_done",
        "mark_audio_done",
        "mark_content_done",
        "mark_output_item_done",
        "mark_response_done",
    )

    for method_name in provider_method_names:
        parameters = inspect.signature(
            getattr(CandidateQuarantine, method_name)
        ).parameters
        assert parameters["generation"].default is inspect.Parameter.empty
        assert parameters["event_id"].default is inspect.Parameter.empty


@pytest.mark.parametrize(
    ("case_id", "event_id", "generation", "expected_error"),
    (
        ("missing_generation", "evt_missing_generation", None, "generation"),
        ("none_event_id", None, 1, "event_id"),
        ("empty_event_id", "", 1, "event_id"),
        ("wrong_generation", "evt_wrong_generation", 2, "generation"),
        ("duplicate_event_id", "evt_pcm_seed", 1, "duplicate_event_id"),
    ),
)
def test_direct_provider_correlation_failure_disqualifies_and_wipes(
    case_id: str,
    event_id: str | None,
    generation: int | None,
    expected_error: str,
) -> None:
    quarantine = _open_bound_candidate()
    controlled_storage = quarantine._pcm._storage

    with pytest.raises(CandidateQuarantineError, match=expected_error):
        quarantine.append_transcript_delta(
            event_id=event_id,  # type: ignore[arg-type]
            generation=generation,  # type: ignore[arg-type]
            response_id="resp_1",
            item_id="item_1",
            output_index=0,
            content_index=0,
            normalized_delta=case_id,
        )

    assert quarantine.disposition.status == "INELIGIBLE"
    assert quarantine.completion() is None
    assert quarantine._pcm.released is True
    assert all(value == 0 for value in controlled_storage)


@pytest.mark.parametrize(
    "late_frame",
    (
        "transcript_delta",
        "pcm_delta",
        "transcript_terminal",
        "audio_terminal",
    ),
)
def test_content_terminal_closes_all_child_frames(late_frame: str) -> None:
    quarantine = _open_bound_candidate()
    _mark_transcript_done(quarantine)
    _mark_audio_done(quarantine)
    _mark_content_done(quarantine)
    controlled_storage = quarantine._pcm._storage
    common = {
        "generation": 1,
        "response_id": "resp_1",
        "item_id": "item_1",
        "output_index": 0,
        "content_index": 0,
    }

    with pytest.raises(
        CandidateQuarantineError,
        match="content_lifecycle_closed",
    ):
        if late_frame == "transcript_delta":
            quarantine.append_transcript_delta(
                event_id="evt_late_text_after_content",
                normalized_delta="late",
                **common,
            )
        elif late_frame == "pcm_delta":
            quarantine.append_pcm_delta(
                event_id="evt_late_pcm_after_content",
                pcm_chunk=b"\x01\x02",
                audio_format_ref="audio-format://pcm16le-1000-mono",
                sample_rate_hz=1000,
                channels=1,
                **common,
            )
        elif late_frame == "transcript_terminal":
            quarantine.mark_transcript_done(
                event_id="evt_late_text_done_after_content",
                **common,
            )
        else:
            quarantine.mark_audio_done(
                event_id="evt_late_audio_done_after_content",
                **common,
            )

    assert quarantine.disposition.status == "INELIGIBLE"
    assert quarantine.completion() is None
    assert quarantine._pcm.released is True
    assert all(value == 0 for value in controlled_storage)


@pytest.mark.parametrize(
    "late_frame",
    (
        "content_part",
        "transcript_delta",
        "pcm_delta",
        "content_terminal",
    ),
)
def test_output_terminal_closes_all_content_frames(late_frame: str) -> None:
    quarantine = _open_bound_candidate()
    _mark_transcript_done(quarantine)
    _mark_audio_done(quarantine)
    _mark_content_done(quarantine)
    _mark_output_done(quarantine)
    controlled_storage = quarantine._pcm._storage
    common = {
        "generation": 1,
        "response_id": "resp_1",
        "item_id": "item_1",
        "output_index": 0,
    }

    with pytest.raises(
        CandidateQuarantineError,
        match="output_item_lifecycle_closed",
    ):
        if late_frame == "content_part":
            quarantine.accept_content_part(
                event_id="evt_late_content_part",
                content_index=1,
                content_type="audio",
                **common,
            )
        elif late_frame == "transcript_delta":
            quarantine.append_transcript_delta(
                event_id="evt_late_text_after_output",
                content_index=0,
                normalized_delta="late",
                **common,
            )
        elif late_frame == "pcm_delta":
            quarantine.append_pcm_delta(
                event_id="evt_late_pcm_after_output",
                content_index=0,
                pcm_chunk=b"\x01\x02",
                audio_format_ref="audio-format://pcm16le-1000-mono",
                sample_rate_hz=1000,
                channels=1,
                **common,
            )
        else:
            quarantine.mark_content_done(
                event_id="evt_late_content_done_after_output",
                content_index=0,
                content_type="audio",
                **common,
            )

    assert quarantine.disposition.status == "INELIGIBLE"
    assert quarantine.completion() is None
    assert quarantine._pcm.released is True
    assert all(value == 0 for value in controlled_storage)


def test_content_cannot_close_before_transcript_and_audio_terminals() -> None:
    quarantine = _open_bound_candidate()
    controlled_storage = quarantine._pcm._storage

    with pytest.raises(
        CandidateQuarantineError,
        match="content_terminal_before_children",
    ):
        _mark_content_done(quarantine)

    assert quarantine.disposition.status == "INELIGIBLE"
    assert quarantine._pcm.released is True
    assert all(value == 0 for value in controlled_storage)


def test_output_cannot_close_before_content_terminal() -> None:
    quarantine = _open_bound_candidate()
    controlled_storage = quarantine._pcm._storage

    with pytest.raises(
        CandidateQuarantineError,
        match="output_terminal_before_content",
    ):
        _mark_output_done(quarantine)

    assert quarantine.disposition.status == "INELIGIBLE"
    assert quarantine._pcm.released is True
    assert all(value == 0 for value in controlled_storage)


def test_cast_wide_memoryview_uses_nbytes_for_overflow_preflight() -> None:
    limits = CandidateLimitsV1(
        max_transcript_unicode_scalars=80,
        max_pcm_bytes=24,
        max_pcm_chunks=4,
        max_audio_duration_ms=2000,
    )
    quarantine = _open_bound_candidate(limits=limits)
    controlled_storage = quarantine._pcm._storage
    wide_view = memoryview(bytearray(b"\x01\x02\x03\x04\x05\x06\x07\x08")).cast(
        "Q"
    )

    with pytest.raises(CandidateQuarantineError, match="quarantine_overflow"):
        quarantine.append_pcm_delta(
            event_id="evt_wide_view_overflow",
            generation=1,
            response_id="resp_1",
            item_id="item_1",
            output_index=0,
            content_index=0,
            pcm_chunk=wide_view,
            audio_format_ref="audio-format://pcm16le-1000-mono",
            sample_rate_hz=1000,
            channels=1,
        )

    assert quarantine.disposition.status == "INELIGIBLE"
    assert quarantine._pcm.released is True
    assert all(value == 0 for value in controlled_storage)


def test_cast_wide_memoryview_manifest_uses_the_same_byte_fact() -> None:
    quarantine = _open_bound_candidate()
    wide_view = memoryview(bytearray(b"\x01\x02\x03\x04\x05\x06\x07\x08")).cast(
        "Q"
    )
    quarantine.append_pcm_delta(
        event_id="evt_wide_view_accepted",
        generation=1,
        response_id="resp_1",
        item_id="item_1",
        output_index=0,
        content_index=0,
        pcm_chunk=wide_view,
        audio_format_ref="audio-format://pcm16le-1000-mono",
        sample_rate_hz=1000,
        channels=1,
    )
    _mark_transcript_done(quarantine)
    _mark_audio_done(quarantine)

    assert quarantine._pcm_manifest is not None
    assert quarantine._pcm_manifest.pcm_byte_count == 28
    assert quarantine._pcm_manifest.observed_pcm_chunk_count == 2


@pytest.mark.parametrize(
    ("case_id", "pcm_chunk"),
    (
        (
            "noncontiguous",
            memoryview(bytearray(b"\x01\x02\x03\x04\x05\x06"))[::2],
        ),
        (
            "multidimensional",
            memoryview(bytearray(b"\x01\x02\x03\x04\x05\x06\x07\x08")).cast(
                "B",
                shape=(2, 4),
            ),
        ),
        ("bool", True),
        ("empty", memoryview(bytearray())),
    ),
)
def test_unsafe_pcm_views_fail_closed_without_builtin_exception_leak(
    case_id: str,
    pcm_chunk: object,
) -> None:
    quarantine = _open_bound_candidate()
    controlled_storage = quarantine._pcm._storage

    with pytest.raises(CandidateQuarantineError, match="invalid_pcm_chunk"):
        quarantine.append_pcm_delta(
            event_id=f"evt_invalid_pcm_{case_id}",
            generation=1,
            response_id="resp_1",
            item_id="item_1",
            output_index=0,
            content_index=0,
            pcm_chunk=pcm_chunk,  # type: ignore[arg-type]
            audio_format_ref="audio-format://pcm16le-1000-mono",
            sample_rate_hz=1000,
            channels=1,
        )

    assert quarantine.disposition.status == "INELIGIBLE"
    assert quarantine.completion() is None
    assert quarantine._pcm.released is True
    assert all(value == 0 for value in controlled_storage)


def test_pcm_view_aliasing_owned_storage_cannot_leak_buffer_error() -> None:
    quarantine = _open_bound_candidate()
    controlled_storage = quarantine._pcm._storage
    aliasing_view = memoryview(controlled_storage)

    with pytest.raises(CandidateQuarantineError, match="invalid_pcm_chunk"):
        quarantine.append_pcm_delta(
            event_id="evt_aliasing_pcm_view",
            generation=1,
            response_id="resp_1",
            item_id="item_1",
            output_index=0,
            content_index=0,
            pcm_chunk=aliasing_view,
            audio_format_ref="audio-format://pcm16le-1000-mono",
            sample_rate_hz=1000,
            channels=1,
        )

    assert quarantine.disposition.status == "INELIGIBLE"
    assert quarantine._pcm.released is True
    assert all(value == 0 for value in controlled_storage)
    aliasing_view.release()


def test_invalid_empty_item_identity_uses_terminal_wipe_path() -> None:
    quarantine = CandidateQuarantine(limits=SECURITY_LIMITS)
    quarantine.open_response(
        event_id="evt_response_created",
        generation=1,
        response_id="resp_1",
        candidate_id="cand_1",
        playback_epoch=4,
        provisional_ingress_id="ingress_1",
        input_item_ref="qwen-input://synthetic/1",
    )

    with pytest.raises(CandidateQuarantineError, match="output_item_id"):
        quarantine.accept_assistant_item(
            event_id="evt_empty_item",
            generation=1,
            response_id="resp_1",
            item_id="",
            item_type="message",
            role="assistant",
        )

    assert quarantine.disposition.status == "INELIGIBLE"
    assert quarantine._pcm.released is True


def test_second_response_permanently_disqualifies_and_wipes_first() -> None:
    quarantine = _open_bound_candidate()
    controlled_storage = quarantine._pcm._storage

    with pytest.raises(CandidateQuarantineError, match="second_response"):
        quarantine.open_response(
            event_id="evt_second_response_created",
            generation=1,
            response_id="resp_2",
            candidate_id="cand_2",
            playback_epoch=4,
            provisional_ingress_id="ingress_1",
            input_item_ref="qwen-input://synthetic/1",
        )

    assert quarantine.completion() is None
    assert quarantine.disposition.status == "INELIGIBLE"
    assert all(value == 0 for value in controlled_storage)


def test_spawn_successor_rejects_not_open_and_active_predecessors() -> None:
    unopened = CandidateQuarantine(limits=SECURITY_LIMITS)
    with pytest.raises(CandidateQuarantineError, match="predecessor_not_terminal"):
        unopened.spawn_successor()

    active = _open_bound_candidate()
    with pytest.raises(CandidateQuarantineError, match="predecessor_not_terminal"):
        active.spawn_successor()


def test_late_frame_after_full_completion_revokes_completion_and_wipes() -> None:
    quarantine = _open_bound_candidate()
    _mark_transcript_done(quarantine)
    _mark_audio_done(quarantine)
    _mark_content_done(quarantine)
    _mark_output_done(quarantine)
    _mark_response_done(quarantine)
    assert quarantine.completion() is not None
    controlled_storage = quarantine._pcm._storage

    with pytest.raises(CandidateQuarantineError, match="response_terminal"):
        quarantine.append_pcm_delta(
            event_id="evt_late_pcm",
            generation=1,
            response_id="resp_1",
            item_id="item_1",
            output_index=0,
            content_index=0,
            pcm_chunk=b"\x01\x02",
            audio_format_ref="audio-format://pcm16le-1000-mono",
            sample_rate_hz=1000,
            channels=1,
        )

    assert quarantine.completion() is None
    assert quarantine.disposition.status == "INELIGIBLE"
    assert quarantine._pcm.released is True
    assert all(value == 0 for value in controlled_storage)


@pytest.mark.parametrize(
    ("normalized_delta", "expected_error"),
    (
        ("x" * 81, "transcript_overflow"),
        ("bad\ud800scalar", "invalid_unicode"),
    ),
    ids=("candidate_81_unicode_scalars", "candidate_unpaired_surrogate"),
)
def test_invalid_candidate_unicode_never_yields_either_completion_stage(
    normalized_delta: str,
    expected_error: str,
) -> None:
    quarantine = _open_bound_candidate()
    controlled_storage = quarantine._pcm._storage

    with pytest.raises(CandidateQuarantineError, match=expected_error) as raised:
        quarantine.append_transcript_delta(
            event_id="evt_invalid_unicode",
            generation=1,
            response_id="resp_1",
            item_id="item_1",
            output_index=0,
            content_index=0,
            normalized_delta=normalized_delta,
        )

    assert quarantine.transcript_completion() is None
    assert quarantine.completion() is None
    assert quarantine.disposition.status == "INELIGIBLE"
    assert quarantine._pcm.released is True
    assert all(value == 0 for value in controlled_storage)
    assert normalized_delta not in str(raised.value)


def test_candidate_limit_above_80_is_rejected() -> None:
    with pytest.raises(ValueError, match="max_transcript_unicode_scalars"):
        CandidateLimitsV1(
            max_transcript_unicode_scalars=81,
            max_pcm_bytes=4096,
            max_pcm_chunks=8,
            max_audio_duration_ms=2000,
        )


def test_stale_candidate_text_ref_fails_closed_and_discard_wipes_pcm() -> None:
    text_store = EphemeralTextStore()
    quarantine = _open_bound_candidate(text_store=text_store)
    _mark_transcript_done(quarantine)
    transcript = quarantine.transcript_completion()
    assert transcript is not None
    controlled_pcm_storage = quarantine._pcm._storage
    controlled_text_storage = text_store._entries[transcript.candidate_ref]._storage

    text_store.discard(transcript.candidate_ref)
    with pytest.raises(EphemeralTextStoreError, match="not_found"):
        with text_store.resolve(
            transcript.candidate_ref,
            expected_kind="candidate",
            expected_digest=transcript.candidate_transcript_digest,
            max_unicode_scalars=80,
        ):
            pytest.fail("stale candidate text ref must not resolve")
    quarantine.discard(reason="candidate_text_unavailable")

    assert all(value == 0 for value in controlled_text_storage)
    assert all(value == 0 for value in controlled_pcm_storage)
    assert quarantine.completion() is None


def test_discard_reason_cannot_turn_caller_text_into_diagnostics() -> None:
    quarantine = _open_bound_candidate()
    caller_secret = "private_secret_value"

    disposition = quarantine.discard(reason=caller_secret)

    assert disposition.reason_code == "discarded"
    assert caller_secret not in repr(disposition)
    with pytest.raises(CandidateQuarantineError) as raised:
        quarantine.bind_committed_turn(_BINDING)
    assert caller_secret not in str(raised.value)


def test_stale_candidate_text_ref_cannot_reach_full_completion() -> None:
    text_store = EphemeralTextStore()
    quarantine = _open_bound_candidate(text_store=text_store)
    _mark_transcript_done(quarantine)
    transcript = quarantine.transcript_completion()
    assert transcript is not None
    controlled_pcm_storage = quarantine._pcm._storage
    text_store.discard(transcript.candidate_ref)
    _mark_audio_done(quarantine)
    _mark_content_done(quarantine)
    _mark_output_done(quarantine)

    with pytest.raises(CandidateQuarantineError, match="text_store"):
        _mark_response_done(quarantine)

    assert quarantine.completion() is None
    assert quarantine.disposition.status == "INELIGIBLE"
    assert quarantine._pcm.released is True
    assert all(value == 0 for value in controlled_pcm_storage)


def _completed_pcm_digest(
    *,
    chunks: tuple[bytes, ...],
    audio_format_ref: str = "audio-format://pcm16le-1000-mono",
    sample_rate_hz: int = 1000,
    channels: int = 1,
) -> str:
    limits = CandidateLimitsV1(
        max_transcript_unicode_scalars=80,
        max_pcm_bytes=4096,
        max_pcm_chunks=8,
        max_audio_duration_ms=2000,
    )
    quarantine = CandidateQuarantine(limits=limits)
    quarantine.open_response(
        event_id="manifest_response_created",
        generation=1,
        response_id="resp_1",
        candidate_id="cand_manifest",
        playback_epoch=0,
        provisional_ingress_id="ingress_manifest",
        input_item_ref="qwen-input://synthetic/manifest",
    )
    quarantine.bind_committed_turn(_BINDING)
    quarantine.accept_assistant_item(
        event_id="manifest_assistant",
        generation=1,
        response_id="resp_1",
        item_id="item_1",
        item_type="message",
        role="assistant",
    )
    quarantine.accept_output_item(
        event_id="manifest_output",
        generation=1,
        response_id="resp_1",
        item_id="item_1",
        output_index=0,
        item_type="message",
    )
    quarantine.accept_content_part(
        event_id="manifest_content",
        generation=1,
        response_id="resp_1",
        item_id="item_1",
        output_index=0,
        content_index=0,
        content_type="audio",
    )
    quarantine.append_transcript_delta(
        event_id="manifest_text",
        generation=1,
        response_id="resp_1",
        item_id="item_1",
        output_index=0,
        content_index=0,
        normalized_delta="safe",
    )
    for index, chunk in enumerate(chunks, start=1):
        quarantine.append_pcm_delta(
            event_id=f"manifest_pcm_{index}",
            generation=1,
            response_id="resp_1",
            item_id="item_1",
            output_index=0,
            content_index=0,
            pcm_chunk=chunk,
            audio_format_ref=audio_format_ref,
            sample_rate_hz=sample_rate_hz,
            channels=channels,
        )
    _mark_transcript_done(quarantine, event_id="manifest_text_done")
    _mark_audio_done(quarantine, event_id="manifest_audio_done")
    _mark_content_done(quarantine)
    _mark_output_done(quarantine)
    _mark_response_done(quarantine)
    completion = quarantine.completion()
    assert completion is not None
    return completion.eligibility_facts.candidate_pcm_manifest_digest


def test_pcm_manifest_digest_commits_format_rate_channels_order_and_content() -> None:
    baseline = _completed_pcm_digest(chunks=(b"\x01\x02", b"\x03\x04"))
    variants = {
        _completed_pcm_digest(chunks=(b"\x01\x02\x03\x04",)),
        _completed_pcm_digest(chunks=(b"\x01\x02", b"\x05\x06")),
        _completed_pcm_digest(
            chunks=(b"\x01\x02", b"\x03\x04"),
            audio_format_ref="audio-format://pcm16le-alt",
        ),
        _completed_pcm_digest(
            chunks=(b"\x01\x02", b"\x03\x04"),
            sample_rate_hz=2000,
        ),
        _completed_pcm_digest(
            chunks=(b"\x01\x02", b"\x03\x04"),
            channels=2,
        ),
    }

    assert baseline not in variants
    assert len(variants) == 5


def test_completion_has_no_public_pcm_redemption_or_content_resolver() -> None:
    quarantine = _open_bound_candidate()
    public_names = {
        name
        for name in dir(quarantine)
        if not name.startswith("_")
    }

    assert not public_names & {
        "pcm",
        "pcm_buffer",
        "redeem_pcm",
        "release_pcm",
        "resolve_text",
        "text",
    }
