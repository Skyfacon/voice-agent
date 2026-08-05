from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Iterator

import pytest

from voice_agent.governance.codex_context.model import SnapshotRequest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/codex-context-snapshot"
CANDIDATE = PurePosixPath(
    "docs/governance/codex-context/AGENTS.candidate.md"
)
BASELINE_ENTRY = PurePosixPath("docs/tasks/baseline.md")
CANDIDATE_ENTRY = PurePosixPath("docs/tasks/candidate.md")
SELECTED_CARD = PurePosixPath(
    "docs/governance/codex-task-cards/TC-TEST-01.md"
)
SAFE_CODE = re.compile(r"^[A-Z][A-Z0-9_]*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _snapshot() -> object:
    return importlib.import_module(
        "voice_agent.governance.codex_context.snapshot"
    )


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ("git", *args),
        cwd=repo,
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
    )


def _write(path: Path, content: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


@pytest.fixture
def synthetic_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Snapshot Test")
    _git(repo, "config", "user.email", "snapshot@example.invalid")
    _write(
        repo / ".gitignore",
        "\n".join(
            (
                ".env",
                ".env.*",
                "diagnostics/",
                "traces/",
                "replays/local/",
                "audio/raw/",
                "__pycache__/",
                ".pytest_cache/",
                ".venv/",
                "node_modules/",
                "ignored-generic/",
                "",
            )
        ),
    )
    _write(repo / "AGENTS.md", "baseline instruction\n")
    _write(repo / CANDIDATE, "candidate instruction\n")
    _write(repo / BASELINE_ENTRY, "# Baseline task\nsame shared clause\n")
    _write(repo / CANDIDATE_ENTRY, "# Candidate task\ndifferent clause\n")
    _write(repo / "README.md", "# synthetic repository\n")
    _write(repo / "race-source/data.txt", "repository source\n")
    _write(repo / "src/run.sh", "#!/bin/sh\nprintf tracked-v1\n")
    os.chmod(repo / "src/run.sh", 0o755)
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "fixture baseline")

    # A tracked working-tree modification must be snapshotted as current bytes.
    _write(repo / "src/run.sh", "#!/bin/sh\nprintf tracked-working-tree\n")
    os.chmod(repo / "src/run.sh", 0o755)
    _write(repo / SELECTED_CARD, "# Explicit selected card\n")
    _write(repo / "unselected.txt", "must not be copied\n")
    _write(repo / ".env", "SENSITIVE_ENV_SENTINEL=1\n")
    _write(repo / "diagnostics/raw.log", "SENSITIVE_DIAGNOSTIC_SENTINEL\n")
    _write(repo / "traces/raw.json", "SENSITIVE_TRACE_SENTINEL\n")
    _write(repo / "replays/local/cache.json", "SENSITIVE_REPLAY_SENTINEL\n")
    _write(repo / "audio/raw/input.pcm", b"SENSITIVE_AUDIO_SENTINEL")
    _write(repo / "__pycache__/cache.pyc", b"CACHE")
    _write(repo / ".pytest_cache/state", "CACHE\n")
    _write(repo / ".venv/state", "CACHE\n")
    _write(repo / "node_modules/pkg/index.js", "CACHE\n")
    _write(repo / "ignored-generic/opaque.bin", "IGNORED_GENERIC_SENTINEL\n")
    (repo / "unsafe-link").symlink_to(repo / "README.md")
    if hasattr(os, "mkfifo"):
        os.mkfifo(repo / "unsafe-fifo")
    return repo


@pytest.fixture
def pair_roots(tmp_path: Path) -> Iterator[callable]:
    created: list[Path] = []
    counter = 0

    def make(suffix: str = "pair") -> Path:
        nonlocal counter
        counter += 1
        token = hashlib.sha256(
            f"{tmp_path}:{suffix}:{counter}".encode()
        ).hexdigest()[:16]
        pair = Path(tempfile.gettempdir()).resolve() / (
            f"codex-context-pytest-{token}"
        )
        assert not pair.exists() and not pair.is_symlink()
        created.append(pair)
        return pair

    yield make
    for pair in created:
        if pair.is_symlink():
            pair.unlink()
        elif pair.exists():
            shutil.rmtree(pair)


def _request(
    repo: Path,
    output_root: Path,
    *,
    baseline_entry: PurePosixPath = BASELINE_ENTRY,
    candidate_entry: PurePosixPath = CANDIDATE_ENTRY,
    selected: tuple[PurePosixPath, ...] = (SELECTED_CARD,),
) -> SnapshotRequest:
    return SnapshotRequest(
        repo_root=repo,
        output_root=output_root,
        candidate_instruction=CANDIDATE,
        baseline_entry=baseline_entry,
        candidate_entry=candidate_entry,
        selected_uncommitted=selected,
    )


def _error_code(exc: pytest.ExceptionInfo[BaseException]) -> str:
    code = getattr(exc.value, "code", "")
    assert isinstance(code, str) and SAFE_CODE.fullmatch(code)
    assert not any(marker in str(exc.value) for marker in ("/Users/", "/tmp/"))
    return code


def _cleanup(snapshot: object, pair: Path) -> None:
    snapshot.cleanup_snapshot_pair(
        pair,
        approved_parent=Path(tempfile.gettempdir()).resolve(),
    )


def _quarantines(pair: Path) -> list[Path]:
    return sorted(
        pair.parent.glob(f".{pair.name}.cleanup-*"),
        key=lambda path: path.name,
    )


def test_prepare_pair_uses_same_tracked_and_selected_uncommitted_source(
    synthetic_repo: Path,
    pair_roots: callable,
) -> None:
    snapshot = _snapshot()
    pair = pair_roots()
    manifest = snapshot.prepare_snapshot_pair(_request(synthetic_repo, pair))

    source_by_path = {
        entry.relative_path: entry for entry in manifest.source_entries
    }
    assert source_by_path[SELECTED_CARD].origin == "selected-uncommitted"
    assert source_by_path[PurePosixPath("src/run.sh")].origin == "tracked"
    assert PurePosixPath("unselected.txt") not in source_by_path
    assert [entry.relative_path for entry in manifest.source_entries] == sorted(
        source_by_path
    )
    for arm in ("baseline", "candidate"):
        assert (pair / arm / "src/run.sh").read_bytes() == (
            synthetic_repo / "src/run.sh"
        ).read_bytes()
        assert (pair / arm / SELECTED_CARD).read_bytes() == (
            synthetic_repo / SELECTED_CARD
        ).read_bytes()
        assert not (pair / arm / "unselected.txt").exists()
        assert stat.S_IMODE((pair / arm / "src/run.sh").stat().st_mode) & 0o111

    assert (pair / "baseline/AGENTS.md").read_bytes() == (
        synthetic_repo / "AGENTS.md"
    ).read_bytes()
    assert (pair / "candidate/AGENTS.md").read_bytes() == (
        synthetic_repo / CANDIDATE
    ).read_bytes()
    assert snapshot.verify_snapshot_pair(
        pair,
        approved_parent=pair.parent,
    ).passed
    _cleanup(snapshot, pair)


def test_prepare_pair_rejects_ignored_sensitive_cache_and_symlink_paths(
    synthetic_repo: Path,
    pair_roots: callable,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot()
    unsafe = [
        PurePosixPath(".env"),
        PurePosixPath("diagnostics/raw.log"),
        PurePosixPath("traces/raw.json"),
        PurePosixPath("replays/local/cache.json"),
        PurePosixPath("audio/raw/input.pcm"),
        PurePosixPath("__pycache__/cache.pyc"),
        PurePosixPath(".pytest_cache/state"),
        PurePosixPath(".venv/state"),
        PurePosixPath("node_modules/pkg/index.js"),
        PurePosixPath("ignored-generic/opaque.bin"),
        PurePosixPath("unsafe-link"),
        PurePosixPath("missing-untracked.txt"),
        PurePosixPath("../outside"),
        PurePosixPath("/absolute"),
    ]
    if (synthetic_repo / "unsafe-fifo").exists():
        unsafe.append(PurePosixPath("unsafe-fifo"))

    for index, relative in enumerate(unsafe):
        with pytest.raises(snapshot.SnapshotError) as exc:
            snapshot.collect_source_entries(
                _request(
                    synthetic_repo,
                    pair_roots(f"unsafe-{index}"),
                    selected=(SELECTED_CARD, relative),
                )
            )
        _error_code(exc)

    with pytest.raises(snapshot.SnapshotError) as exc:
        snapshot.collect_source_entries(
            _request(
                synthetic_repo,
                pair_roots("selected-tracked"),
                selected=(SELECTED_CARD, PurePosixPath("README.md")),
            )
        )
    assert _error_code(exc) == "SNAPSHOT_SELECTED_PATH_TRACKED"

    outside = synthetic_repo.parent / "selected-link-target"
    _write(outside / "file.md", "# outside\n")
    (synthetic_repo / "linked-parent").symlink_to(outside)
    with pytest.raises(snapshot.SnapshotError) as exc:
        snapshot.collect_source_entries(
            _request(
                synthetic_repo,
                pair_roots("selected-parent-symlink"),
                selected=(
                    SELECTED_CARD,
                    PurePosixPath("linked-parent/file.md"),
                ),
            )
    )
    assert _error_code(exc) == "SNAPSHOT_SOURCE_NOT_REGULAR"

    race_target = synthetic_repo.parent / "source-race-target"
    _write(race_target / "data.txt", "EXTERNAL_SOURCE_SENTINEL\n")
    saved_source = synthetic_repo.parent / "race-source-saved"
    original_open_chain = snapshot._open_source_chain
    swapped = False

    def swap_parent_after_open(
        repo_root: Path,
        relative: PurePosixPath,
    ) -> list[int]:
        nonlocal swapped
        descriptors = original_open_chain(repo_root, relative)
        if (
            not swapped
            and relative == PurePosixPath("race-source/data.txt")
        ):
            swapped = True
            (synthetic_repo / "race-source").rename(saved_source)
            (synthetic_repo / "race-source").symlink_to(
                race_target,
                target_is_directory=True,
            )
        return descriptors

    monkeypatch.setattr(
        snapshot,
        "_open_source_chain",
        swap_parent_after_open,
    )
    race_pair = pair_roots("source-parent-race")
    with pytest.raises(snapshot.SnapshotError) as exc:
        snapshot.prepare_snapshot_pair(
            _request(synthetic_repo, race_pair)
        )
    assert _error_code(exc) == "SNAPSHOT_SOURCE_CHANGED"
    assert not race_pair.exists()
    assert (race_target / "data.txt").read_text(
        encoding="utf-8"
    ) == "EXTERNAL_SOURCE_SENTINEL\n"
    (synthetic_repo / "race-source").unlink()
    saved_source.rename(synthetic_repo / "race-source")
    monkeypatch.setattr(
        snapshot,
        "_open_source_chain",
        original_open_chain,
    )

    # Required overlay inputs cannot bypass explicit source selection.
    _write(synthetic_repo / "docs/tasks/untracked.md", "# untracked task\n")
    with pytest.raises(snapshot.SnapshotError) as exc:
        snapshot.collect_source_entries(
            _request(
                synthetic_repo,
                pair_roots("unselected-overlay"),
                baseline_entry=PurePosixPath("docs/tasks/untracked.md"),
            )
    )
    assert _error_code(exc) == "SNAPSHOT_OVERLAY_NOT_SELECTED"

    # Generic ignored paths remain unsafe even if force-tracked.
    _git(synthetic_repo, "add", "-f", "ignored-generic/opaque.bin")
    _git(synthetic_repo, "commit", "-qm", "force tracked ignored path")
    with pytest.raises(snapshot.SnapshotError) as exc:
        snapshot.collect_source_entries(
            _request(synthetic_repo, pair_roots("tracked-ignored"))
        )
    assert _error_code(exc) == "SNAPSHOT_IGNORED_SOURCE_PATH"
    _git(synthetic_repo, "rm", "--cached", "ignored-generic/opaque.bin")
    _git(synthetic_repo, "commit", "-qm", "remove tracked ignored path")

    # Hard-denied names are rejected even when force-tracked.
    _write(synthetic_repo / ".env.tracked", "TRACKED_SECRET_SENTINEL=1\n")
    _git(synthetic_repo, "add", "-f", ".env.tracked")
    _git(synthetic_repo, "commit", "-qm", "force tracked unsafe path")
    with pytest.raises(snapshot.SnapshotError) as exc:
        snapshot.collect_source_entries(
            _request(synthetic_repo, pair_roots("tracked-sensitive"))
        )
    assert _error_code(exc) == "SNAPSHOT_UNSAFE_SOURCE_PATH"

    monkeypatch.setattr(snapshot, "_MAX_GIT_OUTPUT", 1)
    with pytest.raises(snapshot.SnapshotError) as exc:
        snapshot.collect_source_entries(
            _request(synthetic_repo, pair_roots("bounded-git-output"))
        )
    assert _error_code(exc) == "SNAPSHOT_GIT_OUTPUT_TOO_LARGE"


def test_prepare_refuses_to_overwrite_existing_pair(
    synthetic_repo: Path,
    pair_roots: callable,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot()
    pair = pair_roots()
    pair.mkdir()
    _write(pair / "keep.txt", "preserve\n")

    with pytest.raises(snapshot.SnapshotError) as exc:
        snapshot.prepare_snapshot_pair(_request(synthetic_repo, pair))

    assert _error_code(exc) == "SNAPSHOT_PAIR_EXISTS"
    assert (pair / "keep.txt").read_text(encoding="utf-8") == "preserve\n"

    rollback_pair = pair_roots("rollback")
    sibling = rollback_pair.parent / f"{rollback_pair.name}-sibling"
    sibling.write_text("preserve sibling\n", encoding="utf-8")
    original_write = snapshot._write_exclusive_at
    calls = 0

    def fail_after_first_write(*args: object, **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise snapshot.SnapshotError("SNAPSHOT_WRITE_FAILURE")
        original_write(*args, **kwargs)

    monkeypatch.setattr(
        snapshot,
        "_write_exclusive_at",
        fail_after_first_write,
    )
    with pytest.raises(snapshot.SnapshotError) as exc:
        snapshot.prepare_snapshot_pair(
            _request(synthetic_repo, rollback_pair)
        )
    assert _error_code(exc) == "SNAPSHOT_WRITE_FAILURE"
    assert not rollback_pair.exists()
    assert sibling.read_text(encoding="utf-8") == "preserve sibling\n"

    monkeypatch.setattr(snapshot, "_write_exclusive_at", original_write)
    unknown_pair = pair_roots("rollback-unknown")
    original_write_arm = snapshot._write_arm
    injected = False

    def inject_unknown_then_fail(*args: object, **kwargs: object) -> None:
        nonlocal injected
        original_write_arm(*args, **kwargs)
        if not injected:
            injected = True
            _write(unknown_pair / "operator-note.txt", "preserve unknown\n")
            raise snapshot.SnapshotError("SNAPSHOT_WRITE_FAILURE")

    monkeypatch.setattr(snapshot, "_write_arm", inject_unknown_then_fail)
    with pytest.raises(snapshot.SnapshotError) as exc:
        snapshot.prepare_snapshot_pair(
            _request(synthetic_repo, unknown_pair)
        )
    assert _error_code(exc) == "SNAPSHOT_WRITE_FAILURE"
    assert (unknown_pair / "operator-note.txt").read_text(
        encoding="utf-8"
    ) == "preserve unknown\n"
    assert sorted(path.name for path in unknown_pair.iterdir()) == [
        "operator-note.txt"
    ]
    (unknown_pair / "operator-note.txt").unlink()
    unknown_pair.rmdir()
    monkeypatch.setattr(snapshot, "_write_arm", original_write_arm)

    chmod_pair = pair_roots("chmod-rollback")
    original_fchmod = snapshot.os.fchmod
    fchmod_calls = 0

    def fail_pair_fchmod(descriptor: int, mode: int) -> None:
        nonlocal fchmod_calls
        fchmod_calls += 1
        if fchmod_calls == 1:
            raise OSError("injected")
        original_fchmod(descriptor, mode)

    monkeypatch.setattr(snapshot.os, "fchmod", fail_pair_fchmod)
    with pytest.raises(snapshot.SnapshotError) as exc:
        snapshot.prepare_snapshot_pair(_request(synthetic_repo, chmod_pair))
    assert _error_code(exc) == "SNAPSHOT_WRITE_FAILURE"
    assert not chmod_pair.exists()
    assert sibling.read_text(encoding="utf-8") == "preserve sibling\n"
    monkeypatch.setattr(snapshot.os, "fchmod", original_fchmod)

    replacement_pair = pair_roots("mkdir-replacement")
    saved_created_pair = (
        replacement_pair.parent / f"{replacement_pair.name}-created"
    )
    replacement_calls = 0

    def replace_created_directory_then_fail(
        descriptor: int,
        mode: int,
    ) -> None:
        nonlocal replacement_calls
        replacement_calls += 1
        if replacement_calls == 1:
            replacement_pair.rename(saved_created_pair)
            replacement_pair.mkdir(mode=0o700)
            raise OSError("injected")
        original_fchmod(descriptor, mode)

    monkeypatch.setattr(
        snapshot.os,
        "fchmod",
        replace_created_directory_then_fail,
    )
    with pytest.raises(snapshot.SnapshotError) as exc:
        snapshot.prepare_snapshot_pair(
            _request(synthetic_repo, replacement_pair)
        )
    assert _error_code(exc) == "SNAPSHOT_WRITE_FAILURE"
    assert replacement_pair.is_dir()
    assert saved_created_pair.is_dir()
    assert list(replacement_pair.iterdir()) == []
    assert list(saved_created_pair.iterdir()) == []
    replacement_pair.rmdir()
    saved_created_pair.rmdir()
    monkeypatch.setattr(snapshot.os, "fchmod", original_fchmod)
    sibling.unlink()


def test_prepare_rejects_repo_root_ancestor_and_arbitrary_output_parent(
    synthetic_repo: Path,
    tmp_path: Path,
    pair_roots: callable,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot()
    arbitrary = tmp_path / "arbitrary"
    arbitrary.mkdir()
    nested_temp = pair_roots("nested-parent")
    nested_temp.mkdir()
    invalid_roots = (
        synthetic_repo,
        synthetic_repo.parent,
        arbitrary / "pair",
        nested_temp / "nested-pair",
    )
    for root in invalid_roots:
        with pytest.raises(snapshot.SnapshotError) as exc:
            snapshot.prepare_snapshot_pair(_request(synthetic_repo, root))
        _error_code(exc)

    repo_anchor = (
        synthetic_repo / "diagnostics/codex-context/snapshots"
    )
    repo_anchor.mkdir(parents=True)
    ignored_pair = repo_anchor / "repo-ignored-pair"
    manifest = snapshot.prepare_snapshot_pair(
        _request(synthetic_repo, ignored_pair)
    )
    assert manifest.anchor_kind == "ignored-repo-diagnostics"
    assert snapshot.verify_snapshot_pair(
        ignored_pair,
        approved_parent=repo_anchor,
    ).passed
    snapshot.cleanup_snapshot_pair(
        ignored_pair,
        approved_parent=repo_anchor,
    )
    assert repo_anchor.is_dir()

    anchor_race_pair = repo_anchor / "repo-anchor-race"
    saved_diagnostics = synthetic_repo / "diagnostics-saved"
    original_write_arm = snapshot._write_arm
    moved_anchor = False

    def move_anchor_after_first_arm(*args: object, **kwargs: object) -> None:
        nonlocal moved_anchor
        original_write_arm(*args, **kwargs)
        if not moved_anchor:
            moved_anchor = True
            (synthetic_repo / "diagnostics").rename(saved_diagnostics)
            repo_anchor.mkdir(parents=True)

    monkeypatch.setattr(snapshot, "_write_arm", move_anchor_after_first_arm)
    with pytest.raises(snapshot.SnapshotError) as exc:
        snapshot.prepare_snapshot_pair(
            _request(synthetic_repo, anchor_race_pair)
        )
    assert _error_code(exc) == "SNAPSHOT_BINDING_MISMATCH"
    assert not anchor_race_pair.exists()
    assert list(
        (
            saved_diagnostics / "codex-context/snapshots"
        ).iterdir()
    ) == []
    shutil.rmtree(synthetic_repo / "diagnostics")
    saved_diagnostics.rename(synthetic_repo / "diagnostics")
    monkeypatch.setattr(snapshot, "_write_arm", original_write_arm)


def test_prepare_rejects_symlink_between_anchor_and_pair(
    synthetic_repo: Path,
    tmp_path: Path,
    pair_roots: callable,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot()
    outside = tmp_path / "outside"
    outside.mkdir()
    shutil.rmtree(synthetic_repo / "diagnostics")
    (synthetic_repo / "diagnostics").symlink_to(outside)
    (outside / "codex-context/snapshots").mkdir(parents=True)
    output = (
        synthetic_repo
        / "diagnostics/codex-context/snapshots/symlink-parent-pair"
    )

    with pytest.raises(snapshot.SnapshotError) as exc:
        snapshot.prepare_snapshot_pair(_request(synthetic_repo, output))

    assert _error_code(exc) == "SNAPSHOT_UNSAFE_ANCHOR"
    assert not (outside / "codex-context/snapshots/symlink-parent-pair").exists()

    # A pair-name swap after creation must not redirect any write or rollback.
    race_pair = pair_roots("prepare-rebind")
    saved_pair = race_pair.parent / f"{race_pair.name}-saved"
    escaped = tmp_path / "escaped-prepare-target"
    escaped.mkdir()
    original_write_arm = snapshot._write_arm
    swapped = False

    def swap_pair_before_arm_write(*args: object, **kwargs: object) -> None:
        nonlocal swapped
        if not swapped:
            swapped = True
            race_pair.rename(saved_pair)
            race_pair.symlink_to(escaped, target_is_directory=True)
        original_write_arm(*args, **kwargs)

    monkeypatch.setattr(
        snapshot,
        "_write_arm",
        swap_pair_before_arm_write,
    )
    with pytest.raises(snapshot.SnapshotError) as exc:
        snapshot.prepare_snapshot_pair(
            _request(synthetic_repo, race_pair)
        )
    assert _error_code(exc) == "SNAPSHOT_BINDING_MISMATCH"
    assert race_pair.is_symlink()
    assert not (escaped / "baseline").exists()
    assert not (escaped / "candidate").exists()
    assert not (escaped / "pair-manifest.json").exists()
    race_pair.unlink()
    assert saved_pair.is_dir()
    assert list(saved_pair.iterdir()) == []
    saved_pair.rmdir()
    monkeypatch.setattr(snapshot, "_write_arm", original_write_arm)


def test_pair_diff_matches_overlay_digests_for_same_and_different_entries(
    synthetic_repo: Path,
    pair_roots: callable,
) -> None:
    snapshot = _snapshot()
    same_pair = pair_roots("same")
    same = snapshot.prepare_snapshot_pair(
        _request(
            synthetic_repo,
            same_pair,
            candidate_entry=BASELINE_ENTRY,
        )
    )
    assert same.expected_differences == (PurePosixPath("AGENTS.md"),)
    same_verification = snapshot.verify_snapshot_pair(
        same_pair,
        approved_parent=same_pair.parent,
    )
    assert same_verification.passed
    assert same_verification.observed_differences == same.expected_differences
    _cleanup(snapshot, same_pair)

    different_pair = pair_roots("different")
    different = snapshot.prepare_snapshot_pair(
        _request(synthetic_repo, different_pair)
    )
    assert different.expected_differences == (
        PurePosixPath("AGENTS.md"),
        PurePosixPath("CODEX_TASK.md"),
    )
    assert (different_pair / "baseline/CODEX_TASK.md").read_bytes() == (
        synthetic_repo / BASELINE_ENTRY
    ).read_bytes()
    assert (different_pair / "candidate/CODEX_TASK.md").read_bytes() == (
        synthetic_repo / CANDIDATE_ENTRY
    ).read_bytes()
    _cleanup(snapshot, different_pair)

    candidate_path = synthetic_repo / CANDIDATE
    candidate_original = candidate_path.read_bytes()
    candidate_path.write_bytes((synthetic_repo / "AGENTS.md").read_bytes())
    try:
        with pytest.raises(snapshot.SnapshotError) as exc:
            snapshot.prepare_snapshot_pair(
                _request(synthetic_repo, pair_roots("identical-instructions"))
            )
        assert _error_code(exc) == "SNAPSHOT_IDENTICAL_INSTRUCTIONS"
    finally:
        candidate_path.write_bytes(candidate_original)


def test_manifest_contains_only_safe_sorted_metadata_and_sha256(
    synthetic_repo: Path,
    pair_roots: callable,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot()
    pair = pair_roots()
    manifest = snapshot.prepare_snapshot_pair(_request(synthetic_repo, pair))
    raw = (pair / "pair-manifest.json").read_text(encoding="utf-8")
    payload = json.loads(raw)
    sentinel = json.loads(
        (pair / ".codex-context-snapshot-pair.v1").read_text(encoding="utf-8")
    )

    assert set(payload) == {
        "anchor_digest",
        "anchor_kind",
        "expected_differences",
        "pair_digest",
        "pair_name",
        "schema",
        "source_entries",
    }
    assert set(sentinel) == {
        "anchor_digest",
        "anchor_kind",
        "pair_digest",
        "pair_name",
        "schema",
    }
    assert payload["schema"] == "voice_agent.codex_context.snapshot_pair.v1"
    assert payload["pair_name"] == pair.name
    assert SHA256.fullmatch(payload["pair_digest"])
    assert SHA256.fullmatch(payload["anchor_digest"])
    assert payload["source_entries"] == sorted(
        payload["source_entries"],
        key=lambda item: item["relative_path"],
    )
    assert all(
        set(item) == {"origin", "relative_path", "sha256", "size_bytes"}
        and SHA256.fullmatch(item["sha256"])
        and item["origin"] in {"tracked", "selected-uncommitted"}
        for item in payload["source_entries"]
    )
    assert manifest.pair_digest == payload["pair_digest"]
    for unsafe in (
        str(synthetic_repo.resolve()),
        str(pair.parent.resolve()),
        "SENSITIVE_",
        "snapshot@example.invalid",
    ):
        assert unsafe not in raw
    assert raw == (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    )
    _cleanup(snapshot, pair)

    oversized_pair = pair_roots("oversized-manifest")
    monkeypatch.setattr(snapshot, "_MAX_MANIFEST_BYTES", 256)
    with pytest.raises(snapshot.SnapshotError) as exc:
        snapshot.prepare_snapshot_pair(
            _request(synthetic_repo, oversized_pair)
        )
    assert _error_code(exc) == "SNAPSHOT_SOURCE_TOO_LARGE"
    assert not oversized_pair.exists()


def test_verify_rejects_unexpected_difference_or_digest_drift(
    synthetic_repo: Path,
    pair_roots: callable,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot()

    pair = pair_roots("one-arm-drift")
    snapshot.prepare_snapshot_pair(_request(synthetic_repo, pair))
    _write(pair / "candidate/README.md", "# unexpected candidate drift\n")
    verification = snapshot.verify_snapshot_pair(
        pair,
        approved_parent=pair.parent,
    )
    assert not verification.passed
    assert "SNAPSHOT_UNEXPECTED_DIFFERENCE" in verification.issue_codes

    pair = pair_roots("post-read-replacement")
    snapshot.prepare_snapshot_pair(_request(synthetic_repo, pair))
    original_read = snapshot._read_bounded_regular_at
    replaced = False

    def replace_name_after_read(
        directory_fd: int,
        name: str,
        **kwargs: object,
    ) -> tuple[bytes, os.stat_result]:
        nonlocal replaced
        result = original_read(directory_fd, name, **kwargs)
        if not replaced and name == "README.md":
            replaced = True
            os.rename(
                name,
                "README.saved",
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
            )
            descriptor = os.open(
                name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o644,
                dir_fd=directory_fd,
            )
            try:
                os.write(descriptor, b"TAMPERED\n")
                os.fchmod(descriptor, 0o644)
            finally:
                os.close(descriptor)
        return result

    monkeypatch.setattr(
        snapshot,
        "_read_bounded_regular_at",
        replace_name_after_read,
    )
    verification = snapshot.verify_snapshot_pair(
        pair,
        approved_parent=pair.parent,
    )
    assert not verification.passed
    assert verification.issue_codes == ("SNAPSHOT_INVENTORY_MISMATCH",)
    assert replaced
    monkeypatch.setattr(
        snapshot,
        "_read_bounded_regular_at",
        original_read,
    )

    pair = pair_roots("same-arm-deletion")
    snapshot.prepare_snapshot_pair(_request(synthetic_repo, pair))
    (pair / "baseline/README.md").unlink()
    (pair / "candidate/README.md").unlink()
    verification = snapshot.verify_snapshot_pair(
        pair,
        approved_parent=pair.parent,
    )
    assert not verification.passed
    assert "SNAPSHOT_INVENTORY_MISMATCH" in verification.issue_codes

    pair = pair_roots("same-arm-extra")
    snapshot.prepare_snapshot_pair(_request(synthetic_repo, pair))
    _write(pair / "baseline/extra.txt", "same extra\n")
    _write(pair / "candidate/extra.txt", "same extra\n")
    verification = snapshot.verify_snapshot_pair(
        pair,
        approved_parent=pair.parent,
    )
    assert not verification.passed
    assert "SNAPSHOT_INVENTORY_MISMATCH" in verification.issue_codes

    pair = pair_roots("extra-empty-directory")
    snapshot.prepare_snapshot_pair(_request(synthetic_repo, pair))
    baseline_agents_before = (pair / "baseline/AGENTS.md").read_bytes()
    (pair / "baseline/empty/unexpected").mkdir(parents=True)
    verification = snapshot.verify_snapshot_pair(
        pair,
        approved_parent=pair.parent,
    )
    assert not verification.passed
    assert "SNAPSHOT_INVENTORY_MISMATCH" in verification.issue_codes
    with pytest.raises(snapshot.SnapshotError) as exc:
        snapshot.cleanup_snapshot_pair(pair, approved_parent=pair.parent)
    assert _error_code(exc) == "SNAPSHOT_INVENTORY_MISMATCH"
    assert (pair / "baseline/AGENTS.md").read_bytes() == baseline_agents_before

    pair = pair_roots("excessive-directory-depth")
    snapshot.prepare_snapshot_pair(_request(synthetic_repo, pair))
    current = pair / "baseline"
    for index in range(snapshot._MAX_PATH_DEPTH + 1):
        current = current / f"d{index}"
        current.mkdir()
    verification = snapshot.verify_snapshot_pair(
        pair,
        approved_parent=pair.parent,
    )
    assert not verification.passed
    assert verification.issue_codes == ("SNAPSHOT_INVENTORY_MISMATCH",)

    pair = pair_roots("manifest-unknown")
    snapshot.prepare_snapshot_pair(_request(synthetic_repo, pair))
    manifest_path = pair / "pair-manifest.json"
    raw = manifest_path.read_text(encoding="utf-8").rstrip()
    manifest_path.write_text(
        raw[:-1] + ',"unknown":"SENSITIVE_MANIFEST_SENTINEL"}\n',
        encoding="utf-8",
    )
    verification = snapshot.verify_snapshot_pair(
        pair,
        approved_parent=pair.parent,
    )
    assert not verification.passed
    assert verification.issue_codes == ("SNAPSHOT_MANIFEST_INVALID",)
    assert "SENSITIVE_MANIFEST_SENTINEL" not in repr(verification)

    pair = pair_roots("manifest-duplicate")
    snapshot.prepare_snapshot_pair(_request(synthetic_repo, pair))
    manifest_path = pair / "pair-manifest.json"
    raw = manifest_path.read_text(encoding="utf-8")
    manifest_path.write_text(
        raw.replace('"schema":', '"schema":"duplicate","schema":', 1),
        encoding="utf-8",
    )
    verification = snapshot.verify_snapshot_pair(
        pair,
        approved_parent=pair.parent,
    )
    assert not verification.passed
    assert verification.issue_codes == ("SNAPSHOT_MANIFEST_INVALID",)

    pair = pair_roots("top-level-rebind")
    snapshot.prepare_snapshot_pair(_request(synthetic_repo, pair))
    original_parse_manifest = snapshot._parse_manifest_at
    parse_calls = 0

    def replace_manifest_after_second_parse(directory_fd: int) -> object:
        nonlocal parse_calls
        manifest = original_parse_manifest(directory_fd)
        parse_calls += 1
        if parse_calls == 2:
            manifest_path = pair / "pair-manifest.json"
            saved_path = pair / "pair-manifest.saved"
            content = manifest_path.read_bytes()
            manifest_path.rename(saved_path)
            manifest_path.write_bytes(content)
            os.chmod(manifest_path, 0o644)
        return manifest

    monkeypatch.setattr(
        snapshot,
        "_parse_manifest_at",
        replace_manifest_after_second_parse,
    )
    verification = snapshot.verify_snapshot_pair(
        pair,
        approved_parent=pair.parent,
    )
    assert not verification.passed
    assert verification.issue_codes == ("SNAPSHOT_INVENTORY_MISMATCH",)
    assert parse_calls == 2
    monkeypatch.setattr(
        snapshot,
        "_parse_manifest_at",
        original_parse_manifest,
    )

    for suffix, mutate_payload in (
        (
            "manifest-anchor-list",
            lambda value: value.update({"anchor_kind": []}),
        ),
        (
            "manifest-origin-dict",
            lambda value: value["source_entries"][0].update(
                {"origin": {}}
            ),
        ),
    ):
        pair = pair_roots(suffix)
        snapshot.prepare_snapshot_pair(_request(synthetic_repo, pair))
        manifest_path = pair / "pair-manifest.json"
        malformed = json.loads(manifest_path.read_text(encoding="utf-8"))
        mutate_payload(malformed)
        manifest_path.write_text(
            json.dumps(malformed, sort_keys=True, separators=(",", ":"))
            + "\n",
            encoding="ascii",
        )
        verification = snapshot.verify_snapshot_pair(
            pair,
            approved_parent=pair.parent,
        )
        assert not verification.passed
        assert verification.issue_codes == ("SNAPSHOT_MANIFEST_INVALID",)

    pair = pair_roots("manifest-deep-json")
    snapshot.prepare_snapshot_pair(_request(synthetic_repo, pair))
    (pair / "pair-manifest.json").write_text(
        "[" * 2000 + "0" + "]" * 2000,
        encoding="ascii",
    )
    verification = snapshot.verify_snapshot_pair(
        pair,
        approved_parent=pair.parent,
    )
    assert not verification.passed
    assert verification.issue_codes == ("SNAPSHOT_MANIFEST_INVALID",)

    pair = pair_roots("manifest-wrong-type")
    snapshot.prepare_snapshot_pair(_request(synthetic_repo, pair))
    manifest_path = pair / "pair-manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["source_entries"][0]["size_bytes"] = True
    manifest_path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="ascii",
    )
    verification = snapshot.verify_snapshot_pair(
        pair,
        approved_parent=pair.parent,
    )
    assert not verification.passed
    assert verification.issue_codes == ("SNAPSHOT_MANIFEST_INVALID",)

    for suffix, mutation in (
        (
            "sentinel-unknown",
            lambda raw: raw[:-2] + ',"unknown":"redacted"}\n',
        ),
        (
            "sentinel-duplicate",
            lambda raw: raw.replace(
                '"schema":',
                '"schema":"duplicate","schema":',
                1,
            ),
        ),
    ):
        pair = pair_roots(suffix)
        snapshot.prepare_snapshot_pair(_request(synthetic_repo, pair))
        sentinel_path = pair / ".codex-context-snapshot-pair.v1"
        sentinel_path.write_text(
            mutation(sentinel_path.read_text(encoding="utf-8")),
            encoding="ascii",
        )
        verification = snapshot.verify_snapshot_pair(
            pair,
            approved_parent=pair.parent,
        )
        assert not verification.passed
        assert verification.issue_codes == ("SNAPSHOT_SENTINEL_INVALID",)

    for suffix, meta_name, expected_code in (
        (
            "manifest-noncanonical",
            "pair-manifest.json",
            "SNAPSHOT_MANIFEST_INVALID",
        ),
        (
            "sentinel-noncanonical",
            ".codex-context-snapshot-pair.v1",
            "SNAPSHOT_SENTINEL_INVALID",
        ),
    ):
        pair = pair_roots(suffix)
        snapshot.prepare_snapshot_pair(_request(synthetic_repo, pair))
        baseline_before = (pair / "baseline/AGENTS.md").read_bytes()
        meta_path = pair / meta_name
        raw = meta_path.read_text(encoding="ascii")
        meta_path.write_text(raw.replace("{", "{ ", 1), encoding="ascii")
        verification = snapshot.verify_snapshot_pair(
            pair,
            approved_parent=pair.parent,
        )
        assert not verification.passed
        assert verification.issue_codes == (expected_code,)
        with pytest.raises(snapshot.SnapshotError) as exc:
            snapshot.cleanup_snapshot_pair(
                pair,
                approved_parent=pair.parent,
            )
        assert _error_code(exc) == expected_code
        assert pair.is_dir()
        assert (pair / "baseline/AGENTS.md").read_bytes() == baseline_before
        assert _quarantines(pair) == []

    pair = pair_roots("mode-drift")
    snapshot.prepare_snapshot_pair(_request(synthetic_repo, pair))
    candidate_readme = pair / "candidate/README.md"
    os.chmod(candidate_readme, 0o600)
    verification = snapshot.verify_snapshot_pair(
        pair,
        approved_parent=pair.parent,
    )
    assert not verification.passed
    assert "SNAPSHOT_DIGEST_DRIFT" in verification.issue_codes

    pair = pair_roots("hardlink-alias")
    snapshot.prepare_snapshot_pair(_request(synthetic_repo, pair))
    candidate_readme = pair / "candidate/README.md"
    candidate_readme.unlink()
    os.link(pair / "baseline/README.md", candidate_readme)
    verification = snapshot.verify_snapshot_pair(
        pair,
        approved_parent=pair.parent,
    )
    assert not verification.passed
    assert verification.issue_codes == ("SNAPSHOT_INVENTORY_MISMATCH",)

    pair = pair_roots("file-symlink")
    snapshot.prepare_snapshot_pair(_request(synthetic_repo, pair))
    candidate_readme = pair / "candidate/README.md"
    candidate_readme.unlink()
    candidate_readme.symlink_to(pair / "baseline/README.md")
    verification = snapshot.verify_snapshot_pair(
        pair,
        approved_parent=pair.parent,
    )
    assert not verification.passed
    assert verification.issue_codes == ("SNAPSHOT_INVENTORY_MISMATCH",)

    pair = pair_roots("arm-symlink")
    snapshot.prepare_snapshot_pair(_request(synthetic_repo, pair))
    candidate_arm = pair / "candidate"
    saved_arm = pair.parent / f"{pair.name}-candidate-saved"
    candidate_arm.rename(saved_arm)
    candidate_arm.symlink_to(saved_arm)
    try:
        verification = snapshot.verify_snapshot_pair(
            pair,
            approved_parent=pair.parent,
        )
        assert not verification.passed
        assert "SNAPSHOT_INVENTORY_MISMATCH" in verification.issue_codes
    finally:
        shutil.rmtree(saved_arm)


def test_cleanup_requires_pair_sentinel_and_removes_only_manifested_paths(
    synthetic_repo: Path,
    pair_roots: callable,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot()
    anchor = Path(tempfile.gettempdir()).resolve()
    sibling = anchor / f"{pair_roots('name-source').name}-sibling"
    sibling.write_text("preserve sibling\n", encoding="utf-8")
    try:
        collision_pair = pair_roots("quarantine-collision")
        snapshot.prepare_snapshot_pair(
            _request(synthetic_repo, collision_pair)
        )
        original_token_hex = snapshot.secrets.token_hex
        fixed_token = "0" * 32
        monkeypatch.setattr(
            snapshot.secrets,
            "token_hex",
            lambda _: fixed_token,
        )
        quarantine_collision = (
            anchor
            / f".{collision_pair.name}.cleanup-{fixed_token}"
        )
        quarantine_collision.mkdir()
        _write(quarantine_collision / "keep.txt", "preserve collision\n")
        with pytest.raises(snapshot.SnapshotError) as exc:
            snapshot.cleanup_snapshot_pair(
                collision_pair,
                approved_parent=anchor,
            )
        assert _error_code(exc) == "SNAPSHOT_CLEANUP_REFUSED"
        assert collision_pair.is_dir()
        assert (
            quarantine_collision / "keep.txt"
        ).read_text(encoding="utf-8") == "preserve collision\n"
        shutil.rmtree(quarantine_collision)
        monkeypatch.setattr(
            snapshot.secrets,
            "token_hex",
            original_token_hex,
        )
        snapshot.cleanup_snapshot_pair(
            collision_pair,
            approved_parent=anchor,
        )

        identity_pair = pair_roots("cleanup-identity")
        snapshot.prepare_snapshot_pair(
            _request(synthetic_repo, identity_pair)
        )
        original_verify = snapshot._verify_open_pair
        verify_calls = 0

        def replace_after_second_verification(
            pair_fd: int,
            pair_name: str,
            bound_anchor: object,
        ) -> object:
            nonlocal verify_calls
            result = original_verify(pair_fd, pair_name, bound_anchor)
            verify_calls += 1
            if verify_calls == 2:
                quarantines = _quarantines(identity_pair)
                assert len(quarantines) == 1
                target = (
                    quarantines[0]
                    / "payload/baseline/.gitignore"
                )
                saved = target.with_name(".gitignore.saved")
                content = target.read_bytes()
                target.rename(saved)
                target.write_bytes(content)
                os.chmod(target, 0o644)
            return result

        monkeypatch.setattr(
            snapshot,
            "_verify_open_pair",
            replace_after_second_verification,
        )
        with pytest.raises(snapshot.SnapshotError) as exc:
            snapshot.cleanup_snapshot_pair(
                identity_pair,
                approved_parent=anchor,
            )
        assert _error_code(exc) == "SNAPSHOT_CLEANUP_REFUSED"
        assert identity_pair.is_dir()
        assert (identity_pair / "baseline/.gitignore").is_file()
        assert (identity_pair / "baseline/.gitignore.saved").is_file()
        monkeypatch.setattr(
            snapshot,
            "_verify_open_pair",
            original_verify,
        )

        directory_pair = pair_roots("cleanup-directory-identity")
        snapshot.prepare_snapshot_pair(
            _request(synthetic_repo, directory_pair)
        )
        verify_calls = 0

        def replace_arm_directory_after_second_verification(
            pair_fd: int,
            pair_name: str,
            bound_anchor: object,
        ) -> object:
            nonlocal verify_calls
            result = original_verify(pair_fd, pair_name, bound_anchor)
            verify_calls += 1
            if verify_calls == 2:
                quarantines = _quarantines(directory_pair)
                assert len(quarantines) == 1
                baseline = quarantines[0] / "payload/baseline"
                saved = quarantines[0] / "payload/baseline.saved"
                baseline.rename(saved)
                baseline.mkdir(mode=0o700)
                for child in list(saved.iterdir()):
                    child.rename(baseline / child.name)
            return result

        monkeypatch.setattr(
            snapshot,
            "_verify_open_pair",
            replace_arm_directory_after_second_verification,
        )
        with pytest.raises(snapshot.SnapshotError) as exc:
            snapshot.cleanup_snapshot_pair(
                directory_pair,
                approved_parent=anchor,
            )
        assert _error_code(exc) == "SNAPSHOT_CLEANUP_REFUSED"
        assert directory_pair.is_dir()
        assert (directory_pair / "baseline").is_dir()
        assert (directory_pair / "baseline.saved").is_dir()
        monkeypatch.setattr(
            snapshot,
            "_verify_open_pair",
            original_verify,
        )

        pair = pair_roots("missing-sentinel")
        snapshot.prepare_snapshot_pair(_request(synthetic_repo, pair))
        sentinel = pair / ".codex-context-snapshot-pair.v1"
        saved_sentinel = sentinel.read_bytes()
        sentinel.unlink()
        with pytest.raises(snapshot.SnapshotError) as exc:
            snapshot.cleanup_snapshot_pair(pair, approved_parent=anchor)
        assert _error_code(exc) == "SNAPSHOT_SENTINEL_INVALID"
        assert pair.is_dir()
        sentinel.write_bytes(saved_sentinel)

        _write(pair / "unexpected.txt", "must block cleanup\n")
        with pytest.raises(snapshot.SnapshotError) as exc:
            snapshot.cleanup_snapshot_pair(pair, approved_parent=anchor)
        assert _error_code(exc) == "SNAPSHOT_INVENTORY_MISMATCH"
        assert pair.is_dir()
        assert sibling.read_text(encoding="utf-8") == "preserve sibling\n"
        (pair / "unexpected.txt").unlink()

        snapshot.cleanup_snapshot_pair(pair, approved_parent=anchor)
        assert not pair.exists()
        assert sibling.read_text(encoding="utf-8") == "preserve sibling\n"

        unlink_pair = pair_roots("unlink-failure")
        snapshot.prepare_snapshot_pair(_request(synthetic_repo, unlink_pair))
        original_unlink = snapshot.os.unlink

        def fail_pair_unlink(
            path: os.PathLike[str] | str,
            *,
            dir_fd: int | None = None,
        ) -> None:
            if dir_fd is not None:
                raise OSError("injected")
            original_unlink(path)

        monkeypatch.setattr(snapshot.os, "unlink", fail_pair_unlink)
        with pytest.raises(snapshot.SnapshotError) as exc:
            snapshot.cleanup_snapshot_pair(
                unlink_pair,
                approved_parent=anchor,
            )
        assert _error_code(exc) == "SNAPSHOT_CLEANUP_FAILURE"
        assert sibling.read_text(encoding="utf-8") == "preserve sibling\n"
        assert unlink_pair.is_dir()
        monkeypatch.setattr(snapshot.os, "unlink", original_unlink)

        rmdir_pair = pair_roots("rmdir-failure")
        snapshot.prepare_snapshot_pair(_request(synthetic_repo, rmdir_pair))
        original_rmdir = snapshot.os.rmdir

        def fail_pair_rmdir(
            path: os.PathLike[str] | str,
            *,
            dir_fd: int | None = None,
        ) -> None:
            if dir_fd is not None:
                raise OSError("injected")
            original_rmdir(path)

        monkeypatch.setattr(snapshot.os, "rmdir", fail_pair_rmdir)
        with pytest.raises(snapshot.SnapshotError) as exc:
            snapshot.cleanup_snapshot_pair(
                rmdir_pair,
                approved_parent=anchor,
            )
        assert _error_code(exc) == "SNAPSHOT_CLEANUP_FAILURE"
        assert sibling.read_text(encoding="utf-8") == "preserve sibling\n"
        monkeypatch.setattr(snapshot.os, "rmdir", original_rmdir)
        for quarantine in _quarantines(rmdir_pair):
            shutil.rmtree(quarantine)
    finally:
        sibling.unlink(missing_ok=True)


def test_verify_and_cleanup_reject_wrong_anchor_arbitrary_root_and_symlink_parent(
    synthetic_repo: Path,
    tmp_path: Path,
    pair_roots: callable,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot()
    pair = pair_roots()
    snapshot.prepare_snapshot_pair(_request(synthetic_repo, pair))
    arbitrary = tmp_path / "arbitrary"
    arbitrary.mkdir()

    for action in (
        snapshot.verify_snapshot_pair,
        snapshot.cleanup_snapshot_pair,
    ):
        with pytest.raises(snapshot.SnapshotError) as exc:
            action(pair, approved_parent=arbitrary)
        _error_code(exc)
        assert pair.is_dir()

    alias = tmp_path / "temp-alias"
    alias.symlink_to(pair.parent)
    alias_pair = alias / pair.name
    for action in (
        snapshot.verify_snapshot_pair,
        snapshot.cleanup_snapshot_pair,
    ):
        with pytest.raises(snapshot.SnapshotError) as exc:
            action(alias_pair, approved_parent=alias)
        assert _error_code(exc) == "SNAPSHOT_UNSAFE_ANCHOR"
        assert pair.is_dir()

    pair_alias = pair.parent / f"{pair.name}-alias"
    pair_alias.symlink_to(pair)
    try:
        for action in (
            snapshot.verify_snapshot_pair,
            snapshot.cleanup_snapshot_pair,
        ):
            with pytest.raises(snapshot.SnapshotError) as exc:
                action(pair_alias, approved_parent=pair.parent)
            assert _error_code(exc) == "SNAPSHOT_PAIR_INVALID"
            assert pair.is_dir()
    finally:
        pair_alias.unlink()

    verify_backup = pair.parent / f"{pair.name}-verify-backup"
    external = tmp_path / "external-pair"
    external.mkdir()
    external_marker = external / "do-not-read-or-delete.txt"
    external_marker.write_text("EXTERNAL_SENTINEL\n", encoding="utf-8")
    original_parse_manifest = snapshot._parse_manifest_at
    swapped = False

    def swap_pair_after_descriptor_open(directory_fd: int) -> object:
        nonlocal swapped
        if not swapped:
            swapped = True
            pair.rename(verify_backup)
            pair.symlink_to(external)
        return original_parse_manifest(directory_fd)

    monkeypatch.setattr(
        snapshot,
        "_parse_manifest_at",
        swap_pair_after_descriptor_open,
    )
    verification = snapshot.verify_snapshot_pair(
        pair,
        approved_parent=pair.parent,
    )
    assert not verification.passed
    assert verification.issue_codes == ("SNAPSHOT_BINDING_MISMATCH",)
    assert external_marker.read_text(encoding="utf-8") == "EXTERNAL_SENTINEL\n"
    pair.unlink()
    verify_backup.rename(pair)
    monkeypatch.setattr(
        snapshot,
        "_parse_manifest_at",
        original_parse_manifest,
    )

    cleanup_backup = pair.parent / f"{pair.name}-cleanup-backup"
    original_quarantine = snapshot._quarantine_pair_at

    def swap_pair_before_quarantine(
        anchor_fd: int,
        pair_fd: int,
        pair_name: str,
    ) -> str:
        pair.rename(cleanup_backup)
        pair.symlink_to(external)
        return original_quarantine(anchor_fd, pair_fd, pair_name)

    monkeypatch.setattr(
        snapshot,
        "_quarantine_pair_at",
        swap_pair_before_quarantine,
    )
    with pytest.raises(snapshot.SnapshotError) as exc:
        snapshot.cleanup_snapshot_pair(pair, approved_parent=pair.parent)
    assert _error_code(exc) == "SNAPSHOT_CLEANUP_REFUSED"
    assert external_marker.read_text(encoding="utf-8") == "EXTERNAL_SENTINEL\n"
    pair.unlink()
    cleanup_backup.rename(pair)
    monkeypatch.setattr(
        snapshot,
        "_quarantine_pair_at",
        original_quarantine,
    )

    moved = pair.parent / f"{pair.name}-moved"
    pair.rename(moved)
    verification = snapshot.verify_snapshot_pair(
        moved,
        approved_parent=moved.parent,
    )
    assert not verification.passed
    assert "SNAPSHOT_BINDING_MISMATCH" in verification.issue_codes
    with pytest.raises(snapshot.SnapshotError) as exc:
        snapshot.cleanup_snapshot_pair(moved, approved_parent=moved.parent)
    assert _error_code(exc) == "SNAPSHOT_BINDING_MISMATCH"
    moved.rename(pair)

    repo_anchor = (
        synthetic_repo / "diagnostics/codex-context/snapshots"
    )
    repo_anchor.mkdir(parents=True)
    cross_anchor = repo_anchor / pair.name
    pair.rename(cross_anchor)
    cross_verification = snapshot.verify_snapshot_pair(
        cross_anchor,
        approved_parent=repo_anchor,
    )
    assert not cross_verification.passed
    assert "SNAPSHOT_BINDING_MISMATCH" in cross_verification.issue_codes
    with pytest.raises(snapshot.SnapshotError) as exc:
        snapshot.cleanup_snapshot_pair(
            cross_anchor,
            approved_parent=repo_anchor,
        )
    assert _error_code(exc) == "SNAPSHOT_BINDING_MISMATCH"
    cross_anchor.rename(pair)
    _cleanup(snapshot, pair)


def test_snapshot_cli_requires_exact_pair_and_approved_parent(
    synthetic_repo: Path,
    pair_roots: callable,
) -> None:
    pair = pair_roots()
    module = "voice_agent.governance.codex_context.snapshot_cli"
    base = (sys.executable, "-m", module)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    prepare = subprocess.run(
        (
            *base,
            "prepare",
            "--repo-root",
            str(synthetic_repo),
            "--output-root",
            str(pair),
            "--baseline-entry",
            str(BASELINE_ENTRY),
            "--candidate-entry",
            str(CANDIDATE_ENTRY),
            "--include-uncommitted",
            str(SELECTED_CARD),
        ),
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert prepare.returncode == 0
    prepared = json.loads(prepare.stdout)
    assert set(prepared) == {
        "entry_count",
        "pair_digest",
        "pair_name",
        "passed",
        "schema",
    }
    assert prepared["passed"] is True
    assert prepared["pair_name"] == pair.name
    assert str(synthetic_repo) not in prepare.stdout
    assert prepare.stderr == ""

    missing_parent = subprocess.run(
        (*base, "verify", "--pair-root", str(pair)),
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert missing_parent.returncode != 0
    assert str(pair) not in missing_parent.stdout + missing_parent.stderr
    assert json.loads(missing_parent.stdout) == {
        "issue_codes": ["SNAPSHOT_ARGUMENT_ERROR"],
        "passed": False,
        "schema": "voice_agent.codex_context.snapshot_cli.v1",
    }
    assert missing_parent.stderr == ""

    invalid = subprocess.run(
        (
            *base,
            "verify",
            "--pair-root",
            str(pair),
            "--approved-parent",
            str(synthetic_repo),
        ),
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert invalid.returncode == 1
    invalid_payload = json.loads(invalid.stdout)
    assert invalid_payload["passed"] is False
    assert invalid_payload["issue_codes"] == ["SNAPSHOT_UNSAFE_ANCHOR"]
    assert invalid_payload["pair_name"] == pair.name
    assert str(pair) not in invalid.stdout + invalid.stderr
    assert str(synthetic_repo) not in invalid.stdout + invalid.stderr
    assert "Traceback" not in invalid.stdout + invalid.stderr
    assert invalid.stderr == ""

    verified = subprocess.run(
        (
            *base,
            "verify",
            "--pair-root",
            str(pair),
            "--approved-parent",
            str(pair.parent),
        ),
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert verified.returncode == 0
    verification = json.loads(verified.stdout)
    assert verification["passed"] is True
    assert verification["pair_name"] == pair.name
    assert str(pair.parent) not in verified.stdout

    cleaned = subprocess.run(
        (
            *base,
            "cleanup",
            "--pair-root",
            str(pair),
            "--approved-parent",
            str(pair.parent),
        ),
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert cleaned.returncode == 0
    assert json.loads(cleaned.stdout) == {
        "pair_name": pair.name,
        "passed": True,
        "schema": "voice_agent.codex_context.snapshot_cli.v1",
    }
    assert not pair.exists()


def test_snapshot_script_entrypoint_uses_repository_python() -> None:
    content = SCRIPT.read_text(encoding="utf-8")
    mode = SCRIPT.stat().st_mode

    assert mode & stat.S_IXUSR
    assert 'PYTHON_BIN="${VOICE_AGENT_PYTHON:-python3}"' in content
    assert "voice_agent.governance.codex_context.snapshot_cli" in content
    assert 'export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"' in content
    result = subprocess.run(
        (str(SCRIPT), "--help"),
        cwd=ROOT,
        env={**os.environ, "VOICE_AGENT_PYTHON": sys.executable},
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0
    assert "prepare" in result.stdout
    assert result.stderr == ""
