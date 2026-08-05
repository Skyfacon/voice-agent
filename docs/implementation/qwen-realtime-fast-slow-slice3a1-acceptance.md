# Qwen Realtime Fast/Slow Slice 3A.1 Acceptance

Date: 2026-07-22 (+0800)

> Superseded safety verdict: the Slice 3A.1.1 `executed_pass` recorded below
> was invalidated by independent dynamic review. Its historical commands and
> observations remain preserved, but it must not be used as current admission
> evidence. The blocking findings and provider-free closure are recorded in
> [qwen-realtime-fast-slow-slice3a12-acceptance.md](qwen-realtime-fast-slow-slice3a12-acceptance.md).

Status: the original Slice 3A.1 `executed_pass` is historical and was invalidated by the Slice 3A.1.1 reproductions below. Slice 3A.1.1 provider-free closure is now `executed_pass`: the final local-loopback experiment suite completed with `387 passed in 16.19s`, the final full repository suite completed with `2050 passed in 22.07s`, and the authoritative control-plane regression completed with `96 passed in 0.36s`. The sandbox-only Qwen slice run completed with `286 passed, 13 skipped in 8.41s`; all 13 skips are only loopback-port tests, and the approved loopback run above proves the same server tests without skips. Real microphone, ASR, cancel terminal, delete/rebuild, confirmation, reconnect, and live per-turn latency remain `not_executed`. The earlier one-sample credential-safe startup is unchanged historical evidence and did not commit a turn. This does not authorize Slice 3B audio.

The current routing mode is an experimental enforced control plane. The deterministic local Router remains authoritative, the Fast Foreground Gate remains the only foreground commit authority, and a Qwen proposal remains non-authoritative provider evidence. SlowTask is still mock, provider-native Qwen PCM remains disabled, and this slice does not implement Slice 3B audio. The associated ADR remains proposed; `stage_b_adr_register.md` was not changed.

## Slice 3A.1.1 closure amendment

The previous passing suite did not cover five newly reproduced safety gaps, so its broad safety claim is invalidated rather than carried forward:

| Reproduction before fix | Observation | Closure evidence |
| --- | --- | --- |
| Browser delivery failure after Router append | one turn produced `router_count=2` | phase-aware authority recovery produces exactly one Router and at most one Gate/output chain |
| `risk_class=LOW`, `risk_tags=["payment"]` | Gate passed and `CONTROL-CANDIDATE-SENTINEL` became visible | core Gate fails with `risk_signal_conflict`; candidate remains invisible |
| `ACCEPT` without a current pending confirmation | `plan_version` advanced `1 -> 2` and one `USER_PATCH_RECEIVED` was emitted | `control_confirmation_orphan`; plan stays at 1 and UserPatch count stays zero |
| Pre-closure loopback run | `372 passed, 1 failed`; health test incorrectly expected `output_mode=real` before connect | expectation corrected to truthful `not_executed`; final loopback run is `387 passed` |
| Short-session-only lifecycle coverage | active correlation dictionaries and terminal fences could grow without a proved bound | 300-turn end-to-end stress proves bounded active maps/tombstones and no stale rebinding |

Each committed enforced turn now owns an explicit in-memory phase record attached to its turn context. It records claim, FastInteraction emission, Router emission, Gate terminal, mutation start/completion, and browser dispatch attempt. Recovery scans the append-only journal after an exception and completes only a missing phase. Once Router exists it is reused; fail-closed handling cannot run Router, SlowTask creation, UserPatch, plan advance, or terminal browser dispatch twice. Browser/timeline failures after the dispatch attempt are degraded delivery metadata only.

The core Fast Foreground Gate consumes an immutable `FastForegroundGateContext`: interaction state, Router task focus, active SlowTask lifecycle, pending confirmation, capability health/output/verification, schema state, transient local candidate-policy result, and confidence threshold. Only empty normalized risk tags or exactly `["none"]` are eligible. Every other tag, multi-tag non-none signal, class/tag conflict, pending confirmation, task-patch/new-task/cancel focus, degraded capability, invalid schema, or unverified local candidate fails closed with a bounded safe code. Candidate content is checked only in transient memory and is not added to Gate metadata.

An explicit confirmation signal additionally binds current task identity, pending confirmation id/scope, `plan_version`, `task_event_seq`, turn/request/ASR correlation, epoch, confidence, and uncertainty. `ACCEPT` or `REJECT` without a current pending confirmation is an orphan signal and cannot become an ordinary task patch. `AMBIGUOUS` and `NOT_APPLICABLE` preserve a pending confirmation and use silence or controlled clarification without task mutation.

Voice response, input-item, and enforced-terminal active records are retired at terminal cleanup into bounded tombstones. Active/pending records are never capacity-evicted. Invalid `response.created` taints Voice and schedules one bounded Voice-only rebuild outside the coordinator lock; concurrent triggers coalesce, new PCM is boundedly dropped without replay, success resumes Voice, and failure remains degraded while Control and the browser session remain alive.

## Accepted boundary

- Required mode remains `provider=qwen`, `routing=enforced`, `slow_runtime=mock`, `audio_output=none`, `shadow_control=dual_session`.
- `qwen + enforced + audio-output qwen` remains rejected.
- Voice output is quarantine-only. Voice text and PCM are never a Control candidate, QA output, or playback source.
- There is no real Slow LLM, tool execution, external write, or side effect.
- Only existing ADR-002 canonical event names are used. Experiment timeline labels remain metadata-only and are not replay reducer inputs.

## Official protocol recheck

The Aliyun Qwen Audio Realtime user guide, WebSocket API, client-event reference, and server-event reference were rechecked on 2026-07-22.

- Current model: `qwen-audio-3.0-realtime-plus`.
- Current Beijing workspace endpoint: `wss://<workspace>.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime?model=qwen-audio-3.0-realtime-plus`.
- The documentation describes speech/ASR item IDs, response IDs, output item IDs, `response.done` statuses (`completed`, `cancelled`, `failed`), cancel leading to a cancelled terminal, delete/deleted acknowledgement, and one active response per connection.
- No documented automatic-response suppression switch was found.
- No documented forced `tool_choice` guarantee was found.
- No documented business-idle timeout event or server heartbeat contract was found. Ordinary receive idle is therefore non-terminal; transport heartbeat/close detection is used only as WebSocket liveness, and that heartbeat interval is an implementation choice rather than a provider guarantee.
- No post-cancel event-order guarantee sufficient to skip quarantine, terminal matching, deletion, or rebuild was found.

Accordingly, `forced_route_function_call` remains `unsupported_or_unverified`, automatic suppression remains unsupported, and every missing/unknown/mismatched item binding fails closed.

## Disproved pre-hardening claims

The pre-hardening baseline was `234 passed, 13 skipped in 2.33s`, plus `82 passed in 0.32s` for the control-plane regression. Those passing tests did not establish the following claims:

| Reproduction | Pre-fix observation | Slice 3A.1 disposition |
| --- | --- | --- |
| Voice failure while valid Control remained in flight | `router_before=1`, `router_after=2`, `slowtask_created=1` | fixed and regression-covered |
| Pending confirmation followed by non-assistant/ignore | emitted `CONFIRMATION_ACCEPTED` and `SLOWTASK_CANCELLED` | fixed; only explicit bound accept/reject resolves confirmation |
| Interrupt followed by matching old `response.done` | `voice_context_delete_count=0`, `voice_context_rebuild_count=0`, late discard only | fixed; output eligibility and cleanup ownership are separate |
| Candidate-absent SPAWN/PATCH | template commit was mistaken for candidate pass and an assertion killed the worker | fixed; local ACK template and candidate pass are distinct |
| Rapid turn supersession | stale queue-drop/late turns displayed clarification | fixed; terminal bookkeeping is separate from display eligibility |
| In-flight proposal after task replacement | old proposal could patch the replacement task | fixed with task-identity and confirmation fences |

The Slice 3A acceptance document now marks these former `executed_pass` statements as invalidated rather than preserving disproven claims.

## Safety invariants and regression evidence

### Terminal uniqueness and worker reliability

- `_claim_enforced_terminal` is called while the coordinator mutation lock is held. Success, degradation, timeout, Voice failure, supersession, and late result paths share the same per-turn terminal fence.
- An already-terminal result increments metadata-only late-discard evidence and cannot enter FastInteraction, Router, Gate, SlowTask, UserPatch, or visible output.
- `dispatch.result` carries the local turn identity, allowing the tests to assert exactly one terminal dispatch per committed turn.
- Each Control envelope has exception normalization plus `task_done()` in `finally`; one handler exception cannot terminate the worker or strand `queue.join()`.
- Candidate presence and template fallback are independent. Candidate-absent SPAWN/PATCH emits only local `ACK_SLOW`/`ACK_PATCH`; it never dereferences missing provider text.

Regression tests:

- `test_slice3a1_voice_failure_owns_the_only_terminal_before_late_spawn`
- `test_slice3a1_fail_closed_terminal_discards_late_patch_without_advancing_task`
- `test_slice3a1_candidate_absent_uses_local_template_and_worker_survives`
- `test_slice3a1_worker_normalizes_one_handler_exception_and_processes_next_turn`
- `test_slice3a1_slow_control_cancel_never_holds_mutation_lock_or_reorders_journal`

### Confirmation semantics

The additive, strict `confirmation_signal_hint` enum is `ACCEPT | REJECT | AMBIGUOUS | NOT_APPLICABLE`. It remains provider evidence, not authority. Missing is compatible with non-confirmation turns and normalizes to `NOT_APPLICABLE`.

- `ACCEPT` can produce `CONFIRMATION_ACCEPTED` only after exact current turn/ASR/request/epoch, task identity, `confirmation_id`, scope, and `plan_version` binding, then local Router, UserPatch construction, and SlowTask interpretation.
- `REJECT` follows the same binding and produces `CONFIRMATION_REJECTED` without cancelling the task.
- `AMBIGUOUS`, `NOT_APPLICABLE`, ordinary task patch, non-assistant/ignore, provider error/timeout, stale plan, changed scope, and changed task identity do not resolve the pending confirmation.
- A cancel hint without an explicit current-scope accept can request confirmation but cannot cancel directly.

Regression tests:

- `test_slice3a1_pending_confirmation_requires_explicit_bound_signal`
- `test_slice3a1_nonexplicit_confirmation_never_resolves_or_cancels`
- `test_slice3a1_explicit_confirmation_fails_closed_when_binding_is_stale`
- `test_qwen_cancel_hint_enters_userpatch_confirmation_instead_of_cancelling_directly`
- `test_slice3a1_inflight_patch_cannot_rebase_onto_replacement_task_identity`
- `test_stale_patch_snapshot_never_applies_to_the_old_plan_version`

### ASR item correlation

The enforced Voice core keeps the raw provider item ID only at the adapter boundary. It emits local opaque `provider_item_id`, `turn_ref`, `utterance_ref`, `audio_span_ref`, and session generation. A final is eligible only when item, local turn, utterance, audio span, offsets, and generation all match. Raw provider IDs never enter browser metadata, journal, timeline, repr, or error text.

Duplicate, missing, old, reordered, mismatched, post-interrupt, and post-rebuild final events are content-free and fail closed. They cannot create a Control request or authoritative state transition.

Regression tests:

- `test_slice3a1_asr_final_requires_exact_item_turn_utterance_span_and_generation`
- `test_slice3a1_duplicate_missing_mismatched_or_old_asr_is_content_free`
- `test_slice3a1_interrupt_fences_late_asr_final_without_rebinding_new_turn`
- `test_slice3a1_coordinator_routes_one_exactly_bound_asr_final_only_once`
- `test_slice3a1_invalid_asr_final_never_binds_current_turn_or_control_request`

### Voice interrupt, cancel, delete, rebuild, and watchdog

Each suppressed Voice response keeps a lifecycle record after output becomes permanently ineligible. Cleanup ownership remains until a matching terminal plus confirmed item delete, or a bounded watchdog timeout plus Voice-only rebuild.

- Only `status=cancelled` increments `cancel_terminal_count`.
- `completed` or `failed` after cancel increments unsafe status counters, remains output-ineligible, performs bounded cleanup, taints Voice, and requires rebuild.
- The independent watchdog is async, bounded, session-owned, and cancelled during close. Timeout taints and rebuilds Voice without stopping Control or the browser session.
- Delete acknowledgement futures are resolved only by the single ordered provider receiver; cleanup never races a second `receive()` call.
- Rebuild never replays accepted PCM. New PCM during rebuild is boundedly dropped and counted.

Regression tests:

- `test_enforced_voice_suppresses_text_pcm_cancels_to_terminal_and_deletes`
- `test_enforced_voice_cleanup_without_terminal_fails_closed_and_rebuilds_only_voice`
- `test_enforced_voice_delete_failure_taints_and_rebuild_does_not_replay_pcm`
- `test_slice3a1_completed_or_failed_after_cancel_is_unsafe_but_still_cleaned`
- `test_slice3a1_cancel_terminal_watchdog_rebuilds_and_bounds_new_pcm_drop`
- `test_slice3a1_successful_delete_keeps_late_output_permanently_ineligible`
- `test_slice3a1_core_delete_ack_is_resolved_only_by_single_receiver_path`

### Stale/superseded display and task identity

- A newer committed turn permanently removes old turns from user-visible eligibility.
- Queue drops, wrong correlation, active cancellation, and late results may record redacted metadata and a canonical fail-closed terminal, but cannot display clarification, text, or audio.
- Request envelopes carry an opaque task-identity ref plus version/confirmation snapshot. Task identity changes fail closed. Same-task version advance is explicitly re-evaluated against current authoritative state and is never silently applied to an old version.

Regression tests:

- `test_slice3a1_superseded_queue_drop_and_late_result_have_zero_visible_output`
- `test_wrong_correlation_late_result_queue_drop_and_supersede_never_rebind`
- `test_slice3a1_inflight_patch_cannot_rebase_onto_replacement_task_identity`

### Schema, capability truthfulness, security, and replay

- Strict schema rejects unknown/missing fields, invalid enum/range/type, oversized candidate, oversized full argument envelope, oversized fragments, and multiple/mismatched calls.
- Full Function Call arguments, candidate text, raw provider payload, transcript, PCM, credentials, and authorization headers are absent from safe metadata.
- Default real profiles now report `health_status=not_executed`, `output_mode=not_executed`, `verification_status=not_executed`, and `real_live_verified=false`. Provider-free verification and protocol declaration are separate from live connection health.
- `/healthz` does not return `status=ok` or `degraded=false` for a not-executed real profile.
- Browser binary playback frames remain zero in enforced mode.
- Canonical event sequences are contiguous and deterministic replay produces the same state digest without rerunning a provider.

Regression tests:

- `test_control_frame_rejects_missing_unknown_and_provider_binding_fields`
- `test_slice3a1_function_arguments_envelope_is_bounded_and_content_free`
- `test_slice3a1_not_executed_real_health_never_projects_ready_or_ok`
- `test_metadata_journal_and_timeline_exclude_voice_text_candidate_and_raw_inputs`
- `test_enforced_journal_is_authoritative_registry_only_and_replays`
- all tests in `test_security.py`

## Executed commands

Pre-hardening baseline:

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python \
  ./scripts/test tests/experiments/qwen_realtime_fast_slow -q
```

Result before Slice 3A.1 tests: `234 passed, 13 skipped in 2.33s`.

Historical Slice 3A.1 provider-free experiment suite (superseded by the Slice 3A.1.1 results above):

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python \
  ./scripts/test tests/experiments/qwen_realtime_fast_slow -q -rs
```

Result: `271 passed, 13 skipped in 2.64s`. Skip reason: sandbox does not permit binding a loopback test port.

Focused safety/security/capability suite:

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python \
  ./scripts/test \
  tests/experiments/qwen_realtime_fast_slow/test_slice3a_enforced_control.py \
  tests/experiments/qwen_realtime_fast_slow/test_qwen_voice_adapter.py \
  tests/experiments/qwen_realtime_fast_slow/test_security.py \
  tests/experiments/qwen_realtime_fast_slow/test_shadow_control_contract.py \
  tests/experiments/qwen_realtime_fast_slow/test_slice2_capabilities.py \
  tests/experiments/qwen_realtime_fast_slow/test_slice3a_server_flags.py -q
```

Result: `144 passed in 1.40s`.

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

Result: `82 passed in 0.33s`.

Slice 1 Fake/enforced and Slice 2 qwen/shadow remain included in the final experiment suite and passed. The explicit qwen/enforced provider-audio rejection also passed.

## Live acceptance record

| Check | Status | Evidence |
| --- | --- | --- |
| Credential-safe local server and headed browser startup | `executed_pass`, `n=1` | started on `127.0.0.1:8767`, then cleanly disconnected and stopped |
| Real Voice plus real Control WebSockets | `executed_pass`, `n=1` | UI showed Voice ingress and Control connected, `output_mode=real`, topology `dual_session_enforced_control`, experimental=yes, Qwen proposal non-authoritative, local Router authoritative, provider-native audio disabled, contexts clean, binary frames=0 |
| Real microphone upload | `not_executed` | privacy approval rejected exporting ambient audio/transcript; no workaround was attempted |
| Real item-bound ASR final | `not_executed` | provider-free correlation tests only |
| Real cancel terminal | `not_executed` | provider-free tests only |
| Real item delete acknowledgement | `not_executed` | provider-free tests only |
| Real Voice rebuild | `not_executed` | provider-free tests only |
| Real Control Function Call | `not_executed_for_3a1` | the older one-sample Slice 3A smoke is historical and not rerun as 3A.1 evidence |
| Live latency | `not_executed`, `n=0` | no 3A.1 real sample |
| Browser console errors/warnings | `not_executed` | not inspected during the startup sample |

No API key, Authorization header, raw provider payload, raw PCM, complete real transcript, complete Function Call arguments, or raw trace was printed or persisted.

## Slice 3B readiness

Provider-free control-plane hardening is ready for live validation, but Slice 3B admission is **not yet satisfied**. Remaining blockers are:

1. complete a real two-connection turn-level smoke with committed ingress and an authoritative Control outcome;
2. exercise exact real item-bound ASR final with microphone or an approved transient synthetic input;
3. observe real cancelled terminal, completed/failed-after-cancel handling, item delete acknowledgement, interrupt cleanup, and Voice-only rebuild;
4. exercise disconnect/reconnect freshness and verify no old PCM replay;
5. record live latency and browser-console sample counts;
6. obtain human acceptance of the proposed architecture ADR before broadening the boundary.

The recommended next stage remains dual session because it preserves Voice/Control isolation and independent cleanup/rebuild. It is not yet safe to start provider-native foreground audio: live Voice lifecycle/correlation evidence and ADR acceptance are still missing, and provider-native Qwen PCM remains prohibited.
