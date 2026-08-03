from __future__ import annotations

import json

import pytest

from experiments.qwen_realtime_fast_slow_web.candidate_quarantine import (
    CandidateQuarantine,
    QuarantineLimits,
)
from experiments.qwen_realtime_fast_slow_web.capability_profile import (
    fake_capability_profile,
)
from experiments.qwen_realtime_fast_slow_web.realtime_evidence import (
    ProviderRouteProposal,
    RealtimeTurnEvidenceBundle,
)


def proposal(**overrides: object) -> ProviderRouteProposal:
    fields: dict[str, object] = {
        "scenario": "fast",
        "response_id": "response-safe-1",
        "provider_item_id": "provider-item-safe-1",
        "route_hint": "FAST_ONLY",
        "task_focus_hint": "FOREGROUND_CHAT",
        "foreground_act": "ANSWER",
        "risk_class": "LOW",
        "confidence": 0.99,
        "output_mode": "mock",
    }
    fields.update(overrides)
    return ProviderRouteProposal(**fields)  # type: ignore[arg-type]


def event_pair(
    *,
    turn_id: str = "turn-safe-1",
    utterance_id: str = "utterance-safe-1",
    audio_span_id: str = "audio-span-safe-1",
) -> tuple[dict[str, object], dict[str, object]]:
    turn = {
        "event_name": "TURN_INGRESS_COMMITTED",
        "event_id": "event-turn-safe-1",
        "turn_id": turn_id,
        "utterance_id": utterance_id,
        "audio_span_id": audio_span_id,
    }
    asr = {
        "event_name": "ASR_TRANSCRIPT_OUTPUT_EMITTED",
        "event_id": "event-asr-safe-1",
        "turn_id": turn_id,
        "utterance_id": utterance_id,
        "audio_span_id": audio_span_id,
    }
    return turn, asr


def evidence_bundle(**overrides: object) -> RealtimeTurnEvidenceBundle:
    turn, asr = event_pair()
    fields: dict[str, object] = {
        "turn_id": "turn-safe-1",
        "utterance_id": "utterance-safe-1",
        "audio_span_id": "audio-span-safe-1",
        "provider_item_id": "provider-item-safe-1",
        "response_id": "response-safe-1",
        "playback_epoch": 2,
        "turn_committed_event": turn,
        "asr_frame_event": asr,
        "proposal": proposal(),
    }
    fields.update(overrides)
    return RealtimeTurnEvidenceBundle(**fields)  # type: ignore[arg-type]


def test_fake_capability_profile_is_secret_free_and_does_not_overclaim() -> None:
    profile = fake_capability_profile()
    metadata = profile.to_metadata()
    serialized = json.dumps(metadata, sort_keys=True)

    assert profile.output_mode == "mock"
    assert profile.health_status == "ready"
    assert profile.duplex_projection == "mock"
    assert profile.asr_projection == "mock"
    assert profile.fast_interaction_projection == "mock"
    assert profile.supports_candidate_quarantine is True
    assert profile.supports_response_cancel is True
    assert profile.supports_provider_item_delete is True
    assert profile.supports_context_rebuild is False
    assert profile.supports_direct_provider_audio_before_gate is False
    assert profile.supports_playback_reference_aec is False
    assert profile.supports_real_provider is False
    assert profile.tools_enabled is False
    assert profile.persistence_enabled is False
    assert "authorization" not in serialized.lower()
    assert "api_key" not in serialized.lower()
    assert "credential" not in serialized.lower()
    assert "secret" not in serialized.lower()


def test_capability_health_can_report_degraded_and_disconnected_distinctly() -> None:
    profile = fake_capability_profile()

    degraded = profile.with_health("degraded")
    disconnected = degraded.with_health("disconnected")

    assert degraded.health_status == "degraded"
    assert disconnected.health_status == "disconnected"
    assert profile.health_status == "ready"
    assert degraded.output_mode == disconnected.output_mode == "mock"


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("route_hint", "DIRECT_PROVIDER_ROUTE"),
        ("task_focus_hint", "PROVIDER_OWNS_TASK"),
        ("foreground_act", "UNCONTROLLED_ANSWER"),
        ("risk_class", "UNKNOWN"),
        ("confidence", -0.01),
        ("confidence", 1.01),
        ("confidence", True),
        ("output_mode", "provider_direct"),
    ),
)
def test_provider_route_proposal_rejects_out_of_contract_values(
    field: str, value: object
) -> None:
    with pytest.raises(ValueError):
        proposal(**{field: value})


def test_provider_route_proposal_accepts_real_control_evidence_without_authority() -> None:
    real = proposal(output_mode="real")

    assert real.output_mode == "real"
    assert real.route_hint == "FAST_ONLY"
    assert real.task_focus_hint == "FOREGROUND_CHAT"


def test_realtime_evidence_bundle_preserves_all_correlation_bindings() -> None:
    bundle = evidence_bundle()

    assert bundle.to_metadata() == {
        "turn_id": "turn-safe-1",
        "utterance_id": "utterance-safe-1",
        "audio_span_id": "audio-span-safe-1",
        "provider_item_id": "provider-item-safe-1",
        "response_id": "response-safe-1",
        "playback_epoch": 2,
        "scenario": "fast",
        "route_hint": "FAST_ONLY",
        "task_focus_hint": "FOREGROUND_CHAT",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("turn_id", "turn-mismatch"),
        ("utterance_id", "utterance-mismatch"),
        ("audio_span_id", "audio-span-mismatch"),
        ("provider_item_id", "provider-item-mismatch"),
        ("response_id", "response-mismatch"),
    ),
)
def test_realtime_evidence_bundle_rejects_mismatched_correlation(
    field: str, value: str
) -> None:
    with pytest.raises(ValueError, match="mismatch"):
        evidence_bundle(**{field: value})


@pytest.mark.parametrize("playback_epoch", (-1, True, 1.5, "1"))
def test_realtime_evidence_bundle_rejects_invalid_epoch(playback_epoch: object) -> None:
    with pytest.raises(ValueError, match="playback_epoch"):
        evidence_bundle(playback_epoch=playback_epoch)


def test_quarantine_buffers_text_and_pcm_until_matching_epoch_release() -> None:
    quarantine = CandidateQuarantine()
    quarantine.start(
        response_id="response-1",
        provider_item_id="item-1",
        turn_id="turn-1",
        utterance_id="utterance-1",
        playback_epoch=3,
    )

    assert quarantine.append_text("response-1", "synthetic ") is True
    assert quarantine.append_text("response-1", "answer") is True
    assert quarantine.append_audio("response-1", b"\x01\x00\x02\x00") is True
    snapshot = quarantine.snapshot("response-1")

    assert snapshot is not None
    assert snapshot.text == "synthetic answer"
    assert snapshot.audio_bytes == 4
    assert quarantine.active_response_ids == ("response-1",)
    released = quarantine.release("response-1", expected_playback_epoch=3)
    assert released == snapshot
    assert quarantine.active_response_ids == ()
    assert quarantine.counters()["discarded_responses"] == 0


def test_quarantine_epoch_mismatch_fails_closed_and_discards_candidate() -> None:
    quarantine = CandidateQuarantine()
    quarantine.start(
        response_id="response-old",
        provider_item_id="item-old",
        turn_id="turn-old",
        utterance_id="utterance-old",
        playback_epoch=4,
    )
    quarantine.append_text("response-old", "must never release")
    quarantine.append_audio("response-old", b"\x01\x00")

    assert quarantine.release("response-old", expected_playback_epoch=5) is None
    assert quarantine.active_response_ids == ()
    assert quarantine.counters() == {
        "active_responses": 0,
        "discarded_responses": 1,
        "dropped_text_deltas": 1,
        "dropped_audio_chunks": 1,
        "dropped_audio_bytes": 2,
        "overflow_count": 0,
        "quarantined_text_characters": 0,
        "quarantined_audio_bytes": 0,
    }


@pytest.mark.parametrize("kind", ("text_count", "text_chars", "audio_count", "audio_bytes"))
def test_quarantine_overflow_clears_candidate_and_cannot_release(kind: str) -> None:
    quarantine = CandidateQuarantine(
        QuarantineLimits(
            max_responses=2,
            max_text_deltas=1,
            max_text_characters=4,
            max_audio_chunks=1,
            max_audio_bytes=4,
        )
    )
    quarantine.start(
        response_id="response-overflow",
        provider_item_id="item-overflow",
        turn_id="turn-overflow",
        utterance_id="utterance-overflow",
        playback_epoch=1,
    )
    if kind == "text_count":
        assert quarantine.append_text("response-overflow", "one") is True
        assert quarantine.append_text("response-overflow", "x") is False
    elif kind == "text_chars":
        assert quarantine.append_text("response-overflow", "12345") is False
    elif kind == "audio_count":
        assert quarantine.append_audio("response-overflow", b"\x01\x00") is True
        assert quarantine.append_audio("response-overflow", b"\x02\x00") is False
    else:
        assert quarantine.append_audio("response-overflow", b"\x01\x00" * 3) is False

    snapshot = quarantine.snapshot("response-overflow")
    assert snapshot is not None and snapshot.overflowed is True
    assert snapshot.text == ""
    assert snapshot.audio_chunks == ()
    assert quarantine.total_text_characters == 0
    assert quarantine.total_audio_bytes == 0
    assert quarantine.release("response-overflow", expected_playback_epoch=1) is None
    assert quarantine.counters()["overflow_count"] == 1


def test_quarantine_evicts_oldest_response_and_clear_removes_all_pcm() -> None:
    quarantine = CandidateQuarantine(QuarantineLimits(max_responses=2))
    for index in range(3):
        response_id = f"response-{index}"
        quarantine.start(
            response_id=response_id,
            provider_item_id=f"item-{index}",
            turn_id=f"turn-{index}",
            utterance_id=f"utterance-{index}",
            playback_epoch=index,
        )
        quarantine.append_audio(response_id, b"\x01\x00")

    assert quarantine.active_response_ids == ("response-1", "response-2")
    assert quarantine.snapshot("response-0") is None
    assert quarantine.counters()["discarded_responses"] == 1
    cleared = quarantine.clear(reason="interrupt")
    assert {item.response_id for item in cleared} == {"response-1", "response-2"}
    assert quarantine.active_response_ids == ()
    assert quarantine.total_audio_bytes == 0
    assert quarantine.counters()["discarded_responses"] == 3


def test_quarantine_rejects_invalid_pcm_and_unknown_response_without_storage() -> None:
    quarantine = CandidateQuarantine()
    quarantine.start(
        response_id="response-safe",
        provider_item_id="item-safe",
        turn_id="turn-safe",
        utterance_id="utterance-safe",
        playback_epoch=0,
    )

    assert quarantine.append_audio("response-safe", b"") is False
    assert quarantine.append_audio("response-safe", b"\x00") is False
    assert quarantine.append_audio("response-unknown", b"\x00\x00") is False
    assert quarantine.append_text("response-unknown", "hidden") is False
    assert quarantine.total_audio_bytes == 0
    assert quarantine.total_text_characters == 0
    assert quarantine.counters()["dropped_audio_chunks"] == 3
    assert quarantine.counters()["dropped_text_deltas"] == 1


def test_quarantine_and_bundle_reject_boolean_playback_epoch() -> None:
    quarantine = CandidateQuarantine()
    with pytest.raises(ValueError, match="playback_epoch"):
        quarantine.start(
            response_id="response-safe",
            provider_item_id="item-safe",
            turn_id="turn-safe",
            utterance_id="utterance-safe",
            playback_epoch=True,
        )

    with pytest.raises(ValueError, match="playback_epoch"):
        evidence_bundle(playback_epoch=True)
