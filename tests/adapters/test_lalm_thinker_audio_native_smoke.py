from __future__ import annotations

import base64
import json
from pathlib import Path

from voice_agent.adapters import lalm_thinker_audio_native_smoke as audio_smoke
from voice_agent.adapters.lalm_thinker_audio_native_smoke import (
    run_lalm_thinker_audio_native_smoke,
)
from voice_agent.adapters.lalm_thinker_runtime_adapter import LALM_THINKER_RUNTIME_MODEL_ALIAS


def test_audio_native_smoke_missing_key_fails_before_transport_call(tmp_path: Path) -> None:
    transport = _FakeAudioTransport()

    metadata = run_lalm_thinker_audio_native_smoke(
        repo_root=tmp_path,
        env={},
        transport=transport,
        audio_bytes=b"synthetic-audio",
    )

    assert metadata["success"] is False
    assert metadata["failure_category"] == "credential_missing"
    assert metadata["validated_count"] == 0
    assert metadata["request_failed_count"] == 1
    assert metadata["audio_input_mode"] == "native_audio"
    assert metadata["raw_audio_included"] is False
    assert metadata["audio_bytes_retained"] is False
    assert transport.call_count == 0
    summary_path = tmp_path / metadata["output_file"]
    assert summary_path.exists()
    rendered = summary_path.read_text(encoding="utf-8")
    assert "DASHSCOPE_API_KEY" not in rendered
    assert "runtime-secret-value-for-test-only" not in rendered
    assert "Bearer " not in rendered
    assert "provider_text" not in rendered
    assert base64.b64encode(b"synthetic-audio").decode("ascii") not in rendered


def test_audio_native_smoke_with_fake_transport_writes_metadata_only_summary(
    tmp_path: Path,
) -> None:
    transport = _FakeAudioTransport()
    audio_bytes = b"synthetic-audio"

    metadata = run_lalm_thinker_audio_native_smoke(
        repo_root=tmp_path,
        env={"DASHSCOPE_API_KEY": "runtime-secret-value-for-test-only"},
        transport=transport,
        audio_bytes=audio_bytes,
    )

    assert metadata["success"] is True
    assert metadata["provider_model_alias"] == LALM_THINKER_RUNTIME_MODEL_ALIAS
    assert metadata["audio_input_mode"] == "native_audio"
    assert metadata["input_modality"] == "audio"
    assert metadata["validated_count"] == 1
    assert metadata["validation_failed_count"] == 0
    assert metadata["request_failed_count"] == 0
    assert metadata["safe_refs"]
    assert metadata["raw_provider_request_included"] is False
    assert metadata["raw_provider_response_included"] is False
    assert metadata["raw_audio_included"] is False
    assert metadata["audio_bytes_retained"] is False
    assert metadata["candidate_text_included"] is False
    assert transport.call_count == 1
    assert transport.audio_format == "wav"
    assert transport.audio_bytes_seen == audio_bytes
    summary_path = tmp_path / metadata["output_file"]
    assert summary_path.exists()
    persisted = json.loads(summary_path.read_text(encoding="utf-8"))
    assert persisted == metadata

    rendered = repr(metadata)
    assert "DASHSCOPE_API_KEY" not in rendered
    assert "runtime-secret-value-for-test-only" not in rendered
    assert "Bearer " not in rendered
    assert "provider_text" not in rendered
    assert base64.b64encode(audio_bytes).decode("ascii") not in rendered


def test_audio_native_smoke_generates_portable_wav_when_macos_tools_are_absent(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    monkeypatch.setattr(audio_smoke.shutil, "which", lambda _command: None)
    transport = _FakeAudioTransport()

    metadata = run_lalm_thinker_audio_native_smoke(
        repo_root=tmp_path,
        env={"DASHSCOPE_API_KEY": "runtime-secret-value-for-test-only"},
        transport=transport,
    )

    assert metadata["success"] is True
    assert metadata["local_audio_generated"] is True
    assert transport.call_count == 1
    assert transport.audio_format == "wav"
    assert transport.audio_bytes_seen is not None
    assert transport.audio_bytes_seen.startswith(b"RIFF")
    summary_path = tmp_path / metadata["output_file"]
    rendered = summary_path.read_text(encoding="utf-8")
    assert "runtime-secret-value-for-test-only" not in rendered
    assert base64.b64encode(transport.audio_bytes_seen).decode("ascii") not in rendered


class _FakeAudioTransport:
    def __init__(self) -> None:
        self.call_count = 0
        self.audio_bytes_seen: bytes | None = None
        self.audio_format: str | None = None

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
        assert "local-only" not in repr(request_payload)
        assert credential_value == "runtime-secret-value-for-test-only"
        assert adapter_request_id.startswith("adapter-request-lalm-thinker-audio-native-")
        assert timeout_ms == 60_000
        assert model_alias == LALM_THINKER_RUNTIME_MODEL_ALIAS
        assert "secret_materialized=False" in repr(credential_handle)
        self.call_count += 1
        self.audio_bytes_seen = audio_bytes
        self.audio_format = audio_format

        skeleton = dict(request_payload["required_output_skeleton"])
        assert skeleton["request_binding"]["input_modality"] == "audio"
        skeleton["output_mode"] = "real"
        skeleton["optional_evidence_refs"] = {
            "semantic_close": {"status": "available", "label": "closed"},
            "assistant_directedness": {"status": "available", "label": "directed"},
            "emotion": {"status": "available", "label": "neutral"},
            "audio_caption": {"status": "available", "label": "speech_available"},
        }
        return json.dumps(skeleton, separators=(",", ":"), sort_keys=True)
