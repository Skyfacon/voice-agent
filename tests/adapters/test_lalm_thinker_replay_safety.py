from __future__ import annotations

from pathlib import Path

import pytest

from tests.adapters.test_mvp3_adapter_profiles import valid_mvp3_real_profiles
from voice_agent.adapters.lalm_thinker_binding import bind_lalm_thinker_request
from voice_agent.adapters.lalm_thinker_profile import build_lalm_thinker_capability
from voice_agent.adapters.lalm_thinker_skeleton import (
    emit_lalm_thinker_semantic_frame,
    fake_lalm_thinker_transport,
    parse_lalm_thinker_candidate_text,
    validate_lalm_thinker_candidate,
)
from voice_agent.replay.runner import ReplayValidationError, run_replay_fixture
from voice_agent.runtime.adapter_callback_boundary import AdapterCallbackAppendBoundary
from voice_agent.runtime.assembly import RuntimeAdapterAssemblyConfig
from voice_agent.runtime.session import start_configured_session


def test_replay_accepts_synthetic_lalm_thinker_all_refs_available_fixture() -> None:
    fixture, thinker_event = _lalm_thinker_fixture(
        session_id="sess_lalm_thinker_replay_available",
        event_id_prefix="evt_lalm_thinker_replay_available",
        optional_refs_available=True,
    )

    result = run_replay_fixture(fixture)

    assert result.result_status == "passed"
    assert result.adapter_health_state.output_event_modes[thinker_event["event_id"]] == "real"
    assert result.adapter_health_state.adapters["lalm_thinker_provider_free"].missing_capabilities == ()


def test_replay_accepts_synthetic_lalm_thinker_degraded_fixture_with_matching_degraded_events() -> None:
    fixture, thinker_event = _lalm_thinker_fixture(
        session_id="sess_lalm_thinker_replay_degraded",
        event_id_prefix="evt_lalm_thinker_replay_degraded",
        optional_refs_available=False,
    )

    result = run_replay_fixture(fixture)

    assert result.result_status == "passed"
    assert result.adapter_health_state.output_event_modes[thinker_event["event_id"]] == "degraded"
    assert result.adapter_health_state.adapters["lalm_thinker_provider_free"].missing_capabilities == (
        "supports_assistant_directedness",
        "supports_audio_caption",
        "supports_emotion",
        "supports_semantic_close",
    )


def test_replay_rejects_lalm_thinker_available_status_without_matching_ref() -> None:
    fixture, thinker_event = _lalm_thinker_fixture(
        session_id="sess_lalm_thinker_replay_available_without_ref",
        event_id_prefix="evt_lalm_thinker_replay_available_without_ref",
        optional_refs_available=True,
    )
    thinker = _event_by_id(fixture["events"], str(thinker_event["event_id"]))
    thinker.pop("semantic_close_ref")

    with pytest.raises(ReplayValidationError, match="semantic_close_status"):
        run_replay_fixture(fixture)


def test_replay_rejects_lalm_thinker_unavailable_status_with_ref_tampering() -> None:
    fixture, thinker_event = _lalm_thinker_fixture(
        session_id="sess_lalm_thinker_replay_unavailable_with_ref",
        event_id_prefix="evt_lalm_thinker_replay_unavailable_with_ref",
        optional_refs_available=False,
    )
    thinker = _event_by_id(fixture["events"], str(thinker_event["event_id"]))
    thinker["semantic_close_ref"] = "semantic-close://synthetic/lalm-thinker/tampered/closed"

    with pytest.raises(ReplayValidationError, match="unavailable must not include semantic_close_ref"):
        run_replay_fixture(fixture)


def test_replay_rejects_lalm_thinker_missing_degraded_event_for_unavailable_optional_ref() -> None:
    fixture, _ = _lalm_thinker_fixture(
        session_id="sess_lalm_thinker_replay_missing_degraded",
        event_id_prefix="evt_lalm_thinker_replay_missing_degraded",
        optional_refs_available=False,
    )
    fixture["events"] = [
        event
        for event in fixture["events"]
        if event.get("missing_capability") != "supports_semantic_close"
    ]

    with pytest.raises(ReplayValidationError, match="supports_semantic_close"):
        run_replay_fixture(fixture)


def test_replay_rejects_lalm_thinker_nested_provider_metadata_leakage() -> None:
    fixture, thinker_event = _lalm_thinker_fixture(
        session_id="sess_lalm_thinker_replay_nested_provider_leak",
        event_id_prefix="evt_lalm_thinker_replay_nested_provider_leak",
        optional_refs_available=True,
    )
    thinker = _event_by_id(fixture["events"], str(thinker_event["event_id"]))
    thinker["normalization_metadata"] = {
        "safe_ref": "validation://synthetic/lalm-thinker/nested-provider-leak",
        "provider_response": {"choices": [{"message": "provider-specific"}]},
    }

    with pytest.raises(ReplayValidationError, match="provider-specific schema or raw payload"):
        run_replay_fixture(fixture)


def test_replay_rejects_lalm_thinker_credential_like_ref_tampering() -> None:
    fixture, thinker_event = _lalm_thinker_fixture(
        session_id="sess_lalm_thinker_replay_unsafe_ref",
        event_id_prefix="evt_lalm_thinker_replay_unsafe_ref",
        optional_refs_available=True,
    )
    thinker = _event_by_id(fixture["events"], str(thinker_event["event_id"]))
    thinker["semantic_summary_ref"] = "summary://synthetic/lalm-thinker?api_key=sk-synthetic"

    with pytest.raises(ReplayValidationError, match="unsafe ref"):
        run_replay_fixture(fixture)


@pytest.mark.parametrize(
    ("field", "unsafe_ref"),
    (
        (
            "semantic_frame_ref",
            "https://dashscope.aliyuncs.com/compatible-mode/v1/raw-frame",
        ),
        ("semantic_summary_ref", "provider-url://dashscope/raw-summary"),
        (
            "semantic_close_ref",
            "/Users/a123/workspace/voice-agent-lalm-thinker/diagnostics/raw-close.json",
        ),
        (
            "assistant_directedness_ref",
            "assistant-directedness://synthetic/lalm-thinker/traces/session.jsonl",
        ),
        ("emotion_ref", "file:///Users/a123/workspace/voice-agent-lalm-thinker/raw-emotion.json"),
        (
            "audio_caption_ref",
            "audio-caption://synthetic/lalm-thinker/replays%2Flocal%2Fraw-caption.json",
        ),
    ),
)
def test_replay_rejects_lalm_thinker_provider_specific_or_local_ref_tampering(
    field: str,
    unsafe_ref: str,
) -> None:
    fixture, thinker_event = _lalm_thinker_fixture(
        session_id=f"sess_lalm_thinker_replay_{field}_tamper",
        event_id_prefix=f"evt_lalm_thinker_replay_{field}_tamper",
        optional_refs_available=True,
    )
    thinker = _event_by_id(fixture["events"], str(thinker_event["event_id"]))
    thinker[field] = unsafe_ref

    with pytest.raises(ReplayValidationError, match="safe ref"):
        run_replay_fixture(fixture)


def test_replay_runner_does_not_import_lalm_thinker_live_transport() -> None:
    source = Path("src/voice_agent/replay/runner.py").read_text(encoding="utf-8")

    assert "lalm_thinker_live_transport" not in source
    assert "DASHSCOPE_API_KEY" not in source
    assert "dashscope.aliyuncs.com" not in source


def _lalm_thinker_fixture(
    *,
    session_id: str,
    event_id_prefix: str,
    optional_refs_available: bool,
) -> tuple[dict[str, object], dict[str, object]]:
    startup = _start_lalm_thinker_session(session_id=session_id)
    committed_turn = _append_committed_text_turn(startup.journal, event_id_prefix=event_id_prefix)
    binding = bind_lalm_thinker_request(
        turn_committed_event=committed_turn,
        adapter_request_id=f"adapter-request-{event_id_prefix}",
        request_metadata_ref=f"request-metadata://synthetic/lalm-thinker/{event_id_prefix}",
        input_ref=f"text://synthetic/lalm-thinker/{event_id_prefix}",
        policy_ref="policy://synthetic/lalm-thinker/evidence-only",
    )
    candidate = parse_lalm_thinker_candidate_text(
        fake_lalm_thinker_transport(
            binding,
            optional_refs_available=optional_refs_available,
        )
    )
    validated = validate_lalm_thinker_candidate(candidate, expected_binding=binding)
    emission = emit_lalm_thinker_semantic_frame(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="lalm_thinker_provider_free",
        event_id=f"{event_id_prefix}_semantic_frame",
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        turn_committed_event=committed_turn,
        validated_candidate=validated,
    )
    return (
        {
            "replay_manifest": _github_allowed_replay_manifest(event_id_prefix),
            "events": startup.journal.events(),
        },
        emission.thinker_event,
    )


def _start_lalm_thinker_session(*, session_id: str) -> object:
    return start_configured_session(
        session_id=session_id,
        conversation_id="conv_lalm_thinker_replay_safety",
        runtime_config_ref="config://synthetic/lalm-thinker/replay-safety",
        created_monotonic_ms=100,
        created_wall_clock_ms=1700000000100,
        assembly_config=RuntimeAdapterAssemblyConfig(
            stage="mvp3",
            capability_snapshot_ref="capability://synthetic/lalm-thinker/replay-safety",
            capability_version="mvp3.lalm-thinker.replay-safety.v1",
        ),
        capabilities=_lalm_thinker_profiles(),
    )


def _append_committed_text_turn(
    journal: object,
    *,
    event_id_prefix: str,
) -> dict[str, object]:
    snapshot_event_id = str(journal.events()[1]["event_id"])
    text_received = journal.append(
        event_name="TEXT_INPUT_RECEIVED",
        event_id=f"{event_id_prefix}_text_received",
        source_module="access_layer",
        caused_by_event_id=snapshot_event_id,
        created_monotonic_ms=110,
        created_wall_clock_ms=1700000000110,
        trace_redaction_level="redacted_fixture",
        input_span_id=f"input_{event_id_prefix}",
        text_span_id=f"text_{event_id_prefix}",
        input_modality="text",
        directedness="ASSUMED_DIRECTED",
        semantic_close="ASSUMED_CLOSED",
        text_ref=f"text://synthetic/lalm-thinker/{event_id_prefix}",
    )
    turn_opened = journal.append(
        event_name="TURN_OPENED",
        event_id=f"{event_id_prefix}_turn_opened",
        source_module="interaction_controller",
        caused_by_event_id=str(text_received["event_id"]),
        created_monotonic_ms=111,
        created_wall_clock_ms=1700000000111,
        trace_redaction_level="metadata_only",
        turn_id=f"turn_{event_id_prefix}",
        input_span_id=f"input_{event_id_prefix}",
        input_modality="text",
        turn_phase="COLLECTING_INPUT",
    )
    accepted = journal.append(
        event_name="TURN_INGRESS_ACCEPTED",
        event_id=f"{event_id_prefix}_ingress_accepted",
        source_module="interaction_controller",
        caused_by_event_id=str(turn_opened["event_id"]),
        created_monotonic_ms=112,
        created_wall_clock_ms=1700000000112,
        trace_redaction_level="metadata_only",
        turn_id=f"turn_{event_id_prefix}",
        input_span_id=f"input_{event_id_prefix}",
        ingress_outcome="ACCEPTED",
    )
    return journal.append(
        event_name="TURN_INGRESS_COMMITTED",
        event_id=f"{event_id_prefix}_ingress_committed",
        source_module="interaction_controller",
        caused_by_event_id=str(accepted["event_id"]),
        created_monotonic_ms=113,
        created_wall_clock_ms=1700000000113,
        trace_redaction_level="metadata_only",
        turn_id=f"turn_{event_id_prefix}",
        utterance_id=f"utt_{event_id_prefix}",
        input_span_id=f"input_{event_id_prefix}",
        text_span_id=f"text_{event_id_prefix}",
        input_modality="text",
        directedness="ASSUMED_DIRECTED",
        semantic_close="ASSUMED_CLOSED",
        ingress_outcome="COMMITTED",
    )


def _github_allowed_replay_manifest(replay_id: str) -> dict[str, object]:
    return {
        "manifest_schema_version": "1.0",
        "replay_id": replay_id,
        "source_trace_ref": f"fixture://mvp3/lalm-thinker/{replay_id}",
        "replay_mode": "deterministic",
        "event_schema_version_range": ["1.0"],
        "fixture_domain": "GITHUB_ALLOWED",
        "generated_from": "hand_written_minimal",
        "contains_raw_audio": False,
        "contains_raw_trace": False,
        "contains_real_user_input": False,
        "contains_secrets": False,
        "contains_unredacted_tool_result": False,
        "contains_large_raw_web_content": False,
        "allowed_re_eval_components": [],
    }


def _lalm_thinker_profiles() -> tuple[object, ...]:
    return tuple(
        build_lalm_thinker_capability() if profile.adapter_type == "thinker" else profile
        for profile in valid_mvp3_real_profiles()
    )


def _event_by_id(events: object, event_id: str) -> dict[str, object]:
    assert isinstance(events, list)
    return next(event for event in events if event["event_id"] == event_id)
