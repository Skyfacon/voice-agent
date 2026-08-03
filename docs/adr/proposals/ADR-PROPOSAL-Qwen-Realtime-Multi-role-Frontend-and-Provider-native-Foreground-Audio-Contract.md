# ADR Proposal: Qwen Realtime Multi-role Frontend and Provider-native Foreground Audio Contract

## Status

proposed

This proposal is intentionally not listed in `stage_b_adr_register.md`. It is not accepted and does not authorize production behavior. Slice 0 and Slice 1 exercise a provider-free fake. Slice 2 adds an isolated real-provider **shadow evaluation** only; its Qwen route proposal is never authoritative and cannot mutate Router, Gate, SlowTask, UserPatch, or canonical playback decisions.

## Context

The repository has an isolated Qwen Realtime audio transport spike and a separate canonical control plane. A future integration needs one provider session to project several logical roles without allowing a provider-native response to bypass turn ingress, Router, Fast Foreground Gate, SlowTask, or the Event Journal.

The immediate experiment is `experiments/qwen_realtime_fast_slow_web/`. It must leave `experiments/qwen_audio_realtime_web/` unchanged, use no real Qwen endpoint, read no provider credential, persist no audio, and introduce no canonical event name.

For Slice 2, the last sentence above remains the Slice 0+1 historical boundary. The same experiment may now call Qwen only through spike-local adapters, with credentials held by an opaque backend handle, metadata-only observability, no persisted provider payload, and the `dual_session_shadow` isolation described below. This does not make the proposal accepted.

## Proposed decision

### One provider session, three logical projections

A Qwen-compatible realtime provider session may expose three logically separate projections:

1. **Duplex projection**: speech start/stop, barge-in candidate, directedness hint, semantic-close hint, and provider cancellation capability. It remains non-authoritative. The Interaction Controller owns ingress commit and truncate policy.
2. **ASR projection**: transcript deltas for local UX and a final transcript/evidence ref for the post-commit chain. Raw audio and raw provider bodies are not journal payloads.
3. **FastInteraction projection**: route hint, task-focus hint, foreground act, risk, confidence, reply candidate, and final fast evidence. It is normalized through the existing Fast Interaction contract.

Provider reuse does not merge role permissions. Each projection has a distinct capability declaration, normalized shape, source metadata, and output mode (`mock`, `real`, `fallback`, or `degraded`).

### Slice 2 experimental topology: dual_session_shadow

Slice 2 intentionally does **not** test the one-connection topology proposed above. One browser WebSocket is backed by two logically and physically independent Qwen Realtime WebSockets:

1. **Voice Session** uses `smart_turn` and `modalities=["audio", "text"]` for live microphone ingress, ASR, assistant captions, response cancellation, and the existing isolated Qwen voice-demo experience.
2. **Shadow Control Session** uses `turn_detection=null`, `modalities=["text"]`, and one internal `propose_turn_disposition` Function Calling schema. It receives a transient final transcript plus a minimized active-task snapshot. It never executes the function as a tool and never writes a `function_call_output` item.

The Voice Session remains operational if the Shadow Control Session times out or disconnects. Shadow output is not allowed to select, cancel, suppress, release, or replace Voice Session text/audio. When `--audio-output qwen` is used for live evaluation, that audio is explicitly the pre-existing Voice Session UX projection, not an ADR-017 gate-authorized fast foreground output. No shadow reply candidate may enter the QA conversation or player. Canonical fast/slow direct provider-audio eligibility remains prohibited until an accepted ADR defines it.

`dual_session_shadow` incurs a second provider connection and one additional inference per accepted final transcript. Passing Slice 2 therefore cannot be used as evidence that the two roles can later share one provider connection safely.

### Ownership

- `RealtimeSessionCoordinator` is the single owner of one browser/provider session lifecycle, its asyncio tasks, bounded queues, cancellation, disconnect cleanup, response correlation, and playback epoch.
- Interaction Controller remains the only owner of turn ingress commit and canonical interrupt/truncate requests.
- Router remains the final owner of `FAST_ONLY`, `SPAWN_SLOW_TASK`, `PATCH_ACTIVE_SLOW_TASK`, and `IGNORE`. Provider route/task-focus values are evidence only.
- SlowTask Runtime remains the owner of task lifecycle, `plan_version`, `task_event_seq`, confirmation, task cancellation, and UserPatch interpretation.
- Fast Foreground Gate remains the deterministic owner of candidate display permission.
- The browser renders server-authorized state. Provider text never directly mutates task, confirmation, route, gate, or UI control-plane state.

### Realtime evidence bundle and correlation

Each accepted provider turn is normalized into a `RealtimeTurnEvidenceBundle` with these bindings:

| identifier | owner | purpose |
| --- | --- | --- |
| `turn_id` | Interaction Controller/runtime | canonical accepted turn |
| `utterance_id` | Interaction Controller/runtime | post-commit ASR/FastInteraction binding |
| `audio_span_id` | Access/Duplex projection | transient microphone span metadata; never audio bytes |
| `provider_item_id` | provider adapter | provider-local input/output item correlation |
| `response_id` | provider adapter/coordinator | candidate quarantine and cancellation correlation |
| `playback_epoch` | coordinator/browser player | generation fence for clear and late-audio rejection |

Provider IDs are opaque metadata. They do not replace canonical IDs and cannot be used to advance SlowTask state.

### Candidate quarantine

Provider assistant text deltas and provider-native PCM enter a bounded, response-scoped `CandidateQuarantine` before Router and Gate finish. Quarantined material is not sent to the QA conversation, browser player, canonical committed-output event, or any user-visible channel.

The quarantine has explicit limits for text characters, text deltas, audio chunks, and audio bytes. Overflow fails closed, clears the response candidate, records only bounded counters/metadata, and reports degraded state. It never persists PCM.

After the final Router decision:

| local route/focus | candidate policy | allowed foreground output |
| --- | --- | --- |
| `FAST_ONLY` + `FOREGROUND_CHAT` | Gate may pass only `ANSWER + LOW risk + sufficient confidence` | released candidate text/audio after `FOREGROUND_OUTPUT_COMMITTED` |
| `SPAWN_SLOW_TASK` | discard provider candidate | controlled `ACK_SLOW` template or later SlowTask output |
| `PATCH_ACTIVE_SLOW_TASK` | discard provider candidate | controlled `ACK_PATCH`/confirmation template; patch enters UserPatch |
| `IGNORE` / `NON_ASSISTANT` | discard provider candidate | silence by default |
| `AMBIGUOUS` | discard provider answer | controlled `CLARIFY` template or silence |

Non-FAST routing also requests provider response cancellation when a response is still active and clears any queued candidate output.

### Provider-native foreground audio

Provider-native audio must not play before final local routing and Fast Foreground Gate approval. Slice 1 buffers complete synthetic PCM and releases it only after an allowed committed foreground output.

Direct playback of Qwen streaming audio while final routing/gating is unresolved is not authorized by this proposal or by Slice 1. Any future gate-before-leak or speculative provider-native playback contract requires this proposal (or a successor ADR) to be accepted with explicit rollback, audible-leak, Talker, playback-commit, and replay semantics.

### Interrupt and tainted provider context

New `speech_started` or an explicit interrupt advances `playback_epoch`, clears the browser player, clears response-scoped output/quarantine, requests provider cancellation, and rejects late old-epoch PCM. The same epoch is a control-plane generation fence: a late proposal from the cancelled response must not reach Router, Gate, SlowTask, or UserPatch, even if `response.created` itself arrived after the interrupt.

If a provider generated content for a response that local routing discarded, that provider context is **tainted**. The adapter must use one of these explicit capabilities:

1. delete the uncommitted provider item/response when supported;
2. rebuild provider context from locally committed conversation items when deletion is unavailable;
3. close and recreate the provider session when neither operation is trustworthy.

Slice 1 fake mode models delete/clear and labels context-rebuild capability as degraded. Slice 2 must not silently keep discarded candidate facts in Qwen context.

For the Slice 2 Shadow Control Session, every request owns its locally generated input item and any returned function-call item. The adapter requests `conversation.item.delete` for those items and waits for `conversation.item.deleted`. Missing confirmation, provider error, timeout, ambiguous item correlation, or partial cleanup marks the context `context_tainted`; the control connection is then closed and rebuilt before another request can be trusted. A late result is discarded by the local request/turn correlation even if the provider later completes it.

The Voice Session and Shadow Control Session never share provider item IDs or conversation history. Voice context is not copied into the control session; only the current final transcript and minimized task-state booleans/enums are transiently injected.

### Canonical Event Journal versus browser metadata timeline

The per-session `InMemoryEventJournal` records accepted ADR-002 canonical events for session startup, ingress, Router decisions, foreground candidate/gate/commit/discard, SlowTask/UserPatch, playback, and interrupt/truncate paths. Replay/state assertions consume that journal and do not rerun the fake/provider.

The accepted ADR text describes `SESSION_ENDED`, but that name is not present in the repository's current canonical event registry. Slice 1 must not invent the name or modify the registry under this proposal. Disconnect therefore performs deterministic resource cleanup but cannot claim a complete canonical session-end replay; resolving that registry/ADR mismatch requires separate governance.

The browser `metadata timeline` is a bounded, redacted, experiment-local observability projection. WebSocket message names such as `route.decided`, `gate.result`, or `playback.clear` are not canonical event names and must never be fed to the canonical replay reducer as if they were journal entries.

## Experiment-local browser WebSocket v2

The same-origin loopback endpoint is `/ws`. JSON controls carry `protocol_version=2`. Browser PCM input is raw little-endian PCM16, 16 kHz, mono, approximately 100 ms per frame. Server PCM output uses the binary envelope `QFS2 || uint32_be(playback_epoch) || PCM16LE_24k_mono`.

Browser to server controls:

- `session.configure`
- `microphone.start`
- binary PCM input
- `microphone.stop`
- `interrupt.request`
- `disconnect`
- `synthetic.turn` (fake-only deterministic QA/test extension)

Server to browser messages:

- `session.ready`
- `state.changed`
- `transcript.user.delta` / `transcript.user.final`
- `transcript.assistant.delta` / `transcript.assistant.done`
- `route.proposed`
- `route.decided`
- `gate.result`
- `slowtask.state`
- `userpatch.accepted`
- `playback.begin`
- binary PCM output
- `playback.clear`
- `playback.end`
- `degraded`
- `safe_error`

All JSON is bounded. Errors are normalized to safe codes. Timeline entries contain only safe IDs, enums, booleans, small counters, and latency values; never PCM, credentials, authorization headers, raw provider payloads, or unredacted real transcripts.

## Capabilities Slice 1 cannot claim

Even if the fake vertical loop passes, it cannot claim:

- ADR-001 target Duplex semantic directedness/semantic-close quality or real pre-ASR rejection; fake policy uses assumed/mock evidence.
- ADR-003 playback-reference AEC, echo discrimination, provider/Talker physical stop guarantees, or real-device truncate SLO validation.
- ADR-017 real Fast Interaction model quality, safe token-stream gate-before-leak, or direct provider-native streaming audio approval.
- Real Qwen adapter correctness, latency, cancellation/context deletion semantics, production privacy/authentication, or external side effects.

## Validation for the proposal experiment

Slice 1 must provide provider-free tests for the four Router decisions plus controlled clarification, gate pass/reject/discard, single active MockSlowTask, UserPatch and plan-version binding, confirmation-as-patch, response cancel, epoch clear/late drop, bounded queues, disconnect/error normalization, output-mode labeling, and deterministic canonical journal/state assertions.

## Follow-up required for Slice 2

Before real Qwen shadow routing, confirm provider capability/protocol facts and update this proposed ADR with:

- exact item/response delete or context rebuild behavior;
- shadow-only routing that cannot affect Router/Gate/user-visible output;
- real capability snapshot and adapter method separation for Duplex/ASR/FastInteraction;
- provider cancellation and late-event semantics;
- metadata-only live trace/redaction policy;
- criteria for accepting or rejecting direct provider-native foreground audio.

## Slice 2 official capability check (2026-07-21)

The Alibaba Cloud Qwen-Audio Realtime user guide and client/server event references were rechecked on 2026-07-21. They document:

- model `qwen-audio-3.0-realtime-plus` at the Beijing workspace endpoint `wss://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime?model=qwen-audio-3.0-realtime-plus`;
- `session.update`, `modalities=["text"]`, `modalities=["audio", "text"]`, `smart_turn`, and manual `turn_detection=null`;
- `conversation.item.create`, `conversation.item.delete`, and `conversation.item.deleted` confirmation;
- `response.create`, one-response-at-a-time restrictions, `response.cancel`, and terminal `response.done` statuses;
- Function Calling tools schema plus `response.function_call_arguments.delta` and `.done`;
- streaming ASR delta and final/completed events.

The checked official pages do not document a `tool_choice` or another protocol-level guarantee that forces a particular Function Call. Slice 2 therefore declares `forced_route_function_call=unsupported_or_unverified`. Prompt-only compliance is not a capability: ordinary assistant text, a missing call, a wrong function name, malformed JSON, invalid schema, or timeout produces a degraded/not-available shadow result and never a fabricated proposal.

## Slice 3A experimental topology: dual_session_enforced_control

Slice 3A adds an explicitly selected, experiment-only topology:

```text
--provider qwen --routing enforced --slow-runtime mock
--audio-output none --shadow-control dual_session
```

The topology name is `dual_session_enforced_control`. It is not a single
provider session and does not authorize provider-native foreground audio. One
Qwen Voice ingress connection remains responsible for continuous PCM upload,
speech start/stop, final ASR, and provider cancellation. A physically separate
text-only Control connection returns one strictly validated
`propose_turn_disposition` Function Call per locally committed final transcript.

The Control Function Call is provider evidence, not a `RouterDecision`. The
coordinator adds locally owned `turn_id`, `utterance_id`, ASR-event binding and
playback/control epoch, normalizes the validated frame as Fast Interaction
evidence on the browser session's authoritative journal, runs the existing
deterministic Router against the latest authoritative task snapshot, and then
runs the existing Fast Foreground Gate. Provider-supplied task identifiers or
plan versions are neither accepted nor used.

The only candidate eligible for `FAST_ONLY` is the bounded
`reply_candidate_text` from the same validated Control Function Call that
provided route, task-focus, foreground-act, risk and confidence. It is retained
only in bounded transient memory and represented in the journal by a safe ref.
It may enter browser QA only after `FOREGROUND_ACT_GATE_PASSED` and
`FOREGROUND_OUTPUT_COMMITTED`. Slice 3A never releases a Voice Session answer or
PCM as that candidate.

Local dispatch remains authoritative:

- `FAST_ONLY + FOREGROUND_CHAT + ANSWER + LOW + sufficient confidence` may
  display the Control text candidate after Gate commit.
- `SPAWN_SLOW_TASK` discards any candidate and invokes only the existing
  `MockSlowTaskRuntime` canonical create chain; a controlled text-only
  `ACK_SLOW` may be committed.
- `PATCH_ACTIVE_SLOW_TASK` discards any candidate, re-reads the current active
  task, binds `task_id`, `plan_version`, and `task_event_seq`, and uses the
  existing UserPatch evidence/SlowTask interpretation path. Only a material
  interpretation advances `plan_version`; a controlled text-only `ACK_PATCH`
  may be committed.
- `IGNORE` / `NON_ASSISTANT` discards the candidate and is silent.
- ambiguous or degraded input discards the candidate and permits only a
  controlled template clarification or silence. It creates no task or patch.

Every committed turn must finish with either a local Router/Gate/dispatch
outcome or an explicit fail-closed clarify/ignore/degraded outcome. Queue drops,
supersession, timeouts and late results are fenced by the locally owned turn and
epoch and must be exposed as bounded metadata rather than disappearing.

### Slice 3A Voice auto-output suppression and cleanup

The official protocol was rechecked on **2026-07-22** using the Qwen-Audio
Realtime user guide, WebSocket API, client-event reference and server-event
reference. The documented model remains `qwen-audio-3.0-realtime-plus`; the
Beijing workspace endpoint remains
`wss://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime?model=qwen-audio-3.0-realtime-plus`.
The pages document `modalities=["text"]` or `["audio","text"]`, `smart_turn`,
`server_vad`, manual `turn_detection=null`, item create/delete/deleted,
response create/cancel/done, Function Calling argument delta/done, and one
active response at a time.

They do **not** document a `create_response=false` field or another setting that
retains continuous smart-turn speech detection/ASR while suppressing automatic
response creation. Slice 3A must not invent or send such a parameter. The pages
also still do not document `tool_choice` or another forced-Function-Call
guarantee, so `forced_route_function_call=unsupported_or_unverified` remains
mandatory.

For `qwen + enforced`, every Voice assistant response is therefore treated as
prohibited output in a bounded response-scoped quarantine:

1. `response.created` is correlated to the current local turn/epoch and
   cancellation is requested as soon as possible.
2. Assistant transcript and PCM are counted and discarded inside the backend;
   they are never sent to QA, the player, a Fast Interaction candidate, or a
   canonical committed-output event.
3. Cancellation is not considered complete until the matching
   `response.done` terminal status is observed.
4. Every uncommitted provider output item is deleted and requires a matching
   `conversation.item.deleted` acknowledgement.
5. Missing terminal correlation, item correlation, delete acknowledgement,
   timeout, overflow, terminal provider error, or input-correlation failure
   taints only the Voice context. The Voice connection is rebuilt from locally
   committed metadata/context before it can be trusted again; old microphone
   PCM is never replayed. A non-terminal provider error before canonical final
   ASR is cleanup evidence only: it neither taints Voice nor owns a Control
   terminal.

If the real provider adapter cannot prove response/item correlation and cleanup,
real `qwen + enforced` startup must remain unsupported. Provider-free Fake
enforced automation may still validate the local control plane, but cannot be
reported as real zero-leak evidence.

Before `FOREGROUND_OUTPUT_COMMITTED`, browser-visible assistant text deltas and
binary PCM frames must both remain zero. In all Slice 3A paths, binary provider
PCM output remains zero even after a text candidate is committed.

### Slice 3A Function Call fail-closed policy

Ordinary assistant text, no Function Call, a wrong function name, malformed
JSON, schema-invalid or missing fields, invalid enums, confidence outside
`[0,1]`, an oversized candidate, timeout, provider error, correlation mismatch,
multiple calls, late output, queue overflow or tainted context never becomes a
Qwen proposal and never reaches SlowTask/UserPatch ownership. For a non-empty,
assistant-directed committed transcript the authoritative fallback is a
controlled clarification; empty, rejected or non-assistant input is ignored.
The fallback creates zero SlowTasks, zero UserPatches and zero playback frames.

### Slice 3A capability and Slice 3B preconditions

Slice 3A must declare `output=text_only`, `audio_output=none`,
`slow_runtime=mock`, `route_proposal_authority=non_authoritative_provider_evidence`,
and `local_router_authority=authoritative`. The proposal remains `proposed`; the
accepted ADR register and canonical event registry are unchanged.

Provider-native foreground audio is deferred to Slice 3B. Before that slice,
the project needs an accepted contract for gate-before-audible-leak, Talker and
playback-commit ownership, provider response/item rollback after local discard,
cancel terminal proof, replayable audio selection, physical truncate/AEC
semantics, and recovery when a provider has already generated or emitted audio.
Single-session Voice+Control integration is not recommended before those
questions are closed.

## Slice 3A.1 safety-hardening amendment (2026-07-22)

This amendment remains **proposed** and changes no accepted ADR or canonical
event registry.  It narrows the experimental enforced-control contract after
concurrency, confirmation, Voice-cleanup and input-correlation defects were
reproduced in Slice 3A.

### One terminal owner and supersession

For each locally committed Voice turn, the coordinator performs a serialized
compare-and-claim before any authoritative Router/Gate/fail-closed chain.  The
first Control success, Control failure/timeout, or Voice failure owns the
turn's sole terminal dispatch.  Later results are metadata-only late discards:
they cannot append another Router decision, enter Gate, create a SlowTask,
construct a UserPatch, or display text/audio.

Terminal bookkeeping and display eligibility are separate.  A superseded turn
may record the existing canonical `ADAPTER_OUTPUT_DEGRADED` event and one
metadata terminal result, but after a newer committed turn begins it cannot
produce a local clarification.  No new canonical event name is introduced.

The request envelope binds a safe local task identity reference, task presence,
plan version, pending confirmation identifier/scope, turn/ASR and playback
epoch.  Active-task identity or confirmation-binding changes fail closed.  A
plan change on the same task is explicitly labelled as re-evaluated current
state and cannot silently authorize an old confirmation.

### Explicit confirmation evidence, local authority

`propose_turn_disposition` has an additive, strictly validated
`confirmation_signal_hint` enum:

```text
ACCEPT | REJECT | AMBIGUOUS | NOT_APPLICABLE
```

The experiment retains schema version `v1` for compatibility with stored
provider-free fixtures: an absent field normalizes to `NOT_APPLICABLE`.
Unknown values and unknown fields still fail schema validation.  This is a
narrow additive compatibility rule, not a default acceptance rule.

The hint is non-authoritative provider evidence.  Only `ACCEPT` or `REJECT`
with exact current turn/ASR/request/epoch, local Router focus, task identity,
pending confirmation id/scope and plan-version binding may enter the existing
UserPatch and SlowTask interpretation path.  SlowTask Runtime remains the sole
owner of `CONFIRMATION_ACCEPTED`, `CONFIRMATION_REJECTED` and cancellation.
`AMBIGUOUS`, `NOT_APPLICABLE`, an ordinary patch, low confidence, high
uncertainty, degraded schema, or provider failure preserves the pending
confirmation.  `NON_ASSISTANT`/`IGNORE` is silent; assistant-directed ambiguity
may use a controlled local clarification.  Raw transcript matching is never a
confirmation authority.

### Provider input-item correlation

The Voice adapter retains provider-supplied input item identifiers only in
private transient memory and projects safe opaque `provider_item_id`,
`turn_ref`, `utterance_ref`, `audio_span_ref`, and `session_ref` bindings.  A
real enforced transcript final is eligible for local ASR projection only when
all opaque refs match the currently open local turn and session generation,
the provider item was observed at speech start/stop, and no final was already
accepted.  Missing, duplicate, old, reordered, interrupted, reconnected or
mismatched items fail closed and cannot start an authoritative Control request.

The official server-event reference checked on **2026-07-22** documents an
`item_id` on speech-started, speech-stopped, ASR-delta and ASR-completed events.
The adapter does not infer this binding from event arrival order when the field
is absent.

### Voice output lifecycle and cleanup

Playback/output eligibility is separate from provider cleanup ownership.
Interrupt permanently fences old Voice output, but retains a response-id
lifecycle until a matching terminal and confirmed item deletion, or a bounded
cancel-terminal timeout followed by a Voice-only rebuild.  Only
`response.done.status=cancelled` is successful cancellation.  `completed`,
`failed`, unknown, missing or mismatched terminals remain prohibited output,
taint Voice, and require cleanup/rebuild; they never become a success count.

Provider cancel/terminal/delete/rebuild waits run outside the coordinator's
serialized mutation lock.  Returning work re-enters the lock and checks its
generation before updating current state.  Watchdog tasks are session-owned
and cancelled at close.  A rebuild discards bounded in-flight PCM and never
replays microphone audio; browser and Control lifecycles remain independent.

The official client/server references checked on **2026-07-22** document
response ids, response output-item ids, terminal `completed`/`cancelled`/
`failed` states, `response.cancel`, `conversation.item.delete`, and
`conversation.item.deleted`.  They document cancellation as producing a
cancelled terminal, but do not establish an ordering guarantee that makes
post-cancel output safe to display.  The enforced adapter therefore continues
to quarantine all Voice output and requires explicit terminal/delete evidence.

### Capability and health truthfulness

Protocol declaration, implementation support, provider-free verification and
real-live verification remain distinct fields.  A profile whose health or
verification is `not_executed` is not reported as ready/ok by `/healthz`.
Cancel, item-delete and rebuild support are not `executed_pass` until a real
live run proves them.  Forced Function Call and automatic smart-turn response
suppression remain `unsupported_or_unverified`; neither is inferred from a
prompt.

## Slice 3A.1.1 phase, Gate-context, and long-session amendment (2026-07-22)

This amendment remains **proposed**. It changes neither the accepted ADR
register nor the ADR-002 canonical event registry.

An enforced turn has one in-memory phase authority record attached to the turn,
covering terminal claim, FastInteraction emission, Router emission, Gate
terminal, SlowTask/UserPatch mutation start and completion, and browser dispatch
attempt. Exception recovery rehydrates already-appended phases from the
per-session journal. Before Router, one fail-closed Router/Gate chain may be
completed. After Router, that decision is immutable for the turn: recovery may
append at most one missing Gate/output terminal but may not rerun Router, repeat
task mutation, advance a plan twice, or retry an already-attempted browser
terminal. Browser and timeline sink failures are degraded delivery metadata,
not a new authority path.

The shared Fast Foreground Gate accepts a typed immutable context with the
minimum current interaction, task-focus, SlowTask lifecycle, pending
confirmation, capability health/output/verification, schema, transient local
candidate-policy, and configured-threshold fields. Only normalized empty risk
tags or exactly `["none"]` are low-risk eligible. Every non-none tag or
class/tag conflict fails closed. Pending confirmation and task-changing focus
classes block an ordinary foreground ANSWER. Candidate text is evaluated only
in transient memory and is never persisted by the Gate.

An explicit confirmation hint is valid only when bound to the current pending
confirmation id/scope, task identity, `plan_version`, `task_event_seq`, turn,
request, ASR evidence, playback epoch, confidence, and uncertainty. Orphan
accept/reject signals fail closed and cannot become an ordinary patch.

Coordinator correlation maps are active-record stores, not history. Terminal
response/input/turn identities move into bounded tombstones; active and pending
records are never evicted to satisfy a bound. Invalid Voice response creation
taints Voice and schedules one coalesced, bounded, Voice-only rebuild outside
the serialized mutation lock. New PCM may be boundedly dropped during rebuild
but is never replayed. Rebuild failure leaves Voice degraded while Control and
browser lifecycles remain independent.

The Qwen Audio Realtime documentation rechecked on 2026-07-22 documents
continuous `input_audio_buffer.append`, WebSocket close/error behavior,
response correlation, cancel and terminal states, but no business-idle timeout
event or server heartbeat guarantee. Receive idle is therefore non-terminal.
Transport heartbeat and close detection are implementation liveness mechanisms,
not claimed provider guarantees. Protocol-level forced tool choice remains
`unsupported_or_unverified` for this Qwen Audio Realtime control path.

## Slice 3A.1.2 safety, authority, replay and Voice-lifecycle amendment (2026-07-22)

This amendment remains **proposed**. It changes neither the accepted ADR
register nor the ADR-002 canonical event registry. Independent dynamic review
invalidated the Slice 3A.1.1 `executed_pass`; this amendment narrows the
provider-free qualification boundary before any Slice 3A.2 turn-level live
qualification.

### Candidate policy and live Gate authority

Arbitrary provider-generated reply text is quarantined by provenance. Provider
`risk_class`, `risk_tags`, confidence and schema validity are evidence fields,
not a safety attestation, and no keyword allow/deny list can promote the text.
The Gate consumes an immutable local `CandidatePolicyDecision` containing a
policy version, decision, reason code and provenance. Only explicitly trusted
synthetic fixtures or server-owned deterministic template refs may use an
allow decision in this slice; provider provenance cannot construct one.

Live Gate callers bind interaction state and task focus from canonical journal
events, active SlowTask identity/lifecycle and confirmation state from current
local authority, and output mode from the recorded capability snapshot.
Missing or inconsistent authority fails closed. Synthetic eval context is
explicitly labelled and cannot be reused as live provider authority.

### User-visible delivery and mutation reconciliation

Each enforced turn records delivery state before its first potentially visible
browser send: not-started, attempted/started, terminal, or ambiguous. Response
identity, semantic response kind and commit ref remain stable. Once any send
may have been accepted, recovery emits metadata only and cannot create a second
semantic fallback. Router, Gate, dispatch and task mutation remain at most once.

The append-only Event Journal is authoritative for SlowTask/UserPatch mutation.
Spawn enters `PLANNING` through canonical events. After any partial append or
interpretation failure, coordinator state is reconstructed with the existing
SlowTask reducer; an already-partial mutation is not blindly retried and is not
reported as a successful dispatch. No-candidate slow routes create a real
server-owned local candidate where the existing Gate contract requires a
candidate reference; no fake identifier, new event name or replay-validator
relaxation is used.

### Voice generations and bounded correlation

Every accepted PCM frame carries both coordinator and provider ingress
generation. Rebuild fences the generation before its first await, drains queued
old frames, and rechecks generation before provider send. Old PCM is dropped
and never replayed to a replacement core. Provider events also carry a local
generation and are rechecked before state mutation; stale terminal, ASR and
audio events are discarded without entering Router, QA or playback.

A terminal receiver has one lifecycle owner. It stops polling the dead core,
awaits one coalesced Voice-only rebuild and resumes only against the new
generation. Recovery is scheduled before best-effort browser metadata, and
background task exceptions are always retrieved. Provider input/response IDs
are remembered for the whole physical generation; duplicate/reused IDs fail
closed and reaching the bounded horizon taints Voice and requires rotation
rather than evicting an ID that could later rebind.

### Qualification boundary

`real_live_verified` remains `false`; connection, health, schema success or a
Function Call cannot promote it. Provider-native audio, real SlowTask, real
tools/external side effects and single-session Voice+Control remain outside the
slice. Slice 3A.2 may start only after this provider-free closure passes its
full regression, and should retain dual session plus `audio_output=none`.

## Slice 3A.1.3 generation-fenced authority and journal/replay closure amendment (2026-07-24)

This amendment supersedes the Slice 3A.1.2 qualification verdict after
independent dynamic review. The proposal remains `proposed`; this amendment
does not change the accepted ADR register and does not authorize provider
network access, provider-native audio, real tools, or external side effects.

### Immutable Voice authority

Every enforced Voice callback captures an immutable authority token before
dispatch. The token binds provider generation, coordinator rebuild generation,
and provider session ref. Authority is rechecked after an awaited boundary and
before any journal, Router, Gate, SlowTask, UserPatch, QA, playback, or control
mutation. A retired generation is a content-free discard with a bounded safe
counter. Missing/empty session ref fails closed, and the adapter freezes the
generation's non-empty session ref before provider receive so concurrent close
cannot erase stale-event identity. A blocked user-transcript browser projection
is cancellable when its generation retires; it cannot become a route or QA
input afterward.

Voice correlation sets remain bounded without eviction-and-rebind. The 64th
input/provider identifier is permitted; the 65th taints the current Voice
generation and schedules one coalesced Voice-only rebuild before browser
metadata. The same rule applies to the response horizon. Queued retired PCM is
drained and never replayed, while the replacement generation must accept fresh
input.

### Foreground truthfulness and templates

One versioned local template catalog owns every deterministic fallback's exact
route, basis, ref, policy ref, foreground act, and text. Forged or cross-route
refs fail closed. Provider candidates remain quarantined regardless of claimed
risk or confidence. Missing, quarantined, risky, or otherwise unauthorized
FAST output commits `template_clarify`, never an ACK.

`ACK_SLOW` and `ACK_PATCH` are postconditions, not preambles. Their
`template_ack` commitment may be appended only after the corresponding
canonical SPAWN or PATCH mutation completes. Failed or partially reconciled
mutation cannot produce a success ACK. Candidate, Gate, commit, browser
delivery, output basis/ref, foreground act, and mutation outcome must agree.
An ambiguous browser delivery retains one semantic response identity; recovery
is metadata-only.

### Current Gate authority and replay cardinality

Live Gate context is derived from the current reducer/interaction state for the
target turn and Router refs, not the historical existence of
`TURN_INGRESS_COMMITTED`. Interrupting, waiting, terminal, unknown, stale task,
stale confirmation, stale `plan_version`, or stale `task_event_seq` fails
closed. Caller-supplied candidate/Fast/Router mappings must exactly match their
canonical journal events. A caller active-task snapshot without canonical
SlowTask journal history cannot authorize PATCH; legal PATCH uses the
reducer-derived current task/plan/sequence authority.

Every `FAST_ONLY` outcome has a terminal Gate and foreground commitment even
when candidate evidence is missing; no direct-answer fallback may bypass the
Gate. Deterministic replay rejects more than one Router, terminal Gate,
foreground commit, SPAWN initiation, or PATCH/UserPatch initiation for the
same `(turn_id, utterance_id)`. The state digest includes stable Router/Gate/
commit identities, output basis, and output ref without raw text or provider
reruns.

### Qualification boundary

Slice 3A.1.2 is historical evidence only. Slice 3A.2 remains blocked until the
Slice 3A.1.3 acceptance record proves the generation race, both 65th-item
horizons, no-rebuild-storm behavior, post-mutation ACK ordering, partial
mutation clarification, current-state Gate rejection, forged-template
rejection, missing-candidate Gate closure, duplicate-chain replay rejection,
stable digest, provider-free regressions, full project tests, artifact scans,
and independent P0/P1 review.

## Slice 3A.2 stale-cleanup closure and bounded live amendment (2026-07-24)

This proposal remains `proposed`. This amendment changes neither the accepted
ADR register nor the canonical event registry and does not authorize
provider-native audio, real SlowTask, real tools, external side effects, or a
single-session topology.

A later independent review found that Voice cleanup could cross a provider
await and then mutate the replacement generation. The adapter now binds
cleanup to immutable core identity, provider generation, session ref, and
response lifecycle identity, and rechecks all four before any success/failure
counter, taint, lifecycle, correlation-map, or stale-ID mutation. The
coordinator separately rechecks the exact lifecycle and its immutable
provider/coordinator/session authority, plus current provider taint, before
scheduling a rebuild. It holds no state lock across provider I/O. Stale
completion is a content-free no-op; current-generation failure remains
fail-closed and concurrent failures coalesce into one Voice-only rebuild.

The provider-free and full-project regressions passed. Bounded real
qualification reached real text-only Control, physically separate connected
Voice and Control sessions, Chrome microphone capture permission, zero binary
playback, Voice idle-timeout rebuild recovery, and clean disconnect/reconnect.
No actual speech was present: input level remained 0%, so no real ASR final,
route matrix, Voice cancel terminal, or Voice item-delete claim is made.
Overall status is `executed_partial`, `real_live_verified=false`, and
Slice 3B-MVP admission is `NO_GO` until a human-present spoken-turn run covers
the required routes and lifecycle acknowledgements. Continue dual session with
Local Router authority, `audio_output=none`, candidate/PCM quarantine, mock
SlowTask, and reconnect-on-untrusted-taint. Do not merge Voice and Control into
one provider session.

## Slice 3A.2.1 committed-turn authority and Voice recovery amendment (2026-07-24)

This proposal remains `proposed`. This amendment changes neither the accepted
ADR register nor the ADR-002 canonical event registry. It does not authorize
provider-native playback, a single provider session, real SlowTask/Slow LLM,
real tools, or external side effects.

### Authority transfer at canonical final ASR

Provider-generation authority remains mandatory through validation and append
of `ASR_TRANSCRIPT_OUTPUT_EMITTED`. The synchronous canonical append transfers
the turn to an immutable local committed authority that binds session,
conversation, turn, utterance, final-ASR event/ref, and playback epoch. After
that boundary, a cleanup-only Voice generation rebuild cannot revoke or rebind
the already committed Control request.

The local authority is still retired by new speech, a newer committed turn,
explicit interrupt, playback-epoch change, disconnect, browser close, or any
turn/utterance/ASR correlation mismatch. Superseded, queue-dropped, and late
Control work is metadata-only evidence: it cannot append an old Router/Gate
chain, mutate SlowTask/UserPatch, produce a semantic reply, or bind to the
newer turn. Provider events blocked before the canonical final-ASR append
remain governed by the Voice generation token and are discarded when retired.

### Bounded cancel outcomes and ingress recovery

Voice cancel terminal state is exposed only as one of five bounded outcomes:
`cancelled_on_time`, `cancelled_after_watchdog`,
`completed_after_cancel`, `failed_after_cancel`, or `missing_terminal`.
Completed, failed, late-cancelled, or missing terminal remains fail-closed and
taints/rebuilds Voice; confirmed deletion does not promote an unsafe cancel to
success.

Microphone ingress exposes typed availability and failure codes. Frames
observed during rebuild, taint, disconnect, or retired/stale generation are
dropped immediately, counted, and never replayed. One recovery episode
produces one bounded non-error degradation notice. A real provider send
exception is normalized to `voice_send_failed`, taints the current generation
once, emits at most one safe error for that generation, and schedules one
coalesced Voice-only rebuild. Control remains physically separate and its
committed local authority is not advanced or revoked by that repair.

### Error ownership, receiver handoff, and browser projection

A non-terminal `provider.error` observed before canonical final ASR is not
sufficient to claim the turn's one Control terminal. It leaves the Voice
adapter connected and untainted so a later valid final ASR can still transfer
authority. After final ASR, the current turn may fail closed exactly once on
that error. A terminal provider error instead retires and taints the physical
Voice generation in the adapter before the coordinator schedules its rebuild.
An invalid provider input correlation does the same; coordinator-local taint
alone is not sufficient rebuild authority.

The single receiver owner parks on the exact in-flight Voice rebuild while the
replacement generation connects, then resumes only against that generation.
Recovery-critical browser projections are best effort and bounded to 250 ms so
a stalled browser sink cannot hold the mutation lock, kill the receiver owner,
or prevent PCM fencing and generation advance. Browser projection failure has
no authority to create another Router/Gate terminal, SlowTask/UserPatch
mutation, or semantic delivery.

Only bounded outcome enums, counters, opaque local refs, and output modes may
enter control state or timeline metadata. Raw PCM, transcripts, provider
payloads, candidates, Function Call arguments, response/item IDs, credentials,
and authorization headers remain prohibited.
