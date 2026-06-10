from __future__ import annotations

import http.client
from pathlib import Path
import random
import socket
import time
import urllib.request

import pytest

from tests.adapters.test_mvp3_adapter_profiles import valid_mvp3_real_profiles
from voice_agent.adapters.event_harness import FakeRealAdapterEventHarness
from voice_agent.events.envelope import validate_event_envelope
from voice_agent.replay.runner import ReplayValidationError, run_replay_fixture
from voice_agent.runtime.adapter_callback_boundary import AdapterCallbackAppendBoundary
from voice_agent.runtime.assembly import RuntimeAdapterAssemblyConfig
from voice_agent.runtime.session import start_configured_session


SPEC_PATH = Path("docs/specs/mvp3-acceptance-scenarios.md")
TTS_OUTPUT_EVENT_NAME = "TTS_SYNTHESIS_OUTPUT_EMITTED"


def test_mvp3_tts_contract_spec_names_slice7_contract() -> None:
    tts_section = SPEC_PATH.read_text(encoding="utf-8").split(
        "## Scenario MVP3-TTS-CONTRACT-001",
        maxsplit=1,
    )[1].split("## Scenario", maxsplit=1)[0]

    for required_text in (
        "TTS basic synthesis refs and truncate capability handling",
        "TTS_SYNTHESIS_OUTPUT_EMITTED",
        "output_mode=real|fallback|degraded",
        "safe normalized audio refs/metadata",
        "missing truncate capability blocks or degrades barge-in target validation",
        "Retry/failure/degraded path is event-visible",
        "Replay uses recorded refs only",
        "No raw audio fixture or pause/resume scope",
    ):
        assert required_text in tts_section


def test_tts_contract_emits_safe_synthesis_refs_and_playback_link_without_provider_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from voice_agent.adapters.tts_contract import TtsSynthesisAdapterContract

    startup = _start_mvp3_tts_contract_session()
    approved_check = _append_approved_spoken_plan_chain(startup.journal)
    boundary = AdapterCallbackAppendBoundary(startup.journal)
    blocked_calls = _block_provider_runtime(monkeypatch)

    contract = TtsSynthesisAdapterContract(
        boundary=boundary,
        adapter_id="mvp3_tts",
        output_mode="real",
    )

    emission = contract.emit_synthesis_output(
        event_id="evt_mvp3_slice7_tts_synthesis_output",
        caused_by_event_id=str(approved_check["event_id"]),
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        approved_check_event=approved_check,
        adapter_request_id="adapter_request_mvp3_tts_slice7_001",
        audio_ref="audio://synthetic/mvp3/slice7/synthesis-001",
        tts_stream_ref="tts-stream://synthetic/mvp3/slice7/synthesis-001",
        audio_format_ref="audio-format://synthetic/mvp3/tts/opus-24khz-mono",
        synthesis_result_ref="tts-result://synthetic/mvp3/slice7/synthesis-001",
        truncate_supported=True,
    )
    playback = _append_playback_started_from_tts(
        startup.journal,
        approved_check=approved_check,
        tts_event=emission.synthesis_event,
    )

    events = startup.journal.events()
    emitted = events[-2:]
    tts_event = emission.synthesis_event

    assert [event["event_name"] for event in emitted] == [
        TTS_OUTPUT_EVENT_NAME,
        "PLAYBACK_SPAN_STARTED",
    ]
    assert tts_event == emitted[0]
    assert playback == emitted[1]
    assert tts_event["event_seq"] == 8
    assert tts_event["adapter_callback_seq"] == 1
    assert tts_event["adapter_id"] == "mvp3_tts"
    assert tts_event["adapter_type"] == "tts"
    assert tts_event["adapter_request_id"] == "adapter_request_mvp3_tts_slice7_001"
    assert tts_event["spoken_plan_id"] == approved_check["spoken_plan_id"]
    assert tts_event["approved_check_event_id"] == approved_check["event_id"]
    assert tts_event["audio_ref"] == "audio://synthetic/mvp3/slice7/synthesis-001"
    assert tts_event["tts_stream_ref"] == "tts-stream://synthetic/mvp3/slice7/synthesis-001"
    assert tts_event["audio_format_ref"] == "audio-format://synthetic/mvp3/tts/opus-24khz-mono"
    assert tts_event["synthesis_result_ref"] == "tts-result://synthetic/mvp3/slice7/synthesis-001"
    assert tts_event["truncate_status"] == "supported"
    assert tts_event["output_mode"] == "real"
    assert playback["tts_output_event_id"] == tts_event["event_id"]
    assert playback["audio_ref"] == tts_event["audio_ref"]
    assert playback["tts_stream_ref"] == tts_event["tts_stream_ref"]
    assert "raw_audio" not in tts_event
    assert "audio_bytes" not in tts_event
    assert "provider_response" not in tts_event

    assert all(validate_event_envelope(event) == event for event in emitted)
    assert _forbidden_payload_terms_are_absent(events)

    replay_result = run_replay_fixture(
        {
            "replay_manifest": _github_allowed_replay_manifest(),
            "events": events,
        }
    )

    assert replay_result.result_status == "passed"
    assert replay_result.adapter_health_state.output_event_modes[tts_event["event_id"]] == "real"
    assert replay_result.playback_state.current_playback_span_id == playback["playback_span_id"]
    assert {
        "event_id": tts_event["event_id"],
        "field": "audio_ref",
        "ref": "audio://synthetic/mvp3/slice7/synthesis-001",
        "status": "unavailable",
    } in replay_result.diagnostics["data_plane_refs"]
    assert {
        "event_id": tts_event["event_id"],
        "field": "synthesis_result_ref",
        "ref": "tts-result://synthetic/mvp3/slice7/synthesis-001",
        "status": "unavailable",
    } in replay_result.diagnostics["data_plane_refs"]
    assert blocked_calls == []


def test_missing_tts_truncate_capability_emits_degraded_blocking_metadata() -> None:
    from voice_agent.adapters.tts_contract import TtsSynthesisAdapterContract

    startup = _start_mvp3_tts_contract_session(
        session_id="sess_mvp3_slice7_tts_truncate_degraded_synthetic",
    )
    approved_check = _append_approved_spoken_plan_chain(
        startup.journal,
        event_id_prefix="evt_mvp3_slice7_tts_truncate_degraded",
    )
    contract = TtsSynthesisAdapterContract(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="mvp3_tts",
        output_mode="degraded",
    )

    emission = contract.emit_synthesis_output(
        event_id="evt_mvp3_slice7_tts_truncate_degraded_output",
        caused_by_event_id=str(approved_check["event_id"]),
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        approved_check_event=approved_check,
        adapter_request_id="adapter_request_mvp3_tts_truncate_degraded_001",
        audio_ref="audio://synthetic/mvp3/slice7/truncate-degraded",
        tts_stream_ref=None,
        audio_format_ref="audio-format://synthetic/mvp3/tts/opus-24khz-mono",
        synthesis_result_ref="tts-result://synthetic/mvp3/slice7/truncate-degraded",
        truncate_supported=False,
    )

    emitted = startup.journal.events()[-2:]

    assert [event["event_name"] for event in emitted] == [
        "ADAPTER_OUTPUT_DEGRADED",
        TTS_OUTPUT_EVENT_NAME,
    ]
    assert emission.degraded_events == (emitted[0],)
    assert emitted[0]["missing_capability"] == "supports_tts_truncate"
    assert emitted[0]["degraded_reason"] == "supports_tts_truncate"
    assert emitted[0]["output_mode"] == "degraded"
    assert emission.synthesis_event["truncate_status"] == "unsupported_blocked"
    assert emission.synthesis_event["output_mode"] == "degraded"

    replay_result = run_replay_fixture(
        {
            "replay_manifest": _github_allowed_replay_manifest(),
            "events": startup.journal.events(),
        }
    )

    assert replay_result.result_status == "passed"
    assert replay_result.adapter_health_state.adapters["mvp3_tts"].missing_capabilities == (
        "supports_tts_truncate",
    )


def test_replay_rejects_truncate_request_against_tts_output_missing_truncate_capability() -> None:
    from voice_agent.adapters.tts_contract import TtsSynthesisAdapterContract

    startup = _start_mvp3_tts_contract_session(
        session_id="sess_mvp3_slice7_tts_truncate_blocked_synthetic",
    )
    approved_check = _append_approved_spoken_plan_chain(
        startup.journal,
        event_id_prefix="evt_mvp3_slice7_tts_truncate_blocked",
    )
    emission = TtsSynthesisAdapterContract(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="mvp3_tts",
        output_mode="degraded",
    ).emit_synthesis_output(
        event_id="evt_mvp3_slice7_tts_truncate_blocked_output",
        caused_by_event_id=str(approved_check["event_id"]),
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        approved_check_event=approved_check,
        adapter_request_id="adapter_request_mvp3_tts_truncate_blocked_001",
        audio_ref="audio://synthetic/mvp3/slice7/truncate-blocked",
        tts_stream_ref=None,
        audio_format_ref="audio-format://synthetic/mvp3/tts/opus-24khz-mono",
        synthesis_result_ref="tts-result://synthetic/mvp3/slice7/truncate-blocked",
        truncate_supported=False,
    )
    playback = _append_playback_started_from_tts(
        startup.journal,
        approved_check=approved_check,
        tts_event=emission.synthesis_event,
        event_id="evt_mvp3_slice7_tts_truncate_blocked_playback_started",
    )
    interrupt = startup.journal.append(
        event_name="INTERRUPT_CANDIDATE",
        event_id="evt_mvp3_slice7_tts_truncate_blocked_interrupt",
        source_module="interaction_controller",
        caused_by_event_id=str(playback["event_id"]),
        created_monotonic_ms=220,
        created_wall_clock_ms=1700000000220,
        trace_redaction_level="metadata_only",
        playback_span_id=str(playback["playback_span_id"]),
        playback_offset_ms=320,
        policy_reason="barge_in_candidate",
        confidence_summary="synthetic high-confidence interruption",
    )
    startup.journal.append(
        event_name="TTS_TRUNCATE_REQUESTED",
        event_id="evt_mvp3_slice7_tts_truncate_blocked_requested",
        source_module="interaction_controller",
        caused_by_event_id=str(interrupt["event_id"]),
        created_monotonic_ms=221,
        created_wall_clock_ms=1700000000221,
        trace_redaction_level="metadata_only",
        playback_span_id=str(playback["playback_span_id"]),
        cutoff_playback_offset_ms=320,
        interrupt_candidate_event_id=str(interrupt["event_id"]),
    )

    with pytest.raises(ReplayValidationError, match="truncate capability"):
        run_replay_fixture(
            {
                "replay_manifest": _github_allowed_replay_manifest(),
                "events": startup.journal.events(),
            }
        )


def test_replay_rejects_truncate_request_when_blocked_tts_playback_omits_output_link() -> None:
    from voice_agent.adapters.tts_contract import TtsSynthesisAdapterContract

    startup = _start_mvp3_tts_contract_session(
        session_id="sess_mvp3_slice7_tts_truncate_unlinked_synthetic",
    )
    approved_check = _append_approved_spoken_plan_chain(
        startup.journal,
        event_id_prefix="evt_mvp3_slice7_tts_truncate_unlinked",
    )
    emission = TtsSynthesisAdapterContract(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="mvp3_tts",
        output_mode="degraded",
    ).emit_synthesis_output(
        event_id="evt_mvp3_slice7_tts_truncate_unlinked_output",
        caused_by_event_id=str(approved_check["event_id"]),
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        approved_check_event=approved_check,
        adapter_request_id="adapter_request_mvp3_tts_truncate_unlinked_001",
        audio_ref="audio://synthetic/mvp3/slice7/truncate-unlinked",
        tts_stream_ref=None,
        audio_format_ref="audio-format://synthetic/mvp3/tts/opus-24khz-mono",
        synthesis_result_ref="tts-result://synthetic/mvp3/slice7/truncate-unlinked",
        truncate_supported=False,
    )
    playback = _append_playback_started_from_tts(
        startup.journal,
        approved_check=approved_check,
        tts_event=emission.synthesis_event,
        event_id="evt_mvp3_slice7_tts_truncate_unlinked_playback_started",
        include_tts_output_event_id=False,
    )
    interrupt = startup.journal.append(
        event_name="INTERRUPT_CANDIDATE",
        event_id="evt_mvp3_slice7_tts_truncate_unlinked_interrupt",
        source_module="interaction_controller",
        caused_by_event_id=str(playback["event_id"]),
        created_monotonic_ms=220,
        created_wall_clock_ms=1700000000220,
        trace_redaction_level="metadata_only",
        playback_span_id=str(playback["playback_span_id"]),
        playback_offset_ms=320,
        policy_reason="barge_in_candidate",
        confidence_summary="synthetic high-confidence interruption",
    )
    startup.journal.append(
        event_name="TTS_TRUNCATE_REQUESTED",
        event_id="evt_mvp3_slice7_tts_truncate_unlinked_requested",
        source_module="interaction_controller",
        caused_by_event_id=str(interrupt["event_id"]),
        created_monotonic_ms=221,
        created_wall_clock_ms=1700000000221,
        trace_redaction_level="metadata_only",
        playback_span_id=str(playback["playback_span_id"]),
        cutoff_playback_offset_ms=320,
        interrupt_candidate_event_id=str(interrupt["event_id"]),
    )

    assert "tts_output_event_id" not in playback
    with pytest.raises(ReplayValidationError, match="truncate capability"):
        run_replay_fixture(
            {
                "replay_manifest": _github_allowed_replay_manifest(),
                "events": startup.journal.events(),
            }
        )


@pytest.mark.parametrize(
    ("unsafe_field", "unsafe_ref"),
    (
        ("audio_ref", "audio/raw/mvp3/slice7/unsafe.wav"),
        ("audio_ref", "data:audio/wav;base64,UklGRg=="),
        ("tts_stream_ref", "traces/mvp3/slice7/unsafe-stream"),
        ("tts_stream_ref", "data:audio/ogg;base64,T2dnUw=="),
        ("synthesis_result_ref", "diagnostics/mvp3/slice7/unsafe-result"),
        ("synthesis_result_ref", "data:audio/mpeg;base64,//uQZAAA"),
    ),
)
def test_tts_contract_rejects_local_raw_or_debug_refs_before_journal_append(
    unsafe_field: str,
    unsafe_ref: str,
) -> None:
    from voice_agent.adapters.tts_contract import (
        TtsSynthesisAdapterContract,
        TtsSynthesisAdapterContractError,
    )

    startup = _start_mvp3_tts_contract_session(
        session_id=f"sess_mvp3_slice7_tts_unsafe_{unsafe_field}_synthetic",
    )
    approved_check = _append_approved_spoken_plan_chain(
        startup.journal,
        event_id_prefix=f"evt_mvp3_slice7_tts_unsafe_{unsafe_field}",
    )
    event_count_before = len(startup.journal.events())
    refs = {
        "audio_ref": "audio://synthetic/mvp3/slice7/safe",
        "tts_stream_ref": None,
        "audio_format_ref": "audio-format://synthetic/mvp3/tts/opus-24khz-mono",
        "synthesis_result_ref": "tts-result://synthetic/mvp3/slice7/safe",
    }
    refs[unsafe_field] = unsafe_ref

    with pytest.raises(TtsSynthesisAdapterContractError, match="safe ref"):
        TtsSynthesisAdapterContract(
            boundary=AdapterCallbackAppendBoundary(startup.journal),
            adapter_id="mvp3_tts",
            output_mode="real",
        ).emit_synthesis_output(
            event_id=f"evt_mvp3_slice7_tts_unsafe_{unsafe_field}_output",
            caused_by_event_id=str(approved_check["event_id"]),
            created_monotonic_ms=210,
            created_wall_clock_ms=1700000000210,
            approved_check_event=approved_check,
            adapter_request_id=f"adapter_request_mvp3_tts_unsafe_{unsafe_field}_001",
            truncate_supported=True,
            **refs,
        )

    assert len(startup.journal.events()) == event_count_before


def test_replay_rejects_raw_audio_data_uri_tts_refs() -> None:
    from voice_agent.adapters.tts_contract import TtsSynthesisAdapterContract

    startup = _start_mvp3_tts_contract_session(
        session_id="sess_mvp3_slice7_tts_data_uri_replay_synthetic",
    )
    approved_check = _append_approved_spoken_plan_chain(
        startup.journal,
        event_id_prefix="evt_mvp3_slice7_tts_data_uri_replay",
    )
    emission = TtsSynthesisAdapterContract(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="mvp3_tts",
        output_mode="real",
    ).emit_synthesis_output(
        event_id="evt_mvp3_slice7_tts_data_uri_replay_output",
        caused_by_event_id=str(approved_check["event_id"]),
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        approved_check_event=approved_check,
        adapter_request_id="adapter_request_mvp3_tts_data_uri_replay_001",
        audio_ref="audio://synthetic/mvp3/slice7/data-uri-replay",
        tts_stream_ref=None,
        audio_format_ref="audio-format://synthetic/mvp3/tts/opus-24khz-mono",
        synthesis_result_ref="tts-result://synthetic/mvp3/slice7/data-uri-replay",
        truncate_supported=True,
    )
    events = startup.journal.events()
    tts_event = next(event for event in events if event["event_id"] == emission.synthesis_event["event_id"])
    tts_event["audio_ref"] = "data:audio/wav;base64,UklGRg=="

    with pytest.raises(ReplayValidationError, match="safe ref"):
        run_replay_fixture(
            {
                "replay_manifest": _github_allowed_replay_manifest(),
                "events": events,
            }
        )


def test_replay_accepts_linked_playback_that_consumes_one_of_two_tts_refs() -> None:
    from voice_agent.adapters.tts_contract import TtsSynthesisAdapterContract

    startup = _start_mvp3_tts_contract_session(
        session_id="sess_mvp3_slice7_tts_single_ref_playback_synthetic",
    )
    approved_check = _append_approved_spoken_plan_chain(
        startup.journal,
        event_id_prefix="evt_mvp3_slice7_tts_single_ref_playback",
    )
    emission = TtsSynthesisAdapterContract(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="mvp3_tts",
        output_mode="real",
    ).emit_synthesis_output(
        event_id="evt_mvp3_slice7_tts_single_ref_playback_output",
        caused_by_event_id=str(approved_check["event_id"]),
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        approved_check_event=approved_check,
        adapter_request_id="adapter_request_mvp3_tts_single_ref_playback_001",
        audio_ref="audio://synthetic/mvp3/slice7/single-ref-playback",
        tts_stream_ref="tts-stream://synthetic/mvp3/slice7/single-ref-playback",
        audio_format_ref="audio-format://synthetic/mvp3/tts/opus-24khz-mono",
        synthesis_result_ref="tts-result://synthetic/mvp3/slice7/single-ref-playback",
        truncate_supported=True,
    )
    playback = _append_playback_started_from_tts(
        startup.journal,
        approved_check=approved_check,
        tts_event=emission.synthesis_event,
        event_id="evt_mvp3_slice7_tts_single_ref_playback_started",
        include_tts_stream_ref=False,
    )

    result = run_replay_fixture(
        {
            "replay_manifest": _github_allowed_replay_manifest(),
            "events": startup.journal.events(),
        }
    )

    assert result.result_status == "passed"
    assert playback["audio_ref"] == emission.synthesis_event["audio_ref"]
    assert "tts_stream_ref" not in playback


def test_tts_retry_failure_and_degraded_paths_are_replay_visible() -> None:
    startup = _start_mvp3_tts_contract_session(
        session_id="sess_mvp3_slice7_tts_failure_paths_synthetic",
    )
    approved_check = _append_approved_spoken_plan_chain(
        startup.journal,
        event_id_prefix="evt_mvp3_slice7_tts_failure_paths",
    )
    harness = FakeRealAdapterEventHarness(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="mvp3_tts",
        adapter_type="tts",
        output_mode="degraded",
    )

    retrying = harness.emit_request_retrying(
        event_id="evt_mvp3_slice7_tts_retrying",
        caused_by_event_id=str(approved_check["event_id"]),
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        adapter_request_id="adapter_request_mvp3_tts_failure_paths_001",
        retry_count=1,
        retry_reason="synthetic_timeout",
        timeout_ms=800,
    )
    failed = harness.emit_request_failed(
        event_id="evt_mvp3_slice7_tts_failed",
        caused_by_event_id=str(retrying["event_id"]),
        created_monotonic_ms=211,
        created_wall_clock_ms=1700000000211,
        adapter_request_id="adapter_request_mvp3_tts_failure_paths_001",
        failure_reason="synthetic_tts_provider_unavailable",
        retryable=False,
        timeout_ms=800,
    )
    degraded = harness.emit_output_degraded(
        event_id="evt_mvp3_slice7_tts_degraded",
        caused_by_event_id=str(failed["event_id"]),
        created_monotonic_ms=212,
        created_wall_clock_ms=1700000000212,
        adapter_request_id="adapter_request_mvp3_tts_failure_paths_001",
        degraded_reason="fallback_audio_unavailable",
        missing_capability="supports_tts",
    )

    assert [retrying["event_name"], failed["event_name"], degraded["event_name"]] == [
        "ADAPTER_REQUEST_RETRYING",
        "ADAPTER_REQUEST_FAILED",
        "ADAPTER_OUTPUT_DEGRADED",
    ]
    assert all(validate_event_envelope(event) == event for event in (retrying, failed, degraded))

    replay_result = run_replay_fixture(
        {
            "replay_manifest": _github_allowed_replay_manifest(),
            "events": startup.journal.events(),
        }
    )

    adapter = replay_result.adapter_health_state.adapters["mvp3_tts"]
    assert replay_result.result_status == "passed"
    assert adapter.retry_count == 1
    assert adapter.failure_count == 1
    assert adapter.latest_degradation_reason == "fallback_audio_unavailable"
    assert adapter.missing_capabilities == ("supports_tts",)


def test_replay_rejects_nested_provider_specific_tts_payload() -> None:
    from voice_agent.adapters.tts_contract import TtsSynthesisAdapterContract

    startup = _start_mvp3_tts_contract_session(
        session_id="sess_mvp3_slice7_tts_nested_provider_payload_synthetic",
    )
    approved_check = _append_approved_spoken_plan_chain(
        startup.journal,
        event_id_prefix="evt_mvp3_slice7_tts_nested_provider_payload",
    )
    emission = TtsSynthesisAdapterContract(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="mvp3_tts",
        output_mode="real",
    ).emit_synthesis_output(
        event_id="evt_mvp3_slice7_tts_nested_provider_payload_output",
        caused_by_event_id=str(approved_check["event_id"]),
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        approved_check_event=approved_check,
        adapter_request_id="adapter_request_mvp3_tts_nested_provider_payload_001",
        audio_ref="audio://synthetic/mvp3/slice7/nested-provider-payload",
        tts_stream_ref=None,
        audio_format_ref="audio-format://synthetic/mvp3/tts/opus-24khz-mono",
        synthesis_result_ref="tts-result://synthetic/mvp3/slice7/nested-provider-payload",
        truncate_supported=True,
    )
    events = startup.journal.events()
    tts_event = next(event for event in events if event["event_id"] == emission.synthesis_event["event_id"])
    tts_event["adapter_metadata"] = {
        "provider_response": {"audio": "provider-specific"},
    }

    with pytest.raises(ReplayValidationError, match="provider-specific|raw audio"):
        run_replay_fixture(
            {
                "replay_manifest": _github_allowed_replay_manifest(),
                "events": events,
            }
        )


@pytest.mark.parametrize("output_mode", ("real", "fallback", "degraded"))
def test_tts_contract_accepts_explicit_real_fallback_or_degraded_output_modes(output_mode: str) -> None:
    from voice_agent.adapters.tts_contract import TtsSynthesisAdapterContract

    startup = _start_mvp3_tts_contract_session(
        session_id=f"sess_mvp3_slice7_tts_{output_mode}_synthetic",
    )
    approved_check = _append_approved_spoken_plan_chain(
        startup.journal,
        event_id_prefix=f"evt_mvp3_slice7_tts_{output_mode}",
    )
    contract = TtsSynthesisAdapterContract(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="mvp3_tts",
        output_mode=output_mode,
    )

    emission = contract.emit_synthesis_output(
        event_id=f"evt_mvp3_slice7_tts_output_{output_mode}",
        caused_by_event_id=str(approved_check["event_id"]),
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        approved_check_event=approved_check,
        adapter_request_id=f"adapter_request_mvp3_tts_{output_mode}_001",
        audio_ref=f"audio://synthetic/mvp3/slice7/{output_mode}",
        tts_stream_ref=None,
        audio_format_ref="audio-format://synthetic/mvp3/tts/opus-24khz-mono",
        synthesis_result_ref=f"tts-result://synthetic/mvp3/slice7/{output_mode}",
        truncate_supported=True,
    )

    assert emission.degraded_events == ()
    assert emission.synthesis_event["event_name"] == TTS_OUTPUT_EVENT_NAME
    assert emission.synthesis_event["output_mode"] == output_mode
    assert emission.synthesis_event["truncate_status"] == "supported"


def _start_mvp3_tts_contract_session(*, session_id: str = "sess_mvp3_slice7_tts_synthetic") -> object:
    return start_configured_session(
        session_id=session_id,
        conversation_id="conv_mvp3_slice7_tts_synthetic",
        runtime_config_ref="config://synthetic/mvp3/slice7-tts-contract",
        created_monotonic_ms=100,
        created_wall_clock_ms=1700000000100,
        assembly_config=RuntimeAdapterAssemblyConfig(
            stage="mvp3",
            capability_snapshot_ref="capability://synthetic/mvp3/slice7-tts-contract",
            capability_version="mvp3.contract.v1",
        ),
        capabilities=valid_mvp3_real_profiles(),
    )


def _append_approved_spoken_plan_chain(
    journal: object,
    *,
    event_id_prefix: str = "evt_mvp3_slice7_tts",
) -> dict[str, object]:
    snapshot_event_id = str(journal.events()[1]["event_id"])
    created = journal.append(
        event_name="SLOWTASK_CREATED",
        event_id=f"{event_id_prefix}_task_created",
        source_module="slowtask_runtime",
        caused_by_event_id=snapshot_event_id,
        created_monotonic_ms=120,
        created_wall_clock_ms=1700000000120,
        trace_redaction_level="metadata_only",
        task_id="task_mvp3_slice7",
        plan_version=1,
        task_event_seq=1,
        initial_goal_ref="goal://synthetic/mvp3/slice7/tts",
    )
    state_created = journal.append(
        event_name="SLOWTASK_STATE_CHANGED",
        event_id=f"{event_id_prefix}_state_created",
        source_module="slowtask_runtime",
        caused_by_event_id=str(created["event_id"]),
        created_monotonic_ms=121,
        created_wall_clock_ms=1700000000121,
        trace_redaction_level="metadata_only",
        task_id="task_mvp3_slice7",
        plan_version=1,
        task_event_seq=2,
        from_state="CREATED",
        to_state="PLANNING",
        reason="synthetic_planning_started",
    )
    commitment = journal.append(
        event_name="SEMANTIC_COMMITMENT_EMITTED",
        event_id=f"{event_id_prefix}_commitment",
        source_module="slowtask_runtime",
        caused_by_event_id=str(state_created["event_id"]),
        created_monotonic_ms=122,
        created_wall_clock_ms=1700000000122,
        trace_redaction_level="metadata_only",
        commitment_id="commitment_mvp3_slice7",
        task_id="task_mvp3_slice7",
        plan_version=1,
        task_event_seq=3,
        source_events=[str(state_created["event_id"])],
        commitment_ref="commitment://synthetic/mvp3/slice7/tts",
        immutable_fields=["task_id"],
        must_say_fields=["status"],
        forbidden_rewrite_fields=["tool_status"],
    )
    spoken = journal.append(
        event_name="SPOKEN_PLAN_EMITTED",
        event_id=f"{event_id_prefix}_spoken_plan",
        source_module="composer",
        caused_by_event_id=str(commitment["event_id"]),
        created_monotonic_ms=123,
        created_wall_clock_ms=1700000000123,
        trace_redaction_level="metadata_only",
        spoken_plan_id="spoken_plan_mvp3_slice7",
        task_id="task_mvp3_slice7",
        plan_version=1,
        task_event_seq=4,
        source_events=[str(commitment["event_id"])],
        source_progress_event_ids=[],
        source_commitment_id="commitment_mvp3_slice7",
        coverage_check_required=True,
        truthfulness_check_required=False,
        text_ref="text://synthetic/mvp3/slice7/spoken-plan",
        emotion="neutral",
        speaking_style="concise",
        interruptible=True,
        priority="normal",
        source="semantic_commitment",
        output_mode="real",
        immutable_fields=["task_id"],
        must_say_fields=["status"],
        forbidden_rewrite_fields=["tool_status"],
    )
    return journal.append(
        event_name="COMMITMENT_COVERAGE_CHECK_PASSED",
        event_id=f"{event_id_prefix}_coverage_passed",
        source_module="coverage_checker",
        caused_by_event_id=str(spoken["event_id"]),
        created_monotonic_ms=124,
        created_wall_clock_ms=1700000000124,
        trace_redaction_level="metadata_only",
        spoken_plan_id="spoken_plan_mvp3_slice7",
        source_commitment_id="commitment_mvp3_slice7",
        checked_fields=["status"],
        check_result_ref="check-result://synthetic/mvp3/slice7/coverage",
        output_mode="real",
        task_id="task_mvp3_slice7",
        plan_version=1,
        task_event_seq=5,
    )


def _append_playback_started_from_tts(
    journal: object,
    *,
    approved_check: dict[str, object],
    tts_event: dict[str, object],
    event_id: str = "evt_mvp3_slice7_tts_playback_started",
    include_tts_output_event_id: bool = True,
    include_tts_stream_ref: bool = True,
) -> dict[str, object]:
    fields = {
        "event_name": "PLAYBACK_SPAN_STARTED",
        "event_id": event_id,
        "source_module": "talker",
        "caused_by_event_id": str(approved_check["event_id"]),
        "created_monotonic_ms": 211,
        "created_wall_clock_ms": 1700000000211,
        "trace_redaction_level": "metadata_only",
        "playback_span_id": "playback_mvp3_slice7_001",
        "spoken_plan_id": str(approved_check["spoken_plan_id"]),
        "approved_check_event_id": str(approved_check["event_id"]),
        "audio_ref": str(tts_event["audio_ref"]),
    }
    if include_tts_stream_ref and tts_event.get("tts_stream_ref"):
        fields["tts_stream_ref"] = tts_event["tts_stream_ref"]
    if include_tts_output_event_id:
        fields["tts_output_event_id"] = str(tts_event["event_id"])
    return journal.append(
        **fields,
    )


def _github_allowed_replay_manifest() -> dict[str, object]:
    return {
        "manifest_schema_version": "1.0",
        "replay_id": "replay_mvp3_slice7_tts_contract_synthetic",
        "source_trace_ref": "fixture://mvp3/slice7-tts-contract",
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
        raise AssertionError("TTS contract and replay must not call provider runtime")

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
        "raw_tts_output",
        "provider_response",
        "provider_schema",
        "authorization",
        "credential",
        "api_key",
        "token",
    )
    return all(term not in rendered.lower() for term in forbidden_terms)
