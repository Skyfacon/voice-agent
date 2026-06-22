from __future__ import annotations

import base64
import json
from pathlib import Path
import time
import wave

from voice_agent.adapters.asr_live_transport import AsrLiveProviderCallMetadata
from voice_agent.adapters.asr_fake_transport import FakeAsrProviderResponse, FakeAsrTransport
from voice_agent.adapters.lalm_thinker_live_transport import LALMThinkerLiveTransportError
from voice_agent.adapters.lalm_thinker_runtime_adapter import LALM_THINKER_RUNTIME_MODEL_ALIAS
from voice_agent.runtime.mvp5_live_voice_evidence import (
    MVP5LiveVoiceEvidenceConfig,
    run_mvp5_live_voice_evidence,
)


def test_provider_free_default_does_not_read_local_wav_env_or_transports(tmp_path: Path) -> None:
    missing_wav = tmp_path / "must-not-be-read.wav"
    asr_transport = _ExplodingAsrTransport()
    thinker_transport = _ExplodingThinkerTransport()

    result = run_mvp5_live_voice_evidence(
        local_wav=missing_wav,
        config=MVP5LiveVoiceEvidenceConfig(),
        asr_transport=asr_transport,
        thinker_transport=thinker_transport,
    )

    metadata = result.to_metadata()
    rendered = json.dumps(metadata, sort_keys=True)
    assert metadata["status"] == "provider_free_skipped"
    assert metadata["event_names"] == []
    assert metadata["provider_call_used"] is False
    assert metadata["fake_transport_used"] is False
    assert metadata["local_wav_opt_in_used"] is False
    assert metadata["live_provider_approval_used"] is False
    assert metadata["raw_audio_included"] is False
    assert metadata["raw_transcript_included"] is False
    assert metadata["raw_provider_body_included"] is False
    assert metadata["prompt_dump_included"] is False
    assert metadata["secret_included"] is False
    assert metadata["local_wav_path_included"] is False
    assert str(missing_wav) not in rendered
    assert missing_wav.name not in rendered
    assert asr_transport.call_count == 0
    assert thinker_transport.call_count == 0


def test_fake_transports_emit_asr_and_thinker_evidence_for_same_committed_audio_turn(
    tmp_path: Path,
) -> None:
    wav_path = tmp_path / "goal2-success.wav"
    wav_bytes = _write_wav_file(wav_path)
    asr_transport = FakeAsrTransport(
        (
            FakeAsrProviderResponse.success(
                asr_frame_ref="asr-frame://synthetic/mvp5/goal2/success",
                text_ref="text://synthetic/mvp5/goal2/success",
                audio_timestamps_ref="audio-timestamps://synthetic/mvp5/goal2/success",
                streaming_status="supported",
                confidence_score=0.93,
            ),
        )
    )
    thinker_transport = _FakeThinkerAudioTransport(optional_available=True)

    result = run_mvp5_live_voice_evidence(
        local_wav=wav_path,
        config=MVP5LiveVoiceEvidenceConfig(
            run_id="mvp5-goal2-success",
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

    events = result.events
    committed = _event(events, "TURN_INGRESS_COMMITTED")
    asr_event = _event(events, "ASR_TRANSCRIPT_OUTPUT_EMITTED")
    thinker_event = _event(events, "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED")

    assert committed["event_seq"] < asr_event["event_seq"]
    assert committed["event_seq"] < thinker_event["event_seq"]
    for field in ("turn_id", "utterance_id", "audio_span_id", "input_modality"):
        assert asr_event[field] == committed[field]
        assert thinker_event[field] == committed[field]
    assert asr_event["output_mode"] == "real"
    assert thinker_event["output_mode"] == "real"
    assert asr_event["asr_frame_ref"].startswith("asr-frame://synthetic/mvp5/")
    assert asr_event["text_ref"].startswith("text://synthetic/mvp5/")
    assert thinker_event["semantic_frame_ref"].startswith(
        "semantic-frame://synthetic/lalm-thinker/adapter-owned/"
    )
    assert thinker_event["semantic_summary_ref"].startswith(
        "summary://synthetic/lalm-thinker/adapter-owned/"
    )
    assert thinker_event["task_focus_hint"] == "FOREGROUND_CHAT"
    assert thinker_event["task_like"] is False
    assert thinker_event["complexity_hint"] == "simple"
    assert thinker_event["focus_confidence"] == 0.86
    assert thinker_event["evidence_uncertainty"] == "low"

    metadata = result.to_metadata()
    rendered = json.dumps(metadata, sort_keys=True)
    assert metadata["status"] == "evidence_emitted"
    assert metadata["turn_id"] == committed["turn_id"]
    assert metadata["utterance_id"] == committed["utterance_id"]
    assert metadata["audio_span_id"] == committed["audio_span_id"]
    assert metadata["input_modality"] == "audio"
    assert metadata["asr_event_id"] == asr_event["event_id"]
    assert metadata["thinker_event_id"] == thinker_event["event_id"]
    assert metadata["asr_output_mode"] == "real"
    assert metadata["thinker_output_mode"] == "real"
    assert metadata["provider_call_used"] is False
    assert metadata["fake_transport_used"] is True
    assert metadata["local_wav_opt_in_used"] is True
    assert metadata["live_provider_approval_used"] is True
    assert metadata["raw_audio_included"] is False
    assert metadata["raw_transcript_included"] is False
    assert metadata["raw_provider_body_included"] is False
    assert metadata["prompt_dump_included"] is False
    assert metadata["secret_included"] is False
    assert metadata["local_wav_path_included"] is False
    assert str(wav_path) not in rendered
    assert wav_path.name not in rendered
    assert "DUMMY_TEST_CREDENTIAL_THAT_MUST_NOT_LEAK" not in rendered
    assert base64.b64encode(wav_bytes).decode("ascii") not in rendered
    assert thinker_transport.call_count == 1
    assert thinker_transport.audio_bytes_seen == wav_bytes


def test_slow_injected_live_transports_start_asr_and_thinker_in_parallel(
    tmp_path: Path,
) -> None:
    wav_path = tmp_path / "goal2-parallel.wav"
    wav_bytes = _write_wav_file(wav_path)
    asr_transport = _SlowAsrLiveTransport(delay_seconds=0.3)
    thinker_transport = _SlowThinkerAudioTransport(delay_seconds=0.3)

    started = time.monotonic()
    result = run_mvp5_live_voice_evidence(
        local_wav=wav_path,
        config=MVP5LiveVoiceEvidenceConfig(
            run_id="mvp5-goal2-parallel",
            live_provider=True,
            allow_local_wav=True,
            approval_packet=_approval_packet(),
            credential_env_var_name="MVP5_TEST_PROVIDER_KEY",
            requested_provider_calls=2,
            max_provider_calls=2,
        ),
        env={"MVP5_TEST_PROVIDER_KEY": "DUMMY_TEST_CREDENTIAL"},
        asr_transport=asr_transport,
        thinker_transport=thinker_transport,
    )
    elapsed_ms = int((time.monotonic() - started) * 1000)

    metadata = result.to_metadata()
    latency_debug = metadata["latency_debug"]
    events = result.events
    asr_event = _event(events, "ASR_TRANSCRIPT_OUTPUT_EMITTED")
    thinker_event = _event(events, "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED")

    assert metadata["status"] == "degraded_evidence_emitted"
    assert metadata["thinker_transient_asr_text_used"] is False
    assert latency_debug["provider_calls_parallel"] is True
    assert latency_debug["asr_started_before_thinker_finished"] is True
    assert latency_debug["thinker_started_before_asr_finished"] is True
    assert latency_debug["asr_provider_http_ms"] >= 250
    assert latency_debug["thinker_provider_http_ms"] >= 250
    assert elapsed_ms < 550
    assert asr_event["event_seq"] < thinker_event["event_seq"]
    assert asr_transport.audio_bytes_seen == wav_bytes
    assert thinker_transport.audio_bytes_seen == wav_bytes
    assert thinker_transport.transient_input_text_seen is False


def test_missing_optional_model_fields_are_degraded_and_explicitly_unavailable(
    tmp_path: Path,
) -> None:
    wav_path = tmp_path / "goal2-degraded.wav"
    _write_wav_file(wav_path)
    asr_transport = FakeAsrTransport(
        (
            FakeAsrProviderResponse.success(
                asr_frame_ref="asr-frame://synthetic/mvp5/goal2/degraded",
                text_ref="text://synthetic/mvp5/goal2/degraded",
                audio_timestamps_ref=None,
                streaming_status="unsupported_final_only",
            ),
        )
    )
    thinker_transport = _FakeThinkerAudioTransport(optional_available=False)

    result = run_mvp5_live_voice_evidence(
        local_wav=wav_path,
        config=MVP5LiveVoiceEvidenceConfig(
            run_id="mvp5-goal2-degraded",
            live_provider=True,
            allow_local_wav=True,
            approval_packet=_approval_packet(),
            credential_env_var_name="MVP5_TEST_PROVIDER_KEY",
            requested_provider_calls=2,
            max_provider_calls=2,
        ),
        env={"MVP5_TEST_PROVIDER_KEY": "DUMMY_TEST_CREDENTIAL"},
        asr_transport=asr_transport,
        thinker_transport=thinker_transport,
    )

    asr_event = _event(result.events, "ASR_TRANSCRIPT_OUTPUT_EMITTED")
    thinker_event = _event(result.events, "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED")
    degraded_events = [
        event for event in result.events if event["event_name"] == "ADAPTER_OUTPUT_DEGRADED"
    ]

    assert asr_event["output_mode"] == "degraded"
    assert asr_event["timestamp_status"] == "unavailable"
    assert asr_event["streaming_status"] == "unsupported_final_only"
    assert thinker_event["output_mode"] == "degraded"
    for status_field in (
        "semantic_close_status",
        "assistant_directedness_status",
        "emotion_status",
        "audio_caption_status",
    ):
        assert thinker_event[status_field] == "unavailable"
    for ref_field in (
        "semantic_close_ref",
        "assistant_directedness_ref",
        "emotion_ref",
        "audio_caption_ref",
    ):
        assert ref_field not in thinker_event
    assert {
        event["missing_capability"] for event in degraded_events
    } >= {
        "supports_audio_timestamps",
        "supports_streaming_output",
        "supports_semantic_close",
        "supports_assistant_directedness",
        "supports_emotion",
        "supports_audio_caption",
    }

    metadata = result.to_metadata()
    assert metadata["status"] == "degraded_evidence_emitted"
    assert metadata["asr_output_mode"] == "degraded"
    assert metadata["thinker_output_mode"] == "degraded"
    assert metadata["provider_call_used"] is False


def test_fake_transport_failures_emit_safe_adapter_failures_without_provider_payload(
    tmp_path: Path,
) -> None:
    wav_path = tmp_path / "goal2-failure.wav"
    wav_bytes = _write_wav_file(wav_path)
    asr_transport = FakeAsrTransport(
        (FakeAsrProviderResponse.request_failure("provider_unavailable"),)
    )
    thinker_transport = _FailingThinkerAudioTransport()

    result = run_mvp5_live_voice_evidence(
        local_wav=wav_path,
        config=MVP5LiveVoiceEvidenceConfig(
            run_id="mvp5-goal2-failure",
            live_provider=True,
            allow_local_wav=True,
            approval_packet=_approval_packet(),
            credential_env_var_name="MVP5_TEST_PROVIDER_KEY",
            requested_provider_calls=2,
            max_provider_calls=2,
        ),
        env={"MVP5_TEST_PROVIDER_KEY": "DUMMY_TEST_CREDENTIAL"},
        asr_transport=asr_transport,
        thinker_transport=thinker_transport,
    )

    failed_events = [
        event for event in result.events if event["event_name"] == "ADAPTER_REQUEST_FAILED"
    ]
    assert len(failed_events) == 2
    assert {event["adapter_type"] for event in failed_events} == {"asr", "thinker"}
    assert result.to_metadata()["status"] == "evidence_failed"
    rendered = json.dumps(result.to_metadata(), sort_keys=True)
    assert result.to_metadata()["provider_call_used"] is False
    assert result.to_metadata()["raw_provider_body_included"] is False
    assert str(wav_path) not in rendered
    assert wav_path.name not in rendered
    assert base64.b64encode(wav_bytes).decode("ascii") not in rendered
    assert "provider body" not in rendered.lower()
    assert thinker_transport.call_count == 1


def test_validation_failures_collect_safe_failure_reasons_without_traceback(
    tmp_path: Path,
) -> None:
    wav_path = tmp_path / "goal2-validation-failure.wav"
    _write_wav_file(wav_path)
    asr_transport = FakeAsrTransport(
        (
            FakeAsrProviderResponse.success(
                asr_frame_ref="asr-frame://synthetic/mvp5/goal2/validation-failure",
                text_ref="text://synthetic/mvp5/goal2/validation-failure",
                audio_timestamps_ref=None,
                streaming_status="unsupported_final_only",
            ),
        )
    )
    thinker_transport = _MalformedThinkerAudioTransport()

    result = run_mvp5_live_voice_evidence(
        local_wav=wav_path,
        config=MVP5LiveVoiceEvidenceConfig(
            run_id="mvp5-goal2-validation-failure",
            live_provider=True,
            allow_local_wav=True,
            approval_packet=_approval_packet(),
            credential_env_var_name="MVP5_TEST_PROVIDER_KEY",
            requested_provider_calls=2,
            max_provider_calls=2,
        ),
        env={"MVP5_TEST_PROVIDER_KEY": "DUMMY_TEST_CREDENTIAL"},
        asr_transport=asr_transport,
        thinker_transport=thinker_transport,
    )

    metadata = result.to_metadata()
    assert metadata["status"] == "evidence_failed"
    assert metadata["failure_reasons"] == ["invalid_json"]
    assert metadata["raw_provider_body_included"] is False
    assert thinker_transport.call_count == 1


class _ExplodingAsrTransport:
    def __init__(self) -> None:
        self.call_count = 0

    def transcribe(self, *_args: object, **_kwargs: object) -> object:
        self.call_count += 1
        raise AssertionError("ASR transport must not be called in provider-free default mode")


class _ExplodingThinkerTransport:
    def __init__(self) -> None:
        self.call_count = 0

    def complete_audio(self, *_args: object, **_kwargs: object) -> str:
        self.call_count += 1
        raise AssertionError("Thinker transport must not be called in provider-free default mode")


class _MalformedThinkerAudioTransport:
    def __init__(self) -> None:
        self.call_count = 0

    def complete_audio(self, *_args: object, **_kwargs: object) -> str:
        self.call_count += 1
        return "{bad}"


class _FakeThinkerAudioTransport:
    def __init__(
        self,
        *,
        optional_available: bool,
        focus: str = "FOREGROUND_CHAT",
        task_like: bool = False,
        complexity_hint: str = "simple",
        focus_confidence: float = 0.86,
        evidence_uncertainty: str = "low",
    ) -> None:
        self.optional_available = optional_available
        self.focus = focus
        self.task_like = task_like
        self.complexity_hint = complexity_hint
        self.focus_confidence = focus_confidence
        self.evidence_uncertainty = evidence_uncertainty
        self.call_count = 0
        self.audio_bytes_seen: bytes | None = None

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
        assert audio_format == "wav"
        assert credential_value.startswith("DUMMY_TEST_CREDENTIAL")
        assert adapter_request_id.startswith("adapter-request-mvp5-thinker-")
        assert timeout_ms == 30_000
        assert model_alias == LALM_THINKER_RUNTIME_MODEL_ALIAS
        assert "secret_materialized=False" in repr(credential_handle)
        self.call_count += 1
        self.audio_bytes_seen = audio_bytes

        skeleton = dict(request_payload["required_output_skeleton"])
        skeleton["output_mode"] = "real" if self.optional_available else "degraded"
        status = "available" if self.optional_available else "unavailable"
        skeleton["optional_evidence_refs"] = {
            "semantic_close": {"status": status, "label": "closed"},
            "assistant_directedness": {"status": status, "label": "directed"},
            "emotion": {"status": status, "label": "neutral"},
            "audio_caption": {"status": status, "label": "speech_available"},
        }
        skeleton["task_focus_hint"] = {
            "focus": self.focus,
            "task_like": self.task_like,
            "complexity_hint": self.complexity_hint,
            "focus_confidence": self.focus_confidence,
            "evidence_uncertainty": self.evidence_uncertainty,
        }
        return json.dumps(skeleton, separators=(",", ":"), sort_keys=True)


class _SlowAsrLiveTransport:
    def __init__(self, *, delay_seconds: float) -> None:
        self.delay_seconds = delay_seconds
        self.call_count = 0
        self.audio_bytes_seen: bytes | None = None

    def transcribe(
        self,
        *,
        audio_payload: bytes,
        audio_mime_type: str,
        credential_handle: object,
        credential_value: str,
        adapter_request_id: str,
        timeout_ms: int,
        model_alias: str,
    ) -> AsrLiveProviderCallMetadata:
        assert audio_mime_type == "audio/wav"
        assert credential_value.startswith("DUMMY_TEST_CREDENTIAL")
        assert adapter_request_id.startswith("adapter-request-mvp5-asr-")
        assert timeout_ms == 30_000
        assert model_alias
        assert "secret_materialized=False" in repr(credential_handle)
        self.call_count += 1
        self.audio_bytes_seen = audio_payload
        time.sleep(self.delay_seconds)
        return AsrLiveProviderCallMetadata(
            adapter_request_id=adapter_request_id,
            provider_url_ref="provider-url://dashscope/qwen-asr/openai-compatible-chat-completions",
            model_alias=model_alias,
            transcript_present=True,
            asr_frame_ref=f"asr-frame://synthetic/mvp5/parallel/{adapter_request_id}",
            text_ref=f"text://synthetic/mvp5/parallel/{adapter_request_id}",
            response_text_size_bucket="small",
        )


class _SlowThinkerAudioTransport:
    def __init__(self, *, delay_seconds: float) -> None:
        self.delay_seconds = delay_seconds
        self.call_count = 0
        self.audio_bytes_seen: bytes | None = None
        self.transient_input_text_seen = False

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
        assert "transient_input_evidence" not in request_payload
        assert audio_format == "wav"
        assert credential_value.startswith("DUMMY_TEST_CREDENTIAL")
        assert adapter_request_id.startswith("adapter-request-mvp5-thinker-")
        assert timeout_ms == 30_000
        assert model_alias == LALM_THINKER_RUNTIME_MODEL_ALIAS
        assert "secret_materialized=False" in repr(credential_handle)
        self.call_count += 1
        self.audio_bytes_seen = audio_bytes
        self.transient_input_text_seen = "transient_input_evidence" in request_payload
        time.sleep(self.delay_seconds)

        skeleton = dict(request_payload["required_output_skeleton"])
        skeleton["output_mode"] = "real"
        skeleton["optional_evidence_refs"] = {
            "semantic_close": {"status": "available", "label": "closed"},
            "assistant_directedness": {"status": "available", "label": "directed"},
            "emotion": {"status": "available", "label": "neutral"},
            "audio_caption": {"status": "available", "label": "speech_available"},
        }
        skeleton["task_focus_hint"] = {
            "focus": "FOREGROUND_CHAT",
            "task_like": False,
            "complexity_hint": "simple",
            "focus_confidence": 0.86,
            "evidence_uncertainty": "low",
        }
        return json.dumps(skeleton, separators=(",", ":"), sort_keys=True)


class _FailingThinkerAudioTransport:
    def __init__(self) -> None:
        self.call_count = 0

    def complete_audio(self, **_kwargs: object) -> str:
        self.call_count += 1
        raise LALMThinkerLiveTransportError(
            "provider failed before returning safe metadata",
            category="provider_request_failed",
            failure_reasons=("provider_request_failed",),
        )


def _approval_packet() -> dict[str, object]:
    return {
        "approval_id": "mvp5-live-evidence-goal2-test",
        "live_provider_opt_in": True,
        "local_wav_opt_in": True,
        "metadata_only_output": True,
        "replay_reruns_provider": False,
        "provider_adapter_ids": ["mvp5_asr_adapter", "mvp5_thinker_adapter"],
        "credential_env_var_name": "MVP5_TEST_PROVIDER_KEY",
        "max_provider_calls": 2,
        "timeout_ms": 30_000,
        "safe_output_ref": "summary://mvp5/goal2/live-evidence-test",
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
