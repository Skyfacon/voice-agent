# Qwen Realtime Fast/Slow Slice 3A.2.1 Acceptance

Date: 2026-07-24 (+0800)

Status: `executed_partial`.

Branch: `codex/adr-017-fast-interaction-adapter`

Baseline HEAD: `ca44cd750afae901502c3cbe7178b6385e7e523d`

The shared worktree remained intentionally dirty and uncommitted. This slice
did not reset, restore, clean, switch worktrees, create a branch, commit, push,
or open a pull request. It did not change the accepted ADR register, canonical
event registry, or `src/voice_agent/`.

## Scope and fixed authority

The only live topology in scope is:

```text
--provider qwen --routing enforced --slow-runtime mock
--audio-output none --shadow-control dual_session
```

Voice and Control remain separate sessions. Qwen Control output is
non-authoritative evidence. The Local Router and deterministic Fast Foreground
Gate remain authoritative. Provider text candidates, provider-native audio,
raw PCM, real tools, external writes, real SlowTask/Slow LLM, and a merged
Voice+Control session remain outside this slice.

## Root cause reproduced

After a provider final transcript had already appended the canonical
`ASR_TRANSCRIPT_OUTPUT_EMITTED`, the serialized Control worker still rechecked
the Voice provider-generation token before and after Control awaits. A
cleanup-only Voice rebuild retired that token. The already committed Control
request therefore reached `analyze()` once but was discarded before the Local
Router and Gate:

```text
(Control analyze, Router, Gate) = (1, 0, 0)
```

The PCM loop independently collapsed every real adapter exception to
`audio_forward_failed`, so a temporary rebuild/taint window could create
per-frame safe-error noise despite the adapter's typed recovery conditions.

The first human-present retry exposed two additional lifecycle races. A
non-terminal provider cleanup error before final ASR claimed the turn's
terminal before local Control authority existed, so the later committed
Control result was discarded. During the resulting cleanup rebuild, the
single receiver owner could poll the replacement core while its handshake was
still in progress, raise `voice_receiver_generation_rebuilding`, and exit.
Without a receiver, the replacement WebSocket later timed out and the next PCM
frame became `voice_send_failed`.

Final review also reproduced a coordinator/adapter taint split: terminal
`provider.error` and invalid input correlation scheduled a coordinator rebuild
without first tainting the adapter, so `rebuild_if_tainted()` could return a
no-op and leave Voice without a live receiver.

## Implemented authority separation

Provider authority is required until the canonical final-ASR append. The same
synchronous section then creates an immutable local committed-turn token that
binds:

- `session_id` and `conversation_id`;
- `turn_id` and `utterance_id`;
- canonical final-ASR `event_id` and `asr_frame_ref`;
- the turn's `playback_epoch`.

The Control queue and worker use that local token, not Voice transport
generation. A cleanup-only Voice rebuild can therefore complete while an
already committed Control request is running, and the request still produces
exactly one correlated Local Router and Gate result.

New speech, a newer committed turn, explicit interrupt, playback-epoch change,
disconnect, browser close, and correlation mismatch still invalidate the old
local token. Superseded or queue-dropped Control work is recorded only as
bounded late/degraded metadata. It does not append an old Router/Gate chain,
mutate SlowTask/UserPatch, emit a semantic reply, or rebind to a newer turn.
Provider events blocked before the canonical ASR append continue to use the
Voice generation fence and remain content-free discards after rebuild.

## Cancel and recovery behavior

The Voice adapter exposes a read-only bounded terminal outcome:

```text
cancelled_on_time
cancelled_after_watchdog
completed_after_cancel
failed_after_cancel
missing_terminal
```

Only `cancelled_on_time` is a successful cancel terminal. Late cancellation,
completion, failure, and missing terminal remain unsafe, taint Voice, and
require the existing fail-closed rebuild path. Confirmed item deletion does not
turn an unsafe terminal into success.

Ingress availability uses typed codes for rebuild, taint, disconnected, stale
generation, and retired generation. Recovery-window frames are dropped and
counted immediately and are never replayed. One recovery episode emits one
bounded `voice_recovering` degradation message, not a per-frame
`audio_forward_failed` flood.

A real provider send exception becomes `voice_send_failed`. The adapter taints
and counts it once per Voice generation; the coordinator emits at most one safe
error for that generation, drains retired queued frames, and schedules one
Voice-only rebuild. Concurrent rebuild callers join the existing attempt and
are counted separately from actual rebuilds.

A pre-ASR non-terminal provider error now remains cleanup evidence only:
Voice stays connected/untainted and no Control terminal is claimed. Terminal
provider errors and invalid input correlations taint the adapter before
coordinator rebuild scheduling. The receiver owner parks on the exact rebuild
task until the replacement generation connects. Recovery-critical browser
projections are best effort and bounded to 250 ms, so a stalled browser cannot
hold the coordinator lock or terminate Voice recovery.

## Provider-free evidence

Initial authority RED:

```text
ASR final = 1
Control analyze = 1
Local Router = 0
Gate = 0
```

Final automated results:

```text
Slice 3A.2.1 cancel + committed authority: 31 passed
Qwen experiment suite: 420 passed, 13 skipped
Interaction/Router/Gate/UserPatch/SlowTask: 104 passed
Security suite: 8 passed
Full repository: 2219 passed in 43.75s
node --check static/app.js: passed
git diff --check: passed
```

The 13 Qwen-suite skips are the existing restricted live/loopback cases, not
test failures. Tracked-artifact scanning found no raw audio/cache/trace file,
and the task-file credential scan matched only an intentional synthetic
`Authorization: Bearer SENTINEL_SECRET` negative test.

## Official protocol boundary

Alibaba documentation rechecked on 2026-07-24 supports PCM16 16 kHz mono input,
PCM16 24 kHz mono provider output, smart-turn configuration before audio,
push-to-talk commit plus explicit response creation, response cancellation and
terminal statuses, and item deletion acknowledgement. This slice keeps
provider output disabled.

The checked documentation does not establish `create_response=false` for
smart turn and does not prove forced Function Calling/tool choice for this
Audio Realtime path. Both remain `unsupported_or_unverified`; no OpenAI-style
field is inferred.

## Security invariants

- no raw audio, transcript, candidate, provider payload, Function Call
  arguments, credential, cookie, token, authorization header, or provider
  response/item ID enters journal or timeline metadata;
- UI-visible outcome values are fixed enums and counters are non-negative
  bounded metadata scalars;
- Voice PCM and natural-language output remain quarantined;
- binary playback must remain zero;
- no new `diagnostics/`, `traces/`, `replays/local/`, or `audio/raw/` artifact
  is permitted.

## Live qualification

The real server was started with the exact required dual-session command and
process-only credentials. The in-app browser showed Voice and Control
`connected`, microphone `capturing`, Local Router `authoritative`, Qwen
proposal `non_authoritative`, provider-native audio disabled, mock SlowTask,
and binary playback 0.

On the final human-present retry both fixed phrases produced real final ASR
without persisting either transcript. Each committed turn produced exactly one
Local Router, Gate, and dispatch terminal:

```text
real ASR final rows: 2
Control schema status: valid
Local route.decided: 2
Local gate.result: 2
dispatch.result: 2
SlowTask/UserPatch creation: 0
binary playback frames: 0
```

Both local paths terminated safely as `FAST_ONLY / AMBIGUOUS`, with Gate
`failed` and controlled degraded dispatch reason
`control_confirmation_orphan`; neither turn advanced SlowTask or UserPatch.
The last projected latency sample was 2.4 ms from ASR to Control request,
388.0 ms to first Control delta, and 2709.0 ms to Control call completion.
Router+Gate latency was not projected for the fail-closed outcome.

The final bounded lifecycle counters were:

```text
cancel terminal outcome: completed_after_cancel
Voice cancel requests: 2
successful cancelled terminals: 0
unsafe cancel terminals: 2
completed after cancel: 2
confirmed Voice deletes: 2
Voice rebuilds: 2
Voice PCM drops during recovery: 5
Voice send-failure generations: 0
coalesced duplicate rebuild callers: 0
assistant text frames suppressed: 28
provider audio frames suppressed: 22
binary playback frames: 0
Control errors/timeouts: 0 / 0
safe errors / recovery notices: 2 / 2
final Voice context: connected, clean
```

The committed-turn authority/cardinality portion passed: cleanup rebuilds did
not eat either committed turn, the second turn survived the first recovery,
there was no per-frame safe-error flood, and no provider candidate or binary
audio leaked. The recovery gate did not pass because the two turns produced
two physical Voice rebuilds rather than at most one rebuild across the
two-turn qualification. Both rebuilds recovered cleanly and no PCM was
replayed, but `real_live_verified` therefore remains `false`.

Microphone capture was stopped, both provider sessions were disconnected, and
the task-owned server was stopped. No generated audio or synthetic text was
substituted.

## Live verdict

Two-turn microphone smoke: `executed_partial`; ASR and authoritative
cardinality passed, recovery-count gate not passed.

Ten-turn qualification: `not_executed` because the two-turn prerequisite did
not pass.

Slice 3B admission: `NO_GO`. The hotfix and provider-free recovery closure are
verified, but real Voice still classifies both observed cancels as
`completed_after_cancel` and rebuilds once per turn. A later qualification must
reduce or explicitly accept that provider lifecycle before ten-turn evidence
can be collected.
