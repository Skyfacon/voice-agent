from __future__ import annotations

import http.client
import json
import random
import socket
import time
import urllib.request

import pytest

from voice_agent.adapters.lalm_thinker_binding import (
    LALM_THINKER_CANDIDATE_SCHEMA_VERSION,
    bind_lalm_thinker_request,
)
from voice_agent.adapters.lalm_thinker_skeleton import (
    LALMThinkerCandidateParseError,
    LALMThinkerCandidateValidationError,
    fake_lalm_thinker_transport,
    parse_lalm_thinker_candidate_text,
    validate_lalm_thinker_candidate,
)


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
    assert validated.semantic_frame_ref == "semantic-frame://synthetic/lalm-thinker/turn-text-001/frame"
    assert validated.semantic_summary_ref == "summary://synthetic/lalm-thinker/turn-text-001/summary"
    assert validated.optional_statuses == {
        "semantic_close_status": "available",
        "assistant_directedness_status": "available",
        "emotion_status": "available",
        "audio_caption_status": "available",
    }
    assert validated.evidence_only is True
    assert validated.may_emit_contract_event is False


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
        (lambda candidate: candidate.update(raw_audio="audio/raw/session.wav"), "raw_artifact_retention"),
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


def test_fake_transport_returns_provider_neutral_synthetic_candidate_without_runtime_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = _binding()
    blocked_calls = _block_provider_runtime(monkeypatch)

    candidate_text = fake_lalm_thinker_transport(binding)
    parsed = parse_lalm_thinker_candidate_text(candidate_text)
    validated = validate_lalm_thinker_candidate(parsed, expected_binding=binding)

    assert blocked_calls == []
    assert validated.semantic_frame_ref.startswith("semantic-frame://synthetic/lalm-thinker/")
    assert validated.may_emit_contract_event is False
    rendered = repr(parsed).lower()
    assert "provider_response" not in rendered
    assert "provider_schema" not in rendered
    assert "raw_audio" not in rendered
    assert "authorization" not in rendered


def _binding() -> object:
    return bind_lalm_thinker_request(
        turn_committed_event={
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
        },
        adapter_request_id="adapter-request-lalm-thinker-001",
        request_metadata_ref="request-metadata://synthetic/lalm-thinker/text-001",
        input_ref="text://synthetic/lalm-thinker/input-001",
        policy_ref="policy://synthetic/lalm-thinker/evidence-only",
    )


def _valid_candidate(binding: object | None = None) -> dict[str, object]:
    binding = binding or _binding()
    return {
        "schema_version": LALM_THINKER_CANDIDATE_SCHEMA_VERSION,
        "request_binding": binding.to_dict(),
        "candidate_role": "evidence_only",
        "output_mode": "real",
        "semantic_frame_ref": "semantic-frame://synthetic/lalm-thinker/turn-text-001/frame",
        "semantic_summary_ref": "summary://synthetic/lalm-thinker/turn-text-001/summary",
        "optional_evidence_refs": {
            "semantic_close": {
                "status": "available",
                "ref": "semantic-close://synthetic/lalm-thinker/turn-text-001/closed",
            },
            "assistant_directedness": {
                "status": "available",
                "ref": "assistant-directedness://synthetic/lalm-thinker/turn-text-001/directed",
            },
            "emotion": {
                "status": "available",
                "ref": "emotion://synthetic/lalm-thinker/turn-text-001/calm",
            },
            "audio_caption": {
                "status": "available",
                "ref": "audio-caption://synthetic/lalm-thinker/turn-text-001/caption",
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
        },
        "artifact_policy": {
            "retention": "refs_only",
            "raw_artifacts_retained": False,
        },
        "validation_ref": "validation://synthetic/lalm-thinker/turn-text-001/candidate",
    }


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
