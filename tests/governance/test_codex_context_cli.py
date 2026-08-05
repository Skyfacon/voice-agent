from __future__ import annotations

import datetime
import importlib
import json
import os
import random
import re
import secrets
import shutil
import socket
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath

import pytest

from voice_agent.governance.codex_context.markdown import load_invariant_map


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/codex-context-audit"
SAFE_ID_RE = re.compile(r"^[A-Z0-9][A-Z0-9_.:-]*$")
DIAGNOSTIC_KEYS = {
    "check",
    "code",
    "line",
    "relative_path",
    "rule_id",
    "severity",
}


def test_all_output_is_compact_sorted_and_deterministic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit = importlib.import_module(
        "voice_agent.governance.codex_context.audit"
    )
    paths = _copy_complete_synthetic_repo(tmp_path / "repo")

    report = audit.run_audit(
        paths,
        checks=(
            "cards",
            "mapping",
            "mapping",
            "artifacts",
            "budgets",
            "references",
        ),
    )
    first = audit.render_audit_json(report)
    second = audit.render_audit_json(report)
    payload = json.loads(first)

    assert first == second
    assert first.endswith("\n")
    assert first == (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    )
    assert [check["name"] for check in payload["checks"]] == list(
        audit.CHECK_ORDER
    )
    assert all(
        set(check)
        == {"checked_count", "error_count", "name", "passed"}
        for check in payload["checks"]
    )
    assert payload["passed"] is True
    assert payload["schema"] == "voice_agent.codex_context.audit.v1"
    assert payload["switch_prerequisites"] == [
        "ADR015_EXPLICIT_OPERATIONAL_AUTHORITY_REQUIRED"
    ]
    assert payload["switch_ready"] is False

    monkeypatch.setattr(
        audit,
        "_load_switch_prerequisites",
        lambda _paths: ((), True),
    )
    subset = audit.run_audit(paths, checks=("budgets",))
    complete = audit.run_audit(paths)
    unknown = audit.run_audit(paths, checks=("unknown",))
    empty = audit.run_audit(paths, checks=())
    assert subset.passed
    assert subset.switch_ready is False
    assert json.loads(audit.render_audit_json(subset))["switch_ready"] is False
    assert complete.passed
    assert complete.switch_ready is True
    assert json.loads(audit.render_audit_json(complete))["switch_ready"] is True
    assert not unknown.passed
    assert unknown.switch_ready is False
    assert not empty.passed
    assert empty.switch_ready is False


def test_diagnostic_output_contains_only_safe_ids_relative_paths_and_lines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit = importlib.import_module(
        "voice_agent.governance.codex_context.audit"
    )
    paths = _copy_complete_synthetic_repo(tmp_path / "repo")
    sensitive_marker = "SENSITIVE-MARKER-7ddcad9f"
    paths.invariant_map.write_text(
        f"not a valid invariant map: {sensitive_marker}\n",
        encoding="utf-8",
    )

    try:
        report = audit.run_audit(paths)
        normal = audit.render_audit_json(report)
        diagnostic = audit.render_audit_json(report, diagnostic=True)

        def exploding_check(_paths: object) -> None:
            raise RuntimeError(sensitive_marker)

        monkeypatch.setattr(audit, "audit_mapping", exploding_check)
        exception_report = audit.run_audit(paths, checks=("mapping",))
        exception_normal = audit.render_audit_json(exception_report)
        exception_diagnostic = audit.render_audit_json(
            exception_report,
            diagnostic=True,
        )
    except Exception as exc:  # pragma: no cover - leak sentinel
        assert sensitive_marker not in str(exc)
        raise AssertionError("audit raised for malformed fixture") from None

    assert sensitive_marker not in normal
    assert sensitive_marker not in diagnostic
    assert sensitive_marker not in exception_normal
    assert sensitive_marker not in exception_diagnostic
    assert str(paths.repo_root.resolve()) not in normal
    assert str(paths.repo_root.resolve()) not in diagnostic
    assert not report.passed
    assert report.switch_ready is False
    assert not exception_report.passed
    assert exception_report.switch_ready is False

    normal_payload = json.loads(normal)
    diagnostic_payload = json.loads(diagnostic)
    assert "issues" not in normal_payload
    assert diagnostic_payload["issues"]
    for issue in diagnostic_payload["issues"]:
        assert set(issue) == DIAGNOSTIC_KEYS
        assert issue["check"] in audit.CHECK_ORDER
        assert SAFE_ID_RE.fullmatch(issue["code"])
        assert issue["severity"] in {"error", "warning"}
        if issue["rule_id"] is not None:
            assert SAFE_ID_RE.fullmatch(issue["rule_id"])
        if issue["relative_path"] is not None:
            relative = PurePosixPath(issue["relative_path"])
            assert not relative.is_absolute()
            assert ".." not in relative.parts
        if issue["line"] is not None:
            assert isinstance(issue["line"], int)
            assert issue["line"] > 0


def test_audit_does_not_read_environment_network_clock_or_randomness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit = importlib.import_module(
        "voice_agent.governance.codex_context.audit"
    )
    paths = _copy_complete_synthetic_repo(tmp_path / "repo")

    class ForbiddenEnvironment(dict[str, str]):
        @staticmethod
        def _blocked(key: object = None) -> None:
            raise AssertionError(f"environment read: {key}")

        def __getitem__(self, key: str) -> str:
            self._blocked(key)

        def get(self, key: str, default: object = None) -> object:
            self._blocked(key)

        def __iter__(self):
            self._blocked("iteration")

        def __len__(self) -> int:
            self._blocked("length")

        def __contains__(self, key: object) -> bool:
            self._blocked(key)

        def keys(self):
            self._blocked("keys")

        def values(self):
            self._blocked("values")

        def items(self):
            self._blocked("items")

        def copy(self):
            self._blocked("copy")

    class ForbiddenDateTime(datetime.datetime):
        @classmethod
        def now(
            cls,
            tz: datetime.tzinfo | None = None,
        ) -> datetime.datetime:
            raise AssertionError("clock read")

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("forbidden nondeterministic dependency")

    monkeypatch.setattr(os, "environ", ForbiddenEnvironment())
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(random, "random", forbidden)
    monkeypatch.setattr(secrets, "token_hex", forbidden)
    monkeypatch.setattr(datetime, "datetime", ForbiddenDateTime)
    monkeypatch.setattr("time.time", forbidden)

    report = audit.run_audit(paths)
    rendered = audit.render_audit_json(report, diagnostic=True)

    assert report.passed
    assert report.switch_prerequisites == (
        "ADR015_EXPLICIT_OPERATIONAL_AUTHORITY_REQUIRED",
    )
    assert json.loads(rendered)["passed"] is True


def test_script_entrypoint_uses_repository_python(tmp_path: Path) -> None:
    audit = importlib.import_module(
        "voice_agent.governance.codex_context.audit"
    )
    paths = _copy_complete_synthetic_repo(tmp_path / "repo")
    shim = tmp_path / "python-shim"
    record = tmp_path / "python-argv.txt"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'printf "%s\\n" "$@" > "$AUDIT_PYTHON_RECORD"\n'
        'exec "$AUDIT_REAL_PYTHON" "$@"\n',
        encoding="utf-8",
    )
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
    environment = os.environ.copy()
    environment.update(
        {
            "AUDIT_PYTHON_RECORD": str(record),
            "AUDIT_REAL_PYTHON": sys.executable,
            "VOICE_AGENT_PYTHON": str(shim),
        }
    )

    completed = subprocess.run(
        [
            str(SCRIPT),
            "all",
            "--repo-root",
            str(paths.repo_root),
        ],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert record.read_text(encoding="utf-8").splitlines()[:2] == [
        "-m",
        "voice_agent.governance.codex_context.audit_cli",
    ]
    payload = json.loads(completed.stdout)
    assert payload["passed"] is True
    assert payload["switch_ready"] is False
    assert audit.CHECK_ORDER == (
        "mapping",
        "references",
        "budgets",
        "cards",
        "artifacts",
    )


def _copy_complete_synthetic_repo(repo: Path):
    from voice_agent.governance.codex_context.audit import default_audit_paths

    live_paths = default_audit_paths(ROOT)
    paths = default_audit_paths(repo)
    core_files = {
        ROOT / ".gitignore",
        live_paths.legacy_instruction,
        live_paths.candidate_instruction,
        live_paths.invariant_map,
        live_paths.adr_register,
        live_paths.master_plan,
        live_paths.candidate_instruction.parent / "shadow-baseline.md",
        (
            ROOT
            / "docs/implementation/"
            "codex-context-slimming-shadow-acceptance.md"
        ),
    }
    mappings = load_invariant_map(live_paths.invariant_map)
    referenced_files = {
        ROOT / reference.path.as_posix()
        for mapping in mappings
        for reference in (*mapping.authority_refs, *mapping.enforcement_refs)
    }
    governance_files = set(
        (ROOT / "docs/governance").rglob("*.md")
    )
    for source in sorted(core_files | referenced_files | governance_files):
        if source.is_file():
            _copy_repo_file(source, repo)

    for document in paths.card_root.glob("*.md"):
        text = document.read_text(encoding="utf-8")
        for token in re.findall(r"`([^`\n]+)`", text):
            relative_token = token.split("::", 1)[0]
            source = ROOT / relative_token
            if source.is_file():
                _copy_repo_file(source, repo)
    return paths


def _copy_repo_file(source: Path, repo: Path) -> None:
    destination = repo / source.relative_to(ROOT)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
