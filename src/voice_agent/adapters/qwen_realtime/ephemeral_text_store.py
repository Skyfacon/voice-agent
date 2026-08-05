from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import re
from typing import Iterator, Literal
import unicodedata


TextKind = Literal["asr", "candidate"]

_SAFE_REF_PATTERNS = {
    "asr": re.compile(
        r"\Atext-ref://(?:synthetic|local)/[A-Za-z0-9._~-]+"
        r"(?:/[A-Za-z0-9._~-]+)*\Z"
    ),
    "candidate": re.compile(
        r"\Acandidate-ref://(?:synthetic|local)/[A-Za-z0-9._~-]+"
        r"(?:/[A-Za-z0-9._~-]+)*\Z"
    ),
}


class EphemeralTextStoreError(ValueError):
    """A sanitized failure at the session-only text boundary."""


class SensitiveTextLeaseError(RuntimeError):
    """A sanitized use-after-scope failure."""


@dataclass(frozen=True, slots=True)
class EphemeralTextRefV1:
    kind: TextKind
    ref: str
    digest: str
    unicode_scalar_count: int


@dataclass(slots=True)
class _TextEntry:
    metadata: EphemeralTextRefV1
    _storage: bytearray = field(repr=False)


def _wipe(storage: bytearray) -> None:
    for index in range(len(storage)):
        storage[index] = 0


def _validate_limit(kind: TextKind, max_unicode_scalars: int) -> None:
    if (
        isinstance(max_unicode_scalars, bool)
        or not isinstance(max_unicode_scalars, int)
        or max_unicode_scalars < 1
    ):
        raise EphemeralTextStoreError("invalid_text_limit")
    if kind == "candidate" and max_unicode_scalars > 80:
        raise EphemeralTextStoreError("invalid_candidate_limit")


def _normalize_and_encode(text: str) -> tuple[str, bytearray]:
    if not isinstance(text, str):
        raise EphemeralTextStoreError("invalid_text")
    normalized = unicodedata.normalize("NFC", text)
    if any(0xD800 <= ord(character) <= 0xDFFF for character in normalized):
        raise EphemeralTextStoreError("invalid_unicode")
    return normalized, bytearray(normalized.encode("utf-8"))


class SensitiveTextLease:
    __slots__ = ("_active", "_storage")

    def __init__(self, storage: bytearray) -> None:
        self._storage = storage
        self._active = True

    @property
    def text(self) -> str:
        if not self._active:
            raise SensitiveTextLeaseError("sensitive_text_lease_inactive")
        return self._storage.decode("utf-8")

    def _invalidate(self) -> None:
        if self._active:
            _wipe(self._storage)
            self._active = False

    def __repr__(self) -> str:
        return f"SensitiveTextLease(active={self._active})"


class EphemeralTextStore:
    """Session-scoped wipeable UTF-8 storage with scoped resolution."""

    __slots__ = ("_closed", "_entries")

    def __init__(self) -> None:
        self._entries: dict[str, _TextEntry] = {}
        self._closed = False

    def put(
        self,
        *,
        kind: TextKind,
        ref: str,
        normalized_text: str,
        max_unicode_scalars: int,
    ) -> EphemeralTextRefV1:
        self._require_open()
        self._validate_kind_and_ref(kind, ref)
        _validate_limit(kind, max_unicode_scalars)
        if ref in self._entries:
            raise EphemeralTextStoreError("duplicate_ref")

        normalized, storage = _normalize_and_encode(normalized_text)
        scalar_count = len(normalized)
        if scalar_count > max_unicode_scalars:
            _wipe(storage)
            raise EphemeralTextStoreError("text_overflow")
        digest = hashlib.sha256(storage).hexdigest()
        metadata = EphemeralTextRefV1(
            kind=kind,
            ref=ref,
            digest=digest,
            unicode_scalar_count=scalar_count,
        )
        self._entries[ref] = _TextEntry(metadata=metadata, _storage=storage)
        return metadata

    @contextmanager
    def resolve(
        self,
        ref: str,
        *,
        expected_kind: TextKind,
        expected_digest: str,
        max_unicode_scalars: int,
    ) -> Iterator[SensitiveTextLease]:
        self._require_open()
        if expected_kind not in _SAFE_REF_PATTERNS:
            raise EphemeralTextStoreError("invalid_kind")
        _validate_limit(expected_kind, max_unicode_scalars)
        entry = self._entries.get(ref)
        if entry is None:
            raise EphemeralTextStoreError("text_ref_not_found")
        metadata = entry.metadata
        if metadata.kind != expected_kind:
            raise EphemeralTextStoreError("text_ref_kind_mismatch")
        if metadata.digest != expected_digest:
            raise EphemeralTextStoreError("text_ref_digest_mismatch")
        if metadata.unicode_scalar_count > max_unicode_scalars:
            raise EphemeralTextStoreError("text_ref_bounds_mismatch")

        lease = SensitiveTextLease(bytearray(entry._storage))
        try:
            yield lease
        finally:
            lease._invalidate()

    def discard(self, ref: str) -> None:
        entry = self._entries.pop(ref, None)
        if entry is not None:
            _wipe(entry._storage)

    def close(self) -> None:
        if self._closed:
            return
        for entry in self._entries.values():
            _wipe(entry._storage)
        self._entries.clear()
        self._closed = True

    def _require_open(self) -> None:
        if self._closed:
            raise EphemeralTextStoreError("ephemeral_text_store_closed")

    @staticmethod
    def _validate_kind_and_ref(kind: TextKind, ref: str) -> None:
        pattern = _SAFE_REF_PATTERNS.get(kind)
        if pattern is None:
            raise EphemeralTextStoreError("invalid_kind")
        if not isinstance(ref, str) or pattern.fullmatch(ref) is None:
            raise EphemeralTextStoreError("invalid_ref")

    def __repr__(self) -> str:
        return (
            "EphemeralTextStore("
            f"closed={self._closed}, entry_count={len(self._entries)})"
        )

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            return


__all__ = [
    "EphemeralTextRefV1",
    "EphemeralTextStore",
    "EphemeralTextStoreError",
    "SensitiveTextLease",
    "SensitiveTextLeaseError",
    "TextKind",
]
