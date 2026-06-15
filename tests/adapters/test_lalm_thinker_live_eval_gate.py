from __future__ import annotations

import http.client
import importlib
import json
import random
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

from voice_agent.adapters.lalm_thinker_live_eval_gate import (
    LALMThinkerLiveEvalApprovalError,
    LALM_THINKER_REQUIRED_LIVE_EVAL_APPROVAL_FIELDS,
    load_lalm_thinker_live_eval_approval,
    parse_lalm_thinker_live_eval_approval_text,
    validate_lalm_thinker_live_eval_approval,
)
from voice_agent.adapters.lalm_thinker_live_eval_entrypoint import (
    run_lalm_thinker_live_eval_entrypoint,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
COMMAND = REPO_ROOT / "scripts" / "lalm-thinker-live-eval"
MODULE_PATH = REPO_ROOT / "src" / "voice_agent" / "adapters" / "lalm_thinker_live_eval_gate.py"
APPROVAL_TEMPLATE = (
    REPO_ROOT / "docs" / "implementation" / "lalm-thinker-live-eval-approval-template.md"
)


def test_command_help_path_is_available_without_provider_sdk() -> None:
    result = subprocess.run(
        [str(COMMAND), "--help"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "provider-free" in result.stdout
    assert "approval" in result.stdout
    assert _module_has_no_provider_sdk_import()


def test_missing_approval_fails_closed() -> None:
    result = subprocess.run(
        [str(COMMAND), "--dry-run-gate-check"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    body = json.loads(result.stdout)
    assert body["success"] is False
    assert body["category"] == "missing_approval"
    assert body["provider_call_allowed"] is False
    assert body["live_eval_output_generated"] is False
    assert "api_key" not in result.stdout.lower()
    assert "token=" not in result.stdout.lower()


def test_malformed_approval_fails_closed(tmp_path: Path) -> None:
    approval = tmp_path / "approval.json"
    approval.write_text("{not-json", encoding="utf-8")

    with pytest.raises(LALMThinkerLiveEvalApprovalError) as captured:
        load_lalm_thinker_live_eval_approval(approval)

    assert captured.value.category == "malformed_approval"
    assert "{not-json" not in str(captured.value)


def test_incomplete_approval_fails_closed() -> None:
    packet = _valid_approval_packet()
    del packet["synthetic_input_set_ref"]

    with pytest.raises(LALMThinkerLiveEvalApprovalError) as captured:
        validate_lalm_thinker_live_eval_approval(packet)

    assert captured.value.category == "missing_required_field"
    assert captured.value.failure_ref.startswith("validation://synthetic/lalm-thinker/live-eval/")


def test_human_approved_false_fails_closed() -> None:
    packet = _valid_approval_packet()
    packet["human_approved"] = False

    with pytest.raises(LALMThinkerLiveEvalApprovalError) as captured:
        validate_lalm_thinker_live_eval_approval(packet)

    assert captured.value.category == "human_approval_required"


@pytest.mark.parametrize(
    "unsafe_output_location",
    (
        "docs/implementation/lalm-thinker-live-eval-output.json",
        "../outputs/lalm-thinker/live-eval",
        "/tmp/lalm-thinker-live-eval",
        "audio/raw/lalm-thinker/live-eval",
        "outputs/other-adapter/live-eval",
    ),
)
def test_output_location_safety_rejects_unsafe_or_non_ignored_paths(
    unsafe_output_location: str,
) -> None:
    packet = _valid_approval_packet()
    packet["output_location"] = unsafe_output_location

    with pytest.raises(LALMThinkerLiveEvalApprovalError) as captured:
        validate_lalm_thinker_live_eval_approval(packet)

    assert captured.value.category == "unsafe_output_location"
    assert unsafe_output_location not in str(captured.value)


def test_approval_containing_credential_like_values_fails_without_echoing_secret() -> None:
    packet = _valid_approval_packet()
    packet["redaction_non_retention_policy"] = "metadata only; token=synthetic-secret"

    with pytest.raises(LALMThinkerLiveEvalApprovalError) as captured:
        validate_lalm_thinker_live_eval_approval(packet)

    assert captured.value.category == "credential_like_content"
    assert "synthetic-secret" not in str(captured.value)
    assert "token=" not in str(captured.value)


def test_valid_synthetic_metadata_only_approval_passes_gate_but_does_not_run_eval(
    tmp_path: Path,
) -> None:
    approval = tmp_path / "approval.json"
    approval.write_text(json.dumps(_valid_approval_packet()), encoding="utf-8")

    result = subprocess.run(
        [
            str(COMMAND),
            "--approval",
            str(approval),
            "--dry-run-gate-check",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    body = json.loads(result.stdout)
    assert body == {
        "success": True,
        "gate_check": {
            "approval_packet_complete": True,
            "allowed_outputs": ["gate_status_metadata_only"],
            "dry_run_only": True,
            "human_approved": True,
            "live_eval_output_generated": False,
            "output_location_safe": True,
            "provider_call_allowed": False,
            "secret_read_allowed": False,
            "synthetic_input_set_only": True,
        },
    }
    assert not list(tmp_path.glob("*.out"))


def test_gate_check_does_not_use_network_clock_random_or_provider_side_channels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocked_calls = _block_runtime_side_channels(monkeypatch)
    metadata = validate_lalm_thinker_live_eval_approval(_valid_approval_packet()).to_dict()

    assert blocked_calls == []
    assert metadata["provider_call_allowed"] is False
    assert metadata["secret_read_allowed"] is False
    assert metadata["live_eval_output_generated"] is False


def test_live_eval_runner_fails_closed_without_credential_value(tmp_path: Path) -> None:
    approval = tmp_path / "approval.json"
    approval.write_text(json.dumps(_valid_live_approval_packet()), encoding="utf-8")

    with pytest.raises(LALMThinkerLiveEvalApprovalError) as captured:
        run_lalm_thinker_live_eval_entrypoint(
            approval_path=approval,
            env={},
            transport=_SequenceTransport(("unused",)),
            repo_root=tmp_path,
        )

    assert captured.value.category == "credential_missing"


def test_live_eval_runner_with_fake_transport_writes_metadata_summary_only(
    tmp_path: Path,
) -> None:
    approval = tmp_path / "approval.json"
    approval.write_text(json.dumps(_valid_live_approval_packet(max_request_count=2)), encoding="utf-8")
    transport = _SequenceTransport(("valid", "invalid"))

    metadata = run_lalm_thinker_live_eval_entrypoint(
        approval_path=approval,
        env={"DASHSCOPE_API_KEY": "runtime-secret-value-for-test-only"},
        transport=transport,
        repo_root=tmp_path,
    )

    assert metadata["request_count"] == 2
    assert metadata["validated_count"] == 1
    assert metadata["validation_failed_count"] == 1
    assert metadata["request_failed_count"] == 0
    assert metadata["retry_count"] == 0
    assert metadata["provider_model_alias"] == "qwen3.5-omni-plus"
    assert metadata["provider_model_alias_recheck_date"] == "2026-06-15"
    assert metadata["credential_source"] == (
        "runtime_env_var:DASHSCOPE_API_KEY via ~/.voice-agent-secrets/dashscope.env"
    )
    assert metadata["raw_provider_request_included"] is False
    assert metadata["raw_provider_response_included"] is False
    assert metadata["secret_included"] is False
    assert metadata["raw_audio_included"] is False
    assert metadata["raw_trace_included"] is False
    assert metadata["real_user_input_included"] is False
    assert metadata["authorization_header_included"] is False
    assert metadata["bearer_token_included"] is False
    assert metadata["full_prompt_included"] is False
    assert metadata["safe_refs"]
    summary_path = tmp_path / "outputs/lalm-thinker/live-eval/metadata-only/summary.json"
    assert summary_path.exists()
    persisted = json.loads(summary_path.read_text(encoding="utf-8"))
    assert persisted == metadata

    rendered = repr(metadata)
    assert "runtime-secret-value-for-test-only" not in rendered
    assert "Bearer " not in rendered
    assert "provider_text" not in rendered
    assert "raw_provider_body" not in rendered
    assert transport.call_count == 2


def test_live_eval_runner_retries_timeout_once_and_records_safe_failure_metadata(
    tmp_path: Path,
) -> None:
    approval = tmp_path / "approval.json"
    approval.write_text(json.dumps(_valid_live_approval_packet(max_request_count=1)), encoding="utf-8")
    transport = _SequenceTransport(("timeout", "valid"))

    metadata = run_lalm_thinker_live_eval_entrypoint(
        approval_path=approval,
        env={"DASHSCOPE_API_KEY": "runtime-secret-value-for-test-only"},
        transport=transport,
        repo_root=tmp_path,
    )

    assert metadata["request_count"] == 1
    assert metadata["validated_count"] == 1
    assert metadata["request_failed_count"] == 0
    assert metadata["retry_count"] == 1
    assert metadata["timeout_count"] == 1
    assert metadata["retry_reason_counts"] == {"provider_timeout": 1}
    assert "runtime-secret-value-for-test-only" not in repr(metadata)


def test_command_module_has_no_provider_sdk_import() -> None:
    module = importlib.import_module("voice_agent.adapters.lalm_thinker_live_eval_gate")

    assert module.__name__ == "voice_agent.adapters.lalm_thinker_live_eval_gate"
    assert _module_has_no_provider_sdk_import()


def test_markdown_approval_parser_supports_template_style_fields() -> None:
    packet = parse_lalm_thinker_live_eval_approval_text(
        "\n".join(f"- {key}: {value}" for key, value in _valid_approval_packet().items())
    )

    assert set(LALM_THINKER_REQUIRED_LIVE_EVAL_APPROVAL_FIELDS) <= set(packet)
    assert packet["human_approved"] is True
    assert packet["synthetic_input_set_only"] is True
    assert packet["max_request_count"] == 3


def test_approval_template_documents_required_sections_and_forbidden_artifacts() -> None:
    text = APPROVAL_TEMPLATE.read_text(encoding="utf-8")
    normalized = text.lower()

    for section in (
        "## purpose",
        "## non-goals",
        "## required approval fields",
        "## provider/model alias and recheck date",
        "## synthetic input set only",
        "## cost/quota/time budget",
        "## timeout/retry limits",
        "## output location and cleanup policy",
        "## redaction / non-retention policy",
        "## forbidden artifacts",
        "## allowed outputs",
        "## fail-closed behavior",
        "## human approval checklist",
        "## template approval status",
    ):
        assert section in normalized

    for forbidden in (
        "raw provider request / response body retention",
        "full prompt dump retention",
        "raw audio",
        "raw trace",
        "local replay cache committed",
        "secrets/tokens/cookies/credentials",
        "unredacted real user input",
        "provider-native tool execution",
        "canonical event changes",
        "production traffic",
    ):
        assert forbidden in normalized

    assert "this template does not approve live eval by itself" in normalized
    assert "- human_approved: false" in text


def _valid_approval_packet() -> dict[str, object]:
    return {
        "approval_packet_schema": "voice_agent.lalm_thinker.live_eval_approval.v1",
        "human_approved": True,
        "provider_model_alias": "synthetic-lalm-thinker-model-alias",
        "provider_model_alias_recheck_date": "2026-06-15",
        "synthetic_input_set_ref": "synthetic-input-set://lalm-thinker/metadata-only-v1",
        "synthetic_input_set_only": True,
        "cost_quota_time_budget": "synthetic minimal budget approved for gate test",
        "max_request_count": 3,
        "per_request_timeout_ms": 30000,
        "retry_limit": 1,
        "output_location": "outputs/lalm-thinker/live-eval/metadata-only",
        "output_location_policy": "local_only_ignored",
        "cleanup_policy": "delete local outputs after metadata summary review",
        "redaction_non_retention_policy": "metadata only and no raw provider bodies retained",
        "forbidden_artifacts_acknowledged": True,
        "allowed_outputs": ["gate_status_metadata_only"],
        "fail_closed_behavior": "block without complete human approval packet",
        "provider_native_tool_execution_allowed": False,
        "canonical_event_changes_allowed": False,
        "production_traffic_allowed": False,
    }


def _valid_live_approval_packet(*, max_request_count: int = 1) -> dict[str, object]:
    packet = _valid_approval_packet()
    packet.update(
        {
            "provider_model_alias": "qwen3.5-omni-plus",
            "provider_model_alias_recheck_date": "2026-06-15",
            "cost_quota_time_budget": "Goal D approved budget: max 10 synthetic metadata-only requests",
            "max_request_count": max_request_count,
            "per_request_timeout_ms": 60000,
            "retry_limit": 1,
            "allowed_outputs": ["metadata_summary_only"],
        }
    )
    return packet


class _SequenceTransport:
    def __init__(self, outcomes: tuple[str, ...]) -> None:
        self._outcomes = list(outcomes)
        self.call_count = 0

    def complete(
        self,
        *,
        request_payload: object,
        credential_handle: object,
        credential_value: str,
        adapter_request_id: str,
        timeout_ms: int,
        model_alias: str,
    ) -> str:
        from voice_agent.adapters.lalm_thinker_live_transport import (
            LALMThinkerLiveTransportError,
        )

        self.call_count += 1
        assert credential_value == "runtime-secret-value-for-test-only"
        assert timeout_ms == 60000
        assert model_alias == "qwen3.5-omni-plus"
        assert adapter_request_id
        assert "runtime-secret-value-for-test-only" not in repr(credential_handle)
        outcome = self._outcomes.pop(0)
        if outcome == "timeout":
            raise LALMThinkerLiveTransportError(
                "provider timeout",
                category="provider_timeout",
                failure_reasons=("provider_timeout",),
            )
        if outcome == "invalid":
            return "not json"
        assert isinstance(request_payload, dict)
        skeleton = request_payload["required_output_skeleton"]
        return json.dumps(
            {
                **skeleton,
                "output_mode": "real",
                "semantic_frame_hint": {
                    "status": "available",
                    "label": "semantic_frame_available",
                },
                "semantic_summary_hint": {
                    "status": "available",
                    "label": "semantic_summary_available",
                },
                "optional_evidence_refs": {
                    "semantic_close": {
                        "status": "available",
                        "label": "closed",
                    },
                    "assistant_directedness": {
                        "status": "available",
                        "label": "directed",
                    },
                    "emotion": {
                        "status": "available",
                        "label": "calm",
                    },
                    "audio_caption": {
                        "status": "available",
                        "label": "caption_available",
                    },
                },
                "task_focus_hint": {
                    "task_like": True,
                    "complexity_hint": "complex",
                    "focus_confidence": 0.75,
                    "evidence_uncertainty": "low",
                },
            },
            sort_keys=True,
        )


def _block_runtime_side_channels(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    blocked_calls: list[object] = []

    def fail_if_called(*args: object, **kwargs: object) -> None:
        blocked_calls.append((args, kwargs))
        raise AssertionError("LALM Thinker live eval gate must remain provider-free")

    monkeypatch.setattr(socket, "create_connection", fail_if_called)
    monkeypatch.setattr(http.client.HTTPConnection, "connect", fail_if_called)
    monkeypatch.setattr(http.client.HTTPSConnection, "connect", fail_if_called)
    monkeypatch.setattr(urllib.request, "urlopen", fail_if_called)
    monkeypatch.setattr(time, "time", fail_if_called)
    monkeypatch.setattr(time, "monotonic", fail_if_called)
    monkeypatch.setattr(random, "random", fail_if_called)
    return blocked_calls


def _module_has_no_provider_sdk_import() -> bool:
    source = MODULE_PATH.read_text(encoding="utf-8")
    forbidden_imports = (
        "openai",
        "dashscope",
        "anthropic",
        "google.generativeai",
        "qwen",
        "requests",
        "httpx",
        "urllib.request",
        "http.client",
        "socket",
    )
    return all(forbidden not in source for forbidden in forbidden_imports)
