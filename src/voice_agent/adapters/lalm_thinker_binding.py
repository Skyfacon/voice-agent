from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote

from voice_agent.adapters.capabilities import CREDENTIAL_LIKE_REF_PATTERN


class LALMThinkerBindingError(ValueError):
    pass


LALM_THINKER_CANDIDATE_SCHEMA_VERSION = "lalm_thinker_semantic_frame_candidate.v1"
LALM_THINKER_CANDIDATE_SCHEMA = {
    "schema_version": LALM_THINKER_CANDIDATE_SCHEMA_VERSION,
    "schema_kind": "adapter_local_candidate_schema",
    "event_journal_event": False,
    "canonical_event_name": None,
    "candidate_role": "evidence_only",
    "forbidden_ownership": (
        "semantic_commitment",
        "confirmation_state",
        "tool_authorization",
        "tool_execution",
        "playback",
        "coverage_truthfulness_verdict",
    ),
}

_DISALLOWED_REF_MARKERS = (
    "audio/raw/",
    "diagnostics/",
    "traces/",
    "replays/local/",
)


@dataclass(frozen=True)
class LALMThinkerRequestBinding:
    adapter_request_id: str
    turn_committed_event_id: str
    turn_id: str
    utterance_id: str
    input_modality: str
    request_metadata_ref: str
    input_ref: str
    policy_ref: str
    input_span_id: str | None = None
    text_span_id: str | None = None
    audio_span_id: str | None = None
    candidate_schema_version: str = LALM_THINKER_CANDIDATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_safe_token(self.adapter_request_id, "adapter_request_id")
        _require_safe_token(self.turn_committed_event_id, "turn_committed_event_id")
        _require_safe_token(self.turn_id, "turn_id")
        _require_safe_token(self.utterance_id, "utterance_id")
        if self.input_modality not in {"text", "audio"}:
            raise LALMThinkerBindingError("input_modality must be text or audio")
        _require_safe_ref(self.request_metadata_ref, "request_metadata_ref")
        _require_safe_ref(self.input_ref, "input_ref")
        _require_safe_ref(self.policy_ref, "policy_ref")
        for field, value in (
            ("input_span_id", self.input_span_id),
            ("text_span_id", self.text_span_id),
            ("audio_span_id", self.audio_span_id),
        ):
            if value is not None:
                _require_safe_token(value, field)
        if self.candidate_schema_version != LALM_THINKER_CANDIDATE_SCHEMA_VERSION:
            raise LALMThinkerBindingError("unsupported candidate_schema_version")

    def to_dict(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "adapter_request_id": self.adapter_request_id,
            "turn_committed_event_id": self.turn_committed_event_id,
            "turn_id": self.turn_id,
            "utterance_id": self.utterance_id,
            "input_modality": self.input_modality,
            "request_metadata_ref": self.request_metadata_ref,
            "input_ref": self.input_ref,
            "policy_ref": self.policy_ref,
            "candidate_schema_version": self.candidate_schema_version,
        }
        if self.input_span_id is not None:
            metadata["input_span_id"] = self.input_span_id
        if self.text_span_id is not None:
            metadata["text_span_id"] = self.text_span_id
        if self.audio_span_id is not None:
            metadata["audio_span_id"] = self.audio_span_id
        return metadata


def bind_lalm_thinker_request(
    *,
    turn_committed_event: Mapping[str, Any],
    adapter_request_id: str,
    request_metadata_ref: str,
    input_ref: str,
    policy_ref: str,
    expected_turn_committed_event_id: str | None = None,
) -> LALMThinkerRequestBinding:
    if turn_committed_event.get("event_name") != "TURN_INGRESS_COMMITTED":
        raise LALMThinkerBindingError("LALM Thinker request requires TURN_INGRESS_COMMITTED")

    event_id = _require_safe_token(
        _require_event_string(turn_committed_event, "event_id"),
        "turn_committed_event_id",
    )
    if expected_turn_committed_event_id is not None and expected_turn_committed_event_id != event_id:
        raise LALMThinkerBindingError("LALM Thinker request causal turn id mismatch")

    input_modality = _require_event_string(turn_committed_event, "input_modality")
    if input_modality not in {"text", "audio"}:
        raise LALMThinkerBindingError("TURN_INGRESS_COMMITTED input_modality must be text or audio")

    return LALMThinkerRequestBinding(
        adapter_request_id=adapter_request_id,
        turn_committed_event_id=event_id,
        turn_id=_require_event_string(turn_committed_event, "turn_id"),
        utterance_id=_require_event_string(turn_committed_event, "utterance_id"),
        input_modality=input_modality,
        input_span_id=_optional_event_string(turn_committed_event, "input_span_id"),
        text_span_id=_optional_event_string(turn_committed_event, "text_span_id"),
        audio_span_id=_optional_event_string(turn_committed_event, "audio_span_id"),
        request_metadata_ref=request_metadata_ref,
        input_ref=input_ref,
        policy_ref=policy_ref,
    )


def build_lalm_thinker_request_metadata(binding: LALMThinkerRequestBinding) -> dict[str, Any]:
    return {
        "request_binding": binding.to_dict(),
        "input": {
            "ref": binding.input_ref,
            "artifact_retention": "refs_only",
        },
        "policy": {
            "ref": binding.policy_ref,
            "router_field_winner_selector": False,
            "semantic_commitment_authority": False,
        },
        "instruction_boundary": {
            "candidate_role": "evidence_only",
            "candidate_schema_version": LALM_THINKER_CANDIDATE_SCHEMA_VERSION,
            "may_emit_event_journal_events": False,
            "may_create_semantic_commitments": False,
            "may_accept_confirmation": False,
            "may_authorize_tools": False,
            "may_execute_tools": False,
            "may_control_playback": False,
            "may_emit_coverage_or_truthfulness_verdicts": False,
        },
    }


def _require_event_string(event: Mapping[str, Any], field: str) -> str:
    return _require_safe_token(event.get(field), field)


def _optional_event_string(event: Mapping[str, Any], field: str) -> str | None:
    value = event.get(field)
    if value in (None, ""):
        return None
    return _require_safe_token(value, field)


def _require_safe_token(value: object, field: str) -> str:
    if not isinstance(value, str) or value == "":
        raise LALMThinkerBindingError(f"{field} must be a non-empty string")
    _reject_unsafe_text(value, field)
    return value


def _require_safe_ref(value: object, field: str) -> str:
    value = _require_safe_token(value, field)
    if "://" not in value:
        raise LALMThinkerBindingError(f"{field} must be a safe ref")
    return value


def _reject_unsafe_text(value: str, field: str) -> None:
    variants = {value, unquote(value)}
    for variant in variants:
        if CREDENTIAL_LIKE_REF_PATTERN.search(variant):
            raise LALMThinkerBindingError(f"{field} must not contain credential-like content")
        lowered = variant.lower()
        if any(marker in lowered for marker in _DISALLOWED_REF_MARKERS):
            raise LALMThinkerBindingError(f"{field} must not reference local-only artifacts")
