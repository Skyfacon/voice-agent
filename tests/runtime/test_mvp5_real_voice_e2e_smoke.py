from __future__ import annotations

import base64
import json
from pathlib import Path
import wave

import pytest

from voice_agent.adapters.asr_fake_transport import FakeAsrProviderResponse, FakeAsrTransport
from voice_agent.adapters.lalm_thinker_runtime_adapter import LALM_THINKER_RUNTIME_MODEL_ALIAS
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
                "task_like": False,
                "complexity_hint": "simple",
                "focus_confidence": 0.86,
                "evidence_uncertainty": "low",
            }
        elif self.fake_route == "SPAWN_SLOW_TASK":
            skeleton["task_focus_hint"] = {
                "task_like": True,
                "complexity_hint": "complex",
                "focus_confidence": 0.9,
                "evidence_uncertainty": "low",
            }
        elif self.fake_route == "PATCH_ACTIVE_SLOW_TASK":
            skeleton["task_focus_hint"] = {
                "task_like": True,
                "complexity_hint": "complex",
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
