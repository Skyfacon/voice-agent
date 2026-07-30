from __future__ import annotations

import hashlib
import json
import os
import re
import selectors
import secrets
import stat
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Literal, Sequence

from .model import (
    SnapshotPairManifest,
    SnapshotRequest,
    SnapshotVerification,
    SourceEntry,
)


SNAPSHOT_SCHEMA = "voice_agent.codex_context.snapshot_pair.v1"
SENTINEL_NAME = ".codex-context-snapshot-pair.v1"
MANIFEST_NAME = "pair-manifest.json"
CANDIDATE_INSTRUCTION = PurePosixPath(
    "docs/governance/codex-context/AGENTS.candidate.md"
)

_PAIR_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_GIT_OUTPUT = 16 * 1024 * 1024
_MAX_MANIFEST_BYTES = 16 * 1024 * 1024
_MAX_SENTINEL_BYTES = 4096
_MAX_SOURCE_FILE_BYTES = 64 * 1024 * 1024
_MAX_SOURCE_TOTAL_BYTES = 512 * 1024 * 1024
_MAX_SOURCE_FILES = 100_000
_MAX_PATH_DEPTH = 128
_QUARANTINE_PAYLOAD_NAME = "payload"
# POSIX cleanup is name-based even when a parent fd is supplied. The tool
# therefore isolates the pair in a random 0700 container and verifies every
# observed binding. Concurrent mutation of that private container by another
# process running as the same OS identity is outside this tooling boundary.
_TOP_LEVEL_CHILDREN = frozenset(
    {SENTINEL_NAME, MANIFEST_NAME, "baseline", "candidate"}
)
_MANIFEST_FIELDS = frozenset(
    {
        "schema",
        "pair_digest",
        "pair_name",
        "anchor_kind",
        "anchor_digest",
        "source_entries",
        "expected_differences",
    }
)
_SENTINEL_FIELDS = frozenset(
    {
        "schema",
        "pair_digest",
        "pair_name",
        "anchor_kind",
        "anchor_digest",
    }
)
_SOURCE_ENTRY_FIELDS = frozenset(
    {"relative_path", "sha256", "size_bytes", "origin"}
)
_DENIED_ROOTS = (
    ("diagnostics",),
    ("traces",),
    ("replays", "local"),
    ("audio", "raw"),
)
_DENIED_COMPONENTS = frozenset(
    {"__pycache__", ".pytest_cache", ".venv", "node_modules"}
)

AnchorKind = Literal["system-temp", "ignored-repo-diagnostics"]


class SnapshotError(RuntimeError):
    """A redacted, stable snapshot-operation failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class _SourceBlob:
    entry: SourceEntry
    content: bytes
    executable: bool


@dataclass(frozen=True)
class _InventoryEntry:
    relative_path: PurePosixPath
    sha256: str
    size_bytes: int
    mode: int
    device: int | None = None
    inode: int | None = None


@dataclass(frozen=True)
class _DirectoryIdentity:
    relative_path: PurePosixPath
    device: int
    inode: int
    mode: int


@dataclass(frozen=True)
class _ArmInventory:
    root: _DirectoryIdentity
    directories: tuple[_DirectoryIdentity, ...]
    files: tuple[_InventoryEntry, ...]


@dataclass(frozen=True)
class _QuarantinedPair:
    container_name: str
    container_fd: int


@dataclass(frozen=True)
class _CreatedNode:
    relative_path: PurePosixPath
    device: int
    inode: int
    mode: int


@dataclass(frozen=True)
class _Anchor:
    kind: AnchorKind
    canonical_path: Path
    digest: str


def _raise(code: str) -> None:
    raise SnapshotError(code)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _compact_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")


def _contains_control(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def _validate_relative_path(
    value: PurePosixPath,
    *,
    source: bool,
) -> PurePosixPath:
    if not isinstance(value, PurePosixPath):
        _raise("SNAPSHOT_UNSAFE_SOURCE_PATH")
    rendered = value.as_posix()
    if (
        not rendered
        or rendered == "."
        or value.is_absolute()
        or ".." in value.parts
        or len(value.parts) > _MAX_PATH_DEPTH
        or "\\" in rendered
        or "\x00" in rendered
        or _contains_control(rendered)
        or any(character in rendered for character in "*?[]")
    ):
        _raise("SNAPSHOT_UNSAFE_SOURCE_PATH")
    if not source:
        return value
    lowered_parts = tuple(part.casefold() for part in value.parts)
    if ".git" in lowered_parts:
        _raise("SNAPSHOT_UNSAFE_SOURCE_PATH")
    if any(
        part == ".env" or part.startswith(".env.")
        for part in lowered_parts
    ):
        _raise("SNAPSHOT_UNSAFE_SOURCE_PATH")
    if any(part in _DENIED_COMPONENTS for part in lowered_parts):
        _raise("SNAPSHOT_UNSAFE_SOURCE_PATH")
    for denied in _DENIED_ROOTS:
        if lowered_parts[: len(denied)] == denied:
            _raise("SNAPSHOT_UNSAFE_SOURCE_PATH")
    return value


def _safe_pair_name(path: Path) -> str:
    name = path.name
    if not _PAIR_NAME_RE.fullmatch(name):
        _raise("SNAPSHOT_UNSAFE_PAIR_NAME")
    return name


def _lstat(path: Path) -> os.stat_result:
    try:
        return path.lstat()
    except OSError:
        _raise("SNAPSHOT_PATH_INVALID")


def _path_lexically_absolute(path: Path) -> Path:
    if not path.is_absolute():
        _raise("SNAPSHOT_PATH_INVALID")
    return Path(os.path.abspath(os.fspath(path)))


def _require_directory(path: Path, code: str) -> None:
    try:
        metadata = path.lstat()
    except OSError:
        _raise(code)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        _raise(code)


def _require_directory_chain(root: Path, components: Sequence[str]) -> Path:
    current = root
    _require_directory(current, "SNAPSHOT_UNSAFE_ANCHOR")
    for component in components:
        current = current / component
        _require_directory(current, "SNAPSHOT_UNSAFE_ANCHOR")
    return current


def _run_git(
    repo_root: Path,
    arguments: Sequence[str],
    *,
    check: bool,
    input_bytes: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    command = ("git", *arguments)
    process: subprocess.Popen[bytes] | None = None
    selector = selectors.DefaultSelector()
    output = bytearray()
    input_offset = 0
    deadline = time.monotonic() + 20
    try:
        process = subprocess.Popen(
            command,
            cwd=repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=(
                subprocess.PIPE
                if input_bytes is not None
                else subprocess.DEVNULL
            ),
            shell=False,
        )
        if process.stdout is None:
            _raise("SNAPSHOT_GIT_FAILURE")
        os.set_blocking(process.stdout.fileno(), False)
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        if input_bytes is not None:
            if process.stdin is None:
                _raise("SNAPSHOT_GIT_FAILURE")
            os.set_blocking(process.stdin.fileno(), False)
            selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")

        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, 20)
            events = selector.select(min(remaining, 0.25))
            for key, _ in events:
                if key.data == "stdout":
                    try:
                        chunk = os.read(key.fileobj.fileno(), 64 * 1024)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                        continue
                    if len(output) + len(chunk) > _MAX_GIT_OUTPUT:
                        _raise("SNAPSHOT_GIT_OUTPUT_TOO_LARGE")
                    output.extend(chunk)
                    continue

                assert input_bytes is not None
                try:
                    written = os.write(
                        key.fileobj.fileno(),
                        input_bytes[input_offset : input_offset + 64 * 1024],
                    )
                except BlockingIOError:
                    continue
                except BrokenPipeError:
                    written = 0
                    input_offset = len(input_bytes)
                else:
                    input_offset += written
                if input_offset >= len(input_bytes) or written == 0:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(command, 20)
        returncode = process.wait(timeout=remaining)
        result = subprocess.CompletedProcess(
            command,
            returncode,
            bytes(output),
            None,
        )
    except SnapshotError:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        raise
    except (OSError, subprocess.SubprocessError):
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        _raise("SNAPSHOT_GIT_FAILURE")
    finally:
        selector.close()
        if process is not None:
            if process.stdin is not None and not process.stdin.closed:
                process.stdin.close()
            if process.stdout is not None and not process.stdout.closed:
                process.stdout.close()
    if check and result.returncode != 0:
        _raise("SNAPSHOT_GIT_FAILURE")
    return result


def _canonical_repo_root(repo_root: Path) -> Path:
    lexical = _path_lexically_absolute(repo_root)
    try:
        canonical = lexical.resolve(strict=True)
    except OSError:
        _raise("SNAPSHOT_REPO_INVALID")
    _require_directory(canonical, "SNAPSHOT_REPO_INVALID")
    result = _run_git(
        canonical,
        ("rev-parse", "--show-toplevel"),
        check=True,
    )
    try:
        declared = Path(result.stdout.rstrip(b"\n").decode("utf-8")).resolve(
            strict=True
        )
    except (OSError, UnicodeError):
        _raise("SNAPSHOT_REPO_INVALID")
    if declared != canonical:
        _raise("SNAPSHOT_REPO_INVALID")
    return canonical


def _system_anchor_aliases() -> dict[Path, Path]:
    aliases: dict[Path, Path] = {}
    for raw in (Path(tempfile.gettempdir()), Path("/tmp")):
        try:
            lexical = _path_lexically_absolute(raw)
            canonical = lexical.resolve(strict=True)
        except (OSError, SnapshotError):
            continue
        try:
            metadata = canonical.lstat()
        except OSError:
            continue
        if stat.S_ISDIR(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
            aliases[lexical] = canonical
            aliases[canonical] = canonical
    return aliases


def _anchor_digest(kind: AnchorKind, canonical_path: Path) -> str:
    identity = f"{SNAPSHOT_SCHEMA}\0{kind}\0{os.fspath(canonical_path)}"
    return _sha256(identity.encode("utf-8"))


def _repo_anchor(repo_root: Path) -> _Anchor:
    anchor = _require_directory_chain(
        repo_root,
        ("diagnostics", "codex-context", "snapshots"),
    )
    check = _run_git(
        repo_root,
        (
            "check-ignore",
            "-q",
            "--",
            "diagnostics/codex-context/snapshots",
        ),
        check=False,
    )
    if check.returncode > 1:
        _raise("SNAPSHOT_GIT_FAILURE")
    if check.returncode != 0:
        _raise("SNAPSHOT_ANCHOR_NOT_IGNORED")
    return _Anchor(
        kind="ignored-repo-diagnostics",
        canonical_path=anchor,
        digest=_anchor_digest("ignored-repo-diagnostics", anchor),
    )


def _classify_prepare_anchor(
    repo_root: Path,
    output_root: Path,
) -> tuple[_Anchor, Path]:
    output = _path_lexically_absolute(output_root)
    _safe_pair_name(output)
    aliases = _system_anchor_aliases()
    parent = output.parent
    if parent in aliases:
        canonical_parent = aliases[parent]
        canonical_output = canonical_parent / output.name
        return (
            _Anchor(
                kind="system-temp",
                canonical_path=canonical_parent,
                digest=_anchor_digest("system-temp", canonical_parent),
            ),
            canonical_output,
        )
    expected = repo_root / "diagnostics/codex-context/snapshots"
    if parent == expected:
        anchor = _repo_anchor(repo_root)
        return anchor, anchor.canonical_path / output.name
    _raise("SNAPSHOT_UNAPPROVED_PARENT")


def _classify_supplied_anchor(approved_parent: Path) -> _Anchor:
    parent = _path_lexically_absolute(approved_parent)
    aliases = _system_anchor_aliases()
    if parent in aliases:
        canonical = aliases[parent]
        return _Anchor(
            kind="system-temp",
            canonical_path=canonical,
            digest=_anchor_digest("system-temp", canonical),
        )
    if parent.parts[-3:] != ("diagnostics", "codex-context", "snapshots"):
        _raise("SNAPSHOT_UNSAFE_ANCHOR")
    repo_candidate = parent.parent.parent.parent
    repo_root = _canonical_repo_root(repo_candidate)
    expected = repo_root / "diagnostics/codex-context/snapshots"
    if parent != expected:
        _raise("SNAPSHOT_UNSAFE_ANCHOR")
    return _repo_anchor(repo_root)


def _validated_existing_pair(
    pair_root: Path,
    approved_parent: Path,
) -> tuple[_Anchor, Path]:
    pair = _path_lexically_absolute(pair_root)
    _safe_pair_name(pair)
    anchor = _classify_supplied_anchor(approved_parent)
    supplied_parent = _path_lexically_absolute(approved_parent)
    aliases = _system_anchor_aliases()
    if supplied_parent in aliases:
        canonical_pair = aliases[supplied_parent] / pair.name
        if pair.parent not in aliases:
            _raise("SNAPSHOT_UNSAFE_ANCHOR")
        if aliases[pair.parent] != anchor.canonical_path:
            _raise("SNAPSHOT_UNAPPROVED_PARENT")
    else:
        if pair.parent != supplied_parent:
            _raise("SNAPSHOT_UNAPPROVED_PARENT")
        canonical_pair = anchor.canonical_path / pair.name
    metadata = _lstat(canonical_pair)
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        _raise("SNAPSHOT_PAIR_INVALID")
    return anchor, canonical_pair


def _directory_open_flags() -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return flags


def _open_checked_directory_at(
    parent_fd: int,
    name: str,
    *,
    expected_mode: int,
) -> int:
    descriptor: int | None = None
    try:
        before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        descriptor = os.open(
            name,
            _directory_open_flags(),
            dir_fd=parent_fd,
        )
        opened = os.fstat(descriptor)
    except OSError:
        if descriptor is not None:
            os.close(descriptor)
        _raise("SNAPSHOT_PAIR_INVALID")
    if (
        stat.S_ISLNK(before.st_mode)
        or not stat.S_ISDIR(before.st_mode)
        or not stat.S_ISDIR(opened.st_mode)
        or before.st_dev != opened.st_dev
        or before.st_ino != opened.st_ino
        or stat.S_IMODE(opened.st_mode) != expected_mode
    ):
        os.close(descriptor)
        _raise("SNAPSHOT_PAIR_INVALID")
    assert descriptor is not None
    return descriptor


def _open_anchor_descriptor(anchor: _Anchor) -> int:
    if anchor.kind == "system-temp":
        descriptor: int | None = None
        try:
            descriptor = os.open(
                anchor.canonical_path,
                _directory_open_flags(),
            )
            metadata = os.fstat(descriptor)
        except OSError:
            if descriptor is not None:
                os.close(descriptor)
            _raise("SNAPSHOT_UNSAFE_ANCHOR")
        if not stat.S_ISDIR(metadata.st_mode):
            os.close(descriptor)
            _raise("SNAPSHOT_UNSAFE_ANCHOR")
        return descriptor

    repo_root = anchor.canonical_path.parent.parent.parent
    descriptor = None
    try:
        descriptor = os.open(repo_root, _directory_open_flags())
        metadata = os.fstat(descriptor)
    except OSError:
        if descriptor is not None:
            os.close(descriptor)
        _raise("SNAPSHOT_UNSAFE_ANCHOR")
    if not stat.S_ISDIR(metadata.st_mode):
        os.close(descriptor)
        _raise("SNAPSHOT_UNSAFE_ANCHOR")
    current = descriptor
    try:
        for component in ("diagnostics", "codex-context", "snapshots"):
            next_descriptor = _open_checked_directory_at(
                current,
                component,
                expected_mode=stat.S_IMODE(
                    os.stat(
                        component,
                        dir_fd=current,
                        follow_symlinks=False,
                    ).st_mode
                ),
            )
            os.close(current)
            current = next_descriptor
    except BaseException:
        try:
            os.close(current)
        except OSError:
            pass
        raise
    return current


def _anchor_descriptor_is_bound(
    anchor: _Anchor,
    descriptor: int,
) -> bool:
    if anchor.kind == "ignored-repo-diagnostics":
        repo_root = anchor.canonical_path.parent.parent.parent
        try:
            rebound = _repo_anchor(repo_root)
        except SnapshotError:
            return False
        if (
            rebound.canonical_path != anchor.canonical_path
            or rebound.digest != anchor.digest
        ):
            return False
    try:
        named = os.stat(anchor.canonical_path, follow_symlinks=False)
        opened = os.fstat(descriptor)
    except OSError:
        return False
    return (
        not stat.S_ISLNK(named.st_mode)
        and stat.S_ISDIR(named.st_mode)
        and stat.S_ISDIR(opened.st_mode)
        and named.st_dev == opened.st_dev
        and named.st_ino == opened.st_ino
    )


def _open_pair_descriptors(
    anchor: _Anchor,
    pair_name: str,
) -> tuple[int, int]:
    anchor_fd = _open_anchor_descriptor(anchor)
    try:
        pair_fd = _open_checked_directory_at(
            anchor_fd,
            pair_name,
            expected_mode=0o700,
        )
    except BaseException:
        os.close(anchor_fd)
        raise
    return anchor_fd, pair_fd


def _decode_git_paths(output: bytes) -> tuple[PurePosixPath, ...]:
    if not output:
        return ()
    pieces = output.split(b"\0")
    if pieces[-1] != b"":
        _raise("SNAPSHOT_GIT_FAILURE")
    paths: list[PurePosixPath] = []
    for raw in pieces[:-1]:
        try:
            rendered = raw.decode("utf-8")
        except UnicodeError:
            _raise("SNAPSHOT_UNSAFE_SOURCE_PATH")
        paths.append(
            _validate_relative_path(
                PurePosixPath(rendered),
                source=True,
            )
        )
    if len(set(paths)) != len(paths):
        _raise("SNAPSHOT_GIT_FAILURE")
    return tuple(sorted(paths))


def _close_descriptors(descriptors: Sequence[int]) -> None:
    for descriptor in reversed(descriptors):
        try:
            os.close(descriptor)
        except OSError:
            pass


def _open_source_chain(
    repo_root: Path,
    relative: PurePosixPath,
) -> list[int]:
    descriptors: list[int] = []
    try:
        root_fd = os.open(repo_root, _directory_open_flags())
        descriptors.append(root_fd)
        if not stat.S_ISDIR(os.fstat(root_fd).st_mode):
            _raise("SNAPSHOT_SOURCE_NOT_REGULAR")
        for component in relative.parts[:-1]:
            metadata = os.stat(
                component,
                dir_fd=descriptors[-1],
                follow_symlinks=False,
            )
            if (
                stat.S_ISLNK(metadata.st_mode)
                or not stat.S_ISDIR(metadata.st_mode)
            ):
                _raise("SNAPSHOT_SOURCE_NOT_REGULAR")
            descriptors.append(
                _open_checked_directory_at(
                    descriptors[-1],
                    component,
                    expected_mode=stat.S_IMODE(metadata.st_mode),
                )
            )
    except SnapshotError:
        _close_descriptors(descriptors)
        raise
    except OSError:
        _close_descriptors(descriptors)
        _raise("SNAPSHOT_SOURCE_NOT_REGULAR")
    return descriptors


def _source_chain_is_bound(
    relative: PurePosixPath,
    descriptors: Sequence[int],
) -> bool:
    if len(descriptors) != len(relative.parts):
        return False
    for index, component in enumerate(relative.parts[:-1]):
        try:
            expected_mode = stat.S_IMODE(
                os.fstat(descriptors[index + 1]).st_mode
            )
        except OSError:
            return False
        if not _name_binds_descriptor(
            descriptors[index],
            component,
            descriptors[index + 1],
            expected_mode=expected_mode,
        ):
            return False
    return True


def _source_leaf_metadata_at(
    parent_fd: int,
    name: str,
) -> os.stat_result:
    try:
        metadata = os.stat(
            name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
    except OSError:
        _raise("SNAPSHOT_SOURCE_NOT_REGULAR")
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
    ):
        _raise("SNAPSHOT_SOURCE_NOT_REGULAR")
    if metadata.st_size > _MAX_SOURCE_FILE_BYTES:
        _raise("SNAPSHOT_SOURCE_TOO_LARGE")
    return metadata


def _source_file_metadata(
    repo_root: Path,
    relative: PurePosixPath,
) -> os.stat_result:
    descriptors = _open_source_chain(repo_root, relative)
    try:
        metadata = _source_leaf_metadata_at(
            descriptors[-1],
            relative.name,
        )
        if not _source_chain_is_bound(relative, descriptors):
            _raise("SNAPSHOT_SOURCE_CHANGED")
        return metadata
    finally:
        _close_descriptors(descriptors)


def _read_source_once(
    repo_root: Path,
    relative: PurePosixPath,
    origin: Literal["tracked", "selected-uncommitted"],
) -> _SourceBlob:
    descriptors = _open_source_chain(repo_root, relative)
    try:
        metadata = _source_leaf_metadata_at(
            descriptors[-1],
            relative.name,
        )
        try:
            content, opened = _read_bounded_regular_at(
                descriptors[-1],
                relative.name,
                max_bytes=_MAX_SOURCE_FILE_BYTES,
                require_single_link=False,
            )
        except ValueError:
            _raise("SNAPSHOT_SOURCE_CHANGED")
        if (
            opened.st_dev != metadata.st_dev
            or opened.st_ino != metadata.st_ino
            or opened.st_size != metadata.st_size
            or opened.st_mtime_ns != metadata.st_mtime_ns
            or opened.st_ctime_ns != metadata.st_ctime_ns
            or opened.st_mode != metadata.st_mode
            or not _source_chain_is_bound(relative, descriptors)
        ):
            _raise("SNAPSHOT_SOURCE_CHANGED")
    finally:
        _close_descriptors(descriptors)
    digest = _sha256(content)
    return _SourceBlob(
        entry=SourceEntry(
            relative_path=relative,
            sha256=digest,
            size_bytes=len(content),
            origin=origin,
        ),
        content=content,
        executable=bool(opened.st_mode & 0o111),
    )


def _collect_source_blobs(request: SnapshotRequest) -> tuple[_SourceBlob, ...]:
    repo_root = _canonical_repo_root(request.repo_root)
    tracked_result = _run_git(
        repo_root,
        ("ls-files", "-z", "--"),
        check=True,
    )
    tracked = _decode_git_paths(tracked_result.stdout)
    tracked_set = set(tracked)

    selected_values: list[PurePosixPath] = []
    for value in request.selected_uncommitted:
        selected_values.append(_validate_relative_path(value, source=True))
    if len(set(selected_values)) != len(selected_values):
        _raise("SNAPSHOT_DUPLICATE_SELECTED_PATH")
    selected = tuple(sorted(selected_values))
    if len(tracked) + len(selected) > _MAX_SOURCE_FILES:
        _raise("SNAPSHOT_SOURCE_TOO_LARGE")
    if any(path in tracked_set for path in selected):
        _raise("SNAPSHOT_SELECTED_PATH_TRACKED")

    if selected:
        for path in selected:
            _source_file_metadata(repo_root, path)

    all_paths = tuple(sorted((*tracked, *selected)))
    if all_paths:
        encoded = b"".join(
            path.as_posix().encode("utf-8") + b"\0" for path in all_paths
        )
        ignored = _run_git(
            repo_root,
            ("check-ignore", "--no-index", "--stdin", "-z"),
            check=False,
            input_bytes=encoded,
        )
        if ignored.returncode > 1:
            _raise("SNAPSHOT_GIT_FAILURE")
        if ignored.returncode == 0:
            if not ignored.stdout:
                _raise("SNAPSHOT_GIT_FAILURE")
            _raise("SNAPSHOT_IGNORED_SOURCE_PATH")
        if ignored.returncode != 1:
            _raise("SNAPSHOT_GIT_FAILURE")
        if ignored.stdout:
            _raise("SNAPSHOT_GIT_FAILURE")

    required = (
        PurePosixPath("AGENTS.md"),
        _validate_relative_path(request.candidate_instruction, source=True),
        _validate_relative_path(request.baseline_entry, source=True),
        _validate_relative_path(request.candidate_entry, source=True),
    )
    available = tracked_set | set(selected)
    if any(path not in available for path in required):
        _raise("SNAPSHOT_OVERLAY_NOT_SELECTED")

    origins: dict[
        PurePosixPath,
        Literal["tracked", "selected-uncommitted"],
    ] = {path: "tracked" for path in tracked}
    origins.update({path: "selected-uncommitted" for path in selected})
    blobs: list[_SourceBlob] = []
    total_size = 0
    for relative in sorted(origins):
        blob = _read_source_once(repo_root, relative, origins[relative])
        total_size += blob.entry.size_bytes
        if total_size > _MAX_SOURCE_TOTAL_BYTES:
            _raise("SNAPSHOT_SOURCE_TOO_LARGE")
        blobs.append(blob)
    return tuple(blobs)


def collect_source_entries(
    request: SnapshotRequest,
) -> tuple[SourceEntry, ...]:
    return tuple(blob.entry for blob in _collect_source_blobs(request))


def _source_payload(entries: Sequence[SourceEntry]) -> list[dict[str, object]]:
    return [
        {
            "origin": entry.origin,
            "relative_path": entry.relative_path.as_posix(),
            "sha256": entry.sha256,
            "size_bytes": entry.size_bytes,
        }
        for entry in entries
    ]


def _inventory_payload(
    inventory: Sequence[_InventoryEntry],
) -> list[dict[str, object]]:
    return [
        {
            "mode": entry.mode,
            "relative_path": entry.relative_path.as_posix(),
            "sha256": entry.sha256,
            "size_bytes": entry.size_bytes,
        }
        for entry in inventory
    ]


def _pair_digest(
    *,
    schema: str,
    pair_name: str,
    anchor_kind: AnchorKind,
    anchor_digest: str,
    source_entries: Sequence[SourceEntry],
    expected_differences: Sequence[PurePosixPath],
    baseline_inventory: Sequence[_InventoryEntry],
    candidate_inventory: Sequence[_InventoryEntry],
) -> str:
    payload = {
        "anchor_digest": anchor_digest,
        "anchor_kind": anchor_kind,
        "baseline_inventory": _inventory_payload(baseline_inventory),
        "candidate_inventory": _inventory_payload(candidate_inventory),
        "expected_differences": [
            path.as_posix() for path in expected_differences
        ],
        "pair_name": pair_name,
        "schema": schema,
        "source_entries": _source_payload(source_entries),
    }
    return _sha256(_compact_json(payload))


def _overlay_inventory(
    blobs: Sequence[_SourceBlob],
    *,
    agents_blob: _SourceBlob,
    task_blob: _SourceBlob,
) -> tuple[_InventoryEntry, ...]:
    by_path = {
        blob.entry.relative_path: _InventoryEntry(
            relative_path=blob.entry.relative_path,
            sha256=blob.entry.sha256,
            size_bytes=blob.entry.size_bytes,
            mode=0o755 if blob.executable else 0o644,
        )
        for blob in blobs
    }
    by_path[PurePosixPath("AGENTS.md")] = _InventoryEntry(
        relative_path=PurePosixPath("AGENTS.md"),
        sha256=agents_blob.entry.sha256,
        size_bytes=agents_blob.entry.size_bytes,
        mode=0o755 if agents_blob.executable else 0o644,
    )
    by_path[PurePosixPath("CODEX_TASK.md")] = _InventoryEntry(
        relative_path=PurePosixPath("CODEX_TASK.md"),
        sha256=task_blob.entry.sha256,
        size_bytes=task_blob.entry.size_bytes,
        mode=0o755 if task_blob.executable else 0o644,
    )
    return tuple(by_path[path] for path in sorted(by_path))


def _validate_inventory_bounds(
    inventory: Sequence[_InventoryEntry],
) -> None:
    if (
        len(inventory) > _MAX_SOURCE_FILES
        or sum(entry.size_bytes for entry in inventory)
        > _MAX_SOURCE_TOTAL_BYTES
    ):
        _raise("SNAPSHOT_SOURCE_TOO_LARGE")


def _validate_component(name: str) -> str:
    if (
        not name
        or "/" in name
        or name in {".", ".."}
        or _contains_control(name)
    ):
        _raise("SNAPSHOT_WRITE_FAILURE")
    return name


def _create_directory_at(parent_fd: int, name: str) -> int:
    component = _validate_component(name)
    created = False
    descriptor: int | None = None
    try:
        os.mkdir(component, 0o700, dir_fd=parent_fd)
        created = True
        descriptor = _open_checked_directory_at(
            parent_fd,
            component,
            expected_mode=0o700,
        )
        os.fchmod(descriptor, 0o700)
        if stat.S_IMODE(os.fstat(descriptor).st_mode) != 0o700:
            _raise("SNAPSHOT_WRITE_FAILURE")
        return descriptor
    except BaseException as error:
        if descriptor is not None:
            if created:
                try:
                    expected_mode = stat.S_IMODE(
                        os.fstat(descriptor).st_mode
                    )
                    if _name_binds_descriptor(
                        parent_fd,
                        component,
                        descriptor,
                        expected_mode=expected_mode,
                    ):
                        os.rmdir(component, dir_fd=parent_fd)
                except OSError:
                    pass
            os.close(descriptor)
        if isinstance(error, SnapshotError):
            raise
        _raise("SNAPSHOT_WRITE_FAILURE")


def _open_or_create_directory_at(
    parent_fd: int,
    name: str,
) -> tuple[int, bool]:
    component = _validate_component(name)
    try:
        os.stat(component, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return _create_directory_at(parent_fd, component), True
    except OSError:
        _raise("SNAPSHOT_WRITE_FAILURE")
    try:
        return (
            _open_checked_directory_at(
                parent_fd,
                component,
                expected_mode=0o700,
            ),
            False,
        )
    except SnapshotError:
        _raise("SNAPSHOT_WRITE_FAILURE")


def _created_node(
    relative_path: PurePosixPath,
    metadata: os.stat_result,
) -> _CreatedNode:
    return _CreatedNode(
        relative_path=relative_path,
        device=metadata.st_dev,
        inode=metadata.st_ino,
        mode=metadata.st_mode,
    )


def _open_parent_at(
    root_fd: int,
    relative: PurePosixPath,
    *,
    prefix: PurePosixPath,
    created_directories: list[_CreatedNode],
) -> int:
    current = os.dup(root_fd)
    current_relative = prefix
    try:
        for component in relative.parts[:-1]:
            next_descriptor, created = _open_or_create_directory_at(
                current,
                component,
            )
            try:
                current_relative /= component
                if created:
                    created_directories.append(
                        _created_node(
                            current_relative,
                            os.fstat(next_descriptor),
                        )
                    )
            except BaseException:
                os.close(next_descriptor)
                raise
            os.close(current)
            current = next_descriptor
        return current
    except BaseException:
        os.close(current)
        raise


def _write_exclusive_at(
    directory_fd: int,
    name: str,
    content: bytes,
    *,
    executable: bool,
    relative_path: PurePosixPath,
    created_files: list[_CreatedNode],
) -> None:
    component = _validate_component(name)
    mode = 0o755 if executable else 0o644
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(
            component,
            flags,
            mode,
            dir_fd=directory_fd,
        )
    except OSError:
        _raise("SNAPSHOT_WRITE_FAILURE")
    try:
        created_index = len(created_files)
        created_files.append(
            _created_node(relative_path, os.fstat(descriptor))
        )
        view = memoryview(content)
        offset = 0
        while offset < len(content):
            written = os.write(descriptor, view[offset:])
            if written <= 0:
                _raise("SNAPSHOT_WRITE_FAILURE")
            offset += written
        os.fchmod(descriptor, mode)
        created_files[created_index] = _created_node(
            relative_path,
            os.fstat(descriptor),
        )
    except OSError:
        _raise("SNAPSHOT_WRITE_FAILURE")
    finally:
        os.close(descriptor)


def _write_arm(
    pair_fd: int,
    arm_name: str,
    blobs: Sequence[_SourceBlob],
    *,
    agents_blob: _SourceBlob,
    task_blob: _SourceBlob,
    created_directories: list[_CreatedNode],
    created_files: list[_CreatedNode],
) -> None:
    overlays = {
        PurePosixPath("AGENTS.md"): agents_blob,
        PurePosixPath("CODEX_TASK.md"): task_blob,
    }
    by_path = {blob.entry.relative_path: blob for blob in blobs}
    by_path.update(overlays)
    arm_fd = _create_directory_at(pair_fd, arm_name)
    try:
        arm_path = PurePosixPath(arm_name)
        created_directories.append(
            _created_node(arm_path, os.fstat(arm_fd))
        )
        for relative in sorted(by_path):
            blob = by_path[relative]
            if _sha256(blob.content) != blob.entry.sha256:
                _raise("SNAPSHOT_SOURCE_CHANGED")
            parent_fd = _open_parent_at(
                arm_fd,
                relative,
                prefix=arm_path,
                created_directories=created_directories,
            )
            try:
                _write_exclusive_at(
                    parent_fd,
                    relative.name,
                    blob.content,
                    executable=blob.executable,
                    relative_path=arm_path / relative,
                    created_files=created_files,
                )
            finally:
                os.close(parent_fd)
        if not _name_binds_descriptor(
            pair_fd,
            arm_name,
            arm_fd,
            expected_mode=0o700,
        ):
            _raise("SNAPSHOT_BINDING_MISMATCH")
    finally:
        os.close(arm_fd)


def _name_binds_descriptor(
    parent_fd: int,
    name: str,
    descriptor: int,
    *,
    expected_mode: int,
) -> bool:
    try:
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        opened = os.fstat(descriptor)
    except OSError:
        return False
    return (
        not stat.S_ISLNK(named.st_mode)
        and stat.S_ISDIR(named.st_mode)
        and stat.S_ISDIR(opened.st_mode)
        and named.st_dev == opened.st_dev
        and named.st_ino == opened.st_ino
        and stat.S_IMODE(opened.st_mode) == expected_mode
    )


def _open_recorded_parent_at(
    pair_fd: int,
    relative_path: PurePosixPath,
) -> int | None:
    current = os.dup(pair_fd)
    try:
        for component in relative_path.parts[:-1]:
            next_descriptor = _open_checked_directory_at(
                current,
                component,
                expected_mode=0o700,
            )
            os.close(current)
            current = next_descriptor
        return current
    except SnapshotError:
        os.close(current)
        return None


def _recorded_node_matches(
    parent_fd: int,
    node: _CreatedNode,
) -> bool:
    try:
        metadata = os.stat(
            node.relative_path.name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
    except OSError:
        return False
    return (
        metadata.st_dev == node.device
        and metadata.st_ino == node.inode
        and metadata.st_mode == node.mode
    )


def _rollback_open_pair(
    anchor_fd: int,
    pair_fd: int,
    pair_name: str,
    created_files: Sequence[_CreatedNode],
    created_directories: Sequence[_CreatedNode],
) -> None:
    for node in reversed(created_files):
        parent_fd = _open_recorded_parent_at(
            pair_fd,
            node.relative_path,
        )
        if parent_fd is None:
            continue
        try:
            if (
                stat.S_ISREG(node.mode)
                and _recorded_node_matches(parent_fd, node)
            ):
                try:
                    os.unlink(
                        node.relative_path.name,
                        dir_fd=parent_fd,
                    )
                except OSError:
                    pass
        finally:
            os.close(parent_fd)
    for node in reversed(created_directories):
        parent_fd = _open_recorded_parent_at(
            pair_fd,
            node.relative_path,
        )
        if parent_fd is None:
            continue
        try:
            if (
                stat.S_ISDIR(node.mode)
                and _recorded_node_matches(parent_fd, node)
            ):
                try:
                    os.rmdir(
                        node.relative_path.name,
                        dir_fd=parent_fd,
                    )
                except OSError:
                    pass
        finally:
            os.close(parent_fd)
    if not _name_binds_descriptor(
        anchor_fd,
        pair_name,
        pair_fd,
        expected_mode=0o700,
    ):
        return
    try:
        os.rmdir(pair_name, dir_fd=anchor_fd)
    except OSError:
        pass


def _manifest_payload(manifest: SnapshotPairManifest) -> dict[str, object]:
    return {
        "anchor_digest": manifest.anchor_digest,
        "anchor_kind": manifest.anchor_kind,
        "expected_differences": [
            path.as_posix() for path in manifest.expected_differences
        ],
        "pair_digest": manifest.pair_digest,
        "pair_name": manifest.pair_name,
        "schema": manifest.schema,
        "source_entries": _source_payload(manifest.source_entries),
    }


def _sentinel_payload(manifest: SnapshotPairManifest) -> dict[str, object]:
    return {
        "anchor_digest": manifest.anchor_digest,
        "anchor_kind": manifest.anchor_kind,
        "pair_digest": manifest.pair_digest,
        "pair_name": manifest.pair_name,
        "schema": manifest.schema,
    }


def prepare_snapshot_pair(
    request: SnapshotRequest,
) -> SnapshotPairManifest:
    repo_root = _canonical_repo_root(request.repo_root)
    anchor, pair_root = _classify_prepare_anchor(
        repo_root,
        request.output_root,
    )

    normalized = SnapshotRequest(
        repo_root=repo_root,
        output_root=pair_root,
        candidate_instruction=request.candidate_instruction,
        baseline_entry=request.baseline_entry,
        candidate_entry=request.candidate_entry,
        selected_uncommitted=request.selected_uncommitted,
    )
    blobs = _collect_source_blobs(normalized)
    by_path = {blob.entry.relative_path: blob for blob in blobs}
    baseline_agents = by_path[PurePosixPath("AGENTS.md")]
    candidate_agents = by_path[
        _validate_relative_path(request.candidate_instruction, source=True)
    ]
    baseline_task = by_path[
        _validate_relative_path(request.baseline_entry, source=True)
    ]
    candidate_task = by_path[
        _validate_relative_path(request.candidate_entry, source=True)
    ]
    if baseline_agents.content == candidate_agents.content:
        _raise("SNAPSHOT_IDENTICAL_INSTRUCTIONS")
    expected_differences = [PurePosixPath("AGENTS.md")]
    if baseline_task.content != candidate_task.content:
        expected_differences.append(PurePosixPath("CODEX_TASK.md"))
    expected = tuple(expected_differences)
    source_entries = tuple(blob.entry for blob in blobs)
    baseline_inventory = _overlay_inventory(
        blobs,
        agents_blob=baseline_agents,
        task_blob=baseline_task,
    )
    candidate_inventory = _overlay_inventory(
        blobs,
        agents_blob=candidate_agents,
        task_blob=candidate_task,
    )
    _validate_inventory_bounds(baseline_inventory)
    _validate_inventory_bounds(candidate_inventory)
    pair_name = _safe_pair_name(pair_root)
    digest = _pair_digest(
        schema=SNAPSHOT_SCHEMA,
        pair_name=pair_name,
        anchor_kind=anchor.kind,
        anchor_digest=anchor.digest,
        source_entries=source_entries,
        expected_differences=expected,
        baseline_inventory=baseline_inventory,
        candidate_inventory=candidate_inventory,
    )
    manifest = SnapshotPairManifest(
        schema=SNAPSHOT_SCHEMA,
        pair_digest=digest,
        pair_name=pair_name,
        anchor_kind=anchor.kind,
        anchor_digest=anchor.digest,
        source_entries=source_entries,
        expected_differences=expected,
    )
    manifest_bytes = _compact_json(_manifest_payload(manifest))
    sentinel_bytes = _compact_json(_sentinel_payload(manifest))
    if (
        len(manifest_bytes) > _MAX_MANIFEST_BYTES
        or len(sentinel_bytes) > _MAX_SENTINEL_BYTES
    ):
        _raise("SNAPSHOT_SOURCE_TOO_LARGE")

    created_files: list[_CreatedNode] = []
    created_directories: list[_CreatedNode] = []
    anchor_fd = _open_anchor_descriptor(anchor)
    pair_fd: int | None = None
    try:
        try:
            os.stat(
                pair_name,
                dir_fd=anchor_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            pass
        except OSError:
            _raise("SNAPSHOT_PAIR_INVALID")
        else:
            _raise("SNAPSHOT_PAIR_EXISTS")
        pair_fd = _create_directory_at(anchor_fd, pair_name)
        _write_arm(
            pair_fd,
            "baseline",
            blobs,
            agents_blob=baseline_agents,
            task_blob=baseline_task,
            created_directories=created_directories,
            created_files=created_files,
        )
        _write_arm(
            pair_fd,
            "candidate",
            blobs,
            agents_blob=candidate_agents,
            task_blob=candidate_task,
            created_directories=created_directories,
            created_files=created_files,
        )
        _write_exclusive_at(
            pair_fd,
            MANIFEST_NAME,
            manifest_bytes,
            executable=False,
            relative_path=PurePosixPath(MANIFEST_NAME),
            created_files=created_files,
        )
        _write_exclusive_at(
            pair_fd,
            SENTINEL_NAME,
            sentinel_bytes,
            executable=False,
            relative_path=PurePosixPath(SENTINEL_NAME),
            created_files=created_files,
        )
        if not _name_binds_descriptor(
            anchor_fd,
            pair_name,
            pair_fd,
            expected_mode=0o700,
        ):
            _raise("SNAPSHOT_BINDING_MISMATCH")
        verification, observed_manifest, _, _ = _verify_open_pair(
            pair_fd,
            pair_name,
            anchor,
        )
        if not verification.passed or observed_manifest != manifest:
            _raise("SNAPSHOT_INVENTORY_MISMATCH")
        if not _anchor_descriptor_is_bound(anchor, anchor_fd):
            _raise("SNAPSHOT_BINDING_MISMATCH")
    except BaseException:
        if pair_fd is not None:
            _rollback_open_pair(
                anchor_fd,
                pair_fd,
                pair_name,
                created_files,
                created_directories,
            )
        raise
    finally:
        if pair_fd is not None:
            os.close(pair_fd)
        os.close(anchor_fd)
    return manifest


def _reject_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _read_bounded_regular_at(
    directory_fd: int,
    name: str,
    *,
    max_bytes: int,
    expected_mode: int | None = None,
    require_single_link: bool = True,
) -> tuple[bytes, os.stat_result]:
    if (
        not name
        or "/" in name
        or name in {".", ".."}
        or _contains_control(name)
    ):
        raise ValueError
    try:
        metadata = os.stat(
            name,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
    except OSError:
        raise ValueError from None
    mode = stat.S_IMODE(metadata.st_mode)
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or (require_single_link and metadata.st_nlink != 1)
        or metadata.st_size > max_bytes
        or (expected_mode is not None and mode != expected_mode)
    ):
        raise ValueError
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(name, flags, dir_fd=directory_fd)
    except OSError:
        raise ValueError from None
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or (require_single_link and opened.st_nlink != 1)
            or opened.st_dev != metadata.st_dev
            or opened.st_ino != metadata.st_ino
            or opened.st_size != metadata.st_size
            or opened.st_mtime_ns != metadata.st_mtime_ns
            or opened.st_ctime_ns != metadata.st_ctime_ns
            or stat.S_IMODE(opened.st_mode) != mode
        ):
            raise ValueError
        chunks: list[bytes] = []
        remaining = opened.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                raise ValueError
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise ValueError
        after = os.fstat(descriptor)
        if (
            after.st_dev != opened.st_dev
            or after.st_ino != opened.st_ino
            or after.st_size != opened.st_size
            or after.st_nlink != opened.st_nlink
            or after.st_mtime_ns != opened.st_mtime_ns
            or after.st_ctime_ns != opened.st_ctime_ns
            or stat.S_IMODE(after.st_mode) != mode
        ):
            raise ValueError
        rebound = os.stat(
            name,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
        if (
            rebound.st_dev != opened.st_dev
            or rebound.st_ino != opened.st_ino
            or rebound.st_size != opened.st_size
            or rebound.st_nlink != opened.st_nlink
            or rebound.st_mtime_ns != opened.st_mtime_ns
            or rebound.st_ctime_ns != opened.st_ctime_ns
            or stat.S_IMODE(rebound.st_mode) != mode
        ):
            raise ValueError
        return b"".join(chunks), opened
    except OSError:
        raise ValueError from None
    finally:
        os.close(descriptor)


def _decode_strict_json(content: bytes) -> dict[str, object]:
    try:
        value = json.loads(
            content.decode("ascii"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (
        UnicodeError,
        ValueError,
        TypeError,
        OverflowError,
        RecursionError,
    ):
        raise ValueError from None
    if not isinstance(value, dict):
        raise ValueError
    return value


def _manifest_from_payload(
    payload: dict[str, object],
) -> SnapshotPairManifest:
    if set(payload) != _MANIFEST_FIELDS:
        raise ValueError
    if (
        payload.get("schema") != SNAPSHOT_SCHEMA
        or not isinstance(payload.get("pair_digest"), str)
        or not _SHA256_RE.fullmatch(payload["pair_digest"])
        or not isinstance(payload.get("pair_name"), str)
        or not _PAIR_NAME_RE.fullmatch(payload["pair_name"])
        or not isinstance(payload.get("anchor_kind"), str)
        or payload.get("anchor_kind")
        not in {"system-temp", "ignored-repo-diagnostics"}
        or not isinstance(payload.get("anchor_digest"), str)
        or not _SHA256_RE.fullmatch(payload["anchor_digest"])
        or not isinstance(payload.get("source_entries"), list)
        or not isinstance(payload.get("expected_differences"), list)
    ):
        raise ValueError
    entries: list[SourceEntry] = []
    previous: PurePosixPath | None = None
    total_size = 0
    if len(payload["source_entries"]) > _MAX_SOURCE_FILES:
        raise ValueError
    for raw in payload["source_entries"]:
        if not isinstance(raw, dict) or set(raw) != _SOURCE_ENTRY_FIELDS:
            raise ValueError
        relative_value = raw.get("relative_path")
        digest = raw.get("sha256")
        size = raw.get("size_bytes")
        origin = raw.get("origin")
        if (
            not isinstance(relative_value, str)
            or not isinstance(digest, str)
            or not _SHA256_RE.fullmatch(digest)
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or size > _MAX_SOURCE_FILE_BYTES
            or not isinstance(origin, str)
            or origin not in {"tracked", "selected-uncommitted"}
        ):
            raise ValueError
        try:
            relative = _validate_relative_path(
                PurePosixPath(relative_value),
                source=True,
            )
        except SnapshotError:
            raise ValueError from None
        if previous is not None and relative <= previous:
            raise ValueError
        previous = relative
        total_size += size
        if total_size > _MAX_SOURCE_TOTAL_BYTES:
            raise ValueError
        entries.append(
            SourceEntry(
                relative_path=relative,
                sha256=digest,
                size_bytes=size,
                origin=origin,
            )
        )
    differences: list[PurePosixPath] = []
    previous_difference: PurePosixPath | None = None
    for raw in payload["expected_differences"]:
        if not isinstance(raw, str):
            raise ValueError
        relative = PurePosixPath(raw)
        if relative not in {
            PurePosixPath("AGENTS.md"),
            PurePosixPath("CODEX_TASK.md"),
        }:
            raise ValueError
        if previous_difference is not None and relative <= previous_difference:
            raise ValueError
        previous_difference = relative
        differences.append(relative)
    if not differences or differences[0] != PurePosixPath("AGENTS.md"):
        raise ValueError
    return SnapshotPairManifest(
        schema=SNAPSHOT_SCHEMA,
        pair_digest=payload["pair_digest"],
        pair_name=payload["pair_name"],
        anchor_kind=payload["anchor_kind"],
        anchor_digest=payload["anchor_digest"],
        source_entries=tuple(entries),
        expected_differences=tuple(differences),
    )


def _parse_manifest_at(directory_fd: int) -> SnapshotPairManifest:
    content, _ = _read_bounded_regular_at(
        directory_fd,
        MANIFEST_NAME,
        max_bytes=_MAX_MANIFEST_BYTES,
        expected_mode=0o644,
    )
    manifest = _manifest_from_payload(_decode_strict_json(content))
    if content != _compact_json(_manifest_payload(manifest)):
        raise ValueError
    return manifest


def _sentinel_from_payload(
    payload: dict[str, object],
) -> dict[str, object]:
    if set(payload) != _SENTINEL_FIELDS:
        raise ValueError
    if (
        payload.get("schema") != SNAPSHOT_SCHEMA
        or not isinstance(payload.get("pair_digest"), str)
        or not _SHA256_RE.fullmatch(payload["pair_digest"])
        or not isinstance(payload.get("pair_name"), str)
        or not _PAIR_NAME_RE.fullmatch(payload["pair_name"])
        or not isinstance(payload.get("anchor_kind"), str)
        or payload.get("anchor_kind")
        not in {"system-temp", "ignored-repo-diagnostics"}
        or not isinstance(payload.get("anchor_digest"), str)
        or not _SHA256_RE.fullmatch(payload["anchor_digest"])
    ):
        raise ValueError
    return payload


def _parse_sentinel_at(directory_fd: int) -> dict[str, object]:
    content, _ = _read_bounded_regular_at(
        directory_fd,
        SENTINEL_NAME,
        max_bytes=_MAX_SENTINEL_BYTES,
        expected_mode=0o644,
    )
    sentinel = _sentinel_from_payload(_decode_strict_json(content))
    if content != _compact_json(sentinel):
        raise ValueError
    return sentinel


def _bounded_names_at(
    directory_fd: int,
    *,
    max_entries: int,
) -> tuple[str, ...]:
    names: list[str] = []
    try:
        with os.scandir(directory_fd) as iterator:
            for entry in iterator:
                names.append(entry.name)
                if len(names) > max_entries:
                    raise ValueError
    except OSError:
        raise ValueError from None
    return tuple(sorted(names))


def _metadata_binding(
    metadata: os.stat_result,
) -> tuple[int, int, int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _scan_arm_at(
    pair_fd: int,
    arm_name: str,
) -> _ArmInventory:
    try:
        arm_fd = _open_checked_directory_at(
            pair_fd,
            arm_name,
            expected_mode=0o700,
        )
    except SnapshotError:
        raise ValueError from None
    try:
        root_metadata = os.fstat(arm_fd)
    except OSError:
        os.close(arm_fd)
        raise ValueError from None
    entries: list[_InventoryEntry] = []
    observed_directories: dict[
        PurePosixPath,
        _DirectoryIdentity,
    ] = {}
    total_size = 0
    observed_nodes = 0

    def visit(directory_fd: int, prefix: PurePosixPath) -> None:
        nonlocal observed_nodes, total_size
        names = _bounded_names_at(
            directory_fd,
            max_entries=_MAX_SOURCE_FILES,
        )
        initial_bindings: dict[str, os.stat_result] = {}
        for name in names:
            if (
                not name
                or "/" in name
                or name in {".", ".."}
                or _contains_control(name)
            ):
                raise ValueError
            try:
                metadata = os.stat(
                    name,
                    dir_fd=directory_fd,
                    follow_symlinks=False,
                )
            except OSError:
                raise ValueError from None
            observed_nodes += 1
            if observed_nodes > _MAX_SOURCE_FILES:
                raise ValueError
            initial_bindings[name] = metadata
            relative = prefix / name
            if stat.S_ISLNK(metadata.st_mode):
                raise ValueError
            if stat.S_ISDIR(metadata.st_mode):
                if stat.S_IMODE(metadata.st_mode) != 0o700:
                    raise ValueError
                if len(relative.parts) > _MAX_PATH_DEPTH:
                    raise ValueError
                try:
                    child_fd = _open_checked_directory_at(
                        directory_fd,
                        name,
                        expected_mode=0o700,
                    )
                except SnapshotError:
                    raise ValueError from None
                try:
                    opened_directory = os.fstat(child_fd)
                    if (
                        opened_directory.st_dev != metadata.st_dev
                        or opened_directory.st_ino != metadata.st_ino
                    ):
                        raise ValueError
                    observed_directories[relative] = _DirectoryIdentity(
                        relative_path=relative,
                        device=opened_directory.st_dev,
                        inode=opened_directory.st_ino,
                        mode=stat.S_IMODE(opened_directory.st_mode),
                    )
                    if len(observed_directories) > _MAX_SOURCE_FILES:
                        raise ValueError
                    visit(child_fd, relative)
                    if not _name_binds_descriptor(
                        directory_fd,
                        name,
                        child_fd,
                        expected_mode=0o700,
                    ):
                        raise ValueError
                finally:
                    os.close(child_fd)
                continue
            try:
                validated = _validate_relative_path(relative, source=False)
                content, opened = _read_bounded_regular_at(
                    directory_fd,
                    name,
                    max_bytes=_MAX_SOURCE_FILE_BYTES,
                )
            except (SnapshotError, ValueError):
                raise ValueError from None
            total_size += len(content)
            if (
                total_size > _MAX_SOURCE_TOTAL_BYTES
                or len(entries) >= _MAX_SOURCE_FILES
            ):
                raise ValueError
            entries.append(
                _InventoryEntry(
                    relative_path=validated,
                    sha256=_sha256(content),
                    size_bytes=len(content),
                    mode=stat.S_IMODE(opened.st_mode),
                    device=opened.st_dev,
                    inode=opened.st_ino,
                )
            )
        if _bounded_names_at(
            directory_fd,
            max_entries=_MAX_SOURCE_FILES,
        ) != names:
            raise ValueError
        for name, before in initial_bindings.items():
            try:
                after = os.stat(
                    name,
                    dir_fd=directory_fd,
                    follow_symlinks=False,
                )
            except OSError:
                raise ValueError from None
            if _metadata_binding(after) != _metadata_binding(before):
                raise ValueError

    try:
        visit(arm_fd, PurePosixPath())
        if (
            _metadata_binding(os.fstat(arm_fd))
            != _metadata_binding(root_metadata)
            or not _name_binds_descriptor(
                pair_fd,
                arm_name,
                arm_fd,
                expected_mode=0o700,
            )
        ):
            raise ValueError
    finally:
        os.close(arm_fd)
    expected_directories: set[PurePosixPath] = set()
    for entry in entries:
        parent = entry.relative_path.parent
        while parent != PurePosixPath("."):
            expected_directories.add(parent)
            parent = parent.parent
    if set(observed_directories) != expected_directories:
        raise ValueError
    return _ArmInventory(
        root=_DirectoryIdentity(
            relative_path=PurePosixPath(),
            device=root_metadata.st_dev,
            inode=root_metadata.st_ino,
            mode=stat.S_IMODE(root_metadata.st_mode),
        ),
        directories=tuple(
            observed_directories[path]
            for path in sorted(observed_directories)
        ),
        files=tuple(
            sorted(entries, key=lambda entry: entry.relative_path)
        ),
    )


def _observed_differences(
    baseline: Sequence[_InventoryEntry],
    candidate: Sequence[_InventoryEntry],
) -> tuple[PurePosixPath, ...]:
    baseline_by_path = {entry.relative_path: entry for entry in baseline}
    candidate_by_path = {entry.relative_path: entry for entry in candidate}
    differences: list[PurePosixPath] = []
    for path in sorted(set(baseline_by_path) | set(candidate_by_path)):
        left = baseline_by_path.get(path)
        right = candidate_by_path.get(path)
        if (
            left is None
            or right is None
            or left.sha256 != right.sha256
            or left.size_bytes != right.size_bytes
        ):
            differences.append(path)
    return tuple(differences)


def _verify_open_pair(
    pair_fd: int,
    pair_name: str,
    anchor: _Anchor,
) -> tuple[
    SnapshotVerification,
    SnapshotPairManifest | None,
    _ArmInventory | None,
    _ArmInventory | None,
]:
    try:
        child_names = set(
            _bounded_names_at(
                pair_fd,
                max_entries=len(_TOP_LEVEL_CHILDREN) + 1,
            )
        )
    except ValueError:
        return (
            SnapshotVerification(
                passed=False,
                issue_codes=("SNAPSHOT_INVENTORY_MISMATCH",),
                observed_differences=(),
            ),
            None,
            None,
            None,
        )
    if SENTINEL_NAME not in child_names:
        return (
            SnapshotVerification(
                passed=False,
                issue_codes=("SNAPSHOT_SENTINEL_INVALID",),
                observed_differences=(),
            ),
            None,
            None,
            None,
        )
    if MANIFEST_NAME not in child_names:
        return (
            SnapshotVerification(
                passed=False,
                issue_codes=("SNAPSHOT_MANIFEST_INVALID",),
                observed_differences=(),
            ),
            None,
            None,
            None,
        )
    if child_names != _TOP_LEVEL_CHILDREN:
        return (
            SnapshotVerification(
                passed=False,
                issue_codes=("SNAPSHOT_INVENTORY_MISMATCH",),
                observed_differences=(),
            ),
            None,
            None,
            None,
        )
    try:
        initial_children = {
            name: os.stat(
                name,
                dir_fd=pair_fd,
                follow_symlinks=False,
            )
            for name in child_names
        }
    except OSError:
        return (
            SnapshotVerification(
                passed=False,
                issue_codes=("SNAPSHOT_INVENTORY_MISMATCH",),
                observed_differences=(),
            ),
            None,
            None,
            None,
        )
    try:
        manifest = _parse_manifest_at(pair_fd)
    except (ValueError, RecursionError):
        return (
            SnapshotVerification(
                passed=False,
                issue_codes=("SNAPSHOT_MANIFEST_INVALID",),
                observed_differences=(),
            ),
            None,
            None,
            None,
        )
    try:
        sentinel = _parse_sentinel_at(pair_fd)
    except ValueError:
        return (
            SnapshotVerification(
                passed=False,
                issue_codes=("SNAPSHOT_SENTINEL_INVALID",),
                observed_differences=(),
            ),
            manifest,
            None,
            None,
        )
    binding = _sentinel_payload(manifest)
    if (
        sentinel != binding
        or manifest.pair_name != pair_name
        or manifest.anchor_kind != anchor.kind
        or manifest.anchor_digest != anchor.digest
    ):
        return (
            SnapshotVerification(
                passed=False,
                issue_codes=("SNAPSHOT_BINDING_MISMATCH",),
                observed_differences=(),
            ),
            manifest,
            None,
            None,
        )
    try:
        baseline = _scan_arm_at(pair_fd, "baseline")
        candidate = _scan_arm_at(pair_fd, "candidate")
    except (ValueError, RecursionError):
        return (
            SnapshotVerification(
                passed=False,
                issue_codes=("SNAPSHOT_INVENTORY_MISMATCH",),
                observed_differences=(),
            ),
            manifest,
            None,
            None,
        )
    expected_paths = {
        entry.relative_path for entry in manifest.source_entries
    } | {PurePosixPath("AGENTS.md"), PurePosixPath("CODEX_TASK.md")}
    baseline_paths = {
        entry.relative_path for entry in baseline.files
    }
    candidate_paths = {
        entry.relative_path for entry in candidate.files
    }
    observed = _observed_differences(
        baseline.files,
        candidate.files,
    )
    issues: set[str] = set()
    if baseline_paths != expected_paths or candidate_paths != expected_paths:
        issues.add("SNAPSHOT_INVENTORY_MISMATCH")
    if observed != manifest.expected_differences:
        issues.add("SNAPSHOT_UNEXPECTED_DIFFERENCE")
    recomputed = _pair_digest(
        schema=manifest.schema,
        pair_name=manifest.pair_name,
        anchor_kind=manifest.anchor_kind,
        anchor_digest=manifest.anchor_digest,
        source_entries=manifest.source_entries,
        expected_differences=manifest.expected_differences,
        baseline_inventory=baseline.files,
        candidate_inventory=candidate.files,
    )
    if recomputed != manifest.pair_digest:
        issues.add("SNAPSHOT_DIGEST_DRIFT")
    try:
        final_names = set(
            _bounded_names_at(
                pair_fd,
                max_entries=len(_TOP_LEVEL_CHILDREN) + 1,
            )
        )
        if final_names != child_names:
            issues.add("SNAPSHOT_INVENTORY_MISMATCH")
        else:
            for name, before in initial_children.items():
                after = os.stat(
                    name,
                    dir_fd=pair_fd,
                    follow_symlinks=False,
                )
                if _metadata_binding(after) != _metadata_binding(before):
                    issues.add("SNAPSHOT_INVENTORY_MISMATCH")
                    break
    except (OSError, ValueError):
        issues.add("SNAPSHOT_INVENTORY_MISMATCH")
    verification = SnapshotVerification(
        passed=not issues,
        issue_codes=tuple(sorted(issues)),
        observed_differences=observed,
    )
    return verification, manifest, baseline, candidate


def verify_snapshot_pair(
    pair_root: Path,
    *,
    approved_parent: Path,
) -> SnapshotVerification:
    anchor, pair = _validated_existing_pair(pair_root, approved_parent)
    anchor_fd, pair_fd = _open_pair_descriptors(anchor, pair.name)
    try:
        verification, manifest, baseline, candidate = _verify_open_pair(
            pair_fd,
            pair.name,
            anchor,
        )
        if verification.passed:
            second, second_manifest, second_baseline, second_candidate = (
                _verify_open_pair(
                    pair_fd,
                    pair.name,
                    anchor,
                )
            )
            if (
                not second.passed
                or second_manifest != manifest
                or second_baseline != baseline
                or second_candidate != candidate
            ):
                verification = SnapshotVerification(
                    passed=False,
                    issue_codes=("SNAPSHOT_INVENTORY_MISMATCH",),
                    observed_differences=(),
                )
        if not _name_binds_descriptor(
            anchor_fd,
            pair.name,
            pair_fd,
            expected_mode=0o700,
        ) or not _anchor_descriptor_is_bound(anchor, anchor_fd):
            return SnapshotVerification(
                passed=False,
                issue_codes=("SNAPSHOT_BINDING_MISMATCH",),
                observed_differences=(),
            )
        return verification
    finally:
        os.close(pair_fd)
        os.close(anchor_fd)


@dataclass
class _DeleteDirectory:
    identity: _DirectoryIdentity
    directories: dict[str, "_DeleteDirectory"] = field(default_factory=dict)
    files: dict[str, _InventoryEntry] = field(default_factory=dict)


def _inventory_delete_tree(
    inventory: _ArmInventory,
) -> _DeleteDirectory:
    root = _DeleteDirectory(identity=inventory.root)
    for identity in sorted(
        inventory.directories,
        key=lambda entry: (
            len(entry.relative_path.parts),
            entry.relative_path,
        ),
    ):
        current = root
        for component in identity.relative_path.parts[:-1]:
            if component not in current.directories:
                _raise("SNAPSHOT_INVENTORY_MISMATCH")
            current = current.directories[component]
        leaf = identity.relative_path.name
        if leaf in current.directories or leaf in current.files:
            _raise("SNAPSHOT_INVENTORY_MISMATCH")
        current.directories[leaf] = _DeleteDirectory(identity=identity)
    for entry in inventory.files:
        current = root
        for component in entry.relative_path.parts[:-1]:
            if component not in current.directories:
                _raise("SNAPSHOT_INVENTORY_MISMATCH")
            current = current.directories[component]
        leaf = entry.relative_path.name
        if leaf in current.directories or leaf in current.files:
            _raise("SNAPSHOT_INVENTORY_MISMATCH")
        current.files[leaf] = entry
    return root


def _open_bound_regular_at(
    directory_fd: int,
    name: str,
    expected: os.stat_result,
) -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(name, flags, dir_fd=directory_fd)
        opened = os.fstat(descriptor)
        named = os.stat(
            name,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
    except OSError:
        if "descriptor" in locals():
            os.close(descriptor)
        _raise("SNAPSHOT_CLEANUP_FAILURE")
    if (
        not stat.S_ISREG(opened.st_mode)
        or opened.st_nlink != 1
        or _metadata_binding(opened) != _metadata_binding(expected)
        or _metadata_binding(named) != _metadata_binding(opened)
    ):
        os.close(descriptor)
        _raise("SNAPSHOT_CLEANUP_REFUSED")
    return descriptor


def _unlink_verified_file_at(
    directory_fd: int,
    name: str,
    entry: _InventoryEntry,
    mutated: list[bool],
) -> None:
    try:
        content, metadata = _read_bounded_regular_at(
            directory_fd,
            name,
            max_bytes=_MAX_SOURCE_FILE_BYTES,
            expected_mode=entry.mode,
        )
        if (
            len(content) != entry.size_bytes
            or _sha256(content) != entry.sha256
            or entry.device is None
            or entry.inode is None
            or metadata.st_dev != entry.device
            or metadata.st_ino != entry.inode
        ):
            _raise("SNAPSHOT_CLEANUP_REFUSED")
        descriptor = _open_bound_regular_at(
            directory_fd,
            name,
            metadata,
        )
        try:
            os.unlink(name, dir_fd=directory_fd)
            mutated[0] = True
        finally:
            os.close(descriptor)
    except SnapshotError:
        raise
    except (OSError, ValueError):
        _raise("SNAPSHOT_CLEANUP_FAILURE")


def _delete_verified_directory_at(
    parent_fd: int,
    name: str,
    tree: _DeleteDirectory,
    mutated: list[bool],
) -> None:
    try:
        directory_fd = _open_checked_directory_at(
            parent_fd,
            name,
            expected_mode=0o700,
        )
    except SnapshotError:
        _raise("SNAPSHOT_CLEANUP_REFUSED")
    try:
        opened_directory = os.fstat(directory_fd)
        if (
            opened_directory.st_dev != tree.identity.device
            or opened_directory.st_ino != tree.identity.inode
            or stat.S_IMODE(opened_directory.st_mode)
            != tree.identity.mode
        ):
            _raise("SNAPSHOT_CLEANUP_REFUSED")
        expected_names = set(tree.directories) | set(tree.files)
        try:
            observed_names = set(
                _bounded_names_at(
                    directory_fd,
                    max_entries=len(expected_names) + 1,
                )
            )
        except ValueError:
            _raise("SNAPSHOT_CLEANUP_FAILURE")
        if observed_names != expected_names:
            _raise("SNAPSHOT_CLEANUP_REFUSED")
        for file_name in sorted(tree.files):
            _unlink_verified_file_at(
                directory_fd,
                file_name,
                tree.files[file_name],
                mutated,
            )
        for directory_name in sorted(tree.directories):
            _delete_verified_directory_at(
                directory_fd,
                directory_name,
                tree.directories[directory_name],
                mutated,
            )
        try:
            if _bounded_names_at(directory_fd, max_entries=0):
                _raise("SNAPSHOT_CLEANUP_REFUSED")
        except ValueError:
            _raise("SNAPSHOT_CLEANUP_REFUSED")
        if not _name_binds_descriptor(
            parent_fd,
            name,
            directory_fd,
            expected_mode=0o700,
        ):
            _raise("SNAPSHOT_CLEANUP_REFUSED")
        try:
            os.rmdir(name, dir_fd=parent_fd)
            mutated[0] = True
        except OSError:
            _raise("SNAPSHOT_CLEANUP_FAILURE")
    finally:
        os.close(directory_fd)


def _raise_for_verification(verification: SnapshotVerification) -> None:
    if "SNAPSHOT_SENTINEL_INVALID" in verification.issue_codes:
        _raise("SNAPSHOT_SENTINEL_INVALID")
    if "SNAPSHOT_MANIFEST_INVALID" in verification.issue_codes:
        _raise("SNAPSHOT_MANIFEST_INVALID")
    if "SNAPSHOT_BINDING_MISMATCH" in verification.issue_codes:
        _raise("SNAPSHOT_BINDING_MISMATCH")
    _raise("SNAPSHOT_INVENTORY_MISMATCH")


def _restore_bound_quarantine_at(
    anchor_fd: int,
    quarantine: _QuarantinedPair,
    pair_name: str,
    pair_fd: int,
) -> None:
    if not _name_binds_descriptor(
        quarantine.container_fd,
        _QUARANTINE_PAYLOAD_NAME,
        pair_fd,
        expected_mode=0o700,
    ):
        return
    try:
        os.stat(pair_name, dir_fd=anchor_fd, follow_symlinks=False)
    except FileNotFoundError:
        try:
            os.rename(
                _QUARANTINE_PAYLOAD_NAME,
                pair_name,
                src_dir_fd=quarantine.container_fd,
                dst_dir_fd=anchor_fd,
            )
        except OSError:
            return
    except OSError:
        return
    if not _name_binds_descriptor(
        anchor_fd,
        pair_name,
        pair_fd,
        expected_mode=0o700,
    ):
        return
    try:
        if (
            _bounded_names_at(
                quarantine.container_fd,
                max_entries=0,
            )
            or not _name_binds_descriptor(
                anchor_fd,
                quarantine.container_name,
                quarantine.container_fd,
                expected_mode=0o700,
            )
        ):
            return
        os.rmdir(
            quarantine.container_name,
            dir_fd=anchor_fd,
        )
    except (OSError, ValueError):
        return


def _create_quarantine_container_at(
    anchor_fd: int,
    pair_name: str,
) -> _QuarantinedPair:
    for _ in range(16):
        token = secrets.token_hex(16)
        if not re.fullmatch(r"[0-9a-f]{32}", token):
            _raise("SNAPSHOT_CLEANUP_REFUSED")
        candidate = f".{pair_name}.cleanup-{token}"
        try:
            os.mkdir(candidate, 0o700, dir_fd=anchor_fd)
        except FileExistsError:
            continue
        except OSError:
            _raise("SNAPSHOT_CLEANUP_FAILURE")
        container_fd: int | None = None
        try:
            container_fd = _open_checked_directory_at(
                anchor_fd,
                candidate,
                expected_mode=0o700,
            )
            if not _name_binds_descriptor(
                anchor_fd,
                candidate,
                container_fd,
                expected_mode=0o700,
            ):
                _raise("SNAPSHOT_CLEANUP_REFUSED")
            return _QuarantinedPair(
                container_name=candidate,
                container_fd=container_fd,
            )
        except BaseException:
            if container_fd is not None:
                try:
                    if (
                        not _bounded_names_at(
                            container_fd,
                            max_entries=0,
                        )
                        and _name_binds_descriptor(
                            anchor_fd,
                            candidate,
                            container_fd,
                            expected_mode=0o700,
                        )
                    ):
                        os.rmdir(candidate, dir_fd=anchor_fd)
                except (OSError, ValueError):
                    pass
                os.close(container_fd)
            raise
    _raise("SNAPSHOT_CLEANUP_REFUSED")


def _quarantine_pair_at(
    anchor_fd: int,
    pair_fd: int,
    pair_name: str,
) -> _QuarantinedPair:
    quarantine = _create_quarantine_container_at(
        anchor_fd,
        pair_name,
    )
    renamed = False
    try:
        named = os.stat(
            pair_name,
            dir_fd=anchor_fd,
            follow_symlinks=False,
        )
        opened = os.fstat(pair_fd)
        if (
            stat.S_ISLNK(named.st_mode)
            or not stat.S_ISDIR(named.st_mode)
            or named.st_dev != opened.st_dev
            or named.st_ino != opened.st_ino
        ):
            _raise("SNAPSHOT_CLEANUP_REFUSED")
        if _bounded_names_at(
            quarantine.container_fd,
            max_entries=0,
        ):
            _raise("SNAPSHOT_CLEANUP_REFUSED")
        os.rename(
            pair_name,
            _QUARANTINE_PAYLOAD_NAME,
            src_dir_fd=anchor_fd,
            dst_dir_fd=quarantine.container_fd,
        )
        renamed = True
        if not _name_binds_descriptor(
            quarantine.container_fd,
            _QUARANTINE_PAYLOAD_NAME,
            pair_fd,
            expected_mode=0o700,
        ):
            _raise("SNAPSHOT_CLEANUP_REFUSED")
    except SnapshotError:
        if renamed:
            _restore_bound_quarantine_at(
                anchor_fd,
                quarantine,
                pair_name,
                pair_fd,
            )
        else:
            _restore_empty_quarantine_container_at(
                anchor_fd,
                quarantine,
            )
        os.close(quarantine.container_fd)
        raise
    except (OSError, ValueError):
        if renamed:
            _restore_bound_quarantine_at(
                anchor_fd,
                quarantine,
                pair_name,
                pair_fd,
            )
        else:
            _restore_empty_quarantine_container_at(
                anchor_fd,
                quarantine,
            )
        os.close(quarantine.container_fd)
        _raise("SNAPSHOT_CLEANUP_FAILURE")
    return quarantine


def _restore_empty_quarantine_container_at(
    anchor_fd: int,
    quarantine: _QuarantinedPair,
) -> None:
    try:
        if (
            _bounded_names_at(
                quarantine.container_fd,
                max_entries=0,
            )
            or not _name_binds_descriptor(
                anchor_fd,
                quarantine.container_name,
                quarantine.container_fd,
                expected_mode=0o700,
            )
        ):
            return
        os.rmdir(
            quarantine.container_name,
            dir_fd=anchor_fd,
        )
    except (OSError, ValueError):
        return


def _restore_quarantine_at(
    anchor_fd: int,
    quarantine: _QuarantinedPair,
    pair_name: str,
    pair_fd: int,
) -> None:
    _restore_bound_quarantine_at(
        anchor_fd,
        quarantine,
        pair_name,
        pair_fd,
    )


def _delete_meta_file_at(
    pair_fd: int,
    name: str,
    expected_content: bytes,
    mutated: list[bool],
) -> None:
    try:
        content, metadata = _read_bounded_regular_at(
            pair_fd,
            name,
            max_bytes=(
                _MAX_SENTINEL_BYTES
                if name == SENTINEL_NAME
                else _MAX_MANIFEST_BYTES
            ),
            expected_mode=0o644,
        )
        if content != expected_content:
            _raise("SNAPSHOT_CLEANUP_REFUSED")
        descriptor = _open_bound_regular_at(pair_fd, name, metadata)
        try:
            os.unlink(name, dir_fd=pair_fd)
            mutated[0] = True
        finally:
            os.close(descriptor)
    except SnapshotError:
        raise
    except (OSError, ValueError):
        _raise("SNAPSHOT_CLEANUP_FAILURE")


def cleanup_snapshot_pair(
    pair_root: Path,
    *,
    approved_parent: Path,
) -> None:
    anchor, pair = _validated_existing_pair(pair_root, approved_parent)
    anchor_fd, pair_fd = _open_pair_descriptors(anchor, pair.name)
    quarantine: _QuarantinedPair | None = None
    mutated = [False]
    try:
        try:
            verification, manifest, baseline, candidate = _verify_open_pair(
                pair_fd,
                pair.name,
                anchor,
            )
            if (
                not verification.passed
                or manifest is None
                or baseline is None
                or candidate is None
            ):
                _raise_for_verification(verification)
            if not _anchor_descriptor_is_bound(anchor, anchor_fd):
                _raise("SNAPSHOT_BINDING_MISMATCH")
            quarantine = _quarantine_pair_at(
                anchor_fd,
                pair_fd,
                pair.name,
            )
            second, rebound_manifest, baseline, candidate = _verify_open_pair(
                pair_fd,
                pair.name,
                anchor,
            )
            if (
                not second.passed
                or rebound_manifest is None
                or baseline is None
                or candidate is None
            ):
                _restore_quarantine_at(
                    anchor_fd,
                    quarantine,
                    pair.name,
                    pair_fd,
                )
                os.close(quarantine.container_fd)
                quarantine = None
                _raise_for_verification(second)
            manifest = rebound_manifest
            baseline_tree = _inventory_delete_tree(baseline)
            candidate_tree = _inventory_delete_tree(candidate)
            _delete_verified_directory_at(
                pair_fd,
                "baseline",
                baseline_tree,
                mutated,
            )
            _delete_verified_directory_at(
                pair_fd,
                "candidate",
                candidate_tree,
                mutated,
            )
            _delete_meta_file_at(
                pair_fd,
                MANIFEST_NAME,
                _compact_json(_manifest_payload(manifest)),
                mutated,
            )
            _delete_meta_file_at(
                pair_fd,
                SENTINEL_NAME,
                _compact_json(_sentinel_payload(manifest)),
                mutated,
            )
            try:
                if _bounded_names_at(pair_fd, max_entries=0):
                    _raise("SNAPSHOT_CLEANUP_REFUSED")
            except ValueError:
                _raise("SNAPSHOT_CLEANUP_REFUSED")
            if (
                quarantine is None
                or not _name_binds_descriptor(
                    quarantine.container_fd,
                    _QUARANTINE_PAYLOAD_NAME,
                    pair_fd,
                    expected_mode=0o700,
                )
                or not _anchor_descriptor_is_bound(anchor, anchor_fd)
            ):
                _raise("SNAPSHOT_CLEANUP_REFUSED")
            try:
                os.rmdir(
                    _QUARANTINE_PAYLOAD_NAME,
                    dir_fd=quarantine.container_fd,
                )
                mutated[0] = True
            except OSError:
                _raise("SNAPSHOT_CLEANUP_FAILURE")
            try:
                if (
                    _bounded_names_at(
                        quarantine.container_fd,
                        max_entries=0,
                    )
                    or not _name_binds_descriptor(
                        anchor_fd,
                        quarantine.container_name,
                        quarantine.container_fd,
                        expected_mode=0o700,
                    )
                    or not _anchor_descriptor_is_bound(anchor, anchor_fd)
                ):
                    _raise("SNAPSHOT_CLEANUP_REFUSED")
                os.rmdir(
                    quarantine.container_name,
                    dir_fd=anchor_fd,
                )
            except SnapshotError:
                raise
            except (OSError, ValueError):
                _raise("SNAPSHOT_CLEANUP_FAILURE")
        except BaseException:
            if quarantine is not None and not mutated[0]:
                _restore_quarantine_at(
                    anchor_fd,
                    quarantine,
                    pair.name,
                    pair_fd,
                )
            raise
    finally:
        if quarantine is not None:
            os.close(quarantine.container_fd)
        os.close(pair_fd)
        os.close(anchor_fd)


__all__ = (
    "CANDIDATE_INSTRUCTION",
    "MANIFEST_NAME",
    "SENTINEL_NAME",
    "SNAPSHOT_SCHEMA",
    "SnapshotError",
    "cleanup_snapshot_pair",
    "collect_source_entries",
    "prepare_snapshot_pair",
    "verify_snapshot_pair",
)
