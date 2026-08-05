from __future__ import annotations

from dataclasses import asdict, replace

import pytest

from voice_agent.adapters.adapter_timing import AdapterTimingSnapshot
from voice_agent.adapters.fast_interaction_contract import (
    FAST_INTERACTION_SCHEMA_NAME,
    FastInteractionBinding,
    FastInteractionOutput,
    FastInteractionValidationError,
    emit_fast_interaction_events,
)
from voice_agent.events.envelope import validate_event_envelope
from voice_agent.events.journal import InMemoryEventJournal
from voice_agent.runtime.adapter_callback_boundary import AdapterCallbackAppendBoundary


def test_audio_native_binding_uses_committed_turn_audio_ref_without_asr_text() -> None:
    _, turn, _ = _journal_with_asr_output("audio_native_binding")

    binding = FastInteractionBinding.from_turn_audio(
        turn,
        adapter_request_id="adapter_request_fast_interaction_audio_native",
        audio_frame_ref="audio-frame://synthetic/fast-interaction/audio-native",
    )

    assert binding.input_modality == "audio"
    assert binding.input_mode == "audio_native"
    assert binding.audio_frame_ref == "audio-frame://synthetic/fast-interaction/audio-native"
    assert binding.audio_payload_ref is None
    assert binding.asr_output_event_id is None
    assert binding.asr_frame_ref is None
    assert binding.text_ref is None
    assert binding.source_event_ids == (turn["event_id"],)


def test_audio_native_binding_accepts_safe_audio_payload_ref() -> None:
    _, turn, _ = _journal_with_asr_output("audio_native_payload_binding")

    binding = FastInteractionBinding.from_turn_audio(
        turn,
        adapter_request_id="adapter_request_fast_interaction_audio_payload_native",
        audio_payload_ref="audio-payload://synthetic/fast-interaction/audio-native",
    )

    assert binding.input_mode == "audio_native"
    assert binding.audio_frame_ref is None
    assert binding.audio_payload_ref == "audio-payload://synthetic/fast-interaction/audio-native"


@pytest.mark.parametrize(
    "unsafe_audio_ref",
    (
        "audio-frame://synthetic/audio/raw/chunk",
        "audio-payload://synthetic/provider_response/body",
        "audio-frame://synthetic/diagnostics/capture",
        "file:///tmp/voice-agent/audio.wav",
        "/tmp/voice-agent/audio.wav",
        "audio-payload://synthetic/raw-transcript-leak",
        "audio-frame://synthetic?token=secret",
    ),
)
def test_audio_native_binding_rejects_unsafe_audio_refs(unsafe_audio_ref: str) -> None:
    _, turn, _ = _journal_with_asr_output("audio_native_unsafe_ref")

    with pytest.raises(FastInteractionValidationError):
        FastInteractionBinding.from_turn_audio(
            turn,
            adapter_request_id="adapter_request_fast_interaction_audio_native_unsafe",
            audio_frame_ref=unsafe_audio_ref,
        )


def test_audio_native_binding_requires_audio_modality_and_audio_ref() -> None:
    _, turn, _ = _journal_with_asr_output("audio_native_requires_audio")

    with pytest.raises(FastInteractionValidationError, match="audio ref"):
        FastInteractionBinding.from_turn_audio(
            turn,
            adapter_request_id="adapter_request_fast_interaction_audio_native_missing_ref",
        )

    with pytest.raises(FastInteractionValidationError, match="input_modality='audio'"):
        FastInteractionBinding.from_turn_audio(
            dict(turn, input_modality="text"),
            adapter_request_id="adapter_request_fast_interaction_audio_native_text",
            audio_frame_ref="audio-frame://synthetic/fast-interaction/audio-native",
        )


def test_asr_text_fallback_binding_is_explicit_and_legacy_constructor_delegates() -> None:
    _, turn, asr_output = _journal_with_asr_output("asr_text_fallback_binding")

    fallback = FastInteractionBinding.from_turn_and_asr_fallback(
        turn,
        asr_output_event=asr_output,
        adapter_request_id="adapter_request_fast_interaction_asr_text_fallback",
    )
    legacy = FastInteractionBinding.from_turn_and_asr(
        turn,
        asr_output_event=asr_output,
        adapter_request_id="adapter_request_fast_interaction_legacy_asr_text_fallback",
    )

    assert fallback.input_mode == "asr_text_fallback"
    assert fallback.asr_output_event_id == asr_output["event_id"]
    assert fallback.asr_frame_ref == asr_output["asr_frame_ref"]
    assert fallback.text_ref == asr_output["text_ref"]
    assert fallback.audio_frame_ref is None
    assert fallback.audio_payload_ref is None
    assert fallback.source_event_ids == (turn["event_id"], asr_output["event_id"])
    assert legacy.input_mode == "asr_text_fallback"


def test_emit_output_with_reply_candidate_appends_output_then_candidate() -> None:
    journal, turn, asr_output = _journal_with_asr_output("with_candidate")
    binding = FastInteractionBinding.from_turn_and_asr(
        turn,
        asr_output_event=asr_output,
        adapter_request_id="adapter_request_fast_interaction_with_candidate",
    )
    output = _fast_output(reply_candidate_ref="candidate://synthetic/fast/with-candidate")

    emission = emit_fast_interaction_events(
        boundary=AdapterCallbackAppendBoundary(journal),
        binding=binding,
        output=output,
        output_event_id="evt_fast_interaction_output_with_candidate",
        candidate_event_id="evt_foreground_reply_candidate_with_candidate",
        created_monotonic_ms=30,
        created_wall_clock_ms=1700000000030,
    )

    emitted = journal.events()[-2:]
    assert emission.output_event == emitted[0]
    assert emission.candidate_event == emitted[1]
    assert [event["event_name"] for event in emitted] == [
        "FAST_INTERACTION_OUTPUT_EMITTED",
        "FOREGROUND_REPLY_CANDIDATE_EMITTED",
    ]
    assert emitted[0]["caused_by_event_id"] == asr_output["event_id"]
    assert emitted[1]["caused_by_event_id"] == emitted[0]["event_id"]
    assert emitted[0]["adapter_id"] == "fast_interaction_contract_test"
    assert emitted[0]["adapter_type"] == "fast_interaction"
    assert emitted[0]["adapter_request_id"] == binding.adapter_request_id
    assert emitted[0]["turn_id"] == turn["turn_id"]
    assert emitted[0]["utterance_id"] == turn["utterance_id"]
    assert emitted[0]["route_hint_ref"] == "route-hint://synthetic/fast/contract"
    assert emitted[0]["route_prelude_ref"] == "route-prelude://synthetic/fast/contract"
    assert emitted[0]["foreground_act"] == "ANSWER"
    assert emitted[0]["final_fast_evidence_ref"] == "evidence://synthetic/fast/contract"
    assert emitted[0]["schema_name"] == FAST_INTERACTION_SCHEMA_NAME
    assert emitted[0]["normalization_status"] == "normalized"
    assert emitted[0]["output_mode"] == "mock"
    assert emitted[0]["input_modality"] == "audio"
    assert emitted[0]["input_mode"] == "asr_text_fallback"
    assert emitted[0]["fast_interaction_input_mode"] == "asr_text_fallback"
    assert emitted[0]["source_event_ids"] == (
        turn["event_id"],
        asr_output["event_id"],
    )
    assert emitted[0]["risk_tags"] == ("low_risk", "no_side_effects")
    assert emitted[0]["confidence"] == 0.91
    assert emitted[0]["risk_class"] == "LOW"

    assert emitted[1]["candidate_id"] == "candidate_fast_contract"
    assert emitted[1]["fast_interaction_output_event_id"] == emitted[0]["event_id"]
    assert emitted[1]["turn_id"] == turn["turn_id"]
    assert emitted[1]["utterance_id"] == turn["utterance_id"]
    assert emitted[1]["candidate_ref"] == "candidate://synthetic/fast/with-candidate"
    assert emitted[1]["candidate_status"] == "complete"
    assert emitted[1]["input_mode"] == "asr_text_fallback"
    assert emitted[1]["fast_interaction_input_mode"] == "asr_text_fallback"
    assert emitted[1]["source_event_ids"] == (emitted[0]["event_id"],)
    assert emitted[1]["risk_tags"] == ("low_risk", "no_side_effects")
    assert emitted[1]["confidence"] == 0.91
    assert emitted[1]["trace_redaction_level"] == "metadata_only"
    assert all(validate_event_envelope(event) == event for event in emitted)


def test_emit_output_without_reply_candidate_appends_only_output() -> None:
    journal, turn, asr_output = _journal_with_asr_output("without_candidate")
    binding = FastInteractionBinding.from_turn_and_asr(
        turn,
        asr_output_event=asr_output,
        adapter_request_id="adapter_request_fast_interaction_without_candidate",
    )

    emission = emit_fast_interaction_events(
        boundary=AdapterCallbackAppendBoundary(journal),
        binding=binding,
        output=_fast_output(reply_candidate_ref=None),
        output_event_id="evt_fast_interaction_output_without_candidate",
        created_monotonic_ms=30,
        created_wall_clock_ms=1700000000030,
    )

    emitted = journal.events()[-1:]
    assert emitted[0]["event_name"] == "FAST_INTERACTION_OUTPUT_EMITTED"
    assert emission.output_event == emitted[0]
    assert emission.candidate_event is None
    assert "candidate_ref" not in emitted[0]


def test_emit_audio_native_output_uses_turn_source_and_sanitized_timing_metadata() -> None:
    journal, turn, _ = _journal_with_asr_output("audio_native_emit")
    binding = FastInteractionBinding.from_turn_audio(
        turn,
        adapter_request_id="adapter_request_fast_interaction_audio_native_emit",
        audio_frame_ref="audio-frame://synthetic/fast-interaction/audio-native-emit",
    )

    emission = emit_fast_interaction_events(
        boundary=AdapterCallbackAppendBoundary(journal),
        binding=binding,
        output=_fast_output(reply_candidate_ref="candidate://synthetic/fast/audio-native-emit"),
        output_event_id="evt_fast_interaction_output_audio_native_emit",
        candidate_event_id="evt_foreground_reply_candidate_audio_native_emit",
        created_monotonic_ms=30,
        created_wall_clock_ms=1700000000030,
        timing_snapshot=_timing_snapshot(),
    )

    assert emission.output_event["caused_by_event_id"] == turn["event_id"]
    assert emission.output_event["input_mode"] == "audio_native"
    assert emission.output_event["fast_interaction_input_mode"] == "audio_native"
    assert emission.output_event["source_event_ids"] == (turn["event_id"],)
    assert emission.output_event["audio_frame_ref"] == (
        "audio-frame://synthetic/fast-interaction/audio-native-emit"
    )
    assert "audio_payload_ref" not in emission.output_event
    assert emission.output_event["fast_interaction_provider_ttft_ms"] == 40
    assert emission.output_event["fast_interaction_ttft_available"] is True
    assert emission.output_event["fast_interaction_timing_mode"] == "streaming"

    assert emission.candidate_event is not None
    assert emission.candidate_event["input_mode"] == "audio_native"
    assert emission.candidate_event["fast_interaction_input_mode"] == "audio_native"
    assert emission.candidate_event["source_event_ids"] == (
        emission.output_event["event_id"],
    )


@pytest.mark.parametrize(
    "malicious_metadata",
    (
        {"fast_interaction_provider_ttft_ms": -1},
        {"fast_interaction_provider_ttft_ms": True},
        {"fast_interaction_ttft_available": 1},
        {"fast_interaction_timing_mode": "provider://raw-body"},
        {"fast_interaction_ttft_source": "raw_prompt"},
        {"fast_interaction_provider_ttft_ms": {"nested": 1}},
        {"fast_interaction_provider_ttft_ms": [1]},
        {"fast_interaction_provider_text": "provider_response"},
        {"fast_interaction_input_mode": "audio_native"},
        {"trace_redaction_level": "full"},
    ),
)
def test_emit_rejects_malicious_fast_interaction_timing_metadata(
    malicious_metadata: dict[str, object],
) -> None:
    journal, turn, _ = _journal_with_asr_output("malicious_timing_metadata")
    binding = FastInteractionBinding.from_turn_audio(
        turn,
        adapter_request_id="adapter_request_fast_interaction_malicious_timing",
        audio_frame_ref="audio-frame://synthetic/fast-interaction/malicious-timing",
    )

    with pytest.raises(FastInteractionValidationError):
        emit_fast_interaction_events(
            boundary=AdapterCallbackAppendBoundary(journal),
            binding=binding,
            output=_fast_output(reply_candidate_ref=None),
            output_event_id="evt_fast_interaction_output_malicious_timing",
            created_monotonic_ms=30,
            created_wall_clock_ms=1700000000030,
            timing_snapshot=_MaliciousTimingSnapshot(malicious_metadata),
        )


def test_emit_rejects_timing_snapshot_that_does_not_return_mapping() -> None:
    journal, turn, _ = _journal_with_asr_output("malicious_timing_non_mapping")
    binding = FastInteractionBinding.from_turn_audio(
        turn,
        adapter_request_id="adapter_request_fast_interaction_non_mapping_timing",
        audio_frame_ref="audio-frame://synthetic/fast-interaction/non-mapping-timing",
    )

    with pytest.raises(FastInteractionValidationError):
        emit_fast_interaction_events(
            boundary=AdapterCallbackAppendBoundary(journal),
            binding=binding,
            output=_fast_output(reply_candidate_ref=None),
            output_event_id="evt_fast_interaction_output_non_mapping_timing",
            created_monotonic_ms=30,
            created_wall_clock_ms=1700000000030,
            timing_snapshot=_MaliciousTimingSnapshot(["not", "a", "mapping"]),
        )


def test_emit_reply_candidate_requires_candidate_event_id_before_appending_fast_events() -> None:
    journal, turn, asr_output = _journal_with_asr_output("missing_candidate_event_id")
    binding = FastInteractionBinding.from_turn_and_asr(
        turn,
        asr_output_event=asr_output,
        adapter_request_id="adapter_request_fast_interaction_missing_candidate_event_id",
    )
    event_count_before = len(journal.events())

    with pytest.raises(FastInteractionValidationError):
        emit_fast_interaction_events(
            boundary=AdapterCallbackAppendBoundary(journal),
            binding=binding,
            output=_fast_output(reply_candidate_ref="candidate://synthetic/fast/missing-event-id"),
            output_event_id="evt_fast_interaction_output_missing_candidate_event_id",
            created_monotonic_ms=30,
            created_wall_clock_ms=1700000000030,
        )

    assert len(journal.events()) == event_count_before
    assert not any(
        event["event_name"]
        in {"FAST_INTERACTION_OUTPUT_EMITTED", "FOREGROUND_REPLY_CANDIDATE_EMITTED"}
        for event in journal.events()
    )


def test_emit_reply_candidate_rejects_duplicate_candidate_event_id_before_appending_fast_events() -> None:
    journal, turn, asr_output = _journal_with_asr_output("duplicate_candidate_event_id")
    binding = FastInteractionBinding.from_turn_and_asr(
        turn,
        asr_output_event=asr_output,
        adapter_request_id="adapter_request_fast_interaction_duplicate_candidate_event_id",
    )
    event_count_before = len(journal.events())
    duplicate_event_id = str(journal.events()[0]["event_id"])

    with pytest.raises(FastInteractionValidationError):
        emit_fast_interaction_events(
            boundary=AdapterCallbackAppendBoundary(journal),
            binding=binding,
            output=_fast_output(reply_candidate_ref="candidate://synthetic/fast/duplicate-event-id"),
            output_event_id="evt_fast_interaction_output_duplicate_candidate_event_id",
            candidate_event_id=duplicate_event_id,
            created_monotonic_ms=30,
            created_wall_clock_ms=1700000000030,
        )

    assert len(journal.events()) == event_count_before
    assert not any(
        event["event_name"]
        in {"FAST_INTERACTION_OUTPUT_EMITTED", "FOREGROUND_REPLY_CANDIDATE_EMITTED"}
        for event in journal.events()
    )


def test_emit_reply_candidate_rejects_reused_output_event_id_before_appending_fast_events() -> None:
    journal, turn, asr_output = _journal_with_asr_output("reused_output_event_id")
    binding = FastInteractionBinding.from_turn_and_asr(
        turn,
        asr_output_event=asr_output,
        adapter_request_id="adapter_request_fast_interaction_reused_output_event_id",
    )
    event_count_before = len(journal.events())

    with pytest.raises(FastInteractionValidationError):
        emit_fast_interaction_events(
            boundary=AdapterCallbackAppendBoundary(journal),
            binding=binding,
            output=_fast_output(reply_candidate_ref="candidate://synthetic/fast/reused-output-id"),
            output_event_id="evt_fast_interaction_output_reused_output_event_id",
            candidate_event_id="evt_fast_interaction_output_reused_output_event_id",
            created_monotonic_ms=30,
            created_wall_clock_ms=1700000000030,
        )

    assert len(journal.events()) == event_count_before
    assert not any(
        event["event_name"]
        in {"FAST_INTERACTION_OUTPUT_EMITTED", "FOREGROUND_REPLY_CANDIDATE_EMITTED"}
        for event in journal.events()
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("confidence", 1.01),
        ("foreground_act", "EXECUTE_TOOL"),
        ("risk_class", "CRITICAL"),
        ("output_mode", "experimental"),
        ("risk_tags", ("low_risk", "")),
        ("route_hint_ref", "https://provider.example.test/route"),
        ("route_prelude_ref", "route-prelude://synthetic/traces/raw"),
        ("final_fast_evidence_ref", "evidence://synthetic/audio/raw/capture"),
        ("reply_candidate_ref", "candidate://synthetic?api_key=sk-test123"),
        ("candidate_id", "token=secret"),
        ("route_hint_ref", "route-hint://synthetic/raw-prompt/route"),
        ("route_prelude_ref", "route-prelude://synthetic/raw%20transcript/route"),
        ("final_fast_evidence_ref", "evidence://synthetic/provider-body/route"),
        ("reply_candidate_ref", "candidate://synthetic/provider%20request/route"),
        ("route_hint_ref", "route-hint://synthetic/provider-schema/route"),
        ("route_prelude_ref", "route-prelude://synthetic/provider_payload/route"),
        ("final_fast_evidence_ref", "evidence://synthetic/provider-text/route"),
    ),
)
def test_fast_interaction_output_rejects_invalid_metadata(field: str, value: object) -> None:
    kwargs = asdict(_fast_output(reply_candidate_ref="candidate://synthetic/fast/valid"))
    kwargs[field] = value

    with pytest.raises(FastInteractionValidationError):
        FastInteractionOutput(**kwargs)


def test_fast_interaction_output_requires_candidate_id_with_reply_candidate_ref() -> None:
    with pytest.raises(FastInteractionValidationError):
        FastInteractionOutput(
            adapter_id="fast_interaction_contract_test",
            route_hint_ref="route-hint://synthetic/fast/contract",
            route_prelude_ref="route-prelude://synthetic/fast/contract",
            foreground_act="ANSWER",
            final_fast_evidence_ref="evidence://synthetic/fast/contract",
            risk_tags=("low_risk", "no_side_effects"),
            risk_class="LOW",
            confidence=0.91,
            output_mode="mock",
            reply_candidate_ref="candidate://synthetic/fast/missing-candidate-id",
            candidate_id=None,
        )


def test_binding_derives_asr_refs_from_asr_output_event() -> None:
    _, turn, asr_output = _journal_with_asr_output("binding_from_asr_event")

    binding = FastInteractionBinding.from_turn_and_asr(
        turn,
        asr_output_event=asr_output,
        adapter_request_id="adapter_request_fast_interaction_binding_from_asr_event",
    )

    assert binding.asr_output_event_id == asr_output["event_id"]
    assert binding.asr_frame_ref == asr_output["asr_frame_ref"]
    assert binding.text_ref == asr_output["text_ref"]
    assert binding.source_event_ids == (turn["event_id"], asr_output["event_id"])


def test_binding_rejects_asr_output_not_caused_by_committed_turn() -> None:
    _, turn, valid_asr_output = _journal_with_asr_output("asr_wrong_cause")
    invalid_asr_output = dict(
        valid_asr_output,
        caused_by_event_id="evt_asr_wrong_cause_different_turn_committed",
    )

    with pytest.raises(FastInteractionValidationError):
        FastInteractionBinding.from_turn_and_asr(
            turn,
            asr_output_event=invalid_asr_output,
            adapter_request_id="adapter_request_fast_interaction_asr_wrong_cause",
        )


@pytest.mark.parametrize(
    "asr_output_override",
    (
        {"input_modality": "text"},
        {"audio_span_id": "audio_span_fast_interaction_different"},
        {"audio_span_id": ""},
    ),
)
def test_binding_rejects_asr_output_modality_or_audio_span_mismatch(
    asr_output_override: dict[str, object],
) -> None:
    _, turn, valid_asr_output = _journal_with_asr_output("asr_wrong_audio_binding")
    invalid_asr_output = dict(valid_asr_output, **asr_output_override)

    with pytest.raises(FastInteractionValidationError):
        FastInteractionBinding.from_turn_and_asr(
            turn,
            asr_output_event=invalid_asr_output,
            adapter_request_id="adapter_request_fast_interaction_asr_wrong_audio_binding",
        )


def test_binding_rejects_loose_asr_refs_without_asr_output_event() -> None:
    _, turn, asr_output = _journal_with_asr_output("loose_asr_refs_rejected")

    with pytest.raises(FastInteractionValidationError):
        FastInteractionBinding.from_turn_and_asr(
            turn,
            asr_output_event_id=str(asr_output["event_id"]),
            asr_frame_ref=str(asr_output["asr_frame_ref"]),
            text_ref=str(asr_output["text_ref"]),
            adapter_request_id="adapter_request_fast_interaction_loose_asr_refs_rejected",
        )


@pytest.mark.parametrize(
    "asr_output_event",
    (
        {"event_name": "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED"},
        {"event_name": "ASR_TRANSCRIPT_OUTPUT_EMITTED", "turn_id": "different_turn"},
        {"event_name": "ASR_TRANSCRIPT_OUTPUT_EMITTED", "utterance_id": "different_utterance"},
    ),
)
def test_binding_rejects_asr_output_event_wrong_name_or_mismatched_turn(
    asr_output_event: dict[str, object],
) -> None:
    _, turn, valid_asr_output = _journal_with_asr_output("invalid_asr_output_event")
    invalid_asr_output = dict(valid_asr_output, **asr_output_event)

    with pytest.raises(FastInteractionValidationError):
        FastInteractionBinding.from_turn_and_asr(
            turn,
            asr_output_event=invalid_asr_output,
            adapter_request_id="adapter_request_fast_interaction_invalid_asr_output_event",
        )


def test_binding_rejects_wrong_event_missing_ids_and_unsafe_refs() -> None:
    journal, turn, asr_output = _journal_with_asr_output("invalid_binding")
    non_turn = dict(turn, event_name="TURN_OPENED")
    missing_turn = dict(turn)
    del missing_turn["turn_id"]
    missing_utterance = dict(turn, utterance_id="")

    for invalid_turn in (non_turn, missing_turn, missing_utterance):
        with pytest.raises(FastInteractionValidationError):
            FastInteractionBinding.from_turn_and_asr(
                invalid_turn,
                asr_output_event=asr_output,
                adapter_request_id="adapter_request_fast_interaction_invalid_binding",
            )

    for field, value in (
        ("event_id", "evt_asr_output?authorization=Bearer%20secret"),
        ("asr_frame_ref", "asr-frame://synthetic/diagnostics/raw"),
        ("text_ref", "file:///tmp/raw-transcript.txt"),
        ("text_ref", "text://synthetic/raw-transcript.txt"),
        ("adapter_request_id", "password=secret"),
    ):
        invalid_asr_output = dict(asr_output)
        adapter_request_id = "adapter_request_fast_interaction_invalid_ref"
        if field == "adapter_request_id":
            adapter_request_id = value
        else:
            invalid_asr_output[field] = value
        with pytest.raises(FastInteractionValidationError):
            FastInteractionBinding.from_turn_and_asr(
                turn,
                asr_output_event=invalid_asr_output,
                adapter_request_id=adapter_request_id,
            )

    binding = FastInteractionBinding.from_turn_and_asr(
        turn,
        asr_output_event=asr_output,
        adapter_request_id="adapter_request_fast_interaction_safe_binding",
    )
    serialized_binding = repr(asdict(binding)).lower()
    assert "raw transcript" not in serialized_binding
    assert "raw_audio" not in serialized_binding
    assert "audio/raw" not in serialized_binding
    assert "provider_response" not in serialized_binding
    assert journal.events()[-1]["event_id"] == asr_output["event_id"]


def test_emitted_events_are_journal_validated() -> None:
    journal, turn, asr_output = _journal_with_asr_output("journal_validated")
    binding = FastInteractionBinding.from_turn_and_asr(
        turn,
        asr_output_event=asr_output,
        adapter_request_id="adapter_request_fast_interaction_journal_validated",
    )

    emission = emit_fast_interaction_events(
        boundary=AdapterCallbackAppendBoundary(journal),
        binding=binding,
        output=replace(
            _fast_output(reply_candidate_ref="candidate://synthetic/fast/journal-validated"),
            output_mode="real",
        ),
        output_event_id="evt_fast_interaction_output_journal_validated",
        candidate_event_id="evt_foreground_reply_candidate_journal_validated",
        created_monotonic_ms=30,
        created_wall_clock_ms=1700000000030,
    )

    assert validate_event_envelope(emission.output_event) == emission.output_event
    assert emission.candidate_event is not None
    assert validate_event_envelope(emission.candidate_event) == emission.candidate_event
    assert [event["event_seq"] for event in journal.events()] == [1, 2, 3, 4, 5]


def _timing_snapshot() -> AdapterTimingSnapshot:
    return AdapterTimingSnapshot(
        adapter_start_offset_ms=5,
        provider_request_start_offset_ms=8,
        provider_first_chunk_offset_ms=48,
        provider_full_response_offset_ms=72,
        adapter_event_emit_offset_ms=80,
        provider_ttft_ms=40,
        provider_full_response_ms=64,
        provider_generation_ms=24,
        stream_decode_ms=3,
        parse_validate_emit_ms=5,
        total_ms=75,
        timing_mode="streaming",
        ttft_available=True,
        ttft_source="provider_stream_chunk",
    )


class _MaliciousTimingSnapshot:
    def __init__(self, metadata: object) -> None:
        self._metadata = metadata

    def to_prefixed_metadata(self, prefix: str) -> object:
        assert prefix == "fast_interaction"
        return self._metadata


def _fast_output(*, reply_candidate_ref: str | None) -> FastInteractionOutput:
    return FastInteractionOutput(
        adapter_id="fast_interaction_contract_test",
        route_hint_ref="route-hint://synthetic/fast/contract",
        route_prelude_ref="route-prelude://synthetic/fast/contract",
        foreground_act="ANSWER",
        final_fast_evidence_ref="evidence://synthetic/fast/contract",
        risk_tags=("low_risk", "no_side_effects"),
        risk_class="LOW",
        confidence=0.91,
        output_mode="mock",
        reply_candidate_ref=reply_candidate_ref,
        candidate_id="candidate_fast_contract",
    )


def _journal_with_asr_output(suffix: str) -> tuple[InMemoryEventJournal, dict[str, object], dict[str, object]]:
    journal = InMemoryEventJournal(
        session_id=f"sess_fast_interaction_contract_{suffix}",
        conversation_id=f"conv_fast_interaction_contract_{suffix}",
    )
    session_started = journal.append(
        event_name="SESSION_STARTED",
        event_id=f"evt_{suffix}_session_started",
        source_module="session_runtime",
        created_monotonic_ms=1,
        created_wall_clock_ms=1700000000001,
        trace_redaction_level="metadata_only",
        runtime_config_ref="config://synthetic/fast-interaction/contract",
        capability_snapshot_ref="capability://synthetic/fast-interaction/contract",
    )
    turn = journal.append(
        event_name="TURN_INGRESS_COMMITTED",
        event_id=f"evt_{suffix}_turn_committed",
        source_module="interaction_controller",
        caused_by_event_id=str(session_started["event_id"]),
        created_monotonic_ms=10,
        created_wall_clock_ms=1700000000010,
        trace_redaction_level="metadata_only",
        turn_id=f"turn_fast_interaction_{suffix}",
        utterance_id=f"utt_fast_interaction_{suffix}",
        input_modality="audio",
        audio_span_id=f"audio_span_fast_interaction_{suffix}",
        directedness="ASSUMED_DIRECTED",
        semantic_close="ASSUMED_CLOSED",
        ingress_outcome="COMMITTED",
    )
    asr_output = journal.append(
        event_name="ASR_TRANSCRIPT_OUTPUT_EMITTED",
        event_id=f"evt_{suffix}_asr_output",
        source_module="asr_adapter",
        caused_by_event_id=str(turn["event_id"]),
        created_monotonic_ms=20,
        created_wall_clock_ms=1700000000020,
        trace_redaction_level="metadata_only",
        adapter_id="asr_contract_test",
        adapter_type="asr",
        adapter_request_id=f"adapter_request_asr_{suffix}",
        turn_id=str(turn["turn_id"]),
        utterance_id=str(turn["utterance_id"]),
        input_modality="audio",
        audio_span_id=str(turn["audio_span_id"]),
        asr_frame_ref=f"asr-frame://synthetic/fast-interaction/{suffix}",
        text_ref=f"text://synthetic/fast-interaction/{suffix}",
        transcript_finality="final",
        timestamp_status="available",
        streaming_status="supported",
        output_mode="real",
    )
    return journal, turn, asr_output
