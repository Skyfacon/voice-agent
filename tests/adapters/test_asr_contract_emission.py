from __future__ import annotations

from dataclasses import asdict

import pytest

from tests.adapters.test_mvp3_asr_adapter_contract import (
    ASR_OUTPUT_EVENT_NAME,
    _append_committed_audio_turn,
    _block_provider_runtime,
    _github_allowed_replay_manifest,
    _start_mvp3_asr_contract_session,
)
from voice_agent.adapters.asr_contract import AsrAdapterContract
from voice_agent.adapters.asr_normalization import (
    AsrNormalizationError,
    AsrRequestBinding,
    emit_normalized_asr_candidate,
    normalize_asr_candidate,
)
from voice_agent.events.envelope import validate_event_envelope
from voice_agent.replay.runner import run_replay_fixture
from voice_agent.runtime.adapter_callback_boundary import AdapterCallbackAppendBoundary


def test_validated_candidate_emits_asr_transcript_output_through_existing_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    startup = _start_mvp3_asr_contract_session(session_id="sess_asr_candidate_emit_success")
    committed_turn = _append_committed_audio_turn(startup.journal, event_id_prefix="evt_asr_candidate_emit_success")
    blocked_calls = _block_provider_runtime(monkeypatch)
    candidate = normalize_asr_candidate(
        binding=AsrRequestBinding.from_turn_committed_event(
            committed_turn,
            adapter_request_id="adapter_request_asr_candidate_emit_success",
        ),
        asr_frame_ref="asr-frame://synthetic/asr/candidate-emission/success",
        text_ref="text://synthetic/asr/candidate-emission/success",
        audio_timestamps_ref="timestamps://synthetic/asr/candidate-emission/success",
        timestamp_status="available",
        streaming_status="supported",
        output_mode="real",
    )
    contract = AsrAdapterContract(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="mvp3_asr",
        output_mode=candidate.output_mode,
    )

    emission = emit_normalized_asr_candidate(
        contract=contract,
        candidate=candidate,
        turn_committed_event=committed_turn,
        event_id="evt_asr_candidate_emit_success_transcript",
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
    )

    assert emission.degraded_events == ()
    assert emission.transcript_event["event_name"] == ASR_OUTPUT_EVENT_NAME
    assert emission.transcript_event["caused_by_event_id"] == committed_turn["event_id"]
    assert emission.transcript_event["asr_frame_ref"] == candidate.asr_frame_ref
    assert emission.transcript_event["text_ref"] == candidate.text_ref
    assert emission.transcript_event["audio_timestamps_ref"] == candidate.audio_timestamps_ref
    assert validate_event_envelope(emission.transcript_event) == emission.transcript_event

    replay_result = run_replay_fixture(
        {
            "replay_manifest": _github_allowed_replay_manifest(),
            "events": startup.journal.events(),
        }
    )
    assert replay_result.result_status == "passed"
    assert blocked_calls == []


@pytest.mark.parametrize(
    ("timestamp_status", "streaming_status", "audio_timestamps_ref", "expected_missing"),
    (
        ("unavailable", "supported", None, ["supports_audio_timestamps"]),
        (
            "available",
            "unsupported_final_only",
            "timestamps://synthetic/asr/candidate-emission/final-only",
            ["supports_streaming_output"],
        ),
    ),
)
def test_degraded_candidate_emits_degradation_before_transcript(
    timestamp_status: str,
    streaming_status: str,
    audio_timestamps_ref: str | None,
    expected_missing: list[str],
) -> None:
    startup = _start_mvp3_asr_contract_session(
        session_id=f"sess_asr_candidate_emit_{timestamp_status}_{streaming_status}"
    )
    committed_turn = _append_committed_audio_turn(
        startup.journal,
        event_id_prefix=f"evt_asr_candidate_emit_{timestamp_status}_{streaming_status}",
    )
    candidate = normalize_asr_candidate(
        binding=AsrRequestBinding.from_turn_committed_event(
            committed_turn,
            adapter_request_id=f"adapter_request_asr_candidate_{timestamp_status}_{streaming_status}",
        ),
        asr_frame_ref=f"asr-frame://synthetic/asr/candidate-emission/{timestamp_status}-{streaming_status}",
        text_ref=f"text://synthetic/asr/candidate-emission/{timestamp_status}-{streaming_status}",
        audio_timestamps_ref=audio_timestamps_ref,
        timestamp_status=timestamp_status,
        streaming_status=streaming_status,
        output_mode="degraded",
    )
    contract = AsrAdapterContract(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="mvp3_asr",
        output_mode=candidate.output_mode,
    )

    emission = emit_normalized_asr_candidate(
        contract=contract,
        candidate=candidate,
        turn_committed_event=committed_turn,
        event_id=f"evt_asr_candidate_emit_{timestamp_status}_{streaming_status}_transcript",
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
    )

    emitted = startup.journal.events()[-(len(expected_missing) + 1) :]
    assert [event["event_name"] for event in emitted] == [
        *["ADAPTER_OUTPUT_DEGRADED" for _ in expected_missing],
        ASR_OUTPUT_EVENT_NAME,
    ]
    assert [event["missing_capability"] for event in emitted[:-1]] == expected_missing
    assert emission.transcript_event == emitted[-1]
    assert [event["event_seq"] for event in emitted] == sorted(event["event_seq"] for event in emitted)


def test_unsafe_candidate_mapping_fails_before_event_append() -> None:
    startup = _start_mvp3_asr_contract_session(session_id="sess_asr_candidate_emit_unsafe")
    committed_turn = _append_committed_audio_turn(startup.journal, event_id_prefix="evt_asr_candidate_emit_unsafe")
    candidate = asdict(
        normalize_asr_candidate(
            binding=AsrRequestBinding.from_turn_committed_event(
                committed_turn,
                adapter_request_id="adapter_request_asr_candidate_unsafe",
            ),
            asr_frame_ref="asr-frame://synthetic/asr/candidate-emission/unsafe",
            text_ref="text://synthetic/asr/candidate-emission/unsafe",
            audio_timestamps_ref="timestamps://synthetic/asr/candidate-emission/unsafe",
            timestamp_status="available",
            streaming_status="supported",
            output_mode="real",
        )
    )
    candidate["provider_response"] = "response-ref://synthetic/forbidden"
    event_count = len(startup.journal.events())
    contract = AsrAdapterContract(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="mvp3_asr",
        output_mode="real",
    )

    with pytest.raises(AsrNormalizationError, match="forbidden"):
        emit_normalized_asr_candidate(
            contract=contract,
            candidate=candidate,
            turn_committed_event=committed_turn,
            event_id="evt_asr_candidate_emit_unsafe_transcript",
            created_monotonic_ms=210,
            created_wall_clock_ms=1700000000210,
        )

    assert len(startup.journal.events()) == event_count
