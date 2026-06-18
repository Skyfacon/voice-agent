from __future__ import annotations

from voice_agent.runtime.mvp6_debug_console_static import MVP6_DEBUG_CONSOLE_HTML


def test_static_html_contains_core_controls_and_provider_state() -> None:
    html = MVP6_DEBUG_CONSOLE_HTML
    assert "MVP6 Local Debug Console" in html
    assert 'id="recordButton"' in html
    assert 'id="stopButton"' in html
    assert 'id="clearRecordingButton"' in html
    assert 'id="runButton"' in html
    assert 'id="providerMode"' in html
    assert "dashscope_live" in html
    assert 'id="expectedRoute"' in html
    assert "PATCH_ACTIVE_SLOW_TASK" in html


def test_static_html_contains_pipeline_and_history_surfaces() -> None:
    html = MVP6_DEBUG_CONSOLE_HTML
    assert "local_audio_gate" in html
    assert "asr" in html
    assert "thinker" in html
    assert "router" in html
    assert "qa_history" in html
    assert "QA history is local-only" in html


def test_static_js_encodes_wav_and_requires_explicit_run() -> None:
    html = MVP6_DEBUG_CONSOLE_HTML
    assert "function startRecording" in html
    assert "function stopRecording" in html
    assert "function clearRecording" in html
    assert "function runDraft" in html
    assert "function encodeWav" in html
    assert "new Blob([wavBytes], { type: 'audio/wav' })" in html
