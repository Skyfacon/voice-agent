from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimeArtifactPolicy:
    local_debug_trace_enabled: bool = True
    raw_audio_enabled: bool = False
    raw_audio_retention_days: int = 0
    cross_machine_raw_audio_sync: bool = False
    github_trace_upload: str = "synthetic_or_redacted_only"
    commit_raw_trace: bool = False
    commit_raw_audio: bool = False
    credential_trace_policy: str = "never"
    local_only_artifact_paths: tuple[str, ...] = (
        "diagnostics/",
        "traces/",
        "replays/local/",
        "audio/raw/",
    )
    github_allowed_fixture_dir: Path = Path("tests/fixtures/replay/mvp0")


DEFAULT_RUNTIME_ARTIFACT_POLICY = RuntimeArtifactPolicy()
