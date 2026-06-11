from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping
from pathlib import Path
import time
from typing import Any

from voice_agent.adapters.qwen_slow_llm_live_transport import (
    QwenSlowLLMLiveDirectHTTPTransport,
)
from voice_agent.adapters.qwen_slow_llm_skeleton import (
    QwenSlowLLMAdapterSkeletonError,
    QwenSlowLLMCredentialHandle,
    QwenSlowLLMRequestBinding,
    load_qwen_slow_llm_synthetic_live_eval_inputs,
    run_qwen_slow_llm_synthetic_live_eval,
)
from voice_agent.adapters.slow_llm_contract import SlowLLMStructuredOutputContract
from voice_agent.events.journal import InMemoryEventJournal
from voice_agent.runtime.adapter_callback_boundary import AdapterCallbackAppendBoundary


QWEN_SLOW_LLM_LIVE_EVAL_DEFAULT_APPROVAL_PACKET_PATH = Path(
    "docs/implementation/qwen-slow-llm-live-provider-eval-approval-packet.md"
)
QWEN_SLOW_LLM_LIVE_EVAL_DEFAULT_INPUT_PATH = Path(
    "tests/fixtures/synthetic/qwen-slow-llm-inputs.jsonl"
)
_QWEN_SLOW_LLM_CREDENTIAL_ENV_VAR = "DASHSCOPE_API_KEY"


def parse_qwen_slow_llm_approval_packet_markdown(text: str) -> dict[str, object]:
    if not isinstance(text, str) or text == "":
        raise QwenSlowLLMAdapterSkeletonError("approval packet text must be non-empty")

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
        elif value.isdigit():
            fields[key] = int(value)
        else:
            fields[key] = value
    return fields


def run_qwen_slow_llm_live_eval_entrypoint(
    *,
    approval_packet_path: str | Path = QWEN_SLOW_LLM_LIVE_EVAL_DEFAULT_APPROVAL_PACKET_PATH,
    input_path: str | Path = QWEN_SLOW_LLM_LIVE_EVAL_DEFAULT_INPUT_PATH,
    env: Mapping[str, str] | None = None,
    transport: object | None = None,
) -> dict[str, Any]:
    approval_packet = parse_qwen_slow_llm_approval_packet_markdown(
        Path(approval_packet_path).read_text(encoding="utf-8")
    )
    input_records = load_qwen_slow_llm_synthetic_live_eval_inputs(input_path)
    runtime_env = os.environ if env is None else env
    credential_value = runtime_env.get(_QWEN_SLOW_LLM_CREDENTIAL_ENV_VAR)

    journal, slowtask_event = _build_entrypoint_journal()
    boundary = AdapterCallbackAppendBoundary(journal)
    contract = SlowLLMStructuredOutputContract(
        boundary=boundary,
        adapter_id="slow_llm_qwen_mvp3_skeleton",
        output_mode="real",
    )
    binding = QwenSlowLLMRequestBinding(
        task_id="task_qwen_slow_llm_live_eval_synthetic",
        plan_version=1,
        observed_plan_version=1,
        interpreted_against_plan_version=1,
        task_event_seq=1,
        adapter_request_id="adapter-request-qwen-slow-llm-live-eval",
        causal_refs=(f"event:{slowtask_event['event_id']}",),
    )
    now_wall_ms = int(time.time() * 1000)
    now_monotonic_ms = int(time.monotonic() * 1000)

    summary = run_qwen_slow_llm_synthetic_live_eval(
        approval_packet=approval_packet,
        input_records=input_records,
        transport=transport if transport is not None else QwenSlowLLMLiveDirectHTTPTransport(),
        credential_handle=QwenSlowLLMCredentialHandle(
            credential_ref="secret-ref://local/qwen-slow-llm/synthetic",
        ),
        credential_value=credential_value,
        contract=contract,
        boundary=boundary,
        slowtask_event=slowtask_event,
        binding=binding,
        created_monotonic_ms=now_monotonic_ms,
        created_wall_clock_ms=now_wall_ms,
    )
    return summary.to_metadata()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the approval-gated synthetic Qwen Slow LLM live eval."
    )
    parser.add_argument(
        "--approval-packet",
        default=str(QWEN_SLOW_LLM_LIVE_EVAL_DEFAULT_APPROVAL_PACKET_PATH),
    )
    parser.add_argument(
        "--input",
        default=str(QWEN_SLOW_LLM_LIVE_EVAL_DEFAULT_INPUT_PATH),
    )
    args = parser.parse_args(argv)

    try:
        metadata = run_qwen_slow_llm_live_eval_entrypoint(
            approval_packet_path=Path(args.approval_packet),
            input_path=Path(args.input),
            env=os.environ,
        )
    except QwenSlowLLMAdapterSkeletonError as exc:
        print(
            json.dumps(
                {
                    "success": False,
                    "failure_reasons": exc.failure_reasons,
                    "raw_provider_body_included": False,
                    "secret_included": False,
                },
                sort_keys=True,
            )
        )
        return 2

    print(json.dumps({"success": True, "summary": metadata}, sort_keys=True))
    return 0


def _build_entrypoint_journal() -> tuple[InMemoryEventJournal, dict[str, object]]:
    journal = InMemoryEventJournal(
        session_id="sess_qwen_slow_llm_live_eval_synthetic",
        conversation_id="conv_qwen_slow_llm_live_eval_synthetic",
    )
    session_started = journal.append(
        event_name="SESSION_STARTED",
        event_id="evt_qwen_slow_llm_live_eval_session_started",
        source_module="session_runtime",
        created_monotonic_ms=1,
        created_wall_clock_ms=1700000000001,
        trace_redaction_level="metadata_only",
        runtime_config_ref="config://synthetic/qwen-slow-llm/live-eval",
        capability_snapshot_ref="capability://synthetic/qwen-slow-llm/live-eval",
    )
    slowtask_event = journal.append(
        event_name="EVIDENCE_REVIEWED",
        event_id="evt_qwen_slow_llm_live_eval_evidence_reviewed",
        source_module="slowtask_runtime",
        caused_by_event_id=str(session_started["event_id"]),
        created_monotonic_ms=2,
        created_wall_clock_ms=1700000000002,
        trace_redaction_level="metadata_only",
        task_id="task_qwen_slow_llm_live_eval_synthetic",
        plan_version=1,
        task_event_seq=1,
        evidence_refs=("evidence://synthetic/qwen-slow-llm/live-eval/reviewed",),
        review_result="synthetic_live_eval_ready",
    )
    return journal, slowtask_event


if __name__ == "__main__":
    raise SystemExit(main())
