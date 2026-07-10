# MVP6 Local Developer Debug Console

## Goal

MVP6 provides a local-only developer debug console for the single-audio routing
path. It is a Python localhost server plus plain HTML/JS page for recording one
microphone draft, explicitly running parallel ASR observation plus audio-native
Fast Interaction, inspecting the gated Question/Answer result and metadata-only
pipeline details, and saving local-only QA history.

## Start The Console

Provider-free mode is the default:

```bash
scripts/mvp6-debug-console
```

To make DashScope Live mode available, start the server with a local-only
approval packet created or updated for the exact MVP6.3 adapter set below:

```bash
scripts/mvp6-debug-console \
  --approval-packet outputs/mvp6-debug-console/approval.json
```

Do not reuse an older ASR + Thinker approval packet. The server requires the
request adapter IDs to exactly match `provider_adapter_ids` in the packet, so an
old packet cannot authorize ASR + Fast Interaction. Keep the packet timeout and
call budget at or below the explicitly approved values.

Optional local server controls:

```bash
scripts/mvp6-debug-console \
  --output-root outputs/mvp6-debug-console \
  --host 127.0.0.1 \
  --port 8766
```

Open:

```text
http://127.0.0.1:8766
```

DashScope Live mode is visible in the page but requires server-side approval and
credential readiness. Missing approval reports `approval_missing`; missing
credential reports `credential_missing`.

## Approval Packet

```json
{
  "approval_id": "mvp6-local-debug-console-local",
  "live_provider_opt_in": true,
  "local_wav_opt_in": true,
  "metadata_only_output": true,
  "replay_reruns_provider": false,
  "provider_adapter_ids": ["mvp5_asr_adapter", "mvp63_fast_interaction_runtime"],
  "credential_env_var_name": "DASHSCOPE_API_KEY",
  "max_provider_calls": 2,
  "timeout_ms": 1500,
  "safe_output_ref": "summary://mvp6/debug-console/local"
}
```

The approval packet path itself is local-only and must not be committed.

## Local Artifact Policy

All MVP6 artifacts are local-only. The output root defaults to
`outputs/mvp6-debug-console/`, which is ignored by the repository. Keep approval
packets, uploaded browser draft wav files, QA history, and any manual debug
notes in that ignored output root or another ignored local-only path.

## QA History

QA history is local-only and may contain the normalized ASR Question and the
runtime-approved displayed Answer. It is written to:

```text
outputs/mvp6-debug-console/qa-history.jsonl
```

raw audio is not saved to QA history. The QA history and API responses also do
not save:

- Provider request bodies.
- provider response bodies.
- prompt dumps.
- local paths.
- filenames.
- secrets.

It never stores a discarded Fast Interaction candidate as the Answer.
The live Answer is resolved only from `FOREGROUND_OUTPUT_COMMITTED`: a candidate
must match the committed ref, while a fallback must match the runtime template
catalog and committed fallback provenance. Credential-like Question/Answer text
is redacted before response/history projection. Provider-free fake mode does not
invent a Question when its synthetic ASR ref has no process-local text resolver;
the page reports `ref_unresolved` instead.

## Acceptance Scenarios

- MVP6-LOCAL-CONSOLE-STARTUP-001: console starts on localhost and exposes safe status.
- MVP6-MIC-DRAFT-RUN-001: browser recording creates a draft, and only explicit Run sends it.
- MVP6-PROVIDER-FREE-RUN-001: default fake mode runs the MVP5 provider-free route path.
- MVP6-LIVE-PROVIDER-GATE-001: DashScope Live mode is gated by approval and credential readiness.
- MVP6-PIPELINE-INSPECTOR-001: page displays local_audio_gate, ASR observation, Fast Interaction, Router, foreground gate, and QA history stages.
- MVP6-QA-HISTORY-001: local QA history stores normalized ASR Question and committed/fallback Answer by default.
- MVP6-SAFETY-REDACTION-001: responses and history omit raw audio, provider body, prompt dump, local path, and secret material.
- MVP6-NO-ARCHITECTURE-EXPANSION-001: MVP6 adds no canonical event, RouterDecision, real TTS, or Slow LLM loop.

## Non-Goals

- No realtime microphone streaming.
- No full-duplex, AEC, or barge-in.
- No real TTS.
- No real Slow LLM.
- No production demo UI claim.
- No real external side-effect tool execution.
- No new canonical event.
- No new RouterDecision.
