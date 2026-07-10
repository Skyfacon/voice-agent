from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import wave

import pytest

from voice_agent.adapters.adapter_timing import AdapterTimingSnapshot
from voice_agent.adapters.asr_fake_transport import FakeAsrProviderResponse, FakeAsrTransport
from voice_agent.adapters.fast_interaction_live_transport import FastInteractionProviderCompletion
from voice_agent.adapters.lalm_thinker_runtime_adapter import LALM_THINKER_RUNTIME_MODEL_ALIAS
from voice_agent.replay.runner import ReplayValidationError, run_replay_fixture
from voice_agent.runtime.mvp5_live_router_runner import (
    MVP5LiveRouterConfig,
    run_mvp5_live_router_runner,
)
from voice_agent.runtime.mvp5_live_voice_evidence import (
    MVP5LiveVoiceEvidenceConfig,
    run_mvp5_live_voice_evidence,
)


def test_mvp5_live_route_events_replay_from_recorded_metadata_without_provider_rerun(
    tmp_path: Path,
) -> None:
    evidence = _live_evidence_result(
        tmp_path,
        route_slug="replay-spawn",
        task_focus_hint="NEW_TASK_CANDIDATE",
        task_like=True,
        complexity_hint="complex",
    )
    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="mvp5-goal3-replay-spawn",
            expected_route="SPAWN_SLOW_TASK",
        ),
    )

    fixture = _fixture_from_events(result.events)
    replay_result = run_replay_fixture(fixture)

    router_event = _event(result.events, "ROUTER_DECISION_EMITTED")
    created = _event(result.events, "SLOWTASK_CREATED")
    thinker_event = _event(result.events, "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED")
    assert replay_result.result_status == "passed"
    assert replay_result.replay_mode == "deterministic"
    assert replay_result.fixture_domain == "GITHUB_ALLOWED"
    assert replay_result.task_focus_state.router_decision_event_id == router_event["event_id"]
    assert router_event["task_focus"] == "NEW_TASK_CANDIDATE"
    assert thinker_event["task_focus_hint"] == "NEW_TASK_CANDIDATE"
    assert created["task_id"] in replay_result.slowtask_state.tasks
    assert replay_result.trace_privacy_state.contains_raw_audio is False
    assert replay_result.trace_privacy_state.contains_secrets is False
    assert result.to_metadata()["provider_call_used"] is False
    assert result.to_metadata()["replay_reruns_provider"] is False


def test_mvp63_fast_foreground_replay_uses_recorded_events_without_provider_rerun(
    tmp_path: Path,
) -> None:
    evidence = _live_fast_evidence_result(tmp_path, route_slug="mvp63-fast-replay")
    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="mvp63-fast-replay",
            expected_route="FAST_ONLY",
        ),
    )

    fixture = _fixture_from_events(result.events)
    replay_result = run_replay_fixture(fixture)
    event_names = [event["event_name"] for event in result.events]

    assert replay_result.result_status == "passed"
    assert replay_result.replay_mode == "deterministic"
    assert "FAST_INTERACTION_OUTPUT_EMITTED" in event_names
    assert "FOREGROUND_REPLY_CANDIDATE_EMITTED" in event_names
    assert "FOREGROUND_ACT_GATE_PASSED" in event_names
    assert "FOREGROUND_OUTPUT_COMMITTED" in event_names
    assert result.to_metadata()["provider_call_used"] is False
    assert result.to_metadata()["replay_reruns_provider"] is False


def test_mvp63_fast_foreground_replay_rejects_mismatched_candidate_provenance(
    tmp_path: Path,
) -> None:
    evidence = _live_fast_evidence_result(tmp_path, route_slug="mvp63-fast-bad-candidate")
    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="mvp63-fast-bad-candidate",
            expected_route="FAST_ONLY",
        ),
    )
    fixture = _fixture_from_events(result.events)
    candidate = _event(fixture["events"], "FOREGROUND_REPLY_CANDIDATE_EMITTED")
    candidate["fast_interaction_output_event_id"] = "evt_mvp63_wrong_fast_output"

    with pytest.raises(ReplayValidationError, match="fast_interaction_output_event_id"):
        run_replay_fixture(fixture)


def test_mvp63_fast_foreground_replay_rejects_raw_fast_payload_fields(
    tmp_path: Path,
) -> None:
    evidence = _live_fast_evidence_result(tmp_path, route_slug="mvp63-fast-raw-payload")
    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="mvp63-fast-raw-payload",
            expected_route="FAST_ONLY",
        ),
    )
    fixture = _fixture_from_events(result.events)
    fast_event = _event(fixture["events"], "FAST_INTERACTION_OUTPUT_EMITTED")
    fast_event["provider_body"] = {"raw": "must not replay"}

    with pytest.raises(ReplayValidationError, match="raw Fast Interaction payload"):
        run_replay_fixture(fixture)


def test_mvp63_fast_foreground_replay_rejects_raw_candidate_payload_fields(
    tmp_path: Path,
) -> None:
    evidence = _live_fast_evidence_result(tmp_path, route_slug="mvp63-candidate-raw-payload")
    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="mvp63-candidate-raw-payload",
            expected_route="FAST_ONLY",
        ),
    )
    fixture = _fixture_from_events(result.events)
    candidate = _event(fixture["events"], "FOREGROUND_REPLY_CANDIDATE_EMITTED")
    candidate["reply_candidate"] = "raw candidate text must not replay"

    with pytest.raises(ReplayValidationError, match="raw Fast Interaction payload"):
        run_replay_fixture(fixture)


def test_mvp63_fast_foreground_replay_rejects_commit_without_gate_chain(
    tmp_path: Path,
) -> None:
    evidence = _live_fast_evidence_result(tmp_path, route_slug="mvp63-fast-bad-commit")
    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="mvp63-fast-bad-commit",
            expected_route="FAST_ONLY",
        ),
    )
    fixture = _fixture_from_events(result.events)
    committed = _event(fixture["events"], "FOREGROUND_OUTPUT_COMMITTED")
    committed["gate_event_id"] = "evt_mvp63_wrong_gate"

    with pytest.raises(ReplayValidationError, match="gate_event_id"):
        run_replay_fixture(fixture)


def test_mvp63_fast_foreground_replay_rejects_committed_output_ref_mismatch(
    tmp_path: Path,
) -> None:
    evidence = _live_fast_evidence_result(tmp_path, route_slug="mvp63-fast-bad-output-ref")
    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="mvp63-fast-bad-output-ref",
            expected_route="FAST_ONLY",
        ),
    )
    fixture = _fixture_from_events(result.events)
    committed = _event(fixture["events"], "FOREGROUND_OUTPUT_COMMITTED")
    committed["output_ref"] = "foreground-candidate://synthetic/mvp63/wrong-candidate"

    with pytest.raises(ReplayValidationError, match="output_ref"):
        run_replay_fixture(fixture)


def test_mvp63_fast_foreground_replay_rejects_ambiguous_gate_pass(
    tmp_path: Path,
) -> None:
    evidence = _live_fast_evidence_result(tmp_path, route_slug="mvp63-fast-ambiguous-pass")
    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="mvp63-fast-ambiguous-pass",
            expected_route="FAST_ONLY",
        ),
    )
    fixture = _fixture_from_events(result.events)
    router = _event(fixture["events"], "ROUTER_DECISION_EMITTED")
    router["task_focus"] = "AMBIGUOUS"

    with pytest.raises(ReplayValidationError, match="AMBIGUOUS"):
        run_replay_fixture(fixture)


def test_mvp63_audio_native_fast_interaction_replays_without_asr_or_provider_rerun() -> None:
    turn_event_id = "evt_mvp63_audio_native_turn_committed"
    fast_interaction_event_id = "evt_mvp63_audio_native_fast_interaction_output"
    fixture = _fixture_from_events(
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
                "turn_phase": "COLLECTING_INPUT",
                "input_modality": "audio",
                "audio_span_id": "audio_span_mvp63_audio_native_fast_replay",
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
                "event_id": fast_interaction_event_id,
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
                "source_event_ids": (turn_event_id,),
                "risk_tags": ("low_risk", "no_side_effects"),
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
                "caused_by_event_id": fast_interaction_event_id,
                "created_monotonic_ms": 40,
                "created_wall_clock_ms": 1700000000040,
                "trace_redaction_level": "metadata_only",
                "turn_id": "turn_mvp63_audio_native_fast_replay",
                "utterance_id": "utt_mvp63_audio_native_fast_replay",
                "router_decision": "FAST_ONLY",
                "task_focus": "FOREGROUND_CHAT",
                "confidence": 0.9,
                "turn_committed_event_id": turn_event_id,
                "fast_interaction_output_event_id": fast_interaction_event_id,
            },
        )
    )

    replay_result = run_replay_fixture(fixture)

    assert replay_result.result_status == "passed"
    assert replay_result.manifest.allowed_re_eval_components == ()
    assert replay_result.task_focus_state.router_decision_event_id == (
        "evt_mvp63_audio_native_router_decision"
    )
    assert all(event["event_name"] != "ASR_TRANSCRIPT_OUTPUT_EMITTED" for event in replay_result.ordered_events)

    missing_mode_fixture = deepcopy(fixture)
    missing_mode_event = _event(missing_mode_fixture["events"], "FAST_INTERACTION_OUTPUT_EMITTED")
    missing_mode_event.pop("input_mode")
    missing_mode_event.pop("fast_interaction_input_mode")
    with pytest.raises(ReplayValidationError, match="input_mode"):
        run_replay_fixture(missing_mode_fixture)

    unknown_mode_fixture = deepcopy(fixture)
    unknown_mode_event = _event(unknown_mode_fixture["events"], "FAST_INTERACTION_OUTPUT_EMITTED")
    unknown_mode_event["input_mode"] = "provider_body"
    unknown_mode_event["fast_interaction_input_mode"] = "provider_body"
    with pytest.raises(ReplayValidationError, match="unsupported input_mode"):
        run_replay_fixture(unknown_mode_fixture)


def test_replay_rejects_router_asr_ref_that_does_not_match_same_turn_evidence(
    tmp_path: Path,
) -> None:
    evidence = _live_evidence_result(
        tmp_path,
        route_slug="replay-bad-router-ref",
        task_focus_hint="NEW_TASK_CANDIDATE",
        task_like=True,
        complexity_hint="complex",
    )
    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="mvp5-goal3-replay-bad-router-ref",
            expected_route="SPAWN_SLOW_TASK",
        ),
    )
    fixture = _fixture_from_events(result.events)
    router = _event(fixture["events"], "ROUTER_DECISION_EMITTED")
    router["asr_frame_event_id"] = "evt_mvp5_goal3_wrong_asr_event"

    with pytest.raises(ReplayValidationError, match="asr_frame_event_id"):
        run_replay_fixture(fixture)


def _fixture_from_events(events: tuple[dict[str, object], ...]) -> dict[str, object]:
    rendered = json.dumps(events, sort_keys=True)
    for unsafe in (
        "DUMMY_TEST_CREDENTIAL",
        "file://",
        "data:",
        "audio/raw/",
        "diagnostics/",
        "traces/",
        "replays/local/",
        "provider body",
        "provider request",
        "provider response",
        "prompt dump",
    ):
        assert unsafe not in rendered

    return {
        "replay_manifest": {
            "manifest_schema_version": "1.0",
            "replay_id": "mvp5_goal3_live_route_replay",
            "source_trace_ref": "fixture://mvp5/goal3/live-route-replay",
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
        "events": [dict(event) for event in events],
    }


def _live_evidence_result(
    tmp_path: Path,
    *,
    route_slug: str,
    task_focus_hint: str,
    task_like: bool,
    complexity_hint: str,
):
    wav_path = tmp_path / f"{route_slug}.wav"
    _write_wav_file(wav_path)
    asr_transport = FakeAsrTransport(
        (
            FakeAsrProviderResponse.success(
                asr_frame_ref=f"asr-frame://synthetic/mvp5/goal3/{route_slug}",
                text_ref=f"text://synthetic/mvp5/goal3/{route_slug}",
                audio_timestamps_ref=f"audio-timestamps://synthetic/mvp5/goal3/{route_slug}",
                streaming_status="supported",
                confidence_score=0.91,
            ),
        )
    )
    thinker_transport = _FakeThinkerAudioTransport(
        task_focus_hint=task_focus_hint,
        task_like=task_like,
        complexity_hint=complexity_hint,
    )

    return run_mvp5_live_voice_evidence(
        local_wav=wav_path,
        config=MVP5LiveVoiceEvidenceConfig(
            run_id=f"mvp5-goal3-{route_slug}",
            live_provider=True,
            allow_local_wav=True,
            approval_packet=_approval_packet(),
            credential_env_var_name="MVP5_TEST_PROVIDER_KEY",
            requested_provider_calls=2,
            max_provider_calls=2,
        ),
        env={"MVP5_TEST_PROVIDER_KEY": "DUMMY_TEST_CREDENTIAL_THAT_MUST_NOT_LEAK"},
        asr_transport=asr_transport,
        thinker_transport=thinker_transport,
    )


def _live_fast_evidence_result(
    tmp_path: Path,
    *,
    route_slug: str,
):
    wav_path = tmp_path / f"{route_slug}.wav"
    _write_wav_file(wav_path)
    return run_mvp5_live_voice_evidence(
        local_wav=wav_path,
        config=MVP5LiveVoiceEvidenceConfig(
            run_id=f"mvp63-replay-{route_slug}",
            live_provider=True,
            allow_local_wav=True,
            approval_packet=_fast_approval_packet(),
            credential_env_var_name="MVP63_TEST_PROVIDER_KEY",
            requested_provider_calls=1,
            max_provider_calls=1,
            timeout_ms=1500,
            fast_interaction_enabled=True,
            audio_native_thinker_enabled=False,
            fast_interaction_timeout_ms=1500,
        ),
        env={"MVP63_TEST_PROVIDER_KEY": "DUMMY_TEST_CREDENTIAL_THAT_MUST_NOT_LEAK"},
        asr_transport=_ExplodingAsrTransport(),
        thinker_transport=_ExplodingThinkerTransport(),
        fast_interaction_transport=_FakeFastInteractionTransport(),
    )


class _FakeThinkerAudioTransport:
    def __init__(
        self,
        *,
        task_focus_hint: str,
        task_like: bool,
        complexity_hint: str,
    ) -> None:
        self.task_focus_hint = task_focus_hint
        self.task_like = task_like
        self.complexity_hint = complexity_hint

    def complete_audio(
        self,
        *,
        request_payload: object,
        audio_bytes: bytes,
        audio_format: str,
        credential_handle: object,
        credential_value: str,
        adapter_request_id: str,
        timeout_ms: int,
        model_alias: str,
    ) -> str:
        assert isinstance(request_payload, dict)
        assert audio_bytes
        assert audio_format == "wav"
        assert credential_value.startswith("DUMMY_TEST_CREDENTIAL")
        assert adapter_request_id.startswith("adapter-request-mvp5-thinker-")
        assert timeout_ms == 30_000
        assert model_alias == LALM_THINKER_RUNTIME_MODEL_ALIAS
        skeleton = dict(request_payload["required_output_skeleton"])
        skeleton["output_mode"] = "real"
        skeleton["optional_evidence_refs"] = {
            "semantic_close": {"status": "available", "label": "closed"},
            "assistant_directedness": {"status": "available", "label": "directed"},
            "emotion": {"status": "available", "label": "neutral"},
            "audio_caption": {"status": "available", "label": "speech_available"},
        }
        skeleton["task_focus_hint"] = {
            "focus": self.task_focus_hint,
            "task_like": self.task_like,
            "complexity_hint": self.complexity_hint,
            "focus_confidence": 0.86,
            "evidence_uncertainty": "low",
        }
        return json.dumps(skeleton, separators=(",", ":"), sort_keys=True)


class _FakeFastInteractionTransport:
    def complete_audio_with_timing(self, **kwargs: object) -> FastInteractionProviderCompletion:
        assert str(kwargs["credential_value"]).startswith("DUMMY_TEST_CREDENTIAL")
        assert kwargs["timeout_ms"] == 1500
        return FastInteractionProviderCompletion(
            provider_text=json.dumps(
                {
                    "schema_name": "voice_agent.fast_interaction.output.v1",
                    "route_hint": {"router_decision_candidate": "FAST_ONLY"},
                    "route_prelude": {"summary": "foreground replay story"},
                    "foreground_act": "ANSWER",
                    "reply_candidate": "A tiny safe spooky story.",
                    "final_fast_evidence": {"label": "foreground_replay"},
                    "risk_tags": ["low_risk", "no_side_effects"],
                    "risk_class": "LOW",
                    "confidence": 0.91,
                    "output_mode": "real",
                    "boundary_assertions": {
                        "candidate_is_not_semantic_commitment": True,
                        "may_authorize_tools": False,
                        "may_execute_tools": False,
                        "may_accept_confirmation": False,
                        "may_mutate_slowtask_facts": False,
                        "runtime_gate_owns_display": True,
                    },
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
            timing=_fast_timing_snapshot(),
        )


class _ExplodingThinkerTransport:
    def complete_audio(self, **_kwargs: object) -> str:
        raise AssertionError("audio-native thinker must not run in MVP6.3 replay fast path")


class _ExplodingAsrTransport:
    def transcribe(self, **_kwargs: object) -> object:
        raise AssertionError("ASR must not run in MVP6.3 audio-native fast primary path")


def _approval_packet() -> dict[str, object]:
    return {
        "approval_id": "mvp5-live-route-replay-goal3-test",
        "live_provider_opt_in": True,
        "local_wav_opt_in": True,
        "metadata_only_output": True,
        "replay_reruns_provider": False,
        "provider_adapter_ids": ["mvp5_asr_adapter", "mvp5_thinker_adapter"],
        "credential_env_var_name": "MVP5_TEST_PROVIDER_KEY",
        "max_provider_calls": 2,
        "timeout_ms": 30_000,
        "safe_output_ref": "summary://mvp5/goal3/live-route-replay-test",
    }


def _fast_approval_packet() -> dict[str, object]:
    return {
        "approval_id": "mvp63-fast-route-replay-test",
        "live_provider_opt_in": True,
        "local_wav_opt_in": True,
        "metadata_only_output": True,
        "replay_reruns_provider": False,
        "provider_adapter_ids": ["mvp63_fast_interaction_runtime"],
        "credential_env_var_name": "MVP63_TEST_PROVIDER_KEY",
        "max_provider_calls": 1,
        "timeout_ms": 1500,
        "safe_output_ref": "summary://mvp63/fast-route-replay-test",
    }


def _fast_timing_snapshot() -> AdapterTimingSnapshot:
    return AdapterTimingSnapshot(
        adapter_start_offset_ms=0,
        provider_request_start_offset_ms=5,
        provider_first_chunk_offset_ms=25,
        provider_full_response_offset_ms=65,
        adapter_event_emit_offset_ms=70,
        provider_ttft_ms=20,
        provider_full_response_ms=60,
        provider_generation_ms=40,
        stream_decode_ms=0,
        parse_validate_emit_ms=0,
        total_ms=70,
        timing_mode="streaming",
        ttft_available=True,
        ttft_source="provider_stream_chunk",
    )


def _event(events: tuple[dict[str, object], ...] | list[dict[str, object]], event_name: str) -> dict[str, object]:
    matches = [event for event in events if event["event_name"] == event_name]
    assert len(matches) == 1
    return matches[0]


def _write_wav_file(
    path: Path,
    *,
    sample_rate_hz: int = 16000,
    channel_count: int = 1,
    frame_count: int = 160,
) -> bytes:
    sample_width_bytes = 2
    silent_frame = b"\x00" * sample_width_bytes * channel_count
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(channel_count)
        wav_file.setsampwidth(sample_width_bytes)
        wav_file.setframerate(sample_rate_hz)
        wav_file.writeframes(silent_frame * frame_count)
    return path.read_bytes()
