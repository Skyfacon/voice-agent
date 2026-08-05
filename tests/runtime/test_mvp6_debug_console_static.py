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


def test_static_html_keeps_active_task_context_in_advanced_details() -> None:
    html = MVP6_DEBUG_CONSOLE_HTML

    assert '<details id="activeTaskContextDetails"' in html
    assert "Advanced active-task context" in html
    assert html.index('<details id="activeTaskContextDetails"') < html.index('id="activeTaskId"')
    assert "form.append('active_task_id', document.getElementById('activeTaskId').value);" in html
    assert "form.append('active_plan_version', document.getElementById('activePlanVersion').value);" in html
    assert "form.append('active_task_event_seq', document.getElementById('activeTaskEventSeq').value);" in html


def test_static_html_contains_pipeline_and_history_surfaces() -> None:
    html = MVP6_DEBUG_CONSOLE_HTML
    assert "local_audio_gate" in html
    assert "asr" in html
    assert "fast_interaction" in html
    assert "thinker" in html
    assert "router" in html
    assert "foreground_gate" in html
    assert "qa_history" in html
    assert "Latency" in html
    assert 'id="questionDisplay"' in html
    assert 'id="answerDisplay"' in html
    assert 'id="qaStatus"' in html
    assert 'id="latencyPanel"' in html
    assert "QA history is local-only" in html
    assert 'id="showModelIo"' in html
    assert 'id="modelIoPanel"' in html
    assert 'id="modelIoEmpty"' in html
    assert 'id="modelIoAsrText"' in html
    assert 'id="modelIoFastInteraction"' in html
    assert 'id="modelIoThinkerSystem"' in html
    assert "Thinker User Payload" in html
    assert 'id="modelIoThinkerRequest"' in html
    assert 'id="modelIoThinkerOutput"' in html
    assert 'id="modelIoMetadata"' in html


def test_static_js_encodes_wav_and_requires_explicit_run() -> None:
    html = MVP6_DEBUG_CONSOLE_HTML
    assert "function startRecording" in html
    assert "function stopRecording" in html
    assert "function clearRecording" in html
    assert "function runDraft" in html
    assert "function encodeWav" in html
    assert "new Blob([wavBytes], { type: 'audio/wav' })" in html


def test_static_js_resets_unreturned_pipeline_stages_for_gated_runs() -> None:
    html = MVP6_DEBUG_CONSOLE_HTML
    assert (
        "const STAGE_NAMES = ['local_audio_gate', 'asr', 'fast_interaction', "
        "'thinker', 'router', 'foreground_gate', 'qa_history'];"
        in html
    )
    assert "setStages(payload.status === 'completed' ? 'waiting' : 'not_run');" in html


def test_static_js_submits_and_renders_model_io_debug() -> None:
    html = MVP6_DEBUG_CONSOLE_HTML
    assert "form.append('show_model_io', document.getElementById('showModelIo').checked ? 'true' : 'false');" in html
    assert "renderModelIoDebug(payload.model_io_debug || null);" in html
    assert "function renderModelIoDebug(modelIo)" in html
    assert "setText('modelIoAsrText', formatModelIoSummary(modelIo.asr));" in html
    assert "setText('modelIoFastInteraction', formatModelIoSummary(modelIo.fast_interaction));" in html
    assert "setText('modelIoThinkerSystem', formatModelIoSummary(modelIo.thinker));" in html
    assert "metadata only; request payload redacted" in html
    assert "metadata only; provider output redacted" in html
    assert "function formatModelIoSummary(summary)" in html
    assert ".provider_text" not in html
    assert ".system_message" not in html
    assert ".request_body" not in html
    assert "JSON.stringify(buildModelIoMetadata(modelIo), null, 2)" in html
    assert "document.getElementById('latencyPanel').textContent = JSON.stringify(payload.latency_debug || {}, null, 2);" in html
    assert "document.getElementById('questionDisplay').textContent" in html
    assert "payload.question_text" in html
    assert "payload.qa_status" in html
