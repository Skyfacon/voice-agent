from __future__ import annotations

from copy import deepcopy

import pytest

from voice_agent.replay.runner import ReplayValidationError, run_replay_fixture


def test_audio_native_fast_interaction_replays_without_asr_or_provider_rerun() -> None:
    fixture = _audio_native_fast_interaction_fixture()

    replay_result = run_replay_fixture(fixture)

    assert replay_result.result_status == "passed"
    assert replay_result.replay_mode == "deterministic"
    assert replay_result.manifest.allowed_re_eval_components == ()
    assert replay_result.task_focus_state.router_decision_event_id == (
        "evt_mvp63_audio_native_router_decision"
    )


def test_audio_native_fast_interaction_replay_requires_input_mode() -> None:
    fixture = _audio_native_fast_interaction_fixture()
    fast_event = _event(fixture["events"], "FAST_INTERACTION_OUTPUT_EMITTED")
    fast_event.pop("input_mode")
    fast_event.pop("fast_interaction_input_mode")

    with pytest.raises(ReplayValidationError, match="input_mode"):
        run_replay_fixture(fixture)


def test_audio_native_fast_interaction_replay_rejects_unsupported_input_mode() -> None:
    fixture = _audio_native_fast_interaction_fixture()
    fast_event = _event(fixture["events"], "FAST_INTERACTION_OUTPUT_EMITTED")
    fast_event["input_mode"] = "provider_body"
    fast_event["fast_interaction_input_mode"] = "provider_body"

    with pytest.raises(ReplayValidationError, match="unsupported input_mode"):
        run_replay_fixture(fixture)


def _audio_native_fast_interaction_fixture() -> dict[str, object]:
    turn_event_id = "evt_mvp63_audio_native_turn_committed"
    fast_event_id = "evt_mvp63_audio_native_fast_interaction_output"
    return _fixture_from_events(
        (
            {
                "event_name": "SESSION_STARTED",
                "event_id": "evt_mvp63_audio_native_session_started",
                "event_seq": 1,
                "event_schema_version": "1.0",
                "session_id": "sess_mvp63_audio_native_fast_replay",
                "conversation_id": "conv_mvp63_audio_native_fast_replay",
                "source_module": "session_runtime",
                "created_monotonic_ms": 1,
                "created_wall_clock_ms": 1700000000001,
                "trace_redaction_level": "metadata_only",
                "runtime_config_ref": "config://synthetic/mvp63/audio-native-fast-replay",
                "capability_snapshot_ref": "capability://synthetic/mvp63/audio-native-fast-replay",
            },
            {
                "event_name": "TURN_OPENED",
                "event_id": "evt_mvp63_audio_native_turn_opened",
                "event_seq": 2,
                "event_schema_version": "1.0",
                "session_id": "sess_mvp63_audio_native_fast_replay",
                "conversation_id": "conv_mvp63_audio_native_fast_replay",
                "source_module": "interaction_controller",
                "caused_by_event_id": "evt_mvp63_audio_native_session_started",
                "created_monotonic_ms": 5,
                "created_wall_clock_ms": 1700000000005,
                "trace_redaction_level": "metadata_only",
                "turn_id": "turn_mvp63_audio_native_fast_replay",
                "utterance_id": "utt_mvp63_audio_native_fast_replay",
                "input_modality": "audio",
                "audio_span_id": "audio_span_mvp63_audio_native_fast_replay",
                "turn_phase": "COLLECTING_INPUT",
            },
            {
                "event_name": "TURN_INGRESS_COMMITTED",
                "event_id": turn_event_id,
                "event_seq": 3,
                "event_schema_version": "1.0",
                "session_id": "sess_mvp63_audio_native_fast_replay",
                "conversation_id": "conv_mvp63_audio_native_fast_replay",
                "source_module": "interaction_controller",
                "caused_by_event_id": "evt_mvp63_audio_native_session_started",
                "created_monotonic_ms": 10,
                "created_wall_clock_ms": 1700000000010,
                "trace_redaction_level": "metadata_only",
                "turn_id": "turn_mvp63_audio_native_fast_replay",
                "utterance_id": "utt_mvp63_audio_native_fast_replay",
                "input_modality": "audio",
                "audio_span_id": "audio_span_mvp63_audio_native_fast_replay",
                "directedness": "ASSUMED_DIRECTED",
                "semantic_close": "ASSUMED_CLOSED",
                "ingress_outcome": "COMMITTED",
            },
            {
                "event_name": "FAST_INTERACTION_OUTPUT_EMITTED",
                "event_id": fast_event_id,
                "event_seq": 4,
                "event_schema_version": "1.0",
                "session_id": "sess_mvp63_audio_native_fast_replay",
                "conversation_id": "conv_mvp63_audio_native_fast_replay",
                "source_module": "fast_interaction_adapter",
                "caused_by_event_id": turn_event_id,
                "created_monotonic_ms": 30,
                "created_wall_clock_ms": 1700000000030,
                "trace_redaction_level": "metadata_only",
                "adapter_id": "mvp63_fast_interaction_runtime",
                "adapter_type": "fast_interaction",
                "adapter_request_id": "adapter_request_mvp63_audio_native_fast_replay",
                "turn_id": "turn_mvp63_audio_native_fast_replay",
                "utterance_id": "utt_mvp63_audio_native_fast_replay",
                "route_hint_ref": "route-hint://synthetic/mvp63/audio-native-fast-replay",
                "route_prelude_ref": "route-prelude://synthetic/mvp63/audio-native-fast-replay",
                "foreground_act": "ANSWER",
                "final_fast_evidence_ref": "evidence://synthetic/mvp63/audio-native-fast-replay",
                "schema_name": "voice_agent.fast_interaction.output.v1",
                "normalization_status": "normalized",
                "output_mode": "real",
                "input_modality": "audio",
                "input_mode": "audio_native",
                "fast_interaction_input_mode": "audio_native",
                "source_event_ids": [turn_event_id],
                "risk_tags": ["low_risk", "no_side_effects"],
                "risk_class": "LOW",
                "confidence": 0.91,
            },
            {
                "event_name": "ROUTER_DECISION_EMITTED",
                "event_id": "evt_mvp63_audio_native_router_decision",
                "event_seq": 5,
                "event_schema_version": "1.0",
                "session_id": "sess_mvp63_audio_native_fast_replay",
                "conversation_id": "conv_mvp63_audio_native_fast_replay",
                "source_module": "router",
                "caused_by_event_id": fast_event_id,
                "created_monotonic_ms": 40,
                "created_wall_clock_ms": 1700000000040,
                "trace_redaction_level": "metadata_only",
                "turn_id": "turn_mvp63_audio_native_fast_replay",
                "utterance_id": "utt_mvp63_audio_native_fast_replay",
                "router_decision": "FAST_ONLY",
                "task_focus": "FOREGROUND_CHAT",
                "confidence": 0.9,
                "turn_committed_event_id": turn_event_id,
                "fast_interaction_output_event_id": fast_event_id,
            },
        )
    )


def _fixture_from_events(events: tuple[dict[str, object], ...]) -> dict[str, object]:
    return {
        "replay_manifest": {
            "manifest_schema_version": "1.0",
            "replay_id": "mvp63_audio_native_fast_interaction_replay",
            "source_trace_ref": "fixture://mvp63/audio-native-fast-interaction-replay",
            "replay_mode": "deterministic",
            "event_schema_version_range": ["1.0"],
            "fixture_domain": "GITHUB_ALLOWED",
            "generated_from": "synthetic",
            "contains_raw_audio": False,
            "contains_raw_trace": False,
            "contains_real_user_input": False,
            "contains_secrets": False,
            "contains_unredacted_tool_result": False,
            "contains_large_raw_web_content": False,
            "allowed_re_eval_components": [],
        },
        "events": [deepcopy(event) for event in events],
    }


def _event(events: object, event_name: str) -> dict[str, object]:
    assert isinstance(events, list)
    matches = [event for event in events if event["event_name"] == event_name]
    assert len(matches) == 1
    return matches[0]
