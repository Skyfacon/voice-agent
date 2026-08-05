from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Sequence

from .model import SnapshotRequest
from .snapshot import (
    CANDIDATE_INSTRUCTION,
    SnapshotError,
    cleanup_snapshot_pair,
    prepare_snapshot_pair,
    verify_snapshot_pair,
)


CLI_SCHEMA = "voice_agent.codex_context.snapshot_cli.v1"
_SAFE_PAIR_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")


def _render(payload: dict[str, object]) -> str:
    return (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    )


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        sys.stdout.write(
            _render(
                {
                    "issue_codes": ["SNAPSHOT_ARGUMENT_ERROR"],
                    "passed": False,
                    "schema": CLI_SCHEMA,
                }
            )
        )
        raise SystemExit(2)


def _parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(prog="codex-context-snapshot")
    commands = parser.add_subparsers(
        dest="command",
        required=True,
        parser_class=_SafeArgumentParser,
    )

    prepare = commands.add_parser("prepare")
    prepare.add_argument("--repo-root", type=Path, required=True)
    prepare.add_argument("--output-root", type=Path, required=True)
    prepare.add_argument("--baseline-entry", required=True)
    prepare.add_argument("--candidate-entry", required=True)
    prepare.add_argument(
        "--include-uncommitted",
        action="append",
        default=[],
    )

    for name in ("verify", "cleanup"):
        command = commands.add_parser(name)
        command.add_argument("--pair-root", type=Path, required=True)
        command.add_argument("--approved-parent", type=Path, required=True)
    return parser


def _pair_name(path: Path | None) -> str | None:
    if path is None or not _SAFE_PAIR_NAME.fullmatch(path.name):
        return None
    return path.name


def _failure(code: str, pair_root: Path | None) -> dict[str, object]:
    payload: dict[str, object] = {
        "issue_codes": [code],
        "passed": False,
        "schema": CLI_SCHEMA,
    }
    name = _pair_name(pair_root)
    if name is not None:
        payload["pair_name"] = name
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    pair_root: Path | None = None
    try:
        if arguments.command == "prepare":
            pair_root = arguments.output_root
            request = SnapshotRequest(
                repo_root=arguments.repo_root,
                output_root=arguments.output_root,
                candidate_instruction=CANDIDATE_INSTRUCTION,
                baseline_entry=PurePosixPath(arguments.baseline_entry),
                candidate_entry=PurePosixPath(arguments.candidate_entry),
                selected_uncommitted=tuple(
                    PurePosixPath(value)
                    for value in arguments.include_uncommitted
                ),
            )
            manifest = prepare_snapshot_pair(request)
            payload = {
                "entry_count": len(manifest.source_entries),
                "pair_digest": manifest.pair_digest,
                "pair_name": manifest.pair_name,
                "passed": True,
                "schema": CLI_SCHEMA,
            }
        elif arguments.command == "verify":
            pair_root = arguments.pair_root
            verification = verify_snapshot_pair(
                arguments.pair_root,
                approved_parent=arguments.approved_parent,
            )
            payload = {
                "difference_count": len(
                    verification.observed_differences
                ),
                "issue_codes": list(verification.issue_codes),
                "pair_name": _pair_name(arguments.pair_root),
                "passed": verification.passed,
                "schema": CLI_SCHEMA,
            }
        else:
            pair_root = arguments.pair_root
            cleanup_snapshot_pair(
                arguments.pair_root,
                approved_parent=arguments.approved_parent,
            )
            payload = {
                "pair_name": _pair_name(arguments.pair_root),
                "passed": True,
                "schema": CLI_SCHEMA,
            }
    except SnapshotError as error:
        sys.stdout.write(_render(_failure(error.code, pair_root)))
        return 1
    except Exception:
        sys.stdout.write(
            _render(_failure("SNAPSHOT_INTERNAL_ERROR", pair_root))
        )
        return 1
    sys.stdout.write(_render(payload))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
