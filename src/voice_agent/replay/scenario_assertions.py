from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from voice_agent.replay.runner import ReplayResult, run_replay_fixture


class MVP0AcceptanceError(AssertionError):
    pass


MVP0_REQUIRED_SCENARIOS = (
    "MVP0-TEXT-INGRESS-001",
    "MVP0-AUDIO-INGRESS-001",
    "MVP0-BARGE-IN-TRUNCATE-001",
    "MVP0-MOCK-ADAPTER-CAPABILITY-001",
    "MVP0-LOCAL-TRACE-SAFETY-001",
)
MVP0_OUTPUT_MODES = frozenset({"mock", "degraded", "fallback", "real"})
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
        "TOOL_PROGRESS_UPDATED",
        "TOOL_UI_STATE_PATCHED",
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
