from __future__ import annotations

import importlib
from dataclasses import FrozenInstanceError
from types import ModuleType

import pytest

from voice_agent.replay.state_digest import (
    canonical_digest_payload,
    stable_hash,
    state_digest,
)
from voice_agent.state.adapter_health_state import AdapterHealthState


_TRANSCRIPT_DIGEST = "sha256:" + "1" * 64
_PCM_DIGEST = "sha256:" + "2" * 64
_PARALLEL_TOPOLOGY = "speculative_candidate_parallel_route"
_RELEASE_REF = (
    "release-token://synthetic/"
    "release_token_0123456789abcdef0123456789abcdef"
)


def _module() -> ModuleType:
    return importlib.import_module("voice_agent.state.qwen_parallel_state")


def _event(event_name: str, event_id: str, **fields: object) -> dict[str, object]:
    return {"event_name": event_name, "event_id": event_id, **fields}


def _provider_event(
    event_id: str,
    *,
    generation: int,
    from_state: str,
    to_state: str,
    playback_epoch: int | None = None,
    interaction_state_version: int | None = None,
    dropped_audio_frame_count: int | None = None,
    event_seq: int | None = None,
) -> dict[str, object]:
    fields: dict[str, object] = {
        "provider_session_generation": generation,
        "from_state": from_state,
        "to_state": to_state,
    }
    if playback_epoch is not None:
        fields["playback_epoch"] = playback_epoch
    if interaction_state_version is not None:
        fields["interaction_state_version"] = interaction_state_version
    if dropped_audio_frame_count is not None:
        fields["dropped_audio_frame_count"] = dropped_audio_frame_count
    if event_seq is not None:
        fields["event_seq"] = event_seq
    return _event("PROVIDER_CONTEXT_STATE_CHANGED", event_id, **fields)


def _ready_state() -> object:
    state = _module().QwenParallelState()
    assert state.reduce_event(
        _provider_event(
            "evt_provider_rebuilding_1",
            generation=1,
            from_state="CLOSED",
            to_state="REBUILDING",
            playback_epoch=0,
            interaction_state_version=0,
        )
    )
    assert state.reduce_event(
        _provider_event(
            "evt_provider_clean_1",
            generation=1,
            from_state="REBUILDING",
            to_state="CLEAN",
        )
    )
    return state


def _projection(
    event_id: str,
    *,
    role: str,
    projection_id: str,
    snapshot_id: str = "context_snapshot_1",
    generation: int = 1,
    source_event_ids: tuple[str, ...] | None = None,
    source_event_seq: int = 10,
    active_task_ref: str | None = None,
    plan_version: int | None = None,
    task_event_seq: int | None = None,
    pending_confirmation_ref: str | None = None,
) -> dict[str, object]:
    fields: dict[str, object] = {
        "projection_id": projection_id,
        "target_role": role,
        "context_snapshot_id": snapshot_id,
        "provider_session_generation": generation,
        "source_event_seq": source_event_seq,
    }
    if source_event_ids is not None:
        fields["source_event_ids"] = source_event_ids
    if active_task_ref is not None:
        fields["active_task_ref"] = active_task_ref
    if plan_version is not None:
        fields["plan_version"] = plan_version
    if task_event_seq is not None:
        fields["task_event_seq"] = task_event_seq
    if pending_confirmation_ref is not None:
        fields["pending_confirmation_ref"] = pending_confirmation_ref
    return _event(
        "MODEL_CONTEXT_PROJECTION_EMITTED",
        event_id,
        **fields,
    )


def _route_evidence(
    event_id: str = "evt_route_evidence_1",
    *,
    projection_event_id: str = "evt_projection_route_1",
    request_id: str = "route_request_1",
    turn_id: str = "turn_1",
    final_asr_event_id: str = "evt_final_asr_1",
) -> dict[str, object]:
    return _event(
        "ROUTE_EVIDENCE_OUTPUT_EMITTED",
        event_id,
        context_projection_event_id=projection_event_id,
        adapter_request_id=request_id,
        turn_id=turn_id,
        final_asr_event_id=final_asr_event_id,
    )


def _candidate_safety(
    event_id: str = "evt_candidate_safety_1",
    *,
    projection_event_id: str = "evt_projection_safety_1",
    request_id: str = "candidate_safety_request_1",
    response_id: str = "qwen_response_1",
    transcript_digest: str = _TRANSCRIPT_DIGEST,
    decision: str = "SAFE",
) -> dict[str, object]:
    return _event(
        "CANDIDATE_SAFETY_EVIDENCE_OUTPUT_EMITTED",
        event_id,
        context_projection_event_id=projection_event_id,
        adapter_request_id=request_id,
        qwen_response_id=response_id,
        candidate_transcript_digest=transcript_digest,
        decision=decision,
    )


def _parallel_fast_output(
    event_id: str = "evt_parallel_fast_1",
    *,
    route_evidence_event_id: str = "evt_route_evidence_1",
    candidate_safety_event_id: str = "evt_candidate_safety_1",
    snapshot_id: str = "context_snapshot_1",
    generation: int = 1,
) -> dict[str, object]:
    return _event(
        "FAST_INTERACTION_OUTPUT_EMITTED",
        event_id,
        fast_interaction_topology=_PARALLEL_TOPOLOGY,
        route_evidence_event_id=route_evidence_event_id,
        candidate_safety_evidence_event_id=candidate_safety_event_id,
        context_snapshot_id=snapshot_id,
        provider_session_generation=generation,
    )


def _candidate(
    event_id: str = "evt_candidate_1",
    *,
    candidate_id: str = "candidate_1",
    fast_output_event_id: str = "evt_parallel_fast_1",
    snapshot_id: str = "context_snapshot_1",
    generation: int = 1,
    response_id: str = "qwen_response_1",
    transcript_digest: str = _TRANSCRIPT_DIGEST,
    pcm_digest: str = _PCM_DIGEST,
) -> dict[str, object]:
    return _event(
        "FOREGROUND_REPLY_CANDIDATE_EMITTED",
        event_id,
        fast_interaction_topology=_PARALLEL_TOPOLOGY,
        candidate_id=candidate_id,
        fast_interaction_output_event_id=fast_output_event_id,
        provider_session_generation=generation,
        context_snapshot_id=snapshot_id,
        qwen_response_id=response_id,
        qwen_output_item_id="qwen_output_item_1",
        qwen_output_index=0,
        qwen_content_index=0,
        candidate_transcript_digest=transcript_digest,
        candidate_pcm_manifest_digest=pcm_digest,
    )


def _gate(
    event_name: str,
    event_id: str,
    *,
    candidate_event_id: str = "evt_candidate_1",
    snapshot_id: str = "context_snapshot_1",
    generation: int = 1,
    release_token_ref: str | None = None,
) -> dict[str, object]:
    fields: dict[str, object] = {
        "fast_interaction_topology": _PARALLEL_TOPOLOGY,
        "candidate_event_id": candidate_event_id,
        "provider_session_generation": generation,
        "context_snapshot_id": snapshot_id,
        "route_evidence_event_id": "evt_route_evidence_1",
        "candidate_safety_evidence_event_id": "evt_candidate_safety_1",
    }
    if release_token_ref is not None:
        fields["release_token_ref"] = release_token_ref
    return _event(event_name, event_id, **fields)


def _handoff(
    event_id: str = "evt_handoff_1",
    *,
    handoff_id: str = "handoff_1",
    kind: str = "PROGRESS",
    expiry_status: str = "CURRENT",
    task_id: str = "task_1",
    plan_version: int = 1,
    task_event_seq: int = 1,
) -> dict[str, object]:
    return _event(
        "SLOW_TO_FAST_HANDOFF_EMITTED",
        event_id,
        handoff_id=handoff_id,
        kind=kind,
        expiry_status=expiry_status,
        task_id=task_id,
        plan_version=plan_version,
        task_event_seq=task_event_seq,
    )


def _arbitration(
    event_id: str,
    *,
    arbitration_id: str,
    selected_source_type: str,
    selected_source_event_id: str | None = None,
    superseded_source_event_ids: tuple[str, ...] = (),
    generation: int = 1,
    playback_epoch: int = 0,
    interaction_state_version: int = 0,
) -> dict[str, object]:
    fields: dict[str, object] = {
        "arbitration_id": arbitration_id,
        "selected_source_type": selected_source_type,
        "superseded_source_event_ids": superseded_source_event_ids,
        "provider_session_generation": generation,
        "playback_epoch": playback_epoch,
        "interaction_state_version": interaction_state_version,
    }
    if selected_source_event_id is not None:
        fields["selected_source_event_id"] = selected_source_event_id
    return _event(
        "RESPONSE_ARBITRATION_DECIDED",
        event_id,
        **fields,
    )


def _candidate_state() -> object:
    state = _ready_state()
    events = (
        _projection(
            "evt_projection_route_1",
            role="route_evidence",
            projection_id="projection_route_1",
        ),
        _route_evidence(),
        _projection(
            "evt_projection_safety_1",
            role="candidate_safety",
            projection_id="projection_safety_1",
        ),
        _candidate_safety(),
        _parallel_fast_output(),
        _candidate(),
    )
    assert all(state.reduce_event(event) for event in events)
    return state


def _committed_candidate_state() -> object:
    state = _candidate_state()
    assert state.reduce_event(
        _gate(
            "FOREGROUND_ACT_GATE_PASSED",
            "evt_gate_passed_for_delivery",
            release_token_ref=_RELEASE_REF,
        )
    )
    assert state.reduce_event(
        _event(
            "FOREGROUND_OUTPUT_COMMITTED",
            "evt_commit_for_delivery",
            fast_interaction_topology=_PARALLEL_TOPOLOGY,
            gate_event_id="evt_gate_passed_for_delivery",
            release_token_ref=_RELEASE_REF,
        )
    )
    return state


def _selected_handoff_state() -> object:
    state = _ready_state()
    assert state.reduce_event(_handoff())
    assert state.reduce_event(
        _event(
            "RESPONSE_ARBITRATION_DECIDED",
            "evt_arbitration_1",
            arbitration_id="arbitration_1",
            selected_source_type="progress",
            selected_source_event_id="evt_handoff_1",
            superseded_source_event_ids=(),
            provider_session_generation=1,
            playback_epoch=0,
            interaction_state_version=0,
        )
    )
    assert state.reduce_event(
        _event(
            "SLOW_TO_FAST_HANDOFF_DISPOSITIONED",
            "evt_handoff_selected_1",
            handoff_id="handoff_1",
            disposition="SELECTED",
            response_arbitration_event_id="evt_arbitration_1",
            current_task_id="task_1",
            current_plan_version=1,
            current_task_event_seq=1,
        )
    )
    return state


def test_candidate_replay_identity_is_frozen_and_slotted() -> None:
    module = _module()
    identity = module.CandidateReplayIdentityV1(
        provider_session_generation=1,
        context_snapshot_id="context_snapshot_1",
        qwen_response_id="qwen_response_1",
        qwen_output_item_id="qwen_output_item_1",
        qwen_output_index=0,
        qwen_content_index=0,
        candidate_transcript_digest=_TRANSCRIPT_DIGEST,
        candidate_pcm_manifest_digest=_PCM_DIGEST,
    )

    assert identity.__slots__ == (
        "provider_session_generation",
        "context_snapshot_id",
        "qwen_response_id",
        "qwen_output_item_id",
        "qwen_output_index",
        "qwen_content_index",
        "candidate_transcript_digest",
        "candidate_pcm_manifest_digest",
    )
    with pytest.raises(FrozenInstanceError):
        identity.provider_session_generation = 2


def test_provider_transition_binds_generation_and_rebuild_fences() -> None:
    module = _module()
    state = _ready_state()

    assert state.saw_adr018_event is True
    assert state.provider_session_generation == 1
    assert state.provider_context_state == "CLEAN"
    assert state.playback_epoch == 0
    assert state.interaction_state_version == 0

    assert state.reduce_event(
        _provider_event(
            "evt_provider_rebuilding_2",
            generation=2,
            from_state="CLEAN",
            to_state="REBUILDING",
            playback_epoch=2,
            interaction_state_version=3,
            dropped_audio_frame_count=4,
        )
    )
    assert state.reduce_event(
        _provider_event(
            "evt_provider_clean_2",
            generation=2,
            from_state="REBUILDING",
            to_state="CLEAN",
            dropped_audio_frame_count=4,
        )
    )
    assert (
        state.provider_session_generation,
        state.provider_context_state,
        state.playback_epoch,
        state.interaction_state_version,
        state.dropped_audio_frame_count,
    ) == (2, "CLEAN", 2, 3, 4)

    before = state.to_digest_dict()
    with pytest.raises(module.QwenParallelStateError, match="generation"):
        state.reduce_event(
            _provider_event(
                "evt_provider_generation_decrease",
                generation=1,
                from_state="CLEAN",
                to_state="REBUILDING",
                playback_epoch=3,
                interaction_state_version=4,
            )
        )
    assert state.to_digest_dict() == before


@pytest.mark.parametrize(
    ("event", "error_match"),
    (
        (
            _provider_event(
                "evt_illegal_transition",
                generation=1,
                from_state="CLOSED",
                to_state="CLEAN",
            ),
            "transition",
        ),
        (
            _provider_event(
                "evt_initial_generation_two",
                generation=2,
                from_state="CLOSED",
                to_state="REBUILDING",
                playback_epoch=0,
                interaction_state_version=0,
            ),
            "generation",
        ),
        (
            _provider_event(
                "evt_partial_rebuild_fence",
                generation=1,
                from_state="CLOSED",
                to_state="REBUILDING",
                playback_epoch=0,
            ),
            "fence",
        ),
    ),
)
def test_provider_transition_rejects_invalid_initial_state_without_mutation(
    event: dict[str, object],
    error_match: str,
) -> None:
    module = _module()
    state = module.QwenParallelState()
    before = state.to_digest_dict()

    with pytest.raises(module.QwenParallelStateError, match=error_match):
        state.reduce_event(event)

    assert state.to_digest_dict() == before
    assert state.saw_adr018_event is False


def test_rebuild_requires_strictly_new_epoch_and_state_version() -> None:
    module = _module()
    for epoch, version in ((0, 1), (1, 0), (0, 0)):
        state = _ready_state()
        before = state.to_digest_dict()

        with pytest.raises(module.QwenParallelStateError, match="fence"):
            state.reduce_event(
                _provider_event(
                    f"evt_bad_rebuild_{epoch}_{version}",
                    generation=2,
                    from_state="CLEAN",
                    to_state="REBUILDING",
                    playback_epoch=epoch,
                    interaction_state_version=version,
                )
            )

        assert state.to_digest_dict() == before


def test_projection_source_prefix_cannot_cross_provider_rebuild_fence() -> None:
    module = _module()
    state = _ready_state()
    assert state.reduce_event(
        _provider_event(
            "evt_provider_rebuilding_2",
            generation=2,
            from_state="CLEAN",
            to_state="REBUILDING",
            playback_epoch=1,
            interaction_state_version=1,
            event_seq=30,
        )
    )
    assert state.reduce_event(
        _provider_event(
            "evt_provider_clean_2",
            generation=2,
            from_state="REBUILDING",
            to_state="CLEAN",
            event_seq=31,
        )
    )
    before = state.to_digest_dict()

    with pytest.raises(module.QwenParallelStateError, match="source.*prefix"):
        state.reduce_event(
            _projection(
                "evt_projection_before_rebuild",
                role="route_evidence",
                projection_id="projection_before_rebuild",
                generation=2,
                source_event_seq=29,
            )
        )
    assert state.to_digest_dict() == before

    assert state.reduce_event(
        _projection(
            "evt_projection_at_rebuild",
            role="route_evidence",
            projection_id="projection_at_rebuild",
            generation=2,
            source_event_seq=30,
        )
    )


def test_provider_rebuild_source_prefix_lower_bound_is_in_digest() -> None:
    earlier = _ready_state()
    later = _ready_state()
    for state, rebuild_event_seq in ((earlier, 30), (later, 31)):
        assert state.reduce_event(
            _provider_event(
                "evt_provider_rebuilding_2",
                generation=2,
                from_state="CLEAN",
                to_state="REBUILDING",
                playback_epoch=1,
                interaction_state_version=1,
                event_seq=rebuild_event_seq,
            )
        )
        assert state.reduce_event(
            _provider_event(
                "evt_provider_clean_2",
                generation=2,
                from_state="REBUILDING",
                to_state="CLEAN",
                event_seq=32,
            )
        )

    assert earlier.to_digest_dict() != later.to_digest_dict()


@pytest.mark.parametrize(
    ("field_name", "mutated_value"),
    (
        ("active_task_ref", "context://synthetic/active/2"),
        ("plan_version", 2),
        ("task_event_seq", 3),
        (
            "pending_confirmation_ref",
            "context://synthetic/confirmation/2",
        ),
    ),
)
def test_context_snapshot_id_rejects_mutated_task_identity(
    field_name: str,
    mutated_value: object,
) -> None:
    module = _module()
    state = _ready_state()
    identity: dict[str, object] = {
        "active_task_ref": "context://synthetic/active/1",
        "plan_version": 1,
        "task_event_seq": 2,
        "pending_confirmation_ref": (
            "context://synthetic/confirmation/1"
        ),
    }
    assert state.reduce_event(
        _projection(
            "evt_projection_route_snapshot_identity",
            role="route_evidence",
            projection_id="projection_route_snapshot_identity",
            **identity,
        )
    )
    mutated_identity = {**identity, field_name: mutated_value}
    before = state.to_digest_dict()

    with pytest.raises(
        module.QwenParallelStateError,
        match="context_snapshot_id",
    ):
        state.reduce_event(
            _projection(
                "evt_projection_safety_snapshot_identity",
                role="candidate_safety",
                projection_id="projection_safety_snapshot_identity",
                **mutated_identity,
            )
        )

    assert state.to_digest_dict() == before


def test_context_snapshot_accepts_bounded_uri_refs_longer_than_safe_token() -> None:
    state = _ready_state()
    long_ref = "context://synthetic/" + "a" * 300

    assert len(long_ref) > 256
    assert state.reduce_event(
        _projection(
            "evt_projection_long_snapshot_refs",
            role="route_evidence",
            projection_id="projection_long_snapshot_refs",
            active_task_ref=long_ref,
            plan_version=1,
            task_event_seq=1,
            pending_confirmation_ref=long_ref,
        )
    )


def test_context_snapshot_identity_is_a_behavioral_digest_input() -> None:
    first = _ready_state()
    second = _ready_state()
    assert first.reduce_event(
        _projection(
            "evt_projection_snapshot_digest",
            role="route_evidence",
            projection_id="projection_snapshot_digest",
            active_task_ref="context://synthetic/active/1",
            plan_version=1,
            task_event_seq=1,
            pending_confirmation_ref=(
                "context://synthetic/confirmation/1"
            ),
        )
    )
    assert second.reduce_event(
        _projection(
            "evt_projection_snapshot_digest",
            role="route_evidence",
            projection_id="projection_snapshot_digest",
            active_task_ref="context://synthetic/active/1",
            plan_version=2,
            task_event_seq=1,
            pending_confirmation_ref=(
                "context://synthetic/confirmation/1"
            ),
        )
    )

    first_digest = first.to_digest_dict()
    second_digest = second.to_digest_dict()

    snapshot_identity = first_digest["authority_state"][
        "context_snapshot_by_id"
    ]["context_snapshot_1"]

    assert {
        key: snapshot_identity[key]
        for key in (
            "provider_session_generation",
            "source_event_seq",
            "active_task_ref",
            "plan_version",
            "task_event_seq",
            "pending_confirmation_ref",
        )
    } == {
        "provider_session_generation": 1,
        "source_event_seq": 10,
        "active_task_ref": "context://synthetic/active/1",
        "plan_version": 1,
        "task_event_seq": 1,
        "pending_confirmation_ref": (
            "context://synthetic/confirmation/1"
        ),
    }
    assert first_digest != second_digest


def test_interrupt_advances_fence_and_matching_truncate_preserves_it() -> None:
    module = _module()
    state = _ready_state()
    legacy_interrupt = _event(
        "INTERRUPT_CANDIDATE",
        "evt_legacy_interrupt",
        playback_span_id="playback_legacy",
    )
    legacy_truncate = _event(
        "TTS_TRUNCATE_REQUESTED",
        "evt_legacy_truncate",
        interrupt_candidate_event_id="evt_legacy_interrupt",
    )
    before = state.to_digest_dict()

    assert state.reduce_event(legacy_interrupt) is False
    assert state.reduce_event(legacy_truncate) is False
    assert state.to_digest_dict() == before

    assert state.reduce_event(
        _event(
            "INTERRUPT_CANDIDATE",
            "evt_interrupt_1",
            playback_epoch=1,
            interaction_state_version=1,
        )
    )
    assert (state.playback_epoch, state.interaction_state_version) == (1, 1)
    assert state.reduce_event(
        _event(
            "TTS_TRUNCATE_REQUESTED",
            "evt_truncate_1",
            interrupt_candidate_event_id="evt_interrupt_1",
            playback_epoch=1,
            interaction_state_version=1,
        )
    )

    with pytest.raises(module.QwenParallelStateError, match="truncate"):
        state.reduce_event(
            _event(
                "TTS_TRUNCATE_REQUESTED",
                "evt_truncate_duplicate",
                interrupt_candidate_event_id="evt_interrupt_1",
                playback_epoch=1,
                interaction_state_version=1,
            )
        )


def test_projection_source_prefix_cannot_cross_interrupt_fence() -> None:
    module = _module()
    state = _ready_state()
    assert state.reduce_event(
        _event(
            "INTERRUPT_CANDIDATE",
            "evt_interrupt_prefix",
            event_seq=20,
            playback_epoch=1,
            interaction_state_version=1,
        )
    )
    assert state.reduce_event(
        _event(
            "TTS_TRUNCATE_REQUESTED",
            "evt_truncate_prefix",
            event_seq=21,
            interrupt_candidate_event_id="evt_interrupt_prefix",
            playback_epoch=1,
            interaction_state_version=1,
        )
    )
    before = state.to_digest_dict()

    with pytest.raises(module.QwenParallelStateError, match="source.*prefix"):
        state.reduce_event(
            _projection(
                "evt_projection_before_interrupt",
                role="route_evidence",
                projection_id="projection_before_interrupt",
                source_event_seq=19,
            )
        )
    assert state.to_digest_dict() == before

    assert state.reduce_event(
        _projection(
            "evt_projection_at_interrupt",
            role="route_evidence",
            projection_id="projection_at_interrupt",
            source_event_seq=20,
        )
    )


def test_interrupt_source_prefix_lower_bound_is_in_digest() -> None:
    earlier = _ready_state()
    later = _ready_state()
    for state, interrupt_event_seq in ((earlier, 20), (later, 21)):
        assert state.reduce_event(
            _event(
                "INTERRUPT_CANDIDATE",
                "evt_interrupt_prefix",
                event_seq=interrupt_event_seq,
                playback_epoch=1,
                interaction_state_version=1,
            )
        )
        assert state.reduce_event(
            _event(
                "TTS_TRUNCATE_REQUESTED",
                "evt_truncate_prefix",
                event_seq=22,
                interrupt_candidate_event_id="evt_interrupt_prefix",
                playback_epoch=1,
                interaction_state_version=1,
            )
        )

    assert earlier.to_digest_dict() != later.to_digest_dict()


def test_duplicate_id_index_supports_more_than_512_owned_fence_events() -> None:
    module = _module()
    state = _ready_state()

    for fence in range(1, 261):
        interrupt_event_id = f"evt_capacity_interrupt_{fence}"
        assert state.reduce_event(
            _event(
                "INTERRUPT_CANDIDATE",
                interrupt_event_id,
                playback_epoch=fence,
                interaction_state_version=fence,
            )
        )
        assert state.reduce_event(
            _event(
                "TTS_TRUNCATE_REQUESTED",
                f"evt_capacity_truncate_{fence}",
                interrupt_candidate_event_id=interrupt_event_id,
                playback_epoch=fence,
                interaction_state_version=fence,
            )
        )

    assert (state.playback_epoch, state.interaction_state_version) == (
        260,
        260,
    )
    before = state.to_digest_dict()
    with pytest.raises(module.QwenParallelStateError, match="duplicate event_id"):
        state.reduce_event(
            _event(
                "INTERRUPT_CANDIDATE",
                "evt_capacity_interrupt_1",
                playback_epoch=261,
                interaction_state_version=261,
            )
        )
    assert state.to_digest_dict() == before


@pytest.mark.parametrize(
    "event",
    (
        _event(
            "INTERRUPT_CANDIDATE",
            "evt_interrupt_partial",
            playback_epoch=1,
        ),
        _event(
            "TTS_TRUNCATE_REQUESTED",
            "evt_truncate_without_interrupt",
            interrupt_candidate_event_id="evt_missing_interrupt",
            playback_epoch=1,
            interaction_state_version=1,
        ),
    ),
)
def test_interrupt_and_truncate_fail_closed(event: dict[str, object]) -> None:
    module = _module()
    state = _ready_state()
    before = state.to_digest_dict()

    with pytest.raises(module.QwenParallelStateError):
        state.reduce_event(event)

    assert state.to_digest_dict() == before


def test_parallel_candidate_chain_tracks_identity_and_discard_terminal() -> None:
    module = _module()
    state = _candidate_state()
    assert state.reduce_event(
        _gate("FOREGROUND_ACT_GATE_FAILED", "evt_gate_failed_1")
    )
    assert state.reduce_event(
        _event(
            "FOREGROUND_OUTPUT_DISCARDED",
            "evt_discard_1",
            fast_interaction_topology=_PARALLEL_TOPOLOGY,
            caused_by_event_id="evt_gate_failed_1",
            candidate_event_id="evt_candidate_1",
            fast_interaction_output_event_id="evt_parallel_fast_1",
        )
    )

    identity = state.candidate_identities["candidate_1"]
    assert identity == module.CandidateReplayIdentityV1(
        provider_session_generation=1,
        context_snapshot_id="context_snapshot_1",
        qwen_response_id="qwen_response_1",
        qwen_output_item_id="qwen_output_item_1",
        qwen_output_index=0,
        qwen_content_index=0,
        candidate_transcript_digest=_TRANSCRIPT_DIGEST,
        candidate_pcm_manifest_digest=_PCM_DIGEST,
    )
    assert state.candidate_dispositions == {"candidate_1": "DISCARDED"}

    before = state.to_digest_dict()
    with pytest.raises(module.QwenParallelStateError, match="terminal"):
        state.reduce_event(
            _event(
                "FOREGROUND_OUTPUT_DISCARDED",
                "evt_discard_duplicate",
                fast_interaction_topology=_PARALLEL_TOPOLOGY,
                caused_by_event_id="evt_gate_failed_1",
                candidate_event_id="evt_candidate_1",
                fast_interaction_output_event_id="evt_parallel_fast_1",
            )
        )
    assert state.to_digest_dict() == before


def test_failed_gate_accepts_safe_token_metadata_but_only_allows_discard() -> None:
    module = _module()
    state = _candidate_state()
    release_ref = (
        "release-token://synthetic/"
        "release_token_0123456789abcdef0123456789abcdef"
    )
    assert state.reduce_event(
        _gate(
            "FOREGROUND_ACT_GATE_FAILED",
            "evt_gate_failed_with_token",
            release_token_ref=release_ref,
        )
    )

    with pytest.raises(module.QwenParallelStateError, match="passed Gate"):
        state.reduce_event(
            _event(
                "FOREGROUND_OUTPUT_COMMITTED",
                "evt_commit_from_failed_gate",
                fast_interaction_topology=_PARALLEL_TOPOLOGY,
                gate_event_id="evt_gate_failed_with_token",
                release_token_ref=release_ref,
            )
        )

    assert state.reduce_event(
        _event(
            "FOREGROUND_OUTPUT_DISCARDED",
            "evt_discard_after_failed_gate_with_token",
            fast_interaction_topology=_PARALLEL_TOPOLOGY,
            caused_by_event_id="evt_gate_failed_with_token",
            candidate_event_id="evt_candidate_1",
            fast_interaction_output_event_id="evt_parallel_fast_1",
        )
    )
    assert state.candidate_dispositions == {"candidate_1": "DISCARDED"}


@pytest.mark.parametrize(
    ("drift", "observed_generation", "observed_state", "observed_fence"),
    (
        pytest.param(
            "tainted",
            1,
            "TAINTED",
            (0, 0),
            id="provider-tainted",
        ),
        pytest.param(
            "interrupt",
            1,
            "CLEAN",
            (1, 1),
            id="interaction-fence-advanced",
        ),
        pytest.param(
            "rebuilding",
            2,
            "REBUILDING",
            (1, 1),
            id="provider-rebuilding",
        ),
    ),
)
def test_failed_gate_records_stale_candidate_context_and_only_discards(
    drift: str,
    observed_generation: int,
    observed_state: str,
    observed_fence: tuple[int, int],
) -> None:
    module = _module()
    state = _candidate_state()
    if drift == "tainted":
        assert state.reduce_event(
            _provider_event(
                "evt_gate_failure_context",
                generation=1,
                from_state="CLEAN",
                to_state="TAINTED",
            )
        )
    elif drift == "interrupt":
        assert state.reduce_event(
            _event(
                "INTERRUPT_CANDIDATE",
                "evt_gate_failure_context",
                playback_epoch=1,
                interaction_state_version=1,
            )
        )
    else:
        assert state.reduce_event(
            _provider_event(
                "evt_gate_failure_context",
                generation=2,
                from_state="CLEAN",
                to_state="REBUILDING",
                playback_epoch=1,
                interaction_state_version=1,
            )
        )

    assert state.reduce_event(
        _gate(
            "FOREGROUND_ACT_GATE_FAILED",
            "evt_gate_failed_after_context_drift",
        )
    )
    gate_binding = state.to_digest_dict()["authority_state"][
        "gate_by_event_id"
    ]["evt_gate_failed_after_context_drift"]
    assert {
        "provider_session_generation": gate_binding[
            "provider_session_generation"
        ],
        "context_snapshot_id": gate_binding["context_snapshot_id"],
        "route_evidence_event_id": gate_binding[
            "route_evidence_event_id"
        ],
        "candidate_safety_evidence_event_id": gate_binding[
            "candidate_safety_evidence_event_id"
        ],
        "candidate_fence": (
            gate_binding["candidate_playback_epoch"],
            gate_binding["candidate_interaction_state_version"],
        ),
        "observed_generation": gate_binding[
            "observed_provider_session_generation"
        ],
        "observed_state": gate_binding[
            "observed_provider_context_state"
        ],
        "observed_fence": (
            gate_binding["observed_playback_epoch"],
            gate_binding["observed_interaction_state_version"],
        ),
    } == {
        "provider_session_generation": 1,
        "context_snapshot_id": "context_snapshot_1",
        "route_evidence_event_id": "evt_route_evidence_1",
        "candidate_safety_evidence_event_id": (
            "evt_candidate_safety_1"
        ),
        "candidate_fence": (0, 0),
        "observed_generation": observed_generation,
        "observed_state": observed_state,
        "observed_fence": observed_fence,
    }

    with pytest.raises(module.QwenParallelStateError, match="passed Gate"):
        state.reduce_event(
            _event(
                "FOREGROUND_OUTPUT_COMMITTED",
                f"evt_commit_after_{drift}_failure",
                fast_interaction_topology=_PARALLEL_TOPOLOGY,
                gate_event_id="evt_gate_failed_after_context_drift",
                release_token_ref=(
                    "release-token://synthetic/"
                    "release_token_0123456789abcdef0123456789abcdef"
                ),
            )
        )

    assert state.reduce_event(
        _event(
            "FOREGROUND_OUTPUT_DISCARDED",
            f"evt_discard_after_{drift}_failure",
            fast_interaction_topology=_PARALLEL_TOPOLOGY,
            caused_by_event_id="evt_gate_failed_after_context_drift",
            candidate_event_id="evt_candidate_1",
            fast_interaction_output_event_id="evt_parallel_fast_1",
        )
    )
    assert state.candidate_dispositions == {"candidate_1": "DISCARDED"}


def test_passed_gate_rejects_tainted_provider_context_without_mutation() -> None:
    module = _module()
    state = _candidate_state()
    assert state.reduce_event(
        _provider_event(
            "evt_provider_tainted_before_passed_gate",
            generation=1,
            from_state="CLEAN",
            to_state="TAINTED",
        )
    )
    before = state.to_digest_dict()

    with pytest.raises(module.QwenParallelStateError, match="CLEAN"):
        state.reduce_event(
            _gate(
                "FOREGROUND_ACT_GATE_PASSED",
                "evt_gate_passed_after_taint",
                release_token_ref=(
                    "release-token://synthetic/"
                    "release_token_0123456789abcdef0123456789abcdef"
                ),
            )
        )

    assert state.to_digest_dict() == before


def test_failed_gate_rejects_unsafe_optional_token_metadata() -> None:
    module = _module()
    state = _candidate_state()
    before = state.to_digest_dict()

    with pytest.raises(module.QwenParallelStateError, match="release"):
        state.reduce_event(
            _gate(
                "FOREGROUND_ACT_GATE_FAILED",
                "evt_gate_failed_with_unsafe_token",
                release_token_ref=(
                    "release-token://synthetic/release_token_not_hex"
                ),
            )
        )

    assert state.to_digest_dict() == before


def test_parallel_gate_commit_resolves_candidate_through_gate_event() -> None:
    module = _module()
    state = _candidate_state()
    release_ref = (
        "release-token://synthetic/"
        "release_token_0123456789abcdef0123456789abcdef"
    )
    assert state.reduce_event(
        _gate(
            "FOREGROUND_ACT_GATE_PASSED",
            "evt_gate_passed_1",
            release_token_ref=release_ref,
        )
    )
    assert state.reduce_event(
        _event(
            "FOREGROUND_OUTPUT_COMMITTED",
            "evt_commit_1",
            fast_interaction_topology=_PARALLEL_TOPOLOGY,
            gate_event_id="evt_gate_passed_1",
            release_token_ref=release_ref,
        )
    )
    assert state.candidate_dispositions == {"candidate_1": "COMMITTED"}

    before = state.to_digest_dict()
    with pytest.raises(module.QwenParallelStateError, match="release"):
        state.reduce_event(
            _event(
                "FOREGROUND_OUTPUT_COMMITTED",
                "evt_commit_forged",
                fast_interaction_topology=_PARALLEL_TOPOLOGY,
                gate_event_id="evt_gate_passed_1",
                release_token_ref=(
                    "release-token://synthetic/"
                    "release_token_fedcba9876543210fedcba9876543210"
                ),
            )
        )
    assert state.to_digest_dict() == before


def test_old_generation_gate_cannot_commit_after_provider_rebuild() -> None:
    module = _module()
    state = _candidate_state()
    release_ref = (
        "release-token://synthetic/"
        "release_token_0123456789abcdef0123456789abcdef"
    )
    assert state.reduce_event(
        _gate(
            "FOREGROUND_ACT_GATE_PASSED",
            "evt_gate_passed_before_rebuild",
            release_token_ref=release_ref,
        )
    )
    assert state.reduce_event(
        _provider_event(
            "evt_provider_rebuilding_2",
            generation=2,
            from_state="CLEAN",
            to_state="REBUILDING",
            playback_epoch=1,
            interaction_state_version=1,
        )
    )
    assert state.reduce_event(
        _provider_event(
            "evt_provider_clean_2",
            generation=2,
            from_state="REBUILDING",
            to_state="CLEAN",
        )
    )
    before = state.to_digest_dict()

    with pytest.raises(module.QwenParallelStateError, match="generation"):
        state.reduce_event(
            _event(
                "FOREGROUND_OUTPUT_COMMITTED",
                "evt_stale_generation_commit",
                fast_interaction_topology=_PARALLEL_TOPOLOGY,
                gate_event_id="evt_gate_passed_before_rebuild",
                release_token_ref=release_ref,
            )
        )

    assert state.to_digest_dict() == before
    assert state.candidate_dispositions == {}


def test_gate_pass_cannot_commit_after_interrupt_advances_fence() -> None:
    module = _module()
    state = _candidate_state()
    release_ref = (
        "release-token://synthetic/"
        "release_token_0123456789abcdef0123456789abcdef"
    )
    assert state.reduce_event(
        _gate(
            "FOREGROUND_ACT_GATE_PASSED",
            "evt_gate_passed_before_interrupt",
            release_token_ref=release_ref,
        )
    )
    assert state.reduce_event(
        _event(
            "INTERRUPT_CANDIDATE",
            "evt_interrupt_after_gate",
            playback_epoch=1,
            interaction_state_version=1,
        )
    )
    before = state.to_digest_dict()

    with pytest.raises(module.QwenParallelStateError, match="fence"):
        state.reduce_event(
            _event(
                "FOREGROUND_OUTPUT_COMMITTED",
                "evt_stale_fence_commit",
                fast_interaction_topology=_PARALLEL_TOPOLOGY,
                gate_event_id="evt_gate_passed_before_interrupt",
                release_token_ref=release_ref,
            )
        )

    assert state.to_digest_dict() == before
    assert state.candidate_dispositions == {}


def test_candidate_cannot_reach_gate_after_interrupt_advances_fence() -> None:
    module = _module()
    state = _candidate_state()
    assert state.reduce_event(
        _event(
            "INTERRUPT_CANDIDATE",
            "evt_interrupt_after_candidate",
            playback_epoch=1,
            interaction_state_version=1,
        )
    )
    before = state.to_digest_dict()

    with pytest.raises(module.QwenParallelStateError, match="fence"):
        state.reduce_event(
            _gate(
                "FOREGROUND_ACT_GATE_PASSED",
                "evt_gate_for_stale_candidate",
                release_token_ref=(
                    "release-token://synthetic/"
                    "release_token_0123456789abcdef0123456789abcdef"
                ),
            )
        )

    assert state.to_digest_dict() == before
    assert state.candidate_dispositions == {}


def test_parallel_fast_output_cannot_emit_candidate_after_fence_advances() -> None:
    module = _module()
    state = _ready_state()
    prefix_events = (
        _projection(
            "evt_projection_route_1",
            role="route_evidence",
            projection_id="projection_route_1",
        ),
        _route_evidence(),
        _projection(
            "evt_projection_safety_1",
            role="candidate_safety",
            projection_id="projection_safety_1",
        ),
        _candidate_safety(),
        _parallel_fast_output(),
    )
    assert all(state.reduce_event(event) for event in prefix_events)
    assert state.reduce_event(
        _event(
            "INTERRUPT_CANDIDATE",
            "evt_interrupt_after_parallel_fast",
            playback_epoch=1,
            interaction_state_version=1,
        )
    )
    before = state.to_digest_dict()

    with pytest.raises(module.QwenParallelStateError, match="fence"):
        state.reduce_event(_candidate())

    assert state.to_digest_dict() == before
    assert state.candidate_identities == {}


def test_parallel_fast_output_rejects_pre_interrupt_candidate_safety() -> None:
    module = _module()
    state = _ready_state()
    assert state.reduce_event(
        _projection(
            "evt_projection_safety_1",
            role="candidate_safety",
            projection_id="projection_safety_1",
        )
    )
    assert state.reduce_event(_candidate_safety())
    assert state.reduce_event(
        _event(
            "INTERRUPT_CANDIDATE",
            "evt_interrupt_after_safety",
            playback_epoch=1,
            interaction_state_version=1,
        )
    )
    assert state.reduce_event(
        _event(
            "TTS_TRUNCATE_REQUESTED",
            "evt_truncate_after_safety",
            interrupt_candidate_event_id="evt_interrupt_after_safety",
            playback_epoch=1,
            interaction_state_version=1,
        )
    )
    assert state.reduce_event(
        _projection(
            "evt_projection_route_1",
            role="route_evidence",
            projection_id="projection_route_1",
            snapshot_id="context_snapshot_2",
        )
    )
    assert state.reduce_event(_route_evidence())
    before = state.to_digest_dict()

    with pytest.raises(
        module.QwenParallelStateError,
        match="candidate safety.*fence",
    ):
        state.reduce_event(
            _parallel_fast_output(snapshot_id="context_snapshot_2")
        )

    assert state.to_digest_dict() == before


def test_parallel_fast_output_rejects_pre_interrupt_route_evidence() -> None:
    module = _module()
    state = _ready_state()
    assert state.reduce_event(
        _projection(
            "evt_projection_route_1",
            role="route_evidence",
            projection_id="projection_route_1",
        )
    )
    assert state.reduce_event(_route_evidence())
    assert state.reduce_event(
        _event(
            "INTERRUPT_CANDIDATE",
            "evt_interrupt_after_route",
            playback_epoch=1,
            interaction_state_version=1,
        )
    )
    assert state.reduce_event(
        _event(
            "TTS_TRUNCATE_REQUESTED",
            "evt_truncate_after_route",
            interrupt_candidate_event_id="evt_interrupt_after_route",
            playback_epoch=1,
            interaction_state_version=1,
        )
    )
    assert state.reduce_event(
        _projection(
            "evt_projection_safety_1",
            role="candidate_safety",
            projection_id="projection_safety_1",
            snapshot_id="context_snapshot_2",
        )
    )
    assert state.reduce_event(_candidate_safety())
    before = state.to_digest_dict()

    with pytest.raises(
        module.QwenParallelStateError,
        match="route evidence.*fence",
    ):
        state.reduce_event(
            _parallel_fast_output(snapshot_id="context_snapshot_2")
        )

    assert state.to_digest_dict() == before


@pytest.mark.parametrize(
    ("request_id", "turn_id", "final_asr_event_id"),
    (
        pytest.param(
            "route_request_2",
            "turn_1",
            "evt_final_asr_2",
            id="same-turn",
        ),
        pytest.param(
            "route_request_2",
            "turn_2",
            "evt_final_asr_1",
            id="same-final-asr",
        ),
        pytest.param(
            "route_request_1",
            "turn_2",
            "evt_final_asr_2",
            id="same-request",
        ),
    ),
)
def test_route_evidence_allows_one_terminal_per_owned_correlation(
    request_id: str,
    turn_id: str,
    final_asr_event_id: str,
) -> None:
    module = _module()
    state = _ready_state()
    assert state.reduce_event(
        _projection(
            "evt_projection_route_1",
            role="route_evidence",
            projection_id="projection_route_1",
        )
    )
    assert state.reduce_event(_route_evidence())
    before = state.to_digest_dict()

    with pytest.raises(
        module.QwenParallelStateError,
        match="route evidence.*terminal|route evidence.*correlation",
    ):
        state.reduce_event(
            _route_evidence(
                "evt_route_evidence_2",
                request_id=request_id,
                turn_id=turn_id,
                final_asr_event_id=final_asr_event_id,
            )
        )

    assert state.to_digest_dict() == before


@pytest.mark.parametrize(
    ("request_id", "response_id", "transcript_digest", "decision"),
    (
        pytest.param(
            "candidate_safety_request_2",
            "qwen_response_1",
            _TRANSCRIPT_DIGEST,
            "UNSAFE",
            id="conflicting-terminal-for-response",
        ),
        pytest.param(
            "candidate_safety_request_1",
            "qwen_response_2",
            "sha256:" + "9" * 64,
            "UNSAFE",
            id="same-request",
        ),
        pytest.param(
            "candidate_safety_request_2",
            "qwen_response_1",
            "sha256:" + "9" * 64,
            "UNSAFE",
            id="same-response-different-digest",
        ),
    ),
)
def test_candidate_safety_allows_one_terminal_per_owned_correlation(
    request_id: str,
    response_id: str,
    transcript_digest: str,
    decision: str,
) -> None:
    module = _module()
    state = _ready_state()
    assert state.reduce_event(
        _projection(
            "evt_projection_safety_1",
            role="candidate_safety",
            projection_id="projection_safety_1",
        )
    )
    assert state.reduce_event(_candidate_safety())
    before = state.to_digest_dict()

    with pytest.raises(
        module.QwenParallelStateError,
        match="candidate safety.*terminal|candidate safety.*correlation",
    ):
        state.reduce_event(
            _candidate_safety(
                "evt_candidate_safety_2",
                request_id=request_id,
                response_id=response_id,
                transcript_digest=transcript_digest,
                decision=decision,
            )
        )

    assert state.to_digest_dict() == before


def test_evidence_terminal_indexes_are_behavioral_digest_inputs() -> None:
    state = _candidate_state()
    authority = state.to_digest_dict()["authority_state"]

    assert authority["route_terminal_by_turn"] == {
        "turn_1": "evt_route_evidence_1"
    }
    assert authority["route_terminal_by_final_asr"] == {
        "evt_final_asr_1": "evt_route_evidence_1"
    }
    assert authority["route_terminal_by_request"] == {
        "route_request_1": "evt_route_evidence_1"
    }
    assert authority["candidate_safety_terminal_by_response"] == {
        "qwen_response_1": "evt_candidate_safety_1"
    }
    assert authority["candidate_safety_terminal_by_request"] == {
        "candidate_safety_request_1": "evt_candidate_safety_1"
    }
    assert authority["candidate_safety_by_event_id"][
        "evt_candidate_safety_1"
    ]["decision"] == "SAFE"


def test_candidate_safety_terminal_may_precede_route_terminal() -> None:
    state = _ready_state()
    events = (
        _projection(
            "evt_projection_safety_1",
            role="candidate_safety",
            projection_id="projection_safety_1",
        ),
        _candidate_safety(),
        _projection(
            "evt_projection_route_1",
            role="route_evidence",
            projection_id="projection_route_1",
        ),
        _route_evidence(),
        _parallel_fast_output(),
    )

    assert all(state.reduce_event(event) for event in events)


@pytest.mark.parametrize(
    ("role", "projection_id", "projection_event_id", "evidence_event"),
    (
        (
            "route_evidence",
            "projection_route_stale",
            "evt_projection_route_stale",
            _route_evidence(
                event_id="evt_route_evidence_from_stale_projection",
                projection_event_id="evt_projection_route_stale",
            ),
        ),
        (
            "candidate_safety",
            "projection_safety_stale",
            "evt_projection_safety_stale",
            _candidate_safety(
                event_id="evt_safety_from_stale_projection",
                projection_event_id="evt_projection_safety_stale",
            ),
        ),
    ),
)
def test_evidence_rejects_projection_created_before_interrupt(
    role: str,
    projection_id: str,
    projection_event_id: str,
    evidence_event: dict[str, object],
) -> None:
    module = _module()
    state = _ready_state()
    assert state.reduce_event(
        _projection(
            projection_event_id,
            role=role,
            projection_id=projection_id,
        )
    )
    assert state.reduce_event(
        _event(
            "INTERRUPT_CANDIDATE",
            f"evt_interrupt_after_{role}_projection",
            playback_epoch=1,
            interaction_state_version=1,
        )
    )
    assert state.reduce_event(
        _event(
            "TTS_TRUNCATE_REQUESTED",
            f"evt_truncate_after_{role}_projection",
            interrupt_candidate_event_id=(
                f"evt_interrupt_after_{role}_projection"
            ),
            playback_epoch=1,
            interaction_state_version=1,
        )
    )
    before = state.to_digest_dict()

    with pytest.raises(
        module.QwenParallelStateError,
        match="projection fence",
    ):
        state.reduce_event(evidence_event)

    assert state.to_digest_dict() == before


@pytest.mark.parametrize(
    ("mutation", "error_match"),
    (
        ({"provider_session_generation": 2}, "generation"),
        ({"context_snapshot_id": "context_snapshot_other"}, "snapshot"),
        ({"candidate_transcript_digest": "sha256:" + "9" * 64}, "digest"),
        ({"qwen_output_index": -1}, "index"),
    ),
)
def test_parallel_candidate_identity_mismatch_fails_closed(
    mutation: dict[str, object],
    error_match: str,
) -> None:
    module = _module()
    state = _ready_state()
    prefix_events = (
        _projection(
            "evt_projection_route_1",
            role="route_evidence",
            projection_id="projection_route_1",
        ),
        _route_evidence(),
        _projection(
            "evt_projection_safety_1",
            role="candidate_safety",
            projection_id="projection_safety_1",
        ),
        _candidate_safety(),
        _parallel_fast_output(),
    )
    assert all(state.reduce_event(event) for event in prefix_events)
    candidate = _candidate()
    candidate.update(mutation)
    before = state.to_digest_dict()

    with pytest.raises(module.QwenParallelStateError, match=error_match):
        state.reduce_event(candidate)

    assert state.to_digest_dict() == before


def test_all_adr018_event_types_are_owned_and_terminal_maps_are_unique() -> None:
    module = _module()
    state = _candidate_state()
    assert state.reduce_event(
        _event(
            "CANDIDATE_AUDIO_SHADOW_VERIFICATION_EMITTED",
            "evt_shadow_1",
            qwen_response_id="qwen_response_1",
            candidate_transcript_digest=_TRANSCRIPT_DIGEST,
            candidate_pcm_manifest_digest=_PCM_DIGEST,
        )
    )
    assert state.reduce_event(
        _handoff()
    )
    assert state.reduce_event(
        _event(
            "SLOW_TO_FAST_HANDOFF_DISPOSITIONED",
            "evt_handoff_queued_1",
            handoff_id="handoff_1",
            disposition="QUEUED",
        )
    )
    assert state.reduce_event(
        _event(
            "RESPONSE_ARBITRATION_DECIDED",
            "evt_arbitration_1",
            arbitration_id="arbitration_1",
            selected_source_type="progress",
            selected_source_event_id="evt_handoff_1",
            superseded_source_event_ids=(),
            provider_session_generation=1,
            playback_epoch=0,
            interaction_state_version=0,
        )
    )
    assert state.reduce_event(
        _event(
            "SLOW_TO_FAST_HANDOFF_DISPOSITIONED",
            "evt_handoff_selected_1",
            handoff_id="handoff_1",
            disposition="SELECTED",
            response_arbitration_event_id="evt_arbitration_1",
            current_task_id="task_1",
            current_plan_version=1,
            current_task_event_seq=1,
        )
    )
    assert state.reduce_event(
        _event(
            "ASSISTANT_DELIVERY_DISPOSITIONED",
            "evt_delivery_1",
            assistant_item_ref="assistant_item_1",
            source_output_event_id="evt_commit_prior",
            from_status="PENDING",
            to_status="NOT_STARTED",
        )
    )

    assert state.shadow_verification_event_ids == ("evt_shadow_1",)
    assert state.response_arbitration_event_ids == ("evt_arbitration_1",)
    assert state.handoff_dispositions == {"handoff_1": "SELECTED"}
    assert state.assistant_delivery_dispositions == {
        "assistant_item_1": "NOT_STARTED"
    }

    before = state.to_digest_dict()
    with pytest.raises(module.QwenParallelStateError, match="terminal"):
        state.reduce_event(
            _event(
                "SLOW_TO_FAST_HANDOFF_DISPOSITIONED",
                "evt_handoff_terminal_duplicate",
                handoff_id="handoff_1",
                disposition="STALE",
            )
        )
    assert state.to_digest_dict() == before

    with pytest.raises(module.QwenParallelStateError, match="terminal"):
        state.reduce_event(
            _event(
                "ASSISTANT_DELIVERY_DISPOSITIONED",
                "evt_delivery_duplicate",
                assistant_item_ref="assistant_item_1",
                source_output_event_id="evt_commit_prior",
                from_status="PENDING",
                to_status="FULL",
            )
        )
    assert state.to_digest_dict() == before


def test_handoff_selection_requires_matching_prior_arbitration() -> None:
    module = _module()
    state = _ready_state()
    assert state.reduce_event(_handoff())
    before = state.to_digest_dict()

    with pytest.raises(module.QwenParallelStateError, match="arbitration"):
        state.reduce_event(
            _event(
                "SLOW_TO_FAST_HANDOFF_DISPOSITIONED",
                "evt_handoff_selected_without_arbitration",
                handoff_id="handoff_1",
                disposition="SELECTED",
                response_arbitration_event_id="evt_missing_arbitration",
                current_task_id="task_1",
                current_plan_version=1,
                current_task_event_seq=1,
            )
        )

    assert state.to_digest_dict() == before


@pytest.mark.parametrize(
    ("kind", "selected_source_type"),
    (
        ("PROGRESS", "progress"),
        ("CLARIFICATION", "clarification"),
        ("CONFIRMATION", "confirmation"),
        ("FINAL", "final"),
        ("DEGRADED", "final"),
        ("FAILED", "final"),
    ),
)
def test_handoff_selection_accepts_kind_compatible_arbitration_source(
    kind: str,
    selected_source_type: str,
) -> None:
    state = _ready_state()
    handoff_id = f"handoff_{kind.lower()}"
    handoff_event_id = f"evt_handoff_{kind.lower()}"
    assert state.reduce_event(
        _handoff(
            handoff_event_id,
            handoff_id=handoff_id,
            kind=kind,
        )
    )
    assert state.reduce_event(
        _event(
            "RESPONSE_ARBITRATION_DECIDED",
            f"evt_arbitration_{kind.lower()}",
            arbitration_id=f"arbitration_{kind.lower()}",
            selected_source_type=selected_source_type,
            selected_source_event_id=handoff_event_id,
            superseded_source_event_ids=(),
            provider_session_generation=1,
            playback_epoch=0,
            interaction_state_version=0,
        )
    )

    assert state.reduce_event(
        _event(
            "SLOW_TO_FAST_HANDOFF_DISPOSITIONED",
            f"evt_handoff_selected_{kind.lower()}",
            handoff_id=handoff_id,
            disposition="SELECTED",
            response_arbitration_event_id=(
                f"evt_arbitration_{kind.lower()}"
            ),
            current_task_id="task_1",
            current_plan_version=1,
            current_task_event_seq=1,
        )
    )
    assert state.handoff_dispositions[handoff_id] == "SELECTED"


@pytest.mark.parametrize(
    ("kind", "wrong_source_type"),
    (
        ("PROGRESS", "final"),
        ("CLARIFICATION", "progress"),
        ("CONFIRMATION", "clarification"),
        ("FINAL", "progress"),
        ("DEGRADED", "confirmation"),
        ("FAILED", "clarification"),
    ),
)
def test_handoff_selection_rejects_kind_incompatible_arbitration_source(
    kind: str,
    wrong_source_type: str,
) -> None:
    module = _module()
    state = _ready_state()
    handoff_id = f"handoff_{kind.lower()}"
    handoff_event_id = f"evt_handoff_{kind.lower()}"
    assert state.reduce_event(
        _handoff(
            handoff_event_id,
            handoff_id=handoff_id,
            kind=kind,
        )
    )
    before = state.to_digest_dict()

    with pytest.raises(
        module.QwenParallelStateError,
        match="source type|kind",
    ):
        state.reduce_event(
            _arbitration(
                f"evt_arbitration_wrong_{kind.lower()}",
                arbitration_id=f"arbitration_wrong_{kind.lower()}",
                selected_source_type=wrong_source_type,
                selected_source_event_id=handoff_event_id,
            )
        )

    assert state.to_digest_dict() == before
    assert handoff_id not in state.handoff_dispositions


@pytest.mark.parametrize(
    ("selected_source_type", "selected_source_event_id"),
    (
        pytest.param(
            "none",
            "evt_candidate_1",
            id="none-with-source",
        ),
        pytest.param(
            "user_fast",
            None,
            id="user-fast-without-source",
        ),
        pytest.param(
            "progress",
            None,
            id="handoff-without-source",
        ),
        pytest.param(
            "progress",
            "evt_unknown_handoff",
            id="unknown-handoff",
        ),
        pytest.param(
            "user_fast",
            "evt_unknown_fast_authority",
            id="unknown-user-fast",
        ),
    ),
)
def test_arbitration_rejects_missing_unknown_or_none_mismatched_source(
    selected_source_type: str,
    selected_source_event_id: str | None,
) -> None:
    module = _module()
    state = _candidate_state()
    before = state.to_digest_dict()

    with pytest.raises(
        module.QwenParallelStateError,
        match="selected source|user_fast|handoff",
    ):
        state.reduce_event(
            _arbitration(
                "evt_arbitration_invalid_source",
                arbitration_id="arbitration_invalid_source",
                selected_source_type=selected_source_type,
                selected_source_event_id=selected_source_event_id,
            )
        )

    assert state.to_digest_dict() == before


@pytest.mark.parametrize(
    "authority_kind",
    ("live_candidate", "passed_gate", "committed_output"),
)
def test_user_fast_arbitration_accepts_known_eligible_authority(
    authority_kind: str,
) -> None:
    state = _candidate_state()
    source_event_id = "evt_candidate_1"
    if authority_kind in {"passed_gate", "committed_output"}:
        assert state.reduce_event(
            _gate(
                "FOREGROUND_ACT_GATE_PASSED",
                "evt_gate_passed_for_arbitration",
                release_token_ref=_RELEASE_REF,
            )
        )
        source_event_id = "evt_gate_passed_for_arbitration"
    if authority_kind == "committed_output":
        assert state.reduce_event(
            _event(
                "FOREGROUND_OUTPUT_COMMITTED",
                "evt_commit_for_arbitration",
                fast_interaction_topology=_PARALLEL_TOPOLOGY,
                gate_event_id="evt_gate_passed_for_arbitration",
                release_token_ref=_RELEASE_REF,
            )
        )
        source_event_id = "evt_commit_for_arbitration"

    assert state.reduce_event(
        _arbitration(
            f"evt_arbitration_{authority_kind}",
            arbitration_id=f"arbitration_{authority_kind}",
            selected_source_type="user_fast",
            selected_source_event_id=source_event_id,
        )
    )


@pytest.mark.parametrize(
    "delivery_status",
    ("FULL", "TRUNCATED", "NOT_STARTED"),
)
@pytest.mark.parametrize(
    ("authority_kind", "source_event_id"),
    (
        ("candidate", "evt_candidate_1"),
        ("passed_gate", "evt_gate_passed_for_delivery"),
        ("committed_output", "evt_commit_for_delivery"),
    ),
)
def test_delivery_terminal_retires_all_user_fast_authority_stages(
    delivery_status: str,
    authority_kind: str,
    source_event_id: str,
) -> None:
    module = _module()
    state = _committed_candidate_state()
    assert state.reduce_event(
        _event(
            "ASSISTANT_DELIVERY_DISPOSITIONED",
            f"evt_delivery_{delivery_status.lower()}",
            assistant_item_ref="assistant_item_delivery_1",
            source_output_event_id="evt_commit_for_delivery",
            from_status="PENDING",
            to_status=delivery_status,
        )
    )
    before = state.to_digest_dict()

    with pytest.raises(
        module.QwenParallelStateError,
        match="user_fast",
    ):
        state.reduce_event(
            _arbitration(
                f"evt_arbitration_retired_{authority_kind}",
                arbitration_id=f"arbitration_retired_{authority_kind}",
                selected_source_type="user_fast",
                selected_source_event_id=source_event_id,
            )
        )

    assert state.to_digest_dict() == before


def test_committed_output_is_selectable_before_delivery_terminal() -> None:
    state = _committed_candidate_state()

    assert state.reduce_event(
        _arbitration(
            "evt_arbitration_before_delivery",
            arbitration_id="arbitration_before_delivery",
            selected_source_type="user_fast",
            selected_source_event_id="evt_commit_for_delivery",
        )
    )


@pytest.mark.parametrize(
    "delivery_status",
    ("FULL", "TRUNCATED", "NOT_STARTED"),
)
def test_none_arbitration_after_delivery_keeps_retired_audit_refs(
    delivery_status: str,
) -> None:
    state = _committed_candidate_state()
    retired_ids = (
        "evt_candidate_1",
        "evt_commit_for_delivery",
        "evt_gate_passed_for_delivery",
    )
    assert state.reduce_event(
        _event(
            "ASSISTANT_DELIVERY_DISPOSITIONED",
            f"evt_delivery_none_{delivery_status.lower()}",
            assistant_item_ref="assistant_item_delivery_1",
            source_output_event_id="evt_commit_for_delivery",
            from_status="PENDING",
            to_status=delivery_status,
        )
    )
    assert state.reduce_event(
        _arbitration(
            f"evt_arbitration_none_{delivery_status.lower()}",
            arbitration_id=(
                f"arbitration_none_{delivery_status.lower()}"
            ),
            selected_source_type="none",
            superseded_source_event_ids=retired_ids,
        )
    )

    assert state.to_digest_dict()["authority_state"][
        "retired_user_fast_authority_event_ids"
    ] == tuple(sorted(retired_ids))


@pytest.mark.parametrize(
    "authority_kind",
    ("failed_candidate", "failed_gate", "discarded_output"),
)
def test_user_fast_arbitration_rejects_failed_or_discarded_authority(
    authority_kind: str,
) -> None:
    module = _module()
    state = _candidate_state()
    assert state.reduce_event(
        _gate(
            "FOREGROUND_ACT_GATE_FAILED",
            "evt_gate_failed_for_arbitration",
        )
    )
    source_event_id = (
        "evt_candidate_1"
        if authority_kind == "failed_candidate"
        else "evt_gate_failed_for_arbitration"
    )
    if authority_kind == "discarded_output":
        assert state.reduce_event(
            _event(
                "FOREGROUND_OUTPUT_DISCARDED",
                "evt_discard_for_arbitration",
                fast_interaction_topology=_PARALLEL_TOPOLOGY,
                caused_by_event_id="evt_gate_failed_for_arbitration",
                candidate_event_id="evt_candidate_1",
                fast_interaction_output_event_id="evt_parallel_fast_1",
            )
        )
        source_event_id = "evt_discard_for_arbitration"
    before = state.to_digest_dict()

    with pytest.raises(
        module.QwenParallelStateError,
        match="user_fast",
    ):
        state.reduce_event(
            _arbitration(
                f"evt_arbitration_reject_{authority_kind}",
                arbitration_id=f"arbitration_reject_{authority_kind}",
                selected_source_type="user_fast",
                selected_source_event_id=source_event_id,
            )
        )

    assert state.to_digest_dict() == before


def test_arbitration_rejects_unknown_superseded_authority() -> None:
    module = _module()
    state = _ready_state()
    before = state.to_digest_dict()

    with pytest.raises(
        module.QwenParallelStateError,
        match="superseded.*authority",
    ):
        state.reduce_event(
            _arbitration(
                "evt_arbitration_unknown_supersession",
                arbitration_id="arbitration_unknown_supersession",
                selected_source_type="none",
                superseded_source_event_ids=("evt_unknown_authority",),
            )
        )

    assert state.to_digest_dict() == before


def test_arbitration_cannot_select_and_supersede_same_authority() -> None:
    module = _module()
    state = _candidate_state()
    before = state.to_digest_dict()

    with pytest.raises(
        module.QwenParallelStateError,
        match="selected.*superseded",
    ):
        state.reduce_event(
            _arbitration(
                "evt_arbitration_self_supersession",
                arbitration_id="arbitration_self_supersession",
                selected_source_type="user_fast",
                selected_source_event_id="evt_candidate_1",
                superseded_source_event_ids=("evt_candidate_1",),
            )
        )

    assert state.to_digest_dict() == before


def test_expired_handoff_cannot_be_arbitration_selected_and_only_expires() -> None:
    module = _module()
    state = _ready_state()
    assert state.reduce_event(_handoff(expiry_status="EXPIRED"))
    before = state.to_digest_dict()

    with pytest.raises(module.QwenParallelStateError, match="expired"):
        state.reduce_event(
            _event(
                "RESPONSE_ARBITRATION_DECIDED",
                "evt_arbitration_expired",
                arbitration_id="arbitration_expired",
                selected_source_type="progress",
                selected_source_event_id="evt_handoff_1",
                superseded_source_event_ids=(),
                provider_session_generation=1,
                playback_epoch=0,
                interaction_state_version=0,
            )
        )
    assert state.to_digest_dict() == before

    with pytest.raises(
        module.QwenParallelStateError,
        match="EXPIRED handoff.*EXPIRED disposition",
    ):
        state.reduce_event(
            _event(
                "SLOW_TO_FAST_HANDOFF_DISPOSITIONED",
                "evt_handoff_expired_queued",
                handoff_id="handoff_1",
                disposition="QUEUED",
            )
        )
    assert state.to_digest_dict() == before

    assert state.reduce_event(
        _event(
            "SLOW_TO_FAST_HANDOFF_DISPOSITIONED",
            "evt_handoff_expired",
            handoff_id="handoff_1",
            disposition="EXPIRED",
        )
    )
    assert state.handoff_dispositions == {"handoff_1": "EXPIRED"}


@pytest.mark.parametrize(
    ("current_identity", "error_match"),
    (
        pytest.param({}, "current_task_id", id="missing-current-identity"),
        pytest.param(
            {
                "current_task_id": "task_2",
                "current_plan_version": 1,
                "current_task_event_seq": 1,
            },
            "current task identity",
            id="task-mismatch",
        ),
        pytest.param(
            {
                "current_task_id": "task_1",
                "current_plan_version": 2,
                "current_task_event_seq": 1,
            },
            "current task identity",
            id="plan-mismatch",
        ),
        pytest.param(
            {
                "current_task_id": "task_1",
                "current_plan_version": 1,
                "current_task_event_seq": 2,
            },
            "current task identity",
            id="sequence-mismatch",
        ),
    ),
)
def test_selected_handoff_requires_exact_current_task_identity(
    current_identity: dict[str, object],
    error_match: str,
) -> None:
    module = _module()
    state = _ready_state()
    assert state.reduce_event(_handoff())
    assert state.reduce_event(
        _event(
            "RESPONSE_ARBITRATION_DECIDED",
            "evt_arbitration_1",
            arbitration_id="arbitration_1",
            selected_source_type="progress",
            selected_source_event_id="evt_handoff_1",
            superseded_source_event_ids=(),
            provider_session_generation=1,
            playback_epoch=0,
            interaction_state_version=0,
        )
    )
    before = state.to_digest_dict()

    with pytest.raises(module.QwenParallelStateError, match=error_match):
        state.reduce_event(
            _event(
                "SLOW_TO_FAST_HANDOFF_DISPOSITIONED",
                "evt_handoff_selected_1",
                handoff_id="handoff_1",
                disposition="SELECTED",
                response_arbitration_event_id="evt_arbitration_1",
                **current_identity,
            )
        )

    assert state.to_digest_dict() == before


@pytest.mark.parametrize(
    ("current_identity", "should_accept", "error_match"),
    (
        pytest.param({}, False, "current_task_id", id="missing-current-identity"),
        pytest.param(
            {
                "current_task_id": "task_1",
                "current_plan_version": 1,
                "current_task_event_seq": 1,
            },
            False,
            "identity mismatch",
            id="exact-emitted-identity",
        ),
        pytest.param(
            {
                "current_task_id": "task_1",
                "current_plan_version": 2,
                "current_task_event_seq": 1,
            },
            True,
            None,
            id="plan-mismatch",
        ),
    ),
)
def test_stale_handoff_requires_complete_mismatching_current_identity(
    current_identity: dict[str, object],
    should_accept: bool,
    error_match: str | None,
) -> None:
    module = _module()
    state = _ready_state()
    assert state.reduce_event(_handoff())
    event = _event(
        "SLOW_TO_FAST_HANDOFF_DISPOSITIONED",
        "evt_handoff_stale_1",
        handoff_id="handoff_1",
        disposition="STALE",
        **current_identity,
    )

    if should_accept:
        assert state.reduce_event(event)
        assert state.handoff_dispositions == {"handoff_1": "STALE"}
        return

    before = state.to_digest_dict()
    with pytest.raises(module.QwenParallelStateError, match=error_match):
        state.reduce_event(event)
    assert state.to_digest_dict() == before


def test_handoff_identity_and_expiry_are_behavioral_digest_inputs() -> None:
    current = _ready_state()
    expired = _ready_state()
    other_plan = _ready_state()

    assert current.reduce_event(_handoff())
    assert expired.reduce_event(_handoff(expiry_status="EXPIRED"))
    assert other_plan.reduce_event(_handoff(plan_version=2))

    assert current.to_digest_dict() != expired.to_digest_dict()
    assert current.to_digest_dict() != other_plan.to_digest_dict()


def test_coalesced_handoff_rejects_expired_terminal_replacement() -> None:
    module = _module()
    state = _ready_state()
    assert state.reduce_event(_handoff())
    assert state.reduce_event(
        _handoff(
            "evt_handoff_2",
            handoff_id="handoff_2",
            expiry_status="EXPIRED",
            task_event_seq=2,
        )
    )
    assert state.reduce_event(
        _event(
            "SLOW_TO_FAST_HANDOFF_DISPOSITIONED",
            "evt_handoff_2_expired",
            handoff_id="handoff_2",
            disposition="EXPIRED",
        )
    )
    before = state.to_digest_dict()

    with pytest.raises(
        module.QwenParallelStateError,
        match="coalesced.*CURRENT|replacement.*eligible",
    ):
        state.reduce_event(
            _event(
                "SLOW_TO_FAST_HANDOFF_DISPOSITIONED",
                "evt_handoff_1_coalesced",
                handoff_id="handoff_1",
                disposition="COALESCED",
                replacement_handoff_id="handoff_2",
            )
        )

    assert state.to_digest_dict() == before


def test_coalesced_handoff_replacement_must_be_emitted_later() -> None:
    module = _module()
    state = _ready_state()
    assert state.reduce_event(
        _handoff(
            "evt_handoff_2",
            handoff_id="handoff_2",
            task_event_seq=2,
        )
    )
    assert state.reduce_event(_handoff(task_event_seq=1))
    before = state.to_digest_dict()

    with pytest.raises(
        module.QwenParallelStateError,
        match="coalesced.*replacement.*later",
    ):
        state.reduce_event(
            _event(
                "SLOW_TO_FAST_HANDOFF_DISPOSITIONED",
                "evt_handoff_1_coalesced",
                handoff_id="handoff_1",
                disposition="COALESCED",
                replacement_handoff_id="handoff_2",
            )
        )

    assert state.to_digest_dict() == before


@pytest.mark.parametrize(
    ("replacement_fields", "replacement_disposition"),
    (
        pytest.param(
            {"task_event_seq": 1},
            None,
            id="not-newer",
        ),
        pytest.param(
            {"task_id": "task_2", "task_event_seq": 2},
            None,
            id="other-task",
        ),
        pytest.param(
            {"plan_version": 2, "task_event_seq": 2},
            None,
            id="other-plan",
        ),
        pytest.param(
            {"kind": "FINAL", "task_event_seq": 2},
            None,
            id="incompatible-kind",
        ),
        pytest.param(
            {"task_event_seq": 2},
            "CANCELLED",
            id="terminal-lifecycle",
        ),
    ),
)
def test_coalesced_handoff_requires_newer_compatible_eligible_replacement(
    replacement_fields: dict[str, object],
    replacement_disposition: str | None,
) -> None:
    module = _module()
    state = _ready_state()
    assert state.reduce_event(_handoff(task_event_seq=1))
    assert state.reduce_event(
        _handoff(
            "evt_handoff_2",
            handoff_id="handoff_2",
            **replacement_fields,
        )
    )
    if replacement_disposition is not None:
        assert state.reduce_event(
            _event(
                "SLOW_TO_FAST_HANDOFF_DISPOSITIONED",
                "evt_handoff_2_terminal",
                handoff_id="handoff_2",
                disposition=replacement_disposition,
            )
        )
    before = state.to_digest_dict()

    with pytest.raises(
        module.QwenParallelStateError,
        match="coalesced.*replacement",
    ):
        state.reduce_event(
            _event(
                "SLOW_TO_FAST_HANDOFF_DISPOSITIONED",
                "evt_handoff_1_coalesced",
                handoff_id="handoff_1",
                disposition="COALESCED",
                replacement_handoff_id="handoff_2",
            )
        )

    assert state.to_digest_dict() == before


def test_coalesced_handoff_binds_newer_queued_replacement_in_digest() -> None:
    state = _ready_state()
    assert state.reduce_event(_handoff())
    assert state.reduce_event(
        _handoff(
            "evt_handoff_2",
            handoff_id="handoff_2",
            task_event_seq=2,
        )
    )
    assert state.reduce_event(
        _event(
            "SLOW_TO_FAST_HANDOFF_DISPOSITIONED",
            "evt_handoff_2_queued",
            handoff_id="handoff_2",
            disposition="QUEUED",
        )
    )

    assert state.reduce_event(
        _event(
            "SLOW_TO_FAST_HANDOFF_DISPOSITIONED",
            "evt_handoff_1_coalesced",
            handoff_id="handoff_1",
            disposition="COALESCED",
            replacement_handoff_id="handoff_2",
        )
    )

    assert state.handoff_dispositions == {
        "handoff_1": "COALESCED",
        "handoff_2": "QUEUED",
    }
    assert state.to_digest_dict()["authority_state"][
        "coalesced_handoff_by_id"
    ] == {
        "handoff_1": {
            "replacement_handoff_id": "handoff_2",
            "disposition_event_id": "evt_handoff_1_coalesced",
        }
    }


@pytest.mark.parametrize(
    "superseded_source_event_id",
    ("evt_handoff_1", "evt_arbitration_1"),
)
def test_supersession_before_disposition_invalidates_handoff_selection(
    superseded_source_event_id: str,
) -> None:
    module = _module()
    state = _ready_state()
    assert state.reduce_event(_handoff())
    assert state.reduce_event(
        _event(
            "RESPONSE_ARBITRATION_DECIDED",
            "evt_arbitration_1",
            arbitration_id="arbitration_1",
            selected_source_type="progress",
            selected_source_event_id="evt_handoff_1",
            superseded_source_event_ids=(),
            provider_session_generation=1,
            playback_epoch=0,
            interaction_state_version=0,
        )
    )
    assert state.reduce_event(
        _event(
            "RESPONSE_ARBITRATION_DECIDED",
            "evt_arbitration_2",
            arbitration_id="arbitration_2",
            selected_source_type="none",
            superseded_source_event_ids=(superseded_source_event_id,),
            provider_session_generation=1,
            playback_epoch=0,
            interaction_state_version=0,
        )
    )
    before = state.to_digest_dict()

    with pytest.raises(module.QwenParallelStateError, match="superseded"):
        state.reduce_event(
            _event(
                "SLOW_TO_FAST_HANDOFF_DISPOSITIONED",
                "evt_handoff_selected_1",
                handoff_id="handoff_1",
                disposition="SELECTED",
                response_arbitration_event_id="evt_arbitration_1",
                current_task_id="task_1",
                current_plan_version=1,
                current_task_event_seq=1,
            )
        )

    assert state.to_digest_dict() == before
    assert "handoff_1" not in state.handoff_dispositions


@pytest.mark.parametrize(
    "superseded_source_event_id",
    (
        "evt_handoff_1",
        "evt_arbitration_1",
        "evt_handoff_selected_1",
    ),
)
def test_supersession_after_disposition_invalidates_composer_projection(
    superseded_source_event_id: str,
) -> None:
    module = _module()
    state = _selected_handoff_state()
    assert state.reduce_event(
        _event(
            "RESPONSE_ARBITRATION_DECIDED",
            "evt_arbitration_2",
            arbitration_id="arbitration_2",
            selected_source_type="none",
            superseded_source_event_ids=(superseded_source_event_id,),
            provider_session_generation=1,
            playback_epoch=0,
            interaction_state_version=0,
        )
    )
    before = state.to_digest_dict()

    with pytest.raises(module.QwenParallelStateError, match="superseded"):
        state.reduce_event(
            _projection(
                "evt_projection_composer_superseded",
                role="composer",
                projection_id="projection_composer_superseded",
                source_event_ids=(
                    "evt_handoff_1",
                    "evt_arbitration_1",
                    "evt_handoff_selected_1",
                ),
            )
        )

    assert state.to_digest_dict() == before


def test_arbitration_superseded_sets_are_sorted_behavioral_digest_inputs() -> None:
    superseding = _selected_handoff_state()
    unrelated = _selected_handoff_state()
    for state in (superseding, unrelated):
        assert state.reduce_event(
            _handoff(
                "evt_handoff_2",
                handoff_id="handoff_2",
                task_event_seq=2,
            )
        )
        assert state.reduce_event(
            _handoff(
                "evt_handoff_3",
                handoff_id="handoff_3",
                task_event_seq=3,
            )
        )

    assert superseding.reduce_event(
        _event(
            "RESPONSE_ARBITRATION_DECIDED",
            "evt_arbitration_2",
            arbitration_id="arbitration_2",
            selected_source_type="none",
            superseded_source_event_ids=(
                "evt_handoff_1",
                "evt_arbitration_1",
            ),
            provider_session_generation=1,
            playback_epoch=0,
            interaction_state_version=0,
        )
    )
    assert unrelated.reduce_event(
        _event(
            "RESPONSE_ARBITRATION_DECIDED",
            "evt_arbitration_2",
            arbitration_id="arbitration_2",
            selected_source_type="none",
            superseded_source_event_ids=(
                "evt_handoff_3",
                "evt_handoff_2",
            ),
            provider_session_generation=1,
            playback_epoch=0,
            interaction_state_version=0,
        )
    )

    superseding_digest = superseding.to_digest_dict()
    unrelated_digest = unrelated.to_digest_dict()
    superseded_ids = superseding_digest["authority_state"][
        "arbitration_by_event_id"
    ]["evt_arbitration_2"]["superseded_source_event_ids"]

    assert superseded_ids == ("evt_arbitration_1", "evt_handoff_1")
    assert superseding_digest != unrelated_digest


def test_state_digest_preserves_only_exact_safe_release_token_metadata() -> None:
    release_token_id = "release_token_0123456789abcdef0123456789abcdef"
    release_token_ref = f"release-token://synthetic/{release_token_id}"
    canonical = canonical_digest_payload(
        {
            "release_token_id": release_token_id,
            "release_token_ref": release_token_ref,
            "access_token": "must-be-dropped",
            "refresh_token": "must-also-be-dropped",
        }
    )

    assert canonical == {
        "release_token_id": release_token_id,
        "release_token_ref": release_token_ref,
    }


@pytest.mark.parametrize(
    ("key", "unsafe_value"),
    (
        ("release_token_id", "release_token_not-fixed-width"),
        (
            "release_token_id",
            "release_token_%30%31%32%33%34%35%36%37"
            "%38%39%61%62%63%64%65%66"
            "%30%31%32%33%34%35%36%37"
            "%38%39%61%62%63%64%65%66",
        ),
        (
            "release_token_ref",
            "release-token://synthetic/"
            "release_token_0123456789abcdef0123456789abcdef?token=secret",
        ),
        (
            "release_token_ref",
            "release-token%3A%2F%2Fsynthetic%2F"
            "release_token_0123456789abcdef0123456789abcdef",
        ),
    ),
)
def test_state_digest_rejects_malformed_or_encoded_release_token_metadata(
    key: str,
    unsafe_value: str,
) -> None:
    with pytest.raises(ValueError, match=key):
        canonical_digest_payload({key: unsafe_value})


def test_state_digest_conditionally_includes_qwen_parallel_state_hash() -> None:
    common = {
        "source_session_id": "sess_mvp0_synthetic",
        "last_event_seq": 7,
        "event_schema_version_range": ["1.0"],
        "interaction_state": {"turn_phase": "IDLE"},
        "playback_state": {"phase": "NOT_PLAYING"},
        "adapter_health_state": {"adapters": {}},
        "trace_privacy_state": {"fixture_domain": "GITHUB_ALLOWED"},
    }

    legacy = state_digest(**common)
    parallel = state_digest(
        **common,
        qwen_parallel_state={
            "saw_adr018_event": True,
            "provider_context_state": "CLEAN",
        },
    )

    assert "qwen_parallel_state_hash" not in legacy
    assert parallel["qwen_parallel_state_hash"] == stable_hash(
        {
            "saw_adr018_event": True,
            "provider_context_state": "CLEAN",
        }
    )
    assert parallel["overall_digest"] != legacy["overall_digest"]


def test_adapter_health_digest_records_adr018_adapter_output_modes() -> None:
    state = AdapterHealthState()
    events = (
        {
            "event_name": "ROUTE_EVIDENCE_OUTPUT_EMITTED",
            "event_id": "evt_route_evidence",
            "output_mode": "mock",
        },
        {
            "event_name": "CANDIDATE_SAFETY_EVIDENCE_OUTPUT_EMITTED",
            "event_id": "evt_candidate_safety",
            "output_mode": "mock",
        },
        {
            "event_name": "CANDIDATE_AUDIO_SHADOW_VERIFICATION_EMITTED",
            "event_id": "evt_shadow_verification",
            "output_mode": "degraded",
        },
    )

    assert all(state.reduce_event(event) for event in events)
    assert state.to_digest_dict()["output_event_modes"] == {
        "evt_candidate_safety": "mock",
        "evt_route_evidence": "mock",
        "evt_shadow_verification": "degraded",
    }


def test_failed_gate_digest_omits_absent_release_token_ref() -> None:
    digest_module = importlib.import_module("voice_agent.replay.state_digest")
    state = _candidate_state()
    assert state.reduce_event(
        _gate(
            "FOREGROUND_ACT_GATE_FAILED",
            "evt_gate_failed_without_token",
        )
    )

    digest = state.to_digest_dict()
    gate_binding = digest["authority_state"]["gate_by_event_id"][
        "evt_gate_failed_without_token"
    ]

    assert "release_token_ref" not in gate_binding
    assert len(digest_module.stable_hash(digest)) == 64


def test_composer_projection_rejects_nonselected_handoff_source() -> None:
    module = _module()
    state = _ready_state()
    assert state.reduce_event(_handoff())
    before = state.to_digest_dict()

    with pytest.raises(module.QwenParallelStateError, match="SELECTED handoff"):
        state.reduce_event(
            _projection(
                "evt_projection_composer_1",
                role="composer",
                projection_id="projection_composer_1",
                source_event_ids=("evt_handoff_1",),
            )
        )

    assert state.to_digest_dict() == before


@pytest.mark.parametrize(
    ("expiry_status", "disposition", "current_identity"),
    (
        pytest.param("CURRENT", "QUEUED", {}, id="queued"),
        pytest.param(
            "CURRENT",
            "STALE",
            {
                "current_task_id": "task_1",
                "current_plan_version": 2,
                "current_task_event_seq": 1,
            },
            id="stale",
        ),
        pytest.param("EXPIRED", "EXPIRED", {}, id="expired"),
    ),
)
def test_composer_projection_rejects_terminally_unselectable_handoff_source(
    expiry_status: str,
    disposition: str,
    current_identity: dict[str, object],
) -> None:
    module = _module()
    state = _ready_state()
    assert state.reduce_event(_handoff(expiry_status=expiry_status))
    assert state.reduce_event(
        _event(
            "SLOW_TO_FAST_HANDOFF_DISPOSITIONED",
            "evt_handoff_disposition_1",
            handoff_id="handoff_1",
            disposition=disposition,
            **current_identity,
        )
    )
    before = state.to_digest_dict()

    with pytest.raises(
        module.QwenParallelStateError,
        match="CURRENT.*SELECTED handoff",
    ):
        state.reduce_event(
            _projection(
                "evt_projection_composer_1",
                role="composer",
                projection_id="projection_composer_1",
                source_event_ids=("evt_handoff_1",),
            )
        )

    assert state.to_digest_dict() == before


def test_composer_projection_requires_exact_selected_handoff_emission_source() -> None:
    module = _module()
    state = _ready_state()
    assert state.reduce_event(_handoff())
    assert state.reduce_event(
        _event(
            "RESPONSE_ARBITRATION_DECIDED",
            "evt_arbitration_1",
            arbitration_id="arbitration_1",
            selected_source_type="progress",
            selected_source_event_id="evt_handoff_1",
            superseded_source_event_ids=(),
            provider_session_generation=1,
            playback_epoch=0,
            interaction_state_version=0,
        )
    )
    assert state.reduce_event(
        _event(
            "SLOW_TO_FAST_HANDOFF_DISPOSITIONED",
            "evt_handoff_selected_1",
            handoff_id="handoff_1",
            disposition="SELECTED",
            response_arbitration_event_id="evt_arbitration_1",
            current_task_id="task_1",
            current_plan_version=1,
            current_task_event_seq=1,
        )
    )

    for projection_id, source_event_ids in (
        ("projection_without_handoff", ("evt_generic_prior_output",)),
        ("projection_arbitration_only", ("evt_arbitration_1",)),
    ):
        before = state.to_digest_dict()
        with pytest.raises(
            module.QwenParallelStateError,
            match="exact CURRENT.*SELECTED handoff",
        ):
            state.reduce_event(
                _projection(
                    f"evt_{projection_id}",
                    role="composer",
                    projection_id=projection_id,
                    source_event_ids=source_event_ids,
                )
            )
        assert state.to_digest_dict() == before

    assert state.reduce_event(
        _projection(
            "evt_projection_selected_handoff",
            role="composer",
            projection_id="projection_selected_handoff",
            source_event_ids=(
                "evt_handoff_1",
                "evt_arbitration_1",
                "evt_handoff_selected_1",
            ),
        )
    )


def test_safe_bounded_ids_and_digests_are_enforced() -> None:
    module = _module()
    state = _ready_state()

    with pytest.raises(module.QwenParallelStateError, match="event_id"):
        state.reduce_event(
            _projection(
                "evt projection unsafe",
                role="route_evidence",
                projection_id="projection_route_1",
            )
        )

    state = _ready_state()
    events = (
        _projection(
            "evt_projection_route_1",
            role="route_evidence",
            projection_id="projection_route_1",
        ),
        _route_evidence(),
        _projection(
            "evt_projection_safety_1",
            role="candidate_safety",
            projection_id="projection_safety_1",
        ),
        _candidate_safety(),
        _parallel_fast_output(),
    )
    assert all(state.reduce_event(event) for event in events)
    with pytest.raises(module.QwenParallelStateError, match="digest"):
        state.reduce_event(
            _candidate(transcript_digest="not-a-safe-digest")
        )


def test_digest_distinguishes_candidate_fence_that_changes_gate_authority() -> None:
    module = _module()
    stale = _candidate_state()
    current = _ready_state()

    assert stale.reduce_event(
        _event(
            "INTERRUPT_CANDIDATE",
            "evt_interrupt_same",
            playback_epoch=1,
            interaction_state_version=1,
        )
    )
    assert stale.reduce_event(
        _event(
            "TTS_TRUNCATE_REQUESTED",
            "evt_truncate_same",
            interrupt_candidate_event_id="evt_interrupt_same",
            playback_epoch=1,
            interaction_state_version=1,
        )
    )
    assert current.reduce_event(
        _event(
            "INTERRUPT_CANDIDATE",
            "evt_interrupt_same",
            playback_epoch=1,
            interaction_state_version=1,
        )
    )
    assert current.reduce_event(
        _event(
            "TTS_TRUNCATE_REQUESTED",
            "evt_truncate_same",
            interrupt_candidate_event_id="evt_interrupt_same",
            playback_epoch=1,
            interaction_state_version=1,
        )
    )
    current_events = (
        _projection(
            "evt_projection_route_1",
            role="route_evidence",
            projection_id="projection_route_1",
        ),
        _route_evidence(),
        _projection(
            "evt_projection_safety_1",
            role="candidate_safety",
            projection_id="projection_safety_1",
        ),
        _candidate_safety(),
        _parallel_fast_output(),
        _candidate(),
    )
    assert all(current.reduce_event(event) for event in current_events)

    stale_digest = stale.to_digest_dict()
    current_digest = current.to_digest_dict()
    gate = _gate(
        "FOREGROUND_ACT_GATE_PASSED",
        "evt_gate_same",
        release_token_ref=(
            "release-token://synthetic/"
            "release_token_0123456789abcdef0123456789abcdef"
        ),
    )

    with pytest.raises(module.QwenParallelStateError, match="fence"):
        stale.reduce_event(gate)
    assert current.reduce_event(gate)
    assert stale_digest != current_digest


def test_digest_distinguishes_seen_event_ids_that_change_duplicate_acceptance() -> None:
    module = _module()
    seen = _ready_state()
    unseen = _ready_state()

    for state, interrupt_event_id, truncate_event_id in (
        (seen, "evt_duplicate_target", "evt_truncate_seen"),
        (unseen, "evt_interrupt_unseen", "evt_truncate_unseen"),
    ):
        assert state.reduce_event(
            _event(
                "INTERRUPT_CANDIDATE",
                interrupt_event_id,
                playback_epoch=1,
                interaction_state_version=1,
            )
        )
        assert state.reduce_event(
            _event(
                "TTS_TRUNCATE_REQUESTED",
                truncate_event_id,
                interrupt_candidate_event_id=interrupt_event_id,
                playback_epoch=1,
                interaction_state_version=1,
            )
        )

    seen_digest = seen.to_digest_dict()
    unseen_digest = unseen.to_digest_dict()
    next_event = _handoff(
        "evt_duplicate_target",
        handoff_id="handoff_next",
    )

    with pytest.raises(module.QwenParallelStateError, match="duplicate"):
        seen.reduce_event(next_event)
    assert unseen.reduce_event(next_event)
    assert seen_digest != unseen_digest


def test_digest_distinguishes_pending_interrupt_identity() -> None:
    module = _module()
    pending_b = _ready_state()
    pending_a = _ready_state()

    for state, first_interrupt_id, second_interrupt_id in (
        (pending_b, "evt_interrupt_a", "evt_interrupt_b"),
        (pending_a, "evt_interrupt_b", "evt_interrupt_a"),
    ):
        assert state.reduce_event(
            _event(
                "INTERRUPT_CANDIDATE",
                first_interrupt_id,
                playback_epoch=1,
                interaction_state_version=1,
            )
        )
        assert state.reduce_event(
            _event(
                "TTS_TRUNCATE_REQUESTED",
                "evt_truncate_first",
                interrupt_candidate_event_id=first_interrupt_id,
                playback_epoch=1,
                interaction_state_version=1,
            )
        )
        assert state.reduce_event(
            _event(
                "INTERRUPT_CANDIDATE",
                second_interrupt_id,
                playback_epoch=2,
                interaction_state_version=2,
            )
        )

    pending_b_digest = pending_b.to_digest_dict()
    pending_a_digest = pending_a.to_digest_dict()
    truncate_b = _event(
        "TTS_TRUNCATE_REQUESTED",
        "evt_truncate_second",
        interrupt_candidate_event_id="evt_interrupt_b",
        playback_epoch=2,
        interaction_state_version=2,
    )

    assert pending_b.reduce_event(truncate_b)
    with pytest.raises(module.QwenParallelStateError, match="preserve"):
        pending_a.reduce_event(truncate_b)
    assert pending_b_digest != pending_a_digest


def test_digest_is_sorted_deterministic_and_does_not_alias_state() -> None:
    module = _module()
    first = module.QwenParallelState(
        context_projection_event_ids=("evt_projection_b", "evt_projection_a"),
        handoff_dispositions={"handoff_b": "STALE", "handoff_a": "EXPIRED"},
        assistant_delivery_dispositions={
            "assistant_b": "FULL",
            "assistant_a": "NOT_STARTED",
        },
    )
    second = module.QwenParallelState(
        context_projection_event_ids=("evt_projection_b", "evt_projection_a"),
        handoff_dispositions={"handoff_a": "EXPIRED", "handoff_b": "STALE"},
        assistant_delivery_dispositions={
            "assistant_a": "NOT_STARTED",
            "assistant_b": "FULL",
        },
    )

    first_digest = first.to_digest_dict()
    assert first_digest == second.to_digest_dict()
    assert list(first_digest["handoff_dispositions"]) == [
        "handoff_a",
        "handoff_b",
    ]

    first_digest["handoff_dispositions"]["handoff_c"] = "DISCARDED"
    assert "handoff_c" not in first.handoff_dispositions
    reordered = module.QwenParallelState(
        context_projection_event_ids=("evt_projection_a", "evt_projection_b"),
        handoff_dispositions={"handoff_a": "EXPIRED", "handoff_b": "STALE"},
        assistant_delivery_dispositions={
            "assistant_a": "NOT_STARTED",
            "assistant_b": "FULL",
        },
    )
    assert reordered.to_digest_dict() != first.to_digest_dict()


def test_legacy_fast_events_are_not_owned_or_digest_visible() -> None:
    module = _module()
    state = module.QwenParallelState()
    before = state.to_digest_dict()

    assert (
        state.reduce_event(
            _event(
                "FAST_INTERACTION_OUTPUT_EMITTED",
                "evt_atomic_fast",
                fast_interaction_topology="atomic_single_call",
            )
        )
        is False
    )
    assert (
        state.reduce_event(_event("ROUTER_DECISION_EMITTED", "evt_router"))
        is False
    )
    assert state.to_digest_dict() == before
    assert state.saw_adr018_event is False
