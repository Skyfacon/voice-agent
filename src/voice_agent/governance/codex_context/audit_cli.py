from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from .audit import (
    CHECK_ORDER,
    default_audit_paths,
    render_audit_json,
    run_audit,
)
from .model import AuditCheck


_DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[4]


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    repo_root: Path = arguments.repo_root
    command: str = arguments.command
    checks: tuple[AuditCheck, ...] = (
        CHECK_ORDER if command == "all" else (command,)
    )
    report = run_audit(default_audit_paths(repo_root), checks)
    sys.stdout.write(
        render_audit_json(report, diagnostic=arguments.diagnostic)
    )
    return 0 if report.passed else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codex-context-audit",
        description="Run deterministic Codex context governance checks.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in (*CHECK_ORDER, "all"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument(
            "--diagnostic",
            action="store_true",
            help="include redacted issue identifiers and relative locations",
        )
        subparser.add_argument(
            "--repo-root",
            type=_normalized_repo_root,
            default=str(_DEFAULT_REPO_ROOT),
            help=argparse.SUPPRESS,
        )
    return parser


def _normalized_repo_root(value: str) -> Path:
    try:
        return Path(value).resolve()
    except (OSError, RuntimeError):
        raise argparse.ArgumentTypeError("repository path is invalid") from None


if __name__ == "__main__":
    raise SystemExit(main())
