# Qwen Realtime Fast/Slow Slice 2 Acceptance

Date: 2026-07-21

Status: provider-free implementation acceptance is `executed_pass`, the real Shadow Control text-only smoke is `executed_pass` with a very small synthetic/redacted sample, and a real browser connection confirmed both Voice and Shadow WebSockets. Real microphone/ASR/audio conversation remains `manual_not_executed`. The architecture proposal remains `proposed`.

## Acceptance boundary

- Slice 2 mode is `dual_session_shadow`: one Voice Session and one logically independent Shadow Control Session behind the browser's single local WebSocket.
- The Voice Session owns realtime ASR, user-visible assistant transcript/audio, interruption, and provider cancellation.
- The Shadow Control Session receives one final transcript plus a minimized active-task snapshot, requests `propose_turn_disposition`, validates the function-call frame, and compares it with an isolated deterministic local Router evaluation.
- A Qwen proposal is non-authoritative experiment evidence. It cannot update authoritative `TaskFocusState`, create or patch a `SlowTask`, create a `UserPatch`, invoke the Fast Foreground Gate, change playback, or enter the QA conversation.
- `route.shadow.proposed`, `route.shadow.validated`, `route.shadow.compared`, and `route.shadow.degraded` are experiment-local metadata labels, not ADR-002 canonical event names and not replay inputs.
- `qwen + enforced` is unsupported in this Slice. `fake + enforced` remains the Slice 1 regression path.

## Provider capability matrix

| Capability | Voice Session | Shadow Control Session | Verification state |
| --- | --- | --- | --- |
| Model | `qwen-audio-3.0-realtime-plus` | `qwen-audio-3.0-realtime-plus` | official documentation recheck on 2026-07-21: verified; real Shadow connection: `executed_pass` |
| Beijing Realtime endpoint | workspace-scoped `/api-ws/v1/realtime` | independent connection to the same endpoint class | Shadow live connection: `executed_pass`; Voice: `not_executed` |
| `session.update` | `modalities=["audio","text"]`, `smart_turn` | `modalities=["text"]`, `turn_detection=null`, one internal tool | provider-free wire tests and real Shadow smoke: `executed_pass`; real Voice: `not_executed` |
| ASR delta/final | normalized transiently | final transcript is request input only | real provider: `not_executed` |
| Streaming transcript/audio | user-visible Voice path | prohibited from playback/QA | real provider: `not_executed` |
| `response.cancel` | supported by adapter contract | used only to fence a timed-out/superseded analysis response | real semantics: `not_executed` |
| `conversation.item.create` | provider-managed voice context | one bounded text/control item per shadow request | real Shadow smoke: `executed_pass` |
| `conversation.item.delete` | not claimed by Slice 2 Voice path | attempted after request completion | real Shadow smoke: `2/2` delete acknowledgements for the measured comparison request |
| Context rebuild | not required for normal Voice flow | fail-closed recovery when delete cannot be confirmed | real recovery: `not_executed` |
| Function-call argument delta/done and `response.done` | not consumed for routing | strictly accumulated and schema validated | provider-free tests: `executed_pass`; post-fix real smoke: `2/2` |
| Forced function call / `tool_choice` | not applicable | must not be assumed from prompting | `unsupported_or_unverified` |
| Concurrent response behavior | provider-defined | adapter allows at most one active request and fences late results | real provider: `not_executed` |
| Direct Shadow audio or candidate playback | prohibited | prohibited | structurally enforced: `executed_pass` |

The main agent rechecked the official documentation on 2026-07-21. It verified the current model name and Beijing workspace-scoped endpoint shape `wss://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime?model=qwen-audio-3.0-realtime-plus`, `session.update`, text-only and audio/text modalities, `smart_turn` and manual `turn_detection=null`, item create/delete, response create/cancel/done, ASR delta/final, Function Calling tools plus argument delta/done, and the one-active-response constraint. The checked pages were the [Qwen Audio Realtime user guide](https://help.aliyun.com/zh/model-studio/qwen-audio-realtime-user-guides), [WebSocket API](https://help.aliyun.com/zh/model-studio/fun-audiochat-realtime-websocket-api), [client events](https://help.aliyun.com/zh/model-studio/fun-audiochat-client-events), and [server events](https://help.aliyun.com/zh/model-studio/qwen-audio-realtime-server-events). None of those pages declared a forced `tool_choice`, so prompt compliance was not promoted into a protocol capability.

## Provider-free automated acceptance matrix

| Acceptance item | Test evidence | Status |
| --- | --- | --- |
| Voice and Shadow sessions connect/configure independently | Slice 2 adapter/coordinator tests | `executed_pass` |
| Voice ASR/transcript/audio remains functional | Slice 1 regression plus Slice 2 coordinator tests | `executed_pass` |
| Final transcript forwards once with a minimized task snapshot | Slice 2 coordinator tests | `executed_pass` |
| Function-call fragmented delta + done | Slice 2 shadow-adapter tests | `executed_pass` |
| Missing field, invalid enum, out-of-range confidence, oversized candidate | Slice 2 schema tests | `executed_pass` |
| Plain text, malformed JSON, wrong function name | Slice 2 degraded tests | `executed_pass` |
| Provider error, timeout, Shadow disconnect, Voice disconnect | Slice 2 adapter/coordinator tests | `executed_pass` |
| Multi-turn correlation and stale/late function-call discard | Slice 2 coordinator tests | `executed_pass` |
| Bounded request queue/drop counter | Slice 2 queue tests | `executed_pass` |
| Context delete acknowledgement and taint/rebuild fallback | Slice 2 shadow-adapter tests | `executed_pass` |
| Proposal/local Router agreement, mismatch, and not-available | Slice 2 comparison tests | `executed_pass` |
| Shadow leaves TaskFocus/SlowTask/UserPatch/Gate/playback unchanged | Slice 2 authority-boundary tests | `executed_pass` |
| `fake + enforced` Slice 1 regression | existing Slice 1 suite | `executed_pass` |
| Credential handle is opaque and metadata is redacted | Slice 2 security tests | `executed_pass` |
| Browser/timeline excludes secrets, raw audio, full provider payload/arguments, real transcript, full candidate | Slice 2 browser/security tests | `executed_pass` |
| real/fake/degraded labels are distinguishable | capability/server/coordinator tests | `executed_pass` |

Canonical provider-free command:

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python \
  ./scripts/test tests/experiments/qwen_realtime_fast_slow -q
```

Final result with loopback binding permitted: `201 passed in 1.57s`, no skips. The same revision in the restricted sandbox produced `188 passed, 13 skipped in 2.03s`; all 13 skips were server integration cases guarded at `tests/experiments/qwen_realtime_fast_slow/test_server.py:39` solely because that sandbox denied binding a loopback test port. The no-skip rerun used the same canonical command and did not require a provider credential.

Related authoritative control-plane regression:

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python \
  ./scripts/test \
  tests/interaction \
  tests/router \
  tests/runtime/test_mvp63_fast_foreground_gate.py \
  tests/user_patch \
  tests/slowtask -q
```

Result: `82 passed in 0.28s`, no skips.

## Live acceptance

| Check | Status | Evidence |
| --- | --- | --- |
| Real Shadow text request | `executed_pass` | Two post-fix control-only requests used fixed synthetic/redacted text; both returned validated proposals. |
| Voice and Shadow WebSockets both connected | `executed_pass` | Real browser smoke showed both `connected`, then Disconnect/Reconnect returned both to `connected` with a fresh playback epoch/session. |
| Real function-call coverage | `2/2` | Both post-fix requests produced the expected Function Call. This sample is too small to estimate production coverage. |
| Real schema-valid rate | `2/2` | Both post-fix Function Calls passed strict local validation. This sample is too small to estimate production validity. |
| Real Qwen/local Router agreement rate | overall `0/1`; route `1/1`, focus `1/1`, foreground act `0/1` | Comparison sample: both route decisions were `SPAWN_SLOW_TASK`; both focus interpretations were `NEW_TASK_CANDIDATE`; Qwen act `CLARIFY` differed from local `ACK_SLOW`. Overall agreement requires all three axes. |
| ASR final to Shadow request latency | real ASR `not_executed` | Synthetic safe-ref to request dispatch was `179.989 ms` and included standalone connection timing, so it is not an ASR latency measurement. |
| Shadow request to first function-call delta | `372.152 ms` | One latest comparison sample. |
| Shadow request to function-call done | `2579.491 ms` | One latest comparison sample. |
| Function-call done to local Router decision | `37.524 ms` | Adapter completion `33.524 ms` plus isolated Router evaluation `4 ms`, one sample. |
| Browser microphone/audio smoke | `manual_not_executed` | The automated environment did not provide a real microphone/audio run. |
| Shadow failure while Voice remains usable | `executed_pass_fake`; real `not_executed` | Scripted timeout, provider error, and Shadow disconnect leave subsequent Voice transcript/audio usable. |

The latest real comparison request received `2/2` context-delete acknowledgements and observed zero context taints, rebuilds, provider errors, timeouts, and late-event discards. These are one-request observations, not reliability rates. The first pre-fix live attempt revealed the provider's valid event order `output_item.added -> function_call_arguments.delta/done -> output_item.done` for the same Function Call; the adapter initially mistook the repeated same-item completion for a second call. The fix treats only identical correlation as idempotent, retains fail-closed behavior for a genuinely different second call, and is covered by the in-memory transport regression.

The real browser smoke used the documented server command, loaded credentials only in the backend shell, and observed `provider=qwen`, `routing=shadow`, `audio_output=qwen`, and `dual_session_shadow`; Voice and Shadow Control both connected on the first connection and after reconnect. No microphone was started, so this is connection/lifecycle evidence only, not ASR, Voice response, interruption, or audio-playback evidence. Browser console result was `0` errors and `0` warnings, the temporary Playwright artifacts were removed, and port `8767` was stopped afterward.

Reproduction command for the credential-safe, control-only smoke:

```bash
/bin/zsh -lc '
  source ~/.voice-agent-secrets/dashscope.env &&
  /Users/a123/anaconda3/bin/python \
    experiments/qwen_realtime_fast_slow_web/live_shadow_smoke.py \
    --timeout 15
'
```

The script uses a fixed synthetic/redacted transcript and emits only safe metadata. It does not print, copy, or persist the credential, raw provider payload, Function Call arguments, or reply candidate.

Do not replace `not_executed` with a claimed result unless the exact command, sample count, and observed outcome are recorded. No raw provider payload, complete real transcript, audio, function arguments, or credential may be added to this document.

## Security and privacy acceptance

- Credentials are backend-only opaque handles. Browser payloads and serializable metadata may expose only configured/presence booleans and a one-way safe workspace reference.
- No `.env` is created. Tests use sentinels and injected mappings; they never read `~/.voice-agent-secrets/dashscope.env`.
- Raw microphone/provider audio remains transient and is never written to a fixture, timeline, log, trace, or replay.
- Provider exception strings, Authorization headers, full `session.update`, full provider events, full function arguments, unredacted real transcripts, and complete reply candidates are excluded from safe metadata.
- Reply candidate text is bounded, transient, and never included in the browser QA projection or playback path.
- No external tool is invoked. A provider function call is only an untrusted proposal frame.

## Cost, latency, and next-slice decision

`dual_session_shadow` intentionally adds a second provider connection, a text-context create/response/delete cycle, and extra request latency. It isolates tool/function-call experiments from the realtime Voice response and is therefore the recommended default until real cancellation, late-event fencing, context deletion/rebuild, and route quality are measured. This Slice does not prove that a single provider connection can safely combine voice output and routing control.

Before Slice 3 can consider enforced routing:

1. The ADR proposal must be accepted or superseded; accepted ADRs and the canonical registry must not be silently changed by the spike.
2. Forced function-call support must be verified from the provider protocol or enforcement must remain fail-closed without treating prompt compliance as a guarantee.
3. Real function-call coverage, schema-valid rate, latency, and local agreement need representative measurements.
4. Delete acknowledgement/rebuild and response cancellation/late-event behavior need real-provider evidence.
5. A reviewed authority boundary must map validated evidence into canonical Router/SlowTask/UserPatch flows without letting provider IDs or suggestions advance state.
6. Direct provider audio needs an accepted gate-before-leak and playback/truncate contract; Shadow output must remain non-audible until then.

## Explicit non-claims

Passing Slice 2 cannot claim enforced Qwen routing, provider authority over Router decisions, direct Qwen control of SlowTask/UserPatch/Gate/playback, production privacy/auth, real tool execution, single-session safety, real-device AEC/truncate SLOs, or accepted ADR-017 extensions beyond its current scope.
