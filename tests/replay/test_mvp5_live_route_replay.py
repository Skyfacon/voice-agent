from __future__ import annotations

import json
from pathlib import Path
import wave

import pytest

from voice_agent.adapters.asr_fake_transport import FakeAsrProviderResponse, FakeAsrTransport
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
