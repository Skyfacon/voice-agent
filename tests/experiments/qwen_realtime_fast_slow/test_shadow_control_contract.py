from __future__ import annotations

import asyncio
import json
import time

import pytest

from experiments.qwen_realtime_fast_slow_web.qwen_shadow_router_adapter import (
    FUNCTION_NAME,
    MAX_FUNCTION_ARGUMENT_BYTES,
    MAX_REPLY_CANDIDATE_CHARS,
    MAX_TRANSCRIPT_CHARS,
    SCHEMA_VERSION,
    BoundedShadowRequestQueue,
    FakeShadowControlProvider,
    FakeShadowScript,
    FunctionCallAccumulator,
    SchemaValidationError,
    ShadowRouteRequest,
    build_shadow_session_update,
    minimize_task_focus_snapshot,
    validate_proposal_frame,
)


def run(coro):
    return asyncio.run(coro)


def valid_frame(**overrides: object) -> dict[str, object]:
    frame: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "task_focus_hint": "FOREGROUND_CHAT",
        "route_decision_hint": "FAST_ONLY",
        "foreground_act": "ANSWER",
        "task_like": False,
        "complexity_hint": "LOW",
        "evidence_uncertainty": "LOW",
        "risk_class": "LOW",
        "risk_tags": ["none"],
        "confidence": 0.95,
        "reply_candidate_text": "bounded transient candidate",
    }
    frame.update(overrides)
    return frame


def request(
    index: int = 1,
    *,
    transcript: str = "synthetic redacted final transcript",
    task_focus_snapshot: dict[str, object] | None = None,
) -> ShadowRouteRequest:
    return ShadowRouteRequest(
        request_id=f"shadow-request-{index}",
        turn_id=f"turn-{index}",
        utterance_id=f"utterance-{index}",
        asr_frame_ref=f"asr-frame://safe/{index}",
        transcript=transcript,
        task_focus_snapshot=task_focus_snapshot or {},
        asr_final_monotonic_ms=time.monotonic_ns() / 1_000_000.0,
    )


def test_shadow_session_update_is_text_only_tool_enabled_and_not_forced() -> None:
    update = build_shadow_session_update()
    session = update["session"]

    assert update["type"] == "session.update"
    assert session["modalities"] == ["text"]
    assert session["turn_detection"] is None
    assert "tool_choice" not in session
    assert session["tools"] == [
        {
            "type": "function",
            "function": session["tools"][0]["function"],
        }
    ]
    function = session["tools"][0]["function"]
    assert function["name"] == FUNCTION_NAME
    schema = function["parameters"]
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "schema_version",
        "task_focus_hint",
        "route_decision_hint",
        "foreground_act",
        "task_like",
        "complexity_hint",
        "evidence_uncertainty",
        "risk_class",
        "risk_tags",
        "confidence",
    }
    assert schema["properties"]["confidence"] == {
        "type": "number",
        "minimum": 0.0,
        "maximum": 1.0,
    }
    assert schema["properties"]["reply_candidate_text"]["maxLength"] == (
        MAX_REPLY_CANDIDATE_CHARS
    )
    assert schema["properties"]["confirmation_signal_hint"]["enum"] == [
        "ACCEPT",
        "AMBIGUOUS",
        "NOT_APPLICABLE",
        "REJECT",
    ]


def test_valid_control_frame_is_strictly_normalized_and_candidate_stays_transient() -> None:
    candidate = "PRIVATE_TRANSIENT_REPLY_CANDIDATE"
    proposal = validate_proposal_frame(
        valid_frame(
            risk_tags=[
                "Medical",
                "unknown provider novelty",
                "Medical",
                "confirmation_required",
            ],
            reply_candidate_text=candidate,
        )
    )

    assert proposal.schema_version == SCHEMA_VERSION
    assert proposal.task_focus_hint == "FOREGROUND_CHAT"
    assert proposal.route_decision_hint == "FAST_ONLY"
    assert proposal.foreground_act == "ANSWER"
    assert proposal.confidence == 0.95
    assert proposal.risk_tags == ("medical", "other", "confirmation_required")
    assert proposal.reply_candidate_text == candidate
    metadata = proposal.to_safe_metadata()
    serialized = json.dumps(metadata, sort_keys=True)
    assert metadata["reply_candidate_present"] is True
    assert metadata["reply_candidate_chars"] == len(candidate)
    assert candidate not in serialized
    assert candidate not in repr(proposal)


@pytest.mark.parametrize(
    ("field", "value", "code"),
    (
        ("schema_version", "v2", "route_frame_schema_version_invalid"),
        ("task_focus_hint", "PROVIDER_OWNS_TASK", "route_frame_task_focus_hint_invalid"),
        ("route_decision_hint", "EXECUTE_TOOL", "route_frame_route_decision_hint_invalid"),
        ("foreground_act", "PLAY_DIRECTLY", "route_frame_foreground_act_invalid"),
        ("task_like", "true", "route_frame_task_like_invalid"),
        ("complexity_hint", "EXTREME", "route_frame_complexity_hint_invalid"),
        ("evidence_uncertainty", "UNKNOWN", "route_frame_evidence_uncertainty_invalid"),
        ("risk_class", "CRITICAL", "route_frame_risk_class_invalid"),
        ("confidence", -0.01, "route_frame_confidence_invalid"),
        ("confidence", 1.01, "route_frame_confidence_invalid"),
        ("confidence", True, "route_frame_confidence_invalid"),
        ("risk_tags", "medical", "route_frame_risk_tags_invalid"),
        ("reply_candidate_text", 7, "route_frame_reply_candidate_invalid"),
        (
            "confirmation_signal_hint",
            "CANCEL_NOW",
            "route_frame_confirmation_signal_hint_invalid",
        ),
        (
            "reply_candidate_text",
            "x" * (MAX_REPLY_CANDIDATE_CHARS + 1),
            "route_frame_reply_candidate_too_large",
        ),
    ),
)
def test_control_frame_rejects_invalid_enums_ranges_and_types(
    field: str, value: object, code: str
) -> None:
    with pytest.raises(SchemaValidationError) as exc_info:
        validate_proposal_frame(valid_frame(**{field: value}))
    assert exc_info.value.code == code


def test_control_frame_rejects_missing_unknown_and_provider_binding_fields() -> None:
    missing = valid_frame()
    missing.pop("foreground_act")
    with pytest.raises(SchemaValidationError) as exc_info:
        validate_proposal_frame(missing)
    assert exc_info.value.code == "route_frame_missing_field"

    for provider_owned_field in ("turn_id", "task_id", "plan_version"):
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_proposal_frame(
                valid_frame(**{provider_owned_field: "provider-value"})
            )
        assert exc_info.value.code == "route_frame_unknown_field"


def test_request_minimizes_active_task_snapshot_and_omits_transcript_from_metadata() -> None:
    transcript = "PRIVATE_TRANSCRIPT_SENTINEL"
    raw_task_id = "task-private-provider-must-not-see-raw-id"
    route_request = request(
        transcript=transcript,
        task_focus_snapshot={
            "active_task_id": raw_task_id,
            "lifecycle": "WAITING_FOR_USER_CONFIRMATION",
            "plan_version": 4,
            "pending_confirmation_id": "confirmation-private-id",
            "pending_confirmation_scope": "TASK_CANCEL",
            "foreground_mode": "CONFIRMATION",
            "default_patch_policy": "ACTIVE_TASK_PATCH_ONLY",
            "side_conversation_allowed": False,
            "immutable_facts": ["must never cross"],
            "resolved_arguments": {"secret": "must never cross"},
        },
    )

    assert route_request.task_focus_snapshot == {
        "has_active_non_terminal_task": True,
        "active_task_ref": route_request.task_focus_snapshot["active_task_ref"],
        "lifecycle_phase": "WAITING_FOR_USER_CONFIRMATION",
        "foreground_mode": "CONFIRMATION",
        "default_patch_policy": "ACTIVE_TASK_PATCH_ONLY",
        "current_plan_version": 4,
        "pending_confirmation": True,
        "side_conversation_allowed": False,
    }
    assert route_request.task_focus_snapshot["active_task_ref"].startswith("task-")
    metadata = route_request.to_safe_metadata()
    serialized = json.dumps(metadata, sort_keys=True)
    assert metadata["transcript_chars"] == len(transcript)
    assert transcript not in serialized
    assert raw_task_id not in serialized
    assert "confirmation-private-id" not in serialized
    assert "TASK_CANCEL" not in serialized
    assert "immutable_facts" not in serialized
    assert "resolved_arguments" not in serialized
    assert transcript not in repr(route_request)
    assert raw_task_id not in repr(route_request)


def test_request_rejects_missing_or_oversized_transcript_and_unsafe_refs() -> None:
    with pytest.raises(ValueError, match="shadow_transcript_required"):
        request(transcript="")
    with pytest.raises(ValueError, match="shadow_transcript_too_large"):
        request(transcript="x" * (MAX_TRANSCRIPT_CHARS + 1))
    with pytest.raises(ValueError, match="invalid_turn_id"):
        ShadowRouteRequest(
            request_id="request-1",
            turn_id="turn with spaces",
            utterance_id="utterance-1",
            asr_frame_ref="asr://safe/1",
            transcript="synthetic",
        )


def test_function_call_accumulator_accepts_fragmented_delta_and_done() -> None:
    arguments = json.dumps(valid_frame(), separators=(",", ":"))
    fragments = (arguments[:23], arguments[23:91], arguments[91:])
    accumulator = FunctionCallAccumulator()

    for fragment in fragments:
        accumulator.feed_delta(
            response_id="response-provider-1",
            item_id="item-provider-1",
            call_id="call-provider-1",
            name=FUNCTION_NAME,
            delta=fragment,
        )
    proposal = accumulator.finish(
        response_id="response-provider-1",
        item_id="item-provider-1",
        call_id="call-provider-1",
        name=FUNCTION_NAME,
        arguments=arguments,
    )

    assert proposal.route_decision_hint == "FAST_ONLY"
    assert accumulator.fragment_count == 3
    assert accumulator.safe_metadata() == {
        "fragment_count": 3,
        "argument_bytes": len(arguments.encode("utf-8")),
        "finished": True,
        "expected_function": FUNCTION_NAME,
    }
    assert arguments not in json.dumps(accumulator.safe_metadata())


@pytest.mark.parametrize(
    ("arguments", "name", "expected_code"),
    (
        ("{not-json", FUNCTION_NAME, "function_call_arguments_malformed"),
        (
            json.dumps(valid_frame()),
            "wrong_function_name",
            "function_call_name_invalid",
        ),
    ),
)
def test_function_call_done_rejects_malformed_json_or_wrong_name(
    arguments: str, name: str, expected_code: str
) -> None:
    accumulator = FunctionCallAccumulator()
    accumulator.feed_delta(
        response_id="response-1",
        item_id="item-1",
        call_id="call-1",
        name=name,
        delta=arguments,
    )
    with pytest.raises(SchemaValidationError) as exc_info:
        accumulator.finish(
            response_id="response-1",
            item_id="item-1",
            call_id="call-1",
            name=name,
            arguments=arguments,
        )
    assert exc_info.value.code == expected_code


def test_function_call_accumulator_rejects_fragment_and_correlation_mismatch() -> None:
    arguments = json.dumps(valid_frame())
    accumulator = FunctionCallAccumulator()
    accumulator.feed_delta(
        response_id="response-1",
        item_id="item-1",
        call_id="call-1",
        delta=arguments,
    )
    with pytest.raises(SchemaValidationError) as exc_info:
        accumulator.finish(
            response_id="response-1",
            item_id="item-1",
            call_id="call-1",
            name=FUNCTION_NAME,
            arguments=arguments + " ",
        )
    assert exc_info.value.code == "function_call_arguments_mismatch"

    mismatched = FunctionCallAccumulator()
    mismatched.feed_delta(
        response_id="response-old",
        item_id="item-old",
        call_id="call-old",
        delta="{}",
    )
    with pytest.raises(SchemaValidationError) as exc_info:
        mismatched.feed_delta(
            response_id="response-new",
            item_id="item-old",
            call_id="call-old",
            delta="{}",
        )
    assert exc_info.value.code == "function_call_correlation_mismatch"


@pytest.mark.parametrize("at_finish", (False, True))
def test_slice3a1_function_arguments_envelope_is_bounded_and_content_free(
    at_finish: bool,
) -> None:
    private_arguments = "PRIVATE_FULL_ARGUMENT_SENTINEL" + (
        "x" * MAX_FUNCTION_ARGUMENT_BYTES
    )
    accumulator = FunctionCallAccumulator()

    with pytest.raises(SchemaValidationError) as exc_info:
        if at_finish:
            accumulator.finish(
                response_id="response-1",
                item_id="item-1",
                call_id="call-1",
                name=FUNCTION_NAME,
                arguments=private_arguments,
            )
        else:
            accumulator.feed_delta(
                response_id="response-1",
                item_id="item-1",
                call_id="call-1",
                name=FUNCTION_NAME,
                delta=private_arguments,
            )

    assert exc_info.value.code == "function_call_arguments_too_large"
    assert "PRIVATE_FULL_ARGUMENT_SENTINEL" not in str(exc_info.value)
    assert "PRIVATE_FULL_ARGUMENT_SENTINEL" not in json.dumps(
        accumulator.safe_metadata(), sort_keys=True
    )


def test_bounded_shadow_queue_drops_oldest_without_rebinding_new_turn() -> None:
    async def scenario() -> None:
        queue = BoundedShadowRequestQueue(maxsize=2)
        first, second, third = request(1), request(2), request(3)

        assert queue.put_nowait(first) is None
        assert queue.put_nowait(second) is None
        assert queue.put_nowait(third) is first
        assert queue.dropped_count == 1
        assert queue.qsize() == 2
        assert await queue.get() is second
        queue.task_done()
        assert await queue.get() is third
        queue.task_done()
        await queue.join()

    run(scenario())


def test_fake_shadow_connect_and_fragmented_function_call_done() -> None:
    async def scenario() -> None:
        arguments = json.dumps(valid_frame(), separators=(",", ":"))
        provider = FakeShadowControlProvider(
            [
                FakeShadowScript(
                    scenario="valid",
                    delta_fragments=(arguments[:41], arguments[41:]),
                    done_arguments=arguments,
                )
            ]
        )
        await provider.connect()
        result = await provider.analyze(request())

        assert provider.profile.output_mode == "mock"
        assert provider.session_state == "connected"
        assert result.output_mode == "mock"
        assert result.schema_valid is True
        assert result.proposal is not None
        assert result.proposal.route_decision_hint == "FAST_ONLY"
        assert result.request_id == "shadow-request-1"
        assert result.turn_id == "turn-1"
        assert result.utterance_id == "utterance-1"
        assert result.context_delete_count == 2
        assert provider.counters.request_count == 1
        assert provider.counters.context_delete_count == 2
        assert result.latency.request_to_function_call_first_delta_ms is not None
        assert result.latency.request_to_function_call_done_ms is not None
        await provider.close()

    run(scenario())


@pytest.mark.parametrize(
    ("scenario_name", "degraded_code"),
    (
        ("plain_text", "shadow_ordinary_text_instead_of_function_call"),
        ("malformed", "function_call_arguments_malformed"),
        ("wrong_name", "function_call_name_invalid"),
        ("provider_error", "shadow_provider_error"),
        ("disconnect", "shadow_provider_disconnected"),
    ),
)
def test_fake_shadow_failures_are_degraded_without_fabricated_proposal(
    scenario_name: str, degraded_code: str
) -> None:
    async def scenario() -> None:
        provider = FakeShadowControlProvider([scenario_name])
        await provider.connect()
        result = await provider.analyze(request())

        assert result.output_mode == "degraded"
        assert result.schema_valid is False
        assert result.proposal is None
        assert result.degraded_code == degraded_code
        assert result.safe_metadata()["proposal_available"] is False
        await provider.close()

    run(scenario())


def test_fake_shadow_timeout_isolated_and_counted() -> None:
    async def scenario() -> None:
        provider = FakeShadowControlProvider(["timeout"])
        await provider.connect()
        result = await provider.analyze(request(), timeout_seconds=0.005)

        assert result.output_mode == "degraded"
        assert result.proposal is None
        assert result.degraded_code == "shadow_request_timeout"
        assert result.context_tainted is True
        assert provider.counters.timeout_count == 1
        assert provider.session_state == "degraded"
        await provider.close()

    run(scenario())


def test_fake_context_delete_failure_taints_then_rebuilds_before_next_request() -> None:
    async def scenario() -> None:
        provider = FakeShadowControlProvider(["delete_fail", "valid"])
        await provider.connect()

        failed = await provider.analyze(request(1))
        assert failed.schema_valid is True
        assert failed.proposal is not None
        assert failed.output_mode == "degraded"
        assert failed.degraded_code == "shadow_context_delete_unconfirmed"
        assert failed.context_tainted is True
        assert provider.counters.context_delete_failure_count == 1
        assert provider.session_state == "degraded"

        recovered = await provider.analyze(request(2))
        assert provider.counters.context_rebuild_count == 1
        assert recovered.context_rebuild_count == 1
        assert recovered.context_tainted is False
        assert recovered.output_mode == "mock"
        assert recovered.schema_valid is True
        assert recovered.turn_id == "turn-2"
        await provider.close()

    run(scenario())


def test_fake_multi_turn_results_remain_bound_to_each_local_request() -> None:
    async def scenario() -> None:
        provider = FakeShadowControlProvider(["valid", "valid"])
        await provider.connect()
        first = await provider.analyze(request(1))
        second = await provider.analyze(request(2))

        assert (first.request_id, first.turn_id, first.utterance_id) == (
            "shadow-request-1",
            "turn-1",
            "utterance-1",
        )
        assert (second.request_id, second.turn_id, second.utterance_id) == (
            "shadow-request-2",
            "turn-2",
            "utterance-2",
        )
        assert first.safe_turn_ref != second.safe_turn_ref
        await provider.close()

    run(scenario())


def test_shadow_result_metadata_excludes_transcript_arguments_and_full_candidate() -> None:
    async def scenario() -> None:
        transcript = "PRIVATE_REAL_TRANSCRIPT_SENTINEL"
        candidate = "PRIVATE_FULL_REPLY_CANDIDATE_SENTINEL"
        provider_arguments = json.dumps(
            valid_frame(reply_candidate_text=candidate), separators=(",", ":")
        )
        provider = FakeShadowControlProvider(
            [FakeShadowScript(done_arguments=provider_arguments)]
        )
        await provider.connect()
        result = await provider.analyze(request(transcript=transcript))
        serialized = json.dumps(result.to_safe_metadata(), sort_keys=True)

        assert result.schema_valid is True
        assert transcript not in serialized
        assert candidate not in serialized
        assert provider_arguments not in serialized
        for marker in (
            "transcript",
            "reply_candidate_text",
            "function_arguments",
            "provider_payload",
            "raw_audio",
            "authorization",
            "api_key",
        ):
            assert marker not in serialized.lower()
        await provider.close()

    run(scenario())


def test_minimize_task_focus_snapshot_rejects_non_mapping() -> None:
    with pytest.raises(ValueError, match="task_focus_snapshot_invalid"):
        minimize_task_focus_snapshot([])  # type: ignore[arg-type]
