from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Sequence

from voice_agent.evals.routing.audit import (
    audit_routing_corpus,
    milestone1_prompt_dev_policy,
)
from voice_agent.evals.routing.e2e_runner import run_routing_e2e_case
from voice_agent.evals.routing.loader import load_routing_cases_jsonl
from voice_agent.evals.routing.metrics import (
    RoutingPrediction,
    aggregate_metrics,
    evaluate_case,
)
from voice_agent.evals.routing.report import build_safe_report
from voice_agent.evals.routing.review_packet import (
    build_human_review_packet,
    render_human_review_packet_markdown,
)
from voice_agent.evals.routing.router_runner import (
    oracle_policy_evidence_from_gold,
    run_router_policy_case,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_MANIFEST = REPO_ROOT / "evals" / "routing" / "manifests" / "prompt-dev.jsonl"
CLI_RUN_SCHEMA_NAME = "voice_agent.routing_eval.cli_run.v1"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="routing-eval",
        description="Provider-free routing corpus, policy, and E2E evaluation tools.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit = subparsers.add_parser(
        "audit", help="validate the Milestone 1 corpus and quota"
    )
    _add_manifest_argument(audit)

    review = subparsers.add_parser(
        "review", help="render the safe synthetic Human Review Packet"
    )
    _add_manifest_argument(review)

    for name, help_text in (
        ("router", "run the deterministic Router policy harness"),
        ("e2e", "run Router, foreground gate, state effects, and replay"),
    ):
        command = subparsers.add_parser(name, help=help_text)
        _add_manifest_argument(command)
        command.add_argument(
            "--oracle-policy",
            action="store_true",
            help=(
                "required explicit opt-in to gold-derived, provider-free policy "
                "evidence; this does not evaluate a model"
            ),
        )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    cases = load_routing_cases_jsonl(args.manifest)

    if args.command == "audit":
        result = audit_routing_corpus(cases, policy=milestone1_prompt_dev_policy())
        _write_json(result)
        return 0 if result["status"] == "passed" else 1

    if args.command == "review":
        packet = build_human_review_packet(cases)
        sys.stdout.write(render_human_review_packet_markdown(packet))
        return 0

    if not args.oracle_policy:
        parser.error(
            f"{args.command} requires explicit --oracle-policy; "
            "gold-derived evidence is a policy harness, not a model evaluation"
        )

    if args.command == "router":
        evaluations = []
        for case in cases:
            run = run_router_policy_case(
                case,
                predicted_evidence=oracle_policy_evidence_from_gold(case),
            )
            prediction = RoutingPrediction(**run.evaluation.to_prediction_dict())
            evaluations.append(evaluate_case(case, prediction))
    elif args.command == "e2e":
        evaluations = []
        for case in cases:
            run = run_routing_e2e_case(
                case,
                predicted_evidence=oracle_policy_evidence_from_gold(case),
            )
            prediction = RoutingPrediction(**run.evaluation.to_prediction_dict())
            evaluations.append(evaluate_case(case, prediction))
    else:  # pragma: no cover - argparse constrains this branch.
        parser.error(f"unsupported command: {args.command}")

    metrics = aggregate_metrics(evaluations)
    safe_report = build_safe_report(
        metrics,
        {
            "run_id": f"milestone1-{args.command}-oracle",
            "dataset_id": "routing-prompt-dev-v1",
            "dataset_version": "draft-v1",
            "mode": "oracle",
            "layer": args.command,
        },
    )
    output: dict[str, Any] = {
        "schema_name": CLI_RUN_SCHEMA_NAME,
        "command": args.command,
        "execution_scope": "deterministic_policy_contract_only",
        "model_evaluated": False,
        "oracle_evidence_used": True,
        "gold_derived_evidence": True,
        "interpretation": "not_a_model_evaluation",
        "report": safe_report,
    }
    _write_json(output)
    return 0 if metrics["critical_violations"]["count"] == 0 else 1


def _add_manifest_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="routing case JSONL (default: Milestone 1 prompt-dev manifest)",
    )


def _write_json(value: object) -> None:
    sys.stdout.write(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    )


if __name__ == "__main__":
    raise SystemExit(main())
