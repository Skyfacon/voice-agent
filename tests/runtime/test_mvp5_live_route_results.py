from __future__ import annotations

import json
from pathlib import Path
import wave

from voice_agent.adapters.asr_fake_transport import FakeAsrProviderResponse, FakeAsrTransport
from voice_agent.adapters.lalm_thinker_runtime_adapter import LALM_THINKER_RUNTIME_MODEL_ALIAS
from voice_agent.runtime.mvp5_live_router_runner import (
    MVP5ActiveSlowTaskContext,
    MVP5LiveRouterConfig,
    run_mvp5_live_router_runner,
)
from voice_agent.runtime.mvp5_live_voice_evidence import (
    MVP5LiveVoiceEvidenceConfig,
    run_mvp5_live_voice_evidence,
)


def test_fast_only_result_is_metadata_only_and_does_not_mutate_slowtask(
    tmp_path: Path,
) -> None:
    evidence = _live_evidence_result(
        tmp_path,
        route_slug="fast-only",
        task_focus_hint="FOREGROUND_CHAT",
        task_like=False,
        complexity_hint="simple",
    )

    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="mvp5-goal3-fast-only",
            expected_route="FAST_ONLY",
        ),
    )

    metadata = result.to_metadata()
    event_names = [event["event_name"] for event in result.events]

    assert result.status == "routed"
    assert metadata["route_result_kind"] == "direct_answer"
    assert metadata["router_decision"] == "FAST_ONLY"
    assert _event(result.events, "ROUTER_DECISION_EMITTED")["task_focus"] == "FOREGROUND_CHAT"
    assert metadata["response_text_ref"].startswith("response://synthetic/mvp5/")
    assert metadata["real_tts_used"] is False
    assert metadata["voice_output"] == "none"
    for forbidden_event in (
        "SLOWTASK_CREATED",
        "USER_PATCH_RECEIVED",
        "USER_PATCH_INTERPRETED",
        "PLAN_VERSION_ADVANCED",
    ):
        assert forbidden_event not in event_names
    _assert_safe_summary(metadata)


def test_spawn_slowtask_records_asr_and_thinker_refs_in_slowtask_evidence(
    tmp_path: Path,
) -> None:
    evidence = _live_evidence_result(
        tmp_path,
        route_slug="spawn-route",
        task_focus_hint="NEW_TASK_CANDIDATE",
        task_like=True,
        complexity_hint="complex",
    )

    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="mvp5-goal3-spawn-slowtask",
            expected_route="SPAWN_SLOW_TASK",
        ),
    )

    asr_event = _event(result.events, "ASR_TRANSCRIPT_OUTPUT_EMITTED")
    thinker_event = _event(result.events, "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED")
    created = _event(result.events, "SLOWTASK_CREATED")
    reviewed = _event(result.events, "EVIDENCE_REVIEWED")
    slowtask_events = [
        event for event in result.events if event["event_name"] in result.slowtask_event_ids_by_name
    ]

    expected_refs = {
        f"event://mvp5/{asr_event['event_id']}",
        str(asr_event["asr_frame_ref"]),
        f"event://mvp5/{thinker_event['event_id']}",
        str(thinker_event["semantic_frame_ref"]),
    }
    assert result.to_metadata()["route_result_kind"] == "slowtask_spawn"
    assert _event(result.events, "ROUTER_DECISION_EMITTED")["task_focus"] == "NEW_TASK_CANDIDATE"
    assert expected_refs.issubset(set(created["source_evidence_refs"]))
    assert expected_refs.issubset(set(reviewed["evidence_refs"]))
    assert slowtask_events
    for event in slowtask_events:
        assert event["task_id"] == created["task_id"]
        assert event["plan_version"] == 1
        assert isinstance(event["task_event_seq"], int)
    _assert_safe_summary(result.to_metadata())


def test_patch_active_slowtask_receives_current_plan_user_patch_only(
    tmp_path: Path,
) -> None:
    evidence = _live_evidence_result(
        tmp_path,
        route_slug="patch-active",
        task_focus_hint="ACTIVE_TASK_PATCH",
        task_like=True,
        complexity_hint="medium",
    )

    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="mvp5-goal3-patch-active",
            expected_route="PATCH_ACTIVE_SLOW_TASK",
            active_task_context=MVP5ActiveSlowTaskContext(
                task_id="task_mvp5_goal3_active",
                current_plan_version=4,
                current_task_event_seq=9,
                lifecycle_phase="PLANNING",
            ),
        ),
    )

    user_patch = _event(result.events, "USER_PATCH_RECEIVED")
    asr_event = _event(result.events, "ASR_TRANSCRIPT_OUTPUT_EMITTED")
    thinker_event = _event(result.events, "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED")
    event_names = [event["event_name"] for event in result.events]

    assert result.to_metadata()["route_result_kind"] == "user_patch"
    assert _event(result.events, "ROUTER_DECISION_EMITTED")["task_focus"] == "ACTIVE_TASK_PATCH"
    assert user_patch["patch_id"] == "patch_mvp5_goal3_patch_active"
    assert user_patch["task_id"] == "task_mvp5_goal3_active"
    assert user_patch["plan_version"] == 4
    assert user_patch["observed_plan_version"] == 4
    assert user_patch["task_event_seq"] == 10
    assert user_patch["turn_id"] == evidence.turn_id
    assert user_patch["utterance_id"] == evidence.utterance_id
    assert user_patch["evidence_ref"].startswith("evidence://synthetic/mvp5/")
    assert f"audio-span://{evidence.audio_span_id}" in user_patch["authoritative_evidence_refs"]
    assert asr_event["asr_frame_ref"] in user_patch["authoritative_evidence_refs"]
    assert thinker_event["semantic_frame_ref"] in user_patch["non_authoritative_hypothesis_refs"]
    assert thinker_event["semantic_summary_ref"] in user_patch["non_authoritative_hypothesis_refs"]
    assert user_patch["evidence_pack"]["authoritative_evidence"]["source_event_ids"] == [
        _event(result.events, "TURN_INGRESS_COMMITTED")["event_id"],
        asr_event["event_id"],
    ]
    assert (
        user_patch["evidence_pack"]["non_authoritative_hypothesis"]["provenance"][
            "semantic_summary_ref"
        ]["source_event_id"]
        == thinker_event["event_id"]
    )
    for forbidden_event in (
        "USER_PATCH_INTERPRETED",
        "PLAN_VERSION_ADVANCED",
        "CONFIRMATION_ACCEPTED",
        "TOOL_EXECUTION_AUTHORIZED",
    ):
        assert forbidden_event not in event_names
    for forbidden_field in (
        "resolved_arguments_ref",
        "constraints_ref",
        "goal_ref",
        "confirmation_id",
        "authorization_ref",
    ):
        assert forbidden_field not in user_patch
    _assert_safe_summary(result.to_metadata())


def test_active_task_patch_hint_without_active_context_is_blocked_without_mutation(
    tmp_path: Path,
) -> None:
    evidence = _live_evidence_result(
        tmp_path,
        route_slug="patch-no-active",
        task_focus_hint="ACTIVE_TASK_PATCH",
        task_like=True,
        complexity_hint="medium",
    )

    result = run_mvp5_live_router_runner(
        evidence,
        config=MVP5LiveRouterConfig(
            run_id="mvp5-goal3-patch-no-active",
            expected_route="PATCH_ACTIVE_SLOW_TASK",
        ),
    )

    metadata = result.to_metadata()
    event_names = [event["event_name"] for event in result.events]

    assert metadata["status"] == "blocked_missing_active_task_context"
    assert metadata["route_result_kind"] == "degraded"
    assert metadata["router_decision"] is None
    assert metadata["expected_route"] == "PATCH_ACTIVE_SLOW_TASK"
    assert metadata["expected_route_matched"] is False
    assert "USER_PATCH_RECEIVED" not in event_names
    assert "SLOWTASK_CREATED" not in event_names
    assert "PLAN_VERSION_ADVANCED" not in event_names
    _assert_safe_summary(metadata)


def _assert_safe_summary(metadata: dict[str, object]) -> None:
    assert metadata["raw_audio_included"] is False
    assert metadata["raw_transcript_included"] is False
    assert metadata["raw_provider_body_included"] is False
    assert metadata["prompt_dump_included"] is False
    assert metadata["secret_included"] is False
    assert metadata["local_wav_path_included"] is False
    assert metadata["provider_call_used"] is False
    assert metadata["replay_reruns_provider"] is False
    assert metadata["real_tts_used"] is False
    assert metadata["voice_output"] == "none"
    rendered = json.dumps(metadata, sort_keys=True)
    for unsafe in (
        "DUMMY_TEST_CREDENTIAL",
        "file://",
        "data:",
        "audio/raw/",
        "diagnostics/",
        "traces/",
        "replays/local/",
        "raw transcript",
        "provider body",
        "prompt dump",
    ):
        assert unsafe not in rendered


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
        "approval_id": "mvp5-live-route-results-goal3-test",
        "live_provider_opt_in": True,
        "local_wav_opt_in": True,
        "metadata_only_output": True,
        "replay_reruns_provider": False,
        "provider_adapter_ids": ["mvp5_asr_adapter", "mvp5_thinker_adapter"],
        "credential_env_var_name": "MVP5_TEST_PROVIDER_KEY",
        "max_provider_calls": 2,
        "timeout_ms": 30_000,
        "safe_output_ref": "summary://mvp5/goal3/live-route-results-test",
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
