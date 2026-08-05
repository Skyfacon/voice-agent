from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Literal
import unicodedata

from .ephemeral_text_store import (
    EphemeralTextRefV1,
    EphemeralTextStore,
    EphemeralTextStoreError,
)
from .projections import (
    CandidateCompletionV1,
    CandidateEligibilityFactsV1,
    CandidateTranscriptCompleteV1,
)


_OPAQUE_AUDIO_FORMAT_REF = re.compile(
    r"\Aaudio-format://[A-Za-z0-9._~-]+\Z"
)
_SAFE_REASON_CODE = re.compile(r"\A[a-z][a-z0-9_]{0,95}\Z")
_SAFE_CANDIDATE_REF_SEGMENT = re.compile(r"\A[A-Za-z0-9._~-]+\Z")
_DISCARD_REASON_CODES = frozenset(
    {
        "cancelled",
        "candidate_text_unavailable",
        "discarded",
        "held",
        "missing_response_terminal",
        "rejected",
        "runner_finally",
    }
)


class CandidateQuarantineError(RuntimeError):
    """A sanitized, terminal CandidateQuarantine failure."""


@dataclass(frozen=True, slots=True)
class CandidateLimitsV1:
    max_transcript_unicode_scalars: int = 80
    max_pcm_bytes: int = 192_000
    max_pcm_chunks: int = 256
    max_audio_duration_ms: int = 2_000

    def __post_init__(self) -> None:
        values = (
            self.max_transcript_unicode_scalars,
            self.max_pcm_bytes,
            self.max_pcm_chunks,
            self.max_audio_duration_ms,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 1
            for value in values
        ):
            raise ValueError("invalid_candidate_limits")
        if self.max_transcript_unicode_scalars > 80:
            raise ValueError("invalid_max_transcript_unicode_scalars")


@dataclass(frozen=True, slots=True)
class CommittedCandidateBinding:
    turn_id: str
    utterance_id: str
    context_snapshot_id: str

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or not value.strip()
            for value in (
                self.turn_id,
                self.utterance_id,
                self.context_snapshot_id,
            )
        ):
            raise ValueError("invalid_committed_candidate_binding")


@dataclass(frozen=True, slots=True)
class CandidateDispositionV1:
    status: Literal["OPEN", "ELIGIBLE", "DISCARDED", "INELIGIBLE"]
    reason_code: str

    def __post_init__(self) -> None:
        if self.status not in {
            "OPEN",
            "ELIGIBLE",
            "DISCARDED",
            "INELIGIBLE",
        }:
            raise ValueError("invalid_candidate_disposition")
        if _SAFE_REASON_CODE.fullmatch(self.reason_code) is None:
            raise ValueError("invalid_candidate_disposition_reason")


@dataclass(frozen=True, slots=True)
class CandidatePCMManifestV1:
    candidate_pcm_manifest_digest: str
    candidate_audio_format_ref: str
    sample_rate_hz: int
    channel_count: int
    sample_width_bytes: int
    observed_pcm_chunk_count: int
    pcm_byte_count: int
    decoded_duration_ms: int
    rolling_pcm_content_digest: str


def _contiguous_pcm_byte_view(
    chunk: bytes | bytearray | memoryview,
) -> memoryview:
    if isinstance(chunk, bool) or not isinstance(
        chunk,
        (bytes, bytearray, memoryview),
    ):
        raise CandidateQuarantineError("invalid_pcm_chunk")
    try:
        view = memoryview(chunk)
        if view.ndim != 1 or not view.c_contiguous or view.nbytes < 1:
            raise CandidateQuarantineError("invalid_pcm_chunk")
        if view.format != "B" or view.itemsize != 1:
            view = view.cast("B")
        if view.ndim != 1 or not view.c_contiguous or view.nbytes < 1:
            raise CandidateQuarantineError("invalid_pcm_chunk")
        return view
    except CandidateQuarantineError:
        raise
    except (BufferError, TypeError, ValueError, NotImplementedError):
        raise CandidateQuarantineError("invalid_pcm_chunk") from None


class WipeablePCMBuffer:
    """Quarantine-owned PCM bytes with explicit in-place release."""

    __slots__ = ("_chunk_facts", "_released", "_storage")

    def __init__(self) -> None:
        self._storage = bytearray()
        self._chunk_facts: list[tuple[int, int, str]] = []
        self._released = False

    def append(self, chunk: bytes | bytearray | memoryview) -> int:
        if self._released:
            raise CandidateQuarantineError("pcm_buffer_released")
        view = _contiguous_pcm_byte_view(chunk)
        sequence = len(self._chunk_facts) + 1
        try:
            self._storage.extend(view)
            content_digest = hashlib.sha256(view).hexdigest()
        except (BufferError, TypeError, ValueError, NotImplementedError):
            raise CandidateQuarantineError("invalid_pcm_chunk") from None
        self._chunk_facts.append((sequence, view.nbytes, content_digest))
        return sequence

    @property
    def released(self) -> bool:
        return self._released

    @property
    def byte_count(self) -> int:
        return len(self._storage)

    @property
    def chunk_count(self) -> int:
        return len(self._chunk_facts)

    def manifest(
        self,
        *,
        audio_format_ref: str,
        sample_rate_hz: int,
        channels: int,
        sample_width_bytes: int = 2,
    ) -> CandidatePCMManifestV1:
        if self._released:
            raise CandidateQuarantineError("pcm_buffer_released")
        denominator = sample_rate_hz * channels * sample_width_bytes
        decoded_duration_ms = len(self._storage) * 1000 // denominator
        rolling_digest = hashlib.sha256(self._storage).hexdigest()
        manifest_payload = {
            "audio_format_ref": audio_format_ref,
            "channel_count": channels,
            "decoded_duration_ms": decoded_duration_ms,
            "observed_chunks": [
                {
                    "byte_count": byte_count,
                    "content_digest": content_digest,
                    "pcm_chunk_seq": sequence,
                }
                for sequence, byte_count, content_digest in self._chunk_facts
            ],
            "pcm_byte_count": len(self._storage),
            "rolling_pcm_content_digest": rolling_digest,
            "sample_rate_hz": sample_rate_hz,
            "sample_width_bytes": sample_width_bytes,
        }
        encoded = json.dumps(
            manifest_payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
        return CandidatePCMManifestV1(
            candidate_pcm_manifest_digest=hashlib.sha256(encoded).hexdigest(),
            candidate_audio_format_ref=audio_format_ref,
            sample_rate_hz=sample_rate_hz,
            channel_count=channels,
            sample_width_bytes=sample_width_bytes,
            observed_pcm_chunk_count=len(self._chunk_facts),
            pcm_byte_count=len(self._storage),
            decoded_duration_ms=decoded_duration_ms,
            rolling_pcm_content_digest=rolling_digest,
        )

    def release(self) -> None:
        if self._released:
            return
        for index in range(len(self._storage)):
            self._storage[index] = 0
        self._released = True

    def __repr__(self) -> str:
        return (
            "WipeablePCMBuffer("
            f"released={self._released}, "
            f"byte_count={len(self._storage)}, "
            f"chunk_count={len(self._chunk_facts)})"
        )

    def __del__(self) -> None:
        try:
            self.release()
        except Exception:
            return


class CandidateQuarantine:
    """One response-scoped, two-stage, fail-closed candidate owner."""

    __slots__ = (
        "_assistant_item_id",
        "_audio_done",
        "_audio_format_ref",
        "_binding",
        "_candidate_id",
        "_candidate_ref",
        "_candidate_text_metadata",
        "_completion",
        "_content_done",
        "_content_index",
        "_disposition",
        "_generation",
        "_input_item_ref",
        "_limits",
        "_observed_event_ids",
        "_output_index",
        "_output_item_done",
        "_output_item_id",
        "_pcm",
        "_pcm_channels",
        "_pcm_manifest",
        "_pcm_sample_rate_hz",
        "_playback_epoch",
        "_provisional_ingress_id",
        "_response_done",
        "_response_id",
        "_text_store",
        "_transcript_completion",
        "_transcript_done",
        "_transcript_storage",
    )

    def __init__(
        self,
        *,
        limits: CandidateLimitsV1 | None = None,
        text_store: EphemeralTextStore | None = None,
    ) -> None:
        self._limits = limits if limits is not None else CandidateLimitsV1()
        if not isinstance(self._limits, CandidateLimitsV1):
            raise TypeError("invalid_candidate_limits")
        self._text_store = (
            text_store if text_store is not None else EphemeralTextStore()
        )
        if not isinstance(self._text_store, EphemeralTextStore):
            raise TypeError("invalid_ephemeral_text_store")
        self._generation: int | None = None
        self._response_id: str | None = None
        self._candidate_id: str | None = None
        self._candidate_ref: str | None = None
        self._candidate_text_metadata: EphemeralTextRefV1 | None = None
        self._playback_epoch: int | None = None
        self._provisional_ingress_id: str | None = None
        self._input_item_ref: str | None = None
        self._binding: CommittedCandidateBinding | None = None
        self._assistant_item_id: str | None = None
        self._output_item_id: str | None = None
        self._output_index: int | None = None
        self._content_index: int | None = None
        self._audio_format_ref: str | None = None
        self._pcm_sample_rate_hz: int | None = None
        self._pcm_channels: int | None = None
        self._observed_event_ids: set[str] = set()
        self._transcript_storage = bytearray()
        self._pcm = WipeablePCMBuffer()
        self._transcript_done = False
        self._audio_done = False
        self._content_done = False
        self._output_item_done = False
        self._response_done = False
        self._transcript_completion: CandidateTranscriptCompleteV1 | None = None
        self._pcm_manifest: CandidatePCMManifestV1 | None = None
        self._completion: CandidateCompletionV1 | None = None
        self._disposition: CandidateDispositionV1 | None = None

    @property
    def disposition(self) -> CandidateDispositionV1:
        if self._disposition is None:
            raise CandidateQuarantineError("candidate_not_open")
        return self._disposition

    def spawn_successor(self) -> CandidateQuarantine:
        """Create the next one-response owner without releasing this owner."""
        if (
            self._disposition is None
            or self._disposition.status
            not in {"ELIGIBLE", "DISCARDED", "INELIGIBLE"}
        ):
            raise CandidateQuarantineError("predecessor_not_terminal")
        return CandidateQuarantine(
            limits=self._limits,
            text_store=self._text_store,
        )

    def open_response(
        self,
        *,
        event_id: str,
        generation: int,
        response_id: str,
        candidate_id: str,
        playback_epoch: int,
        provisional_ingress_id: str,
        input_item_ref: str,
    ) -> None:
        self._accept_event(event_id, generation, opening_response=True)
        if self._response_id is not None:
            self._fail("second_response")
        if (
            isinstance(playback_epoch, bool)
            or not isinstance(playback_epoch, int)
            or playback_epoch < 0
        ):
            raise CandidateQuarantineError("invalid_playback_epoch")
        if any(
            not isinstance(value, str) or not value.strip()
            for value in (
                response_id,
                candidate_id,
                provisional_ingress_id,
                input_item_ref,
            )
        ):
            raise CandidateQuarantineError("invalid_response_binding")
        self._generation = generation
        self._response_id = response_id
        self._candidate_id = candidate_id
        self._candidate_ref = self._make_candidate_ref(candidate_id)
        self._playback_epoch = playback_epoch
        self._provisional_ingress_id = provisional_ingress_id
        self._input_item_ref = input_item_ref
        self._disposition = CandidateDispositionV1(
            status="OPEN",
            reason_code="active",
        )

    def bind_committed_turn(
        self,
        binding: CommittedCandidateBinding,
    ) -> None:
        self._ensure_open()
        if not isinstance(binding, CommittedCandidateBinding):
            self._fail("invalid_committed_binding")
        if self._binding is not None:
            self._fail("committed_binding_immutable")
        self._binding = binding
        self._maybe_freeze_transcript_completion()
        if self._response_done:
            self._freeze_completion()

    def accept_assistant_item(
        self,
        *,
        event_id: str,
        response_id: str,
        item_id: str,
        item_type: str,
        role: str,
        generation: int,
    ) -> None:
        self._accept_event(event_id, generation)
        self._require_response(response_id)
        if item_type != "message" or role != "assistant":
            self._fail("assistant_message_required")
        if self._assistant_item_id is not None:
            self._fail("extra_assistant_item")
        if self._output_item_id is not None and self._output_item_id != item_id:
            self._fail("output_item_identity_mismatch")
        self._assistant_item_id = self._require_nonempty_identity(
            item_id,
            "invalid_output_item_id",
        )

    def accept_output_item(
        self,
        *,
        event_id: str,
        response_id: str,
        item_id: str,
        output_index: int,
        item_type: str,
        generation: int,
    ) -> None:
        self._accept_event(event_id, generation)
        self._require_response(response_id)
        if item_type == "function_call":
            self._fail("function_call_output_ineligible")
        if item_type != "message":
            self._fail("assistant_message_required")
        if self._output_item_id is not None:
            self._fail("extra_output_item")
        self._require_nonnegative_index(output_index, "invalid_output_index")
        checked_item_id = self._require_nonempty_identity(
            item_id,
            "invalid_output_item_id",
        )
        if (
            self._assistant_item_id is not None
            and self._assistant_item_id != checked_item_id
        ):
            self._fail("output_item_identity_mismatch")
        self._output_item_id = checked_item_id
        self._output_index = output_index

    def accept_content_part(
        self,
        *,
        event_id: str,
        response_id: str,
        item_id: str,
        output_index: int,
        content_index: int,
        content_type: str,
        generation: int,
    ) -> None:
        self._accept_event(event_id, generation)
        self._require_response(response_id)
        self._require_output_lifecycle_open()
        if self._content_index is not None:
            self._fail("extra_content_part")
        if content_type != "audio":
            self._fail("audio_content_required")
        self._require_joined_output(item_id, output_index)
        self._require_nonnegative_index(content_index, "invalid_content_index")
        self._content_index = content_index

    def append_transcript_delta(
        self,
        *,
        event_id: str,
        response_id: str,
        item_id: str,
        output_index: int,
        content_index: int,
        normalized_delta: str,
        generation: int,
    ) -> None:
        self._accept_event(event_id, generation)
        self._require_content_identity(
            response_id,
            item_id,
            output_index,
            content_index,
        )
        self._require_content_lifecycle_open()
        if self._transcript_done:
            self._fail("transcript_delta_after_done")
        normalized = self._normalize_transcript_delta(normalized_delta)
        encoded = bytearray(normalized.encode("utf-8"))
        for index in range(len(self._transcript_storage)):
            self._transcript_storage[index] = 0
        self._transcript_storage = encoded

    def append_pcm_delta(
        self,
        *,
        event_id: str,
        response_id: str,
        item_id: str,
        output_index: int,
        content_index: int,
        pcm_chunk: bytes | bytearray | memoryview,
        audio_format_ref: str,
        sample_rate_hz: int,
        channels: int,
        generation: int,
    ) -> None:
        self._accept_event(event_id, generation)
        self._require_content_identity(
            response_id,
            item_id,
            output_index,
            content_index,
        )
        self._require_content_lifecycle_open()
        if self._audio_done:
            self._fail("audio_delta_after_audio_done")
        self._validate_audio_config(
            audio_format_ref,
            sample_rate_hz,
            channels,
        )
        try:
            pcm_view = _contiguous_pcm_byte_view(pcm_chunk)
        except CandidateQuarantineError:
            self._fail("invalid_pcm_chunk")
        chunk_byte_count = pcm_view.nbytes
        prospective_bytes = self._pcm.byte_count + chunk_byte_count
        if (
            prospective_bytes > self._limits.max_pcm_bytes
            or self._pcm.chunk_count + 1 > self._limits.max_pcm_chunks
        ):
            self._fail("quarantine_overflow")
        assert self._pcm_sample_rate_hz is not None
        assert self._pcm_channels is not None
        duration_numerator = prospective_bytes * 1000
        duration_denominator = (
            self._pcm_sample_rate_hz * self._pcm_channels * 2
        )
        if (
            duration_numerator
            > self._limits.max_audio_duration_ms * duration_denominator
        ):
            self._fail("quarantine_overflow")
        try:
            self._pcm.append(pcm_view)
        except CandidateQuarantineError:
            self._fail("invalid_pcm_chunk")

    def mark_transcript_done(
        self,
        *,
        event_id: str,
        response_id: str,
        item_id: str,
        output_index: int,
        content_index: int,
        generation: int,
    ) -> None:
        self._accept_event(event_id, generation)
        self._require_content_identity(
            response_id,
            item_id,
            output_index,
            content_index,
        )
        self._require_content_lifecycle_open()
        if self._transcript_done:
            self._fail("duplicate_transcript_terminal")
        if not self._transcript_storage:
            self._fail("missing_candidate_transcript")
        normalized = self._transcript_storage.decode("utf-8")
        assert self._candidate_ref is not None
        try:
            metadata = self._text_store.put(
                kind="candidate",
                ref=self._candidate_ref,
                normalized_text=normalized,
                max_unicode_scalars=self._limits.max_transcript_unicode_scalars,
            )
        except EphemeralTextStoreError:
            self._fail("candidate_text_store_failure")
        self._wipe_transcript_storage()
        self._transcript_done = True
        self._transcript_completion = None
        self._candidate_ref = metadata.ref
        self._candidate_text_metadata = metadata
        self._maybe_freeze_transcript_completion(
            transcript_digest=metadata.digest,
            unicode_scalar_count=metadata.unicode_scalar_count,
        )

    def mark_audio_done(
        self,
        *,
        event_id: str,
        response_id: str,
        item_id: str,
        output_index: int,
        content_index: int,
        generation: int,
    ) -> None:
        self._accept_event(event_id, generation)
        self._require_content_identity(
            response_id,
            item_id,
            output_index,
            content_index,
        )
        self._require_content_lifecycle_open()
        if self._audio_done:
            self._fail("duplicate_audio_terminal")
        if (
            self._pcm.chunk_count < 1
            or self._audio_format_ref is None
            or self._pcm_sample_rate_hz is None
            or self._pcm_channels is None
        ):
            self._fail("missing_candidate_audio")
        if self._pcm.byte_count % (self._pcm_channels * 2) != 0:
            self._fail("unaligned_candidate_audio")
        self._pcm_manifest = self._pcm.manifest(
            audio_format_ref=self._audio_format_ref,
            sample_rate_hz=self._pcm_sample_rate_hz,
            channels=self._pcm_channels,
        )
        if self._pcm_manifest.decoded_duration_ms < 1:
            self._fail("invalid_candidate_audio_duration")
        self._audio_done = True

    def mark_content_done(
        self,
        *,
        event_id: str,
        response_id: str,
        item_id: str,
        output_index: int,
        content_index: int,
        content_type: str,
        generation: int,
    ) -> None:
        self._accept_event(event_id, generation)
        self._require_content_identity(
            response_id,
            item_id,
            output_index,
            content_index,
        )
        self._require_content_lifecycle_open()
        if content_type != "audio":
            self._fail("content_terminal_mismatch")
        if not self._transcript_done or not self._audio_done:
            self._fail("content_terminal_before_children")
        self._content_done = True

    def mark_output_item_done(
        self,
        *,
        event_id: str,
        response_id: str,
        item_id: str,
        output_index: int,
        item_type: str,
        generation: int,
    ) -> None:
        self._accept_event(event_id, generation)
        self._require_response(response_id)
        self._require_joined_output(item_id, output_index)
        self._require_output_lifecycle_open()
        if item_type != "message":
            self._fail("output_item_terminal_mismatch")
        if not self._content_done:
            self._fail("output_terminal_before_content")
        self._output_item_done = True

    def mark_response_done(
        self,
        *,
        event_id: str,
        response_id: str,
        status: str,
        output_item_ids: tuple[str, ...],
        generation: int,
    ) -> None:
        self._accept_event(event_id, generation)
        self._require_response(response_id)
        if self._response_done:
            self._fail("duplicate_response_terminal")
        if status != "completed":
            self._fail("response_terminal_not_completed")
        if (
            not isinstance(output_item_ids, tuple)
            or len(output_item_ids) != 1
            or output_item_ids[0] != self._output_item_id
        ):
            self._fail("response_done_output_item_mismatch")
        if not all(
            (
                self._transcript_done,
                self._audio_done,
                self._content_done,
                self._output_item_done,
            )
        ):
            self._fail("missing_required_terminal")
        self._response_done = True
        self._freeze_completion()

    def transcript_completion(self) -> CandidateTranscriptCompleteV1 | None:
        if self._disposition is None or self._disposition.status in {
            "DISCARDED",
            "INELIGIBLE",
        }:
            return None
        return self._transcript_completion

    def completion(self) -> CandidateCompletionV1 | None:
        if self._disposition is None or self._disposition.status != "ELIGIBLE":
            return None
        return self._completion

    def require_current_transcript_completion(
        self,
        exact_object: CandidateTranscriptCompleteV1,
    ) -> CandidateTranscriptCompleteV1:
        if (
            self._disposition is None
            or self._disposition.status not in {"OPEN", "ELIGIBLE"}
            or self._transcript_completion is not exact_object
        ):
            raise CandidateQuarantineError(
                "candidate_transcript_completion_not_current"
            )
        return exact_object

    def require_current_completion(
        self,
        exact_object: CandidateCompletionV1,
    ) -> CandidateCompletionV1:
        if (
            self._disposition is None
            or self._disposition.status != "ELIGIBLE"
            or self._completion is not exact_object
        ):
            raise CandidateQuarantineError(
                "candidate_completion_not_current"
            )
        return exact_object

    def discard(self, *, reason: str) -> CandidateDispositionV1:
        if self._disposition is not None and self._disposition.status == "INELIGIBLE":
            self._release_sensitive_ownership()
            return self._disposition
        reason_code = (
            reason
            if isinstance(reason, str)
            and reason in _DISCARD_REASON_CODES
            else "discarded"
        )
        self._release_sensitive_ownership()
        self._transcript_completion = None
        self._completion = None
        self._disposition = CandidateDispositionV1(
            status="DISCARDED",
            reason_code=reason_code,
        )
        return self._disposition

    def _accept_event(
        self,
        event_id: str,
        generation: int,
        *,
        opening_response: bool = False,
    ) -> None:
        if self._response_id is None:
            if not opening_response:
                raise CandidateQuarantineError("candidate_not_open")
        else:
            self._ensure_open()
        if not isinstance(event_id, str) or not event_id.strip():
            self._reject_provider_frame("invalid_event_id")
        if (
            isinstance(generation, bool)
            or not isinstance(generation, int)
            or generation < 1
        ):
            self._reject_provider_frame("invalid_provider_generation")
        if self._generation is not None and generation != self._generation:
            self._reject_provider_frame("provider_generation_mismatch")
        if event_id in self._observed_event_ids:
            self._reject_provider_frame("duplicate_event_id")
        self._observed_event_ids.add(event_id)

    def _reject_provider_frame(self, reason_code: str) -> None:
        if self._response_id is not None and self._disposition is not None:
            self._fail(reason_code)
        raise CandidateQuarantineError(reason_code)

    def _ensure_open(self) -> None:
        if self._response_id is None or self._disposition is None:
            raise CandidateQuarantineError("candidate_not_open")
        if self._disposition.status == "ELIGIBLE":
            self._fail("event_after_response_terminal")
        if self._disposition.status != "OPEN":
            raise CandidateQuarantineError(
                f"candidate_{self._disposition.reason_code}"
            )

    def _require_response(self, response_id: str) -> None:
        if response_id != self._response_id:
            self._fail("response_identity_mismatch")

    def _require_joined_output(self, item_id: str, output_index: int) -> None:
        if (
            self._assistant_item_id is None
            or self._output_item_id is None
            or self._assistant_item_id != self._output_item_id
        ):
            self._fail("assistant_output_join_missing")
        if item_id != self._output_item_id:
            self._fail("output_item_identity_mismatch")
        if output_index != self._output_index:
            self._fail("output_index_mismatch")

    def _require_content_identity(
        self,
        response_id: str,
        item_id: str,
        output_index: int,
        content_index: int,
    ) -> None:
        self._require_response(response_id)
        self._require_joined_output(item_id, output_index)
        if self._content_index is None:
            self._fail("content_part_missing")
        if content_index != self._content_index:
            self._fail("content_index_mismatch")

    def _require_output_lifecycle_open(self) -> None:
        if self._output_item_done:
            self._fail("output_item_lifecycle_closed")

    def _require_content_lifecycle_open(self) -> None:
        self._require_output_lifecycle_open()
        if self._content_done:
            self._fail("content_lifecycle_closed")

    def _require_nonempty_identity(self, value: str, reason: str) -> str:
        if not isinstance(value, str) or not value.strip():
            self._fail(reason)
        return value

    def _require_nonnegative_index(self, value: int, reason: str) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            self._fail(reason)

    def _normalize_transcript_delta(self, delta: str) -> str:
        if not isinstance(delta, str) or not delta:
            self._fail("invalid_transcript_delta")
        if any(0xD800 <= ord(character) <= 0xDFFF for character in delta):
            self._fail("invalid_unicode")
        existing = self._transcript_storage.decode("utf-8")
        normalized = unicodedata.normalize("NFC", existing + delta)
        if any(
            0xD800 <= ord(character) <= 0xDFFF
            for character in normalized
        ):
            self._fail("invalid_unicode")
        if len(normalized) > self._limits.max_transcript_unicode_scalars:
            self._fail("transcript_overflow")
        return normalized

    def _validate_audio_config(
        self,
        audio_format_ref: str,
        sample_rate_hz: int,
        channels: int,
    ) -> None:
        if (
            not isinstance(audio_format_ref, str)
            or _OPAQUE_AUDIO_FORMAT_REF.fullmatch(audio_format_ref) is None
        ):
            self._fail("invalid_audio_format_ref")
        if (
            isinstance(sample_rate_hz, bool)
            or not isinstance(sample_rate_hz, int)
            or sample_rate_hz < 1
        ):
            self._fail("invalid_sample_rate")
        if (
            isinstance(channels, bool)
            or not isinstance(channels, int)
            or channels < 1
        ):
            self._fail("invalid_channel_count")
        if self._audio_format_ref is None:
            self._audio_format_ref = audio_format_ref
            self._pcm_sample_rate_hz = sample_rate_hz
            self._pcm_channels = channels
            return
        if (
            audio_format_ref != self._audio_format_ref
            or sample_rate_hz != self._pcm_sample_rate_hz
            or channels != self._pcm_channels
        ):
            self._fail("audio_format_immutable")

    def _maybe_freeze_transcript_completion(
        self,
        *,
        transcript_digest: str | None = None,
        unicode_scalar_count: int | None = None,
    ) -> None:
        if (
            not self._transcript_done
            or self._binding is None
            or self._transcript_completion is not None
        ):
            return
        assert self._candidate_ref is not None
        if transcript_digest is None or unicode_scalar_count is None:
            if self._candidate_text_metadata is None:
                self._fail("candidate_text_store_failure")
            transcript_digest = self._candidate_text_metadata.digest
            unicode_scalar_count = (
                self._candidate_text_metadata.unicode_scalar_count
            )
        self._verify_candidate_text_ref()
        assert self._generation is not None
        assert self._response_id is not None
        assert self._candidate_id is not None
        self._transcript_completion = CandidateTranscriptCompleteV1(
            provider_session_generation=self._generation,
            qwen_response_id=self._response_id,
            candidate_id=self._candidate_id,
            turn_id=self._binding.turn_id,
            utterance_id=self._binding.utterance_id,
            context_snapshot_id=self._binding.context_snapshot_id,
            candidate_ref=self._candidate_ref,
            candidate_transcript_digest=transcript_digest,
            candidate_unicode_scalar_count=unicode_scalar_count,
        )

    def _freeze_completion(self) -> None:
        if self._completion is not None:
            self._fail("candidate_completion_immutable")
        if self._binding is None:
            return
        self._maybe_freeze_transcript_completion()
        self._verify_candidate_text_ref()
        if (
            self._transcript_completion is None
            or self._pcm_manifest is None
            or self._binding is None
            or self._generation is None
            or self._response_id is None
            or self._output_item_id is None
            or self._output_index is None
            or self._content_index is None
            or self._candidate_id is None
            or self._playback_epoch is None
        ):
            self._fail("candidate_completion_incomplete")
        facts = CandidateEligibilityFactsV1(
            provider_session_generation=self._generation,
            qwen_response_id=self._response_id,
            qwen_output_item_id=self._output_item_id,
            qwen_output_index=self._output_index,
            qwen_content_index=self._content_index,
            candidate_id=self._candidate_id,
            turn_id=self._binding.turn_id,
            utterance_id=self._binding.utterance_id,
            context_snapshot_id=self._binding.context_snapshot_id,
            bound_playback_epoch=self._playback_epoch,
            candidate_transcript_digest=(
                self._transcript_completion.candidate_transcript_digest
            ),
            candidate_unicode_scalar_count=(
                self._transcript_completion.candidate_unicode_scalar_count
            ),
            candidate_pcm_manifest_digest=(
                self._pcm_manifest.candidate_pcm_manifest_digest
            ),
            candidate_audio_format_ref=(
                self._pcm_manifest.candidate_audio_format_ref
            ),
            candidate_audio_duration_ms=self._pcm_manifest.decoded_duration_ms,
            provider_terminal_status="completed",
        )
        assert self._candidate_ref is not None
        self._completion = CandidateCompletionV1(
            candidate_ref=self._candidate_ref,
            eligibility_facts=facts,
        )
        self._disposition = CandidateDispositionV1(
            status="ELIGIBLE",
            reason_code="completed",
        )

    def _verify_candidate_text_ref(self) -> None:
        if (
            self._candidate_ref is None
            or self._candidate_text_metadata is None
        ):
            self._fail("candidate_text_store_failure")
        try:
            with self._text_store.resolve(
                self._candidate_ref,
                expected_kind="candidate",
                expected_digest=self._candidate_text_metadata.digest,
                max_unicode_scalars=(
                    self._limits.max_transcript_unicode_scalars
                ),
            ):
                pass
        except EphemeralTextStoreError:
            self._fail("candidate_text_store_failure")

    def _fail(self, reason_code: str) -> None:
        if self._disposition is not None and self._disposition.status in {
            "DISCARDED",
            "INELIGIBLE",
        }:
            raise CandidateQuarantineError(
                f"candidate_{self._disposition.reason_code}"
            )
        self._release_sensitive_ownership()
        self._transcript_completion = None
        self._completion = None
        self._disposition = CandidateDispositionV1(
            status="INELIGIBLE",
            reason_code=reason_code,
        )
        raise CandidateQuarantineError(reason_code)

    def _release_sensitive_ownership(self) -> None:
        self._pcm.release()
        self._wipe_transcript_storage()
        if self._candidate_ref is not None:
            self._text_store.discard(self._candidate_ref)

    def _wipe_transcript_storage(self) -> None:
        for index in range(len(self._transcript_storage)):
            self._transcript_storage[index] = 0

    @staticmethod
    def _make_candidate_ref(candidate_id: str) -> str:
        if _SAFE_CANDIDATE_REF_SEGMENT.fullmatch(candidate_id) is not None:
            opaque_segment = candidate_id
        else:
            opaque_segment = hashlib.sha256(
                candidate_id.encode("utf-8", errors="replace")
            ).hexdigest()
        return f"candidate-ref://synthetic/{opaque_segment}"

    def __repr__(self) -> str:
        status = (
            "NOT_OPEN"
            if self._disposition is None
            else self._disposition.status
        )
        return (
            "CandidateQuarantine("
            f"status={status!r}, "
            f"observed_event_count={len(self._observed_event_ids)}, "
            f"transcript_terminal={self._transcript_done}, "
            f"audio_terminal={self._audio_done}, "
            f"response_terminal={self._response_done})"
        )

    def __del__(self) -> None:
        try:
            self._release_sensitive_ownership()
        except Exception:
            return


__all__ = [
    "CandidateCompletionV1",
    "CandidateDispositionV1",
    "CandidateEligibilityFactsV1",
    "CandidateLimitsV1",
    "CandidatePCMManifestV1",
    "CandidateQuarantine",
    "CandidateQuarantineError",
    "CandidateTranscriptCompleteV1",
    "CommittedCandidateBinding",
    "WipeablePCMBuffer",
]
