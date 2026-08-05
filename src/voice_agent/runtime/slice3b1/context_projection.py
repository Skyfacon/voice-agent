from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from types import MappingProxyType
from typing import Literal, Mapping
import unicodedata

from voice_agent.events.journal import InMemoryEventJournal


class ContextProjectionError(ValueError):
    """Fail-closed error for non-canonical or over-bound context metadata."""


_OPAQUE_REF = re.compile(r"\A[a-z][a-z0-9-]{0,31}://[A-Za-z0-9._~/-]{1,220}\Z")
_OPAQUE_ID = re.compile(r"\A[A-Za-z0-9._~-]{1,128}\Z")
_ROLE = frozenset({"route_evidence", "candidate_safety", "fast_candidate", "composer"})
ContextProjectionSourceKind = Literal[
    "current_transcript",
    "committed_item",
    "dialogue_summary",
    "task_public_summary",
    "memory_hint",
]
_REF_PREFIXES = {
    "current_transcript_ref": (
        "text-ref://synthetic/",
        "text-ref://local/",
    ),
    "recent_committed_item_refs": (
        "committed-item://synthetic/",
        "committed-item://local/",
    ),
    "recent_dialogue_summary_ref": (
        "dialogue-summary://synthetic/",
        "dialogue-summary://local/",
    ),
    "active_task_public_summary_ref": (
        "task-public-summary://synthetic/",
        "task-public-summary://local/",
    ),
    "session_memory_hint_refs": (
        "memory-hint://synthetic/",
        "memory-hint://local/",
    ),
}
_SOURCE_KIND_REF_FIELD = {
    "current_transcript": "current_transcript_ref",
    "committed_item": "recent_committed_item_refs",
    "dialogue_summary": "recent_dialogue_summary_ref",
    "task_public_summary": "active_task_public_summary_ref",
    "memory_hint": "session_memory_hint_refs",
}


@dataclass(frozen=True, slots=True)
class ContextProjectionLimitsV1:
    current_transcript_chars: int
    recent_committed_items: int
    recent_dialogue_summary_chars: int
    active_task_public_summary_chars: int
    session_memory_hint_count: int
    session_memory_hint_chars: int
    total_serialized_chars: int

    def __post_init__(self) -> None:
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 1
            for value in (
                self.current_transcript_chars,
                self.recent_committed_items,
                self.recent_dialogue_summary_chars,
                self.active_task_public_summary_chars,
                self.session_memory_hint_count,
                self.session_memory_hint_chars,
                self.total_serialized_chars,
            )
        ):
            raise ContextProjectionError("invalid_context_projection_limits")


ROUTE_CONTEXT_POLICY_V1 = ContextProjectionLimitsV1(
    current_transcript_chars=2_000,
    recent_committed_items=4,
    recent_dialogue_summary_chars=2_000,
    active_task_public_summary_chars=1_000,
    session_memory_hint_count=5,
    session_memory_hint_chars=1_000,
    total_serialized_chars=8_192,
)


@dataclass(frozen=True, slots=True)
class _RegisteredContextSourceV1:
    kind: ContextProjectionSourceKind
    ref: str
    digest: str
    unicode_scalar_count: int
    json_serialized_char_count: int
    session_id: str
    source_event_id: str
    source_event_seq: int


class ContextProjectionSourceAuthorityV1:
    """Session-local, metadata-only authority for bounded context refs."""

    __slots__ = ("_entries", "_journal")

    def __init__(self, *, journal: InMemoryEventJournal) -> None:
        if not isinstance(journal, InMemoryEventJournal):
            raise ContextProjectionError("invalid_source_authority_journal")
        self._journal = journal
        self._entries: dict[str, _RegisteredContextSourceV1] = {}

    def register(
        self,
        *,
        kind: ContextProjectionSourceKind,
        ref: str,
        normalized_text: str,
        source_event_id: str,
    ) -> None:
        ref_field = _SOURCE_KIND_REF_FIELD.get(kind)
        if ref_field is None:
            raise ContextProjectionError("invalid_context_source_kind")
        _require_ref(ref, ref_field)
        _require_id(source_event_id, "source_event_id")
        if ref in self._entries:
            raise ContextProjectionError("duplicate_context_source_ref")

        events = self._journal.events()
        source_event = next(
            (
                event
                for event in events
                if event.get("event_id") == source_event_id
            ),
            None,
        )
        if source_event is None:
            raise ContextProjectionError("source_event_id is not journaled")
        digest, scalar_count, json_count = _measure_normalized_text(
            normalized_text
        )
        self._entries[ref] = _RegisteredContextSourceV1(
            kind=kind,
            ref=ref,
            digest=digest,
            unicode_scalar_count=scalar_count,
            json_serialized_char_count=json_count,
            session_id=str(source_event["session_id"]),
            source_event_id=source_event_id,
            source_event_seq=int(source_event["event_seq"]),
        )

    def _require_journal(self, journal: InMemoryEventJournal) -> None:
        if self._journal is not journal:
            raise ContextProjectionError("source_authority_journal_mismatch")

    def _require_registered(
        self,
        *,
        ref: str,
        kind: ContextProjectionSourceKind,
        session_id: str,
        source_event_ids: frozenset[str],
        events_by_id: Mapping[str, Mapping[str, object]],
    ) -> _RegisteredContextSourceV1:
        metadata = self._entries.get(ref)
        if metadata is None:
            raise ContextProjectionError("unregistered_context_source_ref")
        if metadata.kind != kind:
            raise ContextProjectionError("context_source_kind_mismatch")
        if metadata.session_id != session_id:
            raise ContextProjectionError("context_source_session_mismatch")
        if metadata.source_event_id not in source_event_ids:
            raise ContextProjectionError("context source ownership is outside snapshot")
        recorded_event = events_by_id.get(metadata.source_event_id)
        if (
            recorded_event is None
            or recorded_event.get("session_id") != metadata.session_id
            or recorded_event.get("event_seq") != metadata.source_event_seq
        ):
            raise ContextProjectionError("context_source_event_mismatch")
        return metadata

    def __repr__(self) -> str:
        return (
            "ContextProjectionSourceAuthorityV1("
            f"registered_ref_count={len(self._entries)})"
        )


@dataclass(frozen=True, slots=True)
class ContextProjectionSourceV1:
    """Metadata-only view of current-session, already committed context."""

    session_id: str
    current_transcript_ref: str
    current_transcript_char_count: int
    recent_committed_item_refs: tuple[str, ...]
    recent_dialogue_summary_ref: str | None
    recent_dialogue_summary_char_count: int
    active_task_public_summary_ref: str | None
    active_task_public_summary_char_count: int
    session_memory_hint_refs: tuple[str, ...]
    session_memory_hint_char_count: int
    source_event_ids: tuple[str, ...]
    source_event_seq: int
    provider_session_generation: int
    context_snapshot_id: str
    target_role: Literal["route_evidence", "candidate_safety", "fast_candidate", "composer"]

    def __post_init__(self) -> None:
        _require_id(self.session_id, "session_id")
        _require_ref(self.current_transcript_ref, "current_transcript_ref")
        _require_positive(
            self.current_transcript_char_count,
            "current_transcript_char_count",
        )
        _require_refs(self.recent_committed_item_refs, "recent_committed_item_refs")
        if len(self.recent_committed_item_refs) > ROUTE_CONTEXT_POLICY_V1.recent_committed_items:
            raise ContextProjectionError("recent_committed_item_refs exceeds policy")
        _require_optional_ref(self.recent_dialogue_summary_ref, "recent_dialogue_summary_ref")
        _require_bounded_count(self.recent_dialogue_summary_char_count, "recent_dialogue_summary_char_count")
        _require_optional_ref_count_consistency(
            self.recent_dialogue_summary_ref,
            self.recent_dialogue_summary_char_count,
            "recent_dialogue_summary",
        )
        _require_optional_ref(self.active_task_public_summary_ref, "active_task_public_summary_ref")
        _require_bounded_count(self.active_task_public_summary_char_count, "active_task_public_summary_char_count")
        _require_optional_ref_count_consistency(
            self.active_task_public_summary_ref,
            self.active_task_public_summary_char_count,
            "active_task_public_summary",
        )
        _require_refs(self.session_memory_hint_refs, "session_memory_hint_refs")
        if len(self.session_memory_hint_refs) > ROUTE_CONTEXT_POLICY_V1.session_memory_hint_count:
            raise ContextProjectionError("session_memory_hint_refs exceeds policy")
        _require_bounded_count(self.session_memory_hint_char_count, "session_memory_hint_char_count")
        if bool(self.session_memory_hint_refs) != (
            self.session_memory_hint_char_count > 0
        ):
            raise ContextProjectionError(
                "session_memory_hint_refs/count mismatch"
            )
        if not self.source_event_ids or any(not _OPAQUE_ID.fullmatch(item) for item in self.source_event_ids):
            raise ContextProjectionError("invalid_source_event_ids")
        _require_positive(self.source_event_seq, "source_event_seq")
        _require_positive(self.provider_session_generation, "provider_session_generation")
        _require_id(self.context_snapshot_id, "context_snapshot_id")
        if self.target_role not in _ROLE:
            raise ContextProjectionError("invalid_target_role")
        self._validate_limits()

    def _validate_limits(self) -> None:
        limits = ROUTE_CONTEXT_POLICY_V1
        if self.current_transcript_char_count > limits.current_transcript_chars:
            raise ContextProjectionError("current_transcript_char_count exceeds policy")
        if self.recent_dialogue_summary_char_count > limits.recent_dialogue_summary_chars:
            raise ContextProjectionError("recent_dialogue_summary_char_count exceeds policy")
        if self.active_task_public_summary_char_count > limits.active_task_public_summary_chars:
            raise ContextProjectionError("active_task_public_summary_char_count exceeds policy")
        if self.session_memory_hint_char_count > limits.session_memory_hint_chars:
            raise ContextProjectionError("session_memory_hint_char_count exceeds policy")
        total = (
            self.current_transcript_char_count
            + self.recent_dialogue_summary_char_count
            + self.active_task_public_summary_char_count
            + self.session_memory_hint_char_count
            + _all_ref_char_count(self)
        )
        if total > limits.total_serialized_chars:
            raise ContextProjectionError("total_serialized_chars exceeds policy")


@dataclass(frozen=True, slots=True)
class ModelContextProjectionV1:
    projection_id: str
    target_role: str
    source_event_ids: tuple[str, ...]
    context_snapshot_id: str
    source_event_seq: int
    provider_session_generation: int
    projection_ref: str
    policy_version: Literal["route_context.v1"]
    redaction_status: Literal["metadata_only"]
    output_mode: Literal["mock"]
    serialized_char_count: int
    event: Mapping[str, object]


def build_context_projection(
    *,
    journal: InMemoryEventJournal,
    event_id: str,
    source: ContextProjectionSourceV1,
    source_authority: ContextProjectionSourceAuthorityV1,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
) -> ModelContextProjectionV1:
    """Append an immutable, ref-only projection from current session state."""
    if not isinstance(journal, InMemoryEventJournal):
        raise ContextProjectionError("invalid_journal")
    _require_id(event_id, "event_id")
    _require_positive(created_monotonic_ms, "created_monotonic_ms", allow_zero=True)
    _require_positive(created_wall_clock_ms, "created_wall_clock_ms", allow_zero=True)
    if not isinstance(source_authority, ContextProjectionSourceAuthorityV1):
        raise ContextProjectionError("invalid_source_authority")
    source_authority._require_journal(journal)
    events = journal.events()
    if not events or source.session_id != events[0]["session_id"]:
        raise ContextProjectionError("source session does not match journal session")
    events_by_id = {str(event["event_id"]): event for event in events}
    event_ids = set(events_by_id)
    if any(event_id_ref not in event_ids for event_id_ref in source.source_event_ids):
        raise ContextProjectionError("source_event_ids must be current-session committed events")
    if len(set(source.source_event_ids)) != len(source.source_event_ids):
        raise ContextProjectionError("source_event_ids must be unique")
    source_event_seqs = tuple(
        int(events_by_id[event_id_ref]["event_seq"])
        for event_id_ref in source.source_event_ids
    )
    if source_event_seqs != tuple(sorted(source_event_seqs)):
        raise ContextProjectionError(
            "source_event_ids must follow journal sequence order"
        )
    terminal_event_seq = int(events[-1]["event_seq"])
    if source.source_event_seq != terminal_event_seq:
        raise ContextProjectionError(
            "source_event_seq must match current journal terminal sequence"
        )
    if source_event_seqs[-1] != terminal_event_seq:
        raise ContextProjectionError(
            "source_event_ids must include current journal terminal event"
        )

    registered_sources = _require_authoritative_sources(
        source_authority=source_authority,
        source=source,
        events_by_id=events_by_id,
    )
    serialized_count = _canonical_serialized_char_count(
        source=source,
        registered_sources=registered_sources,
    )
    if serialized_count > ROUTE_CONTEXT_POLICY_V1.total_serialized_chars:
        raise ContextProjectionError("total_serialized_chars exceeds policy")
    projection_ref = _projection_ref(source, registered_sources)
    projection_digest = projection_ref.rsplit("/", 1)[-1]
    projection_id = f"projection_{source.target_role}_{projection_digest[:32]}"
    event = journal.append(
        event_name="MODEL_CONTEXT_PROJECTION_EMITTED",
        event_id=event_id,
        source_module="slice3b1_context_projection",
        caused_by_event_id=source.source_event_ids[-1],
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
        trace_redaction_level="metadata_only",
        projection_id=projection_id,
        target_role=source.target_role,
        source_event_ids=source.source_event_ids,
        context_snapshot_id=source.context_snapshot_id,
        source_event_seq=source.source_event_seq,
        provider_session_generation=source.provider_session_generation,
        projection_ref=projection_ref,
        policy_version="route_context.v1",
        redaction_status="metadata_only",
        output_mode="mock",
    )
    return ModelContextProjectionV1(
        projection_id=projection_id,
        target_role=source.target_role,
        source_event_ids=source.source_event_ids,
        context_snapshot_id=source.context_snapshot_id,
        source_event_seq=source.source_event_seq,
        provider_session_generation=source.provider_session_generation,
        projection_ref=projection_ref,
        policy_version="route_context.v1",
        redaction_status="metadata_only",
        output_mode="mock",
        serialized_char_count=serialized_count,
        event=MappingProxyType(event),
    )


def _all_ref_char_count(source: ContextProjectionSourceV1) -> int:
    return (
        len(source.current_transcript_ref)
        + sum(len(ref) for ref in source.recent_committed_item_refs)
        + (
            0
            if source.recent_dialogue_summary_ref is None
            else len(source.recent_dialogue_summary_ref)
        )
        + (
            0
            if source.active_task_public_summary_ref is None
            else len(source.active_task_public_summary_ref)
        )
        + sum(len(ref) for ref in source.session_memory_hint_refs)
    )


def _projection_payload(source: ContextProjectionSourceV1) -> dict[str, object]:
    return {
        "active_task_public_summary_char_count": (
            source.active_task_public_summary_char_count
        ),
        "active_task_public_summary_ref": (
            source.active_task_public_summary_ref
        ),
        "context_snapshot_id": source.context_snapshot_id,
        "current_transcript_char_count": source.current_transcript_char_count,
        "current_transcript_ref": source.current_transcript_ref,
        "generation": source.provider_session_generation,
        "policy_version": "route_context.v1",
        "recent_committed_item_refs": source.recent_committed_item_refs,
        "recent_dialogue_summary_char_count": (
            source.recent_dialogue_summary_char_count
        ),
        "recent_dialogue_summary_ref": source.recent_dialogue_summary_ref,
        "role": source.target_role,
        "session_id": source.session_id,
        "session_memory_hint_char_count": source.session_memory_hint_char_count,
        "session_memory_hint_refs": source.session_memory_hint_refs,
        "source_event_ids": source.source_event_ids,
        "source_event_seq": source.source_event_seq,
    }


def _projection_ref(
    source: ContextProjectionSourceV1,
    registered_sources: tuple[_RegisteredContextSourceV1, ...],
) -> str:
    canonical = json.dumps(
        {
            "projection": _projection_payload(source),
            "source_manifest": tuple(
                {
                    "digest": metadata.digest,
                    "json_serialized_char_count": (
                        metadata.json_serialized_char_count
                    ),
                    "kind": metadata.kind,
                    "ref": metadata.ref,
                    "source_event_id": metadata.source_event_id,
                    "source_event_seq": metadata.source_event_seq,
                    "unicode_scalar_count": metadata.unicode_scalar_count,
                }
                for metadata in registered_sources
            ),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"context-projection://slice3b1/{hashlib.sha256(canonical).hexdigest()}"


def _require_authoritative_sources(
    *,
    source_authority: ContextProjectionSourceAuthorityV1,
    source: ContextProjectionSourceV1,
    events_by_id: Mapping[str, Mapping[str, object]],
) -> tuple[_RegisteredContextSourceV1, ...]:
    source_event_ids = frozenset(source.source_event_ids)

    def require(
        ref: str,
        kind: ContextProjectionSourceKind,
    ) -> _RegisteredContextSourceV1:
        return source_authority._require_registered(
            ref=ref,
            kind=kind,
            session_id=source.session_id,
            source_event_ids=source_event_ids,
            events_by_id=events_by_id,
        )

    current = require(source.current_transcript_ref, "current_transcript")
    committed = tuple(
        require(ref, "committed_item")
        for ref in source.recent_committed_item_refs
    )
    dialogue = (
        None
        if source.recent_dialogue_summary_ref is None
        else require(source.recent_dialogue_summary_ref, "dialogue_summary")
    )
    task = (
        None
        if source.active_task_public_summary_ref is None
        else require(
            source.active_task_public_summary_ref,
            "task_public_summary",
        )
    )
    memory = tuple(
        require(ref, "memory_hint")
        for ref in source.session_memory_hint_refs
    )

    if current.unicode_scalar_count != source.current_transcript_char_count:
        raise ContextProjectionError("current_transcript_char_count mismatch")
    if (
        (0 if dialogue is None else dialogue.unicode_scalar_count)
        != source.recent_dialogue_summary_char_count
    ):
        raise ContextProjectionError(
            "recent_dialogue_summary_char_count mismatch"
        )
    if (
        (0 if task is None else task.unicode_scalar_count)
        != source.active_task_public_summary_char_count
    ):
        raise ContextProjectionError(
            "active_task_public_summary_char_count mismatch"
        )
    if (
        sum(metadata.unicode_scalar_count for metadata in memory)
        != source.session_memory_hint_char_count
    ):
        raise ContextProjectionError("session_memory_hint_char_count mismatch")

    return (
        current,
        *committed,
        *((dialogue,) if dialogue is not None else ()),
        *((task,) if task is not None else ()),
        *memory,
    )


def _canonical_serialized_char_count(
    *,
    source: ContextProjectionSourceV1,
    registered_sources: tuple[_RegisteredContextSourceV1, ...],
) -> int:
    by_ref = {metadata.ref: metadata for metadata in registered_sources}

    def text_length(ref: str | None) -> int:
        return 4 if ref is None else by_ref[ref].json_serialized_char_count

    context_length = _json_object_char_count(
        {
            "active_task_public_summary": text_length(
                source.active_task_public_summary_ref
            ),
            "current_transcript": text_length(source.current_transcript_ref),
            "recent_committed_items": _json_array_char_count(
                tuple(
                    text_length(ref)
                    for ref in source.recent_committed_item_refs
                )
            ),
            "recent_dialogue_summary": text_length(
                source.recent_dialogue_summary_ref
            ),
            "session_memory_hints": _json_array_char_count(
                tuple(text_length(ref) for ref in source.session_memory_hint_refs)
            ),
        }
    )
    projection_length = len(
        json.dumps(
            _projection_payload(source),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return _json_object_char_count(
        {
            "context": context_length,
            "projection": projection_length,
        }
    )


def _json_array_char_count(item_lengths: tuple[int, ...]) -> int:
    return 2 + sum(item_lengths) + max(0, len(item_lengths) - 1)


def _json_object_char_count(field_lengths: Mapping[str, int]) -> int:
    return (
        2
        + sum(
            len(json.dumps(key, ensure_ascii=False)) + 1 + value_length
            for key, value_length in field_lengths.items()
        )
        + max(0, len(field_lengths) - 1)
    )


def _measure_normalized_text(
    value: object,
) -> tuple[str, int, int]:
    if not isinstance(value, str):
        raise ContextProjectionError("invalid_context_source_text")
    normalized = unicodedata.normalize("NFC", value)
    if (
        not normalized
        or any(0xD800 <= ord(character) <= 0xDFFF for character in normalized)
    ):
        raise ContextProjectionError("invalid_context_source_text")
    encoded = normalized.encode("utf-8")
    return (
        hashlib.sha256(encoded).hexdigest(),
        len(normalized),
        len(
            json.dumps(
                normalized,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        ),
    )


def _require_id(value: object, name: str) -> None:
    if not isinstance(value, str) or _OPAQUE_ID.fullmatch(value) is None:
        raise ContextProjectionError(f"invalid_{name}")


def _require_ref(value: object, name: str) -> None:
    prefixes = _REF_PREFIXES[name]
    if (
        not isinstance(value, str)
        or _OPAQUE_REF.fullmatch(value) is None
        or not value.startswith(prefixes)
    ):
        raise ContextProjectionError(f"invalid_{name}")


def _require_optional_ref(value: object, name: str) -> None:
    if value is not None:
        _require_ref(value, name)


def _require_optional_ref_count_consistency(
    ref: str | None,
    count: int,
    name: str,
) -> None:
    if (ref is None) != (count == 0):
        raise ContextProjectionError(f"{name}_ref/count mismatch")


def _require_refs(value: object, name: str) -> None:
    if not isinstance(value, tuple):
        raise ContextProjectionError(f"invalid_{name}")
    if len(set(value)) != len(value):
        raise ContextProjectionError(f"invalid_{name}")
    for item in value:
        _require_ref(item, name)


def _require_bounded_count(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContextProjectionError(f"invalid_{name}")


def _require_positive(value: object, name: str, *, allow_zero: bool = False) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < (0 if allow_zero else 1):
        raise ContextProjectionError(f"invalid_{name}")


__all__ = [
    "ContextProjectionError",
    "ContextProjectionLimitsV1",
    "ContextProjectionSourceAuthorityV1",
    "ContextProjectionSourceKind",
    "ContextProjectionSourceV1",
    "ModelContextProjectionV1",
    "ROUTE_CONTEXT_POLICY_V1",
    "build_context_projection",
]
