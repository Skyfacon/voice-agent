from __future__ import annotations

from voice_agent.state.interaction_state import InteractionState


def _base_event(event_name: str, **fields: object) -> dict[str, object]:
    return {
        "event_name": event_name,
        "event_id": f"evt_{event_name.lower()}",
        **fields,
    }


def test_turn_held_reduces_to_holding_input_phase() -> None:
    state = InteractionState()

    state.reduce_event(
        _base_event(
            "TURN_HELD",
            turn_id="turn_hold_001",
            ingress_outcome="HELD",
            semantic_close="NOT_CLOSED",
            directedness="DIRECTED",
        )
    )

    assert state.turn_phase == "HOLDING_INPUT"
    assert state.last_ingress_outcome == "HELD"


def test_turn_rejected_reduces_to_waiting_user_phase() -> None:
    state = InteractionState()

    state.reduce_event(
        _base_event(
            "TURN_INGRESS_REJECTED",
            turn_id="turn_reject_001",
            audio_span_id="audio_reject_001",
            ingress_outcome="REJECTED",
            reject_reason="non_assistant_candidate",
        )
    )

    assert state.turn_phase == "WAITING_USER"
    assert state.last_ingress_outcome == "REJECTED"
