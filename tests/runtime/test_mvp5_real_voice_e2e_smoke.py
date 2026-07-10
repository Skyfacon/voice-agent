from __future__ import annotations

import base64
import json
from pathlib import Path
import wave

import pytest

from voice_agent.adapters.asr_fake_transport import FakeAsrProviderResponse, FakeAsrTransport
from voice_agent.adapters.asr_live_transport import AsrLiveProviderCallMetadata
from voice_agent.adapters.adapter_timing import AdapterTimingSnapshot
from voice_agent.adapters.fast_interaction_live_transport import FastInteractionProviderCompletion
from voice_agent.adapters.lalm_thinker_runtime_adapter import LALM_THINKER_RUNTIME_MODEL_ALIAS
import voice_agent.runtime.mvp5_live_voice_evidence as live_voice_evidence_module
from voice_agent.runtime.mvp5_real_voice_e2e_smoke import (
    MVP5RealVoiceE2ESmokeError,
    MVP5SmokePackCase,
    main,
    run_mvp5_real_voice_e2e_pack,
    run_mvp5_real_voice_e2e_single,
)


def test_single_wav_smoke_outputs_metadata_only_actual_router_outcome(
    tmp_path: Path,
) -> None:
    wav_path = tmp_path / "private-fast-input.wav"
    wav_bytes = _write_wav_file(wav_path)
    approval_packet = _approval_packet()

    metadata = run_mvp5_real_voice_e2e_single(
        local_wav=wav_path,
        live_provider=True,
        allow_local_wav=True,
        approval_packet=approval_packet,
        expected_route="FAST_ONLY",
        run_id="mvp5-goal4-single-fast",
        env={"MVP5_TEST_PROVIDER_KEY": "DUMMY_TEST_CREDENTIAL_THAT_MUST_NOT_LEAK"},
        asr_transport=_fake_asr_transport("single-fast"),
        thinker_transport=_FakeThinkerAudioTransport(fake_route="FAST_ONLY"),
    )

    rendered = json.dumps(metadata, sort_keys=True)
    assert metadata["run_id"] == "mvp5-goal4-single-fast"
    assert metadata["mode"] == "single"
    assert metadata["status"] == "routed"
    assert metadata["route_result_kind"] == "direct_answer"
    assert metadata["actual_route"] == "FAST_ONLY"
    assert metadata["router_decision"] == "FAST_ONLY"
    assert metadata["expected_route"] == "FAST_ONLY"
    assert metadata["expected_route_matched"] is True
    assert metadata["asr_output_mode"] == "real"
    assert metadata["thinker_output_mode"] == "real"
    assert metadata["provider_call_used"] is False
    assert metadata["fake_transport_used"] is True
    assert metadata["raw_audio_included"] is False
    assert metadata["raw_transcript_included"] is False
    assert metadata["raw_provider_body_included"] is False
    assert metadata["prompt_dump_included"] is False
    assert metadata["secret_included"] is False
    assert metadata["local_wav_path_included"] is False
    assert metadata["local_pack_path_included"] is False
    assert metadata["replay_reruns_provider"] is False
    assert metadata["real_tts_used"] is False
    assert metadata["voice_output"] == "none"
    assert "ROUTER_DECISION_EMITTED" in metadata["event_names"]
    assert str(wav_path) not in rendered
    assert wav_path.name not in rendered
    assert "DUMMY_TEST_CREDENTIAL_THAT_MUST_NOT_LEAK" not in rendered
    assert base64.b64encode(wav_bytes).decode("ascii") not in rendered


def test_single_fast_interaction_primary_uses_one_audio_native_provider_call(
    tmp_path: Path,
) -> None:
    wav_path = tmp_path / "private-fast-interaction-input.wav"
    wav_bytes = _write_wav_file(wav_path)
    fast_transport = _FakeFastInteractionTransport()

    metadata = run_mvp5_real_voice_e2e_single(
        local_wav=wav_path,
        live_provider=True,
        allow_local_wav=True,
        approval_packet=_fast_approval_packet(max_provider_calls=1),
        expected_route="FAST_ONLY",
        run_id="mvp63-goal4-single-fast-interaction",
        env={"MVP63_TEST_PROVIDER_KEY": "DUMMY_TEST_CREDENTIAL_THAT_MUST_NOT_LEAK"},
        asr_transport=_ExplodingAsrTransport(),
        thinker_transport=_ExplodingThinkerTransport(),
        fast_interaction_transport=fast_transport,
        fast_interaction_enabled=True,
        audio_native_thinker_enabled=False,
    )

    rendered = json.dumps(metadata, sort_keys=True)
    latency_debug = metadata["latency_debug"]
    assert metadata["status"] == "routed"
    assert metadata["actual_route"] == "FAST_ONLY"
    assert metadata["route_result_kind"] == "direct_answer"
    assert metadata["asr_output_mode"] is None
    assert metadata["thinker_output_mode"] is None
    assert metadata["fast_interaction_output_mode"] == "real"
    assert metadata["foreground_gate_decision"] == "passed"
    assert metadata["foreground_output_basis"] == "reply_candidate"
    assert metadata["evidence_ref_policy"] == "preserve_fast_ref"
    assert metadata["provider_call_used"] is False
    assert metadata["fake_transport_used"] is True
    assert latency_debug["fast_interaction_input_mode"] == "audio_native"
    assert latency_debug["fast_interaction_provider_ttft_ms"] == 20
    assert latency_debug["fast_interaction_total_ms"] >= 0
    assert fast_transport.call_count == 1
    assert fast_transport.input_mode_seen == "audio_native"
    assert str(wav_path) not in rendered
    assert wav_path.name not in rendered
    assert "DUMMY_TEST_CREDENTIAL_THAT_MUST_NOT_LEAK" not in rendered
    assert "A tiny safe spooky story." not in rendered
    assert base64.b64encode(wav_bytes).decode("ascii") not in rendered


def test_single_fast_qa_runs_asr_observation_without_delaying_fast_gate(
    tmp_path: Path,
) -> None:
    wav_path = tmp_path / "private-fast-qa-input.wav"
    _write_wav_file(wav_path)
    fast_transport = _FakeFastInteractionTransport()

    metadata = run_mvp5_real_voice_e2e_single(
        local_wav=wav_path,
        live_provider=True,
        allow_local_wav=True,
        approval_packet=_fast_approval_packet(
            max_provider_calls=2,
            asr_observation=True,
        ),
        expected_route="FAST_ONLY",
        run_id="mvp63-goal4-single-fast-qa",
        env={"MVP63_TEST_PROVIDER_KEY": "DUMMY_TEST_CREDENTIAL_THAT_MUST_NOT_LEAK"},
        asr_transport=_fake_asr_transport("mvp63-fast-qa"),
        thinker_transport=_ExplodingThinkerTransport(),
        fast_interaction_transport=fast_transport,
        fast_interaction_enabled=True,
        audio_native_thinker_enabled=False,
        asr_observation_enabled=True,
    )

    event_names = metadata["event_names"]
    latency_debug = metadata["latency_debug"]
    assert metadata["status"] == "routed"
    assert metadata["actual_route"] == "FAST_ONLY"
    assert metadata["asr_output_mode"] == "real"
    assert metadata["asr_observation_enabled"] is True
    assert metadata["asr_observation_status"] == "completed"
    assert metadata["asr_observation_event_id"] == metadata["question_event_id"]
    assert str(metadata["question_text_ref"]).startswith("text://synthetic/")
    assert metadata["fast_interaction_output_mode"] == "real"
    assert metadata["evidence_ref_policy"] == "preserve_fast_ref"
    assert event_names.index("FOREGROUND_OUTPUT_COMMITTED") < event_names.index(
        "ASR_TRANSCRIPT_OUTPUT_EMITTED"
    )
    assert latency_debug["provider_calls_parallel"] is True
    assert latency_debug["fast_answer_ready_offset_ms"] <= latency_debug[
        "qa_pair_ready_offset_ms"
    ]


def test_three_route_pack_reports_case_ids_actual_routes_and_metadata_only_output(
    tmp_path: Path,
) -> None:
    pack_path = tmp_path / "private-three-route-pack.json"
    wav_paths = {
        "direct": tmp_path / "direct-private.wav",
        "spawn": tmp_path / "spawn-private.wav",
        "patch": tmp_path / "patch-private.wav",
    }
    wav_bytes = b"".join(_write_wav_file(path) for path in wav_paths.values())
    _write_pack(
        pack_path,
        cases=[
            {
                "case_id": "direct",
                "local_wav": str(wav_paths["direct"]),
                "expected_route": "FAST_ONLY",
            },
            {
                "case_id": "spawn",
                "local_wav": str(wav_paths["spawn"]),
                "expected_route": "SPAWN_SLOW_TASK",
            },
            {
                "case_id": "patch",
                "local_wav": str(wav_paths["patch"]),
                "expected_route": "PATCH_ACTIVE_SLOW_TASK",
                "active_task_context": {
                    "task_id": "task_mvp5_local_pack_active",
                    "current_plan_version": 1,
                    "current_task_event_seq": 1,
                },
            },
        ],
    )

    metadata = run_mvp5_real_voice_e2e_pack(
        pack_json=pack_path,
        live_provider=True,
        approval_packet=_approval_packet(max_provider_calls=6),
        run_id="mvp5-goal4-pack",
        env={"MVP5_TEST_PROVIDER_KEY": "DUMMY_TEST_CREDENTIAL_THAT_MUST_NOT_LEAK"},
        transport_factory=_transport_factory_from_expected_route,
    )

    rendered = json.dumps(metadata, sort_keys=True)
    cases_by_id = {case["case_id"]: case for case in metadata["cases"]}
    assert metadata["run_id"] == "mvp5-goal4-pack"
    assert metadata["mode"] == "three_route_pack"
    assert metadata["pack_id"] == "local-mvp5-pack-001"
    assert metadata["status"] == "passed"
    assert metadata["aggregate_status"] == "passed"
    assert metadata["mismatches"] == []
    assert set(cases_by_id) == {"direct", "spawn", "patch"}
    assert cases_by_id["direct"]["expected_route"] == "FAST_ONLY"
    assert cases_by_id["direct"]["actual_route"] == "FAST_ONLY"
    assert cases_by_id["direct"]["route_result_kind"] == "direct_answer"
    assert cases_by_id["spawn"]["expected_route"] == "SPAWN_SLOW_TASK"
    assert cases_by_id["spawn"]["actual_route"] == "SPAWN_SLOW_TASK"
    assert cases_by_id["spawn"]["route_result_kind"] == "slowtask_spawn"
    assert cases_by_id["patch"]["expected_route"] == "PATCH_ACTIVE_SLOW_TASK"
    assert cases_by_id["patch"]["actual_route"] == "PATCH_ACTIVE_SLOW_TASK"
    assert cases_by_id["patch"]["route_result_kind"] == "user_patch"
    assert cases_by_id["patch"]["task_id"] == "task_mvp5_local_pack_active"
    assert cases_by_id["patch"]["user_patch_event_ids"]
    assert "USER_PATCH_INTERPRETED" not in cases_by_id["patch"]["event_names"]
    assert "PLAN_VERSION_ADVANCED" not in cases_by_id["patch"]["event_names"]
    assert metadata["raw_audio_included"] is False
    assert metadata["raw_transcript_included"] is False
    assert metadata["raw_provider_body_included"] is False
    assert metadata["prompt_dump_included"] is False
    assert metadata["secret_included"] is False
    assert metadata["local_wav_path_included"] is False
    assert metadata["local_pack_path_included"] is False
    assert metadata["provider_call_used"] is False
    assert metadata["fake_transport_used"] is True
    assert str(pack_path) not in rendered
    assert pack_path.name not in rendered
    for wav_path in wav_paths.values():
        assert str(wav_path) not in rendered
        assert wav_path.name not in rendered
    assert "DUMMY_TEST_CREDENTIAL_THAT_MUST_NOT_LEAK" not in rendered
    assert base64.b64encode(wav_bytes).decode("ascii") not in rendered


def test_pack_mismatch_reports_actual_router_decision_without_forcing_route(
    tmp_path: Path,
) -> None:
    pack_path = tmp_path / "private-mismatch-pack.json"
    wav_path = tmp_path / "mismatch-private.wav"
    _write_wav_file(wav_path)
    _write_pack(
        pack_path,
        cases=[
            {
                "case_id": "mismatch",
                "local_wav": str(wav_path),
                "expected_route": "FAST_ONLY",
            }
        ],
    )

    metadata = run_mvp5_real_voice_e2e_pack(
        pack_json=pack_path,
        live_provider=True,
        approval_packet=_approval_packet(max_provider_calls=2),
        run_id="mvp5-goal4-pack-mismatch",
        env={"MVP5_TEST_PROVIDER_KEY": "DUMMY_TEST_CREDENTIAL"},
        transport_factory=lambda case: (
            _fake_asr_transport(case.case_id),
            _FakeThinkerAudioTransport(fake_route="SPAWN_SLOW_TASK"),
        ),
    )

    mismatch = metadata["cases"][0]
    assert metadata["status"] == "route_mismatch"
    assert metadata["aggregate_status"] == "route_mismatch"
    assert metadata["mismatches"] == [
        {
            "case_id": "mismatch",
            "expected_route": "FAST_ONLY",
            "actual_route": "SPAWN_SLOW_TASK",
        }
    ]
    assert mismatch["status"] == "route_mismatch"
    assert mismatch["expected_route"] == "FAST_ONLY"
    assert mismatch["actual_route"] == "SPAWN_SLOW_TASK"
    assert mismatch["expected_route_matched"] is False
    assert mismatch["route_result_kind"] == "mismatch"
    assert "SLOWTASK_CREATED" not in mismatch["event_names"]
    assert "USER_PATCH_RECEIVED" not in mismatch["event_names"]
    assert "PLAN_VERSION_ADVANCED" not in mismatch["event_names"]


def test_pack_patch_case_requires_active_task_context(tmp_path: Path) -> None:
    pack_path = tmp_path / "private-invalid-patch-pack.json"
    wav_path = tmp_path / "patch-private.wav"
    _write_wav_file(wav_path)
    _write_pack(
        pack_path,
        cases=[
            {
                "case_id": "patch",
                "local_wav": str(wav_path),
                "expected_route": "PATCH_ACTIVE_SLOW_TASK",
            }
        ],
    )

    with pytest.raises(MVP5RealVoiceE2ESmokeError, match="active_task_context"):
        run_mvp5_real_voice_e2e_pack(
            pack_json=pack_path,
            live_provider=True,
            approval_packet=_approval_packet(max_provider_calls=2),
            env={"MVP5_TEST_PROVIDER_KEY": "DUMMY_TEST_CREDENTIAL"},
            transport_factory=_transport_factory_from_expected_route,
        )


def test_main_prints_single_json_metadata_with_injected_provider_free_transports(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    wav_path = tmp_path / "cli-private.wav"
    _write_wav_file(wav_path)
    approval_path = tmp_path / "approval-private.json"
    approval_path.write_text(json.dumps(_approval_packet()), encoding="utf-8")

    exit_code = main(
        [
            "--live-provider",
            "--allow-local-wav",
            "--local-wav",
            str(wav_path),
            "--expected-route",
            "FAST_ONLY",
            "--approval-packet",
            str(approval_path),
        ],
        env={"MVP5_TEST_PROVIDER_KEY": "DUMMY_TEST_CREDENTIAL"},
        single_transport_factory=lambda: (
            _fake_asr_transport("cli-single"),
            _FakeThinkerAudioTransport(fake_route="FAST_ONLY"),
        ),
    )

    captured = capsys.readouterr()
    metadata = json.loads(captured.out)
    rendered = json.dumps(metadata, sort_keys=True)
    assert exit_code == 0
    assert metadata["mode"] == "single"
    assert metadata["actual_route"] == "FAST_ONLY"
    assert metadata["provider_call_used"] is False
    assert metadata["fake_transport_used"] is True
    assert str(wav_path) not in rendered
    assert wav_path.name not in rendered
    assert str(approval_path) not in rendered
    assert approval_path.name not in rendered


def test_main_provider_free_fake_route_mode_outputs_actual_route_without_env_secret(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    wav_path = tmp_path / "cli-fake-private.wav"
    _write_wav_file(wav_path)
    approval_path = tmp_path / "approval-fake-private.json"
    approval_path.write_text(json.dumps(_approval_packet()), encoding="utf-8")

    exit_code = main(
        [
            "--live-provider",
            "--allow-local-wav",
            "--local-wav",
            str(wav_path),
            "--expected-route",
            "FAST_ONLY",
            "--approval-packet",
            str(approval_path),
            "--provider-free-fake-route",
            "FAST_ONLY",
        ],
        env={},
    )

    captured = capsys.readouterr()
    metadata = json.loads(captured.out)
    rendered = json.dumps(metadata, sort_keys=True)
    assert exit_code == 0
    assert metadata["mode"] == "single"
    assert metadata["actual_route"] == "FAST_ONLY"
    assert metadata["provider_call_used"] is False
    assert metadata["fake_transport_used"] is True
    assert metadata["raw_provider_body_included"] is False
    assert str(wav_path) not in rendered
    assert wav_path.name not in rendered
    assert "DUMMY_TEST_CREDENTIAL" not in rendered


def test_main_single_active_task_context_produces_patch_route_in_provider_free_fake_mode(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    wav_path = tmp_path / "cli-fake-patch-private.wav"
    _write_wav_file(wav_path)
    approval_path = tmp_path / "approval-fake-patch-private.json"
    approval_path.write_text(json.dumps(_approval_packet()), encoding="utf-8")

    exit_code = main(
        [
            "--live-provider",
            "--allow-local-wav",
            "--local-wav",
            str(wav_path),
            "--expected-route",
            "PATCH_ACTIVE_SLOW_TASK",
            "--active-task-id",
            "task_local_active",
            "--active-plan-version",
            "1",
            "--active-task-event-seq",
            "1",
            "--active-lifecycle-phase",
            "PLANNING",
            "--approval-packet",
            str(approval_path),
            "--provider-free-fake-route",
            "PATCH_ACTIVE_SLOW_TASK",
        ],
        env={},
    )

    captured = capsys.readouterr()
    metadata = json.loads(captured.out)
    rendered = json.dumps(metadata, sort_keys=True)
    assert exit_code == 0
    assert metadata["mode"] == "single"
    assert metadata["actual_route"] == "PATCH_ACTIVE_SLOW_TASK"
    assert metadata["route_result_kind"] == "user_patch"
    assert metadata["task_id"] == "task_local_active"
    assert metadata["provider_call_used"] is False
    assert metadata["fake_transport_used"] is True
    assert str(wav_path) not in rendered
    assert wav_path.name not in rendered
    assert str(approval_path) not in rendered
    assert approval_path.name not in rendered


def test_real_provider_mode_constructs_adapter_transports_without_fake_route_or_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wav_path = tmp_path / "real-provider-private.wav"
    _write_wav_file(wav_path)
    fake_asr = _ConstructedRealAsrTransport()
    fake_thinker = _ConstructedRealThinkerTransport(fake_route="FAST_ONLY")

    monkeypatch.setattr(
        live_voice_evidence_module,
        "_default_asr_live_transport",
        lambda: fake_asr,
    )
    monkeypatch.setattr(
        live_voice_evidence_module,
        "LALMThinkerLiveDirectHTTPTransport",
        lambda: fake_thinker,
    )

    metadata = run_mvp5_real_voice_e2e_single(
        local_wav=wav_path,
        live_provider=True,
        allow_local_wav=True,
        approval_packet=_approval_packet(),
        expected_route="FAST_ONLY",
        run_id="mvp5-real-provider-constructed",
        env={"MVP5_TEST_PROVIDER_KEY": "DUMMY_TEST_CREDENTIAL_THAT_MUST_NOT_LEAK"},
    )

    rendered = json.dumps(metadata, sort_keys=True)
    assert metadata["status"] == "routed"
    assert metadata["actual_route"] == "FAST_ONLY"
    assert metadata["provider_call_used"] is True
    assert metadata["fake_transport_used"] is False
    assert metadata["asr_output_mode"] == "degraded"
    assert metadata["thinker_output_mode"] == "real"
    assert fake_asr.call_count == 1
    assert fake_thinker.call_count == 1
    assert str(wav_path) not in rendered
    assert wav_path.name not in rendered
    assert "DUMMY_TEST_CREDENTIAL_THAT_MUST_NOT_LEAK" not in rendered
    assert "synthetic transcript" not in rendered


def test_single_wav_smoke_reports_incomplete_evidence_without_router_traceback(
    tmp_path: Path,
) -> None:
    wav_path = tmp_path / "real-provider-validation-failure.wav"
    wav_bytes = _write_wav_file(wav_path)

    metadata = run_mvp5_real_voice_e2e_single(
        local_wav=wav_path,
        live_provider=True,
        allow_local_wav=True,
        approval_packet=_approval_packet(),
        expected_route="auto",
        run_id="mvp5-real-provider-validation-failure",
        env={"MVP5_TEST_PROVIDER_KEY": "DUMMY_TEST_CREDENTIAL_THAT_MUST_NOT_LEAK"},
        asr_transport=_fake_asr_transport("validation-failure"),
        thinker_transport=_MalformedThinkerAudioTransport(),
    )

    rendered = json.dumps(metadata, sort_keys=True)
    assert metadata["status"] == "evidence_failed"
    assert metadata["route_result_kind"] == "blocked"
    assert metadata["actual_route"] is None
    assert metadata["router_decision"] is None
    assert metadata["expected_route"] == "auto"
    assert metadata["asr_output_mode"] == "real"
    assert metadata["thinker_output_mode"] is None
    assert metadata["failure_reasons"] == ["invalid_json"]
    assert metadata["provider_call_used"] is False
    assert metadata["fake_transport_used"] is True
    assert metadata["raw_provider_body_included"] is False
    assert str(wav_path) not in rendered
    assert wav_path.name not in rendered
    assert base64.b64encode(wav_bytes).decode("ascii") not in rendered


def test_single_wav_smoke_accepts_fenced_thinker_json_and_routes(
    tmp_path: Path,
) -> None:
    wav_path = tmp_path / "real-provider-fenced-json.wav"
    _write_wav_file(wav_path)

    metadata = run_mvp5_real_voice_e2e_single(
        local_wav=wav_path,
        live_provider=True,
        allow_local_wav=True,
        approval_packet=_approval_packet(),
        expected_route="FAST_ONLY",
        run_id="mvp5-real-provider-fenced-json",
        env={"MVP5_TEST_PROVIDER_KEY": "DUMMY_TEST_CREDENTIAL_THAT_MUST_NOT_LEAK"},
        asr_transport=_fake_asr_transport("fenced-json"),
        thinker_transport=_FencedThinkerAudioTransport(fake_route="FAST_ONLY"),
    )

    rendered = json.dumps(metadata, sort_keys=True)
    assert metadata["status"] == "routed"
    assert metadata["actual_route"] == "FAST_ONLY"
    assert metadata["router_decision"] == "FAST_ONLY"
    assert metadata["thinker_output_mode"] == "real"
    assert "fenced_markdown" not in rendered
    assert "```json" not in rendered


def _transport_factory_from_expected_route(
    case: MVP5SmokePackCase,
) -> tuple[FakeAsrTransport, _FakeThinkerAudioTransport]:
    return _fake_asr_transport(case.case_id), _FakeThinkerAudioTransport(
        fake_route=case.expected_route,
    )


def _fake_asr_transport(route_slug: str) -> FakeAsrTransport:
    return FakeAsrTransport(
        (
            FakeAsrProviderResponse.success(
                asr_frame_ref=f"asr-frame://synthetic/mvp5/goal4/{route_slug}",
                text_ref=f"text://synthetic/mvp5/goal4/{route_slug}",
                audio_timestamps_ref=f"audio-timestamps://synthetic/mvp5/goal4/{route_slug}",
                streaming_status="supported",
                confidence_score=0.91,
            ),
        )
    )


class _FakeFastInteractionTransport:
    def __init__(self) -> None:
        self.call_count = 0
        self.input_mode_seen: str | None = None

    def complete_audio_with_timing(
        self,
        *,
        request_payload: dict[str, object],
        audio_bytes: bytes,
        audio_format: str,
        credential_handle: object,
        credential_value: str,
        adapter_request_id: str,
        timeout_ms: int,
        model_alias: str,
        turn_ingress_monotonic_ms: int,
    ) -> FastInteractionProviderCompletion:
        self.call_count += 1
        self.input_mode_seen = str(request_payload["input_mode"])
        assert self.input_mode_seen == "audio_native"
        assert audio_bytes
        assert audio_format == "wav"
        assert credential_value.startswith("DUMMY_TEST_CREDENTIAL")
        assert adapter_request_id.startswith("adapter-request-mvp63-fast-interaction-")
        assert timeout_ms == 1_500
        assert model_alias == "qwen3.5-omni-flash"
        assert turn_ingress_monotonic_ms > 0
        assert "secret_materialized=False" in repr(credential_handle)
        return FastInteractionProviderCompletion(
            provider_text=json.dumps(
                {
                    "schema_name": "voice_agent.fast_interaction.output.v1",
                    "route_hint": {"router_decision_candidate": "FAST_ONLY"},
                    "route_prelude": {"summary": "single smoke fast interaction"},
                    "foreground_act": "ANSWER",
                    "reply_candidate": "A tiny safe spooky story.",
                    "final_fast_evidence": {"label": "single_smoke"},
                    "risk_tags": ["low_risk", "no_side_effects"],
                    "risk_class": "LOW",
                    "confidence": 0.91,
                    "output_mode": "real",
                    "boundary_assertions": {
                        "candidate_is_not_semantic_commitment": True,
                        "may_authorize_tools": False,
                        "may_execute_tools": False,
                        "may_accept_confirmation": False,
                        "may_mutate_slowtask_facts": False,
                        "runtime_gate_owns_display": True,
                    },
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
            timing=_fast_timing_snapshot(),
        )


class _ExplodingAsrTransport:
    def transcribe(self, **_kwargs: object) -> object:
        raise AssertionError("ASR must not run in MVP6.3 audio-native fast primary path")


class _ExplodingThinkerTransport:
    def complete_audio(self, **_kwargs: object) -> str:
        raise AssertionError("audio-native Thinker must not run in MVP6.3 fast primary path")


class _FakeThinkerAudioTransport:
    def __init__(self, *, fake_route: str) -> None:
        self.fake_route = fake_route

    def complete_audio(
        self,
        *,
        request_payload: object,
        audio_bytes: bytes,
        audio_format: str,
        credential_handle: object,
        credential_value: str,
        adapter_request_id: str,
        timeout_ms: int,
        model_alias: str,
    ) -> str:
        assert isinstance(request_payload, dict)
        assert audio_bytes
        assert audio_format == "wav"
        assert credential_value.startswith("DUMMY_TEST_CREDENTIAL")
        assert adapter_request_id.startswith("adapter-request-mvp5-thinker-")
        assert timeout_ms == 30_000
        assert model_alias == LALM_THINKER_RUNTIME_MODEL_ALIAS
        skeleton = dict(request_payload["required_output_skeleton"])
        skeleton["output_mode"] = "real"
        skeleton["optional_evidence_refs"] = {
            "semantic_close": {"status": "available", "label": "closed"},
            "assistant_directedness": {"status": "available", "label": "directed"},
            "emotion": {"status": "available", "label": "neutral"},
            "audio_caption": {"status": "available", "label": "speech_available"},
        }
        if self.fake_route == "FAST_ONLY":
            skeleton["task_focus_hint"] = {
                "focus": "FOREGROUND_CHAT",
                "task_like": False,
                "complexity_hint": "simple",
                "focus_confidence": 0.86,
                "evidence_uncertainty": "low",
            }
        elif self.fake_route == "SPAWN_SLOW_TASK":
            skeleton["task_focus_hint"] = {
                "focus": "NEW_TASK_CANDIDATE",
                "task_like": True,
                "complexity_hint": "complex",
                "focus_confidence": 0.9,
                "evidence_uncertainty": "low",
            }
        elif self.fake_route == "PATCH_ACTIVE_SLOW_TASK":
            skeleton["task_focus_hint"] = {
                "focus": "ACTIVE_TASK_PATCH",
                "task_like": True,
                "complexity_hint": "medium",
                "focus_confidence": 0.92,
                "evidence_uncertainty": "low",
            }
        else:
            raise AssertionError(f"unsupported fake route: {self.fake_route}")
        return json.dumps(skeleton, separators=(",", ":"), sort_keys=True)


def _approval_packet(*, max_provider_calls: int = 2) -> dict[str, object]:
    return {
        "approval_id": "mvp5-live-smoke-goal4-test",
        "live_provider_opt_in": True,
        "local_wav_opt_in": True,
        "metadata_only_output": True,
        "replay_reruns_provider": False,
        "provider_adapter_ids": ["mvp5_asr_adapter", "mvp5_thinker_adapter"],
        "credential_env_var_name": "MVP5_TEST_PROVIDER_KEY",
        "max_provider_calls": max_provider_calls,
        "timeout_ms": 30_000,
        "safe_output_ref": "summary://mvp5/goal4/real-voice-e2e-test",
    }


def _fast_approval_packet(
    *,
    max_provider_calls: int = 1,
    asr_observation: bool = False,
) -> dict[str, object]:
    adapter_ids = ["mvp63_fast_interaction_runtime"]
    if asr_observation:
        adapter_ids = ["mvp5_asr_adapter", "mvp63_fast_interaction_runtime"]
    return {
        "approval_id": "mvp63-live-smoke-fast-interaction-test",
        "live_provider_opt_in": True,
        "local_wav_opt_in": True,
        "metadata_only_output": True,
        "replay_reruns_provider": False,
        "provider_adapter_ids": adapter_ids,
        "credential_env_var_name": "MVP63_TEST_PROVIDER_KEY",
        "max_provider_calls": max_provider_calls,
        "timeout_ms": 1_500,
        "safe_output_ref": "summary://mvp63/goal4/fast-interaction-e2e-test",
    }


def _fast_timing_snapshot() -> AdapterTimingSnapshot:
    return AdapterTimingSnapshot(
        adapter_start_offset_ms=0,
        provider_request_start_offset_ms=5,
        provider_first_chunk_offset_ms=25,
        provider_full_response_offset_ms=65,
        adapter_event_emit_offset_ms=70,
        provider_ttft_ms=20,
        provider_full_response_ms=60,
        provider_generation_ms=40,
        stream_decode_ms=0,
        parse_validate_emit_ms=0,
        total_ms=70,
        timing_mode="streaming",
        ttft_available=True,
        ttft_source="provider_stream_chunk",
    )


class _ConstructedRealAsrTransport:
    def __init__(self) -> None:
        self.call_count = 0

    def transcribe(
        self,
        *,
        audio_payload: bytes,
        audio_mime_type: str,
        credential_handle: object,
        credential_value: str,
        adapter_request_id: str,
        timeout_ms: int,
        model_alias: str,
    ) -> AsrLiveProviderCallMetadata:
        assert audio_payload
        assert audio_mime_type == "audio/wav"
        assert "secret_materialized=False" in repr(credential_handle)
        assert credential_value == "DUMMY_TEST_CREDENTIAL_THAT_MUST_NOT_LEAK"
        assert adapter_request_id.startswith("adapter-request-mvp5-asr-")
        assert timeout_ms == 30_000
        assert model_alias
        self.call_count += 1
        return AsrLiveProviderCallMetadata(
            adapter_request_id=adapter_request_id,
            provider_url_ref="provider-url://dashscope/qwen-asr/openai-compatible-chat-completions",
            model_alias=model_alias,
            transcript_present=True,
            asr_frame_ref=f"asr-frame://provider/dashscope/{adapter_request_id}",
            text_ref=f"text://provider/dashscope/{adapter_request_id}",
            response_text_size_bucket="small",
        )


class _ConstructedRealThinkerTransport(_FakeThinkerAudioTransport):
    def __init__(self, *, fake_route: str) -> None:
        super().__init__(fake_route=fake_route)
        self.call_count = 0

    def complete_audio(self, **kwargs: object) -> str:
        self.call_count += 1
        return super().complete_audio(**kwargs)


class _MalformedThinkerAudioTransport:
    def complete_audio(self, **_kwargs: object) -> str:
        return "{bad}"


class _FencedThinkerAudioTransport(_FakeThinkerAudioTransport):
    def complete_audio(self, **kwargs: object) -> str:
        return "```json\n" + super().complete_audio(**kwargs) + "\n```"


def _write_pack(pack_path: Path, *, cases: list[dict[str, object]]) -> None:
    pack_path.write_text(
        json.dumps(
            {
                "pack_id": "local-mvp5-pack-001",
                "cases": cases,
            },
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _write_wav_file(
    path: Path,
    *,
    sample_rate_hz: int = 16000,
    channel_count: int = 1,
    frame_count: int = 160,
) -> bytes:
    sample_width_bytes = 2
    silent_frame = b"\x00" * sample_width_bytes * channel_count
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(channel_count)
        wav_file.setsampwidth(sample_width_bytes)
        wav_file.setframerate(sample_rate_hz)
        wav_file.writeframes(silent_frame * frame_count)
    return path.read_bytes()
