from __future__ import annotations

import argparse
from collections import Counter
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import io
import math
import os
from pathlib import Path
import shutil
import struct
from typing import Any
import wave

from voice_agent.adapters.asr_live_transport import (
    ASR_LIVE_SELECTED_MODEL_ALIAS,
    AsrLiveCredentialHandle,
    DashScopeAsrLiveDirectHTTPTransport,
    DashScopeAsrLiveTransportError,
)
from voice_agent.adapters.capabilities import CREDENTIAL_LIKE_REF_PATTERN


ASR_LIVE_EVAL_APPROVED_STATUS = (
    "approved_for_asr_provider_discovery_and_synthetic_live_eval"
)
ASR_LIVE_EVAL_REQUIRED_APPROVAL_FIELDS = (
    "approval_status",
    "approver",
    "approval_date",
    "approved_eval_scope",
    "provider_name",
    "model_alias",
    "model_alias_repin_date",
    "provider_transport_allowance",
    "credential_source",
    "credential_runtime_scope",
    "max_request_count",
    "max_cost_quota",
    "per_request_timeout_ms",
    "retry_budget",
    "synthetic_input_set_path",
    "input_redaction_status",
    "real_user_input_included",
    "output_storage_path",
    "redaction_policy",
    "cleanup_policy",
    "aggregate_metadata_commit_policy",
    "forbidden_commit_artifacts_acknowledged",
    "provider_endpoint_ref",
    "provider_endpoint_shape",
    "docs_source_urls",
    "provider_sdk_assumption",
    "model_alias_basis",
)
ASR_LIVE_EVAL_DEFAULT_APPROVAL_TEMPLATE_PATH = Path(
    "docs/implementation/asr-live-eval-approval-template.md"
)
ASR_LIVE_EVAL_DEFAULT_APPROVAL_PACKET_PATH = Path(
    "docs/implementation/asr-live-eval-approval-packet.md"
)
ASR_LIVE_EVAL_DEFAULT_INPUT_PATH = Path(
    "tests/fixtures/synthetic/asr-live-eval-inputs.jsonl"
)
ASR_LIVE_EVAL_LOCAL_OUTPUT_PREFIXES = (
    "diagnostics/",
    "traces/",
    "replays/local/",
    "outputs/",
)
ASR_LIVE_EVAL_CREDENTIAL_ENV_VAR = "DASHSCOPE_API_KEY"
ASR_LIVE_EVAL_FORBIDDEN_SYNTHETIC_INPUT_MARKERS = {
    "raw_audio": "raw_audio",
    "audio_bytes": "audio_bytes",
    "raw_transcript": "raw_transcript",
    "transcript_text": "transcript_text",
    "provider_request": "provider_request",
    "provider_response": "provider_response",
    "request_body": "request_body",
    "response_body": "response_body",
    "prompt_dump": "prompt_dump",
    "api_key": "api_key",
    "token": "token",
    "authorization": "authorization",
    "credential": "credential",
    "password": "password",
    "bearer": "Bearer",
}


class AsrLiveEvalApprovalError(ValueError):
    def __init__(self, message: str, *, failure_reasons: Sequence[str] | None = None) -> None:
        super().__init__(message)
        self.failure_reasons = list(failure_reasons or (message,))


@dataclass(frozen=True)
class AsrLiveEvalApprovalMetadata:
    required_fields: tuple[str, ...]
    approval_packet_complete: bool
    provider_call_allowed: bool
    secret_read_allowed: bool
    output_storage_local_only: bool
    dry_run_only: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "required_fields": self.required_fields,
            "approval_packet_complete": self.approval_packet_complete,
            "provider_call_allowed": self.provider_call_allowed,
            "secret_read_allowed": self.secret_read_allowed,
            "output_storage_local_only": self.output_storage_local_only,
            "dry_run_only": self.dry_run_only,
        }


@dataclass(frozen=True)
class AsrSyntheticLiveEvalSummary:
    attempted_request_count: int
    success_count: int
    request_failed_count: int
    retry_count: int
    timeout_count: int
    failure_category_counts: tuple[tuple[str, int], ...]
    output_storage_path: str
    cleanup_status: str
    aggregate_metadata_commit_policy: str

    def to_metadata(self) -> dict[str, object]:
        return {
            "attempted_request_count": self.attempted_request_count,
            "success_count": self.success_count,
            "request_failed_count": self.request_failed_count,
            "retry_count": self.retry_count,
            "timeout_count": self.timeout_count,
            "failure_category_counts": dict(self.failure_category_counts),
            "output_storage_path": self.output_storage_path,
            "cleanup_status": self.cleanup_status,
            "aggregate_metadata_commit_policy": self.aggregate_metadata_commit_policy,
            "raw_audio_included": False,
            "raw_transcript_included": False,
            "raw_provider_body_included": False,
            "headers_included": False,
            "secret_included": False,
            "provider_call_allowed": True,
            "real_user_input_included": False,
        }


def parse_asr_live_eval_approval_packet_markdown(text: str) -> dict[str, object]:
    if not isinstance(text, str) or text == "":
        _fail("approval packet text must be non-empty")

    fields: dict[str, object] = {}
    for line in text.splitlines():
        if not line.startswith("- "):
            continue
        key, separator, raw_value = line[2:].partition(":")
        if separator != ":":
            continue
        value = raw_value.strip()
        if value == "true":
            fields[key] = True
        elif value == "false":
            fields[key] = False
        elif _is_non_negative_int_text(value):
            fields[key] = int(value)
        else:
            fields[key] = value
    return fields


def validate_asr_live_eval_approval_packet(
    packet: Mapping[str, Any],
) -> AsrLiveEvalApprovalMetadata:
    if not isinstance(packet, Mapping):
        _fail("approval packet must be an object")

    missing_fields = [
        field for field in ASR_LIVE_EVAL_REQUIRED_APPROVAL_FIELDS if field not in packet
    ]
    if missing_fields:
        _fail(f"missing approval field: {missing_fields[0]}")

    if packet["approval_status"] != ASR_LIVE_EVAL_APPROVED_STATUS:
        _fail("approval_status is not approved")
    if packet["real_user_input_included"] is not False:
        _fail("real user input is not allowed")
    if packet["forbidden_commit_artifacts_acknowledged"] is not True:
        _fail("forbidden commit artifacts must be acknowledged")

    for field in ("max_request_count", "per_request_timeout_ms", "retry_budget"):
        _validate_int_bound(packet[field], field)
    if int(packet["max_request_count"]) < 1:
        _fail("max_request_count must be positive")
    if int(packet["max_request_count"]) > 10:
        _fail("max_request_count exceeds approved request bound")
    if int(packet["per_request_timeout_ms"]) < 1:
        _fail("per_request_timeout_ms must be positive")
    if int(packet["retry_budget"]) < 0:
        _fail("retry_budget must be non-negative")

    _validate_cost_quota(packet["max_cost_quota"])

    for field in ASR_LIVE_EVAL_REQUIRED_APPROVAL_FIELDS:
        if field in {
            "max_request_count",
            "per_request_timeout_ms",
            "retry_budget",
            "real_user_input_included",
            "forbidden_commit_artifacts_acknowledged",
        }:
            continue
        value = packet[field]
        if not isinstance(value, str) or value == "":
            _fail(f"approval field must be a non-empty string: {field}")
        if CREDENTIAL_LIKE_REF_PATTERN.search(value):
            _fail(
                f"approval field must not contain credential-like content: {field}",
                failure_reasons=(f"credential-like approval field: {field}",),
            )

    _validate_synthetic_input_set_path(str(packet["synthetic_input_set_path"]))
    if not _is_local_only_output_path(str(packet["output_storage_path"])):
        _fail("output_storage_path must be local-only")

    return AsrLiveEvalApprovalMetadata(
        required_fields=ASR_LIVE_EVAL_REQUIRED_APPROVAL_FIELDS,
        approval_packet_complete=True,
        provider_call_allowed=True,
        secret_read_allowed=False,
        output_storage_local_only=True,
        dry_run_only=False,
    )


def load_asr_live_eval_synthetic_inputs(
    fixture_path: str | Path,
) -> tuple[dict[str, Any], ...]:
    path = Path(fixture_path)
    _validate_synthetic_input_set_path(path.as_posix())
    if not path.exists():
        _fail("synthetic input set missing")

    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parsed = json.loads(line)
        if not isinstance(parsed, dict):
            _fail("synthetic live eval record must be an object")
        records.append(parsed)
    return validate_asr_live_eval_synthetic_inputs(tuple(records))


def validate_asr_live_eval_synthetic_inputs(
    records: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    if isinstance(records, (str, bytes)) or not isinstance(records, Sequence):
        _fail("synthetic input records must be a sequence")
    if not records:
        _fail("synthetic input records must be non-empty")

    validated: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, Mapping):
            _fail("synthetic live eval record must be an object")
        marker = _find_forbidden_synthetic_input_marker(record)
        if marker is not None:
            _fail(f"synthetic input contains forbidden marker: {marker}")
        if record.get("real_input") is not False:
            _fail("synthetic input record must declare real_input=false")
        if record.get("redaction_status") != "synthetic_metadata_refs_only":
            _fail("synthetic input record must be synthetic metadata only")
        validated.append(dict(record))
    return tuple(validated)


def run_asr_live_eval_dry_run(
    *,
    approval_packet: Mapping[str, Any],
    input_records: Sequence[Mapping[str, Any]],
) -> dict[str, object]:
    validate_asr_live_eval_approval_packet(approval_packet)
    records = validate_asr_live_eval_synthetic_inputs(input_records)
    max_request_count = int(approval_packet["max_request_count"])
    selected_count = min(len(records), max_request_count)

    return {
        "status": "would_run_provider_gated_synthetic_live_eval",
        "dry_run": True,
        "provider_call_allowed": True,
        "secret_read_allowed": False,
        "approved_eval_scope": str(approval_packet["approved_eval_scope"]),
        "provider_name": str(approval_packet["provider_name"]),
        "model_alias": str(approval_packet["model_alias"]),
        "model_alias_repin_date": str(approval_packet["model_alias_repin_date"]),
        "synthetic_input_record_count": selected_count,
        "max_request_count": max_request_count,
        "per_request_timeout_ms": int(approval_packet["per_request_timeout_ms"]),
        "retry_budget": int(approval_packet["retry_budget"]),
        "output_storage_path": str(approval_packet["output_storage_path"]),
        "cleanup_policy": str(approval_packet["cleanup_policy"]),
        "aggregate_metadata_commit_policy": str(
            approval_packet["aggregate_metadata_commit_policy"]
        ),
        "raw_audio_included": False,
        "raw_transcript_included": False,
        "raw_provider_body_included": False,
        "headers_included": False,
        "secret_included": False,
        "real_user_input_included": False,
    }


def run_asr_synthetic_live_eval(
    *,
    approval_packet: Mapping[str, Any],
    input_records: Sequence[Mapping[str, Any]],
    transport: object,
    credential_handle: AsrLiveCredentialHandle,
    credential_value: str | None,
) -> AsrSyntheticLiveEvalSummary:
    validate_asr_live_eval_approval_packet(approval_packet)
    _validate_live_eval_gate(
        approval_packet=approval_packet,
        credential_value=credential_value,
    )
    records = validate_asr_live_eval_synthetic_inputs(input_records)
    max_request_count = int(approval_packet["max_request_count"])
    retry_budget = int(approval_packet["retry_budget"])
    timeout_ms = int(approval_packet["per_request_timeout_ms"])
    selected_records = records[:max_request_count]
    output_dir = Path(str(approval_packet["output_storage_path"]))
    failure_categories: Counter[str] = Counter()
    success_count = 0
    request_failed_count = 0
    retry_count = 0
    timeout_count = 0

    try:
        for index, record in enumerate(selected_records, start=1):
            retries_used = 0
            while True:
                try:
                    transport.transcribe(
                        audio_payload=_generate_synthetic_wav_payload(
                            output_dir=output_dir,
                            case_id=str(record.get("case_id", f"case-{index}")),
                        ),
                        audio_mime_type="audio/wav",
                        credential_handle=credential_handle,
                        credential_value=str(credential_value),
                        adapter_request_id=_adapter_request_id_for_record(record, index),
                        timeout_ms=timeout_ms,
                        model_alias=str(approval_packet["model_alias"]),
                    )
                except DashScopeAsrLiveTransportError as exc:
                    for reason in exc.failure_reasons:
                        failure_categories[_classify_failure_reason(reason)] += 1
                    if exc.timeout:
                        timeout_count += 1
                    if exc.retryable and retries_used < retry_budget:
                        retry_count += 1
                        retries_used += 1
                        continue
                    request_failed_count += 1
                    break
                success_count += 1
                break
    finally:
        if str(approval_packet["cleanup_policy"]) == "delete_local_outputs_after_summary":
            shutil.rmtree(output_dir, ignore_errors=True)

    return AsrSyntheticLiveEvalSummary(
        attempted_request_count=len(selected_records),
        success_count=success_count,
        request_failed_count=request_failed_count,
        retry_count=retry_count,
        timeout_count=timeout_count,
        failure_category_counts=_counter_items(failure_categories),
        output_storage_path=str(approval_packet["output_storage_path"]),
        cleanup_status=str(approval_packet["cleanup_policy"]),
        aggregate_metadata_commit_policy=str(
            approval_packet["aggregate_metadata_commit_policy"]
        ),
    )


def run_asr_live_eval_entrypoint(
    *,
    approval_packet_path: str | Path = ASR_LIVE_EVAL_DEFAULT_APPROVAL_TEMPLATE_PATH,
    input_path: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    transport: object | None = None,
    run_live: bool = False,
) -> dict[str, object]:
    approval_path = Path(approval_packet_path)
    if not approval_path.exists():
        _fail("approval packet missing")

    approval_packet = parse_asr_live_eval_approval_packet_markdown(
        approval_path.read_text(encoding="utf-8")
    )
    validate_asr_live_eval_approval_packet(approval_packet)
    selected_input_path = (
        Path(str(approval_packet["synthetic_input_set_path"]))
        if input_path is None
        else Path(input_path)
    )
    if selected_input_path.as_posix() != str(approval_packet["synthetic_input_set_path"]):
        _fail("input path must match approved synthetic input set path")
    input_records = load_asr_live_eval_synthetic_inputs(selected_input_path)
    if run_live:
        runtime_env = os.environ if env is None else env
        summary = run_asr_synthetic_live_eval(
            approval_packet=approval_packet,
            input_records=input_records,
            transport=transport if transport is not None else DashScopeAsrLiveDirectHTTPTransport(),
            credential_handle=AsrLiveCredentialHandle(
                credential_ref="secret-ref://local/asr-live-eval/dashscope",
            ),
            credential_value=runtime_env.get(ASR_LIVE_EVAL_CREDENTIAL_ENV_VAR),
        )
        return summary.to_metadata()
    return run_asr_live_eval_dry_run(
        approval_packet=approval_packet,
        input_records=input_records,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate the approval-gated ASR live eval dry-run skeleton."
    )
    parser.add_argument(
        "--approval-packet",
        default=str(ASR_LIVE_EVAL_DEFAULT_APPROVAL_TEMPLATE_PATH),
    )
    parser.add_argument("--input", default=None)
    parser.add_argument(
        "--run-live",
        action="store_true",
        help="Run the bounded provider eval after approval and credential gates pass.",
    )
    args = parser.parse_args(argv)

    try:
        metadata = run_asr_live_eval_entrypoint(
            approval_packet_path=Path(args.approval_packet),
            input_path=None if args.input is None else Path(args.input),
            env=os.environ,
            run_live=args.run_live,
        )
    except AsrLiveEvalApprovalError as exc:
        print(
            json.dumps(
                {
                    "success": False,
                    "failure_reasons": exc.failure_reasons,
                    "provider_call_allowed": False,
                    "secret_read_allowed": False,
                    "raw_audio_included": False,
                    "raw_transcript_included": False,
                    "raw_provider_body_included": False,
                    "headers_included": False,
                    "secret_included": False,
                },
                sort_keys=True,
            )
        )
        return 2

    print(json.dumps({"success": True, "summary": metadata}, sort_keys=True))
    return 0


def _validate_int_bound(value: Any, field: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        _fail(f"approval field must be an integer: {field}")


def _validate_cost_quota(value: Any) -> None:
    if isinstance(value, bool):
        _fail("max_cost_quota must be a string or non-negative number")
    if isinstance(value, (int, float)):
        if value < 0:
            _fail("max_cost_quota must be non-negative")
        return
    if not isinstance(value, str) or value == "":
        _fail("approval field must be a non-empty string: max_cost_quota")
    if CREDENTIAL_LIKE_REF_PATTERN.search(value):
        _fail(
            "approval field must not contain credential-like content: max_cost_quota",
            failure_reasons=("credential-like approval field: max_cost_quota",),
        )


def _validate_live_eval_gate(
    *,
    approval_packet: Mapping[str, Any],
    credential_value: str | None,
) -> None:
    if _model_alias_requires_provider_discovery(str(approval_packet["model_alias"])):
        _fail(
            "model_alias requires provider discovery re-pin",
            failure_reasons=("model_alias requires provider discovery re-pin",),
        )
    if str(approval_packet["model_alias"]) != ASR_LIVE_SELECTED_MODEL_ALIAS:
        _fail("model_alias does not match selected ASR provider alias")
    if (
        str(approval_packet["provider_transport_allowance"])
        != "direct_http_only_preferred_sdk_allowed_only_if_official_docs_require_it"
    ):
        _fail("provider transport allowance is not direct HTTP")
    if not isinstance(credential_value, str) or credential_value == "":
        _fail("credential value missing", failure_reasons=("credential value missing",))


def _model_alias_requires_provider_discovery(value: str) -> bool:
    lowered = value.lower()
    return "human-repin-required" in lowered or "placeholder" in lowered


def _validate_synthetic_input_set_path(path_text: str) -> None:
    if not isinstance(path_text, str) or path_text == "":
        _fail("synthetic_input_set_path must be a non-empty string")
    if CREDENTIAL_LIKE_REF_PATTERN.search(path_text) or _looks_like_local_path(path_text):
        _fail("synthetic_input_set_path is unsafe")
    path = Path(path_text)
    parts = path.parts
    if path.is_absolute() or ".." in parts:
        _fail("synthetic_input_set_path is unsafe")
    if not path.as_posix().startswith("tests/fixtures/synthetic/"):
        _fail("synthetic_input_set_path is unsafe")
    if path.suffix != ".jsonl":
        _fail("synthetic_input_set_path is unsafe")


def _is_local_only_output_path(path_text: str) -> bool:
    if not isinstance(path_text, str) or path_text == "":
        return False
    if CREDENTIAL_LIKE_REF_PATTERN.search(path_text) or _looks_like_local_path(path_text):
        return False
    path = Path(path_text)
    if path.is_absolute() or ".." in path.parts:
        return False
    normalized = path.as_posix()
    return any(normalized.startswith(prefix) for prefix in ASR_LIVE_EVAL_LOCAL_OUTPUT_PREFIXES)


def _find_forbidden_synthetic_input_marker(value: Any) -> str | None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            marker = _forbidden_marker_from_text(str(key))
            if marker is not None:
                return marker
            marker = _find_forbidden_synthetic_input_marker(item)
            if marker is not None:
                return marker
        return None
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            marker = _find_forbidden_synthetic_input_marker(item)
            if marker is not None:
                return marker
        return None
    if isinstance(value, str):
        return _forbidden_marker_from_text(value)
    return None


def _forbidden_marker_from_text(value: str) -> str | None:
    if _looks_like_local_path(value):
        return "local path"
    lowered = value.lower()
    for marker, display in ASR_LIVE_EVAL_FORBIDDEN_SYNTHETIC_INPUT_MARKERS.items():
        if marker in lowered:
            return display
    if CREDENTIAL_LIKE_REF_PATTERN.search(value):
        return "credential"
    return None


def _adapter_request_id_for_record(record: Mapping[str, Any], index: int) -> str:
    case_id = str(record.get("case_id", f"case-{index}"))
    slug = "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in case_id
    )
    return f"adapter_request_asr_live_eval_{index:03d}_{slug}"


def _generate_synthetic_wav_payload(
    *,
    output_dir: Path,
    case_id: str,
) -> bytes:
    audio_dir = output_dir / "synthetic-audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    path = audio_dir / f"{_safe_filename_slug(case_id)}.wav"
    payload = _build_synthetic_wav_bytes()
    path.write_bytes(payload)
    return path.read_bytes()


def _build_synthetic_wav_bytes() -> bytes:
    sample_rate = 8000
    duration_seconds = 0.25
    amplitude = 800
    frequency = 440
    frame_count = int(sample_rate * duration_seconds)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        frames = bytearray()
        for frame_index in range(frame_count):
            sample = int(
                amplitude
                * math.sin(2 * math.pi * frequency * frame_index / sample_rate)
            )
            frames.extend(struct.pack("<h", sample))
        wav_file.writeframes(bytes(frames))
    return buffer.getvalue()


def _safe_filename_slug(value: str) -> str:
    slug = "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in value
    )
    return slug or "synthetic_asr_live_eval"


def _classify_failure_reason(value: str) -> str:
    if value in {
        "provider_timeout",
        "provider_request_failed",
        "provider_response_parse_failed",
        "provider_response_text_missing",
        "provider_http_status_class_4xx",
        "provider_http_status_class_5xx",
        "unsupported_audio_mime_type",
        "credential value missing",
    }:
        return value
    if value.startswith("provider_http_status_class_"):
        return value
    if value.startswith("provider_response_shape_"):
        return value
    if CREDENTIAL_LIKE_REF_PATTERN.search(value):
        return "redacted_failure"
    return "other_failure"


def _counter_items(counter: Counter[str]) -> tuple[tuple[str, int], ...]:
    return tuple(sorted((category, count) for category, count in counter.items() if count))


def _looks_like_local_path(value: str) -> bool:
    return (
        value.startswith("/")
        or value.startswith("~/")
        or value.startswith("file://")
        or "\\Users\\" in value
        or "/Users/" in value
        or len(value) > 2
        and value[1:3] == ":\\"
        and value[0].isalpha()
    )


def _is_non_negative_int_text(value: str) -> bool:
    return value.isdigit()


def _fail(
    message: str,
    *,
    failure_reasons: Sequence[str] | None = None,
) -> None:
    raise AsrLiveEvalApprovalError(message, failure_reasons=failure_reasons)


if __name__ == "__main__":
    raise SystemExit(main())
