from __future__ import annotations

import argparse
import ast
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any
from urllib.parse import unquote

from voice_agent.adapters.capabilities import CREDENTIAL_LIKE_REF_PATTERN


LALM_THINKER_LIVE_EVAL_APPROVAL_SCHEMA = "voice_agent.lalm_thinker.live_eval_approval.v1"
LALM_THINKER_REQUIRED_LIVE_EVAL_APPROVAL_FIELDS = (
    "approval_packet_schema",
    "human_approved",
    "provider_model_alias",
    "provider_model_alias_recheck_date",
    "synthetic_input_set_ref",
    "synthetic_input_set_only",
    "cost_quota_time_budget",
    "max_request_count",
    "per_request_timeout_ms",
    "retry_limit",
    "output_location",
    "output_location_policy",
    "cleanup_policy",
    "redaction_non_retention_policy",
    "forbidden_artifacts_acknowledged",
    "allowed_outputs",
    "fail_closed_behavior",
    "provider_native_tool_execution_allowed",
    "canonical_event_changes_allowed",
    "production_traffic_allowed",
)

_ALLOWED_OUTPUTS = ("gate_status_metadata_only",)
_LIVE_EVAL_ALLOWED_OUTPUTS = ("metadata_summary_only",)
_ALL_ALLOWED_OUTPUTS = frozenset({_ALLOWED_OUTPUTS, _LIVE_EVAL_ALLOWED_OUTPUTS})
_ALLOWED_OUTPUT_LOCATION_POLICIES = frozenset({"local_only_ignored"})
_SAFE_LOCAL_OUTPUT_PREFIXES = ("outputs/lalm-thinker/", "diagnostics/lalm-thinker/")
_FORBIDDEN_OUTPUT_PREFIXES = ("audio/raw/", "traces/", "replays/local/")
_RECHECK_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MAX_GOAL_D_REQUEST_COUNT = 10
_MAX_GOAL_D_TIMEOUT_MS = 60000
_MAX_GOAL_D_RETRY_LIMIT = 1


class LALMThinkerLiveEvalApprovalError(ValueError):
    def __init__(self, category: str) -> None:
        self.category = category
        self.failure_ref = f"validation://synthetic/lalm-thinker/live-eval/{_slug(category)}"
        super().__init__(
            "lalm_thinker_live_eval_gate_failed "
            f"category={self.category} failure_ref={self.failure_ref}"
        )


@dataclass(frozen=True)
class LALMThinkerLiveEvalGateMetadata:
    approval_packet_complete: bool
    human_approved: bool
    synthetic_input_set_only: bool
    output_location_safe: bool
    allowed_outputs: tuple[str, ...] = _ALLOWED_OUTPUTS
    provider_call_allowed: bool = False
    secret_read_allowed: bool = False
    dry_run_only: bool = True
    live_eval_output_generated: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "approval_packet_complete": self.approval_packet_complete,
            "allowed_outputs": list(self.allowed_outputs),
            "dry_run_only": self.dry_run_only,
            "human_approved": self.human_approved,
            "live_eval_output_generated": self.live_eval_output_generated,
            "output_location_safe": self.output_location_safe,
            "provider_call_allowed": self.provider_call_allowed,
            "secret_read_allowed": self.secret_read_allowed,
            "synthetic_input_set_only": self.synthetic_input_set_only,
        }


def parse_lalm_thinker_live_eval_approval_text(text: str) -> dict[str, object]:
    if not isinstance(text, str) or text.strip() == "":
        raise LALMThinkerLiveEvalApprovalError("malformed_approval")

    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise LALMThinkerLiveEvalApprovalError("malformed_approval") from exc
        if not isinstance(parsed, dict):
            raise LALMThinkerLiveEvalApprovalError("malformed_approval")
        return parsed

    fields: dict[str, object] = {}
    for line in stripped.splitlines():
        if not line.startswith("- "):
            continue
        key, separator, raw_value = line[2:].partition(":")
        if separator != ":":
            continue
        key = key.strip()
        if key == "":
            raise LALMThinkerLiveEvalApprovalError("malformed_approval")
        fields[key] = _parse_markdown_scalar(raw_value.strip())
    if not fields:
        raise LALMThinkerLiveEvalApprovalError("malformed_approval")
    return fields


def load_lalm_thinker_live_eval_approval(path: str | Path) -> dict[str, object]:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise LALMThinkerLiveEvalApprovalError("missing_approval") from exc
    except OSError as exc:
        raise LALMThinkerLiveEvalApprovalError("approval_unreadable") from exc
    return parse_lalm_thinker_live_eval_approval_text(text)


def validate_lalm_thinker_live_eval_approval(
    packet: Mapping[str, Any],
) -> LALMThinkerLiveEvalGateMetadata:
    if not isinstance(packet, Mapping):
        raise LALMThinkerLiveEvalApprovalError("malformed_approval")

    _reject_credential_like_content(packet)

    for field in LALM_THINKER_REQUIRED_LIVE_EVAL_APPROVAL_FIELDS:
        if field not in packet:
            raise LALMThinkerLiveEvalApprovalError("missing_required_field")

    if packet["approval_packet_schema"] != LALM_THINKER_LIVE_EVAL_APPROVAL_SCHEMA:
        raise LALMThinkerLiveEvalApprovalError("approval_schema_mismatch")
    if packet["human_approved"] is not True:
        raise LALMThinkerLiveEvalApprovalError("human_approval_required")
    if packet["synthetic_input_set_only"] is not True:
        raise LALMThinkerLiveEvalApprovalError("synthetic_input_required")
    if packet["forbidden_artifacts_acknowledged"] is not True:
        raise LALMThinkerLiveEvalApprovalError("forbidden_artifacts_acknowledgement_required")
    if packet["provider_native_tool_execution_allowed"] is not False:
        raise LALMThinkerLiveEvalApprovalError("provider_native_tool_execution_forbidden")
    if packet["canonical_event_changes_allowed"] is not False:
        raise LALMThinkerLiveEvalApprovalError("canonical_event_changes_forbidden")
    if packet["production_traffic_allowed"] is not False:
        raise LALMThinkerLiveEvalApprovalError("production_traffic_forbidden")

    for field in (
        "provider_model_alias",
        "cost_quota_time_budget",
        "cleanup_policy",
        "redaction_non_retention_policy",
        "fail_closed_behavior",
    ):
        _require_non_empty_string(packet[field])
    _validate_model_alias(str(packet["provider_model_alias"]))
    _validate_recheck_date(packet["provider_model_alias_recheck_date"])
    _validate_synthetic_input_ref(packet["synthetic_input_set_ref"])
    _validate_positive_int(packet["max_request_count"])
    _validate_positive_int(packet["per_request_timeout_ms"])
    _validate_non_negative_int(packet["retry_limit"])
    _validate_allowed_outputs(packet["allowed_outputs"])
    _validate_fail_closed_behavior(str(packet["fail_closed_behavior"]))
    _validate_output_location(packet["output_location"], packet["output_location_policy"])

    return LALMThinkerLiveEvalGateMetadata(
        approval_packet_complete=True,
        allowed_outputs=tuple(str(item) for item in packet["allowed_outputs"]),
        human_approved=True,
        synthetic_input_set_only=True,
        output_location_safe=True,
    )


def validate_lalm_thinker_live_eval_run_approval(
    packet: Mapping[str, Any],
    *,
    credential_value: str | None,
) -> LALMThinkerLiveEvalGateMetadata:
    metadata = validate_lalm_thinker_live_eval_approval(packet)
    if tuple(packet["allowed_outputs"]) != _LIVE_EVAL_ALLOWED_OUTPUTS:
        raise LALMThinkerLiveEvalApprovalError("allowed_outputs_not_metadata_only")
    if int(packet["max_request_count"]) > _MAX_GOAL_D_REQUEST_COUNT:
        raise LALMThinkerLiveEvalApprovalError("invalid_budget")
    if int(packet["per_request_timeout_ms"]) > _MAX_GOAL_D_TIMEOUT_MS:
        raise LALMThinkerLiveEvalApprovalError("invalid_budget")
    if int(packet["retry_limit"]) > _MAX_GOAL_D_RETRY_LIMIT:
        raise LALMThinkerLiveEvalApprovalError("invalid_budget")
    if credential_value is None or credential_value == "":
        raise LALMThinkerLiveEvalApprovalError("credential_missing")
    return LALMThinkerLiveEvalGateMetadata(
        approval_packet_complete=metadata.approval_packet_complete,
        allowed_outputs=_LIVE_EVAL_ALLOWED_OUTPUTS,
        human_approved=metadata.human_approved,
        synthetic_input_set_only=metadata.synthetic_input_set_only,
        output_location_safe=metadata.output_location_safe,
        provider_call_allowed=True,
        secret_read_allowed=True,
        dry_run_only=False,
        live_eval_output_generated=False,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "provider-free LALM Thinker live eval approval gate and explicit "
            "approval-gated synthetic metadata-only live eval runner."
        )
    )
    parser.add_argument("--approval", help="Path to JSON or markdown approval metadata.")
    parser.add_argument(
        "--dry-run-gate-check",
        action="store_true",
        help="Validate approval metadata and report gate status without producing eval output.",
    )
    parser.add_argument(
        "--run-approved-synthetic-live-eval",
        action="store_true",
        help=(
            "Run the explicitly approved synthetic metadata-only live eval. "
            "Requires approval metadata and DASHSCOPE_API_KEY in the runtime environment."
        ),
    )
    args = parser.parse_args(argv)

    try:
        if not args.approval:
            raise LALMThinkerLiveEvalApprovalError("missing_approval")
        if args.dry_run_gate_check and args.run_approved_synthetic_live_eval:
            raise LALMThinkerLiveEvalApprovalError("single_mode_required")
        if args.run_approved_synthetic_live_eval:
            from voice_agent.adapters.lalm_thinker_live_eval_entrypoint import (
                run_lalm_thinker_live_eval_entrypoint,
            )

            metadata = run_lalm_thinker_live_eval_entrypoint(
                approval_path=args.approval,
            )
            print(json.dumps({"success": True, "summary": metadata}, sort_keys=True))
            return 0
        if not args.dry_run_gate_check:
            raise LALMThinkerLiveEvalApprovalError("dry_run_gate_check_required")
        packet = load_lalm_thinker_live_eval_approval(args.approval)
        metadata = validate_lalm_thinker_live_eval_approval(packet)
    except LALMThinkerLiveEvalApprovalError as exc:
        print(
            json.dumps(
                {
                    "success": False,
                    "category": exc.category,
                    "failure_ref": exc.failure_ref,
                    "provider_call_allowed": False,
                    "secret_read_allowed": False,
                    "live_eval_output_generated": False,
                },
                sort_keys=True,
            )
        )
        return 2

    print(json.dumps({"success": True, "gate_check": metadata.to_dict()}, sort_keys=True))
    return 0


def _parse_markdown_scalar(value: str) -> object:
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value.isdigit():
        return int(value)
    if value.startswith("[") and value.endswith("]"):
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError) as exc:
            raise LALMThinkerLiveEvalApprovalError("malformed_approval") from exc
        if not isinstance(parsed, list):
            raise LALMThinkerLiveEvalApprovalError("malformed_approval")
        return parsed
    return value


def _validate_model_alias(value: str) -> None:
    lowered = value.lower()
    if "placeholder" in lowered or "human-repin-required" in lowered:
        raise LALMThinkerLiveEvalApprovalError("model_alias_recheck_required")


def _validate_recheck_date(value: object) -> None:
    if not isinstance(value, str) or _RECHECK_DATE_PATTERN.fullmatch(value) is None:
        raise LALMThinkerLiveEvalApprovalError("invalid_recheck_date")


def _validate_synthetic_input_ref(value: object) -> None:
    if not isinstance(value, str) or value == "":
        raise LALMThinkerLiveEvalApprovalError("synthetic_input_required")
    if not value.startswith("synthetic-input-set://"):
        raise LALMThinkerLiveEvalApprovalError("synthetic_input_required")


def _validate_positive_int(value: object) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise LALMThinkerLiveEvalApprovalError("invalid_budget")


def _validate_non_negative_int(value: object) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise LALMThinkerLiveEvalApprovalError("invalid_budget")


def _validate_allowed_outputs(value: object) -> None:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or tuple(value) not in _ALL_ALLOWED_OUTPUTS
    ):
        raise LALMThinkerLiveEvalApprovalError("allowed_outputs_not_metadata_only")


def _validate_fail_closed_behavior(value: str) -> None:
    lowered = value.lower()
    if "fail" not in lowered and "block" not in lowered:
        raise LALMThinkerLiveEvalApprovalError("fail_closed_behavior_required")


def _validate_output_location(value: object, policy: object) -> None:
    if policy not in _ALLOWED_OUTPUT_LOCATION_POLICIES:
        raise LALMThinkerLiveEvalApprovalError("unsafe_output_location")
    if not isinstance(value, str) or value == "":
        raise LALMThinkerLiveEvalApprovalError("unsafe_output_location")
    decoded = unquote(value).replace("\\", "/")
    if decoded.startswith("/") or decoded.startswith("~") or "://" in decoded:
        raise LALMThinkerLiveEvalApprovalError("unsafe_output_location")
    path = PurePosixPath(decoded)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise LALMThinkerLiveEvalApprovalError("unsafe_output_location")
    normalized = path.as_posix().rstrip("/") + "/"
    if any(normalized.startswith(prefix) for prefix in _FORBIDDEN_OUTPUT_PREFIXES):
        raise LALMThinkerLiveEvalApprovalError("unsafe_output_location")
    if not any(normalized.startswith(prefix) for prefix in _SAFE_LOCAL_OUTPUT_PREFIXES):
        raise LALMThinkerLiveEvalApprovalError("unsafe_output_location")


def _reject_credential_like_content(value: object) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise LALMThinkerLiveEvalApprovalError("malformed_approval")
            _reject_credential_like_string(key)
            _reject_credential_like_content(nested)
    elif isinstance(value, str):
        _reject_credential_like_string(value)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for nested in value:
            _reject_credential_like_content(nested)


def _reject_credential_like_string(value: str) -> None:
    variants = (value, unquote(value))
    if any(CREDENTIAL_LIKE_REF_PATTERN.search(variant) for variant in variants):
        raise LALMThinkerLiveEvalApprovalError("credential_like_content")


def _require_non_empty_string(value: object) -> str:
    if not isinstance(value, str) or value == "":
        raise LALMThinkerLiveEvalApprovalError("invalid_approval_field")
    return value


def _slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-") or "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
