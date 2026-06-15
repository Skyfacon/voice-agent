from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import os
from pathlib import Path
import time
from typing import Any

from voice_agent.adapters.lalm_thinker_binding import bind_lalm_thinker_request
from voice_agent.adapters.lalm_thinker_live_eval_gate import (
    LALMThinkerLiveEvalApprovalError,
    load_lalm_thinker_live_eval_approval,
    validate_lalm_thinker_live_eval_run_approval,
)
from voice_agent.adapters.lalm_thinker_live_transport import (
    LALMThinkerCredentialHandle,
    LALMThinkerLiveDirectHTTPTransport,
    LALMThinkerLiveTransportError,
    LALM_THINKER_CREDENTIAL_SOURCE_METADATA,
)
from voice_agent.adapters.lalm_thinker_profile import LALM_THINKER_RUNTIME_ADAPTER_ID
from voice_agent.adapters.lalm_thinker_skeleton import (
    emit_lalm_thinker_live_provider_result,
    emit_lalm_thinker_request_failed,
    emit_lalm_thinker_request_retrying,
)
from voice_agent.events.journal import InMemoryEventJournal
from voice_agent.runtime.adapter_callback_boundary import AdapterCallbackAppendBoundary


_LALM_THINKER_CREDENTIAL_ENV_VAR = "DASHSCOPE_API_KEY"
_LALM_THINKER_ADAPTER_ID = LALM_THINKER_RUNTIME_ADAPTER_ID


@dataclass(frozen=True)
class _LiveEvalStartup:
    journal: InMemoryEventJournal


@dataclass(frozen=True)
class LALMThinkerSyntheticLiveEvalSummary:
    request_count: int
    validated_count: int
    validation_failed_count: int
    request_failed_count: int
    retry_count: int
    timeout_count: int
    failure_category_counts: tuple[tuple[str, int], ...]
    retry_reason_counts: tuple[tuple[str, int], ...]
    validation_failure_category_counts: tuple[tuple[str, int], ...]
    latency_buckets: tuple[tuple[str, int], ...]
    status_buckets: tuple[tuple[str, int], ...]
    safe_refs: tuple[dict[str, str], ...]
    output_location: str
    output_file: str
    cleanup_status: str
    provider_model_alias: str
    provider_model_alias_recheck_date: str
    max_request_count: int
    per_request_timeout_ms: int
    retry_limit: int

    def to_metadata(self) -> dict[str, Any]:
        return {
            "request_count": self.request_count,
            "validated_count": self.validated_count,
            "validation_failed_count": self.validation_failed_count,
            "request_failed_count": self.request_failed_count,
            "retry_count": self.retry_count,
            "timeout_count": self.timeout_count,
            "failure_category_counts": dict(self.failure_category_counts),
            "retry_reason_counts": dict(self.retry_reason_counts),
            "validation_failure_category_counts": dict(
                self.validation_failure_category_counts
            ),
            "latency_buckets": dict(self.latency_buckets),
            "status_buckets": dict(self.status_buckets),
            "safe_refs": list(self.safe_refs),
            "output_location": self.output_location,
            "output_file": self.output_file,
            "cleanup_status": self.cleanup_status,
            "provider_model_alias": self.provider_model_alias,
            "provider_model_alias_recheck_date": self.provider_model_alias_recheck_date,
            "request_budget": {
                "max_request_count": self.max_request_count,
                "per_request_timeout_ms": self.per_request_timeout_ms,
                "retry_limit": self.retry_limit,
            },
            "credential_source": LALM_THINKER_CREDENTIAL_SOURCE_METADATA,
            "input_scope": "synthetic_metadata_only",
            "output_scope": "aggregate_metadata_safe_refs_only",
            "raw_provider_request_included": False,
            "raw_provider_response_included": False,
            "secret_included": False,
            "raw_audio_included": False,
            "raw_trace_included": False,
            "real_user_input_included": False,
            "authorization_header_included": False,
            "bearer_token_included": False,
            "full_prompt_included": False,
            "provider_native_tool_execution_included": False,
            "canonical_event_changes_included": False,
        }


def run_lalm_thinker_live_eval_entrypoint(
    *,
    approval_path: str | Path,
    env: Mapping[str, str] | None = None,
    transport: object | None = None,
    repo_root: str | Path = ".",
) -> dict[str, Any]:
    packet = load_lalm_thinker_live_eval_approval(approval_path)
    runtime_env = os.environ if env is None else env
    credential_value = runtime_env.get(_LALM_THINKER_CREDENTIAL_ENV_VAR)
    gate = validate_lalm_thinker_live_eval_run_approval(
        packet,
        credential_value=credential_value,
    )
    records = _build_synthetic_live_eval_records(int(packet["max_request_count"]))
    summary = run_lalm_thinker_synthetic_live_eval(
        approval_packet=packet,
        input_records=records,
        transport=transport if transport is not None else LALMThinkerLiveDirectHTTPTransport(),
        credential_value=credential_value,
    )
    metadata = summary.to_metadata()
    output_file = _write_metadata_summary(
        repo_root=Path(repo_root),
        output_location=str(packet["output_location"]),
        metadata=metadata,
    )
    metadata["output_file"] = str(output_file)
    metadata["provider_call_allowed"] = gate.provider_call_allowed
    metadata["secret_read_allowed"] = gate.secret_read_allowed
    _write_metadata_summary(
        repo_root=Path(repo_root),
        output_location=str(packet["output_location"]),
        metadata=metadata,
    )
    return metadata


def run_lalm_thinker_synthetic_live_eval(
    *,
    approval_packet: Mapping[str, Any],
    input_records: Sequence[Mapping[str, Any]],
    transport: object,
    credential_value: str | None,
) -> LALMThinkerSyntheticLiveEvalSummary:
    gate = validate_lalm_thinker_live_eval_run_approval(
        approval_packet,
        credential_value=credential_value,
    )
    if credential_value is None:
        raise LALMThinkerLiveEvalApprovalError("credential_missing")

    selected_records = tuple(input_records[: int(approval_packet["max_request_count"])])
    startup = _start_lalm_thinker_live_eval_session()
    boundary = AdapterCallbackAppendBoundary(startup.journal)
    credential_handle = LALMThinkerCredentialHandle(
        credential_ref="secret-ref://runtime-env/dashscope-api-key",
    )

    validated_count = 0
    validation_failed_count = 0
    request_failed_count = 0
    retry_count = 0
    timeout_count = 0
    failure_category_counts: Counter[str] = Counter()
    retry_reason_counts: Counter[str] = Counter()
    validation_failure_category_counts: Counter[str] = Counter()
    latency_buckets: Counter[str] = Counter()
    status_buckets: Counter[str] = Counter()
    safe_refs: list[dict[str, str]] = []

    for record_index, record in enumerate(selected_records, start=1):
        turn = _append_synthetic_committed_turn(
            startup.journal,
            record=record,
            record_index=record_index,
        )
        binding = bind_lalm_thinker_request(
            turn_committed_event=turn,
            adapter_request_id=str(record["adapter_request_id"]),
            request_metadata_ref=str(record["request_metadata_ref"]),
            input_ref=str(record["input_ref"]),
            policy_ref="policy://synthetic/lalm-thinker/evidence-only",
        )
        caused_by_event_id = str(turn["event_id"])
        case_slug = _safe_slug(str(record["case_id"]))
        case_completed = False

        for attempt_index in range(int(approval_packet["retry_limit"]) + 1):
            start = time.monotonic()
            try:
                result = emit_lalm_thinker_live_provider_result(
                    transport=transport,
                    credential_handle=credential_handle,
                    credential_value=credential_value,
                    model_alias=str(approval_packet["provider_model_alias"]),
                    timeout_ms=int(approval_packet["per_request_timeout_ms"]),
                    boundary=boundary,
                    adapter_id=_LALM_THINKER_ADAPTER_ID,
                    binding=binding,
                    success_event_id=(
                        f"evt_lalm_thinker_live_eval_{case_slug}_frame_{attempt_index + 1}"
                    ),
                    validation_failed_event_id=(
                        f"evt_lalm_thinker_live_eval_{case_slug}_validation_failed_"
                        f"{attempt_index + 1}"
                    ),
                    caused_by_event_id=caused_by_event_id,
                    created_monotonic_ms=300 + record_index * 10 + attempt_index,
                    created_wall_clock_ms=1700000000300 + record_index * 10 + attempt_index,
                    turn_committed_event=turn,
                    transient_input_text=str(record["transient_input_text"]),
                )
            except LALMThinkerLiveTransportError as exc:
                latency_buckets[_latency_bucket(time.monotonic() - start)] += 1
                failure_category_counts[exc.category] += 1
                if exc.category == "provider_timeout":
                    timeout_count += 1
                if attempt_index < int(approval_packet["retry_limit"]):
                    retry_count += 1
                    retry_reason_counts[exc.category] += 1
                    emit_lalm_thinker_request_retrying(
                        boundary=boundary,
                        event_id=(
                            f"evt_lalm_thinker_live_eval_{case_slug}_retry_"
                            f"{attempt_index + 1}"
                        ),
                        caused_by_event_id=caused_by_event_id,
                        created_monotonic_ms=350 + record_index * 10 + attempt_index,
                        created_wall_clock_ms=1700000000350 + record_index * 10 + attempt_index,
                        adapter_request_id=binding.adapter_request_id,
                        retry_count=attempt_index + 1,
                        retry_reason=exc.category,
                        timeout_ms=int(approval_packet["per_request_timeout_ms"]),
                    )
                    continue
                request_failed_count += 1
                status_buckets["request_failed"] += 1
                emit_lalm_thinker_request_failed(
                    boundary=boundary,
                    event_id=f"evt_lalm_thinker_live_eval_{case_slug}_request_failed",
                    caused_by_event_id=caused_by_event_id,
                    created_monotonic_ms=360 + record_index * 10 + attempt_index,
                    created_wall_clock_ms=1700000000360 + record_index * 10 + attempt_index,
                    adapter_request_id=binding.adapter_request_id,
                    failure_reason=exc.category,
                    retryable=False,
                    timeout_ms=int(approval_packet["per_request_timeout_ms"]),
                )
                case_completed = True
                break

            latency_buckets[_latency_bucket(time.monotonic() - start)] += 1
            if result.success and result.thinker_emission is not None:
                validated_count += 1
                status_buckets["validated"] += 1
                event = result.thinker_emission.thinker_event
                safe_refs.append(
                    {
                        "case_id": str(record["case_id"]),
                        "thinker_event_id": str(event["event_id"]),
                        "semantic_frame_ref": str(event["semantic_frame_ref"]),
                        "semantic_summary_ref": str(event["semantic_summary_ref"]),
                    }
                )
            else:
                validation_failed_count += 1
                status_buckets["validation_failed"] += 1
                failure_category_counts["validation_failed"] += 1
                if result.validation_failed_event is not None:
                    for reason in result.validation_failed_event.get("failure_reasons", ()):
                        validation_failure_category_counts[str(reason)] += 1
                    safe_refs.append(
                        {
                            "case_id": str(record["case_id"]),
                            "validation_failed_event_id": str(
                                result.validation_failed_event["event_id"]
                            ),
                        }
                    )
            case_completed = True
            break

        if not case_completed:
            request_failed_count += 1
            status_buckets["request_failed"] += 1

    output_file = f"{str(approval_packet['output_location']).rstrip('/')}/summary.json"
    return LALMThinkerSyntheticLiveEvalSummary(
        request_count=len(selected_records),
        validated_count=validated_count,
        validation_failed_count=validation_failed_count,
        request_failed_count=request_failed_count,
        retry_count=retry_count,
        timeout_count=timeout_count,
        failure_category_counts=_counter_items(failure_category_counts),
        retry_reason_counts=_counter_items(retry_reason_counts),
        validation_failure_category_counts=_counter_items(validation_failure_category_counts),
        latency_buckets=_counter_items(latency_buckets),
        status_buckets=_counter_items(status_buckets),
        safe_refs=tuple(safe_refs),
        output_location=str(approval_packet["output_location"]),
        output_file=output_file,
        cleanup_status=str(approval_packet["cleanup_policy"]),
        provider_model_alias=str(approval_packet["provider_model_alias"]),
        provider_model_alias_recheck_date=str(approval_packet["provider_model_alias_recheck_date"]),
        max_request_count=int(approval_packet["max_request_count"]),
        per_request_timeout_ms=int(approval_packet["per_request_timeout_ms"]),
        retry_limit=int(approval_packet["retry_limit"]),
    )


def _build_synthetic_live_eval_records(max_request_count: int) -> tuple[dict[str, str], ...]:
    count = max(1, min(max_request_count, 10))
    return tuple(
        {
            "case_id": f"synthetic_metadata_only_{index:03d}",
            "adapter_request_id": f"adapter-request-lalm-thinker-live-eval-{index:03d}",
            "input_ref": f"text://synthetic/lalm-thinker/live-eval/{index:03d}",
            "transient_input_text": f"turn on the synthetic desk lamp {index:03d}",
            "request_metadata_ref": (
                f"request-metadata://synthetic/lalm-thinker/live-eval/{index:03d}"
            ),
        }
        for index in range(1, count + 1)
    )


def _start_lalm_thinker_live_eval_session() -> object:
    journal = InMemoryEventJournal(
        session_id="sess_lalm_thinker_live_eval_synthetic",
        conversation_id="conv_lalm_thinker_live_eval_synthetic",
    )
    session_started = journal.append(
        event_name="SESSION_STARTED",
        event_id="evt_lalm_thinker_live_eval_session_started",
        source_module="session_runtime",
        created_monotonic_ms=100,
        created_wall_clock_ms=1700000000100,
        trace_redaction_level="metadata_only",
        runtime_config_ref="config://synthetic/lalm-thinker/live-eval",
        capability_snapshot_ref="capability://synthetic/lalm-thinker/live-eval",
    )
    journal.append(
        event_name="ADAPTER_CAPABILITY_SNAPSHOT_RECORDED",
        event_id="evt_lalm_thinker_live_eval_capability_snapshot",
        source_module="adapter_registry",
        caused_by_event_id=str(session_started["event_id"]),
        created_monotonic_ms=101,
        created_wall_clock_ms=1700000000101,
        trace_redaction_level="metadata_only",
        capability_snapshot_ref="capability://synthetic/lalm-thinker/live-eval",
        adapter_ids=(_LALM_THINKER_ADAPTER_ID,),
        adapter_types=("thinker",),
        deployment_modes=("remote_api",),
        output_modes=("real",),
    )
    return _LiveEvalStartup(journal=journal)


def _append_synthetic_committed_turn(
    journal: object,
    *,
    record: Mapping[str, Any],
    record_index: int,
) -> dict[str, object]:
    snapshot_event_id = str(journal.events()[1]["event_id"])
    prefix = f"evt_lalm_thinker_live_eval_{_safe_slug(str(record['case_id']))}"
    text_received = journal.append(
        event_name="TEXT_INPUT_RECEIVED",
        event_id=f"{prefix}_text_received",
        source_module="access_layer",
        caused_by_event_id=snapshot_event_id,
        created_monotonic_ms=110 + record_index,
        created_wall_clock_ms=1700000000110 + record_index,
        trace_redaction_level="metadata_only",
        input_span_id=f"input_lalm_thinker_live_eval_{record_index:03d}",
        text_span_id=f"text_lalm_thinker_live_eval_{record_index:03d}",
        input_modality="text",
        directedness="ASSUMED_DIRECTED",
        semantic_close="ASSUMED_CLOSED",
        text_ref=str(record["input_ref"]),
    )
    turn_opened = journal.append(
        event_name="TURN_OPENED",
        event_id=f"{prefix}_turn_opened",
        source_module="interaction_controller",
        caused_by_event_id=str(text_received["event_id"]),
        created_monotonic_ms=120 + record_index,
        created_wall_clock_ms=1700000000120 + record_index,
        trace_redaction_level="metadata_only",
        turn_id=f"turn_lalm_thinker_live_eval_{record_index:03d}",
        input_span_id=f"input_lalm_thinker_live_eval_{record_index:03d}",
        input_modality="text",
        turn_phase="COLLECTING_INPUT",
    )
    accepted = journal.append(
        event_name="TURN_INGRESS_ACCEPTED",
        event_id=f"{prefix}_ingress_accepted",
        source_module="interaction_controller",
        caused_by_event_id=str(turn_opened["event_id"]),
        created_monotonic_ms=130 + record_index,
        created_wall_clock_ms=1700000000130 + record_index,
        trace_redaction_level="metadata_only",
        turn_id=f"turn_lalm_thinker_live_eval_{record_index:03d}",
        input_span_id=f"input_lalm_thinker_live_eval_{record_index:03d}",
        ingress_outcome="ACCEPTED",
    )
    return journal.append(
        event_name="TURN_INGRESS_COMMITTED",
        event_id=f"{prefix}_ingress_committed",
        source_module="interaction_controller",
        caused_by_event_id=str(accepted["event_id"]),
        created_monotonic_ms=140 + record_index,
        created_wall_clock_ms=1700000000140 + record_index,
        trace_redaction_level="metadata_only",
        turn_id=f"turn_lalm_thinker_live_eval_{record_index:03d}",
        utterance_id=f"utt_lalm_thinker_live_eval_{record_index:03d}",
        input_span_id=f"input_lalm_thinker_live_eval_{record_index:03d}",
        text_span_id=f"text_lalm_thinker_live_eval_{record_index:03d}",
        input_modality="text",
        directedness="ASSUMED_DIRECTED",
        semantic_close="ASSUMED_CLOSED",
        ingress_outcome="COMMITTED",
    )


def _write_metadata_summary(
    *,
    repo_root: Path,
    output_location: str,
    metadata: Mapping[str, Any],
) -> Path:
    output_dir = repo_root / output_location
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "summary.json"
    output_file.write_text(
        json.dumps(dict(metadata), sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_file


def _latency_bucket(elapsed_seconds: float) -> str:
    elapsed_ms = max(0.0, elapsed_seconds * 1000)
    if elapsed_ms < 1000:
        return "lt_1s"
    if elapsed_ms < 5000:
        return "1s_to_5s"
    return "gte_5s"


def _counter_items(counter: Counter[str]) -> tuple[tuple[str, int], ...]:
    return tuple(sorted(counter.items()))


def _safe_slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-") or "unknown"
