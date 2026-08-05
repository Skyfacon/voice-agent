from __future__ import annotations

import pytest

from voice_agent.adapters.qwen_realtime.ephemeral_text_store import (
    EphemeralTextRefV1,
    EphemeralTextStore,
    EphemeralTextStoreError,
    SensitiveTextLease,
    SensitiveTextLeaseError,
)


def test_candidate_text_is_normalized_hashed_and_scoped_to_active_lease() -> None:
    store = EphemeralTextStore()
    metadata = store.put(
        kind="candidate",
        ref="candidate-ref://synthetic/cand-1",
        normalized_text="cafe\u0301",
        max_unicode_scalars=80,
    )

    assert metadata == EphemeralTextRefV1(
        kind="candidate",
        ref="candidate-ref://synthetic/cand-1",
        digest="850f7dc43910ff890f8879c0ed26fe697c93a067ad93a7d50f466a7028a9bf4e",
        unicode_scalar_count=4,
    )
    assert "café" not in repr(metadata)
    with store.resolve(
        metadata.ref,
        expected_kind="candidate",
        expected_digest=metadata.digest,
        max_unicode_scalars=80,
    ) as lease:
        assert isinstance(lease, SensitiveTextLease)
        assert lease.text == "café"
        controlled_lease_storage = lease._storage
        assert bytes(controlled_lease_storage) == "café".encode("utf-8")

    assert all(value == 0 for value in controlled_lease_storage)
    with pytest.raises(SensitiveTextLeaseError, match="inactive"):
        _ = lease.text


def test_discard_zeros_store_storage_in_place_and_makes_ref_stale() -> None:
    store = EphemeralTextStore()
    metadata = store.put(
        kind="asr",
        ref="text-ref://synthetic/asr-1",
        normalized_text="private transcript",
        max_unicode_scalars=200,
    )
    controlled_store_storage = store._entries[metadata.ref]._storage

    store.discard(metadata.ref)

    assert all(value == 0 for value in controlled_store_storage)
    with pytest.raises(EphemeralTextStoreError, match="not_found"):
        with store.resolve(
            metadata.ref,
            expected_kind="asr",
            expected_digest=metadata.digest,
            max_unicode_scalars=200,
        ):
            pytest.fail("discarded refs must not resolve")


def test_close_zeros_every_entry_and_is_idempotent() -> None:
    store = EphemeralTextStore()
    first = store.put(
        kind="asr",
        ref="text-ref://local/session-opaque-1",
        normalized_text="first private value",
        max_unicode_scalars=200,
    )
    second = store.put(
        kind="candidate",
        ref="candidate-ref://local/session-opaque-2",
        normalized_text="second private value",
        max_unicode_scalars=80,
    )
    controlled_storages = (
        store._entries[first.ref]._storage,
        store._entries[second.ref]._storage,
    )

    store.close()
    store.close()

    assert all(
        all(value == 0 for value in storage)
        for storage in controlled_storages
    )
    with pytest.raises(EphemeralTextStoreError, match="closed"):
        store.put(
            kind="candidate",
            ref="candidate-ref://synthetic/new",
            normalized_text="not retained",
            max_unicode_scalars=80,
        )


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    (
        ("missing_ref", "not_found"),
        ("wrong_kind", "kind_mismatch"),
        ("wrong_digest", "digest_mismatch"),
        ("narrow_bound", "bounds_mismatch"),
    ),
)
def test_resolver_fails_closed_without_echoing_sensitive_text(
    mutation: str,
    expected_error: str,
) -> None:
    sentinel = "do-not-echo-sensitive-text"
    store = EphemeralTextStore()
    metadata = store.put(
        kind="candidate",
        ref="candidate-ref://synthetic/safe-opaque-ref",
        normalized_text=sentinel,
        max_unicode_scalars=80,
    )
    ref = metadata.ref
    expected_kind = "candidate"
    expected_digest = metadata.digest
    max_unicode_scalars = 80
    if mutation == "missing_ref":
        ref = "candidate-ref://synthetic/missing"
    elif mutation == "wrong_kind":
        expected_kind = "asr"
    elif mutation == "wrong_digest":
        expected_digest = "0" * 64
    else:
        max_unicode_scalars = 5

    with pytest.raises(EphemeralTextStoreError, match=expected_error) as raised:
        with store.resolve(
            ref,
            expected_kind=expected_kind,  # type: ignore[arg-type]
            expected_digest=expected_digest,
            max_unicode_scalars=max_unicode_scalars,
        ):
            pytest.fail("invalid resolver request must not yield")

    assert sentinel not in str(raised.value)
    assert sentinel not in repr(raised.value)
    assert sentinel not in repr(store)


def test_duplicate_ref_is_rejected_without_replacing_or_echoing_content() -> None:
    store = EphemeralTextStore()
    original = store.put(
        kind="candidate",
        ref="candidate-ref://synthetic/duplicate",
        normalized_text="original private text",
        max_unicode_scalars=80,
    )

    with pytest.raises(EphemeralTextStoreError, match="duplicate_ref") as raised:
        store.put(
            kind="candidate",
            ref=original.ref,
            normalized_text="replacement private text",
            max_unicode_scalars=80,
        )

    assert "original private text" not in str(raised.value)
    assert "replacement private text" not in str(raised.value)
    with store.resolve(
        original.ref,
        expected_kind="candidate",
        expected_digest=original.digest,
        max_unicode_scalars=80,
    ) as lease:
        assert lease.text == "original private text"


@pytest.mark.parametrize(
    ("kind", "ref"),
    (
        ("candidate", "/Users/example/private/transcript"),
        ("candidate", "candidate-ref://remote/provider-owned"),
        ("asr", "candidate-ref://synthetic/wrong-kind-prefix"),
        ("candidate", "text-ref://synthetic/wrong-kind-prefix"),
    ),
)
def test_only_safe_local_or_synthetic_opaque_refs_are_accepted(
    kind: str,
    ref: str,
) -> None:
    with pytest.raises(EphemeralTextStoreError, match="invalid_ref") as raised:
        EphemeralTextStore().put(
            kind=kind,  # type: ignore[arg-type]
            ref=ref,
            normalized_text="private value",
            max_unicode_scalars=80,
        )

    assert "private value" not in str(raised.value)
    assert "/Users/example" not in str(raised.value)


@pytest.mark.parametrize(
    ("normalized_text", "max_unicode_scalars", "expected_error"),
    (
        ("x" * 81, 80, "text_overflow"),
        ("bad\ud800scalar", 80, "invalid_unicode"),
        ("short", 81, "invalid_candidate_limit"),
    ),
)
def test_candidate_store_rejects_overflow_surrogates_and_limit_above_80(
    normalized_text: str,
    max_unicode_scalars: int,
    expected_error: str,
) -> None:
    with pytest.raises(EphemeralTextStoreError, match=expected_error) as raised:
        EphemeralTextStore().put(
            kind="candidate",
            ref="candidate-ref://synthetic/bounded",
            normalized_text=normalized_text,
            max_unicode_scalars=max_unicode_scalars,
        )

    assert normalized_text not in str(raised.value)
