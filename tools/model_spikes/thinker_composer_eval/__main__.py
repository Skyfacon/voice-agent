"""CLI entrypoint for the Thinker / Composer eval harness."""

from __future__ import annotations

import argparse
import json
import pathlib

from . import provider_probe
from .observations import DEFAULT_CONTRACT_SNAPSHOT, build_case_set, write_jsonl
from .schema import load_jsonl, validate_records
from .summarize import write_summary
from .synthetic_fixtures import DEFAULT_LOCAL_RUN_ROOT, fixture_policy_summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    dry_run = subparsers.add_parser("dry-run")
    dry_run.add_argument("--case-set", default="smoke")
    dry_run.add_argument("--contract-snapshot", default=DEFAULT_CONTRACT_SNAPSHOT)
    dry_run.add_argument(
        "--out",
        type=pathlib.Path,
        default=pathlib.Path(DEFAULT_LOCAL_RUN_ROOT) / "smoke" / "observations.jsonl",
    )

    validate = subparsers.add_parser("validate")
    validate.add_argument("--schema", type=pathlib.Path, required=True)
    validate.add_argument("--observations", type=pathlib.Path, required=True)

    summarize = subparsers.add_parser("summarize")
    summarize.add_argument("--observations", type=pathlib.Path, required=True)
    summarize.add_argument("--out", type=pathlib.Path, required=True)

    live_run = subparsers.add_parser("live-run")
    live_run.add_argument("--case-set", default="provider_probe")
    live_run.add_argument("--out", type=pathlib.Path)

    return parser.parse_args()


def command_dry_run(args: argparse.Namespace) -> int:
    records = build_case_set(args.case_set, args.contract_snapshot)
    output_path = write_jsonl(records, args.out)
    summary = {
        "command": "dry-run",
        "case_set": args.case_set,
        "observation_count": len(records),
        "case_ids": [record["case_id"] for record in records],
        "observations": str(output_path),
        "fixture_policy": fixture_policy_summary(),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def command_validate(args: argparse.Namespace) -> int:
    if not args.schema.expanduser().resolve().is_file():
        raise SystemExit(f"schema file not found: {args.schema}")
    records = load_jsonl(args.observations)
    count, errors = validate_records(records)
    summary = {
        "command": "validate",
        "observation_count": count,
        "valid": not errors,
        "errors": errors,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if not errors else 1


def command_summarize(args: argparse.Namespace) -> int:
    records = load_jsonl(args.observations)
    output_path = write_summary(records, args.out)
    summary = {
        "command": "summarize",
        "observation_count": len(records),
        "summary": str(output_path),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def command_live_run(args: argparse.Namespace) -> int:
    try:
        provider_probe.fail_closed()
    except provider_probe.ProviderProbeDisabled as exc:
        print(json.dumps({"command": "live-run", "enabled": False, "reason": str(exc)}))
        return 2
    return 1


def main() -> int:
    args = parse_args()
    if args.command == "dry-run":
        return command_dry_run(args)
    if args.command == "validate":
        return command_validate(args)
    if args.command == "summarize":
        return command_summarize(args)
    if args.command == "live-run":
        return command_live_run(args)
    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
