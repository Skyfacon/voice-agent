from __future__ import annotations

import json
import os
from typing import Any

import pytest

from tests.runtime.test_asr_runtime_integration import _approved_packet
from voice_agent.replay.runner import run_replay_fixture
from voice_agent.runtime import mvp4_voice_e2e_orchestrator as mvp4


def test_real_evidence_paths_emit_metadata_only_refs_and_router_ready_event_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class EnvTrap(dict[str, str]):
        def get(self, key: object, default: object | None = None) -> object:
            pytest.fail(f"MVP4 real-evidence orchestrator must not read os.environ key {key!r}")

        def __getitem__(self, key: str) -> str:
            pytest.fail(f"MVP4 real-evidence orchestrator must not read os.environ key {key!r}")

        def __contains__(self, key: object) -> bool:
            pytest.fail(f"MVP4 real-evidence orchestrator must not inspect os.environ key {key!r}")

    monkeypatch.setattr(os, "environ", EnvTrap())
    audio_input = mvp4.load_synthetic_wav_metadata(
        fixture_id="synthetic-real-evidence-001",
        duration_ms=1000,
        sample_rate_hz=16000,
        channel_count=1,
    )
    thinker_transport = _FakeMVP4ThinkerAudioTransport()
    asr_transport = _FakeMVP4AsrTransport()

    result = mvp4.run_real_evidence_voice_e2e(
        audio_input=audio_input,
        thinker_transport=thinker_transport,
        thinker_credential_value="synthetic-credential-value",
        asr_transport=asr_transport,
        asr_approval_packet=_approved_packet(max_request_count=1, retry_budget=0),
        asr_env={"MVP4_FAKE_ASR_CREDENTIAL": "synthetic-credential-value"},
        asr_credential_env_var="MVP4_FAKE_ASR_CREDENTIAL",
    )

    events = result.events
    events_by_id = {event["event_id"]: event for event in events}
    event_names = [event["event_name"] for event in events]

    assert thinker_transport.call_count == 1
    assert asr_transport.call_count == 1
    assert "MOCK_ASR_FRAME_EMITTED" not in event_names
    assert "MOCK_THINKER_FRAME_EMITTED" not in event_names
    assert "SEMANTIC_COMMITMENT_EMITTED" not in event_names

    turn_event = result.turn_committed_event
    thinker_event = result.thinker_frame_event
    asr_event = result.asr_frame_event
    router_event = result.router_decision_event

    assert turn_event["event_name"] == "TURN_INGRESS_COMMITTED"
    assert turn_event["input_modality"] == "audio"
    assert turn_event["audio_input_ref"] == audio_input.safe_audio_ref
    assert thinker_event["event_name"] == "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED"
    assert asr_event["event_name"] == "ASR_TRANSCRIPT_OUTPUT_EMITTED"
    assert router_event["event_name"] == "ROUTER_DECISION_EMITTED"

    assert turn_event["event_seq"] < thinker_event["event_seq"] < asr_event["event_seq"]
    assert asr_event["event_seq"] < router_event["event_seq"]
    assert thinker_event["caused_by_event_id"] == turn_event["event_id"]
    assert asr_event["caused_by_event_id"] == turn_event["event_id"]
    assert router_event["thinker_frame_event_id"] == thinker_event["event_id"]
    assert router_event["asr_frame_event_id"] == asr_event["event_id"]
    assert router_event["turn_committed_event_id"] == turn_event["event_id"]

    for evidence_event in (thinker_event, asr_event, router_event):
        assert evidence_event["turn_id"] == turn_event["turn_id"]
        assert evidence_event["utterance_id"] == turn_event["utterance_id"]
    assert thinker_event["audio_span_id"] == turn_event["audio_span_id"]
    assert asr_event["audio_span_id"] == turn_event["audio_span_id"]

    assert thinker_event["input_modality"] == "audio"
    assert thinker_event["output_mode"] == "real"
    assert thinker_event["semantic_frame_ref"].startswith(
        "semantic-frame://synthetic/lalm-thinker/adapter-owned/"
    )
    assert thinker_event["semantic_summary_ref"].startswith(
        "summary://synthetic/lalm-thinker/adapter-owned/"
    )
    assert thinker_event["semantic_close_status"] == "available"
    assert thinker_event["assistant_directedness_status"] == "available"
    assert thinker_event["emotion_status"] == "available"
    assert thinker_event["audio_caption_status"] == "available"

    assert asr_event["output_mode"] == "degraded"
    assert asr_event["transcript_finality"] == "final"
    assert asr_event["timestamp_status"] == "unavailable"
    assert asr_event["streaming_status"] == "unsupported_final_only"
    assert asr_event["asr_frame_ref"].startswith("asr-frame://synthetic/mvp4/")
    assert asr_event["text_ref"].startswith("text://synthetic/mvp4/")
    assert "semantic_frame_ref" not in asr_event
    assert "raw_transcript" not in asr_event

    assert events_by_id[router_event["asr_frame_event_id"]] == asr_event
    assert events_by_id[router_event["thinker_frame_event_id"]] == thinker_event
    assert "asr_frame_ref" not in router_event
    assert "text_ref" not in router_event
    assert "semantic_frame_ref" not in router_event
    assert "semantic_summary_ref" not in router_event
    assert "raw_transcript" not in repr(router_event)
    assert "provider_body" not in repr(router_event)

    fixture = result.to_replay_fixture()
    mvp4.validate_mvp4_fixture_safety(fixture)
    replay_result = run_replay_fixture(fixture)

    assert replay_result.result_status == "passed"
    assert replay_result.adapter_health_state.output_event_modes[thinker_event["event_id"]] == "real"
    assert replay_result.adapter_health_state.output_event_modes[asr_event["event_id"]] == "degraded"


def test_real_evidence_replay_uses_recorded_refs_without_rerunning_adapters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    thinker_transport = _FakeMVP4ThinkerAudioTransport()
    asr_transport = _FakeMVP4AsrTransport()
    result = mvp4.run_real_evidence_voice_e2e(
        audio_input=mvp4.load_synthetic_wav_metadata(
            fixture_id="synthetic-real-evidence-replay-001",
            duration_ms=1000,
            sample_rate_hz=16000,
            channel_count=1,
        ),
        thinker_transport=thinker_transport,
        thinker_credential_value="synthetic-credential-value",
        asr_transport=asr_transport,
        asr_approval_packet=_approved_packet(max_request_count=1, retry_budget=0),
        asr_env={"MVP4_FAKE_ASR_CREDENTIAL": "synthetic-credential-value"},
        asr_credential_env_var="MVP4_FAKE_ASR_CREDENTIAL",
    )
    fixture = result.to_replay_fixture()
    serialized = repr(fixture)

    assert thinker_transport.call_count == 1
    assert asr_transport.call_count == 1
    assert "synthetic-credential-value" not in serialized
    assert "RIFF" not in serialized
    assert "raw_audio_bytes" not in serialized
    assert "audio_payload" not in serialized
    assert "raw_transcript" not in serialized
    assert "provider_response" not in serialized
    assert "prompt_dump" not in serialized

    def fail_if_replay_calls_runtime(*args: object, **kwargs: object) -> None:
        raise AssertionError("deterministic replay must not rerun Thinker or ASR adapters")

    monkeypatch.setattr(
        "voice_agent.adapters.lalm_thinker_audio_native_runtime.emit_lalm_thinker_audio_native_evidence_for_turn",
        fail_if_replay_calls_runtime,
    )
    monkeypatch.setattr(
        "voice_agent.runtime.asr_session_hook.run_asr_for_committed_audio_turn",
        fail_if_replay_calls_runtime,
    )

    replay_result = run_replay_fixture(fixture)

    assert replay_result.result_status == "passed"
    assert thinker_transport.call_count == 1
    assert asr_transport.call_count == 1


class _FakeMVP4ThinkerAudioTransport:
    def __init__(self) -> None:
        self.call_count = 0
        self.audio_bytes_seen: bytes | None = None
        self.audio_format_seen: str | None = None

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
        assert credential_value == "synthetic-credential-value"
        assert "secret_materialized=False" in repr(credential_handle)
        assert adapter_request_id.startswith("adapter-request-mvp4-thinker-audio-native-")
        assert timeout_ms > 0
        assert model_alias
        assert audio_bytes.startswith(b"RIFF")
        assert audio_format == "wav"
        assert "raw_audio" not in repr(request_payload)
        self.call_count += 1
        self.audio_bytes_seen = audio_bytes
        self.audio_format_seen = audio_format

        skeleton = dict(request_payload["required_output_skeleton"])
        skeleton["output_mode"] = "real"
        skeleton["optional_evidence_refs"] = {
            "semantic_close": {"status": "available", "label": "closed"},
            "assistant_directedness": {"status": "available", "label": "directed"},
            "emotion": {"status": "available", "label": "neutral"},
            "audio_caption": {"status": "available", "label": "speech_available"},
        }
        skeleton["task_focus_hint"] = {
            "task_like": False,
            "complexity_hint": "simple",
            "focus_confidence": 0.88,
            "evidence_uncertainty": "low",
        }
        return json.dumps(skeleton, separators=(",", ":"), sort_keys=True)


class _FakeMVP4AsrTransport:
    def __init__(self) -> None:
        self.call_count = 0
        self.adapter_request_id: str | None = None

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
    ) -> object:
        assert audio_payload.startswith(b"RIFF")
        assert audio_mime_type == "audio/wav"
        assert "synthetic-credential-value" not in repr(credential_handle)
        assert credential_value == "synthetic-credential-value"
        assert adapter_request_id.startswith("adapter_request_runtime_asr_mvp4_real_evidence")
        assert timeout_ms > 0
        assert model_alias
        self.call_count += 1
        self.adapter_request_id = adapter_request_id
        return _FakeMVP4AsrMetadata(adapter_request_id)


class _FakeMVP4AsrMetadata:
    def __init__(self, adapter_request_id: str) -> None:
        self.adapter_request_id = adapter_request_id

    def to_metadata(self) -> dict[str, Any]:
        return {
            "adapter_request_id": self.adapter_request_id,
            "provider_transport": "fake_transport",
            "model_alias": "qwen3-asr-flash",
            "success": True,
            "transcript_present": True,
            "asr_frame_ref": f"asr-frame://synthetic/mvp4/{self.adapter_request_id}",
            "text_ref": f"text://synthetic/mvp4/{self.adapter_request_id}",
            "response_text_size_bucket": "small",
            "raw_audio_included": False,
            "raw_transcript_included": False,
            "raw_provider_request_included": False,
            "raw_provider_response_included": False,
            "headers_included": False,
            "authorization_header_included": False,
            "secret_included": False,
        }
