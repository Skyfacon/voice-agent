from __future__ import annotations

from voice_agent.runtime import mvp4_voice_e2e_orchestrator as mvp4


def test_fast_only_voice_outcome_produces_runtime_summary_without_slowtask_or_voice_out() -> None:
    result = mvp4.run_mvp4_router_fast_only_voice_e2e()
    event_names = [event["event_name"] for event in result.events]
    router_event = result.router_decision_event

    assert router_event["router_decision"] == "FAST_ONLY"
    assert event_names.count("ASR_TRANSCRIPT_OUTPUT_EMITTED") == 1
    assert event_names.count("THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED") == 1
    assert "SLOWTASK_CREATED" not in event_names
    assert "USER_PATCH_RECEIVED" not in event_names
    assert "USER_PATCH_INTERPRETED" not in event_names
    assert "PLAN_VERSION_ADVANCED" not in event_names
    assert "TTS_SYNTHESIS_OUTPUT_EMITTED" not in event_names
    assert "PLAYBACK_SPAN_STARTED" not in event_names

    assert result.response_summary == {
        "response_kind": "runtime_summary",
        "route": "FAST_ONLY",
        "source_router_event_id": router_event["event_id"],
        "response_text_ref": "response-text://synthetic/mvp4/router-fast-only",
        "real_tts_used": False,
        "voice_output": "none",
    }


def test_spawn_slowtask_voice_outcome_records_existing_mock_create_and_planning_path() -> None:
    result = mvp4.run_mvp4_router_spawn_slowtask_voice_e2e()
    events = result.events
    event_names = [event["event_name"] for event in events]
    router_event = result.router_decision_event
    asr_event = result.asr_frame_event
    thinker_event = result.thinker_frame_event
    created_event = _single(events, "SLOWTASK_CREATED")
    evidence_reviewed = _single(events, "EVIDENCE_REVIEWED")
    commitment = _single(events, "SEMANTIC_COMMITMENT_EMITTED")

    assert router_event["router_decision"] == "SPAWN_SLOW_TASK"
    assert router_event["asr_frame_event_id"] == asr_event["event_id"]
    assert router_event["thinker_frame_event_id"] == thinker_event["event_id"]
    assert event_names.count("SLOWTASK_CREATED") == 1
    assert event_names.count("PLANNING_STARTED") == 1
    assert event_names.count("SLOWTASK_STATE_CHANGED") >= 3
    assert "SLOW_LLM_STRUCTURED_OUTPUT_EMITTED" not in event_names
    assert not any(name.startswith("TOOL_") for name in event_names)

    expected_refs = [asr_event["asr_frame_ref"], thinker_event["semantic_frame_ref"]]
    assert created_event["source_evidence_refs"] == expected_refs
    assert evidence_reviewed["evidence_refs"] == expected_refs
    for slowtask_event in (created_event, evidence_reviewed, commitment):
        assert slowtask_event["task_id"] == result.control_plane_summary["task_id"]
        assert slowtask_event["plan_version"] == 1
        assert isinstance(slowtask_event["task_event_seq"], int)

    assert result.response_summary["route"] == "SPAWN_SLOW_TASK"
    assert result.response_summary["source_event_id"] == commitment["event_id"]
    assert result.response_summary["response_text_ref"].startswith(
        "response-text://synthetic/mvp4/slowtask-mock/"
    )
    assert result.response_summary["real_tts_used"] is False


def test_patch_active_slowtask_voice_outcome_records_user_patch_with_real_evidence_refs_only() -> None:
    result = mvp4.run_mvp4_router_patch_active_slowtask_voice_e2e()
    events = result.events
    event_names = [event["event_name"] for event in events]
    router_event = result.router_decision_event
    asr_event = result.asr_frame_event
    thinker_event = result.thinker_frame_event
    turn_event = result.turn_committed_event
    user_patch = _single(events, "USER_PATCH_RECEIVED")

    assert router_event["router_decision"] == "PATCH_ACTIVE_SLOW_TASK"
    assert router_event["active_task_id"] == result.control_plane_summary["active_task_id"]
    assert user_patch["task_id"] == result.control_plane_summary["active_task_id"]
    assert user_patch["plan_version"] == result.control_plane_summary["plan_version"]
    assert user_patch["observed_plan_version"] == result.control_plane_summary["plan_version"]
    assert user_patch["task_event_seq"] == result.control_plane_summary["task_event_seq"]
    assert user_patch["turn_id"] == turn_event["turn_id"]
    assert user_patch["utterance_id"] == turn_event["utterance_id"]
    assert router_event["turn_committed_event_id"] == turn_event["event_id"]
    assert router_event["asr_frame_event_id"] == asr_event["event_id"]
    assert router_event["thinker_frame_event_id"] == thinker_event["event_id"]

    assert f"audio-span://{turn_event['audio_span_id']}" in user_patch["authoritative_evidence_refs"]
    assert asr_event["asr_frame_ref"] in user_patch["authoritative_evidence_refs"]
    assert thinker_event["semantic_frame_ref"] in user_patch["non_authoritative_hypothesis_refs"]
    assert thinker_event["semantic_summary_ref"] in user_patch["non_authoritative_hypothesis_refs"]

    evidence_pack = user_patch["evidence_pack"]
    assert asr_event["event_id"] in evidence_pack["authoritative_evidence"]["source_event_ids"]
    assert evidence_pack["non_authoritative_hypothesis"]["provenance"]["semantic_summary_ref"] == {
        "source": "thinker",
        "source_event_id": thinker_event["event_id"],
        "evidence_ref": thinker_event["semantic_frame_ref"],
    }
    assert "raw_transcript" not in repr(user_patch)
    assert "provider_body" not in repr(user_patch)
    assert "USER_PATCH_INTERPRETED" not in event_names
    assert "PLAN_VERSION_ADVANCED" not in event_names
    assert not any(name.startswith("TOOL_") for name in event_names)


def _single(events: tuple[dict[str, object], ...], event_name: str) -> dict[str, object]:
    matches = [event for event in events if event["event_name"] == event_name]
    assert len(matches) == 1
    return matches[0]
