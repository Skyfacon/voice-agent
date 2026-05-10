from __future__ import annotations

from importlib import import_module
from typing import Any

import pytest

from voice_agent.access.text_ingress import receive_text_input
from voice_agent.interaction.controller import InteractionController
from voice_agent.runtime.session import start_mvp0_session


def _slice6_symbol(module_name: str, symbol_name: str) -> Any:
    try:
        module = import_module(module_name)
    except ModuleNotFoundError as exc:
        pytest.fail(f"Slice 6 module is not implemented: {module_name}")  # noqa: B011
        raise AssertionError from exc
    try:
        return getattr(module, symbol_name)
    except AttributeError as exc:
        pytest.fail(f"Slice 6 symbol is not implemented: {module_name}.{symbol_name}")  # noqa: B011
        raise AssertionError from exc


def _text_commit_with_mock_frames():
    emit_mock_asr_frame = _slice6_symbol("voice_agent.understanding.mock_asr", "emit_mock_asr_frame")
    emit_mock_thinker_frame = _slice6_symbol(
        "voice_agent.understanding.mock_thinker",
        "emit_mock_thinker_frame",
    )
    startup = start_mvp0_session(
        session_id="sess_mvp0_slice6_router",
        conversation_id="conv_mvp0_slice6_router",
        runtime_config_ref="config://synthetic/mvp0/default",
        created_monotonic_ms=600,
        created_wall_clock_ms=1700000000600,
    )
    text_event = receive_text_input(
        startup.journal,
        event_id="evt_mvp0_slice6_router_text_received",
        caused_by_event_id=str(startup.journal.events()[-1]["event_id"]),
        created_monotonic_ms=610,
        created_wall_clock_ms=1700000000610,
        input_span_id="input_slice6_router_text_001",
        text_span_id="text_slice6_router_001",
        text_ref="text://synthetic/mvp0/slice6-router-redacted-text",
    )
    commit_result = InteractionController(startup.journal).commit_text_ingress(
        text_event,
        turn_id="turn_slice6_router_text_001",
        utterance_id="utt_slice6_router_text_001",
        created_monotonic_ms=620,
        created_wall_clock_ms=1700000000620,
    )
    asr_event = emit_mock_asr_frame(
        startup.journal,
        commit_result.turn_committed,
        event_id="evt_mvp0_slice6_router_mock_asr",
        created_monotonic_ms=630,
        created_wall_clock_ms=1700000000630,
        asr_frame_ref="asr-frame://synthetic/mvp0/slice6-router-text",
    )
    thinker_event = emit_mock_thinker_frame(
        startup.journal,
        commit_result.turn_committed,
        event_id="evt_mvp0_slice6_router_mock_thinker",
        created_monotonic_ms=631,
        created_wall_clock_ms=1700000000631,
        semantic_frame_ref="semantic-frame://synthetic/mvp0/slice6-router-text",
    )
    return startup, commit_result.turn_committed, asr_event, thinker_event


def test_router_emits_fast_only_after_committed_turn_and_mock_frames() -> None:
    MVP0Router = _slice6_symbol("voice_agent.router.router", "MVP0Router")
    startup, turn_committed, asr_event, thinker_event = _text_commit_with_mock_frames()

    router_event = MVP0Router(startup.journal).emit_decision(
        turn_committed_event=turn_committed,
        asr_frame_event=asr_event,
        thinker_frame_event=thinker_event,
        event_id="evt_mvp0_slice6_router_decision",
        created_monotonic_ms=632,
        created_wall_clock_ms=1700000000632,
    )

    assert router_event["event_name"] == "ROUTER_DECISION_EMITTED"
    assert router_event["source_module"] == "router"
    assert router_event["caused_by_event_id"] == thinker_event["event_id"]
    assert router_event["turn_committed_event_id"] == turn_committed["event_id"]
    assert router_event["asr_frame_event_id"] == asr_event["event_id"]
    assert router_event["thinker_frame_event_id"] == thinker_event["event_id"]
    assert router_event["router_decision"] == "FAST_ONLY"
    assert router_event["task_focus"] == "FOREGROUND_CHAT"
    assert router_event["confidence"] == 1.0
    assert router_event["evidence_uncertainty"] == "low"
    assert "task_id" not in router_event
    assert "plan_version" not in router_event

    event_names = {event["event_name"] for event in startup.journal.events()}
    assert "SLOWTASK_CREATED" not in event_names
    assert "USER_PATCH_RECEIVED" not in event_names


def test_router_requires_committed_turn_and_both_mock_frames() -> None:
    MVP0Router = _slice6_symbol("voice_agent.router.router", "MVP0Router")
    startup, turn_committed, asr_event, _thinker_event = _text_commit_with_mock_frames()

    with pytest.raises(ValueError, match="MOCK_THINKER_FRAME_EMITTED"):
        MVP0Router(startup.journal).emit_decision(
            turn_committed_event=turn_committed,
            asr_frame_event=asr_event,
            thinker_frame_event=turn_committed,
            event_id="evt_mvp0_slice6_router_missing_thinker",
            created_monotonic_ms=632,
            created_wall_clock_ms=1700000000632,
        )


def test_router_rejects_slice6_out_of_scope_decisions() -> None:
    MVP0Router = _slice6_symbol("voice_agent.router.router", "MVP0Router")
    startup, turn_committed, asr_event, thinker_event = _text_commit_with_mock_frames()

    with pytest.raises(ValueError, match="FAST_ONLY or IGNORE"):
        MVP0Router(startup.journal).emit_decision(
            turn_committed_event=turn_committed,
            asr_frame_event=asr_event,
            thinker_frame_event=thinker_event,
            event_id="evt_mvp0_slice6_router_spawn_slowtask",
            created_monotonic_ms=632,
            created_wall_clock_ms=1700000000632,
            router_decision="SPAWN_SLOW_TASK",
        )


def test_router_rejects_slice6_out_of_scope_task_focus_labels() -> None:
    MVP0Router = _slice6_symbol("voice_agent.router.router", "MVP0Router")
    startup, turn_committed, asr_event, thinker_event = _text_commit_with_mock_frames()

    with pytest.raises(ValueError, match="MVP0 task_focus"):
        MVP0Router(startup.journal).emit_decision(
            turn_committed_event=turn_committed,
            asr_frame_event=asr_event,
            thinker_frame_event=thinker_event,
            event_id="evt_mvp0_slice6_router_patch_focus",
            created_monotonic_ms=632,
            created_wall_clock_ms=1700000000632,
            router_decision="FAST_ONLY",
            task_focus="PATCH_ACTIVE_SLOW_TASK",
        )
