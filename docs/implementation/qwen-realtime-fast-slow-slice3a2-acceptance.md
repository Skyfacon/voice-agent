# Qwen Realtime Fast/Slow Slice 3A.2 Acceptance

Date: 2026-07-24 (+0800)

Status: `executed_partial`.

Branch: `codex/adr-017-fast-interaction-adapter`

HEAD: `ca44cd750afae901502c3cbe7178b6385e7e523d`

The branch remained eight commits ahead of its remote and the shared worktree
remained intentionally dirty and uncommitted. This slice did not reset,
restore, clean, switch worktrees, commit, push, or open a pull request. It did
not modify the accepted ADR register or the ADR-002 canonical event registry.

## Scope and fixed authority boundary

This slice closes the Voice stale-cleanup generation P1 and performs a bounded
real-provider qualification of the existing experimental topology:

```text
--provider qwen --routing enforced --slow-runtime mock
--audio-output none --shadow-control dual_session
```

The topology is still `dual_session_enforced_control`. Qwen Voice and Qwen
Control are physically separate sessions. Qwen Function Call output is
non-authoritative evidence; the Local Router and deterministic Gate remain the
only dispatch authority. Qwen reply candidates and Voice PCM remain
quarantined. FAST output is a server-controlled committed template, not a real
Qwen answer. Provider-native audio, real SlowTask/Slow LLM, real tools, and
external side effects remain prohibited. This is not Slice 3B and does not
qualify single-session Voice+Control.

## Stale-cleanup P1

### Root cause

`QwenVoiceAdapter.cleanup_suppressed_response()` awaited provider item deletion
and then attributed the completion to whichever Voice generation was current
when the await returned. A blocked generation G1 cleanup could outlive a
successful G1-to-G2 rebuild. Its late failure could taint G2, and its late
success could mutate counters or remove a same-ID replacement lifecycle.

`RealtimeSessionCoordinator._cleanup_voice_response_outside_lock()` also
scheduled a rebuild after the provider await before it revalidated the exact
response lifecycle and generation authority. A late G1 failure could therefore
trigger a second rebuild, drain G2 PCM, or project G2 as degraded.

### RED evidence

Before production edits:

- adapter adversarial file: `3 failed, 2 passed`; stale false/exception
  incremented the replacement generation's delete-failure counter, and stale
  success reached current-generation mutation;
- coordinator adversarial file: `2 failed, 1 passed`; stale false/exception
  each caused `rebuild_calls == 2` after G2 was already connected.

All RED tests used synthetic identifiers and PCM only. They recorded no
response content, raw audio, credential, provider payload, or canonical event.

### Fix

The adapter now captures immutable cleanup authority before the provider await:
core object identity, provider session generation, non-content session ref,
and response lifecycle object identity. Both returned and exceptional
completions revalidate all four fields before any counter, taint, lifecycle,
correlation-map, or stale-ID mutation. A retired completion returns a
content-free `False` no-op. A current-generation cleanup failure still taints
Voice and fails closed.

The coordinator now captures the lifecycle authority token before the provider
await, then under its state lock revalidates the exact lifecycle object,
immutable token, provider generation, coordinator rebuild generation, and
session ref before success mutation or rebuild scheduling. It also requires
the current real adapter context to be tainted before rebuilding. No lock is
held across provider I/O. Concurrent current-generation failures coalesce into
one Voice-only rebuild; close cancels blocked cleanup safely.

### GREEN evidence

- new adapter plus coordinator adversarial tests: `10 passed`;
- Slice 3A.2 plus generation/delivery/replay/provenance focus: `41 passed`;
- adapter/generation/delivery regression: `55 passed`;
- full Qwen suite: `390 passed, 13 skipped`; all 13 restricted runs cited
  sandbox-denied loopback binding;
- exact elevated loopback rerun: `21 passed`;
- fake enforced, Qwen shadow, and enforced CLI flag regressions: `40 passed`;
- interaction/router/Gate/UserPatch/SlowTask: `104 passed`;
- security suite: `8 passed`;
- final full repository: `2189 passed`.

The current-generation failure path still triggers exactly one coalesced
Voice-only rebuild. Stale false, exception, and success completions do not
taint or degrade G2, do not trigger a second rebuild, do not retire a same-ID
replacement, and do not prevent fresh or subsequent generation-bound PCM.

## Official Alibaba protocol recheck

Rechecked on 2026-07-24:

- current documented models include `qwen-audio-3.0-realtime-plus` and
  `qwen-audio-3.0-realtime-flash`;
- the Beijing endpoint is
  `wss://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime?model=<model_name>`;
- input is PCM16, 16 kHz, mono; documented provider output is PCM16, 24 kHz,
  mono, but Slice 3A.2 disables that output;
- `session.update` supports `modalities=["text"]` and the default
  `modalities=["audio","text"]`;
- `smart_turn`, ASR delta/final, `response.created`, `response.cancel`,
  terminal `response.done`, `conversation.item.delete/deleted`, and Function
  Call argument delta/done are documented;
- the client-event rules enforce at most one active response in the relevant
  turn state;
- the checked pages document tools and model-selected Function Calling but do
  not document forced `tool_choice`.

Therefore:

```text
forced_route_function_call=unsupported_or_unverified
```

Prompt compliance and ordinary assistant text are not treated as protocol
proof or route authority.

## Bounded real-provider qualification

Credentials were loaded process-only from the existing secret file. Only the
presence of the expected variables was printed. No key, workspace ID,
Authorization header, full `session.update`, provider payload, Function Call
arguments, candidate, transcript, or PCM was printed or persisted.

### Real Control synthetic smoke

The first restricted-network attempt returned `schema_status=not_available`
with zero Function Calls. One evidence-supported network-permission retry was
performed and passed:

| Field | Result |
| --- | --- |
| smoke kind | `synthetic_redacted_real_control` |
| Voice ingress | fake |
| Control provider | real Qwen |
| Function Call coverage | 1/1 |
| Schema valid | 1/1 |
| request to first delta | 420.818 ms |
| request to Function Call done | 2428.568 ms |
| Function Call done to local Router/Gate | 35.831 ms |
| Qwen route hint | `SPAWN_SLOW_TASK` |
| Local Router decision | `FAST_ONLY` |
| Route/focus/act agreement | false |
| Actual dispatch | degraded clarification |
| Binary playback | 0 |
| Unsafe assistant text | 0 |

The disagreement is not a safety failure: the Qwen proposal remained
non-authoritative and the local pipeline failed closed. This smoke proves only
real text-only Control with synthetic/redacted ingress; it does not prove real
Voice, microphone, ASR, or a real dual-session committed turn.

### Real dual-session browser

Both the in-app browser and Chrome reached:

- browser WebSocket connected;
- real Voice Session connected;
- real Control Session connected;
- `topology=dual_session_enforced_control`;
- `audio_output=none`;
- provider-native audio disabled;
- Local Router authoritative and Qwen proposal non-authoritative;
- binary playback frame count 0.

Chrome permission was explicitly granted for the local loopback page and the
microphone entered `capturing`. The page specifies continuous approximately
100 ms PCM16LE, 16 kHz, mono frames. During the bounded observation window the
input level remained 0%, so there was no actual speech sample and no ASR
delta/final. Synthetic text or generated audio was not substituted.

While the permission UI was unresolved, the real Voice connection reached its
bounded idle timeout repeatedly. The page observed five Voice-only rebuilds
that returned to `connected` and `clean`, with Control remaining connected and
binary playback at zero. This is useful reconnect/rebuild evidence, but it is
not a spoken-turn cancel/delete/correlation proof and not a seamless
production-recovery claim.

During that prolonged idle window the Control connection badge remained
connected while its context projection became `tainted`. With no ASR final,
the before-next-request Control rebuild path was not exercised. The separate
synthetic/redacted Control smoke did finish clean with two confirmed context
deletes. This distinction is another reason the browser live result is partial.

Disconnect stopped microphone capture, advanced the playback epoch, cleared
the player with 0 ms reported clear latency, and disconnected both provider
sessions. Reconnect created fresh connected Voice/Control state, reset
microphone to `not_requested`, reset the displayed rebuild counter, kept Voice
clean, and kept binary playback at zero. No pre-disconnect microphone PCM was
observed to replay.

The application page emitted zero console errors/warnings. Six Chrome
extension-level warnings were observed outside the loopback page and are not
counted as application console failures.

## Per-axis result

| Axis | Status | Evidence / limit |
| --- | --- | --- |
| `stale_cleanup_p1` | `executed_pass` | RED reproduced; adapter/coordinator GREEN and regressions passed |
| `real_control` | `executed_pass` | 1/1 real Control Function Call, schema valid |
| `real_voice_connect` | `executed_pass` | real Voice connected in both browser surfaces |
| `real_microphone` | `executed_partial` | permission granted and `capturing`; input level remained 0% |
| `real_asr_final` | `not_executed` | no actual speech sample |
| `function_call_coverage` | `executed_partial` | 1/1 synthetic/redacted Control; 0 real-ASR turns |
| `schema_validation` | `executed_partial` | 1/1 synthetic/redacted Control; no real-ASR sample |
| `route_fast` | `not_executed` | no real-ASR committed turn |
| `route_spawn` | `not_executed` | no real-ASR committed turn |
| `route_patch` | `not_executed` | no real-ASR committed turn |
| `route_ambiguous` | `not_executed` | no real-ASR committed turn |
| `route_ignore` | `not_executed` | no real-ASR committed turn |
| `cancel_terminal` | `not_executed` | no active spoken response |
| `provider_item_delete` | `not_executed` | no active spoken response |
| `control_context_delete` | `executed_pass` | synthetic Control smoke confirmed 2 deletes |
| `voice_rebuild` | `executed_partial` | five real idle-timeout rebuilds returned connected/clean; no spoken-turn rebuild |
| `interrupt_late_event` | `not_executed` | no active spoken Voice/Control turn |
| `reconnect` | `executed_pass` | disconnect cleanup and fresh dual-session reconnect observed |
| `zero_binary_playback` | `executed_pass` | zero throughout Control, dual-session, rebuild, disconnect, reconnect |
| `candidate_non_leakage` | `executed_pass` | unsafe assistant text 0; QA contained no provider candidate |
| `credential_and_artifact_safety` | `executed_pass` | process-only credentials; no raw artifacts or sensitive output |

Live committed-ASR sample count is 0. Consequently route coverage, Qwen/local
agreement for real audio turns, and real-turn latency percentiles are
`not_available`. The single synthetic/redacted Control sample is reported
individually above; no p50/p95 is fabricated.

## Security and privacy

- provider candidates and Voice PCM remained quarantined;
- QA received no Qwen Voice transcript or provider candidate;
- browser player received zero binary frames;
- metadata remained bounded and allowlisted;
- no raw audio, raw provider payload, full Function Call arguments, full
  candidate, Authorization header, key, or complete real transcript was logged
  or written;
- no new `diagnostics/`, `traces/`, `replays/local/`, or `audio/raw/` artifact
  was created;
- the local browsers and port 8767 were closed after qualification;
- static/provider-free security review passed with no new P0/P1.

## Verdict and next slice

Overall: `executed_partial`.

Slice 3B-MVP admission: `NO_GO` for an unconditional entry because there is no
real spoken ASR/route/cancel/delete committed-turn sample and the minimum
8-of-10 schema-valid live-turn smoke gate was not exercised. The stale-cleanup
P1 itself is closed and no new P0/P1 was found.

The minimum next qualification is a human-present, headphone-assisted run with
at least ten non-sensitive spoken assistant-directed turns covering FAST,
SPAWN, PATCH, AMBIGUOUS, and IGNORE; it must record at least eight schema-valid
Function Calls, no duplicate canonical mutation, real cancel terminal and
delete acknowledgement, interrupt/late-event discard, and zero candidate/PCM
leakage. Until that passes, retain two physical sessions, Local Router
authority, `audio_output=none`, mock SlowTask, terminal fail-closed behavior,
and browser reconnect on untrusted taint. Do not merge to a single session and
do not enable provider-native foreground audio.
