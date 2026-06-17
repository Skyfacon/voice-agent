# MVP5.1 Real Semantic Routing Smoke

## Goal

MVP5.1 connects the single local wav smoke path through real DashScope ASR and
real DashScope Thinker audio transports, then lets Router choose the existing
route from normalized semantic evidence:

```text
local wav
-> explicit local wav opt-in
-> DashScope ASR adapter transport
-> DashScope Thinker audio adapter transport
-> ASR_TRANSCRIPT_OUTPUT_EMITTED + THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED
-> Router
-> metadata-only route summary
```

Thinker remains evidence-only. It may emit `task_focus_hint` metadata, but
Router owns `ROUTER_DECISION_EMITTED` and no new RouterDecision or canonical
event is introduced.

## Single Wav Commands

Foreground chat or simple explanation:

```bash
scripts/mvp5-real-voice-e2e \
  --live-provider \
  --allow-local-wav \
  --local-wav <local-only-wav> \
  --expected-route FAST_ONLY \
  --approval-packet <local-only-approval-packet>
```

New task candidate:

```bash
scripts/mvp5-real-voice-e2e \
  --live-provider \
  --allow-local-wav \
  --local-wav <local-only-wav> \
  --expected-route SPAWN_SLOW_TASK \
  --approval-packet <local-only-approval-packet>
```

Patch an existing active SlowTask:

```bash
scripts/mvp5-real-voice-e2e \
  --live-provider \
  --allow-local-wav \
  --local-wav <local-only-wav> \
  --expected-route PATCH_ACTIVE_SLOW_TASK \
  --active-task-id task_local_active \
  --active-plan-version 1 \
  --active-task-event-seq 1 \
  --active-lifecycle-phase PLANNING \
  --approval-packet <local-only-approval-packet>
```

Use `--expected-route auto` when manually exploring a wav without asserting the
route. Mismatches are reported; the CLI does not force Router decisions.

## Approval Packet Template

The approval packet is local-only and must not contain credentials:

```json
{
  "approval_id": "mvp5-real-semantic-routing-local",
  "live_provider_opt_in": true,
  "local_wav_opt_in": true,
  "metadata_only_output": true,
  "replay_reruns_provider": false,
  "provider_adapter_ids": ["mvp5_asr_adapter", "mvp5_thinker_adapter"],
  "credential_env_var_name": "DASHSCOPE_API_KEY",
  "max_provider_calls": 2,
  "timeout_ms": 30000,
  "safe_output_ref": "summary://mvp5/real-semantic-routing/local"
}
```

The runtime reads the credential value only at adapter call time from the named
environment variable. It never prints or writes the credential value.

## Thinker Semantic Routing Hint

The DashScope Thinker prompt asks for one evidence-only candidate JSON object.
The candidate may include:

```json
{
  "task_focus_hint": {
    "focus": "FOREGROUND_CHAT",
    "task_like": false,
    "complexity_hint": "simple",
    "focus_confidence": 0.86,
    "evidence_uncertainty": "low"
  }
}
```

Allowed `focus` values are:

- `FOREGROUND_CHAT`: simple question, chat, or short explanation.
- `NEW_TASK_CANDIDATE`: multi-step work, planning, or something that should be tracked.
- `ACTIVE_TASK_PATCH`: correction, addition, or change to an active SlowTask.
- `AMBIGUOUS`: evidence is unclear; do not hard guess.
- `NON_ASSISTANT`: clearly not directed at the assistant.

The adapter validates the candidate and writes only the normalized focus string
plus safe metadata into `THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED`. Router then maps
that evidence to `FAST_ONLY`, `SPAWN_SLOW_TASK`, `PATCH_ACTIVE_SLOW_TASK`, or
`IGNORE`.

`PATCH_ACTIVE_SLOW_TASK` requires an active non-terminal task context. Without
one, the runner reports `blocked_missing_active_task_context` and does not create
`USER_PATCH_RECEIVED` or any SlowTask mutation.

## Safe Output Fields

Stdout is one JSON object with metadata only. Allowed fields include:

- `status`
- `mode`
- `route_result_kind`
- `actual_route` / `router_decision`
- `expected_route_matched`
- `asr_output_mode`
- `thinker_output_mode`
- event ids and safe refs
- `provider_call_used`
- `fake_transport_used`
- `raw_audio_included=false`
- `raw_transcript_included=false`
- `raw_provider_body_included=false`
- `prompt_dump_included=false`
- `secret_included=false`
- `local_wav_path_included=false`
- `replay_reruns_provider=false`
- `real_tts_used=false`
- `voice_output=none`

The output must not include local wav paths or names, approval packet paths, raw
audio, raw transcript, provider request or response bodies, provider schema,
prompt dumps, headers, cookies, tokens, or API keys.

## Provider-Free And Real Behavior

Provider-free tests use `--provider-free-fake-route` or
`--provider-free-fake-pack`. These modes still emit adapter-normalized ASR and
Thinker evidence and let Router decide naturally from `task_focus_hint`; they do
not call providers or read real env secrets.

When `--live-provider` is used without provider-free fake flags, the runtime
constructs adapter-owned DashScope ASR and Thinker transports. Tests monkeypatch
or inject transports to avoid network. Manual real provider execution remains
explicit opt-in only.

Replay uses recorded events and refs only. It never reruns ASR, Thinker, Router
runtime, tools, TTS, network, clock, random, env secret reads, or local wav
reads.

## Local-Only Artifacts

Local wav files, local approval packets, live summaries, diagnostics, traces,
and replay cache must stay under ignored local-only roots such as `outputs/`,
`diagnostics/`, `traces/`, `replays/local/`, or `audio/raw/`. Do not commit raw
audio, raw transcript, provider bodies, prompt dumps, local paths, or secrets.

Before writing a new local artifact path, confirm it is ignored:

```bash
git check-ignore -v <local-only-artifact>
```

## Non-Goals

- No realtime microphone.
- No full-duplex, AEC, or live barge-in expansion.
- No real TTS or voice output.
- No real Slow LLM loop.
- No real external side-effect tool execution.
- No production privacy claim.
- No new canonical event.
- No new RouterDecision.

## ADR Stop Conditions

Stop and write or update an ADR before proceeding if the implementation needs:

- a new MVP-relevant canonical event name;
- a new RouterDecision value;
- direct provider calls outside adapters;
- Thinker-owned SlowTask, UserPatch, SemanticCommitment, ToolCall, ToolResult,
  confirmation, or playback;
- Router-owned SlowTask mutation beyond existing route-result handling;
- replay that reruns providers or reads local wav/env secrets;
- committed raw audio, raw transcript, provider body, prompt dump, local path,
  diagnostics, trace, replay cache, or secret.
