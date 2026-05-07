# Replay Specification

Source of truth: frozen ADR Baseline v0.4. This document carries P1-B-003. It is a spec detail, derived from ADR baseline.

## 1. Replay Modes

### Deterministic Replay

Default replay mode. It reconstructs state from recorded events and recorded refs. It does not call real models, real tools, external APIs, clocks, or randomness. [ADR-002, ADR-010]

Use for:

- MVP-0 InteractionState replay.
- Barge-in / truncate causal replay.
- UserPatch, plan_version, stale ToolResult replay.
- Tool progress/UI patch replay.
- Coverage/truthfulness chain replay.

### Degraded Replay

Replay mode for incomplete fixtures or missing data-plane refs. It reconstructs all control-plane state available from events, marks unavailable refs as unavailable, and records replay diagnostics. It still does not re-run real models or tools by default. [ADR-010]

Use for:

- Shareable replay fixtures that omit raw audio, raw trace, PII, secrets, and large raw web content.
- Fixture migrations where an old optional ref is absent.

### Re-eval Replay

Explicit opt-in replay that may re-run selected mock evaluators, local deterministic checks, or approved eval adapters against redacted/synthetic inputs. Re-eval replay is not the default and MUST label any regenerated output as re-eval output, not original runtime fact. [ADR-002, ADR-010]

Use for:

- Measuring changed heuristics against frozen synthetic fixtures.
- Re-running coverage/truthfulness checks on redacted fixtures.
- Adapter compatibility tests in a controlled eval context.

## 2. What Replay Must Not Do By Default

Default deterministic and degraded replay MUST NOT:

- Re-run real ASR, Thinker, Slow LLM, TTS, Duplex model, embedding/RAG, or any model provider. [ADR-002, ADR-010, ADR-011]
- Re-run real tools, demo tools, webSearch, external APIs, or side-effecting operations. [ADR-002, ADR-005, ADR-010]
- Fetch raw audio from non-local storage.
- Execute instructions found in webSearch/tool results. [ADR-014]
- Treat `PLAYBACK_COMMITTED` as user acknowledgement. [ADR-001, ADR-002]
- Treat stale ToolResult as current-plan evidence unless `STALE_EVIDENCE_ADOPTED` exists. [ADR-004]
- Generate missing event ids, timestamps, model outputs, or tool results.

## 3. Whether Models / Tools Are Re-run

| Mode | Models re-run | Tools re-run | Notes |
| --- | --- | --- | --- |
| deterministic replay | no | no | Uses recorded frame/result refs and events. |
| degraded replay | no | no | Missing refs become unavailable diagnostics. |
| re-eval replay | explicit opt-in only | explicit opt-in only for mock/dry-run/eval adapters | Regenerated outputs are labeled re-eval, not original facts. |

## 4. Replay Input Format

Replay input is a ReplayManifest plus an ordered or orderable event list.

Spec detail, derived from ADR baseline:

```yaml
replay_manifest:
  manifest_schema_version: "1.0"
  replay_id: "replay_..."
  source_trace_ref: "trace_ref_or_fixture_ref"
  replay_mode: "deterministic | degraded | re_eval"
  event_schema_version_range: ["1.0"]
  fixture_domain: "LOCAL_DEBUG_TRACE | SHAREABLE_REPLAY | GITHUB_ALLOWED"
  generated_from: "local_trace | synthetic | redacted | hand_written_minimal"
  contains_raw_audio: false
  contains_raw_trace: false
  contains_real_user_input: false
  contains_secrets: false
  contains_unredacted_tool_result: false
  contains_large_raw_web_content: false
  allowed_re_eval_components: []
  expected_state_digest_ref: "digest_ref_optional"
events:
  - event_id: "evt_..."
    event_seq: 1
    event_schema_version: "1.0"
    ...
```

## 5. ReplayManifest Fields

| Field | Required | Meaning |
| --- | --- | --- |
| `manifest_schema_version` | yes | Replay manifest schema version. |
| `replay_id` | yes | Replay run or fixture id. |
| `source_trace_ref` | yes | Source trace/fixture ref. |
| `replay_mode` | yes | `deterministic`, `degraded`, or `re_eval`. |
| `event_schema_version_range` | yes | Supported event schema versions in fixture. |
| `fixture_domain` | yes | `LOCAL_DEBUG_TRACE`, `SHAREABLE_REPLAY`, or `GITHUB_ALLOWED`. |
| `generated_from` | yes | `local_trace`, `synthetic`, `redacted`, or `hand_written_minimal`. |
| `contains_raw_audio` | yes | Must be false for shareable/GitHub fixtures. |
| `contains_raw_trace` | yes | Must be false for shareable/GitHub fixtures. |
| `contains_real_user_input` | yes | True only for local debug trace with proper redaction level. |
| `contains_secrets` | yes | Must always be false. |
| `contains_unredacted_tool_result` | yes | Must be false for shareable/GitHub fixtures. |
| `contains_large_raw_web_content` | yes | Must be false for shareable/GitHub fixtures. |
| `raw_audio_ref` | optional | Local debug only, opt-in. |
| `expected_state_digest_ref` | optional | Expected digest for deterministic validation. |
| `allowed_re_eval_components` | optional | Explicit list for re-eval mode. |
| `redaction_report_ref` | optional | Export redaction audit. |

## 6. State Digest Format

State digest follows `docs/specs/state-reducers.md`:

- `digest_schema_version`
- `source_session_id`
- `last_event_seq`
- `event_schema_version_range`
- `interaction_state_hash`
- `task_focus_state_hash`
- `slowtask_state_hash`
- `playback_state_hash`
- `adapter_health_state_hash`
- `trace_privacy_state_hash`
- `overall_digest`

Digest computation MUST exclude raw audio, raw text, secrets, raw web content, and raw tool credential payloads. [ADR-010]

## 7. Redacted Fixture Requirements

Shareable and GitHub-allowed fixtures MUST:

- Be synthetic, redacted, or minimal. [ADR-010, ADR-015]
- Exclude raw audio. [ADR-010, ADR-015]
- Exclude raw debug trace. [ADR-010, ADR-015]
- Exclude API keys, tokens, cookies, credentials, authorization headers, session secrets, and raw tool auth payloads. [ADR-010, ADR-015]
- Exclude unredacted real user input. [ADR-007, ADR-010]
- Exclude unredacted ToolResult payloads when they contain sensitive or external raw content. [ADR-010]
- Exclude large raw webSearch/webpage content. [ADR-010, ADR-014]
- Preserve enough metadata, refs, summaries, and synthetic values to replay state transitions. [ADR-002, ADR-010]

## 8. Local / Debug / Shareable Fixture Boundaries

| Domain | Allowed content | Forbidden content |
| --- | --- | --- |
| `LOCAL_DEBUG_TRACE` | Event journal, ASR/Thinker output, UserPatch, SlowTask state, ToolCall/ToolResult, demo backend patches, SpokenPlan, check results. [ADR-010] | Raw secrets in any form. |
| `LOCAL_RAW_AUDIO` | Raw audio only when dev/debug opt-in; local retention suggested <= 7 days. [ADR-010] | GitHub/shareable export, automatic upload/sync. |
| `SHAREABLE_REPLAY` | Synthetic/redacted/minimal events, summaries, metadata, short safe snippets. [ADR-010] | Raw audio, raw trace, secrets, PII, unredacted real input, unredacted sensitive tool results, large raw web content. |
| `GITHUB_ALLOWED` | Synthetic fixture, redacted sample, schema example, hand-written minimal replay case. [ADR-010, ADR-015] | Raw audio, raw trace, secrets, replay cache, PII trace, unredacted real user input. |

## 9. Synthetic Fixture Rules

Spec detail, derived from ADR baseline:

- Synthetic fixtures should use invented ids, text, tool results, and timestamps.
- Synthetic fixtures MUST preserve causal shape and required fields.
- Synthetic webSearch evidence MAY include fake source titles/URLs or safe public URLs if not sensitive.
- Synthetic tool result values MUST not imply real external side effects.
- Mock outputs in synthetic fixtures MUST use `output_mode=mock`.

## 10. Raw Audio Policy

- Raw audio is disabled by default. [ADR-010]
- Raw audio is allowed only in `LOCAL_RAW_AUDIO` with explicit dev/debug opt-in. [ADR-010]
- Raw audio MUST NOT be committed, uploaded, synchronized, or included in shareable/GitHub fixtures. [ADR-010, ADR-015, AGENTS.md]
- Without raw audio, replay reconstructs event state and does not re-run audio inference. [ADR-010]
- Audio-level replay with raw audio is local debug opt-in and must still avoid real model calls unless explicitly re-eval authorized.

## 11. Tool Result Replay Policy

- Default replay uses recorded `TOOL_RESULT_RECEIVED` metadata and `result_ref`; it does not execute tools. [ADR-002, ADR-010]
- `TOOL_UI_STATE_PATCHED` events replay demo frontend/backend state patches from recorded `patch_ref` or redacted/synthetic substitute. [ADR-005, ADR-010]
- webSearch ToolResult is replayed as `UNTRUSTED_WEB_EVIDENCE` evidence, never instructions. [ADR-014]
- ToolResult refs in shareable fixtures must be redacted, minimized, or synthetic. [ADR-010]
- Old-plan ToolResult replay must follow stale policy. [ADR-004]

## 12. Stale ToolResult Replay Case

Required causal pattern:

1. `TOOL_EXECUTION_STARTED(task_id=T, plan_version=N, task_event_seq=A)`.
2. `USER_PATCH_RECEIVED(task_id=T, plan_version=N, observed_plan_version=N)`.
3. `USER_PATCH_INTERPRETED(interpreted_against_plan_version=N, materially_changes_task=true)`.
4. `PLAN_VERSION_ADVANCED(from_plan_version=N, to_plan_version=N+1)`.
5. Optional `TOOL_EXECUTION_CANCEL_REQUESTED` if cancellation supported.
6. `TOOL_RESULT_RECEIVED(task_id=T, plan_version=N, task_event_seq=A)`.
7. `TOOL_RESULT_MARKED_STALE(result_plan_version=N, current_plan_version=N+1)`.
8. `STALE_EVIDENCE_RECORDED(source_tool_result_event_id=...)`.
9. Optional `STALE_EVIDENCE_ADOPTED(plan_version=N+1, adopted_from_plan_version=N)` if SlowTask explicitly adopts/rebases it.

Replay assertions:

- Without `STALE_EVIDENCE_ADOPTED`, SlowTask current state and SemanticCommitment do not advance from the old ToolResult. [ADR-004, ADR-016]
- With `STALE_EVIDENCE_ADOPTED`, adopted scope and source are visible in state and later commitment metadata. [ADR-004]

## 13. Barge-in / Truncate Replay Case

Required causal pattern:

1. `PLAYBACK_SPAN_STARTED(playback_span_id=P)`.
2. `PLAYBACK_PROGRESS(playback_span_id=P, playback_offset_ms=X)`.
3. `PLAYBACK_COMMITTED(playback_span_id=P, playback_offset_ms=Xc)`.
4. `AUDIO_SPAN_STARTED(audio_span_id=A)`.
5. `SPEECH_START_DETECTED(audio_span_id=A)`.
6. `BARGE_IN_CANDIDATE(audio_span_id=A, playback_span_id=P, playback_offset_ms=B, echo_likelihood=..., barge_in_confidence=...)`.
7. `INTERRUPT_CANDIDATE(playback_span_id=P, playback_offset_ms=I, caused_by_event_id=BARGE_IN_CANDIDATE)`.
8. `TTS_TRUNCATE_REQUESTED(playback_span_id=P, cutoff_playback_offset_ms=C, interrupt_candidate_event_id=...)`.
9. `TTS_TRUNCATED(playback_span_id=P, actual_stop_offset_ms=S, truncate_request_event_id=...)`.

Replay assertions:

- `B`, `C`, and `S` remain distinct offsets. [ADR-003]
- Barge-in to truncate command latency is computed from monotonic timestamps of candidate/request events. [ADR-003, ADR-012]
- PlaybackState ends in `TRUNCATED` for span `P`.
- InteractionState playback phase becomes `TRUNCATED`; collecting input may continue if the user is still speaking. [ADR-001]

## 14. Replay Output

Replay emits:

- `REPLAY_STARTED`.
- State reducer diagnostics.
- Final state digest.
- `REPLAY_COMPLETED(result_status=passed|failed|degraded, state_digest=...)`.

Replay output MUST clearly label fixture domain and replay mode. [ADR-010]
