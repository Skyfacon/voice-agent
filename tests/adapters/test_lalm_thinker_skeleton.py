from __future__ import annotations

import http.client
import json
import random
import socket
import time
import urllib.request

import pytest

from tests.adapters.test_mvp3_adapter_profiles import valid_mvp3_real_profiles
from voice_agent.adapters.lalm_thinker_profile import build_lalm_thinker_capability
from voice_agent.adapters.lalm_thinker_binding import (
    LALM_THINKER_CANDIDATE_SCHEMA_VERSION,
    bind_lalm_thinker_request,
)
from voice_agent.adapters.lalm_thinker_skeleton import (
    LALMThinkerCandidateParseError,
    LALMThinkerCandidateValidationError,
    build_lalm_thinker_live_request_payload,
    emit_lalm_thinker_live_provider_result,
    emit_lalm_thinker_provider_text_result,
    emit_lalm_thinker_semantic_frame,
    fake_lalm_thinker_transport,
    parse_lalm_thinker_candidate_text,
    validate_lalm_thinker_candidate,
)
from voice_agent.adapters.lalm_thinker_live_transport import LALMThinkerCredentialHandle
from voice_agent.replay.runner import run_replay_fixture
from voice_agent.runtime.adapter_callback_boundary import AdapterCallbackAppendBoundary
from voice_agent.runtime.assembly import RuntimeAdapterAssemblyConfig
from voice_agent.runtime.session import start_configured_session


def test_parser_accepts_exactly_one_candidate_object() -> None:
    candidate = _valid_candidate()

    parsed = parse_lalm_thinker_candidate_text(json.dumps(candidate, sort_keys=True))

    assert parsed == candidate


@pytest.mark.parametrize(
    "content",
    (
        "",
        "The answer is {\"schema_version\":\"lalm_thinker_semantic_frame_candidate.v1\"}",
        "```json\n{\"schema_version\":\"lalm_thinker_semantic_frame_candidate.v1\"}\n```",
        "{\"schema_version\":\"lalm_thinker_semantic_frame_candidate.v1\"} {\"extra\": true}",
        "[{\"schema_version\":\"lalm_thinker_semantic_frame_candidate.v1\"}]",
    ),
)
def test_parser_rejects_wrappers_multiple_objects_arrays_and_empty_content(content: str) -> None:
    with pytest.raises(LALMThinkerCandidateParseError) as captured:
        parse_lalm_thinker_candidate_text(content)

    assert captured.value.failure_ref.startswith("validation://synthetic/lalm-thinker/")
    assert "schema_version" not in str(captured.value)
    if content:
        assert content not in str(captured.value)


def test_validator_accepts_available_optional_evidence_refs() -> None:
    binding = _binding()
    candidate = _valid_candidate(binding=binding)

    validated = validate_lalm_thinker_candidate(candidate, expected_binding=binding)

    assert validated.adapter_request_id == "adapter-request-lalm-thinker-001"
    assert validated.semantic_frame_ref == (
        "semantic-frame://synthetic/lalm-thinker/adapter-owned/"
        "adapter-request-lalm-thinker-001/evt-turn-committed-text-001/frame"
    )
    assert validated.semantic_summary_ref == (
        "summary://synthetic/lalm-thinker/adapter-owned/"
        "adapter-request-lalm-thinker-001/evt-turn-committed-text-001/summary"
    )
    assert validated.optional_statuses == {
        "semantic_close_status": "available",
        "assistant_directedness_status": "available",
        "emotion_status": "available",
        "audio_caption_status": "available",
    }
    assert validated.evidence_only is True
    assert validated.may_emit_contract_event is False


def test_validator_generates_adapter_owned_refs_from_hint_only_candidate() -> None:
    binding = _binding()
    candidate = _valid_hint_only_candidate(binding=binding)

    validated = validate_lalm_thinker_candidate(candidate, expected_binding=binding)

    assert validated.semantic_frame_ref == (
        "semantic-frame://synthetic/lalm-thinker/adapter-owned/"
        "adapter-request-lalm-thinker-001/evt-turn-committed-text-001/frame"
    )
    assert validated.semantic_summary_ref == (
        "summary://synthetic/lalm-thinker/adapter-owned/"
        "adapter-request-lalm-thinker-001/evt-turn-committed-text-001/summary"
    )
    assert validated.optional_refs == {
        "semantic_close_ref": (
            "semantic-close://synthetic/lalm-thinker/adapter-owned/"
            "adapter-request-lalm-thinker-001/evt-turn-committed-text-001/semantic-close"
        ),
        "assistant_directedness_ref": (
            "assistant-directedness://synthetic/lalm-thinker/adapter-owned/"
            "adapter-request-lalm-thinker-001/evt-turn-committed-text-001/assistant-directedness"
        ),
        "emotion_ref": (
            "emotion://synthetic/lalm-thinker/adapter-owned/"
            "adapter-request-lalm-thinker-001/evt-turn-committed-text-001/emotion"
        ),
        "audio_caption_ref": (
            "audio-caption://synthetic/lalm-thinker/adapter-owned/"
            "adapter-request-lalm-thinker-001/evt-turn-committed-text-001/audio-caption"
        ),
    }
    rendered = repr(validated)
    assert "dashscope" not in rendered.lower()
    assert "provider-url://" not in rendered.lower()


def test_validator_accepts_unavailable_optional_evidence_as_degraded_evidence() -> None:
    binding = _binding()
    candidate = _valid_candidate(binding=binding)
    candidate["output_mode"] = "degraded"
    candidate["optional_evidence_refs"] = {
        "semantic_close": {"status": "unavailable"},
        "assistant_directedness": {"status": "unavailable"},
        "emotion": {"status": "unavailable"},
        "audio_caption": {"status": "unavailable"},
    }

    validated = validate_lalm_thinker_candidate(candidate, expected_binding=binding)

    assert validated.output_mode == "degraded"
    assert validated.optional_refs == {}
    assert set(validated.missing_capabilities) == {
        "supports_semantic_close",
        "supports_assistant_directedness",
        "supports_emotion",
        "supports_audio_caption",
    }


@pytest.mark.parametrize(
    ("mutation", "category"),
    (
        (lambda candidate: candidate.update(schema_version="lalm_thinker_semantic_frame_candidate.v0"), "schema_version"),
        (
            lambda candidate: candidate["request_binding"].update(turn_id="turn_other"),
            "binding_mismatch",
        ),
        (lambda candidate: candidate.update(semantic_commitment={"claim": "owned"}), "ownership_claim"),
        (lambda candidate: candidate.update(provider_tool_calls=[{"name": "send"}]), "provider_tool_execution_claim"),
        (lambda candidate: candidate.update(function_call={"name": "send"}), "provider_tool_execution_claim"),
        (lambda candidate: candidate.update(native_tool_execution={"name": "send"}), "provider_tool_execution_claim"),
        (lambda candidate: candidate.update(confirmation_state={"accepted": True}), "ownership_claim"),
        (lambda candidate: candidate.update(playback_action={"play": True}), "ownership_claim"),
        (lambda candidate: candidate.update(raw_audio="audio/raw/session.wav"), "raw_artifact_retention"),
        (lambda candidate: candidate.update(raw_provider_response={"choices": []}), "raw_artifact_retention"),
        (lambda candidate: candidate.update(provider_schema={"choices": []}), "raw_artifact_retention"),
        (lambda candidate: candidate.update(raw_semantic_frame={"intent": "book"}), "raw_artifact_retention"),
        (
            lambda candidate: candidate.update(
                semantic_frame_ref="semantic-frame://synthetic/lalm-thinker?api_key=sk-synthetic"
            ),
            "unsafe_ref",
        ),
    ),
)
def test_validator_rejects_invalid_candidates_with_safe_failure_categories(
    mutation: object,
    category: str,
) -> None:
    binding = _binding()
    candidate = _valid_candidate(binding=binding)
    mutation(candidate)

    with pytest.raises(LALMThinkerCandidateValidationError) as captured:
        validate_lalm_thinker_candidate(candidate, expected_binding=binding)

    assert captured.value.category == category
    assert captured.value.failure_ref.startswith("validation://synthetic/lalm-thinker/")
    assert captured.value.failure_reasons
    rendered_error = str(captured.value).lower()
    assert "sk-synthetic" not in rendered_error
    assert "audio/raw/session.wav" not in rendered_error
    assert repr(candidate) not in str(captured.value)


@pytest.mark.parametrize(
    ("mutation", "category"),
    (
        (
            lambda candidate: candidate.update(
                semantic_frame_ref="https://dashscope.aliyuncs.com/compatible-mode/v1/raw-frame"
            ),
            "unsafe_ref",
        ),
        (
            lambda candidate: candidate.update(
                semantic_summary_ref="provider-url://dashscope/raw-summary"
            ),
            "unsafe_ref",
        ),
        (
            lambda candidate: candidate.update(
                semantic_frame_ref="/Users/a123/workspace/voice-agent-lalm-thinker/diagnostics/raw.json"
            ),
            "raw_artifact_retention",
        ),
        (
            lambda candidate: candidate["optional_evidence_refs"]["emotion"].update(
                ref="https://dashscope.aliyuncs.com/raw-emotion"
            ),
            "unsafe_ref",
        ),
        (
            lambda candidate: candidate["optional_evidence_refs"]["audio_caption"].update(
                ref="audio-caption://synthetic/lalm-thinker/audio%2Fraw%2Fsession.wav"
            ),
            "raw_artifact_retention",
        ),
        (
            lambda candidate: candidate["optional_evidence_refs"]["semantic_close"].update(
                ref="semantic-close://synthetic/lalm-thinker?token=synthetic"
            ),
            "unsafe_ref",
        ),
    ),
)
def test_validator_rejects_provider_specific_local_or_credential_refs_without_echoing_body(
    mutation: object,
    category: str,
) -> None:
    binding = _binding()
    candidate = _valid_candidate(binding=binding)
    mutation(candidate)

    with pytest.raises(LALMThinkerCandidateValidationError) as captured:
        validate_lalm_thinker_candidate(candidate, expected_binding=binding)

    assert captured.value.category == category
    assert captured.value.failure_ref.startswith("validation://synthetic/lalm-thinker/")
    rendered_error = str(captured.value).lower()
    assert "dashscope" not in rendered_error
    assert "/users/a123" not in rendered_error
    assert "token=synthetic" not in rendered_error
    assert repr(candidate) not in str(captured.value)


def test_fake_transport_returns_provider_neutral_synthetic_candidate_without_runtime_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = _binding()
    blocked_calls = _block_provider_runtime(monkeypatch)

    candidate_text = fake_lalm_thinker_transport(binding)
    parsed = parse_lalm_thinker_candidate_text(candidate_text)
    validated = validate_lalm_thinker_candidate(parsed, expected_binding=binding)

    assert blocked_calls == []
    assert validated.semantic_frame_ref.startswith(
        "semantic-frame://synthetic/lalm-thinker/adapter-owned/"
    )
    assert validated.may_emit_contract_event is False
    rendered = repr(parsed).lower()
    assert "provider_response" not in rendered
    assert "provider_schema" not in rendered
    assert "raw_audio" not in rendered
    assert "authorization_header" not in rendered
    assert "bearer " not in rendered


def test_fake_transport_defaults_to_degraded_contract_emission_for_unsupported_optional_capabilities() -> None:
    startup = _start_lalm_thinker_session()
    committed_turn = _append_committed_text_turn(startup.journal)
    binding = _binding(turn_committed_event=committed_turn)

    parsed = parse_lalm_thinker_candidate_text(fake_lalm_thinker_transport(binding))
    validated = validate_lalm_thinker_candidate(parsed, expected_binding=binding)
    emission = emit_lalm_thinker_semantic_frame(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="lalm_thinker_provider_free",
        event_id="evt_lalm_thinker_default_contract_frame",
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        turn_committed_event=committed_turn,
        validated_candidate=validated,
    )

    events = startup.journal.events()
    emitted = events[-5:]

    assert validated.output_mode == "degraded"
    assert validated.optional_refs == {}
    assert validated.optional_statuses == {
        "semantic_close_status": "unavailable",
        "assistant_directedness_status": "unavailable",
        "emotion_status": "unavailable",
        "audio_caption_status": "unavailable",
    }
    assert set(validated.missing_capabilities) == {
        "supports_semantic_close",
        "supports_assistant_directedness",
        "supports_emotion",
        "supports_audio_caption",
    }
    assert [event["event_name"] for event in emitted] == [
        "ADAPTER_OUTPUT_DEGRADED",
        "ADAPTER_OUTPUT_DEGRADED",
        "ADAPTER_OUTPUT_DEGRADED",
        "ADAPTER_OUTPUT_DEGRADED",
        "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED",
    ]
    assert [event["adapter_callback_seq"] for event in emitted] == [1, 2, 3, 4, 5]
    assert emission.degraded_events == tuple(emitted[:4])
    assert emission.thinker_event == emitted[4]
    assert emission.thinker_event["caused_by_event_id"] == committed_turn["event_id"]
    assert emission.thinker_event["output_mode"] == "degraded"
    assert "semantic_close_ref" not in emission.thinker_event
    assert "assistant_directedness_ref" not in emission.thinker_event
    assert "emotion_ref" not in emission.thinker_event
    assert "audio_caption_ref" not in emission.thinker_event

    replay_result = run_replay_fixture(
        {
            "replay_manifest": _github_allowed_replay_manifest(),
            "events": events,
        }
    )

    assert replay_result.result_status == "passed"
    assert (
        replay_result.adapter_health_state.output_event_modes[emission.thinker_event["event_id"]]
        == "degraded"
    )
    assert replay_result.adapter_health_state.adapters["lalm_thinker_provider_free"].missing_capabilities == (
        "supports_assistant_directedness",
        "supports_audio_caption",
        "supports_emotion",
        "supports_semantic_close",
    )


def test_fake_transport_explicit_available_refs_emit_real_contract_event_without_degradation() -> None:
    startup = _start_lalm_thinker_session(session_id="sess_lalm_thinker_available_refs")
    committed_turn = _append_committed_text_turn(
        startup.journal,
        event_id_prefix="evt_lalm_thinker_available_refs",
    )
    binding = _binding(turn_committed_event=committed_turn)

    parsed = parse_lalm_thinker_candidate_text(
        fake_lalm_thinker_transport(binding, optional_refs_available=True)
    )
    validated = validate_lalm_thinker_candidate(parsed, expected_binding=binding)
    emission = emit_lalm_thinker_semantic_frame(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="lalm_thinker_provider_free",
        event_id="evt_lalm_thinker_available_refs_contract_frame",
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        turn_committed_event=committed_turn,
        validated_candidate=validated,
    )

    assert validated.output_mode == "real"
    assert validated.missing_capabilities == ()
    assert emission.degraded_events == ()
    assert emission.thinker_event["output_mode"] == "real"
    assert emission.thinker_event["semantic_close_status"] == "available"
    assert emission.thinker_event["assistant_directedness_status"] == "available"
    assert emission.thinker_event["emotion_status"] == "available"
    assert emission.thinker_event["audio_caption_status"] == "available"
    assert emission.thinker_event["semantic_close_ref"].startswith(
        "semantic-close://synthetic/lalm-thinker/"
    )
    assert startup.journal.events()[-1] == emission.thinker_event
    assert run_replay_fixture(
        {
            "replay_manifest": _github_allowed_replay_manifest(),
            "events": startup.journal.events(),
        }
    ).adapter_health_state.output_event_modes[emission.thinker_event["event_id"]] == "real"


def test_live_request_payload_is_refs_only_and_provider_output_is_evidence_candidate_only() -> None:
    binding = _binding()

    payload = build_lalm_thinker_live_request_payload(binding=binding)

    assert payload["request_metadata"] == {
        "request_binding": binding.to_dict(),
        "input": {
            "ref": "text://synthetic/lalm-thinker/input-001",
            "artifact_retention": "refs_only",
        },
        "policy": {
            "ref": "policy://synthetic/lalm-thinker/evidence-only",
            "router_field_winner_selector": False,
            "semantic_commitment_authority": False,
        },
        "instruction_boundary": {
            "candidate_role": "evidence_only",
            "candidate_schema_version": LALM_THINKER_CANDIDATE_SCHEMA_VERSION,
            "response_must_be_single_json_object": True,
            "markdown_or_prose_allowed": False,
            "provider_native_schema_allowed": False,
            "raw_payload_allowed": False,
            "native_tool_execution_allowed": False,
            "candidate_refs_allowed": False,
            "final_refs_owned_by_adapter": True,
            "evidence_hints_only": True,
            "may_emit_event_journal_events": False,
            "may_create_semantic_commitments": False,
            "may_accept_confirmation": False,
            "may_authorize_tools": False,
            "may_execute_tools": False,
            "may_control_playback": False,
            "may_emit_coverage_or_truthfulness_verdicts": False,
            "owns_semantic_commitment": False,
            "owns_confirmation_state": False,
            "owns_tool_authorization": False,
            "owns_tool_execution": False,
            "owns_playback": False,
            "owns_coverage_truthfulness_checks": False,
        },
    }
    assert payload["required_output_skeleton"]["schema_version"] == (
        LALM_THINKER_CANDIDATE_SCHEMA_VERSION
    )
    assert payload["required_output_skeleton"]["request_binding"] == binding.to_dict()
    assert "semantic_frame_ref" not in payload["required_output_skeleton"]
    assert "semantic_summary_ref" not in payload["required_output_skeleton"]
    assert payload["required_output_skeleton"]["semantic_frame_hint"] == {
        "status": "available",
        "label": "semantic_frame_available",
    }
    assert payload["output_rules"] == [
        "return exactly one lalm_thinker_semantic_frame_candidate.v1 JSON object",
        "do not wrap JSON in markdown, prose, arrays, or multiple objects",
        "copy required_output_skeleton.request_binding exactly",
        "express only evidence availability, short safe labels, and normalized hints",
        "do not include final event refs; adapter owns deterministic provider-neutral refs",
        "do not include raw provider request, raw provider response, provider schema, or raw semantic payload",
        "do not call tools, request native tool execution, or include tool_calls/function_call",
        "do not claim SemanticCommitment, confirmation, tool, playback, coverage, or truthfulness ownership",
    ]
    assert _forbidden_request_terms_are_absent(payload)


def test_valid_live_provider_text_emits_only_normalized_contract_events() -> None:
    startup = _start_lalm_thinker_session(session_id="sess_lalm_thinker_live_valid")
    committed_turn = _append_committed_text_turn(
        startup.journal,
        event_id_prefix="evt_lalm_thinker_live_valid",
    )
    binding = _binding(turn_committed_event=committed_turn)
    provider_text = fake_lalm_thinker_transport(binding, optional_refs_available=True)

    result = emit_lalm_thinker_provider_text_result(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="lalm_thinker_provider_free",
        provider_text=provider_text,
        expected_binding=binding,
        success_event_id="evt_lalm_thinker_live_valid_frame",
        validation_failed_event_id="evt_lalm_thinker_live_valid_validation_failed",
        caused_by_event_id=str(committed_turn["event_id"]),
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        turn_committed_event=committed_turn,
    )

    assert result.success is True
    assert result.thinker_emission is not None
    assert result.validation_failed_event is None
    assert result.thinker_emission.thinker_event["event_name"] == (
        "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED"
    )
    assert result.to_metadata() == {
        "success": True,
        "adapter_request_id": binding.adapter_request_id,
        "raw_provider_request_included": False,
        "raw_provider_response_included": False,
        "thinker_event_id": "evt_lalm_thinker_live_valid_frame",
    }
    assert "provider_text" not in repr(result.to_metadata())
    assert "ADAPTER_OUTPUT_VALIDATION_FAILED" not in [
        event["event_name"] for event in startup.journal.events()
    ]


def test_invalid_live_provider_text_emits_validation_failure_without_thinker_frame() -> None:
    startup = _start_lalm_thinker_session(session_id="sess_lalm_thinker_live_invalid")
    committed_turn = _append_committed_text_turn(
        startup.journal,
        event_id_prefix="evt_lalm_thinker_live_invalid",
    )
    binding = _binding(turn_committed_event=committed_turn)

    result = emit_lalm_thinker_provider_text_result(
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="lalm_thinker_provider_free",
        provider_text="```json\n{}\n```",
        expected_binding=binding,
        success_event_id="evt_lalm_thinker_live_invalid_frame",
        validation_failed_event_id="evt_lalm_thinker_live_invalid_validation_failed",
        caused_by_event_id=str(committed_turn["event_id"]),
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        turn_committed_event=committed_turn,
    )

    assert result.success is False
    assert result.thinker_emission is None
    assert result.validation_failed_event is not None
    assert result.validation_failed_event["event_name"] == "ADAPTER_OUTPUT_VALIDATION_FAILED"
    assert result.validation_failed_event["schema_name"] == LALM_THINKER_CANDIDATE_SCHEMA_VERSION
    assert result.validation_failed_event["failure_reasons"] == ["fenced_markdown"]
    event_names = [event["event_name"] for event in startup.journal.events()]
    assert "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED" not in event_names
    assert "```json" not in repr(result.validation_failed_event)


def test_live_provider_path_uses_injected_transport_and_keeps_secret_out_of_metadata() -> None:
    startup = _start_lalm_thinker_session(session_id="sess_lalm_thinker_live_injected")
    committed_turn = _append_committed_text_turn(
        startup.journal,
        event_id_prefix="evt_lalm_thinker_live_injected",
    )
    binding = _binding(turn_committed_event=committed_turn)
    transport = _FakeLiveTransport(fake_lalm_thinker_transport(binding))

    result = emit_lalm_thinker_live_provider_result(
        transport=transport,
        credential_handle=LALMThinkerCredentialHandle(
            credential_ref="secret-ref://runtime-env/dashscope-api-key",
        ),
        credential_value="runtime-secret-value-for-test-only",
        model_alias="qwen3.6-flash",
        timeout_ms=60_000,
        boundary=AdapterCallbackAppendBoundary(startup.journal),
        adapter_id="lalm_thinker_provider_free",
        binding=binding,
        success_event_id="evt_lalm_thinker_live_injected_frame",
        validation_failed_event_id="evt_lalm_thinker_live_injected_validation_failed",
        caused_by_event_id=str(committed_turn["event_id"]),
        created_monotonic_ms=210,
        created_wall_clock_ms=1700000000210,
        turn_committed_event=committed_turn,
    )

    metadata = result.to_metadata()
    assert metadata["raw_provider_request_included"] is False
    assert metadata["raw_provider_response_included"] is False
    assert "runtime-secret-value-for-test-only" not in repr(metadata)
    assert "Bearer " not in repr(metadata)
    assert transport.call_count == 1


class _FakeLiveTransport:
    def __init__(self, provider_text: str) -> None:
        self._provider_text = provider_text
        self.call_count = 0

    def complete(
        self,
        *,
        request_payload: object,
        credential_handle: LALMThinkerCredentialHandle,
        credential_value: str,
        adapter_request_id: str,
        timeout_ms: int,
        model_alias: str,
    ) -> str:
        assert isinstance(request_payload, dict)
        assert credential_handle.to_metadata()["secret_materialized"] is False
        assert credential_value == "runtime-secret-value-for-test-only"
        assert adapter_request_id
        assert timeout_ms == 60_000
        assert model_alias == "qwen3.6-flash"
        self.call_count += 1
        return self._provider_text


def _binding_for_turn(turn_committed_event: dict[str, object]) -> object:
    return bind_lalm_thinker_request(
        turn_committed_event=turn_committed_event,
        adapter_request_id="adapter-request-lalm-thinker-001",
        request_metadata_ref="request-metadata://synthetic/lalm-thinker/text-001",
        input_ref="text://synthetic/lalm-thinker/input-001",
        policy_ref="policy://synthetic/lalm-thinker/evidence-only",
    )


def _binding(turn_committed_event: dict[str, object] | None = None) -> object:
    return _binding_for_turn(turn_committed_event or _committed_text_turn())


def _committed_text_turn() -> dict[str, object]:
    return {
        "event_name": "TURN_INGRESS_COMMITTED",
        "event_id": "evt_turn_committed_text_001",
        "event_seq": 4,
        "turn_id": "turn_text_001",
        "utterance_id": "utt_text_001",
        "input_modality": "text",
        "input_span_id": "input_text_001",
        "text_span_id": "text_span_001",
        "directedness": "ASSUMED_DIRECTED",
        "semantic_close": "ASSUMED_CLOSED",
        "ingress_outcome": "COMMITTED",
    }


def _valid_candidate(binding: object | None = None) -> dict[str, object]:
    return _valid_hint_only_candidate(binding=binding)


def _valid_hint_only_candidate(binding: object | None = None) -> dict[str, object]:
    binding = binding or _binding()
    return {
        "schema_version": LALM_THINKER_CANDIDATE_SCHEMA_VERSION,
        "request_binding": binding.to_dict(),
        "candidate_role": "evidence_only",
        "output_mode": "real",
        "semantic_frame_hint": {
            "status": "available",
            "label": "semantic_frame_available",
        },
        "semantic_summary_hint": {
            "status": "available",
            "label": "semantic_summary_available",
        },
        "optional_evidence_refs": {
            "semantic_close": {
                "status": "available",
                "label": "closed",
            },
            "assistant_directedness": {
                "status": "available",
                "label": "directed",
            },
            "emotion": {
                "status": "available",
                "label": "calm",
            },
            "audio_caption": {
                "status": "available",
                "label": "caption_available",
            },
        },
        "task_focus_hint": {
            "task_like": True,
            "complexity_hint": "complex",
            "focus_confidence": 0.82,
            "evidence_uncertainty": "medium",
        },
        "boundary_assertions": {
            "candidate_is_evidence_only": True,
            "may_emit_event_journal_events": False,
            "may_create_semantic_commitments": False,
            "may_accept_confirmation": False,
            "may_authorize_tools": False,
            "may_execute_tools": False,
            "may_control_playback": False,
            "may_emit_coverage_or_truthfulness_verdicts": False,
            "owns_semantic_commitment": False,
            "owns_confirmation_state": False,
            "owns_tool_authorization": False,
            "owns_tool_execution": False,
            "owns_playback": False,
            "owns_coverage_truthfulness_checks": False,
        },
        "artifact_policy": {
            "retention": "refs_only",
            "raw_artifacts_retained": False,
        },
    }


def _start_lalm_thinker_session(
    *,
    session_id: str = "sess_lalm_thinker_skeleton_synthetic",
) -> object:
    return start_configured_session(
        session_id=session_id,
        conversation_id="conv_lalm_thinker_skeleton_synthetic",
        runtime_config_ref="config://synthetic/lalm-thinker/skeleton",
        created_monotonic_ms=100,
        created_wall_clock_ms=1700000000100,
        assembly_config=RuntimeAdapterAssemblyConfig(
            stage="mvp3",
            capability_snapshot_ref="capability://synthetic/lalm-thinker/skeleton",
            capability_version="mvp3.lalm-thinker.skeleton.v1",
        ),
        capabilities=_lalm_thinker_profiles(),
    )


def _append_committed_text_turn(
    journal: object,
    *,
    event_id_prefix: str = "evt_lalm_thinker_skeleton",
) -> dict[str, object]:
    snapshot_event_id = str(journal.events()[1]["event_id"])
    text_received = journal.append(
        event_name="TEXT_INPUT_RECEIVED",
        event_id=f"{event_id_prefix}_text_received",
        source_module="access_layer",
        caused_by_event_id=snapshot_event_id,
        created_monotonic_ms=110,
        created_wall_clock_ms=1700000000110,
        trace_redaction_level="redacted_fixture",
        input_span_id="input_lalm_thinker_001",
        text_span_id="text_lalm_thinker_001",
        input_modality="text",
        directedness="ASSUMED_DIRECTED",
        semantic_close="ASSUMED_CLOSED",
        text_ref="text://synthetic/lalm-thinker/redacted-input-001",
    )
    turn_opened = journal.append(
        event_name="TURN_OPENED",
        event_id=f"{event_id_prefix}_turn_opened",
        source_module="interaction_controller",
        caused_by_event_id=str(text_received["event_id"]),
        created_monotonic_ms=111,
        created_wall_clock_ms=1700000000111,
        trace_redaction_level="metadata_only",
        turn_id="turn_lalm_thinker_001",
        input_span_id="input_lalm_thinker_001",
        input_modality="text",
        turn_phase="COLLECTING_INPUT",
    )
    accepted = journal.append(
        event_name="TURN_INGRESS_ACCEPTED",
        event_id=f"{event_id_prefix}_ingress_accepted",
        source_module="interaction_controller",
        caused_by_event_id=str(turn_opened["event_id"]),
        created_monotonic_ms=112,
        created_wall_clock_ms=1700000000112,
        trace_redaction_level="metadata_only",
        turn_id="turn_lalm_thinker_001",
        input_span_id="input_lalm_thinker_001",
        ingress_outcome="ACCEPTED",
    )
    return journal.append(
        event_name="TURN_INGRESS_COMMITTED",
        event_id=f"{event_id_prefix}_ingress_committed",
        source_module="interaction_controller",
        caused_by_event_id=str(accepted["event_id"]),
        created_monotonic_ms=113,
        created_wall_clock_ms=1700000000113,
        trace_redaction_level="metadata_only",
        turn_id="turn_lalm_thinker_001",
        utterance_id="utt_lalm_thinker_001",
        input_span_id="input_lalm_thinker_001",
        text_span_id="text_lalm_thinker_001",
        input_modality="text",
        directedness="ASSUMED_DIRECTED",
        semantic_close="ASSUMED_CLOSED",
        ingress_outcome="COMMITTED",
    )


def _github_allowed_replay_manifest() -> dict[str, object]:
    return {
        "manifest_schema_version": "1.0",
        "replay_id": "replay_lalm_thinker_skeleton_synthetic",
        "source_trace_ref": "fixture://mvp3/lalm-thinker/skeleton",
        "replay_mode": "deterministic",
        "event_schema_version_range": ["1.0"],
        "fixture_domain": "GITHUB_ALLOWED",
        "generated_from": "hand_written_minimal",
        "contains_raw_audio": False,
        "contains_raw_trace": False,
        "contains_real_user_input": False,
        "contains_secrets": False,
        "contains_unredacted_tool_result": False,
        "contains_large_raw_web_content": False,
        "allowed_re_eval_components": [],
    }


def _forbidden_request_terms_are_absent(value: object) -> bool:
    rendered = repr(value).lower()
    forbidden_terms = (
        "provider_payload",
        "provider_request",
        "provider_response",
        "raw_audio",
        "audio_bytes",
        "secret",
        "api_key",
        "authorization_header",
        "bearer ",
        "token=",
        "credential=",
    )
    return all(term not in rendered for term in forbidden_terms)


def _lalm_thinker_profiles() -> tuple[object, ...]:
    return tuple(
        build_lalm_thinker_capability() if profile.adapter_type == "thinker" else profile
        for profile in valid_mvp3_real_profiles()
    )


def _block_provider_runtime(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    blocked_calls: list[object] = []

    def fail_if_called(*args: object, **kwargs: object) -> None:
        blocked_calls.append((args, kwargs))
        raise AssertionError("provider-free LALM Thinker skeleton must not call runtime side channels")

    monkeypatch.setattr(socket, "create_connection", fail_if_called)
    monkeypatch.setattr(http.client.HTTPConnection, "connect", fail_if_called)
    monkeypatch.setattr(http.client.HTTPSConnection, "connect", fail_if_called)
    monkeypatch.setattr(urllib.request, "urlopen", fail_if_called)
    monkeypatch.setattr(time, "time", fail_if_called)
    monkeypatch.setattr(time, "monotonic", fail_if_called)
    monkeypatch.setattr(random, "random", fail_if_called)
    return blocked_calls
