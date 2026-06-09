from __future__ import annotations

import http.client
from pathlib import Path
import random
import socket
import time
import urllib.request

import pytest

from tests.adapters.test_mvp3_adapter_profiles import valid_mvp3_real_profiles
from voice_agent.adapters.asr_contract import AsrAdapterContract
from voice_agent.events.envelope import validate_event_envelope
from voice_agent.replay.runner import ReplayValidationError, run_replay_fixture
from voice_agent.runtime.adapter_callback_boundary import AdapterCallbackAppendBoundary
from voice_agent.runtime.assembly import RuntimeAdapterAssemblyConfig
from voice_agent.runtime.session import start_configured_session


SPEC_PATH = Path("docs/specs/mvp3-acceptance-scenarios.md")
ASR_OUTPUT_EVENT_NAME = "ASR_TRANSCRIPT_OUTPUT_EMITTED"


def test_mvp3_asr_contract_spec_names_slice4_contract() -> None:
    asr_section = SPEC_PATH.read_text(encoding="utf-8").split(
        "## Scenario MVP3-ASR-CONTRACT-001",
        maxsplit=1,
    )[1].split("## Scenario", maxsplit=1)[0]

    for required_text in (
        "ASR adapter final transcript or text projection contract",
        "ASR_TRANSCRIPT_OUTPUT_EMITTED",
        "Output mode is explicit",
        "no raw audio is committed",
        "missing timestamps degrade explicitly",
        "Replay uses recorded refs only",
        "No direct ASR provider call outside adapter",
    ):
        assert required_text in asr_section


def test_asr_final_transcript_contract_emits_normalized_refs_and_degradation_events_without_provider_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    startup = _start_mvp3_asr_contract_session()
    committed_turn = _append_committed_audio_turn(startup.journal)
    boundary = AdapterCallbackAppendBoundary(startup.journal)
    blocked_calls = _block_provider_runtime(monkeypatch)

    contract = AsrAdapterContract(
        boundary=boundary,
        adapter_id="mvp3_asr",
        output_mode="degraded",
    )

    emission = contract.emit_final_transcript(
        event_id="evt_mvp3_slice4_asr_transcript_output",
        caused_by_event_id=str(committed_turn["event_id"]),
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        turn_committed_event=committed_turn,
        adapter_request_id="adapter_request_mvp3_asr_slice4_001",
        asr_frame_ref="asr-frame://synthetic/mvp3/slice4/final-transcript-001",
        text_ref="text://synthetic/mvp3/slice4/final-transcript-001",
        audio_timestamps_ref=None,
        streaming_output_supported=False,
    )

    events = startup.journal.events()
    emitted = events[-3:]
    transcript = emission.transcript_event

    assert [event["event_name"] for event in emitted] == [
        "ADAPTER_OUTPUT_DEGRADED",
        "ADAPTER_OUTPUT_DEGRADED",
        ASR_OUTPUT_EVENT_NAME,
    ]
    assert emission.degraded_events == tuple(emitted[:2])
    assert transcript == emitted[2]
    assert [event["event_seq"] for event in emitted] == [10, 11, 12]
    assert [event["adapter_callback_seq"] for event in emitted] == [1, 2, 3]
    assert [event["missing_capability"] for event in emitted[:2]] == [
        "supports_audio_timestamps",
        "supports_streaming_output",
    ]
    assert {event["output_mode"] for event in emitted} == {"degraded"}

    assert transcript["adapter_id"] == "mvp3_asr"
    assert transcript["adapter_type"] == "asr"
    assert transcript["turn_id"] == committed_turn["turn_id"]
    assert transcript["utterance_id"] == committed_turn["utterance_id"]
    assert transcript["audio_span_id"] == committed_turn["audio_span_id"]
    assert transcript["input_modality"] == "audio"
    assert transcript["adapter_request_id"] == "adapter_request_mvp3_asr_slice4_001"
    assert transcript["asr_frame_ref"] == "asr-frame://synthetic/mvp3/slice4/final-transcript-001"
    assert transcript["text_ref"] == "text://synthetic/mvp3/slice4/final-transcript-001"
    assert transcript["transcript_finality"] == "final"
    assert transcript["timestamp_status"] == "unavailable"
    assert transcript["streaming_status"] == "unsupported_final_only"

    assert all(validate_event_envelope(event) == event for event in emitted)
    assert _forbidden_payload_terms_are_absent(events)

    replay_result = run_replay_fixture(
        {
            "replay_manifest": _github_allowed_replay_manifest(),
            "events": events,
        }
    )

    assert replay_result.result_status == "passed"
    assert replay_result.adapter_health_state.output_event_modes[transcript["event_id"]] == "degraded"
    assert replay_result.adapter_health_state.adapters["mvp3_asr"].missing_capabilities == (
        "supports_audio_timestamps",
        "supports_streaming_output",
    )
    assert {
        "event_id": transcript["event_id"],
        "field": "asr_frame_ref",
        "ref": "asr-frame://synthetic/mvp3/slice4/final-transcript-001",
        "status": "unavailable",
    } in replay_result.diagnostics["data_plane_refs"]
    assert {
        "event_id": transcript["event_id"],
        "field": "text_ref",
        "ref": "text://synthetic/mvp3/slice4/final-transcript-001",
        "status": "unavailable",
    } in replay_result.diagnostics["data_plane_refs"]
    assert blocked_calls == []


def test_replay_accepts_router_decision_referencing_real_asr_transcript_output() -> None:
    startup = _start_mvp3_asr_contract_session(session_id="sess_mvp3_slice4_asr_router_synthetic")
    committed_turn = _append_committed_audio_turn(startup.journal, event_id_prefix="evt_mvp3_slice4_asr_router")
    contract = AsrAdapterContract(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="mvp3_asr",
        output_mode="real",
    )
    emission = contract.emit_final_transcript(
        event_id="evt_mvp3_slice4_asr_router_transcript",
        caused_by_event_id=str(committed_turn["event_id"]),
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        turn_committed_event=committed_turn,
        adapter_request_id="adapter_request_mvp3_asr_router_001",
        asr_frame_ref="asr-frame://synthetic/mvp3/slice4/router-transcript-001",
        text_ref="text://synthetic/mvp3/slice4/router-transcript-001",
        audio_timestamps_ref="timestamps://synthetic/mvp3/slice4/router-transcript-001",
        streaming_output_supported=True,
    )
    router_event = startup.journal.append(
        event_name="ROUTER_DECISION_EMITTED",
        event_id="evt_mvp3_slice4_asr_router_decision",
        source_module="router",
        caused_by_event_id=str(emission.transcript_event["event_id"]),
        created_monotonic_ms=220,
        created_wall_clock_ms=1700000000220,
        trace_redaction_level="metadata_only",
        turn_id=str(committed_turn["turn_id"]),
        utterance_id=str(committed_turn["utterance_id"]),
        router_decision="FAST_ONLY",
        task_focus="FOREGROUND_CHAT",
        confidence=0.91,
        evidence_uncertainty="low",
        turn_committed_event_id=str(committed_turn["event_id"]),
        asr_frame_event_id=str(emission.transcript_event["event_id"]),
    )

    result = run_replay_fixture(
        {
            "replay_manifest": _github_allowed_replay_manifest(),
            "events": startup.journal.events(),
        }
    )

    assert result.task_focus_state.last_focus_event_id == router_event["event_id"]
    assert result.adapter_health_state.output_event_modes[emission.transcript_event["event_id"]] == "real"


def test_replay_tracks_available_asr_audio_timestamp_refs_as_data_plane_dependencies() -> None:
    startup = _start_mvp3_asr_contract_session(session_id="sess_mvp3_slice4_asr_timestamps_synthetic")
    committed_turn = _append_committed_audio_turn(startup.journal, event_id_prefix="evt_mvp3_slice4_asr_timestamps")
    contract = AsrAdapterContract(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="mvp3_asr",
        output_mode="real",
    )
    emission = contract.emit_final_transcript(
        event_id="evt_mvp3_slice4_asr_timestamps_transcript",
        caused_by_event_id=str(committed_turn["event_id"]),
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        turn_committed_event=committed_turn,
        adapter_request_id="adapter_request_mvp3_asr_timestamps_001",
        asr_frame_ref="asr-frame://synthetic/mvp3/slice4/timestamps-transcript-001",
        text_ref="text://synthetic/mvp3/slice4/timestamps-transcript-001",
        audio_timestamps_ref="timestamps://synthetic/mvp3/slice4/timestamps-transcript-001",
        streaming_output_supported=True,
    )

    result = run_replay_fixture(
        {
            "replay_manifest": _github_allowed_replay_manifest(),
            "events": startup.journal.events(),
        }
    )

    assert {
        "event_id": emission.transcript_event["event_id"],
        "field": "audio_timestamps_ref",
        "ref": "timestamps://synthetic/mvp3/slice4/timestamps-transcript-001",
        "status": "unavailable",
    } in result.diagnostics["data_plane_refs"]


@pytest.mark.parametrize(
    ("status_field", "invalid_status"),
    (
        ("timestamp_status", "missing"),
        ("streaming_status", "unsupported"),
    ),
)
def test_replay_rejects_noncanonical_asr_status_values(status_field: str, invalid_status: str) -> None:
    startup = _start_mvp3_asr_contract_session(session_id=f"sess_mvp3_slice4_asr_bad_{status_field}_synthetic")
    committed_turn = _append_committed_audio_turn(startup.journal, event_id_prefix=f"evt_mvp3_slice4_asr_bad_{status_field}")
    contract = AsrAdapterContract(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="mvp3_asr",
        output_mode="real",
    )
    emission = contract.emit_final_transcript(
        event_id=f"evt_mvp3_slice4_asr_bad_{status_field}_transcript",
        caused_by_event_id=str(committed_turn["event_id"]),
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        turn_committed_event=committed_turn,
        adapter_request_id=f"adapter_request_mvp3_asr_bad_{status_field}_001",
        asr_frame_ref=f"asr-frame://synthetic/mvp3/slice4/bad-{status_field}",
        text_ref=f"text://synthetic/mvp3/slice4/bad-{status_field}",
        audio_timestamps_ref=f"timestamps://synthetic/mvp3/slice4/bad-{status_field}",
        streaming_output_supported=True,
    )
    events = startup.journal.events()
    transcript = next(event for event in events if event["event_id"] == emission.transcript_event["event_id"])
    transcript[status_field] = invalid_status

    with pytest.raises(ReplayValidationError, match=status_field):
        run_replay_fixture(
            {
                "replay_manifest": _github_allowed_replay_manifest(),
                "events": events,
            }
        )


@pytest.mark.parametrize("output_mode", ("real", "fallback", "degraded"))
def test_asr_contract_accepts_explicit_real_fallback_or_degraded_output_modes(output_mode: str) -> None:
    startup = _start_mvp3_asr_contract_session(session_id=f"sess_mvp3_slice4_{output_mode}_synthetic")
    committed_turn = _append_committed_audio_turn(startup.journal, event_id_prefix=f"evt_mvp3_slice4_{output_mode}")
    contract = AsrAdapterContract(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="mvp3_asr",
        output_mode=output_mode,
    )

    emission = contract.emit_final_transcript(
        event_id=f"evt_mvp3_slice4_asr_transcript_{output_mode}",
        caused_by_event_id=str(committed_turn["event_id"]),
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        turn_committed_event=committed_turn,
        adapter_request_id=f"adapter_request_mvp3_asr_slice4_{output_mode}",
        asr_frame_ref=f"asr-frame://synthetic/mvp3/slice4/{output_mode}",
        text_ref=f"text://synthetic/mvp3/slice4/{output_mode}",
        audio_timestamps_ref=f"timestamps://synthetic/mvp3/slice4/{output_mode}",
        streaming_output_supported=True,
    )

    assert emission.degraded_events == ()
    assert emission.transcript_event["event_name"] == ASR_OUTPUT_EVENT_NAME
    assert emission.transcript_event["output_mode"] == output_mode
    assert emission.transcript_event["timestamp_status"] == "available"
    assert emission.transcript_event["streaming_status"] == "supported"


def _start_mvp3_asr_contract_session(*, session_id: str = "sess_mvp3_slice4_asr_synthetic") -> object:
    return start_configured_session(
        session_id=session_id,
        conversation_id="conv_mvp3_slice4_asr_synthetic",
        runtime_config_ref="config://synthetic/mvp3/slice4-asr-contract",
        created_monotonic_ms=100,
        created_wall_clock_ms=1700000000100,
        assembly_config=RuntimeAdapterAssemblyConfig(
            stage="mvp3",
            capability_snapshot_ref="capability://synthetic/mvp3/slice4-asr-contract",
            capability_version="mvp3.contract.v1",
        ),
        capabilities=valid_mvp3_real_profiles(),
    )


def _append_committed_audio_turn(
    journal: object,
    *,
    event_id_prefix: str = "evt_mvp3_slice4_asr",
) -> dict[str, object]:
    snapshot_event_id = str(journal.events()[1]["event_id"])
    audio_started = journal.append(
        event_name="AUDIO_SPAN_STARTED",
        event_id=f"{event_id_prefix}_audio_started",
        source_module="access_layer",
        caused_by_event_id=snapshot_event_id,
        created_monotonic_ms=101,
        created_wall_clock_ms=1700000000101,
        trace_redaction_level="metadata_only",
        audio_span_id="audio_mvp3_slice4_001",
        input_modality="audio",
        audio_sample_offset=0,
        audio_format_ref="audio-format://synthetic/mvp3/pcm16-16khz-mono",
    )
    speech_started = journal.append(
        event_name="SPEECH_START_DETECTED",
        event_id=f"{event_id_prefix}_speech_started",
        source_module="duplex",
        caused_by_event_id=str(audio_started["event_id"]),
        created_monotonic_ms=102,
        created_wall_clock_ms=1700000000102,
        trace_redaction_level="metadata_only",
        audio_span_id="audio_mvp3_slice4_001",
        audio_sample_offset=0,
        vad_confidence=0.97,
    )
    turn_opened = journal.append(
        event_name="TURN_OPENED",
        event_id=f"{event_id_prefix}_turn_opened",
        source_module="interaction_controller",
        caused_by_event_id=str(speech_started["event_id"]),
        created_monotonic_ms=103,
        created_wall_clock_ms=1700000000103,
        trace_redaction_level="metadata_only",
        turn_id="turn_mvp3_slice4_001",
        audio_span_id="audio_mvp3_slice4_001",
        input_modality="audio",
        turn_phase="COLLECTING_INPUT",
    )
    audio_ended = journal.append(
        event_name="AUDIO_SPAN_ENDED",
        event_id=f"{event_id_prefix}_audio_ended",
        source_module="access_layer",
        caused_by_event_id=str(audio_started["event_id"]),
        created_monotonic_ms=160,
        created_wall_clock_ms=1700000000160,
        trace_redaction_level="metadata_only",
        audio_span_id="audio_mvp3_slice4_001",
        audio_sample_offset=16000,
        duration_ms=1000,
        end_reason="synthetic_turn_complete",
    )
    speech_ended = journal.append(
        event_name="SPEECH_END_DETECTED",
        event_id=f"{event_id_prefix}_speech_ended",
        source_module="duplex",
        caused_by_event_id=str(audio_ended["event_id"]),
        created_monotonic_ms=161,
        created_wall_clock_ms=1700000000161,
        trace_redaction_level="metadata_only",
        audio_span_id="audio_mvp3_slice4_001",
        audio_sample_offset=16000,
        vad_confidence=0.96,
        silence_duration_ms=600,
    )
    accepted = journal.append(
        event_name="TURN_INGRESS_ACCEPTED",
        event_id=f"{event_id_prefix}_ingress_accepted",
        source_module="interaction_controller",
        caused_by_event_id=str(speech_ended["event_id"]),
        created_monotonic_ms=170,
        created_wall_clock_ms=1700000000170,
        trace_redaction_level="metadata_only",
        turn_id="turn_mvp3_slice4_001",
        audio_span_id="audio_mvp3_slice4_001",
        ingress_outcome="ACCEPTED",
    )
    return journal.append(
        event_name="TURN_INGRESS_COMMITTED",
        event_id=f"{event_id_prefix}_ingress_committed",
        source_module="interaction_controller",
        caused_by_event_id=str(accepted["event_id"]),
        created_monotonic_ms=171,
        created_wall_clock_ms=1700000000171,
        trace_redaction_level="metadata_only",
        turn_id="turn_mvp3_slice4_001",
        utterance_id="utt_mvp3_slice4_001",
        audio_span_id="audio_mvp3_slice4_001",
        input_modality="audio",
        directedness="ASSUMED_DIRECTED",
        semantic_close="ASSUMED_CLOSED",
        ingress_outcome="COMMITTED",
    )


def _github_allowed_replay_manifest() -> dict[str, object]:
    return {
        "manifest_schema_version": "1.0",
        "replay_id": "replay_mvp3_slice4_asr_contract_synthetic",
        "source_trace_ref": "fixture://mvp3/slice4-asr-contract",
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


def _block_provider_runtime(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    blocked_calls: list[object] = []

    def fail_if_called(*args: object, **kwargs: object) -> None:
        blocked_calls.append((args, kwargs))
        raise AssertionError("ASR contract and replay must not call provider runtime")

    monkeypatch.setattr(socket, "create_connection", fail_if_called)
    monkeypatch.setattr(http.client.HTTPConnection, "connect", fail_if_called)
    monkeypatch.setattr(http.client.HTTPSConnection, "connect", fail_if_called)
    monkeypatch.setattr(urllib.request, "urlopen", fail_if_called)
    monkeypatch.setattr(time, "time", fail_if_called)
    monkeypatch.setattr(time, "monotonic", fail_if_called)
    monkeypatch.setattr(random, "random", fail_if_called)
    return blocked_calls


def _forbidden_payload_terms_are_absent(events: list[dict[str, object]]) -> bool:
    rendered = repr(events)
    forbidden_terms = (
        "raw_audio",
        "audio_bytes",
        "audio_payload",
        "raw_trace",
        "raw_transcript",
        "provider_response",
        "authorization",
        "credential",
        "api_key",
        "token",
    )
    return all(term not in rendered.lower() for term in forbidden_terms)
