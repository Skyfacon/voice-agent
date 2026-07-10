from __future__ import annotations


MVP6_DEBUG_CONSOLE_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MVP6 Local Debug Console</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f6f8;
      --panel: #ffffff;
      --line: #d7dde5;
      --line-soft: #edf0f4;
      --text: #17202a;
      --muted: #5d6978;
      --blue: #174ea6;
      --blue-soft: #e8f0fe;
      --red: #ba1a1a;
      --green: #137333;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 14px 18px;
      background: var(--panel);
      border-bottom: 1px solid var(--line);
    }
    h1 { margin: 0; font-size: 20px; font-weight: 700; }
    h2 { margin: 0; font-size: 15px; font-weight: 700; }
    main {
      display: grid;
      grid-template-columns: minmax(320px, 440px) minmax(420px, 1fr);
      gap: 16px;
      padding: 16px;
    }
    section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      min-width: 0;
    }
    button, select, input { font: inherit; }
    button {
      min-height: 36px;
      border: 1px solid #aeb8c6;
      background: #ffffff;
      border-radius: 6px;
      padding: 0 12px;
      cursor: pointer;
    }
    button:disabled { cursor: not-allowed; opacity: 0.55; }
    button.primary { background: var(--blue); color: #ffffff; border-color: var(--blue); }
    button.danger { border-color: var(--red); color: var(--red); }
    select, input:not([type="checkbox"]) {
      width: 100%;
      min-height: 34px;
      border: 1px solid #aeb8c6;
      border-radius: 6px;
      padding: 4px 8px;
      background: #ffffff;
    }
    input[type="checkbox"] { width: auto; min-height: 0; margin: 0; }
    label { display: grid; gap: 4px; font-size: 13px; color: var(--muted); }
    label.checkRow {
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--text);
    }
    details {
      border: 1px solid var(--line-soft);
      border-radius: 6px;
      padding: 8px 10px;
      background: #fbfcfe;
    }
    summary {
      cursor: pointer;
      font-size: 13px;
      font-weight: 700;
      color: var(--text);
    }
    details .grid { margin-top: 10px; }
    pre {
      min-height: 220px;
      margin: 0;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      background: #f3f5f8;
      padding: 10px;
      border-radius: 6px;
      font-size: 12px;
    }
    .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    .grid { display: grid; gap: 10px; align-content: start; }
    .status { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; font-size: 13px; }
    .pill {
      display: inline-flex;
      align-items: center;
      min-height: 26px;
      border-radius: 999px;
      padding: 0 10px;
      background: var(--blue-soft);
      color: #123c7c;
      white-space: nowrap;
    }
    .stage {
      display: grid;
      grid-template-columns: 160px minmax(0, 1fr);
      gap: 8px;
      align-items: center;
      padding: 8px 0;
      border-bottom: 1px solid var(--line-soft);
    }
    .stage strong { font-size: 13px; }
    .stage span { color: var(--muted); overflow-wrap: anywhere; }
    .muted { color: var(--muted); font-size: 13px; }
    .answer {
      min-height: 42px;
      padding: 10px;
      border: 1px solid var(--line-soft);
      border-radius: 6px;
      background: #fbfcfe;
    }
    .historyList { display: grid; gap: 8px; }
    .historyItem { border-top: 1px solid var(--line-soft); padding-top: 8px; font-size: 13px; }
    .modelIoPanel {
      display: grid;
      gap: 10px;
    }
    .modelIoSection {
      display: grid;
      gap: 6px;
      border-top: 1px solid var(--line-soft);
      padding-top: 10px;
    }
    .modelIoSection:first-child {
      border-top: 0;
      padding-top: 0;
    }
    .modelIoSection h3 {
      margin: 0;
      font-size: 13px;
      font-weight: 700;
    }
    .modelIoSection pre {
      min-height: 72px;
      max-height: 260px;
      overflow: auto;
    }
    .hidden { display: none; }
    @media (max-width: 860px) {
      header { align-items: flex-start; flex-direction: column; }
      main { grid-template-columns: 1fr; }
      .stage { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <h1>MVP6 Local Debug Console</h1>
    <div class="status">
      <span id="providerStatus" class="pill">Provider: fake</span>
      <span id="approvalStatus" class="pill">Approval: unknown</span>
      <span id="credentialStatus" class="pill">Credential: unknown</span>
      <span id="promptProfileStatus" class="pill">Prompt Profile: unknown</span>
    </div>
  </header>
  <main>
    <section class="grid">
      <h2>Run</h2>
      <div class="row">
        <button id="recordButton" class="primary" onclick="startRecording()">Record</button>
        <button id="stopButton" onclick="stopRecording()" disabled>Stop</button>
        <button id="clearRecordingButton" class="danger" onclick="clearRecording()" disabled>Clear Recording</button>
        <button id="runButton" class="primary" onclick="runDraft()" disabled>Run</button>
      </div>
      <div id="draftStatus" class="muted">No recording draft</div>
      <label>Provider mode
        <select id="providerMode" onchange="updateProviderLabel()">
          <option value="fake">fake</option>
          <option value="dashscope_live">dashscope_live</option>
        </select>
      </label>
      <label>Expected route
        <select id="expectedRoute">
          <option value="auto">auto</option>
          <option value="FAST_ONLY">FAST_ONLY</option>
          <option value="SPAWN_SLOW_TASK">SPAWN_SLOW_TASK</option>
          <option value="PATCH_ACTIVE_SLOW_TASK">PATCH_ACTIVE_SLOW_TASK</option>
        </select>
      </label>
      <details id="activeTaskContextDetails">
        <summary>Advanced active-task context</summary>
        <div class="grid">
          <label>Active task id <input id="activeTaskId" autocomplete="off"></label>
          <label>Active plan version <input id="activePlanVersion" type="number" min="1"></label>
          <label>Active task event seq <input id="activeTaskEventSeq" type="number" min="1"></label>
          <p class="muted">Only needed when manually exercising PATCH_ACTIVE_SLOW_TASK.</p>
        </div>
      </details>
      <label class="checkRow"><input id="saveQaHistory" type="checkbox" checked> Save QA history locally</label>
      <label class="checkRow"><input id="showModelIo" type="checkbox"> Show model I/O for this run</label>
      <p class="muted">QA history is local-only and stores metadata refs, route decisions, gate decisions, and latency.</p>
    </section>

    <section class="grid">
      <h2>Latest Result</h2>
      <div id="answerDisplay" class="answer">No run yet</div>
      <div class="stage"><strong>local_audio_gate</strong><span id="stage-local_audio_gate">waiting</span></div>
      <div class="stage"><strong>asr</strong><span id="stage-asr">waiting</span></div>
      <div class="stage"><strong>fast_interaction</strong><span id="stage-fast_interaction">waiting</span></div>
      <div class="stage"><strong>thinker</strong><span id="stage-thinker">waiting</span></div>
      <div class="stage"><strong>router</strong><span id="stage-router">waiting</span></div>
      <div class="stage"><strong>foreground_gate</strong><span id="stage-foreground_gate">waiting</span></div>
      <div class="stage"><strong>qa_history</strong><span id="stage-qa_history">waiting</span></div>
      <h2>Latency</h2>
      <pre id="latencyPanel">{}</pre>
      <pre id="metadataPanel">{}</pre>
      <h2>Model I/O</h2>
      <div id="modelIoEmpty" class="muted">Enable model I/O before running to inspect provider inputs and outputs.</div>
      <div id="modelIoPanel" class="modelIoPanel hidden">
        <div class="modelIoSection">
          <h3>ASR Output Text</h3>
          <pre id="modelIoAsrText"></pre>
        </div>
        <div class="modelIoSection">
          <h3>Thinker System Prompt</h3>
          <pre id="modelIoThinkerSystem"></pre>
        </div>
        <div class="modelIoSection">
          <h3>Thinker User Payload</h3>
          <pre id="modelIoThinkerRequest"></pre>
        </div>
        <div class="modelIoSection">
          <h3>Thinker Model Output</h3>
          <pre id="modelIoThinkerOutput"></pre>
        </div>
        <details id="modelIoMetadataDetails">
          <summary>Debug metadata</summary>
          <pre id="modelIoMetadata"></pre>
        </details>
      </div>
      <div class="row">
        <button id="refreshHistoryButton" onclick="loadHistory()">Refresh History</button>
        <button id="clearHistoryButton" class="danger" onclick="clearHistory()">Clear History</button>
      </div>
      <div id="historyList" class="historyList"></div>
    </section>
  </main>
  <script>
    let audioContext = null;
    let mediaStream = null;
    let processor = null;
    let source = null;
    let recordedBuffers = [];
    let draftBlob = null;
    let recordingStartedAt = 0;
    const STAGE_NAMES = ['local_audio_gate', 'asr', 'fast_interaction', 'thinker', 'router', 'foreground_gate', 'qa_history'];

    async function loadStatus() {
      const response = await fetch('/api/status');
      const status = await response.json();
      document.getElementById('approvalStatus').textContent = 'Approval: ' + (status.approval_loaded ? 'loaded' : 'missing');
      document.getElementById('credentialStatus').textContent = 'Credential: ' + (status.credential_present ? 'present' : 'missing');
      const profile = status.routing_prompt_profile || {};
      document.getElementById('promptProfileStatus').textContent = 'Prompt Profile: ' + [
        profile.profile_id || 'unknown',
        profile.profile_version || 'unknown',
        profile.profile_hash || 'unknown'
      ].join(' / ');
      updateProviderLabel();
    }

    function updateProviderLabel() {
      document.getElementById('providerStatus').textContent = 'Provider: ' + document.getElementById('providerMode').value;
    }

    async function startRecording() {
      clearRecording();
      mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      audioContext = new AudioContext();
      source = audioContext.createMediaStreamSource(mediaStream);
      processor = audioContext.createScriptProcessor(4096, 1, 1);
      recordedBuffers = [];
      processor.onaudioprocess = (event) => recordedBuffers.push(new Float32Array(event.inputBuffer.getChannelData(0)));
      source.connect(processor);
      processor.connect(audioContext.destination);
      recordingStartedAt = Date.now();
      document.getElementById('recordButton').disabled = true;
      document.getElementById('stopButton').disabled = false;
      document.getElementById('draftStatus').textContent = 'Recording';
    }

    async function stopRecording() {
      if (!audioContext) return;
      if (processor) processor.disconnect();
      if (source) source.disconnect();
      if (mediaStream) mediaStream.getTracks().forEach((track) => track.stop());
      const samples = mergeBuffers(recordedBuffers);
      const wavBytes = encodeWav(samples, audioContext.sampleRate);
      draftBlob = new Blob([wavBytes], { type: 'audio/wav' });
      await audioContext.close();
      audioContext = null;
      const durationMs = Date.now() - recordingStartedAt;
      document.getElementById('draftStatus').textContent = 'Recorded draft: ' + Math.max(1, Math.round(durationMs / 1000)) + 's';
      document.getElementById('recordButton').disabled = false;
      document.getElementById('stopButton').disabled = true;
      document.getElementById('clearRecordingButton').disabled = false;
      document.getElementById('runButton').disabled = false;
    }

    function clearRecording() {
      draftBlob = null;
      recordedBuffers = [];
      if (processor) processor.disconnect();
      if (source) source.disconnect();
      if (mediaStream) mediaStream.getTracks().forEach((track) => track.stop());
      processor = null;
      source = null;
      mediaStream = null;
      document.getElementById('draftStatus').textContent = 'No recording draft';
      document.getElementById('recordButton').disabled = false;
      document.getElementById('stopButton').disabled = true;
      document.getElementById('clearRecordingButton').disabled = true;
      document.getElementById('runButton').disabled = true;
    }

    async function runDraft() {
      if (!draftBlob) return;
      const form = new FormData();
      form.append('audio', draftBlob, 'browser-draft.wav');
      form.append('provider_mode', document.getElementById('providerMode').value);
      form.append('expected_route', document.getElementById('expectedRoute').value);
      form.append('active_task_id', document.getElementById('activeTaskId').value);
      form.append('active_plan_version', document.getElementById('activePlanVersion').value);
      form.append('active_task_event_seq', document.getElementById('activeTaskEventSeq').value);
      form.append('save_qa_history', document.getElementById('saveQaHistory').checked ? 'true' : 'false');
      form.append('show_model_io', document.getElementById('showModelIo').checked ? 'true' : 'false');
      setStages('running');
      const response = await fetch('/api/runs', { method: 'POST', body: form });
      const payload = await response.json();
      renderResult(payload);
      await loadHistory();
    }

    function renderResult(payload) {
      document.getElementById('answerDisplay').textContent = payload.answer_display || payload.status;
      setStages(payload.status === 'completed' ? 'waiting' : 'not_run');
      for (const stage of payload.pipeline || []) {
        const element = document.getElementById('stage-' + stage.stage);
        if (element) element.textContent = stage.status + (stage.output_mode ? ' / ' + stage.output_mode : '');
      }
      document.getElementById('latencyPanel').textContent = JSON.stringify(payload.latency_debug || {}, null, 2);
      document.getElementById('metadataPanel').textContent = JSON.stringify(payload, null, 2);
      renderModelIoDebug(payload.model_io_debug || null);
    }

    function renderModelIoDebug(modelIo) {
      const panel = document.getElementById('modelIoPanel');
      const empty = document.getElementById('modelIoEmpty');
      const hasModelIo = modelIo && typeof modelIo === 'object' && (modelIo.asr || modelIo.thinker);
      panel.classList.toggle('hidden', !hasModelIo);
      empty.classList.toggle('hidden', hasModelIo);
      if (!hasModelIo) {
        setText('modelIoAsrText', '');
        setText('modelIoThinkerSystem', '');
        setText('modelIoThinkerRequest', '');
        setText('modelIoThinkerOutput', '');
        setText('modelIoMetadata', '');
        return;
      }
      modelIo.asr = modelIo.asr || {};
      modelIo.thinker = modelIo.thinker || {};
      setText('modelIoAsrText', formatModelIoSummary(modelIo.asr));
      setText('modelIoThinkerSystem', formatModelIoSummary(modelIo.thinker));
      setText('modelIoThinkerRequest', modelIo.thinker.request_payload_available ? 'metadata only; request payload redacted' : '(not available)');
      setText('modelIoThinkerOutput', modelIo.thinker.provider_output_available ? 'metadata only; provider output redacted' : '(not available)');
      setText('modelIoMetadata', JSON.stringify(buildModelIoMetadata(modelIo), null, 2));
    }

    function formatModelIoSummary(summary) {
      if (!summary || typeof summary !== 'object') return '(not available)';
      if (summary.content_redacted !== true) return '(not available)';
      const count = Number.isInteger(summary.provider_output_char_count) ? summary.provider_output_char_count : 0;
      return 'metadata only; content redacted; provider chars: ' + count;
    }

    function buildModelIoMetadata(modelIo) {
      return {
        saved_to_history: modelIo.saved_to_history === true,
        asr: modelIo.asr || {},
        thinker: modelIo.thinker || {}
      };
    }

    function setText(id, value) {
      document.getElementById(id).textContent = value;
    }

    async function loadHistory() {
      const response = await fetch('/api/history');
      const payload = await response.json();
      const list = document.getElementById('historyList');
      list.replaceChildren();
      for (const entry of payload.entries || []) {
        const item = document.createElement('div');
        item.className = 'historyItem';
        item.textContent = (entry.question_text || '') + ' -> ' + (entry.answer_display || entry.actual_route || '');
        list.appendChild(item);
      }
    }

    async function clearHistory() {
      await fetch('/api/history/clear', { method: 'POST' });
      await loadHistory();
    }

    function setStages(status) {
      for (const name of STAGE_NAMES) {
        document.getElementById('stage-' + name).textContent = status;
      }
    }

    function mergeBuffers(buffers) {
      const length = buffers.reduce((sum, buffer) => sum + buffer.length, 0);
      const result = new Float32Array(length);
      let offset = 0;
      for (const buffer of buffers) {
        result.set(buffer, offset);
        offset += buffer.length;
      }
      return result;
    }

    function encodeWav(samples, sampleRate) {
      const buffer = new ArrayBuffer(44 + samples.length * 2);
      const view = new DataView(buffer);
      writeString(view, 0, 'RIFF');
      view.setUint32(4, 36 + samples.length * 2, true);
      writeString(view, 8, 'WAVE');
      writeString(view, 12, 'fmt ');
      view.setUint32(16, 16, true);
      view.setUint16(20, 1, true);
      view.setUint16(22, 1, true);
      view.setUint32(24, sampleRate, true);
      view.setUint32(28, sampleRate * 2, true);
      view.setUint16(32, 2, true);
      view.setUint16(34, 16, true);
      writeString(view, 36, 'data');
      view.setUint32(40, samples.length * 2, true);
      let offset = 44;
      for (const sample of samples) {
        const clamped = Math.max(-1, Math.min(1, sample));
        view.setInt16(offset, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
        offset += 2;
      }
      return new Uint8Array(buffer);
    }

    function writeString(view, offset, value) {
      for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i));
    }

    loadStatus();
    loadHistory();
  </script>
</body>
</html>
"""
