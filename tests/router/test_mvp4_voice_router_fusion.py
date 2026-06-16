from __future__ import annotations

from typing import Any

import pytest

from voice_agent.router.router import MVP1Router, RouterContext, TaskFocusSnapshot
from voice_agent.runtime import mvp4_voice_e2e_orchestrator as mvp4
from voice_agent.runtime.session import start_mvp0_session


@pytest.mark.parametrize(
    ("suffix", "task_focus_hint", "router_context", "expected_decision"),
    [
        ("fast", "FOREGROUND_CHAT", RouterContext(task_focus_snapshot=TaskFocusSnapshot()), "FAST_ONLY"),
        ("spawn", "NEW_TASK_CANDIDATE", RouterContext(task_focus_snapshot=TaskFocusSnapshot()), "SPAWN_SLOW_TASK"),
        (
            "patch",
            "ACTIVE_TASK_PATCH",
            RouterContext(
                task_focus_snapshot=TaskFocusSnapshot(
                    active_task_id="task_mvp4_router_fusion_active",
                    lifecycle_phase="PLANNING",
                    current_plan_version=2,
                )
            ),
            "PATCH_ACTIVE_SLOW_TASK",
        ),
    ],
)
def test_router_accepts_real_asr_and_real_thinker_event_refs_for_all_mvp4_decisions(
    suffix: str,
    task_focus_hint: str,
    router_context: RouterContext,
    expected_decision: str,
) -> None:
    journal, turn = _audio_turn(suffix)
    asr_event = _real_asr_event(journal, turn, suffix=suffix)
    thinker_event = _real_thinker_event(
        journal,
        turn,
        suffix=suffix,
        task_focus_hint=task_focus_hint,
        task_like=task_focus_hint == "NEW_TASK_CANDIDATE",
        complexity_hint="complex" if task_focus_hint == "NEW_TASK_CANDIDATE" else "simple",
    )

    result = MVP1Router(journal).emit_decision(
        turn_committed_event=turn,
        asr_frame_event={**asr_event, "raw_transcript": "must not be copied"},
        thinker_frame_event={**thinker_event, "provider_body": {"must": "not be copied"}},
        router_context=router_context,
        event_id=f"evt_mvp4_router_fusion_{suffix}_decision",
        task_focus_state_event_id=f"evt_mvp4_router_fusion_{suffix}_focus_state",
        created_monotonic_ms=1500,
        created_wall_clock_ms=1700000001500,
    )

    router_event = result.router_decision_event
    assert router_event["router_decision"] == expected_decision
    assert router_event["turn_committed_event_id"] == turn["event_id"]
    assert router_event["asr_frame_event_id"] == asr_event["event_id"]
    assert router_event["thinker_frame_event_id"] == thinker_event["event_id"]
    assert "asr_frame_ref" not in router_event
    assert "text_ref" not in router_event
    assert "semantic_frame_ref" not in router_event
    assert "semantic_summary_ref" not in router_event
    assert "raw_transcript" not in repr(router_event)
    assert "provider_body" not in repr(router_event)


def test_router_preserves_conflicting_real_evidence_as_ambiguous_not_a_winner() -> None:
    journal, turn = _audio_turn("conflict")
    asr_event = _real_asr_event(
        journal,
        turn,
        suffix="conflict",
        task_focus_hint="NEW_TASK_CANDIDATE",
        focus_confidence=0.91,
        evidence_uncertainty="medium",
    )
    thinker_event = _real_thinker_event(
        journal,
        turn,
        suffix="conflict",
        task_focus_hint="FOREGROUND_CHAT",
        task_like=False,
        complexity_hint="simple",
        focus_confidence=0.78,
        evidence_uncertainty="medium",
    )

    result = MVP1Router(journal).emit_decision(
        turn_committed_event=turn,
        asr_frame_event=asr_event,
        thinker_frame_event=thinker_event,
        router_context=RouterContext(task_focus_snapshot=TaskFocusSnapshot()),
        event_id="evt_mvp4_router_fusion_conflict_decision",
        task_focus_state_event_id="evt_mvp4_router_fusion_conflict_focus_state",
        created_monotonic_ms=1500,
        created_wall_clock_ms=1700000001500,
    )

    router_event = result.router_decision_event
    assert router_event["router_decision"] == "FAST_ONLY"
    assert router_event["task_focus"] == "AMBIGUOUS"
    assert router_event["evidence_uncertainty"] == "conflicting"
    assert router_event["asr_frame_event_id"] == asr_event["event_id"]
    assert router_event["thinker_frame_event_id"] == thinker_event["event_id"]
    assert "winner" not in repr(router_event).lower()


def _audio_turn(suffix: str) -> tuple[Any, dict[str, Any]]:
    startup = start_mvp0_session(
        session_id=f"sess_mvp4_router_fusion_{suffix}",
        conversation_id=f"conv_mvp4_router_fusion_{suffix}",
        runtime_config_ref="config://synthetic/mvp4/router-fusion",
        created_monotonic_ms=1000,
        created_wall_clock_ms=1700000001000,
    )
    audio_input = mvp4.load_synthetic_wav_metadata(
        fixture_id=f"router-fusion-{suffix}",
        duration_ms=900,
        sample_rate_hz=16000,
        channel_count=1,
    )
    turn = mvp4._append_audio_turn(
        journal=startup.journal,
        audio_input=audio_input,
        label=f"router_fusion_{suffix}",
        caused_by_event_id=str(startup.journal.events()[-1]["event_id"]),
        created_monotonic_ms=1100,
        created_wall_clock_ms=1700000001100,
    )
    return startup.journal, turn


def _real_asr_event(
    journal: Any,
    turn: dict[str, Any],
    *,
    suffix: str,
    task_focus_hint: str | None = None,
    focus_confidence: float = 0.86,
    evidence_uncertainty: str = "low",
) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if task_focus_hint is not None:
        fields.update(
            task_focus_hint=task_focus_hint,
            focus_confidence=focus_confidence,
            evidence_uncertainty=evidence_uncertainty,
        )
    return journal.append(
        event_name="ASR_TRANSCRIPT_OUTPUT_EMITTED",
        event_id=f"evt_mvp4_router_fusion_{suffix}_asr",
        source_module="asr_adapter",
        caused_by_event_id=str(turn["event_id"]),
        created_monotonic_ms=1200,
        created_wall_clock_ms=1700000001200,
        trace_redaction_level="metadata_only",
        adapter_id="mvp4_router_fusion_asr",
        adapter_type="asr",
        adapter_request_id=f"adapter_request_mvp4_router_fusion_{suffix}_asr",
        turn_id=str(turn["turn_id"]),
        utterance_id=str(turn["utterance_id"]),
        input_modality="audio",
        audio_span_id=str(turn["audio_span_id"]),
        asr_frame_ref=f"asr-frame://synthetic/mvp4/router-fusion/{suffix}",
        text_ref=f"text://synthetic/mvp4/router-fusion/{suffix}",
        transcript_finality="final",
        timestamp_status="available",
        streaming_status="supported",
        output_mode="real",
        **fields,
    )


def _real_thinker_event(
    journal: Any,
    turn: dict[str, Any],
    *,
    suffix: str,
    task_focus_hint: str,
    task_like: bool,
    complexity_hint: str,
    focus_confidence: float = 0.86,
    evidence_uncertainty: str = "low",
) -> dict[str, Any]:
    return journal.append(
        event_name="THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED",
        event_id=f"evt_mvp4_router_fusion_{suffix}_thinker",
        source_module="thinker_adapter",
        caused_by_event_id=str(turn["event_id"]),
        created_monotonic_ms=1201,
        created_wall_clock_ms=1700000001201,
        trace_redaction_level="metadata_only",
        adapter_id="mvp4_router_fusion_thinker",
        adapter_type="thinker",
        adapter_request_id=f"adapter_request_mvp4_router_fusion_{suffix}_thinker",
        turn_id=str(turn["turn_id"]),
        utterance_id=str(turn["utterance_id"]),
        input_modality="audio",
        audio_span_id=str(turn["audio_span_id"]),
        semantic_frame_schema="voice_agent.semantic_frame.v1",
        normalization_status="normalized",
        semantic_frame_ref=f"semantic-frame://synthetic/mvp4/router-fusion/{suffix}",
        semantic_summary_ref=f"summary://synthetic/mvp4/router-fusion/{suffix}",
        semantic_close_status="available",
        assistant_directedness_status="available",
        emotion_status="available",
        audio_caption_status="available",
        semantic_close_ref=f"semantic-close://synthetic/mvp4/router-fusion/{suffix}",
        assistant_directedness_ref=f"assistant-directedness://synthetic/mvp4/router-fusion/{suffix}",
        emotion_ref=f"emotion://synthetic/mvp4/router-fusion/{suffix}",
        audio_caption_ref=f"audio-caption://synthetic/mvp4/router-fusion/{suffix}",
        output_mode="real",
        task_focus_hint=task_focus_hint,
        task_like=task_like,
        complexity_hint=complexity_hint,
        focus_confidence=focus_confidence,
        evidence_uncertainty=evidence_uncertainty,
    )
