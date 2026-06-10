from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import unquote

from voice_agent.privacy.redaction import SECRET_VALUE_PATTERN, is_safe_authorization_ref
from voice_agent.replay.runner import ReplayResult, run_replay_fixture


class MVP0AcceptanceError(AssertionError):
    pass


class MVP1AcceptanceError(AssertionError):
    pass


class MVP2AcceptanceError(AssertionError):
    pass


class MVP3AcceptanceError(AssertionError):
    pass


MVP0_REQUIRED_SCENARIOS = (
    "MVP0-TEXT-INGRESS-001",
    "MVP0-AUDIO-INGRESS-001",
    "MVP0-BARGE-IN-TRUNCATE-001",
    "MVP0-MOCK-ADAPTER-CAPABILITY-001",
    "MVP0-LOCAL-TRACE-SAFETY-001",
)
MVP0_OUTPUT_MODES = frozenset({"mock", "degraded", "fallback", "real"})
MVP1_REQUIRED_SCENARIOS = (
    "MVP1-SPAWN-SLOWTASK-001",
    "MVP1-ACTIVE-PATCH-001",
    "MVP1-PLAN-ADVANCE-001",
    "MVP1-FOREGROUND-CHAT-001",
    "MVP1-AMBIGUOUS-NO-PATCH-001",
    "MVP1-WAITING-SLOT-001",
    "MVP1-STALE-RESULT-001",
    "MVP1-STALE-ADOPTED-001",
    "MVP1-CANCEL-001",
    "MVP1-SWITCH-TASK-001",
    "MVP1-FAILED-001",
    "MVP1-SEMANTIC-COMMITMENT-001",
)
MVP1_OUTPUT_MODES = frozenset({"mock", "degraded", "fallback"})
MVP2_REQUIRED_SCENARIOS = (
    "MVP2-TOOL-MANIFEST-001",
    "MVP2-TOOL-ARGS-PARTIAL-001",
    "MVP2-TOOL-BLOCKED-INSUFFICIENT-ARGS-001",
    "MVP2-MEMO-SANDBOX-WRITE-001",
    "MVP2-ALARM-SANDBOX-SCHEDULE-001",
    "MVP2-FLASHLIGHT-DEMO-DEVICE-ACTION-001",
    "MVP2-WEATHER-READ-ONLY-001",
    "MVP2-WEBSEARCH-UNTRUSTED-EVIDENCE-001",
    "MVP2-UI-STATE-PATCHED-001",
    "MVP2-DEMO-DESTRUCTIVE-CONFIRMATION-001",
    "MVP2-STALE-TOOL-RESULT-PROGRESSIVE-001",
    "MVP2-COMPOSER-SPOKEN-PLAN-001",
    "MVP2-COMMITMENT-COVERAGE-001",
    "MVP2-PROGRESS-TRUTHFULNESS-001",
    "MVP2-ACCEPTANCE-SCOPE-SAFETY-001",
)
MVP2_OUTPUT_MODES = frozenset({"mock", "degraded", "fallback"})
MVP3_REQUIRED_SCENARIOS = (
    "MVP3-FIXTURE-SAFETY-001",
    "MVP3-ADAPTER-PROFILE-001",
    "MVP3-ADAPTER-EVENT-HARNESS-001",
    "MVP3-RUNTIME-ASSEMBLY-001",
    "MVP3-ASR-CONTRACT-001",
    "MVP3-THINKER-CONTRACT-001",
    "MVP3-SLOW-LLM-STRUCTURED-001",
    "MVP3-TTS-CONTRACT-001",
    "MVP3-FALLBACK-DEGRADED-REPLAY-001",
    "MVP3-ACCEPTANCE-SCOPE-SAFETY-001",
)
MVP3_OUTPUT_MODES = frozenset({"real", "fallback", "degraded"})
MVP3_ALL_OUTPUT_MODES = frozenset({"real", "mock", "fallback", "degraded"})
MVP3_REQUIRED_REPLAY_PROPERTIES = frozenset(
    {
        "deterministic_replay_does_not_rerun_models_tools_network_clock_or_random",
        "mvp3_slice0_contains_no_provider_execution",
        "mvp3_fixtures_are_synthetic_redacted_minimal",
        "mock_real_fallback_degraded_modes_must_be_explicit",
        "adapter_health_digest_distinguishes_output_modes_failure_retry_missing_capabilities_degradation",
        "fallback_degraded_replay_uses_recorded_refs_only",
        "all_mvp3_scenario_ids_are_manifest_mapped",
    }
)
MVP3_REQUIRED_FORBIDDEN_BEHAVIORS = frozenset(
    {
        "provider_sdk_dependency",
        "provider_network_probe",
        "direct_external_model_call",
        "real_external_tool_side_effect",
        "raw_audio_fixture",
        "raw_trace_fixture",
        "secret_or_credential_fixture",
        "unredacted_real_user_input",
        "replay_calls_provider",
        "new_architecture_capability",
        "missing_output_mode_label",
        "weakened_replay_properties",
        "scope_broadening",
        "raw_local_debug_artifact_ref",
    }
)
MVP3_ADAPTER_OUTPUT_EVENT_NAMES = frozenset(
    {
        "ASR_TRANSCRIPT_OUTPUT_EMITTED",
        "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED",
        "SLOW_LLM_STRUCTURED_OUTPUT_EMITTED",
        "TTS_SYNTHESIS_OUTPUT_EMITTED",
    }
)
MVP3_ADAPTER_OUTPUT_MODE_REQUIRED_EVENT_NAMES = MVP3_ADAPTER_OUTPUT_EVENT_NAMES | frozenset(
    {
        "ADAPTER_HEALTHCHECK_FAILED",
        "ADAPTER_REQUEST_FAILED",
        "ADAPTER_OUTPUT_VALIDATION_FAILED",
        "ADAPTER_OUTPUT_DEGRADED",
    }
)
MVP3_FORBIDDEN_SOURCE_MODULES = frozenset(
    {
        "provider_sdk",
        "provider_client",
        "provider_http_client",
        "provider_websocket_client",
        "startup_healthcheck_probe",
        "network_probe",
        "real_external_tool_adapter",
        "external_write_adapter",
        "external_communication_adapter",
        "booking_or_payment_adapter",
        "real_device_adapter",
        "direct_frontend_mutator",
        "model_text_ui_driver",
    }
)
MVP3_FORBIDDEN_EVENT_NAMES = frozenset(
    {
        "PROVIDER_REQUEST_STARTED",
        "PROVIDER_REQUEST_COMPLETED",
        "PROVIDER_HEALTHCHECK_STARTED",
        "PROVIDER_HEALTHCHECK_COMPLETED",
        "EXTERNAL_MODEL_CALL_STARTED",
        "EXTERNAL_TOOL_SIDE_EFFECT_COMMITTED",
        "SLOWTASK_PAUSED",
        "SLOWTASK_RESUMED",
        "MULTI_SLOWTASK_ACTIVATED",
    }
)
MVP3_FORBIDDEN_SCOPE_MARKERS = (
    "multi active slowtask",
    "multi-active slowtask",
    "pause/resume",
    "real external side effect",
    "production privacy",
    "provider call during replay",
    "startup network healthcheck",
)
MVP3_DIRECT_PROVIDER_MARKERS = (
    "http://",
    "https://",
    "ws://",
    "wss://",
    "socket://",
    "sdk://",
    "provider-call://",
    "provider://live",
    "healthcheck://",
    "api.openai.com",
    "api.anthropic.com",
    "api.groq.com",
    "api.deepseek.com",
)
MVP3_FORBIDDEN_FIXTURE_KEY_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"(^|[_-])audio[_-]?(bytes|data|payload)$",
        r"(^|[_-])raw[_-]?(audio|trace|transcript|web)([_-]?(bytes|data|payload|ref))?$",
        r"(^|[_-])provider[_-]?(payload|response|request|request[_-]?body|headers?|schema|raw[_-]?output)$",
        r"(^|[_-])provider[_-].*(payload|response|request|headers?|schema|tool[_-]?calls|raw[_-]?output)$",
        r"(^|[_-])(request|response)[_-]?(body|payload)$",
    )
)
MVP2_REQUIRED_REPLAY_PROPERTIES = frozenset(
    {
        "deterministic_replay_does_not_rerun_models_tools_network_clock_or_random",
        "tool_ui_state_reconstructed_from_tool_ui_state_patched_events",
        "websearch_content_replayed_as_untrusted_evidence_only",
        "demo_destructive_action_requires_current_plan_confirmation",
        "composer_output_requires_coverage_or_truthfulness_check_before_playback",
        "old_plan_tool_result_requires_stale_evidence_chain_before_current_plan_use",
    }
)
MVP2_TOOL_EXECUTOR_OWNED_EVENT_NAMES = frozenset(
    {
        "TOOL_CALL_STARTED",
        "TOOL_MANIFEST_LOADED",
        "TOOL_ARGUMENTS_PARTIAL",
        "TOOL_ARGUMENTS_READY",
        "TOOL_PREVIEW_AVAILABLE",
        "TOOL_EXECUTION_AUTHORIZED",
        "TOOL_EXECUTION_STARTED",
        "TOOL_PROGRESS_UPDATED",
        "TOOL_UI_STATE_PATCHED",
        "TOOL_RESULT_RECEIVED",
        "TOOL_EXECUTION_FAILED",
        "TOOL_CALL_RETRYING",
        "TOOL_EXECUTION_CANCELLED",
        "TOOL_EXECUTION_BLOCKED_INSUFFICIENT_ARGUMENTS",
    }
)
MVP2_ALLOWED_SIDE_EFFECT_CLASSES_BY_TOOL = {
    "memo": frozenset({"READ_ONLY", "SANDBOX_WRITE", "DEMO_DESTRUCTIVE_ACTION"}),
    "alarm": frozenset({"READ_ONLY", "SANDBOX_WRITE", "DEMO_DESTRUCTIVE_ACTION"}),
    "flashlight": frozenset({"SANDBOX_WRITE"}),
    "weather": frozenset({"READ_ONLY"}),
    "webSearch": frozenset({"READ_ONLY"}),
}
MVP2_GLOBAL_ALLOWED_SIDE_EFFECT_CLASSES = frozenset(
    {"READ_ONLY", "DRY_RUN", "SANDBOX_WRITE", "DEMO_DESTRUCTIVE_ACTION"}
)
MVP2_REQUIRED_FORBIDDEN_BEHAVIORS = frozenset(
    {
        "real_external_write",
        "real_external_communication",
        "booking_or_payment",
        "real_deletion",
        "real_device_control",
        "account_or_identity_mutation",
        "credential_mutation",
        "direct_frontend_mutation_by_model_text",
        "websearch_as_instruction",
        "websearch_direct_backend_action",
        "composer_fact_rewrite",
        "tool_executor_direct_slowtask_mutation",
        "raw_text_confirmation_shortcut",
        "fake_tool_cancellation_success",
        "real_model_adapter_runtime_integration",
    }
)
MVP2_REQUIRED_FORBIDDEN_SOURCE_MODULES = frozenset(
    {
        "direct_frontend_mutator",
        "model_text_ui_driver",
        "real_external_tool_adapter",
        "external_write_adapter",
        "external_communication_adapter",
        "booking_or_payment_adapter",
        "real_device_adapter",
        "real_model_adapter",
        "web_search_instruction_adapter",
    }
)
MVP2_REQUIRED_TOOL_SCOPE = {
    "memo": {
        "tool_category": "DEMO_STATE_WRITE",
        "result_trust_level": "TRUSTED_DEMO_TOOL_RESULT",
    },
    "alarm": {
        "tool_category": "DEMO_SCHEDULE_ACTION",
        "result_trust_level": "TRUSTED_DEMO_TOOL_RESULT",
    },
    "flashlight": {
        "tool_category": "DEMO_DEVICE_ACTION",
        "result_trust_level": "TRUSTED_DEMO_TOOL_RESULT",
    },
    "weather": {
        "tool_category": "READ_ONLY_EXTERNAL",
        "result_trust_level": "EXTERNAL_READ_PROVIDER_RESULT",
    },
    "webSearch": {
        "tool_category": "EXTERNAL_READ_UNTRUSTED",
        "result_trust_level": "UNTRUSTED_WEB_EVIDENCE",
    },
}
MVP2_REQUIRED_STATE_DIGEST_FIELDS = frozenset(
    {
        "tool_execution_state_hash",
        "demo_ui_state_hash",
        "spoken_plan_state_hash",
        "spoken_plan_check_state_hash",
        "playback_state_hash",
        "trace_privacy_state_hash",
        "overall_digest",
    }
)
MVP2_ALLOWED_SAFE_SECRET_METADATA_KEYS = frozenset(
    {
        "authorization_basis",
        "authorization_event_id",
        "secret_kind",
    }
)
DEFAULT_FORBIDDEN_EVENT_NAMES = frozenset(
    {
        "SLOWTASK_CREATED",
        "SLOWTASK_STATE_CHANGED",
        "USER_PATCH_RECEIVED",
        "USER_PATCH_INTERPRETED",
        "PLAN_VERSION_ADVANCED",
        "TASK_REPLANNED",
        "PLANNING_STARTED",
        "PLANNING_RESTARTED",
        "WAITING_FOR_SLOT",
        "WAITING_FOR_TOOL",
        "WAITING_FOR_USER_CONFIRMATION",
        "TOOL_CALL_STARTED",
        "TOOL_MANIFEST_LOADED",
        "TOOL_ARGUMENTS_PARTIAL",
        "TOOL_ARGUMENTS_READY",
        "TOOL_PREVIEW_AVAILABLE",
        "TOOL_EXECUTION_AUTHORIZED",
        "TOOL_EXECUTION_STARTED",
        "WAITING_FOR_TOOL",
        "TOOL_PROGRESS_UPDATED",
        "TOOL_UI_STATE_PATCHED",
        "TOOL_EXECUTION_FAILED",
        "TOOL_CALL_RETRYING",
        "TOOL_EXECUTION_CANCEL_REQUESTED",
        "TOOL_EXECUTION_CANCELLED",
        "TOOL_EXECUTION_BLOCKED_INSUFFICIENT_ARGUMENTS",
        "TOOL_RESULT_RECEIVED",
        "TOOL_RESULT_MARKED_STALE",
        "STALE_EVIDENCE_RECORDED",
        "STALE_EVIDENCE_ADOPTED",
        "SEMANTIC_COMMITMENT_EMITTED",
        "SPOKEN_PLAN_EMITTED",
        "COMMITMENT_COVERAGE_CHECK_PASSED",
        "COMMITMENT_COVERAGE_CHECK_FAILED",
        "PROGRESS_TRUTHFULNESS_CHECK_PASSED",
        "PROGRESS_TRUTHFULNESS_CHECK_FAILED",
    }
)
MVP1_FORBIDDEN_EVENT_NAMES = frozenset(
    {
        "TOOL_MANIFEST_LOADED",
        "TOOL_ARGUMENTS_PARTIAL",
        "TOOL_ARGUMENTS_READY",
        "TOOL_PREVIEW_AVAILABLE",
        "TOOL_EXECUTION_AUTHORIZED",
        "TOOL_EXECUTION_STARTED",
        "WAITING_FOR_TOOL",
        "TOOL_PROGRESS_UPDATED",
        "TOOL_UI_STATE_PATCHED",
        "TOOL_EXECUTION_FAILED",
        "TOOL_CALL_RETRYING",
        "TOOL_EXECUTION_CANCEL_REQUESTED",
        "TOOL_EXECUTION_CANCELLED",
        "TOOL_EXECUTION_BLOCKED_INSUFFICIENT_ARGUMENTS",
        "SPOKEN_PLAN_EMITTED",
        "COMMITMENT_COVERAGE_CHECK_PASSED",
        "COMMITMENT_COVERAGE_CHECK_FAILED",
        "PROGRESS_TRUTHFULNESS_CHECK_PASSED",
        "PROGRESS_TRUTHFULNESS_CHECK_FAILED",
        "SEMANTIC_COMMITMENT_CREATED",
        "STALE_TOOL_RESULT_RECORDED",
        "SPOKEN_PLAN_CREATED",
    }
)
DEFAULT_FORBIDDEN_SOURCE_MODULES = frozenset(
    {
        "slowtask_runtime",
        "user_patch_pipeline",
        "tool_executor",
        "demo_tool_executor",
        "composer",
        "coverage_checker",
        "truthfulness_checker",
        "frontend",
        "web_search",
    }
)
MVP1_FORBIDDEN_SOURCE_MODULES = frozenset(
    {
        "tool_executor",
        "demo_tool_executor",
        "composer",
        "coverage_checker",
        "truthfulness_checker",
        "frontend",
        "web_search",
        "real_tool_executor",
        "external_tool_adapter",
    }
)
MVP1_TOOL_MARKER_EVENT_NAMES = frozenset({"TOOL_CALL_STARTED", "TOOL_RESULT_RECEIVED"})
MVP1_REQUIRED_SOURCE_MODULES = {
    "TASK_FOCUS_STATE_UPDATED": "router",
    "SLOWTASK_CREATED": "slowtask_runtime",
    "SLOWTASK_STATE_CHANGED": "slowtask_runtime",
    "USER_PATCH_RECEIVED": "user_patch_pipeline",
    "USER_PATCH_INTERPRETED": "slowtask_runtime",
    "PLAN_VERSION_ADVANCED": "slowtask_runtime",
    "TASK_REPLANNED": "slowtask_runtime",
    "EVIDENCE_REVIEWED": "slowtask_runtime",
    "AMBIGUITY_DETECTED": "slowtask_runtime",
    "AMBIGUITY_RESOLVED": "slowtask_runtime",
    "CLARIFICATION_REQUESTED": "slowtask_runtime",
    "ARGUMENTS_RESOLVED": "slowtask_runtime",
    "ARGUMENT_RESOLUTION_PROVENANCE": "slowtask_runtime",
    "INSUFFICIENT_EVIDENCE_FOR_ACTION": "slowtask_runtime",
    "PLANNING_STARTED": "slowtask_runtime",
    "PLANNING_RESTARTED": "slowtask_runtime",
    "WAITING_FOR_SLOT": "slowtask_runtime",
    "WAITING_FOR_USER_CONFIRMATION": "slowtask_runtime",
    "FINALIZING": "slowtask_runtime",
    "SLOWTASK_DEGRADED": "slowtask_runtime",
    "SLOWTASK_FAILED": "slowtask_runtime",
    "CONFIRMATION_REQUIRED": "slowtask_runtime",
    "USER_CONFIRMATION_RECEIVED": "slowtask_runtime",
    "CONFIRMATION_ACCEPTED": "slowtask_runtime",
    "CONFIRMATION_REJECTED": "slowtask_runtime",
    "SLOWTASK_CANCEL_REQUESTED": "slowtask_runtime",
    "SLOWTASK_CANCELLED": "slowtask_runtime",
    "TOOL_CALL_STARTED": "mock_tool_event_emitter",
    "TOOL_RESULT_RECEIVED": "mock_tool_event_emitter",
    "TOOL_RESULT_MARKED_STALE": "slowtask_runtime",
    "STALE_EVIDENCE_RECORDED": "slowtask_runtime",
    "STALE_EVIDENCE_ADOPTED": "slowtask_runtime",
    "SEMANTIC_COMMITMENT_EMITTED": "slowtask_runtime",
}
MVP1_NO_PATCH_MUTATION_EVENT_NAMES = frozenset(
    {
        "USER_PATCH_RECEIVED",
        "USER_PATCH_INTERPRETED",
        "SLOWTASK_CREATED",
        "PLANNING_STARTED",
        "EVIDENCE_REVIEWED",
        "AMBIGUITY_DETECTED",
        "AMBIGUITY_RESOLVED",
        "CLARIFICATION_REQUESTED",
        "INSUFFICIENT_EVIDENCE_FOR_ACTION",
        "WAITING_FOR_SLOT",
        "FINALIZING",
        "SLOWTASK_DEGRADED",
        "SLOWTASK_FAILED",
        "PLAN_VERSION_ADVANCED",
        "TASK_REPLANNED",
        "PLANNING_RESTARTED",
        "SLOWTASK_STATE_CHANGED",
        "CONFIRMATION_REQUIRED",
        "WAITING_FOR_USER_CONFIRMATION",
        "USER_CONFIRMATION_RECEIVED",
        "CONFIRMATION_ACCEPTED",
        "CONFIRMATION_REJECTED",
        "SLOWTASK_CANCEL_REQUESTED",
        "SLOWTASK_CANCELLED",
        "TOOL_CALL_STARTED",
        "TOOL_RESULT_RECEIVED",
        "TOOL_RESULT_MARKED_STALE",
        "STALE_EVIDENCE_RECORDED",
        "STALE_EVIDENCE_ADOPTED",
        "ARGUMENTS_RESOLVED",
        "ARGUMENT_RESOLUTION_PROVENANCE",
        "SEMANTIC_COMMITMENT_EMITTED",
    }
)
MVP1_REJECTED_SWITCH_MUTATION_EVENT_NAMES = frozenset(
    {
        "USER_PATCH_INTERPRETED",
        "PLAN_VERSION_ADVANCED",
        "TASK_REPLANNED",
        "PLANNING_RESTARTED",
        "EVIDENCE_REVIEWED",
        "ARGUMENTS_RESOLVED",
        "ARGUMENT_RESOLUTION_PROVENANCE",
        "SEMANTIC_COMMITMENT_EMITTED",
    }
)
FORBIDDEN_SCOPE_FIELDS = frozenset({"task_id", "plan_version", "task_event_seq"})
ALLOWED_MANIFEST_SAFETY_FLAGS = frozenset(
    {
        "contains_raw_audio",
        "contains_raw_trace",
        "contains_real_user_input",
        "contains_secrets",
        "contains_unredacted_tool_result",
        "contains_large_raw_web_content",
    }
)
ALLOWED_SAFE_SECRET_METADATA_KEYS = frozenset({"secret_kind"})
ALLOWED_SAFE_REF_KEYS = frozenset({"authorization_ref"})
RAW_AUDIO_EXTENSIONS = (".aac", ".aiff", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav", ".weba")
FORBIDDEN_FIXTURE_KEY_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"api[_-]?key",
        r"authorization",
        r"credential",
        r"cookie",
        r"password",
        r"secret",
        r"session[_-]?secret",
        r"token",
        r"raw[_-]?audio",
        r"raw[_-]?trace",
        r"raw[_-]?transcript",
        r"raw[_-]?user[_-]?text",
        r"raw[_-]?web",
        r"real[_-]?user[_-]?input",
        r"unredacted[_-]?user",
        r"user[_-]?utterance",
        r"user[_-]?text",
    )
)


@dataclass(frozen=True)
class MVP0FixtureCheckResult:
    fixture_name: str
    result_status: str
    state_digest: dict[str, Any]


@dataclass(frozen=True)
class MVP0ScenarioResult:
    scenario_id: str
    fixture_name: str
    result_status: str
    assertion_summary: dict[str, Any]
    state_digest: dict[str, Any]
    slo_measurements: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class MVP0AcceptanceResult:
    scenario_results: tuple[MVP0ScenarioResult, ...]
    fixture_results: tuple[MVP0FixtureCheckResult, ...]
    summary: dict[str, Any]


@dataclass(frozen=True)
class MVP1FixtureCheckResult:
    fixture_name: str
    result_status: str
    state_digest: dict[str, Any]


@dataclass(frozen=True)
class MVP1ScenarioResult:
    scenario_id: str
    fixture_names: tuple[str, ...]
    result_status: str
    assertion_summary: dict[str, Any]
    state_digest: dict[str, Any]


@dataclass(frozen=True)
class MVP1AcceptanceResult:
    scenario_results: tuple[MVP1ScenarioResult, ...]
    fixture_results: tuple[MVP1FixtureCheckResult, ...]
    synthetic_eval_table: tuple[dict[str, Any], ...]
    summary: dict[str, Any]


@dataclass(frozen=True)
class MVP2FixtureCheckResult:
    fixture_name: str
    result_status: str
    state_digest: dict[str, Any]


@dataclass(frozen=True)
class MVP2ScenarioResult:
    scenario_id: str
    fixture_names: tuple[str, ...]
    result_status: str
    assertion_summary: dict[str, Any]
    state_digest: dict[str, Any]


@dataclass(frozen=True)
class MVP2AcceptanceResult:
    scenario_results: tuple[MVP2ScenarioResult, ...]
    fixture_results: tuple[MVP2FixtureCheckResult, ...]
    summary: dict[str, Any]


@dataclass(frozen=True)
class MVP3FixtureCheckResult:
    fixture_name: str
    result_status: str
    state_digest: dict[str, Any]


@dataclass(frozen=True)
class MVP3ScenarioResult:
    scenario_id: str
    fixture_names: tuple[str, ...]
    result_status: str
    assertion_summary: dict[str, Any]
    state_digest: dict[str, Any]


@dataclass(frozen=True)
class MVP3AcceptanceResult:
    scenario_results: tuple[MVP3ScenarioResult, ...]
    fixture_results: tuple[MVP3FixtureCheckResult, ...]
    summary: dict[str, Any]


def run_mvp0_acceptance_manifest(
    manifest_index: Mapping[str, Any],
    *,
    fixture_dir: Path,
) -> MVP0AcceptanceResult:
    index = deepcopy(dict(manifest_index))
    _validate_manifest_index(index)

    forbidden_event_names = frozenset(index.get("forbidden_event_names", DEFAULT_FORBIDDEN_EVENT_NAMES))
    forbidden_source_modules = frozenset(index.get("forbidden_source_modules", DEFAULT_FORBIDDEN_SOURCE_MODULES))

    fixture_results: list[MVP0FixtureCheckResult] = []
    replay_results_by_fixture: dict[str, ReplayResult] = {}
    fixtures_by_name: dict[str, dict[str, Any]] = {}
    for fixture_name in _fixture_check_names(index):
        fixture = _load_fixture(fixture_dir / fixture_name)
        _assert_github_allowed_fixture(fixture)
        assert_fixture_has_no_forbidden_mvp0_scope(
            fixture["events"],
            forbidden_event_names=forbidden_event_names,
            forbidden_source_modules=forbidden_source_modules,
        )
        result = run_replay_fixture(fixture)
        _assert_replay_matches_suite(index, fixture_name=fixture_name, result=result)
        fixtures_by_name[fixture_name] = fixture
        replay_results_by_fixture[fixture_name] = result
        fixture_results.append(
            MVP0FixtureCheckResult(
                fixture_name=fixture_name,
                result_status=result.result_status,
                state_digest=result.state_digest,
            )
        )

    scenario_entries = _scenario_entries_by_id(index)
    scenario_results: list[MVP0ScenarioResult] = []
    for scenario_id in index["required_scenarios"]:
        scenario = scenario_entries[scenario_id]
        fixture_name = str(scenario["fixture"])
        fixture = fixtures_by_name.get(fixture_name) or _load_fixture(fixture_dir / fixture_name)
        replay_result = replay_results_by_fixture.get(fixture_name) or run_replay_fixture(fixture)
        assertion_summary = _assert_scenario(scenario_id, fixture=fixture, result=replay_result)
        slo_measurements = _compute_slo_measurements(scenario.get("slo_measurements", ()), fixture)
        scenario_results.append(
            MVP0ScenarioResult(
                scenario_id=scenario_id,
                fixture_name=fixture_name,
                result_status="passed",
                assertion_summary=assertion_summary,
                state_digest=replay_result.state_digest,
                slo_measurements=slo_measurements,
            )
        )

    return MVP0AcceptanceResult(
        scenario_results=tuple(scenario_results),
        fixture_results=tuple(fixture_results),
        summary={
            "suite_id": str(index["suite_id"]),
            "result_status": "passed",
            "scenario_count": len(scenario_results),
            "fixture_count": len(fixture_results),
            "validated_fixture_names": [fixture.fixture_name for fixture in fixture_results],
        },
    )


def assert_fixture_has_no_forbidden_mvp0_scope(
    events: Sequence[Mapping[str, Any]],
    *,
    forbidden_event_names: frozenset[str] = DEFAULT_FORBIDDEN_EVENT_NAMES,
    forbidden_source_modules: frozenset[str] = DEFAULT_FORBIDDEN_SOURCE_MODULES,
) -> None:
    for event in events:
        event_name = str(event.get("event_name", ""))
        if event_name in forbidden_event_names:
            raise MVP0AcceptanceError(f"forbidden MVP0 event_name: {event_name}")

        source_module = str(event.get("source_module", ""))
        if source_module in forbidden_source_modules:
            raise MVP0AcceptanceError(f"forbidden MVP0 source_module: {source_module}")

        forbidden_fields = sorted(FORBIDDEN_SCOPE_FIELDS & set(event))
        if forbidden_fields:
            raise MVP0AcceptanceError(f"forbidden MVP0 task scope fields: {forbidden_fields}")


def run_mvp1_acceptance_manifest(
    manifest_index: Mapping[str, Any],
    *,
    fixture_dir: Path,
) -> MVP1AcceptanceResult:
    index = deepcopy(dict(manifest_index))
    _validate_mvp1_manifest_index(index)

    forbidden_event_names = frozenset(index.get("forbidden_event_names", MVP1_FORBIDDEN_EVENT_NAMES))
    forbidden_source_modules = frozenset(index.get("forbidden_source_modules", MVP1_FORBIDDEN_SOURCE_MODULES))

    fixture_results: list[MVP1FixtureCheckResult] = []
    replay_results_by_fixture: dict[str, ReplayResult] = {}
    fixtures_by_name: dict[str, dict[str, Any]] = {}
    for fixture_name in _mvp1_fixture_check_names(index):
        fixture = _load_fixture(fixture_dir / fixture_name)
        assert_mvp1_fixture_is_repo_safe(fixture)
        assert_fixture_has_no_forbidden_mvp1_scope(
            fixture["events"],
            forbidden_event_names=forbidden_event_names,
            forbidden_source_modules=forbidden_source_modules,
        )
        _assert_mvp1_mock_degraded_real_labels(fixture)
        result = run_replay_fixture(fixture)
        _assert_mvp1_replay_matches_suite(index, fixture_name=fixture_name, result=result)
        _assert_mvp1_replay_state_surface(result, fixture_name=fixture_name)
        fixtures_by_name[fixture_name] = fixture
        replay_results_by_fixture[fixture_name] = result
        fixture_results.append(
            MVP1FixtureCheckResult(
                fixture_name=fixture_name,
                result_status=result.result_status,
                state_digest=result.state_digest,
            )
        )

    scenario_entries = _mvp1_scenario_entries_by_id(index)
    scenario_results: list[MVP1ScenarioResult] = []
    for scenario_id in index["required_scenarios"]:
        scenario = scenario_entries[scenario_id]
        fixture_names = _mvp1_scenario_fixture_names(scenario)
        fixtures = tuple(fixtures_by_name[name] for name in fixture_names)
        replay_results = tuple(replay_results_by_fixture[name] for name in fixture_names)
        assertion_summary = _assert_mvp1_scenario(
            scenario_id,
            fixtures=fixtures,
            results=replay_results,
        )
        scenario_results.append(
            MVP1ScenarioResult(
                scenario_id=scenario_id,
                fixture_names=fixture_names,
                result_status="passed",
                assertion_summary=assertion_summary,
                state_digest=replay_results[-1].state_digest,
            )
        )

    synthetic_eval_table = _validate_mvp1_synthetic_eval_table(index)
    return MVP1AcceptanceResult(
        scenario_results=tuple(scenario_results),
        fixture_results=tuple(fixture_results),
        synthetic_eval_table=synthetic_eval_table,
        summary={
            "suite_id": str(index["suite_id"]),
            "result_status": "passed",
            "scenario_count": len(scenario_results),
            "fixture_count": len(fixture_results),
            "validated_fixture_names": [fixture.fixture_name for fixture in fixture_results],
            "blocking_readiness_findings": [],
            "adr_update_required": False,
            "hidden_future_scope_detected": False,
        },
    )


def assert_fixture_has_no_forbidden_mvp1_scope(
    events: Sequence[Mapping[str, Any]],
    *,
    forbidden_event_names: frozenset[str] = MVP1_FORBIDDEN_EVENT_NAMES,
    forbidden_source_modules: frozenset[str] = MVP1_FORBIDDEN_SOURCE_MODULES,
) -> None:
    for event in events:
        event_name = str(event.get("event_name", ""))
        if event_name in forbidden_event_names:
            raise MVP1AcceptanceError(f"forbidden MVP-2 event_name in MVP-1 fixture: {event_name}")

        source_module = str(event.get("source_module", ""))
        if source_module in forbidden_source_modules:
            raise MVP1AcceptanceError(f"forbidden MVP-2 source_module in MVP-1 fixture: {source_module}")

        _assert_mvp1_event_source_module(event_name=event_name, source_module=source_module)
        if event_name == "TOOL_CALL_STARTED":
            tool_name = str(event.get("tool_name", ""))
            if not (tool_name.startswith("mock.") or "synthetic" in tool_name):
                raise MVP1AcceptanceError("MVP-1 tool marker must use a mock/synthetic tool_name")
        if event_name == "TOOL_RESULT_RECEIVED":
            result_ref = str(event.get("result_ref", ""))
            if "synthetic" not in result_ref or "external" in result_ref:
                raise MVP1AcceptanceError("MVP-1 ToolResult refs must be synthetic/minimal")


def assert_mvp1_fixture_is_repo_safe(fixture: Mapping[str, Any]) -> None:
    try:
        manifest = _required_mapping(fixture, "replay_manifest")
        if manifest.get("fixture_domain") != "GITHUB_ALLOWED":
            raise MVP1AcceptanceError("fixture_domain must be GITHUB_ALLOWED")
        if manifest.get("generated_from") not in {"synthetic", "redacted", "hand_written_minimal"}:
            raise MVP1AcceptanceError("GitHub fixtures must be synthetic, redacted, or hand_written_minimal")
        if any(manifest.get(flag) is not False for flag in ALLOWED_MANIFEST_SAFETY_FLAGS):
            raise MVP1AcceptanceError("GitHub fixture safety flags must all be false")

        for path, value in _iter_json_values(fixture):
            last_key = path[-1] if path else ""
            if path[:1] == ("replay_manifest",) and last_key in ALLOWED_MANIFEST_SAFETY_FLAGS:
                if value is not False:
                    raise MVP1AcceptanceError(f"unsafe manifest safety flag: {'.'.join(path)}")
                continue
            if last_key in ALLOWED_SAFE_SECRET_METADATA_KEYS:
                if not isinstance(value, str) or _contains_secret_like_value(value):
                    raise MVP1AcceptanceError(f"unsafe secret metadata: {'.'.join(path)}")
                continue
            if last_key in ALLOWED_SAFE_REF_KEYS:
                if not isinstance(value, str) or not is_safe_authorization_ref(value, allow_local=False):
                    raise MVP1AcceptanceError(f"unsafe authorization ref: {'.'.join(path)}")
                _assert_mvp1_safe_string_fixture_value(value, ".".join(path))
                continue
            if any(pattern.search(last_key) for pattern in FORBIDDEN_FIXTURE_KEY_PATTERNS):
                raise MVP1AcceptanceError(f"forbidden fixture key: {'.'.join(path)}")
            if isinstance(value, str):
                _assert_mvp1_safe_string_fixture_value(value, ".".join(path))
    except MVP1AcceptanceError as exc:
        raise MVP1AcceptanceError(f"repo-unsafe MVP-1 fixture content: {exc}") from exc


def run_mvp2_acceptance_manifest(
    manifest_index: Mapping[str, Any],
    *,
    fixture_dir: Path,
    required_scenario_ids: Sequence[str] | None = None,
) -> MVP2AcceptanceResult:
    required_scenarios = tuple(required_scenario_ids or MVP2_REQUIRED_SCENARIOS)
    index = deepcopy(dict(manifest_index))
    _validate_mvp2_manifest_index(index, required_scenario_ids=required_scenarios)

    forbidden_source_modules = frozenset(
        _string_tuple_mvp2(index.get("forbidden_source_modules", ()), "forbidden_source_modules")
    )
    fixture_results: list[MVP2FixtureCheckResult] = []
    replay_results_by_fixture: dict[str, ReplayResult] = {}
    fixtures_by_name: dict[str, dict[str, Any]] = {}
    for fixture_name in _mvp2_fixture_check_names(index):
        fixture = _load_mvp2_fixture(fixture_dir / fixture_name)
        assert_mvp2_fixture_is_repo_safe(fixture)
        assert_fixture_has_no_forbidden_mvp2_scope(
            fixture["events"],
            forbidden_source_modules=forbidden_source_modules,
        )
        _assert_mvp2_mock_degraded_real_labels(fixture)
        first_result = run_replay_fixture(fixture)
        second_result = run_replay_fixture(fixture)
        if first_result.state_digest != second_result.state_digest:
            raise MVP2AcceptanceError(f"{fixture_name} replay is not deterministic")
        _assert_mvp2_replay_matches_suite(index, fixture_name=fixture_name, result=first_result)
        _assert_mvp2_replay_state_surface(first_result, fixture_name=fixture_name)
        fixtures_by_name[fixture_name] = fixture
        replay_results_by_fixture[fixture_name] = first_result
        fixture_results.append(
            MVP2FixtureCheckResult(
                fixture_name=fixture_name,
                result_status=first_result.result_status,
                state_digest=first_result.state_digest,
            )
        )

    scenario_entries = _mvp2_scenario_entries_by_id(index)
    scenario_results: list[MVP2ScenarioResult] = []
    for scenario_id in required_scenarios:
        scenario = scenario_entries[scenario_id]
        fixture_names = _mvp2_scenario_fixture_names(scenario)
        fixtures = tuple(fixtures_by_name[name] for name in fixture_names)
        replay_results = tuple(replay_results_by_fixture[name] for name in fixture_names)
        assertion_summary = _assert_mvp2_scenario(
            scenario_id,
            fixtures=fixtures,
            results=replay_results,
        )
        scenario_results.append(
            MVP2ScenarioResult(
                scenario_id=scenario_id,
                fixture_names=fixture_names,
                result_status="passed",
                assertion_summary=assertion_summary,
                state_digest=replay_results[-1].state_digest,
            )
        )

    return MVP2AcceptanceResult(
        scenario_results=tuple(scenario_results),
        fixture_results=tuple(fixture_results),
        summary={
            "suite_id": str(index["suite_id"]),
            "result_status": "passed",
            "scenario_count": len(scenario_results),
            "fixture_count": len(fixture_results),
            "validated_fixture_names": [fixture.fixture_name for fixture in fixture_results],
            "deterministic_replay_verified": True,
            "runtime_execution_detected": False,
            "adr_update_required": False,
            "hidden_future_scope_detected": False,
        },
    )


def assert_fixture_has_no_forbidden_mvp2_scope(
    events: Sequence[Mapping[str, Any]],
    *,
    forbidden_source_modules: frozenset[str] = MVP2_REQUIRED_FORBIDDEN_SOURCE_MODULES,
) -> None:
    for event in events:
        event_name = str(event.get("event_name", ""))
        source_module = str(event.get("source_module", ""))
        if source_module in forbidden_source_modules:
            raise MVP2AcceptanceError(f"forbidden MVP-2 source_module: {source_module}")

        tool_name = str(event.get("tool_name", ""))
        if event_name in MVP2_TOOL_EXECUTOR_OWNED_EVENT_NAMES and source_module != "tool_executor":
            raise MVP2AcceptanceError(f"{event_name} must be Tool Executor owned")
        if event_name == "TOOL_UI_STATE_PATCHED" and source_module != "tool_executor":
            raise MVP2AcceptanceError("TOOL_UI_STATE_PATCHED must be Tool Executor owned")
        if event_name == "TOOL_UI_STATE_PATCHED" and tool_name == "webSearch":
            raise MVP2AcceptanceError("webSearch must not directly patch demo UI/backend state")
        if event_name == "SPOKEN_PLAN_EMITTED" and source_module != "composer":
            raise MVP2AcceptanceError("Thinker-as-Composer output must use source_module=composer")
        if event_name == "COMMITMENT_COVERAGE_CHECK_PASSED" and source_module != "coverage_checker":
            raise MVP2AcceptanceError("CommitmentCoverageCheck must be coverage_checker owned")
        if event_name == "PROGRESS_TRUTHFULNESS_CHECK_PASSED" and source_module != "truthfulness_checker":
            raise MVP2AcceptanceError("ProgressTruthfulnessCheck must be truthfulness_checker owned")
        if event_name == "TOOL_RESULT_RECEIVED" and tool_name == "webSearch":
            if event.get("trust_level") != "UNTRUSTED_WEB_EVIDENCE":
                raise MVP2AcceptanceError("webSearch result must be UNTRUSTED_WEB_EVIDENCE")
            if event.get("source_type") != "EXTERNAL_READ_UNTRUSTED":
                raise MVP2AcceptanceError("webSearch result must remain EXTERNAL_READ_UNTRUSTED evidence")


def assert_mvp2_fixture_is_repo_safe(fixture: Mapping[str, Any]) -> None:
    try:
        manifest = _required_mapping_mvp2(fixture, "replay_manifest")
        if manifest.get("fixture_domain") != "GITHUB_ALLOWED":
            raise MVP2AcceptanceError("fixture_domain must be GITHUB_ALLOWED")
        if manifest.get("replay_mode") != "deterministic":
            raise MVP2AcceptanceError("MVP-2 fixtures must use deterministic replay")
        if manifest.get("generated_from") not in {"synthetic", "redacted", "hand_written_minimal"}:
            raise MVP2AcceptanceError("GitHub fixtures must be synthetic, redacted, or hand_written_minimal")
        if manifest.get("allowed_re_eval_components", []) != []:
            raise MVP2AcceptanceError("deterministic MVP-2 fixtures must not opt into re-eval components")
        if any(manifest.get(flag) is not False for flag in ALLOWED_MANIFEST_SAFETY_FLAGS):
            raise MVP2AcceptanceError("GitHub fixture safety flags must all be false")

        for path, value in _iter_json_values(fixture):
            last_key = path[-1] if path else ""
            if path[:1] == ("replay_manifest",) and last_key in ALLOWED_MANIFEST_SAFETY_FLAGS:
                if value is not False:
                    raise MVP2AcceptanceError(f"unsafe manifest safety flag: {'.'.join(path)}")
                continue
            if last_key in MVP2_ALLOWED_SAFE_SECRET_METADATA_KEYS:
                if not isinstance(value, str) or _contains_secret_like_value(value):
                    raise MVP2AcceptanceError(f"unsafe authorization/secret metadata: {'.'.join(path)}")
                _assert_mvp2_safe_string_fixture_value(value, ".".join(path))
                continue
            if last_key in ALLOWED_SAFE_REF_KEYS:
                if not isinstance(value, str) or not is_safe_authorization_ref(value, allow_local=False):
                    raise MVP2AcceptanceError(f"unsafe authorization ref: {'.'.join(path)}")
                _assert_mvp2_safe_string_fixture_value(value, ".".join(path))
                continue
            if any(pattern.search(last_key) for pattern in FORBIDDEN_FIXTURE_KEY_PATTERNS):
                raise MVP2AcceptanceError(f"forbidden fixture key: {'.'.join(path)}")
            if isinstance(value, str):
                _assert_mvp2_safe_string_fixture_value(value, ".".join(path))
    except MVP2AcceptanceError as exc:
        raise MVP2AcceptanceError(f"repo-unsafe MVP-2 fixture content: {exc}") from exc


def _validate_mvp2_manifest_index(
    index: Mapping[str, Any],
    *,
    required_scenario_ids: tuple[str, ...],
) -> None:
    required_fields = {
        "manifest_index_schema_version",
        "suite_id",
        "fixture_domain",
        "replay_mode",
        "generated_fixtures_must_be",
        "required_scenarios",
        "initial_tool_scope",
        "fixture_checks",
        "scenarios",
        "forbidden_behaviors",
        "forbidden_source_modules",
        "fixture_safety_flags",
        "required_replay_properties",
    }
    missing = required_fields - set(index)
    if missing:
        raise MVP2AcceptanceError(f"Missing MVP-2 acceptance manifest fields: {sorted(missing)}")
    if index["manifest_index_schema_version"] != "1.0":
        raise MVP2AcceptanceError("manifest_index_schema_version must be '1.0'")
    if index["suite_id"] != "MVP2-ACCEPTANCE":
        raise MVP2AcceptanceError("suite_id must be 'MVP2-ACCEPTANCE'")
    if index["fixture_domain"] != "GITHUB_ALLOWED":
        raise MVP2AcceptanceError("MVP-2 acceptance fixtures must be GITHUB_ALLOWED")
    if index["replay_mode"] != "deterministic":
        raise MVP2AcceptanceError("MVP-2 acceptance uses deterministic replay")

    generated_requirements = _string_tuple_mvp2(
        index["generated_fixtures_must_be"],
        "generated_fixtures_must_be",
    )
    if generated_requirements != ("synthetic", "redacted", "minimal"):
        raise MVP2AcceptanceError("generated_fixtures_must_be must be synthetic/redacted/minimal")

    required_scenarios = _string_tuple_mvp2(index["required_scenarios"], "required_scenarios")
    if required_scenarios != required_scenario_ids:
        raise MVP2AcceptanceError(f"required_scenarios must be {list(required_scenario_ids)}")

    _validate_mvp2_initial_tool_scope(index)
    _validate_mvp2_scope_gate_lists(index)

    scenario_entries = _mvp2_scenario_entries_by_id(index)
    missing_scenarios = [scenario_id for scenario_id in required_scenarios if scenario_id not in scenario_entries]
    if missing_scenarios:
        raise MVP2AcceptanceError(f"Missing scenario entries: {missing_scenarios}")
    fixture_check_names = set(_mvp2_fixture_check_names(index))
    missing_fixture_checks = sorted(
        {
            fixture_name
            for scenario in scenario_entries.values()
            for fixture_name in _mvp2_scenario_fixture_names(scenario)
            if fixture_name not in fixture_check_names
        }
    )
    if missing_fixture_checks:
        raise MVP2AcceptanceError(f"scenario fixtures must be listed in fixture_checks: {missing_fixture_checks}")


def _validate_mvp2_initial_tool_scope(index: Mapping[str, Any]) -> None:
    tool_scope = _required_sequence_mvp2(index, "initial_tool_scope")
    tools_by_name: dict[str, Mapping[str, Any]] = {}
    for tool in tool_scope:
        if not isinstance(tool, Mapping):
            raise MVP2AcceptanceError("initial_tool_scope entries must be objects")
        tool_name = _required_str_mvp2(tool, "tool_name")
        tools_by_name[tool_name] = tool
    missing_tools = sorted(set(MVP2_REQUIRED_TOOL_SCOPE) - set(tools_by_name))
    if missing_tools:
        raise MVP2AcceptanceError(f"initial_tool_scope missing tools: {missing_tools}")
    for tool_name, expected in MVP2_REQUIRED_TOOL_SCOPE.items():
        tool = tools_by_name[tool_name]
        for field, expected_value in expected.items():
            if tool.get(field) != expected_value:
                raise MVP2AcceptanceError(f"{tool_name} {field} must be {expected_value}")
        side_effect_classes = set(_string_tuple_mvp2(tool.get("allowed_side_effect_classes", ()), "allowed_side_effect_classes"))
        if not side_effect_classes:
            raise MVP2AcceptanceError(f"{tool_name} must declare allowed_side_effect_classes")
        expected_side_effect_classes = MVP2_ALLOWED_SIDE_EFFECT_CLASSES_BY_TOOL.get(
            tool_name,
            MVP2_GLOBAL_ALLOWED_SIDE_EFFECT_CLASSES,
        )
        unsafe_side_effect_classes = sorted(side_effect_classes - expected_side_effect_classes)
        if unsafe_side_effect_classes:
            raise MVP2AcceptanceError(
                f"{tool_name} allowed_side_effect_classes include unsafe or future-scope classes: "
                f"{unsafe_side_effect_classes}"
            )
        if tool_name == "webSearch":
            if side_effect_classes != {"READ_ONLY"}:
                raise MVP2AcceptanceError("webSearch must be READ_ONLY only")
            if tool.get("ui_patch_capable") is not False:
                raise MVP2AcceptanceError("webSearch must not be ui_patch_capable")


def _validate_mvp2_scope_gate_lists(index: Mapping[str, Any]) -> None:
    forbidden_behaviors = set(_string_tuple_mvp2(index["forbidden_behaviors"], "forbidden_behaviors"))
    missing_behaviors = sorted(MVP2_REQUIRED_FORBIDDEN_BEHAVIORS - forbidden_behaviors)
    if missing_behaviors:
        raise MVP2AcceptanceError(f"forbidden_behaviors missing MVP-2 scope gates: {missing_behaviors}")

    forbidden_source_modules = set(
        _string_tuple_mvp2(index["forbidden_source_modules"], "forbidden_source_modules")
    )
    missing_source_modules = sorted(MVP2_REQUIRED_FORBIDDEN_SOURCE_MODULES - forbidden_source_modules)
    if missing_source_modules:
        raise MVP2AcceptanceError(
            f"forbidden_source_modules missing MVP-2 scope gates: {missing_source_modules}"
        )

    fixture_safety_flags = _required_mapping_mvp2(index, "fixture_safety_flags")
    if any(fixture_safety_flags.get(flag) is not False for flag in ALLOWED_MANIFEST_SAFETY_FLAGS):
        raise MVP2AcceptanceError("fixture_safety_flags must all be false")

    replay_properties = set(
        _string_tuple_mvp2(index["required_replay_properties"], "required_replay_properties")
    )
    missing_properties = sorted(MVP2_REQUIRED_REPLAY_PROPERTIES - replay_properties)
    if missing_properties:
        raise MVP2AcceptanceError(f"required_replay_properties missing scope gates: {missing_properties}")


def _mvp2_fixture_check_names(index: Mapping[str, Any]) -> tuple[str, ...]:
    checks = _required_sequence_mvp2(index, "fixture_checks")
    names: list[str] = []
    for check in checks:
        if not isinstance(check, Mapping) or not isinstance(check.get("fixture"), str):
            raise MVP2AcceptanceError("fixture_checks entries must contain fixture")
        names.append(str(check["fixture"]))
    if len(names) != len(set(names)):
        raise MVP2AcceptanceError("fixture_checks must not contain duplicate fixtures")
    return tuple(names)


def _mvp2_scenario_entries_by_id(index: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    scenarios = _required_sequence_mvp2(index, "scenarios")
    entries: dict[str, Mapping[str, Any]] = {}
    for scenario in scenarios:
        if not isinstance(scenario, Mapping):
            raise MVP2AcceptanceError("scenarios entries must be objects")
        scenario_id = scenario.get("scenario_id")
        if not isinstance(scenario_id, str) or not scenario_id:
            raise MVP2AcceptanceError("scenario entry must include scenario_id")
        _mvp2_scenario_fixture_names(scenario)
        if scenario_id in entries:
            raise MVP2AcceptanceError(f"duplicate scenario_id: {scenario_id}")
        entries[scenario_id] = scenario
    return entries


def _mvp2_scenario_fixture_names(scenario: Mapping[str, Any]) -> tuple[str, ...]:
    if "fixtures" in scenario:
        fixture_names = _string_tuple_mvp2(scenario["fixtures"], "fixtures")
    else:
        fixture = scenario.get("fixture")
        if not isinstance(fixture, str):
            raise MVP2AcceptanceError("scenario entry must include fixture or fixtures")
        fixture_names = (fixture,)
    if not fixture_names or not all(name.endswith(".fixture.json") for name in fixture_names):
        raise MVP2AcceptanceError("scenario fixtures must be .fixture.json files")
    return fixture_names


def _assert_mvp2_replay_matches_suite(
    index: Mapping[str, Any],
    *,
    fixture_name: str,
    result: ReplayResult,
) -> None:
    if result.fixture_domain != index["fixture_domain"]:
        raise MVP2AcceptanceError(f"{fixture_name} fixture_domain mismatch")
    if result.replay_mode != index["replay_mode"]:
        raise MVP2AcceptanceError(f"{fixture_name} replay_mode mismatch")
    if result.result_status != "passed":
        raise MVP2AcceptanceError(f"{fixture_name} replay did not pass")
    if result.diagnostics["ignored_events"]:
        raise MVP2AcceptanceError(f"{fixture_name} replay ignored MVP-2 events")


def _assert_mvp2_replay_state_surface(result: ReplayResult, *, fixture_name: str) -> None:
    missing = sorted(MVP2_REQUIRED_STATE_DIGEST_FIELDS - set(result.state_digest))
    if missing:
        raise MVP2AcceptanceError(f"{fixture_name} state digest missing fields: {missing}")
    if result.trace_privacy_state.fixture_domain != "GITHUB_ALLOWED":
        raise MVP2AcceptanceError(f"{fixture_name} did not replay TracePrivacyState fixture domain")
    unsafe_flags = {
        "contains_raw_audio": result.trace_privacy_state.contains_raw_audio,
        "contains_raw_trace": result.trace_privacy_state.contains_raw_trace,
        "contains_real_user_input": result.trace_privacy_state.contains_real_user_input,
        "contains_secrets": result.trace_privacy_state.contains_secrets,
        "contains_unredacted_tool_result": result.trace_privacy_state.contains_unredacted_tool_result,
        "contains_large_raw_web_content": result.trace_privacy_state.contains_large_raw_web_content,
    }
    if any(value is not False for value in unsafe_flags.values()):
        raise MVP2AcceptanceError(f"{fixture_name} replayed unsafe fixture flags: {unsafe_flags}")


def _assert_mvp2_scenario(
    scenario_id: str,
    *,
    fixtures: tuple[Mapping[str, Any], ...],
    results: tuple[ReplayResult, ...],
) -> dict[str, Any]:
    if scenario_id == "MVP2-TOOL-MANIFEST-001":
        return _assert_mvp2_tool_manifest(fixtures[0], results[0])
    if scenario_id == "MVP2-TOOL-ARGS-PARTIAL-001":
        return _assert_mvp2_tool_arguments_partial(fixtures[0], results[0])
    if scenario_id == "MVP2-TOOL-BLOCKED-INSUFFICIENT-ARGS-001":
        return _assert_mvp2_tool_blocked_insufficient_args(fixtures[0], results[0])
    if scenario_id == "MVP2-MEMO-SANDBOX-WRITE-001":
        return _assert_mvp2_demo_tool_call(
            fixtures[0],
            results[0],
            tool_call_id="tool_call_mvp2_slice4_memo_create",
            tool_name="memo",
            trust_level="TRUSTED_DEMO_TOOL_RESULT",
            source_type="DEMO_SANDBOX",
            required_ui_namespace="memo",
        )
    if scenario_id == "MVP2-ALARM-SANDBOX-SCHEDULE-001":
        return _assert_mvp2_demo_tool_call(
            fixtures[0],
            results[0],
            tool_call_id="tool_call_mvp2_slice4_alarm_create",
            tool_name="alarm",
            trust_level="TRUSTED_DEMO_TOOL_RESULT",
            source_type="DEMO_SANDBOX",
            required_ui_namespace="alarm",
        )
    if scenario_id == "MVP2-FLASHLIGHT-DEMO-DEVICE-ACTION-001":
        return _assert_mvp2_demo_tool_call(
            fixtures[0],
            results[0],
            tool_call_id="tool_call_mvp2_slice4_flashlight_on",
            tool_name="flashlight",
            trust_level="TRUSTED_DEMO_TOOL_RESULT",
            source_type="DEMO_SANDBOX",
            required_ui_namespace="flashlight",
        )
    if scenario_id == "MVP2-WEATHER-READ-ONLY-001":
        return _assert_mvp2_demo_tool_call(
            fixtures[0],
            results[0],
            tool_call_id="tool_call_mvp2_slice4_weather",
            tool_name="weather",
            trust_level="EXTERNAL_READ_PROVIDER_RESULT",
            source_type="READ_ONLY_EXTERNAL",
            required_ui_namespace=None,
            optional_ui_namespace="weather",
        )
    if scenario_id == "MVP2-WEBSEARCH-UNTRUSTED-EVIDENCE-001":
        return _assert_mvp2_websearch_untrusted_evidence(fixtures[0], results[0])
    if scenario_id == "MVP2-UI-STATE-PATCHED-001":
        return _assert_mvp2_ui_state_patched(fixtures[0], results[0])
    if scenario_id == "MVP2-DEMO-DESTRUCTIVE-CONFIRMATION-001":
        return _assert_mvp2_demo_destructive_confirmation(fixtures[0], results[0])
    if scenario_id == "MVP2-STALE-TOOL-RESULT-PROGRESSIVE-001":
        return _assert_mvp2_progressive_stale_tool_result(fixtures[0], results[0])
    if scenario_id == "MVP2-COMPOSER-SPOKEN-PLAN-001":
        return _assert_mvp2_composer_spoken_plan(fixtures[0], results[0])
    if scenario_id == "MVP2-COMMITMENT-COVERAGE-001":
        return _assert_mvp2_commitment_coverage_gate(fixtures[0], results[0])
    if scenario_id == "MVP2-PROGRESS-TRUTHFULNESS-001":
        return _assert_mvp2_progress_truthfulness_gate(fixtures[0], results[0])
    if scenario_id == "MVP2-ACCEPTANCE-SCOPE-SAFETY-001":
        return _assert_mvp2_acceptance_scope_safety(fixtures, results)
    raise MVP2AcceptanceError(f"Unknown MVP-2 acceptance scenario: {scenario_id}")


def _assert_mvp2_tool_manifest(fixture: Mapping[str, Any], result: ReplayResult) -> dict[str, Any]:
    events = _events_by_name_mvp2(fixture)
    _require_mvp2_event_names(events, ["TOOL_MANIFEST_LOADED"])
    if "TOOL_EXECUTION_STARTED" in events:
        raise MVP2AcceptanceError("tool manifest scenario must not start execution")
    manifests = {str(event["tool_name"]): event for event in events["TOOL_MANIFEST_LOADED"]}
    expected_tool_names = ("alarm", "flashlight", "memo", "weather", "webSearch")
    if tuple(sorted(manifests)) != expected_tool_names:
        raise MVP2AcceptanceError("tool manifest scenario must load all MVP-2 tools")
    required_fields = {"tool_adapter_id", "tool_manifest_version", "side_effect_class"}
    for tool_name, event in manifests.items():
        missing_fields = sorted(field for field in required_fields if event.get(field) in (None, ""))
        if missing_fields:
            raise MVP2AcceptanceError(f"{tool_name} manifest missing fields: {missing_fields}")
    websearch = manifests["webSearch"]
    if websearch.get("tool_category") != "EXTERNAL_READ_UNTRUSTED":
        raise MVP2AcceptanceError("webSearch manifest must mark untrusted external read category")
    if websearch.get("trust_level") != "UNTRUSTED_WEB_EVIDENCE":
        raise MVP2AcceptanceError("webSearch manifest trust label must be UNTRUSTED_WEB_EVIDENCE")
    if result.tool_execution_state.tool_calls:
        raise MVP2AcceptanceError("tool manifest scenario must not replay tool calls")
    return {
        "manifest_tool_names": list(expected_tool_names),
        "manifest_count": len(manifests),
        "execution_started_count": 0,
    }


def _assert_mvp2_tool_arguments_partial(fixture: Mapping[str, Any], result: ReplayResult) -> dict[str, Any]:
    events = _events_by_name_mvp2(fixture)
    _require_mvp2_event_names(events, ["TOOL_ARGUMENTS_PARTIAL"])
    partial = events["TOOL_ARGUMENTS_PARTIAL"][0]
    tool_call_id = str(partial["tool_call_id"])
    call = result.tool_execution_state.tool_calls[tool_call_id]
    if not partial.get("missing_fields"):
        raise MVP2AcceptanceError("TOOL_ARGUMENTS_PARTIAL must record missing_fields")
    if call.ready_arguments or call.authorizations or call.execution_started or call.results:
        raise MVP2AcceptanceError("partial argument scenario must not execute incomplete tool call")
    return {
        "tool_call_id": tool_call_id,
        "missing_fields": list(partial["missing_fields"]),
        "partial_argument_count": len(call.partial_arguments),
        "execution_started_count": len(call.execution_started),
    }


def _assert_mvp2_tool_blocked_insufficient_args(fixture: Mapping[str, Any], result: ReplayResult) -> dict[str, Any]:
    events = _events_by_name_mvp2(fixture)
    _require_mvp2_event_names(events, ["TOOL_EXECUTION_BLOCKED_INSUFFICIENT_ARGUMENTS"])
    blocked = events["TOOL_EXECUTION_BLOCKED_INSUFFICIENT_ARGUMENTS"][0]
    if blocked.get("source_event_id") in (None, ""):
        raise MVP2AcceptanceError("blocked insufficient args event must cite source_event_id")
    tool_call_id = str(blocked["tool_call_id"])
    call = result.tool_execution_state.tool_calls[tool_call_id]
    if call.lifecycle_status != "BLOCKED_INSUFFICIENT_ARGUMENTS":
        raise MVP2AcceptanceError("blocked insufficient args must replay blocked lifecycle")
    if call.execution_started or call.results:
        raise MVP2AcceptanceError("blocked insufficient args must not execute or produce ToolResult")
    return {
        "tool_call_id": tool_call_id,
        "blocking_fields": list(blocked["blocking_fields"]),
        "source_event_id": blocked["source_event_id"],
        "lifecycle_status": call.lifecycle_status,
    }


def _assert_mvp2_demo_tool_call(
    fixture: Mapping[str, Any],
    result: ReplayResult,
    *,
    tool_call_id: str,
    tool_name: str,
    trust_level: str,
    source_type: str,
    required_ui_namespace: str | None,
    optional_ui_namespace: str | None = None,
) -> dict[str, Any]:
    call = result.tool_execution_state.tool_calls[tool_call_id]
    call_tool_name = call.tool_name or _mvp2_tool_name_for_call(fixture, tool_call_id)
    if call_tool_name != tool_name:
        raise MVP2AcceptanceError(f"{tool_call_id} must bind tool_name={tool_name}")
    if call.lifecycle_status != "RESULT_RECEIVED":
        raise MVP2AcceptanceError(f"{tool_call_id} must replay a completed ToolResult")
    if not call.execution_started:
        raise MVP2AcceptanceError(f"{tool_call_id} must record TOOL_EXECUTION_STARTED")
    result_event = call.results[-1]
    if result_event.trust_level != trust_level or result_event.source_type != source_type:
        raise MVP2AcceptanceError(f"{tool_call_id} ToolResult trust/source mismatch")
    if required_ui_namespace is None and optional_ui_namespace is None:
        if call.ui_patches:
            raise MVP2AcceptanceError(f"{tool_call_id} must not mutate demo UI state")
    elif required_ui_namespace is not None:
        if not call.ui_patches:
            raise MVP2AcceptanceError(f"{tool_call_id} must emit TOOL_UI_STATE_PATCHED")
        if required_ui_namespace not in result.demo_ui_state.namespaces:
            raise MVP2AcceptanceError(f"{required_ui_namespace} UI namespace was not replayed from patches")
    elif call.ui_patches and optional_ui_namespace not in result.demo_ui_state.namespaces:
        raise MVP2AcceptanceError(f"{optional_ui_namespace} UI namespace was not replayed from optional patch")
    _assert_mvp2_no_non_patch_demo_mutations(fixture)
    return {
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
        "trust_level": trust_level,
        "source_type": source_type,
        "ui_patch_count": len(call.ui_patches),
    }


def _assert_mvp2_websearch_untrusted_evidence(fixture: Mapping[str, Any], result: ReplayResult) -> dict[str, Any]:
    call = result.tool_execution_state.tool_calls["tool_call_mvp2_slice4_websearch"]
    if call.results[-1].trust_level != "UNTRUSTED_WEB_EVIDENCE":
        raise MVP2AcceptanceError("webSearch ToolResult must be UNTRUSTED_WEB_EVIDENCE")
    if call.results[-1].source_type != "EXTERNAL_READ_UNTRUSTED":
        raise MVP2AcceptanceError("webSearch source_type must be EXTERNAL_READ_UNTRUSTED")
    if call.ui_patches:
        raise MVP2AcceptanceError("webSearch must not emit UI patches")
    task = result.slowtask_state.tasks["task_mvp2_slice4"]
    evidence_reviewed = any(
        event.event_name == "EVIDENCE_REVIEWED"
        and event.refs == ("result://synthetic/demo_backend/websearch/search_000001",)
        for event in task.evidence_events
    )
    if not evidence_reviewed:
        raise MVP2AcceptanceError("webSearch result must enter evidence review, not instruction/backend action")
    return {
        "tool_name": "webSearch",
        "trust_level": call.results[-1].trust_level,
        "source_type": call.results[-1].source_type,
        "ui_patch_count": len(call.ui_patches),
        "evidence_reviewed": evidence_reviewed,
    }


def _assert_mvp2_ui_state_patched(fixture: Mapping[str, Any], result: ReplayResult) -> dict[str, Any]:
    events = _events_by_name_mvp2(fixture)
    _require_mvp2_event_names(events, ["TOOL_UI_STATE_PATCHED"])
    if len(events["TOOL_UI_STATE_PATCHED"]) != 1:
        raise MVP2AcceptanceError("UI patch scenario must carry exactly one TOOL_UI_STATE_PATCHED")
    _assert_mvp2_no_non_patch_demo_mutations(fixture)
    return {
        "demo_ui_namespaces": sorted(result.demo_ui_state.namespaces),
        "tool_ui_patch_count": len(events["TOOL_UI_STATE_PATCHED"]),
        "non_patch_demo_mutation_count": 0,
    }


def _assert_mvp2_demo_destructive_confirmation(
    fixture: Mapping[str, Any],
    result: ReplayResult,
) -> dict[str, Any]:
    events = _events_by_name_mvp2(fixture)
    _require_mvp2_event_names(
        events,
        [
            "CONFIRMATION_REQUIRED",
            "WAITING_FOR_USER_CONFIRMATION",
            "USER_CONFIRMATION_RECEIVED",
            "CONFIRMATION_ACCEPTED",
            "TOOL_EXECUTION_AUTHORIZED",
            "TOOL_EXECUTION_STARTED",
            "TOOL_UI_STATE_PATCHED",
            "TOOL_RESULT_RECEIVED",
        ],
    )
    destructive_calls: list[str] = []
    for event in events["TOOL_MANIFEST_LOADED"]:
        if event.get("side_effect_class") == "DEMO_DESTRUCTIVE_ACTION":
            tool_prefix = str(event["tool_name"])
            for call_id, call in result.tool_execution_state.tool_calls.items():
                call_tool_name = call.tool_name or _mvp2_tool_name_for_call(fixture, call_id)
                if call_tool_name == tool_prefix:
                    destructive_calls.append(call_id)
                    if not call.authorizations or call.authorizations[-1].confirmation_id in (None, ""):
                        raise MVP2AcceptanceError("destructive tool execution must cite accepted confirmation")
                    if not call.execution_started or not call.ui_patches or not call.results:
                        raise MVP2AcceptanceError("destructive tool call must start, patch UI, and record result")
    if sorted(destructive_calls) != [
        "tool_call_mvp2_slice5_alarm_cancel",
        "tool_call_mvp2_slice5_memo_delete",
    ]:
        raise MVP2AcceptanceError("destructive confirmation fixture must cover memo delete and alarm cancel")
    return {
        "destructive_tool_calls": sorted(destructive_calls),
        "accepted_confirmation_count": len(events["CONFIRMATION_ACCEPTED"]),
        "execution_started_count": len(destructive_calls),
        "demo_ui_namespaces": sorted(result.demo_ui_state.namespaces),
    }


def _assert_mvp2_progressive_stale_tool_result(
    fixture: Mapping[str, Any],
    result: ReplayResult,
) -> dict[str, Any]:
    events = _events_by_name_mvp2(fixture)
    _require_mvp2_event_names(
        events,
        [
            "TOOL_EXECUTION_STARTED",
            "PLAN_VERSION_ADVANCED",
            "TOOL_RESULT_RECEIVED",
            "TOOL_RESULT_MARKED_STALE",
            "STALE_EVIDENCE_RECORDED",
        ],
    )
    result_event = events["TOOL_RESULT_RECEIVED"][0]
    stale_event = events["TOOL_RESULT_MARKED_STALE"][0]
    recorded = events["STALE_EVIDENCE_RECORDED"][0]
    if int(result_event["plan_version"]) >= int(stale_event["current_plan_version"]):
        raise MVP2AcceptanceError("stale ToolResult must retain old plan_version binding")
    if stale_event.get("caused_by_event_id") != result_event["event_id"]:
        raise MVP2AcceptanceError("TOOL_RESULT_MARKED_STALE must be caused by old-plan ToolResult")
    if recorded.get("source_tool_result_event_id") != result_event["event_id"]:
        raise MVP2AcceptanceError("STALE_EVIDENCE_RECORDED must cite old ToolResult")
    task = result.slowtask_state.tasks[str(recorded["task_id"])]
    if task.semantic_commitments:
        raise MVP2AcceptanceError("stale result without adoption must not emit SemanticCommitment")
    return {
        "old_plan_tool_result_event_id": result_event["event_id"],
        "current_plan_version": task.current_plan_version,
        "stale_evidence_count": len(task.stale_evidence_refs),
        "adopted_evidence_count": len(task.adopted_evidence),
        "semantic_commitment_count": len(task.semantic_commitments),
    }


def _assert_mvp2_composer_spoken_plan(fixture: Mapping[str, Any], result: ReplayResult) -> dict[str, Any]:
    events = _events_by_name_mvp2(fixture)
    _require_mvp2_event_names(events, ["SPOKEN_PLAN_EMITTED"])
    if any(event_name in events for event_name in {
        "COMMITMENT_COVERAGE_CHECK_PASSED",
        "COMMITMENT_COVERAGE_CHECK_FAILED",
        "PROGRESS_TRUTHFULNESS_CHECK_PASSED",
        "PROGRESS_TRUTHFULNESS_CHECK_FAILED",
        "PLAYBACK_SPAN_STARTED",
    }):
        raise MVP2AcceptanceError("composer scenario must leave SpokenPlan unchecked and unplayed")
    output_modes = sorted({plan.output_mode for plan in result.spoken_plan_state.spoken_plans.values()})
    return {
        "spoken_plan_count": len(result.spoken_plan_state.spoken_plans),
        "checked_plan_count": len(result.spoken_plan_check_state.passed_checks)
        + len(result.spoken_plan_check_state.failed_checks),
        "playback_count": len(events.get("PLAYBACK_SPAN_STARTED", ())),
        "output_modes": output_modes,
    }


def _assert_mvp2_commitment_coverage_gate(fixture: Mapping[str, Any], result: ReplayResult) -> dict[str, Any]:
    events = _events_by_name_mvp2(fixture)
    _require_mvp2_event_names(events, ["COMMITMENT_COVERAGE_CHECK_PASSED", "PLAYBACK_SPAN_STARTED"])
    coverage = _find_event_mvp2(fixture, "COMMITMENT_COVERAGE_CHECK_PASSED")
    playback = _find_event_mvp2(
        fixture,
        "PLAYBACK_SPAN_STARTED",
        approved_check_event_id=coverage["event_id"],
    )
    if playback.get("spoken_plan_id") != coverage.get("spoken_plan_id"):
        raise MVP2AcceptanceError("coverage-gated playback must reference matching spoken_plan_id")
    if result.playback_state.approved_check_event_id != coverage["event_id"]:
        raise MVP2AcceptanceError("PlaybackState must retain approved coverage check id")
    return {
        "coverage_pass_event_id": coverage["event_id"],
        "spoken_plan_id": coverage["spoken_plan_id"],
        "playback_span_id": playback["playback_span_id"],
    }


def _assert_mvp2_progress_truthfulness_gate(fixture: Mapping[str, Any], result: ReplayResult) -> dict[str, Any]:
    events = _events_by_name_mvp2(fixture)
    _require_mvp2_event_names(events, ["PROGRESS_TRUTHFULNESS_CHECK_PASSED", "PLAYBACK_SPAN_STARTED"])
    truthfulness = _find_event_mvp2(fixture, "PROGRESS_TRUTHFULNESS_CHECK_PASSED")
    playback = _find_event_mvp2(
        fixture,
        "PLAYBACK_SPAN_STARTED",
        approved_check_event_id=truthfulness["event_id"],
    )
    if playback.get("spoken_plan_id") != truthfulness.get("spoken_plan_id"):
        raise MVP2AcceptanceError("truthfulness-gated playback must reference matching spoken_plan_id")
    return {
        "truthfulness_pass_event_id": truthfulness["event_id"],
        "spoken_plan_id": truthfulness["spoken_plan_id"],
        "truthfulness_level": truthfulness["truthfulness_level"],
        "playback_span_id": playback["playback_span_id"],
    }


def _assert_mvp2_acceptance_scope_safety(
    fixtures: tuple[Mapping[str, Any], ...],
    results: tuple[ReplayResult, ...],
) -> dict[str, Any]:
    if not fixtures or len(fixtures) != len(results):
        raise MVP2AcceptanceError("scope safety scenario must cover all checked fixtures")
    for fixture, result in zip(fixtures, results, strict=True):
        assert_mvp2_fixture_is_repo_safe(fixture)
        if result.replay_mode != "deterministic" or result.fixture_domain != "GITHUB_ALLOWED":
            raise MVP2AcceptanceError("scope safety scenario requires deterministic GITHUB_ALLOWED fixtures")
    return {
        "fixture_count": len(fixtures),
        "replay_modes": sorted({result.replay_mode for result in results}),
        "fixture_domains": sorted({result.fixture_domain for result in results}),
        "unsafe_fixture_count": 0,
        "runtime_execution_detected": False,
    }


def _assert_mvp2_no_non_patch_demo_mutations(fixture: Mapping[str, Any]) -> None:
    for event in _required_sequence_mvp2(fixture, "events"):
        if not isinstance(event, Mapping):
            raise MVP2AcceptanceError("fixture events must be objects")
        event_name = str(event.get("event_name", ""))
        source_module = str(event.get("source_module", ""))
        if source_module in {"direct_frontend_mutator", "model_text_ui_driver"}:
            raise MVP2AcceptanceError("demo UI/backend mutation must not come from model text or frontend direct mutator")
        if event_name == "TOOL_RESULT_RECEIVED" and event.get("tool_name") != "webSearch":
            continue


def _mvp2_tool_name_for_call(fixture: Mapping[str, Any], tool_call_id: str) -> str | None:
    for event in _required_sequence_mvp2(fixture, "events"):
        if not isinstance(event, Mapping) or event.get("tool_call_id") != tool_call_id:
            continue
        tool_name = event.get("tool_name")
        if isinstance(tool_name, str) and tool_name:
            return tool_name
    return None


def _assert_mvp2_mock_degraded_real_labels(fixture: Mapping[str, Any]) -> None:
    for event in _required_sequence_mvp2(fixture, "events"):
        if not isinstance(event, Mapping):
            raise MVP2AcceptanceError("fixture events must be objects")
        event_name = str(event.get("event_name", ""))
        output_mode = event.get("output_mode")
        if output_mode is not None and output_mode not in MVP2_OUTPUT_MODES:
            raise MVP2AcceptanceError(f"{event_name} must not use real or unlabeled output_mode in MVP-2 acceptance")
        if event_name == "ADAPTER_CAPABILITY_SNAPSHOT_RECORDED":
            output_modes = event.get("output_modes", ())
            deployment_modes = event.get("deployment_modes", ())
            if not isinstance(output_modes, Sequence) or isinstance(output_modes, (str, bytes)):
                raise MVP2AcceptanceError("capability output_modes must be a list")
            if not isinstance(deployment_modes, Sequence) or isinstance(deployment_modes, (str, bytes)):
                raise MVP2AcceptanceError("capability deployment_modes must be a list")
            if not set(output_modes) <= MVP2_OUTPUT_MODES or not set(deployment_modes) <= MVP2_OUTPUT_MODES:
                raise MVP2AcceptanceError("MVP-2 capability modes must be mock/degraded/fallback and must not be real")
        capability = event.get("capability")
        if capability is not None and capability not in MVP2_OUTPUT_MODES:
            raise MVP2AcceptanceError("MVP-2 fixture tool capability must be mock/degraded/fallback")
        if str(event.get("execution_mode", "")).startswith("real"):
            raise MVP2AcceptanceError("MVP-2 acceptance must not claim real execution mode")


def _assert_mvp2_safe_string_fixture_value(value: str, key_path: str) -> None:
    lower_value = value.lower()
    if _contains_secret_like_value(value):
        raise MVP2AcceptanceError(f"forbidden secret-like fixture value: {key_path}")
    if any(lower_value.endswith(extension) for extension in RAW_AUDIO_EXTENSIONS):
        raise MVP2AcceptanceError(f"forbidden raw audio ref: {key_path}")
    forbidden_markers = (
        "audio/raw/",
        "traces/",
        "diagnostics/",
        "replays/local/",
        "raw trace",
        "raw audio",
        "raw transcript",
        "raw web",
        "large raw web",
        "real user",
        "access_token",
        "api_key",
        "authorization header",
        "cookie=",
    )
    if any(marker in lower_value for marker in forbidden_markers):
        raise MVP2AcceptanceError(f"forbidden local, raw, or secret marker: {key_path}")


def _events_by_name_mvp2(fixture: Mapping[str, Any]) -> dict[str, list[Mapping[str, Any]]]:
    events_by_name: dict[str, list[Mapping[str, Any]]] = {}
    for event in _required_sequence_mvp2(fixture, "events"):
        if not isinstance(event, Mapping):
            raise MVP2AcceptanceError("fixture events must be objects")
        events_by_name.setdefault(str(event["event_name"]), []).append(event)
    return events_by_name


def _require_mvp2_event_names(
    events_by_name: Mapping[str, Sequence[Mapping[str, Any]]],
    event_names: Sequence[str],
) -> None:
    missing = [event_name for event_name in event_names if event_name not in events_by_name]
    if missing:
        raise MVP2AcceptanceError(f"Missing expected MVP-2 scenario events: {missing}")


def _find_event_mvp2(fixture: Mapping[str, Any], event_name: str, **matches: object) -> Mapping[str, Any]:
    for event in _required_sequence_mvp2(fixture, "events"):
        if not isinstance(event, Mapping) or event.get("event_name") != event_name:
            continue
        if all(event.get(field) == expected for field, expected in matches.items()):
            return event
    raise MVP2AcceptanceError(f"Missing {event_name} event matching {matches}")


def _load_mvp2_fixture(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise MVP2AcceptanceError(f"Fixture not found: {path.name}")
    with path.open(encoding="utf-8") as fixture_file:
        loaded = json.load(fixture_file)
    if not isinstance(loaded, dict):
        raise MVP2AcceptanceError(f"Fixture must contain a JSON object: {path.name}")
    return loaded


def _required_mapping_mvp2(mapping: Mapping[str, Any], field: str) -> Mapping[str, Any]:
    value = mapping.get(field)
    if not isinstance(value, Mapping):
        raise MVP2AcceptanceError(f"{field} must be an object")
    return value


def _required_sequence_mvp2(mapping: Mapping[str, Any], field: str) -> Sequence[Any]:
    value = mapping.get(field)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise MVP2AcceptanceError(f"{field} must be a list")
    return value


def _required_str_mvp2(mapping: Mapping[str, Any], field: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value:
        raise MVP2AcceptanceError(f"{field} must be a non-empty string")
    return value


def _string_tuple_mvp2(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise MVP2AcceptanceError(f"{field} must be a list of strings")
    if not all(isinstance(item, str) and item for item in value):
        raise MVP2AcceptanceError(f"{field} must be a list of non-empty strings")
    return tuple(value)


def run_mvp3_acceptance_manifest(
    manifest_index: Mapping[str, Any],
    *,
    fixture_dir: Path,
    required_scenario_ids: Sequence[str] | None = None,
) -> MVP3AcceptanceResult:
    required_scenarios = tuple(required_scenario_ids or MVP3_REQUIRED_SCENARIOS)
    index = deepcopy(dict(manifest_index))
    _validate_mvp3_manifest_index(index, required_scenario_ids=required_scenarios)

    fixture_results: list[MVP3FixtureCheckResult] = []
    replay_results_by_fixture: dict[str, ReplayResult] = {}
    fixtures_by_name: dict[str, dict[str, Any]] = {}
    for fixture_name in _mvp3_fixture_check_names(index):
        fixture = _load_mvp3_fixture(fixture_dir / fixture_name)
        assert_mvp3_fixture_is_repo_safe(fixture)
        assert_fixture_has_no_forbidden_mvp3_scope(fixture["events"])
        assert_mvp3_fixture_has_explicit_output_modes(fixture)
        first_result = run_replay_fixture(fixture)
        second_result = run_replay_fixture(fixture)
        if first_result.state_digest != second_result.state_digest:
            raise MVP3AcceptanceError(f"{fixture_name} replay is not deterministic")
        _assert_mvp3_replay_matches_suite(index, fixture_name=fixture_name, result=first_result)
        _assert_mvp3_replay_state_surface(first_result, fixture_name=fixture_name)
        fixtures_by_name[fixture_name] = fixture
        replay_results_by_fixture[fixture_name] = first_result
        fixture_results.append(
            MVP3FixtureCheckResult(
                fixture_name=fixture_name,
                result_status=first_result.result_status,
                state_digest=first_result.state_digest,
            )
        )

    scenario_entries = _mvp3_scenario_entries_by_id(index)
    scenario_results: list[MVP3ScenarioResult] = []
    for scenario_id in required_scenarios:
        scenario = scenario_entries[scenario_id]
        fixture_names = _mvp3_scenario_fixture_names(scenario)
        fixtures = tuple(fixtures_by_name[name] for name in fixture_names)
        replay_results = tuple(replay_results_by_fixture[name] for name in fixture_names)
        assertion_summary = _assert_mvp3_scenario(
            scenario_id,
            fixtures=fixtures,
            results=replay_results,
        )
        scenario_results.append(
            MVP3ScenarioResult(
                scenario_id=scenario_id,
                fixture_names=fixture_names,
                result_status="passed",
                assertion_summary=assertion_summary,
                state_digest=replay_results[-1].state_digest,
            )
        )

    return MVP3AcceptanceResult(
        scenario_results=tuple(scenario_results),
        fixture_results=tuple(fixture_results),
        summary={
            "suite_id": str(index["suite_id"]),
            "result_status": "passed",
            "scenario_count": len(scenario_results),
            "fixture_count": len(fixture_results),
            "validated_fixture_names": [fixture.fixture_name for fixture in fixture_results],
            "deterministic_replay_verified": True,
            "runtime_execution_detected": False,
            "provider_execution_detected": False,
            "adapter_health_digest_verified": _mvp3_adapter_health_digest_verified(
                replay_results_by_fixture.values()
            ),
            "fallback_degraded_contract_verified": any(
                scenario.scenario_id == "MVP3-FALLBACK-DEGRADED-REPLAY-001"
                for scenario in scenario_results
            ),
            "adr_update_required": False,
            "hidden_future_scope_detected": False,
        },
    )


def assert_mvp3_fixture_is_repo_safe(fixture: Mapping[str, Any]) -> None:
    try:
        manifest = _required_mapping_mvp3(fixture, "replay_manifest")
        if manifest.get("fixture_domain") != "GITHUB_ALLOWED":
            raise MVP3AcceptanceError("fixture_domain must be GITHUB_ALLOWED")
        if manifest.get("replay_mode") != "deterministic":
            raise MVP3AcceptanceError("MVP-3 fixtures must use deterministic replay")
        if manifest.get("generated_from") not in {"synthetic", "redacted", "hand_written_minimal"}:
            raise MVP3AcceptanceError("GitHub fixtures must be synthetic, redacted, or hand_written_minimal")
        if manifest.get("allowed_re_eval_components", []) != []:
            raise MVP3AcceptanceError("deterministic MVP-3 fixtures must not opt into re-eval components")
        if any(manifest.get(flag) is not False for flag in ALLOWED_MANIFEST_SAFETY_FLAGS):
            raise MVP3AcceptanceError("GitHub fixture safety flags must all be false")

        for path, value in _iter_json_values(fixture):
            last_key = path[-1] if path else ""
            if path[:1] == ("replay_manifest",) and last_key in ALLOWED_MANIFEST_SAFETY_FLAGS:
                if value is not False:
                    raise MVP3AcceptanceError(f"unsafe manifest safety flag: {'.'.join(path)}")
                continue
            if last_key in ALLOWED_SAFE_SECRET_METADATA_KEYS:
                if not isinstance(value, str) or _contains_secret_like_value(value):
                    raise MVP3AcceptanceError(f"unsafe secret metadata: {'.'.join(path)}")
                _assert_mvp3_safe_string_fixture_value(value, ".".join(path))
                continue
            if last_key in ALLOWED_SAFE_REF_KEYS:
                if not isinstance(value, str) or not is_safe_authorization_ref(value, allow_local=False):
                    raise MVP3AcceptanceError(f"unsafe authorization ref: {'.'.join(path)}")
                _assert_mvp3_safe_string_fixture_value(value, ".".join(path))
                continue
            if any(pattern.search(last_key) for pattern in MVP3_FORBIDDEN_FIXTURE_KEY_PATTERNS):
                raise MVP3AcceptanceError(f"forbidden MVP-3 raw/provider payload key: {'.'.join(path)}")
            if any(pattern.search(last_key) for pattern in FORBIDDEN_FIXTURE_KEY_PATTERNS):
                raise MVP3AcceptanceError(f"forbidden fixture key: {'.'.join(path)}")
            if isinstance(value, str):
                _assert_mvp3_safe_string_fixture_value(value, ".".join(path))
    except MVP3AcceptanceError as exc:
        raise MVP3AcceptanceError(f"repo-unsafe MVP-3 fixture content: {exc}") from exc


def assert_fixture_has_no_forbidden_mvp3_scope(events: Sequence[Mapping[str, Any]]) -> None:
    for event in events:
        event_name = str(event.get("event_name", ""))
        source_module = str(event.get("source_module", ""))
        if event_name in MVP3_FORBIDDEN_EVENT_NAMES:
            raise MVP3AcceptanceError(f"forbidden MVP-3 event_name: {event_name}")
        if _is_forbidden_mvp3_source_module(source_module):
            raise MVP3AcceptanceError(f"forbidden MVP-3 source_module: {source_module}")


def assert_mvp3_fixture_has_explicit_output_modes(fixture: Mapping[str, Any]) -> None:
    for event in _required_sequence_mvp3(fixture, "events"):
        if not isinstance(event, Mapping):
            raise MVP3AcceptanceError("fixture events must be objects")
        event_name = str(event.get("event_name", ""))
        output_mode = event.get("output_mode")
        if event_name in MVP3_ADAPTER_OUTPUT_MODE_REQUIRED_EVENT_NAMES:
            if output_mode not in MVP3_OUTPUT_MODES:
                raise MVP3AcceptanceError(
                    f"{event_name} must declare output_mode=real, fallback, or degraded"
                )
        elif output_mode is not None and output_mode not in MVP3_ALL_OUTPUT_MODES:
            raise MVP3AcceptanceError(f"{event_name} uses unsupported output_mode: {output_mode}")

        if event_name == "ADAPTER_CAPABILITY_SNAPSHOT_RECORDED":
            output_modes = _string_tuple_mvp3(event.get("output_modes", ()), "output_modes")
            deployment_modes = _string_tuple_mvp3(event.get("deployment_modes", ()), "deployment_modes")
            if not output_modes:
                raise MVP3AcceptanceError("capability snapshot must declare output_modes")
            if set(output_modes) - MVP3_OUTPUT_MODES:
                raise MVP3AcceptanceError("MVP-3 capability output_modes must be real/fallback/degraded")
            if "mock" in deployment_modes:
                raise MVP3AcceptanceError("MVP-3 capability deployment_modes must not be mock")
        if str(event.get("execution_mode", "")).startswith(("real_provider", "provider")):
            raise MVP3AcceptanceError("MVP-3 acceptance must not claim direct provider execution")


def _validate_mvp3_manifest_index(
    index: Mapping[str, Any],
    *,
    required_scenario_ids: tuple[str, ...],
) -> None:
    required_fields = {
        "manifest_index_schema_version",
        "suite_id",
        "fixture_domain",
        "replay_mode",
        "scope",
        "generated_fixtures_must_be",
        "required_scenarios",
        "forbidden_behaviors",
        "required_replay_properties",
        "fixture_checks",
        "scenarios",
    }
    missing = required_fields - set(index)
    if missing:
        raise MVP3AcceptanceError(f"Missing MVP-3 acceptance manifest fields: {sorted(missing)}")
    if index["manifest_index_schema_version"] != "1.0":
        raise MVP3AcceptanceError("manifest_index_schema_version must be '1.0'")
    if index["suite_id"] != "MVP3-ACCEPTANCE":
        raise MVP3AcceptanceError("suite_id must be 'MVP3-ACCEPTANCE'")
    if index["fixture_domain"] != "GITHUB_ALLOWED":
        raise MVP3AcceptanceError("MVP-3 acceptance fixtures must be GITHUB_ALLOWED")
    if index["replay_mode"] != "deterministic":
        raise MVP3AcceptanceError("MVP-3 acceptance uses deterministic replay")

    generated_requirements = _string_tuple_mvp3(
        index["generated_fixtures_must_be"],
        "generated_fixtures_must_be",
    )
    if generated_requirements != ("synthetic", "redacted", "minimal"):
        raise MVP3AcceptanceError("generated_fixtures_must_be must be synthetic/redacted/minimal")

    required_scenarios = _string_tuple_mvp3(index["required_scenarios"], "required_scenarios")
    if required_scenarios != required_scenario_ids:
        raise MVP3AcceptanceError(f"required_scenarios must be {list(required_scenario_ids)}")

    _assert_mvp3_scope_text_does_not_broaden(str(index["scope"]))
    _validate_mvp3_scope_gate_lists(index)

    scenario_entries = _mvp3_scenario_entries_by_id(index)
    missing_scenarios = [scenario_id for scenario_id in required_scenarios if scenario_id not in scenario_entries]
    if missing_scenarios:
        raise MVP3AcceptanceError(f"Missing scenario entries: {missing_scenarios}")
    fixture_check_names = set(_mvp3_fixture_check_names(index))
    missing_fixture_checks = sorted(
        {
            fixture_name
            for scenario in scenario_entries.values()
            for fixture_name in _mvp3_scenario_fixture_names(scenario)
            if fixture_name not in fixture_check_names
        }
    )
    if missing_fixture_checks:
        raise MVP3AcceptanceError(f"scenario fixtures must be listed in fixture_checks: {missing_fixture_checks}")


def _validate_mvp3_scope_gate_lists(index: Mapping[str, Any]) -> None:
    forbidden_behaviors = set(_string_tuple_mvp3(index["forbidden_behaviors"], "forbidden_behaviors"))
    missing_behaviors = sorted(MVP3_REQUIRED_FORBIDDEN_BEHAVIORS - forbidden_behaviors)
    if missing_behaviors:
        raise MVP3AcceptanceError(f"forbidden_behaviors missing MVP-3 scope gates: {missing_behaviors}")

    replay_properties = set(
        _string_tuple_mvp3(index["required_replay_properties"], "required_replay_properties")
    )
    missing_properties = sorted(MVP3_REQUIRED_REPLAY_PROPERTIES - replay_properties)
    if missing_properties:
        raise MVP3AcceptanceError(f"required_replay_properties missing scope gates: {missing_properties}")


def _mvp3_fixture_check_names(index: Mapping[str, Any]) -> tuple[str, ...]:
    checks = _required_sequence_mvp3(index, "fixture_checks")
    names: list[str] = []
    for check in checks:
        if not isinstance(check, Mapping) or not isinstance(check.get("fixture"), str):
            raise MVP3AcceptanceError("fixture_checks entries must contain fixture")
        names.append(str(check["fixture"]))
    if len(names) != len(set(names)):
        raise MVP3AcceptanceError("fixture_checks must not contain duplicate fixtures")
    return tuple(names)


def _mvp3_scenario_entries_by_id(index: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    scenarios = _required_sequence_mvp3(index, "scenarios")
    entries: dict[str, Mapping[str, Any]] = {}
    for scenario in scenarios:
        if not isinstance(scenario, Mapping):
            raise MVP3AcceptanceError("scenarios entries must be objects")
        scenario_id = scenario.get("scenario_id")
        if not isinstance(scenario_id, str) or not scenario_id:
            raise MVP3AcceptanceError("scenario entry must include scenario_id")
        _mvp3_scenario_fixture_names(scenario)
        if scenario_id in entries:
            raise MVP3AcceptanceError(f"duplicate scenario_id: {scenario_id}")
        entries[scenario_id] = scenario
    return entries


def _mvp3_scenario_fixture_names(scenario: Mapping[str, Any]) -> tuple[str, ...]:
    if "fixtures" in scenario:
        fixture_names = _string_tuple_mvp3(scenario["fixtures"], "fixtures")
    else:
        fixture = scenario.get("fixture")
        if not isinstance(fixture, str):
            raise MVP3AcceptanceError("scenario entry must include fixture or fixtures")
        fixture_names = (fixture,)
    if not fixture_names or not all(name.endswith(".fixture.json") for name in fixture_names):
        raise MVP3AcceptanceError("scenario fixtures must be .fixture.json files")
    return fixture_names


def _assert_mvp3_replay_matches_suite(
    index: Mapping[str, Any],
    *,
    fixture_name: str,
    result: ReplayResult,
) -> None:
    if result.fixture_domain != index["fixture_domain"]:
        raise MVP3AcceptanceError(f"{fixture_name} fixture_domain mismatch")
    if result.replay_mode != index["replay_mode"]:
        raise MVP3AcceptanceError(f"{fixture_name} replay_mode mismatch")
    if result.result_status != "passed":
        raise MVP3AcceptanceError(f"{fixture_name} replay did not pass")
    if result.diagnostics["ignored_events"]:
        raise MVP3AcceptanceError(f"{fixture_name} replay ignored MVP-3 events")


def _assert_mvp3_replay_state_surface(result: ReplayResult, *, fixture_name: str) -> None:
    required_digest_fields = {
        "adapter_health_state_hash",
        "trace_privacy_state_hash",
        "slowtask_state_hash",
        "overall_digest",
    }
    missing = sorted(required_digest_fields - set(result.state_digest))
    if missing:
        raise MVP3AcceptanceError(f"{fixture_name} state digest missing fields: {missing}")
    unsafe_flags = {
        "contains_raw_audio": result.trace_privacy_state.contains_raw_audio,
        "contains_raw_trace": result.trace_privacy_state.contains_raw_trace,
        "contains_real_user_input": result.trace_privacy_state.contains_real_user_input,
        "contains_secrets": result.trace_privacy_state.contains_secrets,
        "contains_unredacted_tool_result": result.trace_privacy_state.contains_unredacted_tool_result,
        "contains_large_raw_web_content": result.trace_privacy_state.contains_large_raw_web_content,
    }
    if any(value is not False for value in unsafe_flags.values()):
        raise MVP3AcceptanceError(f"{fixture_name} replayed unsafe fixture flags: {unsafe_flags}")


def _assert_mvp3_scenario(
    scenario_id: str,
    *,
    fixtures: tuple[Mapping[str, Any], ...],
    results: tuple[ReplayResult, ...],
) -> dict[str, Any]:
    if scenario_id == "MVP3-FIXTURE-SAFETY-001":
        return _assert_mvp3_fixture_safety(fixtures[0], results[0])
    if scenario_id == "MVP3-ADAPTER-PROFILE-001":
        return _assert_mvp3_adapter_profile(fixtures[0], results[0])
    if scenario_id == "MVP3-ADAPTER-EVENT-HARNESS-001":
        return _assert_mvp3_adapter_event_harness(fixtures[0], results[0])
    if scenario_id == "MVP3-RUNTIME-ASSEMBLY-001":
        return _assert_mvp3_runtime_assembly(fixtures[0], results[0])
    if scenario_id == "MVP3-ASR-CONTRACT-001":
        return _assert_mvp3_asr_contract(fixtures[0], results[0])
    if scenario_id == "MVP3-THINKER-CONTRACT-001":
        return _assert_mvp3_thinker_contract(fixtures[0], results[0])
    if scenario_id == "MVP3-SLOW-LLM-STRUCTURED-001":
        return _assert_mvp3_slow_llm_contract(fixtures[0], results[0])
    if scenario_id == "MVP3-TTS-CONTRACT-001":
        return _assert_mvp3_tts_contract(fixtures[0], results[0])
    if scenario_id == "MVP3-FALLBACK-DEGRADED-REPLAY-001":
        return _assert_mvp3_fallback_degraded_replay(fixtures[0], results[0])
    if scenario_id == "MVP3-ACCEPTANCE-SCOPE-SAFETY-001":
        return _assert_mvp3_acceptance_scope_safety(fixtures, results)
    raise MVP3AcceptanceError(f"Unknown MVP-3 acceptance scenario: {scenario_id}")


def _assert_mvp3_fixture_safety(fixture: Mapping[str, Any], result: ReplayResult) -> dict[str, Any]:
    assert_mvp3_fixture_is_repo_safe(fixture)
    if _required_sequence_mvp3(fixture, "events"):
        raise MVP3AcceptanceError("fixture safety scenario must use the empty MVP-3 fixture")
    if result.ordered_events:
        raise MVP3AcceptanceError("empty MVP-3 fixture must replay without source events")
    return {
        "fixture_domain": result.fixture_domain,
        "replay_mode": result.replay_mode,
        "event_count": len(result.ordered_events),
        "unsafe_fixture_count": 0,
        "runtime_execution_detected": False,
    }


def _assert_mvp3_adapter_profile(fixture: Mapping[str, Any], result: ReplayResult) -> dict[str, Any]:
    events = _events_by_name_mvp3(fixture)
    _require_mvp3_event_names(events, ["ADAPTER_CAPABILITY_SNAPSHOT_RECORDED"])
    snapshot = events["ADAPTER_CAPABILITY_SNAPSHOT_RECORDED"][0]
    adapter_types = tuple(str(value) for value in snapshot["adapter_types"])
    output_modes = tuple(str(value) for value in snapshot["output_modes"])
    deployment_modes = tuple(str(value) for value in snapshot["deployment_modes"])
    if set(adapter_types) != {"asr", "thinker", "slow_llm", "tts"}:
        raise MVP3AcceptanceError("MVP-3 profile scenario must cover ASR, Thinker, Slow LLM, and TTS")
    if set(output_modes) - MVP3_OUTPUT_MODES:
        raise MVP3AcceptanceError("MVP-3 profile output modes must be real/fallback/degraded")
    if "mock" in deployment_modes:
        raise MVP3AcceptanceError("MVP-3 profile scenario must not use mock deployment mode")
    if snapshot.get("capability_version") in (None, ""):
        raise MVP3AcceptanceError("MVP-3 profile scenario must record capability_version")
    if not result.adapter_health_state.adapters:
        raise MVP3AcceptanceError("MVP-3 profile scenario must replay adapter health records")
    return {
        "adapter_ids": list(snapshot["adapter_ids"]),
        "adapter_types": list(adapter_types),
        "deployment_modes": list(deployment_modes),
        "output_modes": list(output_modes),
        "capability_version": snapshot["capability_version"],
    }


def _assert_mvp3_adapter_event_harness(fixture: Mapping[str, Any], result: ReplayResult) -> dict[str, Any]:
    events = _events_by_name_mvp3(fixture)
    _require_mvp3_event_names(
        events,
        [
            "ADAPTER_REQUEST_RETRYING",
            "ADAPTER_REQUEST_FAILED",
            "ADAPTER_OUTPUT_VALIDATION_FAILED",
            "ADAPTER_OUTPUT_DEGRADED",
        ],
    )
    adapters = result.adapter_health_state.adapters
    slow_llm = adapters.get("mvp3_slice8_slow_llm")
    tts = adapters.get("mvp3_slice8_tts")
    if slow_llm is None or tts is None:
        raise MVP3AcceptanceError("adapter event harness scenario must replay slow_llm and tts adapter records")
    if slow_llm.retry_count < 1 or slow_llm.failure_count < 2:
        raise MVP3AcceptanceError("adapter event harness must expose retry and failure counts")
    if not tts.missing_capabilities:
        raise MVP3AcceptanceError("adapter event harness must expose missing_capabilities")
    return {
        "retry_event_count": len(events["ADAPTER_REQUEST_RETRYING"]),
        "failure_event_count": len(events["ADAPTER_REQUEST_FAILED"])
        + len(events["ADAPTER_OUTPUT_VALIDATION_FAILED"]),
        "degraded_event_count": len(events["ADAPTER_OUTPUT_DEGRADED"]),
        "slow_llm_retry_count": slow_llm.retry_count,
        "slow_llm_failure_count": slow_llm.failure_count,
        "tts_missing_capabilities": list(tts.missing_capabilities),
    }


def _assert_mvp3_runtime_assembly(fixture: Mapping[str, Any], result: ReplayResult) -> dict[str, Any]:
    events = _events_by_name_mvp3(fixture)
    _require_mvp3_event_names(events, ["SESSION_STARTED", "ADAPTER_CAPABILITY_SNAPSHOT_RECORDED"])
    started = events["SESSION_STARTED"][0]
    snapshot = events["ADAPTER_CAPABILITY_SNAPSHOT_RECORDED"][0]
    if snapshot.get("caused_by_event_id") != started["event_id"]:
        raise MVP3AcceptanceError("runtime assembly snapshot must be caused by SESSION_STARTED")
    if result.adapter_health_state.capability_snapshot_ref != snapshot["capability_snapshot_ref"]:
        raise MVP3AcceptanceError("runtime assembly must replay capability_snapshot_ref")
    return {
        "capability_snapshot_ref": snapshot["capability_snapshot_ref"],
        "adapter_ids": list(snapshot["adapter_ids"]),
        "adapter_types": list(snapshot["adapter_types"]),
        "deployment_modes": list(snapshot["deployment_modes"]),
        "output_modes": list(snapshot["output_modes"]),
        "capability_version": snapshot["capability_version"],
    }


def _assert_mvp3_asr_contract(fixture: Mapping[str, Any], result: ReplayResult) -> dict[str, Any]:
    event = _find_event_mvp3(fixture, "ASR_TRANSCRIPT_OUTPUT_EMITTED")
    if event.get("output_mode") not in MVP3_OUTPUT_MODES:
        raise MVP3AcceptanceError("ASR contract output_mode must be real/fallback/degraded")
    if event.get("timestamp_status") not in {"available", "unavailable"}:
        raise MVP3AcceptanceError("ASR contract must label timestamp_status")
    if event.get("streaming_status") not in {"supported", "unsupported", "unavailable"}:
        raise MVP3AcceptanceError("ASR contract must label streaming_status")
    if result.adapter_health_state.output_event_modes.get(str(event["event_id"])) != event["output_mode"]:
        raise MVP3AcceptanceError("ASR output mode must appear in adapter health digest")
    return {
        "event_id": event["event_id"],
        "adapter_id": event["adapter_id"],
        "output_mode": event["output_mode"],
        "timestamp_status": event["timestamp_status"],
        "streaming_status": event["streaming_status"],
    }


def _assert_mvp3_thinker_contract(fixture: Mapping[str, Any], result: ReplayResult) -> dict[str, Any]:
    event = _find_event_mvp3(fixture, "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED")
    if event.get("normalization_status") != "normalized":
        raise MVP3AcceptanceError("Thinker contract output must be normalized")
    status_fields = (
        "semantic_close_status",
        "assistant_directedness_status",
        "emotion_status",
        "audio_caption_status",
    )
    unavailable_fields = [field for field in status_fields if event.get(field) == "unavailable"]
    if result.adapter_health_state.output_event_modes.get(str(event["event_id"])) != event["output_mode"]:
        raise MVP3AcceptanceError("Thinker output mode must appear in adapter health digest")
    router = _find_event_mvp3(fixture, "ROUTER_DECISION_EMITTED")
    if router.get("thinker_frame_event_id") != event["event_id"]:
        raise MVP3AcceptanceError("Router must consume the normalized Thinker output event")
    return {
        "event_id": event["event_id"],
        "adapter_id": event["adapter_id"],
        "output_mode": event["output_mode"],
        "normalization_status": event["normalization_status"],
        "unavailable_optional_fields": unavailable_fields,
    }


def _assert_mvp3_slow_llm_contract(fixture: Mapping[str, Any], result: ReplayResult) -> dict[str, Any]:
    events = _events_by_name_mvp3(fixture)
    _require_mvp3_event_names(
        events,
        [
            "ADAPTER_OUTPUT_VALIDATION_FAILED",
            "ADAPTER_OUTPUT_DEGRADED",
            "SLOW_LLM_STRUCTURED_OUTPUT_EMITTED",
            "PLAN_VERSION_ADVANCED",
        ],
    )
    output = events["SLOW_LLM_STRUCTURED_OUTPUT_EMITTED"][0]
    if output.get("normalization_status") != "normalized":
        raise MVP3AcceptanceError("Slow LLM structured output must be normalized")
    if output.get("schema_name") != "voice_agent.slowtask.structured_output.v1":
        raise MVP3AcceptanceError("Slow LLM structured output must use the MVP-3 schema")
    task = result.slowtask_state.tasks[str(output["task_id"])]
    if task.current_plan_version <= int(output["plan_version"]):
        raise MVP3AcceptanceError("old-plan Slow LLM output must not advance current task state")
    if task.resolved_arguments_refs or task.argument_provenance_refs:
        raise MVP3AcceptanceError("old-plan Slow LLM output must remain stale evidence without adoption")
    return {
        "output_event_id": output["event_id"],
        "output_mode": output["output_mode"],
        "output_plan_version": output["plan_version"],
        "current_plan_version": task.current_plan_version,
        "validation_failed_count": len(events["ADAPTER_OUTPUT_VALIDATION_FAILED"]),
        "resolved_arguments_refs": list(task.resolved_arguments_refs),
    }


def _assert_mvp3_tts_contract(fixture: Mapping[str, Any], result: ReplayResult) -> dict[str, Any]:
    tts = _find_event_mvp3(fixture, "TTS_SYNTHESIS_OUTPUT_EMITTED")
    degraded = _find_event_mvp3(fixture, "ADAPTER_OUTPUT_DEGRADED", adapter_id=tts["adapter_id"])
    if tts.get("normalization_status") != "normalized":
        raise MVP3AcceptanceError("TTS output must be normalized")
    if tts.get("truncate_status") == "unsupported_blocked":
        if degraded.get("missing_capability") != "supports_tts_truncate":
            raise MVP3AcceptanceError("unsupported TTS truncate must pair with missing capability degradation")
    audio_ref = str(tts.get("audio_ref") or tts.get("tts_stream_ref") or "")
    _assert_mvp3_safe_string_fixture_value(audio_ref, "tts.audio_ref")
    if result.adapter_health_state.output_event_modes.get(str(tts["event_id"])) != tts["output_mode"]:
        raise MVP3AcceptanceError("TTS output mode must appear in adapter health digest")
    return {
        "event_id": tts["event_id"],
        "adapter_id": tts["adapter_id"],
        "output_mode": tts["output_mode"],
        "truncate_status": tts["truncate_status"],
        "missing_capability": degraded.get("missing_capability"),
    }


def _assert_mvp3_fallback_degraded_replay(
    fixture: Mapping[str, Any],
    result: ReplayResult,
) -> dict[str, Any]:
    expected_output_modes = {
        "evt_mvp3_slice8_asr_real_output": "real",
        "evt_mvp3_slice8_thinker_fallback_output": "fallback",
        "evt_mvp3_slice8_slow_llm_fallback_output": "fallback",
        "evt_mvp3_slice8_tts_degraded_output": "degraded",
    }
    if result.adapter_health_state.output_event_modes != expected_output_modes:
        raise MVP3AcceptanceError("fallback/degraded replay must distinguish output modes")
    if result.diagnostics["adapter_outcomes"]["output_event_modes"] != expected_output_modes:
        raise MVP3AcceptanceError("fallback/degraded diagnostics must expose output modes")
    adapters = result.adapter_health_state.adapters
    slow_llm = adapters["mvp3_slice8_slow_llm"]
    tts = adapters["mvp3_slice8_tts"]
    if slow_llm.retry_count != 1 or slow_llm.failure_count != 2:
        raise MVP3AcceptanceError("fallback/degraded replay must expose retry_count and failure_count")
    if slow_llm.latest_degradation_reason != "fallback_after_validation_failure":
        raise MVP3AcceptanceError("fallback/degraded replay must expose latest_degradation_reason")
    if tts.missing_capabilities != ("supports_tts_truncate",):
        raise MVP3AcceptanceError("fallback/degraded replay must expose missing_capabilities")
    task = result.slowtask_state.tasks["task_mvp3_slice8"]
    if task.current_plan_version != 2 or task.resolved_arguments_refs or task.argument_provenance_refs:
        raise MVP3AcceptanceError("old-plan adapter output must not advance current task state")
    return {
        "output_event_modes": expected_output_modes,
        "slow_llm_retry_count": slow_llm.retry_count,
        "slow_llm_failure_count": slow_llm.failure_count,
        "slow_llm_latest_degradation_reason": slow_llm.latest_degradation_reason,
        "tts_missing_capabilities": list(tts.missing_capabilities),
        "current_plan_version": task.current_plan_version,
    }


def _assert_mvp3_acceptance_scope_safety(
    fixtures: tuple[Mapping[str, Any], ...],
    results: tuple[ReplayResult, ...],
) -> dict[str, Any]:
    if not fixtures or len(fixtures) != len(results):
        raise MVP3AcceptanceError("scope safety scenario must cover all checked fixtures")
    for fixture, result in zip(fixtures, results, strict=True):
        assert_mvp3_fixture_is_repo_safe(fixture)
        assert_fixture_has_no_forbidden_mvp3_scope(fixture["events"])
        assert_mvp3_fixture_has_explicit_output_modes(fixture)
        if result.replay_mode != "deterministic" or result.fixture_domain != "GITHUB_ALLOWED":
            raise MVP3AcceptanceError("scope safety scenario requires deterministic GITHUB_ALLOWED fixtures")
    return {
        "fixture_count": len(fixtures),
        "replay_modes": sorted({result.replay_mode for result in results}),
        "fixture_domains": sorted({result.fixture_domain for result in results}),
        "unsafe_fixture_count": 0,
        "runtime_execution_detected": False,
        "provider_execution_detected": False,
    }


def _mvp3_adapter_health_digest_verified(results: Sequence[ReplayResult]) -> bool:
    for result in results:
        adapters = result.adapter_health_state.adapters
        if not adapters:
            continue
        digest = result.diagnostics.get("adapter_outcomes", {})
        if digest != result.adapter_health_state.to_digest_dict():
            return False
        required_fields = {
            "output_mode",
            "retry_count",
            "failure_count",
            "missing_capabilities",
            "latest_degradation_reason",
        }
        for adapter in digest.get("adapters", {}).values():
            if not required_fields <= set(adapter):
                return False
        if {"real", "fallback", "degraded"} <= set(result.adapter_health_state.output_event_modes.values()):
            return True
    return False


def _events_by_name_mvp3(fixture: Mapping[str, Any]) -> dict[str, list[Mapping[str, Any]]]:
    events_by_name: dict[str, list[Mapping[str, Any]]] = {}
    for event in _required_sequence_mvp3(fixture, "events"):
        if not isinstance(event, Mapping):
            raise MVP3AcceptanceError("fixture events must be objects")
        events_by_name.setdefault(str(event["event_name"]), []).append(event)
    return events_by_name


def _require_mvp3_event_names(
    events_by_name: Mapping[str, Sequence[Mapping[str, Any]]],
    event_names: Sequence[str],
) -> None:
    missing = [event_name for event_name in event_names if event_name not in events_by_name]
    if missing:
        raise MVP3AcceptanceError(f"Missing expected MVP-3 scenario events: {missing}")


def _find_event_mvp3(fixture: Mapping[str, Any], event_name: str, **matches: object) -> Mapping[str, Any]:
    for event in _required_sequence_mvp3(fixture, "events"):
        if not isinstance(event, Mapping) or event.get("event_name") != event_name:
            continue
        if all(event.get(field) == expected for field, expected in matches.items()):
            return event
    raise MVP3AcceptanceError(f"Missing {event_name} event matching {matches}")


def _assert_mvp3_scope_text_does_not_broaden(scope: str) -> None:
    lower_scope = scope.lower()
    for marker in MVP3_FORBIDDEN_SCOPE_MARKERS:
        if marker in lower_scope:
            raise MVP3AcceptanceError(f"MVP-3 manifest scope broadens into forbidden area: {marker}")
    if "adapter" not in lower_scope or "existing adapter boundaries" not in lower_scope:
        raise MVP3AcceptanceError("MVP-3 manifest scope must stay inside existing adapter boundaries")


def _is_forbidden_mvp3_source_module(source_module: str) -> bool:
    return any(
        source_module == forbidden or source_module.startswith(f"{forbidden}.")
        for forbidden in MVP3_FORBIDDEN_SOURCE_MODULES
    )


def _assert_mvp3_safe_string_fixture_value(value: str, key_path: str) -> None:
    lower_values = _mvp3_lower_and_decoded_values(value)
    if _contains_secret_like_value(value):
        raise MVP3AcceptanceError(f"forbidden secret-like fixture value: {key_path}")
    if any(lower_value.endswith(extension) for lower_value in lower_values for extension in RAW_AUDIO_EXTENSIONS):
        raise MVP3AcceptanceError(f"forbidden raw audio ref: {key_path}")
    if any(
        lower_value.startswith(marker) or marker in lower_value
        for lower_value in lower_values
        for marker in MVP3_DIRECT_PROVIDER_MARKERS
    ):
        raise MVP3AcceptanceError(f"forbidden direct provider or network ref: {key_path}")
    forbidden_markers = (
        "audio/raw/",
        "traces/",
        "diagnostics/",
        "replays/local/",
        "raw trace",
        "raw audio",
        "raw transcript",
        "raw web",
        "large raw web",
        "real user",
        "access_token",
        "api_key",
        "authorization header",
        "cookie=",
        "bearer ",
        "provider payload",
        "provider_payload",
        "provider schema",
        "provider_schema",
    )
    if any(marker in lower_value for lower_value in lower_values for marker in forbidden_markers):
        raise MVP3AcceptanceError(f"forbidden local, raw, provider, or secret marker: {key_path}")


def _mvp3_lower_and_decoded_values(value: str) -> tuple[str, ...]:
    values = [value]
    decoded = value
    for _ in range(3):
        next_decoded = unquote(decoded)
        if next_decoded == decoded:
            break
        values.append(next_decoded)
        decoded = next_decoded
    return tuple(dict.fromkeys(item.lower() for item in values))


def _load_mvp3_fixture(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise MVP3AcceptanceError(f"Fixture not found: {path.name}")
    with path.open(encoding="utf-8") as fixture_file:
        loaded = json.load(fixture_file)
    if not isinstance(loaded, dict):
        raise MVP3AcceptanceError(f"Fixture must contain a JSON object: {path.name}")
    return loaded


def _required_mapping_mvp3(mapping: Mapping[str, Any], field: str) -> Mapping[str, Any]:
    value = mapping.get(field)
    if not isinstance(value, Mapping):
        raise MVP3AcceptanceError(f"{field} must be an object")
    return value


def _required_sequence_mvp3(mapping: Mapping[str, Any], field: str) -> Sequence[Any]:
    value = mapping.get(field)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise MVP3AcceptanceError(f"{field} must be a list")
    return value


def _string_tuple_mvp3(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise MVP3AcceptanceError(f"{field} must be a list of strings")
    if not all(isinstance(item, str) and item for item in value):
        raise MVP3AcceptanceError(f"{field} must be a list of non-empty strings")
    return tuple(value)


def _validate_mvp1_manifest_index(index: Mapping[str, Any]) -> None:
    required_fields = {
        "manifest_index_schema_version",
        "suite_id",
        "fixture_domain",
        "replay_mode",
        "required_scenarios",
        "fixture_checks",
        "scenarios",
        "synthetic_eval_table",
    }
    missing = required_fields - set(index)
    if missing:
        raise MVP1AcceptanceError(f"Missing MVP-1 acceptance manifest fields: {sorted(missing)}")
    if index["manifest_index_schema_version"] != "1.0":
        raise MVP1AcceptanceError("manifest_index_schema_version must be '1.0'")
    if index["suite_id"] != "MVP1-ACCEPTANCE":
        raise MVP1AcceptanceError("suite_id must be 'MVP1-ACCEPTANCE'")
    if index["fixture_domain"] != "GITHUB_ALLOWED":
        raise MVP1AcceptanceError("MVP-1 acceptance fixtures must be GITHUB_ALLOWED")
    if index["replay_mode"] != "deterministic":
        raise MVP1AcceptanceError("MVP-1 acceptance uses deterministic replay")

    required_scenarios = _string_tuple_mvp1(index["required_scenarios"], "required_scenarios")
    if required_scenarios != MVP1_REQUIRED_SCENARIOS:
        raise MVP1AcceptanceError(f"required_scenarios must be {list(MVP1_REQUIRED_SCENARIOS)}")

    forbidden_event_names = set(_string_tuple_mvp1(index.get("forbidden_event_names", ()), "forbidden_event_names"))
    missing_forbidden = sorted(MVP1_FORBIDDEN_EVENT_NAMES - forbidden_event_names)
    if missing_forbidden:
        raise MVP1AcceptanceError(f"forbidden_event_names missing MVP-2 scope gates: {missing_forbidden}")
    forbidden_source_modules = set(
        _string_tuple_mvp1(index.get("forbidden_source_modules", ()), "forbidden_source_modules")
    )
    missing_source_modules = sorted(MVP1_FORBIDDEN_SOURCE_MODULES - forbidden_source_modules)
    if missing_source_modules:
        raise MVP1AcceptanceError(
            f"forbidden_source_modules missing MVP-2 scope gates: {missing_source_modules}"
        )

    scenario_entries = _mvp1_scenario_entries_by_id(index)
    missing_scenarios = [scenario_id for scenario_id in required_scenarios if scenario_id not in scenario_entries]
    if missing_scenarios:
        raise MVP1AcceptanceError(f"Missing scenario entries: {missing_scenarios}")
    fixture_check_names = set(_mvp1_fixture_check_names(index))
    missing_fixture_checks = sorted(
        {
            fixture_name
            for scenario in scenario_entries.values()
            for fixture_name in _mvp1_scenario_fixture_names(scenario)
            if fixture_name not in fixture_check_names
        }
    )
    if missing_fixture_checks:
        raise MVP1AcceptanceError(f"scenario fixtures must be listed in fixture_checks: {missing_fixture_checks}")


def _mvp1_fixture_check_names(index: Mapping[str, Any]) -> tuple[str, ...]:
    checks = _required_sequence_mvp1(index, "fixture_checks")
    names: list[str] = []
    for check in checks:
        if not isinstance(check, Mapping) or not isinstance(check.get("fixture"), str):
            raise MVP1AcceptanceError("fixture_checks entries must contain fixture")
        names.append(str(check["fixture"]))
    if len(names) != len(set(names)):
        raise MVP1AcceptanceError("fixture_checks must not contain duplicate fixtures")
    return tuple(names)


def _mvp1_scenario_entries_by_id(index: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    scenarios = _required_sequence_mvp1(index, "scenarios")
    entries: dict[str, Mapping[str, Any]] = {}
    for scenario in scenarios:
        if not isinstance(scenario, Mapping):
            raise MVP1AcceptanceError("scenarios entries must be objects")
        scenario_id = scenario.get("scenario_id")
        if not isinstance(scenario_id, str) or not scenario_id:
            raise MVP1AcceptanceError("scenario entry must include scenario_id")
        _mvp1_scenario_fixture_names(scenario)
        if scenario_id in entries:
            raise MVP1AcceptanceError(f"duplicate scenario_id: {scenario_id}")
        entries[scenario_id] = scenario
    return entries


def _mvp1_scenario_fixture_names(scenario: Mapping[str, Any]) -> tuple[str, ...]:
    if "fixtures" in scenario:
        fixture_names = _string_tuple_mvp1(scenario["fixtures"], "fixtures")
    else:
        fixture = scenario.get("fixture")
        if not isinstance(fixture, str):
            raise MVP1AcceptanceError("scenario entry must include fixture or fixtures")
        fixture_names = (fixture,)
    if not fixture_names or not all(name.endswith(".fixture.json") for name in fixture_names):
        raise MVP1AcceptanceError("scenario fixtures must be .fixture.json files")
    return fixture_names


def _assert_mvp1_replay_matches_suite(
    index: Mapping[str, Any],
    *,
    fixture_name: str,
    result: ReplayResult,
) -> None:
    if result.fixture_domain != index["fixture_domain"]:
        raise MVP1AcceptanceError(f"{fixture_name} fixture_domain mismatch")
    if result.replay_mode != index["replay_mode"]:
        raise MVP1AcceptanceError(f"{fixture_name} replay_mode mismatch")
    if result.result_status != "passed":
        raise MVP1AcceptanceError(f"{fixture_name} replay did not pass")


def _assert_mvp1_replay_state_surface(result: ReplayResult, *, fixture_name: str) -> None:
    required_digest_fields = {
        "task_focus_state_hash",
        "slowtask_state_hash",
        "trace_privacy_state_hash",
        "overall_digest",
    }
    missing = sorted(required_digest_fields - set(result.state_digest))
    if missing:
        raise MVP1AcceptanceError(f"{fixture_name} state digest missing fields: {missing}")
    if result.trace_privacy_state.fixture_domain != "GITHUB_ALLOWED":
        raise MVP1AcceptanceError(f"{fixture_name} did not replay TracePrivacyState fixture domain")
    if result.trace_privacy_state.contains_raw_audio is not False:
        raise MVP1AcceptanceError(f"{fixture_name} replayed unsafe raw audio flag")


def _assert_mvp1_scenario(
    scenario_id: str,
    *,
    fixtures: tuple[Mapping[str, Any], ...],
    results: tuple[ReplayResult, ...],
) -> dict[str, Any]:
    if scenario_id == "MVP1-SPAWN-SLOWTASK-001":
        return _assert_mvp1_spawn_slowtask(fixtures[0], results[0])
    if scenario_id == "MVP1-ACTIVE-PATCH-001":
        return _assert_mvp1_active_patch(fixtures[0], results[0])
    if scenario_id == "MVP1-PLAN-ADVANCE-001":
        return _assert_mvp1_plan_advance(fixtures[0], results[0])
    if scenario_id == "MVP1-FOREGROUND-CHAT-001":
        return _assert_mvp1_foreground_chat(fixtures[0], results[0])
    if scenario_id == "MVP1-AMBIGUOUS-NO-PATCH-001":
        return _assert_mvp1_ambiguous_no_patch(fixtures[0], results[0])
    if scenario_id == "MVP1-WAITING-SLOT-001":
        return _assert_mvp1_waiting_slot(fixtures[0], results[0])
    if scenario_id == "MVP1-STALE-RESULT-001":
        return _assert_mvp1_stale_result(fixtures[0], results[0])
    if scenario_id == "MVP1-STALE-ADOPTED-001":
        return _assert_mvp1_stale_adopted(fixtures[0], results[0])
    if scenario_id == "MVP1-CANCEL-001":
        return _assert_mvp1_cancel(fixtures[0], results[0])
    if scenario_id == "MVP1-SWITCH-TASK-001":
        return _assert_mvp1_switch_task(fixtures, results)
    if scenario_id == "MVP1-FAILED-001":
        return _assert_mvp1_failed(fixtures[0], results[0])
    if scenario_id == "MVP1-SEMANTIC-COMMITMENT-001":
        return _assert_mvp1_semantic_commitment(fixtures[0], results[0])
    raise MVP1AcceptanceError(f"Unknown MVP-1 acceptance scenario: {scenario_id}")


def _assert_mvp1_spawn_slowtask(fixture: Mapping[str, Any], result: ReplayResult) -> dict[str, Any]:
    events = _events_by_name_mvp1(fixture)
    _require_mvp1_event_names(
        events,
        [
            "ROUTER_DECISION_EMITTED",
            "SLOWTASK_CREATED",
            "SLOWTASK_STATE_CHANGED",
            "TASK_FOCUS_STATE_UPDATED",
            "PLANNING_STARTED",
            "EVIDENCE_REVIEWED",
            "SEMANTIC_COMMITMENT_EMITTED",
        ],
    )
    if len(events["SLOWTASK_CREATED"]) != 1:
        raise MVP1AcceptanceError("spawn scenario must create exactly one SlowTask")
    created = events["SLOWTASK_CREATED"][0]
    task = result.slowtask_state.tasks[str(created["task_id"])]
    if task.lifecycle_state != "COMPLETED" or result.task_focus_state.active_task_id is not None:
        raise MVP1AcceptanceError("spawn scenario must complete and clear active focus")
    if task.semantic_commitments[-1].plan_version != task.current_plan_version:
        raise MVP1AcceptanceError("SemanticCommitment must use current plan")
    _assert_event_order(fixture, ["SLOWTASK_CREATED", "TASK_FOCUS_STATE_UPDATED"])
    return {
        "task_id": task.task_id,
        "terminal_state": task.lifecycle_state,
        "current_plan_version": task.current_plan_version,
        "semantic_commitment_count": len(task.semantic_commitments),
        "active_task_id": result.task_focus_state.active_task_id,
    }


def _assert_mvp1_active_patch(fixture: Mapping[str, Any], result: ReplayResult) -> dict[str, Any]:
    events = _events_by_name_mvp1(fixture)
    _require_mvp1_event_names(events, ["ROUTER_DECISION_EMITTED", "TASK_FOCUS_STATE_UPDATED", "USER_PATCH_RECEIVED"])
    if "USER_PATCH_INTERPRETED" in events or "PLAN_VERSION_ADVANCED" in events:
        raise MVP1AcceptanceError("active patch receipt must not interpret or advance plan")
    patch_event = events["USER_PATCH_RECEIVED"][0]
    evidence_pack = patch_event.get("evidence_pack")
    if not isinstance(evidence_pack, Mapping):
        raise MVP1AcceptanceError("USER_PATCH_RECEIVED must carry evidence_pack metadata")
    if "authoritative_evidence" not in evidence_pack or "non_authoritative_hypothesis" not in evidence_pack:
        raise MVP1AcceptanceError("UserPatch evidence pack must preserve evidence and hypotheses")
    task = result.slowtask_state.tasks[str(patch_event["task_id"])]
    if task.current_plan_version != int(patch_event["plan_version"]):
        raise MVP1AcceptanceError("UserPatch receipt must use pre-advance current plan")
    return {
        "task_id": task.task_id,
        "active_task_id": result.task_focus_state.active_task_id,
        "patch_count": len(task.user_patch_evidence),
        "current_plan_version": task.current_plan_version,
        "latest_patch_id": patch_event["patch_id"],
    }


def _assert_mvp1_plan_advance(fixture: Mapping[str, Any], result: ReplayResult) -> dict[str, Any]:
    events = _events_by_name_mvp1(fixture)
    _require_mvp1_event_names(
        events,
        ["USER_PATCH_RECEIVED", "USER_PATCH_INTERPRETED", "PLAN_VERSION_ADVANCED", "PLANNING_RESTARTED", "TASK_REPLANNED"],
    )
    _assert_event_order(
        fixture,
        ["USER_PATCH_RECEIVED", "USER_PATCH_INTERPRETED", "PLAN_VERSION_ADVANCED", "PLANNING_RESTARTED", "TASK_REPLANNED"],
    )
    patch = events["USER_PATCH_RECEIVED"][0]
    interpreted = events["USER_PATCH_INTERPRETED"][0]
    advance = events["PLAN_VERSION_ADVANCED"][0]
    _assert_event_seq_before(patch, interpreted, "USER_PATCH_RECEIVED must precede USER_PATCH_INTERPRETED")
    _assert_event_seq_before(interpreted, advance, "USER_PATCH_INTERPRETED must precede PLAN_VERSION_ADVANCED")
    if interpreted.get("caused_by_event_id") != patch["event_id"] or interpreted.get("patch_id") != patch["patch_id"]:
        raise MVP1AcceptanceError("material UserPatch interpretation must be tied to the received patch")
    if interpreted.get("materially_changes_task") is not True:
        raise MVP1AcceptanceError("MVP1-PLAN-ADVANCE-001 requires a material UserPatch interpretation")
    planning_reason = str(advance.get("planning_reason", ""))
    if not (planning_reason == "material_user_patch" or planning_reason.startswith("material_user_patch:")):
        raise MVP1AcceptanceError("PLAN_VERSION_ADVANCED must cite a material UserPatch planning reason")
    if advance.get("caused_by_user_patch_event_id") != patch["event_id"]:
        raise MVP1AcceptanceError("PLAN_VERSION_ADVANCED must reference the material UserPatch event")
    if advance.get("caused_by_event_id") != interpreted["event_id"]:
        raise MVP1AcceptanceError("PLAN_VERSION_ADVANCED must be caused by the interpreted material UserPatch")
    task = result.slowtask_state.tasks[str(advance["task_id"])]
    if task.current_plan_version != int(advance["to_plan_version"]):
        raise MVP1AcceptanceError("PLAN_VERSION_ADVANCED must be the current plan mutator")
    if task.semantic_commitments:
        raise MVP1AcceptanceError("plan advance fixture must not emit old-plan SemanticCommitment")
    return {
        "task_id": task.task_id,
        "from_plan_version": advance["from_plan_version"],
        "to_plan_version": advance["to_plan_version"],
        "current_plan_version": task.current_plan_version,
        "plan_advance_count": len(task.plan_advances),
    }


def _assert_mvp1_foreground_chat(fixture: Mapping[str, Any], result: ReplayResult) -> dict[str, Any]:
    router = _find_event(
        fixture,
        "ROUTER_DECISION_EMITTED",
        router_decision="FAST_ONLY",
        task_focus="FOREGROUND_CHAT",
    )
    focus = _find_event(fixture, "TASK_FOCUS_STATE_UPDATED", router_decision_event_id=str(router["event_id"]))
    turn_committed = _find_event_by_id(fixture, str(router["turn_committed_event_id"]))
    forbidden = _mvp1_forbidden_events_after_until_next_input(
        fixture,
        after_event=turn_committed,
        forbidden_event_names=MVP1_NO_PATCH_MUTATION_EVENT_NAMES,
    )
    if forbidden:
        raise MVP1AcceptanceError(
            "foreground chat must not create UserPatch, advance plan, or mutate SlowTask state: "
            f"{forbidden}"
        )
    return {
        "router_event_id": router["event_id"],
        "active_task_id": focus["active_task_id"],
        "foreground_mode": focus["foreground_mode"],
        "slowtask_state": result.slowtask_state.tasks[str(focus["active_task_id"])].lifecycle_state,
    }


def _assert_mvp1_ambiguous_no_patch(fixture: Mapping[str, Any], result: ReplayResult) -> dict[str, Any]:
    router = _find_event(
        fixture,
        "ROUTER_DECISION_EMITTED",
        router_decision="FAST_ONLY",
        task_focus="AMBIGUOUS",
    )
    focus = _find_event(fixture, "TASK_FOCUS_STATE_UPDATED", router_decision_event_id=str(router["event_id"]))
    turn_committed = _find_event_by_id(fixture, str(router["turn_committed_event_id"]))
    forbidden = _mvp1_forbidden_events_after_until_next_input(
        fixture,
        after_event=turn_committed,
        forbidden_event_names=MVP1_NO_PATCH_MUTATION_EVENT_NAMES,
    )
    if forbidden:
        raise MVP1AcceptanceError(
            "ambiguous input must not create UserPatch, advance plan, or mutate SlowTask state: "
            f"{forbidden}"
        )
    return {
        "router_event_id": router["event_id"],
        "active_task_id": focus["active_task_id"],
        "last_focus_decision": focus["last_focus_decision"],
        "last_focus_confidence": focus["last_focus_confidence"],
        "current_plan_version": result.slowtask_state.tasks[str(focus["active_task_id"])].current_plan_version,
    }


def _assert_mvp1_waiting_slot(fixture: Mapping[str, Any], result: ReplayResult) -> dict[str, Any]:
    events = _events_by_name_mvp1(fixture)
    _require_mvp1_event_names(
        events,
        ["EVIDENCE_REVIEWED", "INSUFFICIENT_EVIDENCE_FOR_ACTION", "CLARIFICATION_REQUESTED", "WAITING_FOR_SLOT"],
    )
    forbidden = {"TOOL_CALL_STARTED", "TOOL_EXECUTION_STARTED", "SEMANTIC_COMMITMENT_EMITTED"} & set(events)
    if forbidden:
        raise MVP1AcceptanceError(f"waiting-slot scenario emitted forbidden events: {sorted(forbidden)}")
    task_id = str(events["WAITING_FOR_SLOT"][0]["task_id"])
    task = result.slowtask_state.tasks[task_id]
    if task.lifecycle_state != "WAITING_FOR_SLOT":
        raise MVP1AcceptanceError("waiting-slot scenario must replay to WAITING_FOR_SLOT")
    return {
        "task_id": task_id,
        "lifecycle_state": task.lifecycle_state,
        "missing_fields": list(events["WAITING_FOR_SLOT"][0]["missing_fields"]),
    }


def _assert_mvp1_stale_result(fixture: Mapping[str, Any], result: ReplayResult) -> dict[str, Any]:
    events = _events_by_name_mvp1(fixture)
    _require_mvp1_event_names(events, ["TOOL_RESULT_RECEIVED", "TOOL_RESULT_MARKED_STALE", "STALE_EVIDENCE_RECORDED"])
    if "STALE_EVIDENCE_ADOPTED" in events or "SEMANTIC_COMMITMENT_EMITTED" in events:
        raise MVP1AcceptanceError("stale-result scenario must not adopt or commit")
    recorded = events["STALE_EVIDENCE_RECORDED"][0]
    task = result.slowtask_state.tasks[str(recorded["task_id"])]
    return {
        "task_id": task.task_id,
        "current_plan_version": task.current_plan_version,
        "stale_evidence_count": len(task.stale_evidence_refs),
        "adopted_evidence_count": len(task.adopted_evidence),
        "semantic_commitment_count": len(task.semantic_commitments),
    }


def _assert_mvp1_stale_adopted(fixture: Mapping[str, Any], result: ReplayResult) -> dict[str, Any]:
    events = _events_by_name_mvp1(fixture)
    _require_mvp1_event_names(
        events,
        [
            "STALE_EVIDENCE_ADOPTED",
            "EVIDENCE_REVIEWED",
            "ARGUMENTS_RESOLVED",
            "FINALIZING",
            "SEMANTIC_COMMITMENT_EMITTED",
        ],
    )
    adoption = events["STALE_EVIDENCE_ADOPTED"][0]
    reviewed = events["EVIDENCE_REVIEWED"][0]
    finalizing = events["FINALIZING"][0]
    commitment = events["SEMANTIC_COMMITMENT_EMITTED"][0]
    _assert_event_seq_before(
        adoption,
        reviewed,
        "STALE_EVIDENCE_ADOPTED must precede current-plan evidence review",
    )
    _assert_event_seq_before(
        adoption,
        events["ARGUMENTS_RESOLVED"][0],
        "STALE_EVIDENCE_ADOPTED must precede current-plan argument resolution",
    )
    _assert_event_seq_before(
        adoption,
        finalizing,
        "STALE_EVIDENCE_ADOPTED must precede current-plan finalizing",
    )
    _assert_event_seq_before(
        adoption,
        commitment,
        "STALE_EVIDENCE_ADOPTED must precede current-plan SemanticCommitment",
    )
    if reviewed.get("caused_by_event_id") != adoption["event_id"]:
        raise MVP1AcceptanceError("EVIDENCE_REVIEWED must be caused by STALE_EVIDENCE_ADOPTED")
    if adoption["event_id"] not in finalizing.get("source_events", ()):
        raise MVP1AcceptanceError("FINALIZING must cite STALE_EVIDENCE_ADOPTED before commitment")
    if adoption["event_id"] not in commitment["source_events"]:
        raise MVP1AcceptanceError("adopted stale evidence used by commitment must cite adoption event")
    task = result.slowtask_state.tasks[str(adoption["task_id"])]
    return {
        "task_id": task.task_id,
        "current_plan_version": task.current_plan_version,
        "adopted_evidence_count": len(task.adopted_evidence),
        "semantic_commitment_count": len(task.semantic_commitments),
    }


def _assert_mvp1_cancel(fixture: Mapping[str, Any], result: ReplayResult) -> dict[str, Any]:
    events = _events_by_name_mvp1(fixture)
    _require_mvp1_event_names(
        events,
        [
            "USER_PATCH_RECEIVED",
            "USER_PATCH_INTERPRETED",
            "CONFIRMATION_REQUIRED",
            "USER_CONFIRMATION_RECEIVED",
            "CONFIRMATION_ACCEPTED",
            "SLOWTASK_CANCEL_REQUESTED",
            "SLOWTASK_CANCELLED",
        ],
    )
    accepted = events["CONFIRMATION_ACCEPTED"][0]
    requested = events["SLOWTASK_CANCEL_REQUESTED"][0]
    cancelled = events["SLOWTASK_CANCELLED"][0]
    if requested.get("caused_by_event_id") != accepted["event_id"]:
        raise MVP1AcceptanceError("SLOWTASK_CANCEL_REQUESTED must be caused by accepted confirmation")
    _assert_event_seq_before(
        accepted,
        requested,
        "accepted confirmation must precede SLOWTASK_CANCEL_REQUESTED",
    )
    if cancelled.get("caused_by_event_id") != requested["event_id"]:
        raise MVP1AcceptanceError("SLOWTASK_CANCELLED must be caused by SLOWTASK_CANCEL_REQUESTED")
    _assert_event_seq_before(requested, cancelled, "SLOWTASK_CANCEL_REQUESTED must precede SLOWTASK_CANCELLED")
    task = next(iter(result.slowtask_state.tasks.values()))
    if task.lifecycle_state != "CANCELLED" or task.confirmation_state.accepted_scope != "TASK_CANCEL":
        raise MVP1AcceptanceError("cancel scenario must replay SlowTask-owned accepted TASK_CANCEL")
    if result.task_focus_state.active_task_id is not None:
        raise MVP1AcceptanceError("cancel scenario must clear active focus through Router-owned update")
    return {
        "task_id": task.task_id,
        "terminal_state": task.lifecycle_state,
        "accepted_scope": task.confirmation_state.accepted_scope,
        "late_event_count": len(task.late_events),
        "active_task_id": result.task_focus_state.active_task_id,
    }


def _assert_mvp1_switch_task(
    fixtures: tuple[Mapping[str, Any], ...],
    results: tuple[ReplayResult, ...],
) -> dict[str, Any]:
    if len(fixtures) != 2 or len(results) != 2:
        raise MVP1AcceptanceError("switch-task scenario must cover accepted and rejected fixtures")
    accepted_fixture, _rejected_fixture = fixtures
    accepted, rejected = results
    accepted_tasks = accepted.slowtask_state.tasks
    active = accepted_tasks["task_mvp1_slice9_switch_active"]
    replacement = accepted_tasks["task_mvp1_slice9_switch_replacement"]
    if active.lifecycle_state != "CANCELLED" or replacement.lifecycle_state != "CREATED":
        raise MVP1AcceptanceError("accepted switch must cancel active task before replacement spawn")
    accepted_cancelled = _find_event(
        accepted_fixture,
        "SLOWTASK_STATE_CHANGED",
        task_id=active.task_id,
        to_state="CANCELLED",
    )
    replacement_created = _find_event(
        accepted_fixture,
        "SLOWTASK_CREATED",
        task_id=replacement.task_id,
    )
    try:
        focus_cleared = _find_event(
            accepted_fixture,
            "TASK_FOCUS_STATE_UPDATED",
            active_task_id=None,
            foreground_mode="IDLE",
        )
    except MVP1AcceptanceError as exc:
        raise MVP1AcceptanceError("accepted switch must clear active focus before replacement spawn") from exc
    _assert_event_seq_before(
        accepted_cancelled,
        focus_cleared,
        "accepted switch must clear active focus after active cancellation",
    )
    _assert_event_seq_before(
        focus_cleared,
        replacement_created,
        "accepted switch must clear active focus before replacement spawn",
    )
    spawn_router = _find_event(
        accepted_fixture,
        "ROUTER_DECISION_EMITTED",
        router_decision="SPAWN_SLOW_TASK",
        task_focus="NEW_TASK_CANDIDATE",
    )
    if spawn_router.get("caused_by_event_id") != focus_cleared["event_id"]:
        raise MVP1AcceptanceError("accepted switch respawn router decision must be caused by cleared active focus")
    if (
        active.confirmation_state.status != "accepted"
        or active.confirmation_state.accepted_scope != "SWITCH_TASK"
        or active.confirmation_state.authorization_ref is None
    ):
        raise MVP1AcceptanceError(
            "accepted switch must replay accepted SWITCH_TASK confirmation before cancel-then-spawn"
        )
    rejected_task = rejected.slowtask_state.tasks["task_mvp1_slice9_switch_rejected"]
    if rejected_task.lifecycle_state != "PLANNING" or rejected_task.current_plan_version != 1:
        raise MVP1AcceptanceError("rejected switch must preserve active task and current plan")
    if rejected_task.confirmation_state.status != "rejected":
        raise MVP1AcceptanceError("rejected switch must replay rejected confirmation state")
    if rejected.task_focus_state.active_task_id != rejected_task.task_id:
        raise MVP1AcceptanceError("rejected switch must preserve active focus on the original task")
    rejected_event = _find_event(
        fixtures[1],
        "CONFIRMATION_REJECTED",
        task_id=rejected_task.task_id,
    )
    rejected_mutations = _mvp1_forbidden_events_after(
        fixtures[1],
        after_event=rejected_event,
        forbidden_event_names=MVP1_REJECTED_SWITCH_MUTATION_EVENT_NAMES,
        task_id=rejected_task.task_id,
    )
    if rejected_mutations:
        raise MVP1AcceptanceError(
            "rejected switch must not mutate goal, arguments, or current plan after rejection: "
            f"{rejected_mutations}"
        )
    return {
        "accepted_cancelled_task_id": active.task_id,
        "replacement_task_id": replacement.task_id,
        "rejected_task_id": rejected_task.task_id,
        "rejected_current_plan_version": rejected_task.current_plan_version,
        "rejected_active_task_id": rejected.task_focus_state.active_task_id,
    }


def _assert_mvp1_failed(fixture: Mapping[str, Any], result: ReplayResult) -> dict[str, Any]:
    events = _events_by_name_mvp1(fixture)
    _require_mvp1_event_names(events, ["SLOWTASK_FAILED", "SLOWTASK_STATE_CHANGED"])
    task = next(iter(result.slowtask_state.tasks.values()))
    if task.lifecycle_state != "FAILED" or task.terminal_outcome != "FAILED":
        raise MVP1AcceptanceError("failed scenario must replay terminal FAILED state")
    if task.semantic_commitments:
        raise MVP1AcceptanceError("failed scenario must not emit SemanticCommitment")
    return {
        "task_id": task.task_id,
        "terminal_state": task.lifecycle_state,
        "failure_reason": task.failure_reason,
        "late_event_count": len(task.late_events),
    }


def _assert_mvp1_semantic_commitment(fixture: Mapping[str, Any], result: ReplayResult) -> dict[str, Any]:
    events = _events_by_name_mvp1(fixture)
    _require_mvp1_event_names(events, ["ARGUMENTS_RESOLVED", "FINALIZING", "SEMANTIC_COMMITMENT_EMITTED"])
    forbidden = {
        "SPOKEN_PLAN_EMITTED",
        "COMMITMENT_COVERAGE_CHECK_PASSED",
        "PROGRESS_TRUTHFULNESS_CHECK_PASSED",
    } & set(events)
    if forbidden:
        raise MVP1AcceptanceError(f"SemanticCommitment scenario emitted MVP-2 events: {sorted(forbidden)}")
    commitment = events["SEMANTIC_COMMITMENT_EMITTED"][0]
    task = result.slowtask_state.tasks[str(commitment["task_id"])]
    if int(commitment["plan_version"]) != task.current_plan_version:
        raise MVP1AcceptanceError("SemanticCommitment must bind the current plan")
    return {
        "task_id": task.task_id,
        "commitment_id": commitment["commitment_id"],
        "current_plan_version": task.current_plan_version,
        "terminal_state": task.lifecycle_state,
    }


def _validate_mvp1_synthetic_eval_table(index: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    rows = _required_sequence_mvp1(index, "synthetic_eval_table")
    required_measurements = {
        "patch_focus_correctness",
        "ambiguity_no_patch_behavior",
        "user_patch_interpretation_materiality",
    }
    normalized_rows: list[dict[str, Any]] = []
    seen_measurements: set[str] = set()
    fixture_check_names = set(_mvp1_fixture_check_names(index))
    for row in rows:
        if not isinstance(row, Mapping):
            raise MVP1AcceptanceError("synthetic_eval_table rows must be objects")
        measurement = _required_str_mvp1(row, "measurement")
        fixture = _required_str_mvp1(row, "fixture")
        output_mode = _required_str_mvp1(row, "output_mode")
        result_status = _required_str_mvp1(row, "result_status")
        if output_mode not in MVP1_OUTPUT_MODES:
            raise MVP1AcceptanceError("MVP-1 synthetic eval output_mode must be mock/degraded/fallback, not real")
        if result_status != "passed":
            raise MVP1AcceptanceError("synthetic eval table rows must pass for closeout")
        if fixture not in fixture_check_names:
            raise MVP1AcceptanceError(f"synthetic eval fixture not listed in fixture_checks: {fixture}")
        seen_measurements.add(measurement)
        normalized_rows.append(
            {
                "measurement": measurement,
                "fixture": fixture,
                "output_mode": output_mode,
                "result_status": result_status,
            }
        )
    missing = sorted(required_measurements - seen_measurements)
    if missing:
        raise MVP1AcceptanceError(f"synthetic_eval_table missing measurements: {missing}")
    return tuple(normalized_rows)


def _assert_mvp1_mock_degraded_real_labels(fixture: Mapping[str, Any]) -> None:
    for event in _required_sequence_mvp1(fixture, "events"):
        if not isinstance(event, Mapping):
            raise MVP1AcceptanceError("fixture events must be objects")
        event_name = str(event.get("event_name", ""))
        if event_name in {"MOCK_ASR_FRAME_EMITTED", "MOCK_THINKER_FRAME_EMITTED"}:
            if event.get("output_mode") != "mock":
                raise MVP1AcceptanceError(f"{event_name} must be labeled output_mode=mock")
        if event_name == "ADAPTER_CAPABILITY_SNAPSHOT_RECORDED":
            output_modes = event.get("output_modes", ())
            deployment_modes = event.get("deployment_modes", ())
            if not isinstance(output_modes, Sequence) or isinstance(output_modes, (str, bytes)):
                raise MVP1AcceptanceError("capability output_modes must be a list")
            if not isinstance(deployment_modes, Sequence) or isinstance(deployment_modes, (str, bytes)):
                raise MVP1AcceptanceError("capability deployment_modes must be a list")
            if not set(output_modes) <= MVP1_OUTPUT_MODES or not set(deployment_modes) <= MVP1_OUTPUT_MODES:
                raise MVP1AcceptanceError(
                    "MVP-1 capability modes must be mock/degraded/fallback and must not be real"
                )


def _assert_mvp1_event_source_module(*, event_name: str, source_module: str) -> None:
    expected_source_module = MVP1_REQUIRED_SOURCE_MODULES.get(event_name)
    if expected_source_module is None:
        return
    if event_name in MVP1_TOOL_MARKER_EVENT_NAMES and source_module != expected_source_module:
        raise MVP1AcceptanceError(
            "MVP-1 Tool Executor markers must use source_module=mock_tool_event_emitter"
        )
    if source_module != expected_source_module:
        raise MVP1AcceptanceError(
            f"{event_name} source_module must be {expected_source_module}, got {source_module}"
        )


def _assert_mvp1_safe_string_fixture_value(value: str, key_path: str) -> None:
    lower_value = value.lower()
    if _contains_secret_like_value(value):
        raise MVP1AcceptanceError(f"forbidden secret-like fixture value: {key_path}")
    if any(lower_value.endswith(extension) for extension in RAW_AUDIO_EXTENSIONS):
        raise MVP1AcceptanceError(f"forbidden raw audio ref: {key_path}")
    forbidden_markers = (
        "audio/raw/",
        "traces/",
        "diagnostics/",
        "replays/local/",
        "raw trace",
        "real user",
        "access_token",
        "api_key",
        "authorization header",
        "cookie=",
    )
    if any(marker in lower_value for marker in forbidden_markers):
        raise MVP1AcceptanceError(f"forbidden local, raw, or secret marker: {key_path}")


def _contains_secret_like_value(value: str) -> bool:
    for match in SECRET_VALUE_PATTERN.finditer(value):
        if match.start() == 0 or not value[match.start() - 1].isalnum():
            return True
    return False


def _events_by_name_mvp1(fixture: Mapping[str, Any]) -> dict[str, list[Mapping[str, Any]]]:
    events_by_name: dict[str, list[Mapping[str, Any]]] = {}
    for event in _required_sequence_mvp1(fixture, "events"):
        if not isinstance(event, Mapping):
            raise MVP1AcceptanceError("fixture events must be objects")
        events_by_name.setdefault(str(event["event_name"]), []).append(event)
    return events_by_name


def _require_mvp1_event_names(
    events_by_name: Mapping[str, Sequence[Mapping[str, Any]]],
    event_names: Sequence[str],
) -> None:
    missing = [event_name for event_name in event_names if event_name not in events_by_name]
    if missing:
        raise MVP1AcceptanceError(f"Missing expected MVP-1 scenario events: {missing}")


def _find_event(fixture: Mapping[str, Any], event_name: str, **matches: object) -> Mapping[str, Any]:
    for event in _required_sequence_mvp1(fixture, "events"):
        if not isinstance(event, Mapping) or event.get("event_name") != event_name:
            continue
        if all(event.get(field) == expected for field, expected in matches.items()):
            return event
    raise MVP1AcceptanceError(f"Missing {event_name} event matching {matches}")


def _find_event_by_id(fixture: Mapping[str, Any], event_id: str) -> Mapping[str, Any]:
    for event in _required_sequence_mvp1(fixture, "events"):
        if isinstance(event, Mapping) and event.get("event_id") == event_id:
            return event
    raise MVP1AcceptanceError(f"Missing event_id: {event_id}")


def _assert_event_order(fixture: Mapping[str, Any], event_names: Sequence[str]) -> None:
    positions: list[int] = []
    events = _required_sequence_mvp1(fixture, "events")
    for event_name in event_names:
        for index, event in enumerate(events):
            if isinstance(event, Mapping) and event.get("event_name") == event_name:
                positions.append(index)
                break
        else:
            raise MVP1AcceptanceError(f"Missing event for order assertion: {event_name}")
    if positions != sorted(positions):
        raise MVP1AcceptanceError(f"Events are out of order: {list(event_names)}")


def _assert_event_seq_before(
    before_event: Mapping[str, Any],
    after_event: Mapping[str, Any],
    message: str,
) -> None:
    if int(before_event["event_seq"]) >= int(after_event["event_seq"]):
        raise MVP1AcceptanceError(message)


def _mvp1_forbidden_events_after_until_next_input(
    fixture: Mapping[str, Any],
    *,
    after_event: Mapping[str, Any],
    forbidden_event_names: frozenset[str],
) -> list[str]:
    return _mvp1_forbidden_events_after(
        fixture,
        after_event=after_event,
        forbidden_event_names=forbidden_event_names,
        stop_at_next_input=True,
    )


def _mvp1_forbidden_events_after(
    fixture: Mapping[str, Any],
    *,
    after_event: Mapping[str, Any],
    forbidden_event_names: frozenset[str],
    task_id: str | None = None,
    stop_at_next_input: bool = False,
) -> list[str]:
    after_event_seq = int(after_event["event_seq"])
    forbidden: list[str] = []
    events = sorted(
        (
            event
            for event in _required_sequence_mvp1(fixture, "events")
            if isinstance(event, Mapping) and int(event["event_seq"]) > after_event_seq
        ),
        key=lambda event: int(event["event_seq"]),
    )
    for event in events:
        event_name = str(event["event_name"])
        if stop_at_next_input and event_name in {"TEXT_INPUT_RECEIVED", "AUDIO_SPAN_STARTED"}:
            break
        if task_id is not None and event.get("task_id") != task_id:
            continue
        if event_name in forbidden_event_names:
            forbidden.append(f"{event_name}:{event['event_id']}")
    return forbidden


def _required_sequence_mvp1(mapping: Mapping[str, Any], field: str) -> Sequence[Any]:
    value = mapping.get(field)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise MVP1AcceptanceError(f"{field} must be a list")
    return value


def _required_str_mvp1(mapping: Mapping[str, Any], field: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value:
        raise MVP1AcceptanceError(f"{field} must be a non-empty string")
    return value


def _string_tuple_mvp1(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise MVP1AcceptanceError(f"{field} must be a list of strings")
    if not all(isinstance(item, str) and item for item in value):
        raise MVP1AcceptanceError(f"{field} must be a list of non-empty strings")
    return tuple(value)


def _validate_manifest_index(index: Mapping[str, Any]) -> None:
    required_fields = {
        "manifest_index_schema_version",
        "suite_id",
        "fixture_domain",
        "replay_mode",
        "required_scenarios",
        "fixture_checks",
        "scenarios",
    }
    missing = required_fields - set(index)
    if missing:
        raise MVP0AcceptanceError(f"Missing MVP0 acceptance manifest fields: {sorted(missing)}")
    if index["manifest_index_schema_version"] != "1.0":
        raise MVP0AcceptanceError("manifest_index_schema_version must be '1.0'")
    if index["suite_id"] != "MVP0-ACCEPTANCE":
        raise MVP0AcceptanceError("suite_id must be 'MVP0-ACCEPTANCE'")
    if index["fixture_domain"] != "GITHUB_ALLOWED":
        raise MVP0AcceptanceError("MVP0 acceptance fixtures must be GITHUB_ALLOWED")
    if index["replay_mode"] != "deterministic":
        raise MVP0AcceptanceError("MVP0 acceptance uses deterministic replay")

    required_scenarios = _string_tuple(index["required_scenarios"], "required_scenarios")
    if required_scenarios != MVP0_REQUIRED_SCENARIOS:
        raise MVP0AcceptanceError(f"required_scenarios must be {list(MVP0_REQUIRED_SCENARIOS)}")

    scenario_entries = _scenario_entries_by_id(index)
    missing_scenarios = [scenario_id for scenario_id in required_scenarios if scenario_id not in scenario_entries]
    if missing_scenarios:
        raise MVP0AcceptanceError(f"Missing scenario entries: {missing_scenarios}")
    fixture_check_names = set(_fixture_check_names(index))
    missing_fixture_checks = sorted(
        {
            str(scenario["fixture"])
            for scenario in scenario_entries.values()
            if str(scenario["fixture"]) not in fixture_check_names
        }
    )
    if missing_fixture_checks:
        raise MVP0AcceptanceError(f"scenario fixtures must be listed in fixture_checks: {missing_fixture_checks}")


def _fixture_check_names(index: Mapping[str, Any]) -> tuple[str, ...]:
    checks = _required_sequence(index, "fixture_checks")
    names: list[str] = []
    for check in checks:
        if not isinstance(check, Mapping) or not isinstance(check.get("fixture"), str):
            raise MVP0AcceptanceError("fixture_checks entries must contain fixture")
        names.append(str(check["fixture"]))
    if len(names) != len(set(names)):
        raise MVP0AcceptanceError("fixture_checks must not contain duplicate fixtures")
    return tuple(names)


def _scenario_entries_by_id(index: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    scenarios = _required_sequence(index, "scenarios")
    entries: dict[str, Mapping[str, Any]] = {}
    for scenario in scenarios:
        if not isinstance(scenario, Mapping):
            raise MVP0AcceptanceError("scenarios entries must be objects")
        scenario_id = scenario.get("scenario_id")
        fixture_name = scenario.get("fixture")
        if not isinstance(scenario_id, str) or not scenario_id:
            raise MVP0AcceptanceError("scenario entry must include scenario_id")
        if not isinstance(fixture_name, str) or not fixture_name.endswith(".fixture.json"):
            raise MVP0AcceptanceError("scenario entry must include fixture")
        if scenario_id in entries:
            raise MVP0AcceptanceError(f"duplicate scenario_id: {scenario_id}")
        entries[scenario_id] = scenario
    return entries


def _assert_replay_matches_suite(index: Mapping[str, Any], *, fixture_name: str, result: ReplayResult) -> None:
    if result.fixture_domain != index["fixture_domain"]:
        raise MVP0AcceptanceError(f"{fixture_name} fixture_domain mismatch")
    if result.replay_mode != index["replay_mode"]:
        raise MVP0AcceptanceError(f"{fixture_name} replay_mode mismatch")
    if result.result_status not in {"passed", "degraded"}:
        raise MVP0AcceptanceError(f"{fixture_name} replay did not pass")


def _assert_scenario(
    scenario_id: str,
    *,
    fixture: Mapping[str, Any],
    result: ReplayResult,
) -> dict[str, Any]:
    if scenario_id == "MVP0-TEXT-INGRESS-001":
        return _assert_text_ingress_scenario(fixture, result)
    if scenario_id == "MVP0-AUDIO-INGRESS-001":
        return _assert_audio_ingress_scenario(fixture, result)
    if scenario_id == "MVP0-BARGE-IN-TRUNCATE-001":
        return _assert_barge_in_truncate_scenario(fixture, result)
    if scenario_id == "MVP0-MOCK-ADAPTER-CAPABILITY-001":
        return _assert_mock_adapter_capability_scenario(fixture, result)
    if scenario_id == "MVP0-LOCAL-TRACE-SAFETY-001":
        return _assert_local_trace_safety_scenario(fixture, result)
    raise MVP0AcceptanceError(f"Unknown MVP0 acceptance scenario: {scenario_id}")


def _assert_text_ingress_scenario(fixture: Mapping[str, Any], result: ReplayResult) -> dict[str, Any]:
    events = _events_by_name(fixture)
    _require_event_names(
        events,
        [
            "TEXT_INPUT_RECEIVED",
            "TURN_OPENED",
            "TURN_INGRESS_ACCEPTED",
            "TURN_INGRESS_COMMITTED",
            "MOCK_THINKER_FRAME_EMITTED",
            "ROUTER_DECISION_EMITTED",
        ],
    )
    text_event = events["TEXT_INPUT_RECEIVED"][0]
    thinker_event = events["MOCK_THINKER_FRAME_EMITTED"][0]
    router_event = events["ROUTER_DECISION_EMITTED"][0]
    if text_event.get("audio_span_id") is not None:
        raise MVP0AcceptanceError("text ingress must not synthesize audio_span_id")
    if thinker_event.get("output_mode") != "mock":
        raise MVP0AcceptanceError("text ingress mock Thinker handoff must be labeled output_mode=mock")
    if router_event.get("thinker_frame_event_id") != thinker_event["event_id"]:
        raise MVP0AcceptanceError("text ingress Router decision must reference mock Thinker output")
    if router_event.get("turn_committed_event_id") != events["TURN_INGRESS_COMMITTED"][0]["event_id"]:
        raise MVP0AcceptanceError("text ingress Router decision must reference committed turn")
    _assert_playback_commit_is_delivery_marker_only(fixture["events"])

    state = result.interaction_state
    if state.turn_phase != "TURN_COMMITTED" or state.last_ingress_outcome != "COMMITTED":
        raise MVP0AcceptanceError("text ingress did not replay to committed interaction state")
    if state.current_audio_span_id is not None:
        raise MVP0AcceptanceError("text ingress replay must leave current_audio_span_id unset")
    if state.directedness != "ASSUMED_DIRECTED" or state.semantic_close != "ASSUMED_CLOSED":
        raise MVP0AcceptanceError("text ingress must use assumed directed/closed policy")

    return {
        "turn_phase": state.turn_phase,
        "last_ingress_outcome": state.last_ingress_outcome,
        "current_text_span_id": state.current_text_span_id,
        "current_audio_span_id": state.current_audio_span_id,
        "mock_thinker_event_id": thinker_event["event_id"],
        "router_event_id": router_event["event_id"],
        "router_decision": router_event["router_decision"],
    }


def _assert_audio_ingress_scenario(fixture: Mapping[str, Any], result: ReplayResult) -> dict[str, Any]:
    events = _events_by_name(fixture)
    _require_event_names(
        events,
        [
            "AUDIO_SPAN_STARTED",
            "SPEECH_START_DETECTED",
            "AUDIO_SPAN_ENDED",
            "SPEECH_END_DETECTED",
            "TURN_OPENED",
            "TURN_INGRESS_ACCEPTED",
            "TURN_INGRESS_COMMITTED",
            "MOCK_ASR_FRAME_EMITTED",
            "MOCK_THINKER_FRAME_EMITTED",
            "ROUTER_DECISION_EMITTED",
        ],
    )
    _assert_mock_outputs_labeled(fixture["events"])

    state = result.interaction_state
    if state.turn_phase != "TURN_COMMITTED" or state.current_audio_span_id is None:
        raise MVP0AcceptanceError("audio ingress did not replay to committed audio interaction state")
    if result.task_focus_state.active_task_id is not None:
        raise MVP0AcceptanceError("MVP0 audio acceptance must not create active SlowTask")
    if set(result.adapter_health_state.output_event_modes.values()) != {"mock"}:
        raise MVP0AcceptanceError("mock understanding outputs must be labeled mock")

    return {
        "turn_phase": state.turn_phase,
        "current_audio_span_id": state.current_audio_span_id,
        "router_decision": events["ROUTER_DECISION_EMITTED"][0]["router_decision"],
        "mock_output_modes": sorted(set(result.adapter_health_state.output_event_modes.values())),
    }


def _assert_barge_in_truncate_scenario(fixture: Mapping[str, Any], result: ReplayResult) -> dict[str, Any]:
    events_by_name = _events_by_name(fixture)
    _require_event_names(
        events_by_name,
        [
            "PLAYBACK_SPAN_STARTED",
            "PLAYBACK_PROGRESS",
            "PLAYBACK_COMMITTED",
            "BARGE_IN_CANDIDATE",
            "INTERRUPT_CANDIDATE",
            "TTS_TRUNCATE_REQUESTED",
            "TTS_TRUNCATED",
        ],
    )
    events_by_id = _events_by_id(fixture)
    candidate = events_by_name["BARGE_IN_CANDIDATE"][0]
    interrupt = events_by_name["INTERRUPT_CANDIDATE"][0]
    request = events_by_name["TTS_TRUNCATE_REQUESTED"][0]
    truncated = events_by_name["TTS_TRUNCATED"][0]

    if interrupt.get("caused_by_event_id") != candidate["event_id"]:
        raise MVP0AcceptanceError("INTERRUPT_CANDIDATE must be caused by BARGE_IN_CANDIDATE")
    if request.get("caused_by_event_id") != interrupt["event_id"]:
        raise MVP0AcceptanceError("TTS_TRUNCATE_REQUESTED must be caused by INTERRUPT_CANDIDATE")
    if request.get("interrupt_candidate_event_id") != interrupt["event_id"]:
        raise MVP0AcceptanceError("TTS_TRUNCATE_REQUESTED must reference interrupt candidate")
    if truncated.get("caused_by_event_id") != request["event_id"]:
        raise MVP0AcceptanceError("TTS_TRUNCATED must be caused by truncate request")
    if truncated.get("truncate_request_event_id") != request["event_id"]:
        raise MVP0AcceptanceError("TTS_TRUNCATED must reference truncate request")
    offsets = {
        int(candidate["playback_offset_ms"]),
        int(request["cutoff_playback_offset_ms"]),
        int(truncated["actual_stop_offset_ms"]),
    }
    if len(offsets) != 3:
        raise MVP0AcceptanceError("barge-in candidate, truncate cutoff, and actual stop offsets must differ")
    if result.playback_state.phase != "TRUNCATED":
        raise MVP0AcceptanceError("barge-in fixture did not replay to PlaybackState=TRUNCATED")
    _assert_playback_commit_is_delivery_marker_only(fixture["events"])
    _assert_mock_outputs_labeled(fixture["events"])

    return {
        "candidate_event_id": candidate["event_id"],
        "truncate_request_event_id": request["event_id"],
        "truncated_event_id": truncated["event_id"],
        "playback_phase": result.playback_state.phase,
        "offsets": {
            "candidate": candidate["playback_offset_ms"],
            "cutoff": request["cutoff_playback_offset_ms"],
            "actual_stop": truncated["actual_stop_offset_ms"],
        },
        "event_count": len(events_by_id),
    }


def _assert_mock_adapter_capability_scenario(fixture: Mapping[str, Any], result: ReplayResult) -> dict[str, Any]:
    events = _events_by_name(fixture)
    _require_event_names(events, ["SESSION_STARTED", "ADAPTER_CAPABILITY_SNAPSHOT_RECORDED"])
    snapshot = events["ADAPTER_CAPABILITY_SNAPSHOT_RECORDED"][0]
    output_modes = tuple(str(mode) for mode in snapshot["output_modes"])
    deployment_modes = tuple(str(mode) for mode in snapshot["deployment_modes"])
    if set(output_modes) != {"mock"}:
        raise MVP0AcceptanceError("MVP0 capability snapshot output modes must be mock")
    if set(deployment_modes) != {"mock"}:
        raise MVP0AcceptanceError("MVP0 capability snapshot deployment modes must be mock")
    if not result.adapter_health_state.adapters:
        raise MVP0AcceptanceError("adapter health state did not reconstruct mock adapters")

    return {
        "capability_snapshot_ref": result.adapter_health_state.capability_snapshot_ref,
        "adapter_ids": sorted(result.adapter_health_state.adapters),
        "output_modes": sorted(set(output_modes)),
    }


def _assert_local_trace_safety_scenario(fixture: Mapping[str, Any], result: ReplayResult) -> dict[str, Any]:
    events = _events_by_name(fixture)
    _require_event_names(
        events,
        [
            "TRACE_WRITE_DEGRADED",
            "TRACE_SECRET_REDACTION_APPLIED",
            "TRACE_WRITE_BLOCKED_SECRET_DETECTED",
            "REPLAY_STARTED",
            "REPLAY_COMPLETED",
        ],
    )
    manifest = fixture["replay_manifest"]
    if any(manifest[flag] is not False for flag in ALLOWED_MANIFEST_SAFETY_FLAGS):
        raise MVP0AcceptanceError("local trace safety fixture must keep all shareable safety flags false")
    trace_state = result.trace_privacy_state
    if trace_state.redaction_count < 1 or trace_state.blocked_write_count < 1:
        raise MVP0AcceptanceError("local trace safety fixture must replay redaction and blocked-write counters")
    if trace_state.replay_result_status != "passed":
        raise MVP0AcceptanceError("local trace safety replay did not finish as passed")

    return {
        "fixture_domain": trace_state.fixture_domain,
        "contains_raw_audio": trace_state.contains_raw_audio,
        "contains_raw_trace": trace_state.contains_raw_trace,
        "contains_secrets": trace_state.contains_secrets,
        "redaction_count": trace_state.redaction_count,
        "blocked_write_count": trace_state.blocked_write_count,
        "trace_write_degraded_count": trace_state.trace_write_degraded_count,
        "replay_result_status": trace_state.replay_result_status,
    }


def _compute_slo_measurements(
    slo_entries: object,
    fixture: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    entries = _sequence_or_empty(slo_entries, "slo_measurements")
    if not entries:
        return ()

    events_by_id = _events_by_id(fixture)
    measurements: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise MVP0AcceptanceError("slo_measurements entries must be objects")
        name = _required_str(entry, "name")
        start_event_id = _required_str(entry, "start_event_id")
        end_event_id = _required_str(entry, "end_event_id")
        output_mode = _required_str(entry, "output_mode")
        if output_mode not in MVP0_OUTPUT_MODES:
            raise MVP0AcceptanceError("SLO output_mode must be mock, degraded, fallback, or real")
        if not isinstance(entry.get("max_latency_ms"), int):
            raise MVP0AcceptanceError("SLO max_latency_ms must be an integer")
        max_latency_ms = int(entry["max_latency_ms"])
        try:
            start_event = events_by_id[start_event_id]
            end_event = events_by_id[end_event_id]
        except KeyError as exc:
            raise MVP0AcceptanceError(f"SLO event id not found: {exc}") from exc
        latency_ms = int(end_event["created_monotonic_ms"]) - int(start_event["created_monotonic_ms"])
        if latency_ms < 0:
            raise MVP0AcceptanceError(f"SLO {name} produced negative latency")
        if int(end_event["event_seq"]) < int(start_event["event_seq"]):
            raise MVP0AcceptanceError(f"SLO {name} end event must not precede start event")
        result_status = "passed" if latency_ms <= max_latency_ms else "failed"
        if result_status != "passed":
            raise MVP0AcceptanceError(f"SLO {name} exceeded {max_latency_ms}ms")
        measurements.append(
            {
                "name": name,
                "latency_ms": latency_ms,
                "max_latency_ms": max_latency_ms,
                "output_mode": output_mode,
                "result_status": result_status,
            }
        )
    return tuple(measurements)


def _assert_github_allowed_fixture(fixture: Mapping[str, Any]) -> None:
    manifest = _required_mapping(fixture, "replay_manifest")
    if manifest.get("fixture_domain") != "GITHUB_ALLOWED":
        raise MVP0AcceptanceError("fixture_domain must be GITHUB_ALLOWED")
    if manifest.get("generated_from") not in {"synthetic", "redacted", "hand_written_minimal"}:
        raise MVP0AcceptanceError("GitHub fixtures must be synthetic, redacted, or hand_written_minimal")
    if any(manifest.get(flag) is not False for flag in ALLOWED_MANIFEST_SAFETY_FLAGS):
        raise MVP0AcceptanceError("GitHub fixture safety flags must all be false")

    for path, value in _iter_json_values(fixture):
        last_key = path[-1] if path else ""
        if path[:1] == ("replay_manifest",) and last_key in ALLOWED_MANIFEST_SAFETY_FLAGS:
            if value is not False:
                raise MVP0AcceptanceError(f"unsafe manifest safety flag: {'.'.join(path)}")
            continue
        if last_key in ALLOWED_SAFE_SECRET_METADATA_KEYS:
            if not isinstance(value, str) or value.lower().startswith(("sk-", "bearer ")):
                raise MVP0AcceptanceError(f"unsafe secret metadata: {'.'.join(path)}")
            continue
        if any(pattern.search(last_key) for pattern in FORBIDDEN_FIXTURE_KEY_PATTERNS):
            raise MVP0AcceptanceError(f"forbidden fixture key: {'.'.join(path)}")
        if isinstance(value, str):
            lower_value = value.lower()
            if lower_value.startswith(("sk-", "bearer ")):
                raise MVP0AcceptanceError(f"forbidden secret-like fixture value: {'.'.join(path)}")
            if any(lower_value.endswith(extension) for extension in RAW_AUDIO_EXTENSIONS):
                raise MVP0AcceptanceError(f"forbidden raw audio ref: {'.'.join(path)}")
            if any(marker in lower_value for marker in ("audio/raw/", "traces/", "diagnostics/", "replays/local/")):
                raise MVP0AcceptanceError(f"forbidden local artifact ref: {'.'.join(path)}")
            if "raw trace" in lower_value or "real user" in lower_value:
                raise MVP0AcceptanceError(f"forbidden raw trace or real user marker: {'.'.join(path)}")


def _assert_playback_commit_is_delivery_marker_only(events: Sequence[Mapping[str, Any]]) -> None:
    forbidden_keys = {
        "semantic_acknowledgement",
        "semantic_confirmation",
        "user_acknowledgement",
        "user_confirmation",
        "acknowledgement_basis",
    }
    for event in events:
        if event.get("event_name") != "PLAYBACK_COMMITTED":
            continue
        if forbidden_keys & set(event):
            raise MVP0AcceptanceError("PLAYBACK_COMMITTED must not carry acknowledgement or confirmation fields")
        commit_basis = str(event.get("commit_basis", ""))
        if "delivery" not in commit_basis:
            raise MVP0AcceptanceError("PLAYBACK_COMMITTED must remain a delivery marker")


def _assert_mock_outputs_labeled(events: Sequence[Mapping[str, Any]]) -> None:
    for event in events:
        event_name = str(event.get("event_name", ""))
        if event_name in {"MOCK_ASR_FRAME_EMITTED", "MOCK_THINKER_FRAME_EMITTED"}:
            if event.get("output_mode") != "mock":
                raise MVP0AcceptanceError(f"{event_name} must be labeled output_mode=mock")
        if event_name.startswith("PLAYBACK_") or event_name in {"BARGE_IN_CANDIDATE", "TTS_TRUNCATED"}:
            if "output_mode" in event and event["output_mode"] != "mock":
                raise MVP0AcceptanceError(f"{event_name} mock output must be labeled output_mode=mock")


def _require_event_names(events_by_name: Mapping[str, Sequence[Mapping[str, Any]]], event_names: Sequence[str]) -> None:
    missing = [event_name for event_name in event_names if event_name not in events_by_name]
    if missing:
        raise MVP0AcceptanceError(f"Missing expected MVP0 scenario events: {missing}")


def _events_by_name(fixture: Mapping[str, Any]) -> dict[str, list[Mapping[str, Any]]]:
    events_by_name: dict[str, list[Mapping[str, Any]]] = {}
    for event in _required_sequence(fixture, "events"):
        if not isinstance(event, Mapping):
            raise MVP0AcceptanceError("fixture events must be objects")
        events_by_name.setdefault(str(event["event_name"]), []).append(event)
    return events_by_name


def _events_by_id(fixture: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {str(event["event_id"]): event for event in _required_sequence(fixture, "events") if isinstance(event, Mapping)}


def _iter_json_values(value: Any, path: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], Any]]:
    values = [(path, value)]
    if isinstance(value, Mapping):
        for key, child in value.items():
            values.extend(_iter_json_values(child, (*path, str(key))))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            values.extend(_iter_json_values(child, (*path, str(index))))
    return values


def _load_fixture(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise MVP0AcceptanceError(f"Fixture not found: {path.name}")
    with path.open(encoding="utf-8") as fixture_file:
        loaded = json.load(fixture_file)
    if not isinstance(loaded, dict):
        raise MVP0AcceptanceError(f"Fixture must contain a JSON object: {path.name}")
    return loaded


def _required_mapping(mapping: Mapping[str, Any], field: str) -> Mapping[str, Any]:
    value = mapping.get(field)
    if not isinstance(value, Mapping):
        raise MVP0AcceptanceError(f"{field} must be an object")
    return value


def _required_sequence(mapping: Mapping[str, Any], field: str) -> Sequence[Any]:
    value = mapping.get(field)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise MVP0AcceptanceError(f"{field} must be a list")
    return value


def _sequence_or_empty(value: object, field: str) -> Sequence[Any]:
    if value in (None, ()):
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise MVP0AcceptanceError(f"{field} must be a list")
    return value


def _required_str(mapping: Mapping[str, Any], field: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value:
        raise MVP0AcceptanceError(f"{field} must be a non-empty string")
    return value


def _string_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise MVP0AcceptanceError(f"{field} must be a list of strings")
    if not all(isinstance(item, str) and item for item in value):
        raise MVP0AcceptanceError(f"{field} must be a list of non-empty strings")
    return tuple(value)
