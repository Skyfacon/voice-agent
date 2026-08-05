# Qwen Realtime Fast/Slow Integration Spike

This experiment now contains three deliberately different modes:

- Slice 1 `fake + enforced`: the provider-free deterministic Router/Gate/MockSlowTask/UserPatch acceptance path.
- Slice 2 `qwen + shadow`: one real Qwen Voice Session plus an independent text-only Qwen Shadow Control Session. The control result is comparison evidence only.
- Slice 3A `qwen + enforced + audio-output none`: an experimental dual-session control plane. Real Qwen Function Call output is non-authoritative evidence; the existing local Router and Fast Foreground Gate decide the action, only committed text may reach QA, and SlowTask remains mock.

The architecture proposal is [ADR-PROPOSAL-Qwen-Realtime-Multi-role-Frontend-and-Provider-native-Foreground-Audio-Contract.md](../../docs/adr/proposals/ADR-PROPOSAL-Qwen-Realtime-Multi-role-Frontend-and-Provider-native-Foreground-Audio-Contract.md). It remains `proposed`; this spike does not accept the ADR, change the accepted ADR register, or add canonical events.

## Slice 3A.2 stale-cleanup closure and bounded live result

Slice 3A.2 closes a later independent-review P1 in Voice cleanup authority.
Cleanup now captures core identity, provider generation, session ref, and
response lifecycle identity before provider deletion; adapter and coordinator
revalidate that authority after the await and before counter, taint, map, or
rebuild mutation. Retired completion is a content-free no-op. A real
current-generation failure remains fail-closed and concurrent failures
coalesce into one Voice-only rebuild.

Provider-free regression passed, including stale false/exception/success,
same-ID replacement, fresh PCM, concurrent cleanup, and close-during-cleanup
coverage. The bounded 2026-07-24 live run reached real text-only Control, real
dual-session Voice/Control connections, Chrome microphone `capturing`, five
idle-timeout Voice-only rebuild recoveries, clean disconnect/reconnect, and
zero binary playback. The observed microphone input level remained 0%, so no
real ASR committed turn, route matrix, cancel terminal, or Voice item-delete
claim is made. Overall qualification is `executed_partial`; `real_live_verified`
remains `false`.

See
[qwen-realtime-fast-slow-slice3a2-acceptance.md](../../docs/implementation/qwen-realtime-fast-slow-slice3a2-acceptance.md)
for RED/GREEN, commands, official-document review, per-axis live status, and
the Slice 3B-MVP `NO_GO` verdict. Dual session, Local Router authority,
`audio_output=none`, candidate/PCM quarantine, and mock SlowTask remain frozen.

## Slice 3A.1.2 closure

Independent dynamic review invalidated the Slice 3A.1.1 safety verdict. Slice
3A.1.2 closes those provider-free blockers without enabling any new provider
capability:

- every Qwen/provider reply candidate is quarantined by immutable local policy
  provenance, regardless of `LOW`, `risk_tags=["none"]`, confidence or schema
  validity;
- only explicitly trusted synthetic fixtures and server-owned deterministic,
  versioned templates are eligible for local allow policy;
- live Gate state/focus references come from canonical journal events, current
  SlowTask/confirmation authority is bound explicitly, and capability output
  mode comes from the recorded snapshot; missing or inconsistent context fails
  closed;
- delivery attempt/identity/semantic state is recorded before browser sends,
  so an ambiguous send cannot trigger a second reply or response id;
- partial SlowTask/UserPatch mutations are rebuilt from the Event Journal and
  compared with deterministic replay before success is reported;
- no-provider-candidate slow routes use a real server-owned local candidate,
  never a fabricated ID or candidate-less Gate event;
- PCM and provider events carry local Voice generations; rebuild fences and
  drains old PCM, stale events are discarded, terminal receivers resume only
  on a replacement generation, and recovery does not depend on browser
  metadata delivery;
- provider IDs are retained for the whole generation. Reuse fails closed and
  the bounded horizon forces Voice rotation rather than unsafe eviction.

`real_live_verified=false`, provider-native audio remains disabled, forced
Function Call remains `unsupported_or_unverified`, SlowTask remains local/mock,
and no real external side effect is enabled. Dual session remains the required
topology; single session is not qualified.

See
[qwen-realtime-fast-slow-slice3a12-acceptance.md](../../docs/implementation/qwen-realtime-fast-slow-slice3a12-acceptance.md)
for commands, results and the Slice 3A.2 admission decision.

## Slice 3A.1.1 historical closure

The following is retained as historical evidence only. Its `executed_pass` was
overturned by Slice 3A.1.2 independent dynamic review.

Each enforced turn carries a local phase record for terminal claim,
FastInteraction, Router, Gate, SlowTask/UserPatch mutation, and browser dispatch.
If a fault lands after Router append, recovery reuses that Router event and
completes only a missing Gate/output phase. It never reruns Router, repeats a
task mutation, or retries a browser terminal that was already attempted.

The core Fast Foreground Gate required an immutable context, but the original
candidate text check was later shown to be an allow-by-default keyword policy.
Slice 3A.1.2 replaces it with provenance-based default quarantine.

`ACCEPT` and `REJECT` confirmation hints require a current pending confirmation
bound to task identity, scope, plan version, task event sequence, turn, request,
ASR evidence, epoch, confidence, and uncertainty. Orphan signals and ambiguous
or not-applicable signals cannot fall through into an ordinary UserPatch.

Voice lifecycle state is bounded and terminal records move to bounded
tombstones. Invalid `response.created` schedules one coalesced Voice-only
rebuild outside the coordinator lock. New PCM during rebuild is boundedly
dropped, never replayed; a failed rebuild leaves Voice degraded without ending
Control or the browser session. Ordinary provider receive idle is not treated
as terminal. Actual WebSocket close remains terminal, and receiver cancellation
does not leave a detached receive task.

Provider-free closure evidence on 2026-07-22:

- `./scripts/test tests/experiments -q`: `387 passed in 16.19s` with local
  loopback binding;
- `./scripts/test -q`: `2050 passed in 22.07s`;
- authoritative control-plane selection: `96 passed in 0.36s`;
- sandbox-only Qwen slice: `286 passed, 13 skipped in 8.41s`, with all skips
  caused only by denied loopback binding;
- long-session coverage includes 300 end-to-end turns.

Real-live turn evidence was not rerun for this closure and remains
`not_executed`; the prior startup-only sample is not a committed-turn result.

## Slice 3A enforced-control boundary

The browser still opens one loopback WebSocket. `dual_session_enforced_control`
keeps Voice ingress and text-only Control on separate Qwen connections:

```text
browser microphone PCM
  -> Voice Session (smart_turn, speech start/stop, ASR delta/final)
     -> automatic Voice assistant output: quarantine -> cancel -> terminal
        -> delete provider output items, or taint/rebuild Voice only
     -> committed ASR final + minimized current task snapshot
        -> Control Session (turn_detection=null, modalities=["text"])
        -> strict propose_turn_disposition Function Call validation
        -> locally bound FastInteraction evidence in authoritative journal
        -> deterministic local Router
           -> Fast Foreground Gate -> committed bounded text candidate
           -> MockSlowTask / UserPatch owner -> controlled text ACK
           -> IGNORE / controlled CLARIFY
```

Qwen's proposal is always `non_authoritative`; the local Router is
`authoritative`. No Qwen task ID, plan version, task event sequence, raw task
text, or provider-suggested state mutation is trusted. Execution rereads the
latest local TaskFocus snapshot, and stale/superseded Control results fail
closed. Every committed turn reaches a local dispatch or a degraded
ignore/clarification outcome.

The foreground is text-only. Voice assistant transcript and PCM are never
released, never become a Fast candidate, and never enter QA or the player.
Arbitrary Control Function Call reply text is not eligible for display in
Slice 3A.1.2. A Gate failure discards it and may commit only a server-owned
deterministic ACK/CLARIFY template. Fake/provider-free Gate tests can use an
explicit trusted-synthetic policy that is structurally distinct from provider
provenance. The SlowTask runtime is mock; there is no real Slow LLM, tool
execution, or external side effect.

## Slice 2 shadow boundary

The browser still opens one loopback WebSocket. Its coordinator owns two logically independent provider connections:

```text
browser microphone PCM
  -> RealtimeSessionCoordinator
     -> Voice Session (smart_turn, ASR, normal assistant text/audio, cancel)
     -> final ASR transcript + minimized task snapshot
        -> Shadow Control Session (turn_detection=null, text only,
           propose_turn_disposition Function Call)
        -> strict local validation
        -> isolated deterministic Router evaluation journal
        -> redacted Shadow panel / experiment metadata only
```

This topology is named `dual_session_shadow`. It does not prove that Voice and control can safely share one future provider connection.

The Qwen proposal is non-authoritative. Shadow processing never creates or patches a SlowTask, emits a UserPatch, commits through the Fast Foreground Gate, changes authoritative `TaskFocusState`, changes `plan_version`, executes a Function Call as a tool, or selects/cancels user-visible output. The optional `reply_candidate_text` remains transient and never enters QA, playback, timeline, journal, or logs.

`--audio-output qwen` projects the independent Voice Session's normal Qwen audio experience. It is not audio selected by the Shadow Router and is not evidence that the proposed provider-native foreground contract has been accepted. No Shadow candidate can enter this stream.

## Prerequisites

- Python 3.11 or newer.
- `aiohttp` already installed in the selected interpreter.
- A browser with AudioWorklet support for microphone testing.
- For real mode only, `DASHSCOPE_API_KEY` and a Qwen Realtime workspace ID available to the backend process.

No command in this directory installs or fetches dependencies. Raw audio, raw provider payloads, full Function Call arguments, credentials, and unredacted traces are not persisted.

## Fake Slice 1 mode

This remains the deterministic regression path:

```bash
/Users/a123/anaconda3/bin/python \
  experiments/qwen_realtime_fast_slow_web/server.py \
  --provider fake \
  --routing enforced \
  --slow-runtime mock \
  --audio-output fake_pcm \
  --shadow-control dual_session \
  --host 127.0.0.1 \
  --port 8767
```

Open <http://127.0.0.1:8767/>. Fake/enforced keeps the Slice 1 scenario buttons, CandidateQuarantine, canonical Router/Gate, MockSlowTask, UserPatch, playback epoch, interruption, and synthetic PCM behavior.

For provider-free Shadow panel automation, use `--provider fake --routing shadow --audio-output fake_pcm`. Fake shadow results still have no authority and do not run the enforced path.

## Real Qwen Enforced Control mode

This mode must be selected explicitly and must disable provider audio:

```bash
/bin/zsh -lc '
  source ~/.voice-agent-secrets/dashscope.env &&
  /Users/a123/anaconda3/bin/python \
    experiments/qwen_realtime_fast_slow_web/server.py \
    --provider qwen \
    --routing enforced \
    --slow-runtime mock \
    --audio-output none \
    --shadow-control dual_session \
    --host 127.0.0.1 \
    --port 8767
'
```

`qwen + enforced + --audio-output qwen` is rejected with the safe code
`qwen_enforced_provider_audio_unsupported`. Omitting `--routing` for Qwen still
selects Shadow; enforced never becomes an implicit default.

## Real Qwen Shadow mode

Do not paste credentials into command history, browser controls, or issue text. Load the existing secret file into the backend shell without printing it:

```bash
/bin/zsh -lc '
  source ~/.voice-agent-secrets/dashscope.env &&
  /Users/a123/anaconda3/bin/python \
    experiments/qwen_realtime_fast_slow_web/server.py \
    --provider qwen \
    --routing shadow \
    --slow-runtime mock \
    --audio-output qwen \
    --shadow-control dual_session \
    --host 127.0.0.1 \
    --port 8767
'
```

Omitting `--routing` and `--audio-output` selects `shadow` and `qwen`
respectively when `--provider qwen` is chosen, so the Slice 2 experience
remains available.

The backend resolves the workspace in this order:

1. `QWEN_REALTIME_WORKSPACE_ID`.
2. The validated Beijing host from `QWEN_REALTIME_BASE_URL` or `--qwen-base-url`.
3. `--workspace-id`.
4. `--verified-workspace-id`, only when the caller has independently verified it.

The compatible-mode HTTP URL is never used as a WebSocket endpoint. Only its validated Beijing hostname may supply the workspace ID. The adapter constructs:

```text
wss://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime?model=qwen-audio-3.0-realtime-plus
```

The API key stays inside an opaque backend `CredentialHandle`; browser and serializable metadata receive only presence flags and one-way refs.

## Voice and Control protocols

The Voice Session reuses the isolated audio-only provider core. It configures Qwen audio/text conversation with `smart_turn`, streams PCM16LE 16 kHz mono input, emits ASR delta/final, streams assistant transcript and PCM16LE 24 kHz mono output, and supports `response.cancel`. A Voice disconnect ends that browser session; no pre-disconnect microphone audio is replayed.

The Shadow Control Session uses:

- `modalities=["text"]` and `turn_detection=null`;
- one strict `propose_turn_disposition` function schema;
- `conversation.item.create`, then `response.create`;
- Function Call argument delta/done correlation;
- `conversation.item.delete` for input/output items with delete confirmation;
- control-only taint and connection rebuild when cleanup cannot be confirmed.

The official protocol pages were rechecked on 2026-07-22: the current model is
`qwen-audio-3.0-realtime-plus` on the Beijing workspace WebSocket endpoint;
`smart_turn` automatically triggers model generation; `response.cancel` has a
matching cancelled `response.done`; conversation items have delete/deleted
events; and Function Call argument delta/done events carry correlation IDs.
The pages do not document an auto-response-suppression field or protocol-level
forced `tool_choice`. The capabilities therefore remain
`voice_auto_response_suppression=unsupported_or_unverified` and
`forced_route_function_call=unsupported_or_unverified`. See the official
[user guide](https://help.aliyun.com/zh/model-studio/qwen-audio-realtime-user-guides),
[WebSocket API](https://help.aliyun.com/zh/model-studio/fun-audiochat-realtime-websocket-api),
[client events](https://help.aliyun.com/zh/model-studio/fun-audiochat-client-events),
and [server events](https://help.aliyun.com/zh/model-studio/qwen-audio-realtime-server-events).

In enforced mode, the Voice adapter keeps raw provider response/item IDs only
inside its contained transport for correlation and deletion. It requests
cancel on `response.created`, suppresses every assistant text/audio frame,
waits for the matching terminal, deletes all correlated output items, and
requires delete acknowledgement. Missing terminal/correlation or unconfirmed
deletion taints and rebuilds only Voice; accepted microphone PCM is never
replayed. Control uses the equivalent cancel/terminal/delete/rebuild fencing
for superseded requests. Ordinary text, missing/multiple/wrong Function Calls,
malformed JSON, schema violations, oversized candidates, timeouts, provider
errors, correlation mismatches, late results, and tainted context fail closed
with no fabricated proposal and no SlowTask/UserPatch mutation.

## Provider frame, authority, and dispatch

The provider frame contains only versioned enums, booleans, bounded risk tags, confidence in `[0,1]`, and an optional bounded transient reply candidate. Provider-supplied `turn_id`, `task_id`, or `plan_version` are rejected; the coordinator supplies local turn/utterance/ASR binding.

The current `TaskFocusSnapshot` is minimized before injection. Task IDs are one-way refs; the control session receives only the fields needed to distinguish active/terminal/confirmation context. A validated proposal is evaluated by the existing deterministic Router using a separate short-lived journal. Nothing from that journal is reduced into authoritative session state.

Experiment-only browser messages are explicitly named `route.shadow.proposed`, `route.shadow.validated`, `route.shadow.compared`, `route.shadow.degraded`, and `shadow.state`. They are not ADR-002 canonical events.

Enforced mode normalizes the same strict frame into an existing
`FastInteractionOutput` bound to the local committed turn, utterance, ASR ref,
and playback/control epoch. It appends only existing ADR-002 registry events to
the browser session journal. The local Router decides `FAST_ONLY`,
`SPAWN_SLOW_TASK`, `PATCH_ACTIVE_SLOW_TASK`, or `IGNORE`; the existing Gate
then authorizes/discards the candidate. Browser `route.proposed`,
`route.decided`, `gate.result`, `dispatch.result`, and `control.state` frames
are bounded metadata projections, not canonical replay inputs.

- `FAST_ONLY`: requires local foreground chat, provider FAST hint, ANSWER, LOW
  risk, threshold confidence, a valid bounded candidate, and current turn/epoch.
- `SPAWN_SLOW_TASK`: discards provider text, creates exactly one local mock task,
  and may emit controlled `ACK_SLOW` text.
- `PATCH_ACTIVE_SLOW_TASK`: rereads the active task, uses the canonical
  UserPatch pipeline, and advances `plan_version` only through that owner.
- `IGNORE/NON_ASSISTANT`: is silent and cannot create/patch a task.
- `AMBIGUOUS` or any fail-closed assistant-directed turn: emits only a local
  controlled clarification, or silence when ingress is not assistant-directed.

## Browser protocol and safety

The page is loopback-only, requires a same-port loopback `Origin`, caps frames, and creates a fresh coordinator and provider sessions per browser connection. Browser PCM frames are transient. Output binary frames remain `QFS2` + unsigned playback epoch + PCM16LE.

The Shadow panel remains available. Enforced mode adds explicit topology,
authority, audio-disabled, Voice/Control health, safe turn, Qwen/local route,
focus/act, schema, Gate, dispatch, task/plan/stale, latency,
cancel/delete/rebuild, suppression, and output-mode fields. In enforced mode,
QA accepts only server-committed Control candidate or controlled-template
text, and the browser rejects binary output before AudioWorklet playback.

Metadata uses an allowlist. It excludes API keys, Authorization headers, raw audio, raw provider bodies, complete Function Call arguments, full reply candidates, and unredacted transcript content.

## Tests

Run the provider-independent Slice suite:

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python \
  ./scripts/test tests/experiments/qwen_realtime_fast_slow -q
```

Run related control-plane regressions:

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python \
  ./scripts/test \
  tests/interaction \
  tests/router \
  tests/runtime/test_mvp63_fast_foreground_gate.py \
  tests/user_patch \
  tests/slowtask -q
```

Real credentials are never an automated-test prerequisite.

Run a metadata-only synthetic ingress smoke against the real Control Session:

```bash
/bin/zsh -lc '
  source ~/.voice-agent-secrets/dashscope.env &&
  /Users/a123/anaconda3/bin/python \
    experiments/qwen_realtime_fast_slow_web/live_enforced_control_smoke.py
'
```

This smoke prints a bounded JSON summary only. It uses Fake Voice ingress and
does not claim real microphone, Voice, ASR, or audio coverage.

## Manual live checklist

1. Confirm Voice ingress and Control both show connected and the topology is
   `dual_session_enforced_control`.
2. Verify one Control request follows each final ASR turn; ASR deltas never
   create/patch/cancel state.
3. Verify simple gated text appears only after local Router/Gate commit and
   binary playback stays zero.
4. Verify a complex task creates only a MockSlowTask and active-task input uses
   canonical UserPatch/plan-version events.
5. Verify ambiguous input uses only controlled clarification and ignore is
   silent.
6. Interrupt while Control/Voice is active and confirm stale results and old
   audio never bind to the new epoch.
7. Verify Voice cancel terminal and item-delete acknowledgement counters; any
   cleanup failure must rebuild Voice only.
8. Search page/server output for credential values, Authorization headers, raw
   PCM, full provider payloads/arguments/candidates, and transcript in metadata.
9. Disconnect/reconnect and confirm fresh session/task/conversation/context
   without microphone replay.

## Explicit limitations

Slice 3A cannot claim authoritative Qwen routing or task focus, provider-native
foreground audio, real SlowTask/Slow LLM execution, Qwen-created UserPatch,
forced Function Call support, single-session safety, production reconnect
continuity, production privacy/auth, external tools, or external side effects.

It also does not by itself pass the unaccepted provider-native foreground audio contract, ADR-001 target Duplex semantic quality, ADR-003 playback-reference AEC/physical Talker stop, or ADR-017 gate-before-leak requirements for provider-native streaming output.

The proposal remains unaccepted. Before Slice 3B can authorize
provider-native foreground audio, it must define an accepted single-stream
authority/buffering protocol, prove token and PCM zero-leak before Gate commit,
provide authoritative response/item correlation and confirmed cleanup under
cancel/interrupt/reconnect, resolve Function Call absence without prompt
assumptions, validate real route quality/latency at useful scale, and preserve
deterministic replay without silently expanding canonical events. Do not merge
Voice and Control into one session before those prerequisites are accepted and
tested.

## Slice 3A.1.3 provider-free closure

The Slice 3A.1.2 acceptance is superseded and no longer authorizes Slice 3A.2.
Slice 3A.1.3 adds an immutable Voice authority token binding provider
generation, coordinator rebuild generation, and session ref; blocked transcript
projection is cancelled when that generation retires. Missing/empty session
refs fail closed, while the adapter freezes the generation ref before provider
receive so concurrent close cannot erase stale-event identity. The 65th
input/provider identifier or response identifier schedules one coalesced
Voice-only rebuild, drains retired PCM, and requires the replacement generation
to accept fresh input.

Foreground fallbacks now come from one versioned exact template catalog.
Missing, quarantined, risky, ambiguous, and failed FAST output clarifies.
`ACK_SLOW`/`ACK_PATCH` is truthful only after complete canonical SPAWN/PATCH
mutation; partial mutation cannot retain or deliver a success ACK. Live Gate
authority uses the current target turn/reducer/task/confirmation/plan/sequence
state; an active-task snapshot without canonical SlowTask journal history
cannot authorize PATCH. `FAST_ONLY` cannot bypass a terminal Gate when
candidate evidence is missing.

Replay enforces per-turn cardinality for Router, terminal Gate, foreground
commit, SPAWN initiation, and PATCH/UserPatch initiation. Its digest includes
stable Router/Gate/commit identity and basis/ref fields without provider reruns
or raw text. See
`docs/implementation/qwen-realtime-fast-slow-slice3a13-acceptance.md` for the
hard-gate evidence and qualification verdict.

## Slice 3A.2.1 committed-turn authority

In Qwen enforced mode, provider generation authority ends only after the
canonical final-ASR event is appended. That boundary transfers Control work to
an immutable local token bound to session, conversation, turn, utterance, ASR
event/ref, and playback epoch. Cleanup-only Voice rebuilds no longer discard
already committed Control work. New speech, a newer committed turn, interrupt,
epoch change, disconnect, close, or correlation mismatch still retires it.
Superseded work is metadata-only and cannot produce an old Router/Gate chain or
semantic reply.

Voice ingress now distinguishes transient rebuild/taint/generation conditions
from a real send failure. Recovery frames are dropped and never replayed, one
recovery episode produces one bounded degradation notice, and
`voice_send_failed` taints once and schedules one coalesced Voice-only rebuild.
Cancel terminal state is exposed only through the five-value bounded outcome
documented in
`docs/implementation/qwen-realtime-fast-slow-slice3a21-acceptance.md`.
