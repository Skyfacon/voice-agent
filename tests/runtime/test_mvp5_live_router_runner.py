from __future__ import annotations

import json
from pathlib import Path
import wave

from voice_agent.adapters.asr_fake_transport import FakeAsrProviderResponse, FakeAsrTransport
from voice_agent.adapters.lalm_thinker_runtime_adapter import LALM_THINKER_RUNTIME_MODEL_ALIAS
from voice_agent.runtime.mvp5_live_router_runner import (
    MVP5LiveRouterConfig,
    run_mvp5_live_router_runner,
)
from voice_agent.runtime.mvp5_live_voice_evidence import (
    MVP5LiveVoiceEvidenceConfig,
    run_mvp5_live_voice_evidence,
)


def test_runner_routes_goal2_evidence_refs_through_router_without_selecting_winner(
    tmp_path: Path,
) -> None:
    evidence = _live_evidence_result(tmp_path, route_slug="spawn", task_like=True)

    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="mvp5-goal3-router-spawn",
            expected_route="SPAWN_SLOW_TASK",
        ),
    )

    router_event = _event(result.events, "ROUTER_DECISION_EMITTED")
    committed = _event(result.events, "TURN_INGRESS_COMMITTED")
    asr_event = _event(result.events, "ASR_TRANSCRIPT_OUTPUT_EMITTED")
    thinker_event = _event(result.events, "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED")

    assert result.status == "routed"
    assert result.router_decision == "SPAWN_SLOW_TASK"
    assert router_event["router_decision"] == "SPAWN_SLOW_TASK"
    assert router_event["turn_committed_event_id"] == committed["event_id"]
    assert router_event["asr_frame_event_id"] == asr_event["event_id"]
    assert router_event["thinker_frame_event_id"] == thinker_event["event_id"]
    assert router_event["turn_id"] == committed["turn_id"] == asr_event["turn_id"] == thinker_event["turn_id"]
    assert router_event["utterance_id"] == (
        committed["utterance_id"]
    ) == asr_event["utterance_id"] == thinker_event["utterance_id"]
    assert router_event["asr_thinker_winner_selected"] is False

    metadata = result.to_metadata()
    rendered = json.dumps(metadata, sort_keys=True)
    assert metadata["router_decision"] == "SPAWN_SLOW_TASK"
    assert metadata["actual_route"] == "SPAWN_SLOW_TASK"
    assert metadata["expected_route"] == "SPAWN_SLOW_TASK"
    assert metadata["expected_route_matched"] is True
    assert metadata["asr_event_id"] == asr_event["event_id"]
    assert metadata["thinker_event_id"] == thinker_event["event_id"]
    assert metadata["router_event_id"] == router_event["event_id"]
    assert metadata["asr_thinker_winner_selected"] is False
    assert metadata["provider_call_used"] is False
    assert metadata["replay_reruns_provider"] is False
    assert "DUMMY_TEST_CREDENTIAL" not in rendered


def test_expected_route_mismatch_reports_actual_decision_without_forcing_route_events(
    tmp_path: Path,
) -> None:
    evidence = _live_evidence_result(tmp_path, route_slug="actual-spawn", task_like=True)

    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="mvp5-goal3-router-mismatch",
            expected_route="FAST_ONLY",
        ),
    )

    metadata = result.to_metadata()
    event_names = [event["event_name"] for event in result.events]

    assert result.status == "route_mismatch"
    assert result.router_decision == "SPAWN_SLOW_TASK"
    assert metadata["actual_route"] == "SPAWN_SLOW_TASK"
    assert metadata["expected_route"] == "FAST_ONLY"
    assert metadata["expected_route_matched"] is False
    assert metadata["route_result_kind"] == "mismatch"
    assert "SLOWTASK_CREATED" not in event_names
    assert "USER_PATCH_RECEIVED" not in event_names
    assert "USER_PATCH_INTERPRETED" not in event_names
    assert "PLAN_VERSION_ADVANCED" not in event_names


def _live_evidence_result(
    tmp_path: Path,
    *,
    route_slug: str,
    task_like: bool,
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
    thinker_transport = _FakeThinkerAudioTransport(task_like=task_like)

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


class _FakeThinkerAudioTransport:
    def __init__(self, *, task_like: bool) -> None:
        self.task_like = task_like

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
            "task_like": self.task_like,
            "complexity_hint": "complex" if self.task_like else "simple",
            "focus_confidence": 0.86,
            "evidence_uncertainty": "low",
        }
        return json.dumps(skeleton, separators=(",", ":"), sort_keys=True)


def _approval_packet() -> dict[str, object]:
    return {
        "approval_id": "mvp5-live-router-goal3-test",
        "live_provider_opt_in": True,
        "local_wav_opt_in": True,
        "metadata_only_output": True,
        "replay_reruns_provider": False,
        "provider_adapter_ids": ["mvp5_asr_adapter", "mvp5_thinker_adapter"],
        "credential_env_var_name": "MVP5_TEST_PROVIDER_KEY",
        "max_provider_calls": 2,
        "timeout_ms": 30_000,
        "safe_output_ref": "summary://mvp5/goal3/live-router-test",
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
