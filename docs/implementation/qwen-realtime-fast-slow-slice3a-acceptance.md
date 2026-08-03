# Qwen Realtime Fast/Slow Slice 3A Acceptance

Date: 2026-07-22

Status: superseded as full acceptance evidence first by the Slice 3A.1 audit and then by the Slice 3A.1.1 closure. The `234 passed, 13 skipped` and later `271 passed, 13 skipped` results are historical regression evidence only: post-Router duplicate authority, LOW-plus-payment Gate leakage, orphan confirmation mutation, a false pre-connect health expectation, and long-session lifecycle gaps were subsequently reproduced. Current provider-free closure evidence is recorded in `qwen-realtime-fast-slow-slice3a1-acceptance.md` (`387 passed` loopback, `2050 passed` full repository). Real microphone, real Voice/ASR/cancel-cleanup, committed two-real-provider turns, reconnect, and browser-console evidence remain `manual_not_executed` or `not_executed`. The architecture ADR remains a proposal unless a human explicitly accepts it.

## Acceptance boundary

- Explicit mode: `provider=qwen`, `routing=enforced`, `slow_runtime=mock`, `audio_output=none`, `shadow_control=dual_session`.
- Topology: one Voice ingress session plus one independent text-only Control session behind one loopback browser WebSocket. The status name is `dual_session_enforced_control`; this is not a single-session design.
- Voice owns continuous microphone PCM upload, speech start/stop, ASR delta/final, provider response cancellation, and Voice-context cleanup. Its assistant text and PCM are quarantined and are never a Fast candidate, QA output, or playback source.
- Control produces an untrusted `propose_turn_disposition` Function Call. The coordinator binds a validated result to local `turn_id`, `utterance_id`, ASR reference, request correlation, and generation/epoch before converting it to FastInteraction evidence.
- The authoritative browser-session Event Journal, deterministic local Router, Fast Foreground Gate, MockSlowTask runtime, and UserPatch pipeline own all state transitions and user-visible dispatch.
- Only a same-call, bounded Control `reply_candidate_text` may become a direct reply, and only after local Router and Gate authorization. Slice 3A never plays provider-native Qwen PCM.
- Qwen provider IDs and returned task/version/sequence fields are not authoritative. The latest local task snapshot is reread immediately before dispatch.
- No real Slow LLM, external tool, side effect, `function_call_output`, or provider-native foreground audio is in scope.

## Capability and protocol matrix

| Capability | Required Slice 3A behavior | Verification state |
| --- | --- | --- |
| Current model | `qwen-audio-3.0-realtime-plus` only after an official-doc recheck | `executed_doc_recheck` on 2026-07-22: `qwen-audio-3.0-realtime-plus` |
| Beijing endpoint | workspace-scoped `/api-ws/v1/realtime`; credential remains backend-only | `executed_doc_recheck` on 2026-07-22: Beijing workspace endpoint with `/api-ws/v1/realtime` |
| Voice `session.update` | documented audio/text ingress configuration; do not invent undocumented suppression fields | documentation rechecked 2026-07-22; no undocumented suppression field is used |
| Voice continuous PCM and ASR | speech start/stop plus transient ASR delta; one committed ASR final drives one Control request | provider-free: `executed_pass`; real: `not_executed` |
| Voice ASR provider-item correlation | provider input item must bind exactly to local turn, utterance, audio span, and session generation | original Slice 3A claim: `not_executed_and_invalidated`; synthetic Voice finals did not establish real item binding, and missing/late item cases were not covered |
| Voice auto-response suppression | use only a documented capability; otherwise bounded quarantine, cancel, matching terminal, delete, taint/rebuild | official support: `not_documented` as of 2026-07-22; provider-free: `executed_pass`; real Voice: `not_executed` |
| Voice cancel terminal | cancel request alone is not completion; matching `response.done` or equivalent terminal is required | provider-free claim: `invalidated_by_slice3a1_reproduction`; real: `not_executed` |
| Voice item delete and rebuild | delete uncommitted provider output; failure taints and rebuilds only Voice; never replay old microphone PCM | provider-free claim: `invalidated_by_slice3a1_reproduction` because an interrupt could orphan matching terminal cleanup; real: `not_executed` |
| Control `session.update` | independent text-only session, `turn_detection=null`, one internal proposal function | provider-free: `executed_pass`; real Control synthetic/redacted smoke: `executed_pass` (1 sample) |
| Function Call | fragmented argument delta/done, strict function name/schema, one call per request | provider-free: `executed_pass`; real Control synthetic/redacted smoke: `executed_pass` (1/1 Function Call, 1/1 schema-valid) |
| Forced Function Call / `tool_choice` | must not be inferred from prompting | no documented forced `tool_choice` as of 2026-07-22; `forced_route_function_call=unsupported_or_unverified` |
| Control item delete/rebuild | acknowledge delete; taint/rebuild only Control on uncertain cleanup | provider-free: `executed_pass`; real Control smoke: `executed_pass` (`delete=2`, `rebuild=0`, `tainted=false`) |
| Text candidate | bounded, transient, same Function Call as route/focus/act/risk/confidence, Gate-authorized | provider-free: `executed_pass`; real Control smoke: candidate remained non-authoritative and unsafe assistant text count was `0` |
| Local Router authority | exactly one terminal local routing outcome per committed turn | provider-free: `executed_pass`; real Control smoke: `executed_pass` (Qwen/local route agreement was 0/1, and local authority prevailed) |
| Fast Foreground Gate | sole authority for committing Control candidate text | provider-free: `executed_pass`; real Control smoke: `executed_pass` (Function Call done to local Router/Gate: 62.805 ms; Router/Gate stage: 1.544 ms) |
| Slow runtime | existing canonical MockSlowTask creation path only | `executed_pass` |
| UserPatch | authoritative current-task binding and existing evidence/interpretation path only | `executed_pass` |
| Provider-native audio | disabled; binary playback frames must remain zero | provider-free: `executed_pass`; mixed real-Control/Fake-Voice smoke: `0`; real Voice: `not_executed` |

Capability correction: protocol declaration, implementation support, provider-free verification, and real-live verification are separate states. The Slice 3A document does not establish real-live support for response cancel, cancel terminal, provider item delete, context rebuild, or ASR item correlation; all remain `not_executed` as real-provider capabilities until live evidence is recorded.

Official sources rechecked on 2026-07-22:

- [Qwen Audio Realtime user guide](https://help.aliyun.com/zh/model-studio/qwen-audio-realtime-user-guides)
- [WebSocket API](https://help.aliyun.com/zh/model-studio/fun-audiochat-realtime-websocket-api)
- [Client events](https://help.aliyun.com/zh/model-studio/fun-audiochat-client-events)
- [Server events](https://help.aliyun.com/zh/model-studio/qwen-audio-realtime-server-events)

The review confirmed the model and Beijing workspace endpoint above. It found no documented automatic-response suppression capability and no documented forced `tool_choice`; therefore Slice 3A records `forced_route_function_call=unsupported_or_unverified`, uses quarantine/cancel/terminal/delete/rebuild for Voice output, and keeps every non-Function-Call result fail-closed. This review does not substitute for real Voice evidence: `smart_turn`, `server_vad`, manual turn behavior, real cancellation terminal semantics, and real Voice cleanup remain unaccepted until exercised on the real Voice connection.

## Provider-free behavior matrix

| Area | Required evidence | Expected terminal behavior | Status |
| --- | --- | --- | --- |
| Dual connection | Fake Voice and Fake Control independently connect and update | Voice ingress and Control statuses are connected; topology is `dual_session_enforced_control` | `executed_pass` |
| Continuous ingress | Multiple Voice PCM frames, transient ASR delta, one final | final transcript and `TURN_INGRESS_COMMITTED` occur once; no authority action from delta | `executed_pass` |
| Local binding | Control result is bound to local turn, utterance, ASR ref, request, and epoch | mismatched/late binding fails closed | `executed_pass` |
| Snapshot minimization | Control request sees only lifecycle booleans/enums, version, confirmation scope, and safe opaque task ref | no task text, tool result, full journal, credential, or raw context | `executed_pass` |
| FAST | valid `FAST_ONLY` + `FOREGROUND_CHAT` + `ANSWER` + `LOW` + threshold + candidate | one authoritative `FAST_ONLY`, Gate pass, then `FOREGROUND_OUTPUT_COMMITTED`, then bounded Control text becomes visible | `executed_pass` |
| FAST ordering | inspect browser message ordering and counters | assistant QA text count is zero before commit; binary frame count is always zero | `executed_pass` |
| FAST rejection | missing/oversized candidate, local disagreement, unsafe risk, low confidence, stale epoch | candidate discarded; controlled clarify or silence according to directedness; zero spawn/patch/audio | `executed_pass` |
| SPAWN | local Router returns `SPAWN_SLOW_TASK` | exactly one canonical MockSlowTask create; candidate discarded; controlled `ACK_SLOW`; no real Slow LLM | `executed_pass` |
| PATCH | active task and material patch remain current at dispatch | bind local `task_id`, `plan_version`, `task_event_seq`; `USER_PATCH_RECEIVED` and `USER_PATCH_INTERPRETED`; advance version only when material | `executed_pass` |
| PATCH stale state | task/version/confirmation snapshot changes during Control request | task identity change must fail closed; same-task plan change requires explicit re-evaluation | `invalidated_by_slice3a1_reproduction`; an old proposal could be rebound to a replacement active task |
| Confirmation/cancel | active task has ADR-016 pending state | only an explicit, current-scope accept/reject may resolve confirmation | `invalidated_by_slice3a1_reproduction`; pending confirmation was defaulted to accepted |
| IGNORE | local Router returns `IGNORE` / non-assistant | candidate discarded; silence; no task or patch | `executed_pass` |
| AMBIGUOUS | local Router returns `AMBIGUOUS` | candidate discarded; controlled template `CLARIFY` or silence; no task or patch | `executed_pass` |

## Function Call fail-closed matrix

Every row must end in a local terminal `clarify`, `ignore`, or explicitly degraded projection. An assistant-directed non-empty committed transcript may receive only controlled `CLARIFY`; empty, rejected, or non-assistant ingress must `IGNORE`. Every row requires zero SlowTask creates, zero UserPatches, zero Voice assistant text forwarded, and zero playback PCM frames.

| Failure | Required automated injection | Status |
| --- | --- | --- |
| Ordinary assistant text, no Function Call | Fake Control plain-text response | `executed_pass` |
| Wrong function name | Function Call done for a different name | `executed_pass` |
| Malformed JSON | fragmented/done malformed argument string | `executed_pass` |
| Missing field / unknown field | strict schema violation | missing field: `executed_pass`; unknown field: `not_executed` |
| Invalid enum / confidence out of range | strict type/range violation | `executed_pass` |
| Oversized candidate/arguments | configured hard bound exceeded | candidate: `executed_pass`; full argument envelope: `not_executed` |
| Timeout / provider error / disconnect | Fake Control terminal modes | `executed_pass` |
| Correlation mismatch | wrong request/response/item/turn/utterance binding | `executed_pass` |
| Late Function Call | result arrives after turn/epoch generation advances | `executed_pass` |
| Multiple Function Calls | genuinely different second call | `executed_pass` |
| Queue overflow | bounded Control queue overflows | `executed_pass`; dropped request gets an explicit terminal outcome and safe counter |
| Superseded turn | new committed turn cancels old active Control response | `invalidated_by_slice3a1_reproduction`; old fail-closed clarification text remained displayable |
| Context delete failure | Control cleanup cannot be acknowledged | `executed_pass`; Control taints/rebuilds independently and request fails closed |
| Voice cancel without terminal | cancel acknowledgement never reaches matching terminal | `executed_pass`; Voice output stays quarantined and Voice rebuilds |
| Voice delete failure | output item cannot be confirmed deleted | `executed_pass`; Voice rebuilds and browser session survives |
| Voice response after interrupt | old `response.created`/text/audio arrives after fence | `invalidated_by_slice3a1_reproduction`; output eligibility was fenced, but matching terminal cleanup ownership was lost |

## Authority, journal, and replay matrix

| Invariant | Required evidence | Status |
| --- | --- | --- |
| Authoritative journal | Enforced routing appends to the current browser-session journal, not the Shadow evaluator journal | `executed_pass` |
| Commit boundary | authority begins only after final ASR and `TURN_INGRESS_COMMITTED`; ASR delta cannot spawn, patch, confirm, cancel, or route | `executed_pass` |
| One terminal outcome | every committed turn records exactly one terminal dispatch | `invalidated_by_slice3a1_reproduction`; fail-closed plus late valid Control could terminal-dispatch twice |
| One Router decision | no provider path can append a second authority decision for one turn | `invalidated_by_slice3a1_reproduction`; fail-closed plus late valid Control emitted two Router decisions |
| Canonical registry | only existing ADR-002 event names are appended; no `route.enforced.*`, `slowtask.start.signal`, or `patch.signal` canonical events | `executed_pass` |
| Browser metadata isolation | experiment-local projections are not replay reducer inputs | `executed_pass` |
| Provider non-authority | provider hint alone never creates SlowTask/UserPatch or advances plan/lifecycle | `executed_pass` |
| Local disagreement | local Router result owns dispatch even when Qwen hint differs | `executed_pass` |
| Deterministic replay | redacted/minimal journal replays without provider rerun and produces the same state | `executed_pass` |

Canonical event assertions must use the accepted ADR-002 registry names actually exposed by the existing runtime. Tests must not add a new canonical event name merely to make the experiment observable.

## Cancellation, queue, and context matrix

| Invariant | Expected result | Status |
| --- | --- | --- |
| At most one active Control request per turn/session | a new turn actively cancels the old response and advances the generation fence without holding the coordinator lock across network wait | original `executed_pass` claim `invalidated_by_slice3a1_reproduction` |
| At most one provider response per provider session | overlapping `response.create` is prevented or fails closed | `executed_pass` |
| Bounded queues | input, Control, output, and Voice quarantine have hard limits plus metadata-only counters | Control/browser output: `executed_pass`; exhaustive input/Voice-quarantine limit injection: `not_executed` |
| Control cancellation terminal | cancel-sent is distinguished from matching terminal completion | `executed_pass` |
| Independent rebuild | Control cleanup failure rebuilds only Control; Voice cleanup failure rebuilds only Voice | `executed_pass` |
| Rebuild PCM policy | new PCM may be boundedly dropped while Voice rebuilds; old PCM is never replayed | old PCM non-replay: `executed_pass`; new-PCM bounded drop injection: `not_executed` |
| Playback/control generation fence | new speech/interrupt makes old Function Calls and Voice output permanently ineligible | `executed_pass` |

## Feature-flag and three-mode regression matrix

| Invocation | Expected behavior | Status |
| --- | --- | --- |
| `--provider fake --routing enforced` | Slice 1 Fake/enforced behavior remains available | `executed_pass` |
| `--provider qwen` with no `--routing` | defaults to Slice 2 `shadow`; enforced is never implicit | `executed_pass` |
| `--provider qwen --routing shadow --audio-output qwen --shadow-control dual_session` | Slice 2 dual-session Shadow behavior remains available | `executed_pass` |
| `--provider qwen --routing enforced --slow-runtime mock --audio-output none --shadow-control dual_session` | app factory and loopback accept injected Fake dual sessions as `dual_session_enforced_control` | provider-free factory/loopback: `executed_pass`; two-real-provider-session browser startup: `not_executed` |
| Qwen enforced without `--audio-output none` | rejected with a stable safe error | `executed_pass` |
| Qwen enforced without `--slow-runtime mock` | rejected with a stable safe error | `executed_pass` |
| `--provider qwen --routing enforced --audio-output qwen` | rejected as `qwen_enforced_provider_audio_unsupported` or an equally stable safe code | `executed_pass` |
| `--shadow-control single_session` | rejected; single session is not a Slice 3A topology | `executed_pass` |

The enforced page/session projection must label `provider=qwen`, `routing=enforced`, `output=text_only`, `audio_output=none`, `slow_runtime=mock`, `control_topology=dual_session_enforced_control`, `experimental=true`, `qwen_proposal_authority=non_authoritative`, `local_router_authority=authoritative`, and `provider_native_audio_disabled=true`.

## Security and privacy matrix

| Check | Required assertion | Status |
| --- | --- | --- |
| Credential handle | opaque/non-serializable credential object; key/Authorization never reaches browser, timeline, journal, error, or repr | `executed_pass` |
| Raw audio | PCM is transient only; no fixture, trace, replay, log, timeline, or journal persistence | `executed_pass` |
| Raw provider payload | no full inbound/outbound provider event or `session.update` in safe metadata | `executed_pass` |
| Function arguments | full argument JSON is absent from browser/timeline/journal/error | `executed_pass` |
| Transcript | unredacted transcript is absent from metadata projections and error strings | `executed_pass` |
| Candidate | full candidate is absent from timeline/journal/state/replay; transient candidate storage is deleted/discarded after terminal handling | `executed_pass` |
| Voice zero text leak | no Voice assistant delta/done is forwarded to QA or reused as Control candidate | `executed_pass` |
| Voice zero PCM leak | binary playback frame count is zero before and after `FOREGROUND_OUTPUT_COMMITTED` | `executed_pass` |
| Safe counters | cancel/delete/rebuild/timeout/drop/suppression counts contain no content-bearing fields | `executed_pass` |
| Repository artifacts | no raw audio, raw trace, local replay cache, secret, `.env`, or unredacted real-user fixture | automated exclusion/artifact scan: `executed_pass` |

## Automated test commands and result record

Provider-free experiment suite:

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python \
  ./scripts/test tests/experiments/qwen_realtime_fast_slow -q
```

Current pre-hardening baseline result: `234 passed, 13 skipped in 2.33s`. The former `247 passed` record is historical and does not establish the disproven Slice 3A safety claims.

Authoritative control-plane regression:

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python \
  ./scripts/test \
  tests/interaction \
  tests/router \
  tests/runtime/test_mvp63_fast_foreground_gate.py \
  tests/user_patch \
  tests/slowtask -q
```

Current baseline result: `82 passed in 0.32s`.

Repository hygiene:

```bash
git diff --check
git status --short
```

Result: targeted `git diff --check -- tests/experiments/qwen_realtime_fast_slow docs/implementation/qwen-realtime-fast-slow-slice3a-acceptance.md` passed with no output. Full-worktree status remains owned by the main agent because Slice 3A was implemented concurrently across several agents.

Do not replace a status with `executed_pass` unless the exact command, result count, skip reason, environment limitation, and relevant sample count are recorded. A pre-implementation baseline is not Slice 3A acceptance evidence.

## Live Qwen acceptance record

| Check | Status | Observation |
| --- | --- | --- |
| Real Control Function Call smoke | `executed_pass` | latest synthetic/redacted sample used real Qwen Control with Fake Voice ingress; 1 sample passed |
| Real Function Call coverage | `executed_pass` | 1/1 for the latest synthetic/redacted real-Control sample; no broader rate is claimed |
| Real schema-valid coverage | `executed_pass` | 1/1 for the latest synthetic/redacted real-Control sample |
| Qwen/local route, focus, and foreground-act agreement | `executed_observation` | route 0/1; task-focus 1/1; foreground-act 1/1; overall 0/1 |
| Request to first Function Call delta | `executed_observation` | 399.866 ms, n=1 |
| Request to Function Call done | `executed_observation` | 2325.910 ms, n=1 |
| Function Call done to local Router/Gate | `executed_observation` | 62.805 ms, n=1 |
| Local Router/Gate stage | `executed_observation` | 1.544 ms, n=1 |
| Voice and Control both connected | `not_executed` | real Control connected, but Voice was Fake; this is not two real WebSocket sessions |
| Fake Voice suppression-only counters | `executed_pass` | Fake Voice only: cancel=1, assistant text suppressed=3, audio suppressed=3; not real Voice evidence |
| Real microphone continuous upload | `manual_not_executed` | do not infer from a synthetic Control smoke |
| Real ASR final exactly once | `manual_not_executed` | do not infer from fake Voice |
| Real Voice cancel terminal | `not_executed` | Fake Voice cancel=1 does not establish real terminal correlation or semantics |
| Real Voice item delete/rebuild | `not_executed` | Fake Voice suppression counters do not establish real Voice delete/rebuild behavior |
| Real Control delete/rebuild | `executed_pass` | delete=2, rebuild=0, context tainted=false, n=1 |
| Browser assistant text before commit | `executed_pass` | unsafe assistant text count=0 in the synthetic/redacted real-Control smoke |
| Browser binary playback frames | `executed_pass` | binary playback frames=0 for the synthetic/redacted real-Control smoke; real Voice remains unexecuted |
| Disconnect/reconnect freshness | `not_executed` | fresh session/task/conversation/epoch/context refs |
| Browser console errors/warnings | `not_executed` | record counts only |

If no microphone is available, a fixed synthetic/redacted real-Control smoke may use Fake Voice to create a committed turn and then exercise the authoritative Router/Gate/MockSlowTask/UserPatch path. Such a run must still report Voice/ASR/audio as `manual_not_executed` and must not fabricate a provider proposal when the Function Call is absent or invalid.

## Real launch template

Credentials must be loaded only into the backend process; never print the secret file, environment, credential, Authorization header, or raw provider payload.

```bash
/bin/zsh -lc '
  source ~/.voice-agent-secrets/dashscope.env &&
  cd /Users/a123/voice-agent &&
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

Startup status: synthetic/redacted real-Control smoke `executed_pass`; full browser startup with both real Voice and real Control WebSocket sessions `not_executed`.

## Explicit non-claims and Slice 3B gate

- Current experimental Qwen routing may be described as entering an enforced control plane only after provider-free and live-start acceptance passes; final authority still belongs to the local Router.
- A Qwen proposal is never authoritative.
- Slice 3A may release only a Gate-approved text candidate from the Control Function Call.
- Slice 3A does not play provider-native Qwen PCM.
- Slice 3A SlowTask remains mock.
- `qwen + shadow` must continue to run.
- `qwen + enforced + audio-output qwen` must remain rejected.
- Do not attempt or recommend a single-session topology before Slice 3B.

Slice 3A cannot claim documented forced Function Calling unless the official protocol says so, reliable Voice automatic-response suppression unless documented or proven via cancel/terminal/delete/rebuild, real-device microphone/ASR/AEC/truncate behavior, provider-native foreground audio, production privacy/auth, real Slow LLM, external tools, real side effects, production route quality, or accepted architecture beyond the existing ADRs.

Before Slice 3B can consider provider-native foreground audio, it needs an accepted architecture decision and evidence for gate-before-leak audio authorization, response/item correlation, cancellation terminal behavior, late audio fencing, context cleanup/rebuild, physical playback truncate/AEC, bounded buffering, and zero unauthorized text/PCM delivery. Slice 3A provides no basis for merging Voice and Control into one provider session.
