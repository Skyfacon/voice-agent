from __future__ import annotations

import json
from pathlib import Path
import wave

from voice_agent.adapters.adapter_timing import AdapterTimingSnapshot
from voice_agent.adapters.asr_fake_transport import FakeAsrProviderResponse, FakeAsrTransport
from voice_agent.adapters.fast_interaction_live_transport import FastInteractionProviderCompletion
from voice_agent.adapters.fast_interaction_live_transport import FastInteractionLiveTransportError
from voice_agent.runtime.mvp5_live_voice_evidence import (
    MVP5LiveVoiceEvidenceConfig,
    run_mvp5_live_voice_evidence,
)


def test_fast_interaction_primary_path_is_audio_native_before_any_asr_dependency(
    tmp_path: Path,
) -> None:
    wav_path = tmp_path / "mvp63-fast.wav"
    wav_bytes = _write_wav_file(wav_path)
    call_order: list[str] = []
    asr_transport = _OrderingAsrTransport(call_order)
    fast_transport = _FakeFastInteractionTransport(call_order=call_order)
    thinker_transport = _ExplodingThinkerTransport()

    result = run_mvp5_live_voice_evidence(
        local_wav=wav_path,
        config=MVP5LiveVoiceEvidenceConfig(
            run_id="mvp63-fast-interaction-evidence",
            live_provider=True,
            allow_local_wav=True,
            approval_packet=_approval_packet(),
            credential_env_var_name="MVP63_TEST_PROVIDER_KEY",
            requested_provider_calls=1,
            max_provider_calls=1,
            timeout_ms=1500,
            fast_interaction_enabled=True,
            audio_native_thinker_enabled=False,
            allow_fast_interaction_asr_text_fallback=False,
            fast_interaction_timeout_ms=1500,
        ),
        env={"MVP63_TEST_PROVIDER_KEY": "DUMMY_TEST_CREDENTIAL_THAT_MUST_NOT_LEAK"},
        asr_transport=asr_transport,
        thinker_transport=thinker_transport,
        fast_interaction_transport=fast_transport,
    )

    events = result.events
    event_names = [event["event_name"] for event in events]
    fast_event = _event(events, "FAST_INTERACTION_OUTPUT_EMITTED")
    candidate_event = _event(events, "FOREGROUND_REPLY_CANDIDATE_EMITTED")

    assert "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED" not in event_names
    assert "ASR_TRANSCRIPT_OUTPUT_EMITTED" not in event_names
    assert fast_event["event_seq"] < candidate_event["event_seq"]
    assert fast_event["caused_by_event_id"] == _event(events, "TURN_INGRESS_COMMITTED")["event_id"]
    assert candidate_event["caused_by_event_id"] == fast_event["event_id"]
    assert fast_event["adapter_id"] == "mvp63_fast_interaction_runtime"
    assert fast_event["input_mode"] == "audio_native"
    assert fast_event["fast_interaction_input_mode"] == "audio_native"
    assert fast_event["output_mode"] == "real"
    assert result.fast_interaction_output_mode == "real"
    assert result.fast_interaction_input_mode == "audio_native"
    assert result.asr_text_fallback_used is False
    assert result.thinker_output_mode is None
    assert result.fast_interaction_event_id == fast_event["event_id"]
    assert result.foreground_candidate_event_id == candidate_event["event_id"]
    assert call_order == ["fast_interaction_before_router"]
    assert fast_transport.call_count == 1
    assert fast_transport.input_mode_seen == "audio_native"
    assert fast_transport.audio_format_seen == "wav"
    assert fast_transport.audio_bytes_seen == wav_bytes
    assert fast_transport.safe_audio_ref_seen
    assert fast_transport.text_ref_seen is None
    assert fast_transport.asr_frame_ref_seen is None
    assert fast_transport.timeout_ms_seen == 1500

    metadata = result.to_metadata()
    rendered = json.dumps(metadata, sort_keys=True)
    latency_debug = metadata["latency_debug"]
    assert metadata["status"] == "evidence_emitted"
    assert metadata["fast_interaction_output_mode"] == "real"
    assert metadata["fast_interaction_input_mode"] == "audio_native"
    assert metadata["asr_text_fallback_used"] is False
    assert metadata.get("thinker_output_mode") is None
    assert latency_debug["fast_interaction_provider_http_ms"] >= 0
    assert latency_debug["fast_interaction_provider_ttft_ms"] == 20
    assert latency_debug["fast_interaction_input_mode"] == "audio_native"
    assert latency_debug["fast_interaction_parse_validate_emit_ms"] >= 0
    assert latency_debug["fast_interaction_total_ms"] >= 0
    assert latency_debug["fast_interaction_timeout_ms"] == 1500
    assert latency_debug["fast_interaction_timed_out"] is False
    assert metadata["raw_provider_body_included"] is False
    assert metadata["raw_transcript_included"] is False
    assert "DUMMY_TEST_CREDENTIAL_THAT_MUST_NOT_LEAK" not in rendered
    assert "A tiny safe spooky story." not in rendered
    assert str(wav_path) not in rendered
    assert wav_path.name not in rendered
    assert wav_bytes.hex() not in rendered


def test_fast_interaction_asr_text_fallback_requires_explicit_flag(
    tmp_path: Path,
) -> None:
    wav_path = tmp_path / "mvp63-fast-fallback.wav"
    _write_wav_file(wav_path)
    fast_transport = _FallbackFastInteractionTransport()

    result = run_mvp5_live_voice_evidence(
        local_wav=wav_path,
        config=MVP5LiveVoiceEvidenceConfig(
            run_id="mvp63-fast-interaction-fallback",
            live_provider=True,
            allow_local_wav=True,
            approval_packet=_approval_packet(asr_text_fallback=True),
            credential_env_var_name="MVP63_TEST_PROVIDER_KEY",
            requested_provider_calls=2,
            max_provider_calls=2,
            timeout_ms=1500,
            fast_interaction_enabled=True,
            audio_native_thinker_enabled=False,
            allow_fast_interaction_asr_text_fallback=True,
            fast_interaction_timeout_ms=1500,
        ),
        env={"MVP63_TEST_PROVIDER_KEY": "DUMMY_TEST_CREDENTIAL_THAT_MUST_NOT_LEAK"},
        asr_transport=FakeAsrTransport(
            (
                FakeAsrProviderResponse.success(
                    asr_frame_ref="asr-frame://synthetic/mvp63/fallback",
                    text_ref="text://synthetic/mvp63/fallback",
                    audio_timestamps_ref=None,
                    streaming_status="unsupported_final_only",
                ),
            )
        ),
        thinker_transport=_ExplodingThinkerTransport(),
        fast_interaction_transport=fast_transport,
    )

    fast_event = _event(result.events, "FAST_INTERACTION_OUTPUT_EMITTED")
    assert fast_event["input_mode"] == "asr_text_fallback"
    assert fast_event["fast_interaction_input_mode"] == "asr_text_fallback"
    assert fast_event["output_mode"] == "fallback"
    assert result.fast_interaction_input_mode == "asr_text_fallback"
    assert result.fast_interaction_output_mode == "fallback"
    assert result.asr_text_fallback_used is True
    metadata = result.to_metadata()
    assert metadata["asr_text_fallback_used"] is True
    assert metadata["latency_debug"]["fast_interaction_input_mode"] == "asr_text_fallback"
    assert fast_transport.text_call_count == 1
    assert fast_transport.audio_call_count == 0


def test_fast_interaction_timeout_fails_closed_without_audio_native_thinker(
    tmp_path: Path,
) -> None:
    wav_path = tmp_path / "mvp63-fast-timeout.wav"
    _write_wav_file(wav_path)
    fast_transport = _FailingFastInteractionTransport(
        FastInteractionLiveTransportError(
            "raw provider body DUMMY_TEST_CREDENTIAL_THAT_MUST_NOT_LEAK",
            category="provider_timeout",
            failure_reasons=("provider_timeout",),
        )
    )

    result = run_mvp5_live_voice_evidence(
        local_wav=wav_path,
        config=MVP5LiveVoiceEvidenceConfig(
            run_id="mvp63-fast-interaction-timeout",
            live_provider=True,
            allow_local_wav=True,
            approval_packet=_approval_packet(),
            credential_env_var_name="MVP63_TEST_PROVIDER_KEY",
            requested_provider_calls=1,
            max_provider_calls=1,
            timeout_ms=1500,
            fast_interaction_enabled=True,
            audio_native_thinker_enabled=False,
            allow_fast_interaction_asr_text_fallback=False,
            fast_interaction_timeout_ms=1500,
        ),
        env={"MVP63_TEST_PROVIDER_KEY": "DUMMY_TEST_CREDENTIAL_THAT_MUST_NOT_LEAK"},
        asr_transport=FakeAsrTransport(
            (
                FakeAsrProviderResponse.success(
                    asr_frame_ref="asr-frame://synthetic/mvp63/timeout",
                    text_ref="text://synthetic/mvp63/timeout",
                    audio_timestamps_ref=None,
                    streaming_status="unsupported_final_only",
                ),
            )
        ),
        thinker_transport=_ExplodingThinkerTransport(),
        fast_interaction_transport=fast_transport,
    )

    event_names = [event["event_name"] for event in result.events]
    request_failed = _event(result.events, "ADAPTER_REQUEST_FAILED")
    assert "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED" not in event_names
    assert "FAST_INTERACTION_OUTPUT_EMITTED" not in event_names
    assert request_failed["adapter_type"] == "fast_interaction"
    assert request_failed["failure_reason"] == "provider_timeout"
    assert result.fast_interaction_output_mode is None
    assert result.thinker_output_mode is None
    assert result.failure_reasons == ("provider_timeout",)
    metadata = result.to_metadata()
    rendered = json.dumps(metadata, sort_keys=True)
    assert metadata["status"] == "evidence_failed"
    assert metadata["latency_debug"]["fast_interaction_timed_out"] is True
    assert "DUMMY_TEST_CREDENTIAL_THAT_MUST_NOT_LEAK" not in rendered
    assert "raw provider body" not in rendered


class _FakeFastInteractionTransport:
    def __init__(self, *, call_order: list[str] | None = None) -> None:
        self.call_count = 0
        self.call_order = call_order
        self.input_mode_seen: str | None = None
        self.safe_audio_ref_seen: str | None = None
        self.text_ref_seen: str | None = None
        self.asr_frame_ref_seen: str | None = None
        self.audio_bytes_seen: bytes | None = None
        self.audio_format_seen: str | None = None
        self.timeout_ms_seen: int | None = None

    def complete_audio_with_timing(
        self,
        *,
        request_payload: dict[str, object],
        audio_bytes: bytes,
        audio_format: str,
        credential_handle: object,
        credential_value: str,
        adapter_request_id: str,
        timeout_ms: int,
        model_alias: str,
        turn_ingress_monotonic_ms: int,
    ) -> FastInteractionProviderCompletion:
        self.call_count += 1
        if self.call_order is not None:
            self.call_order.append("fast_interaction_before_router")
        self.input_mode_seen = str(request_payload["input_mode"])
        self.safe_audio_ref_seen = str(request_payload["audio_payload_ref"])
        self.text_ref_seen = (
            str(request_payload["text_ref"]) if "text_ref" in request_payload else None
        )
        self.asr_frame_ref_seen = (
            str(request_payload["asr_frame_ref"]) if "asr_frame_ref" in request_payload else None
        )
        self.audio_bytes_seen = audio_bytes
        self.audio_format_seen = audio_format
        self.timeout_ms_seen = timeout_ms
        assert turn_ingress_monotonic_ms == 190
        assert credential_value.startswith("DUMMY_TEST_CREDENTIAL")
        assert adapter_request_id.startswith("adapter-request-mvp63-fast-interaction-")
        assert model_alias == "qwen3.5-fast-interaction"
        assert "secret_materialized=False" in repr(credential_handle)
        return FastInteractionProviderCompletion(
            provider_text=_fast_provider_json(output_mode="real"),
            timing=_fast_timing_snapshot(),
        )


class _FailingFastInteractionTransport:
    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    def complete_audio_with_timing(self, **_kwargs: object) -> FastInteractionProviderCompletion:
        raise self._exc


class _FallbackFastInteractionTransport:
    def __init__(self) -> None:
        self.text_call_count = 0
        self.audio_call_count = 0

    def complete_with_timing(
        self,
        *,
        request_payload: dict[str, object],
        credential_handle: object,
        credential_value: str,
        adapter_request_id: str,
        timeout_ms: int,
        model_alias: str,
        turn_ingress_monotonic_ms: int,
    ) -> FastInteractionProviderCompletion:
        self.text_call_count += 1
        assert request_payload["input_mode"] == "asr_text_fallback"
        assert request_payload["text_ref"] == "text://synthetic/mvp63/fallback"
        assert credential_value.startswith("DUMMY_TEST_CREDENTIAL")
        assert timeout_ms == 1500
        assert model_alias == "qwen3.5-fast-interaction"
        assert turn_ingress_monotonic_ms == 190
        assert "secret_materialized=False" in repr(credential_handle)
        return FastInteractionProviderCompletion(
            provider_text=_fast_provider_json(output_mode="fallback"),
            timing=_fast_timing_snapshot(),
        )

    def complete_audio_with_timing(self, **_kwargs: object) -> FastInteractionProviderCompletion:
        self.audio_call_count += 1
        raise AssertionError("fallback test must use text timing transport")


class _OrderingAsrTransport:
    def __init__(self, call_order: list[str]) -> None:
        self.call_order = call_order

    def transcribe(self, binding: object) -> object:
        if "fast_interaction_before_router" not in self.call_order:
            raise AssertionError("ASR must not run before audio-native Fast Interaction")
        self.call_order.append("asr_debug_after_fast_interaction")
        return FakeAsrTransport(
            (
                FakeAsrProviderResponse.success(
                    asr_frame_ref="asr-frame://synthetic/mvp63/debug",
                    text_ref="text://synthetic/mvp63/debug",
                    audio_timestamps_ref="audio-timestamps://synthetic/mvp63/debug",
                    streaming_status="supported",
                    confidence_score=0.93,
                ),
            )
        ).transcribe(binding)


class _ExplodingThinkerTransport:
    def complete_audio(self, **_kwargs: object) -> str:
        raise AssertionError("audio-native thinker must not run in MVP6.3 fast path test")


def _fast_provider_json(*, output_mode: str) -> str:
    return json.dumps(
        {
            "schema_name": "voice_agent.fast_interaction.output.v1",
            "route_hint": {"router_decision_candidate": "FAST_ONLY"},
            "route_prelude": {"summary": "foreground story request"},
            "foreground_act": "ANSWER",
            "reply_candidate": "A tiny safe spooky story.",
            "final_fast_evidence": {"label": "story"},
            "risk_tags": ["low_risk", "no_side_effects"],
            "risk_class": "LOW",
            "confidence": 0.91,
            "output_mode": output_mode,
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
    )


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


def _approval_packet(*, asr_text_fallback: bool = False) -> dict[str, object]:
    provider_adapter_ids = ["mvp63_fast_interaction_runtime"]
    max_provider_calls = 1
    if asr_text_fallback:
        provider_adapter_ids = ["mvp5_asr_adapter", "mvp63_fast_interaction_runtime"]
        max_provider_calls = 2
    return {
        "approval_id": "mvp63-live-fast-interaction-test",
        "live_provider_opt_in": True,
        "local_wav_opt_in": True,
        "metadata_only_output": True,
        "replay_reruns_provider": False,
        "provider_adapter_ids": provider_adapter_ids,
        "credential_env_var_name": "MVP63_TEST_PROVIDER_KEY",
        "max_provider_calls": max_provider_calls,
        "timeout_ms": 1500,
        "safe_output_ref": "summary://mvp63/live-fast-interaction-test",
    }


def _event(events: tuple[dict[str, object], ...], event_name: str) -> dict[str, object]:
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
