# Replay 规格

Source of truth: frozen ADR Baseline v0.4。本文件承载 P1-B-003，是从 ADR baseline 派生的实现规格。

Replay 的目标是从 event journal 重建状态、验证因果链、计算 SLO，并保护 repo-safe fixture 边界。默认 replay 不重跑真实模型、真实工具、外部 API、时钟或随机数。

## 1. Replay Modes

### Deterministic Replay

默认模式。只使用 recorded events 和 recorded refs 重建状态，不调用真实模型、真实工具、外部 API、时钟或随机数。

适用于：

- MVP-0 `InteractionState` replay。
- barge-in / truncate causal replay。
- UserPatch、plan_version、stale ToolResult replay。
- Tool progress / UI patch replay。
- Coverage / truthfulness chain replay。

### Degraded Replay

用于 data-plane refs 缺失或被 redaction 的 fixture。它重建所有可用 control-plane state，并把不可用 ref 标记为 unavailable diagnostics。它仍然不重跑真实模型或工具。

适用于：

- shareable fixture 省略 raw audio、raw trace、PII、secrets、large raw web content 的情况。
- old fixture 缺少 optional ref 的迁移场景。

### Re-eval Replay

显式 opt-in 模式。可以重跑 selected mock evaluator、本地 deterministic check 或 approved eval adapter。重新生成的输出必须标记为 re-eval output，不能冒充 original runtime fact。

适用于：

- 用 frozen synthetic fixtures 评估 heuristic 变更。
- 在 redacted fixtures 上重跑 coverage/truthfulness checks。
- 控制环境下的 adapter compatibility tests。

## 2. 默认 Replay 不得做什么

Deterministic 和 degraded replay 默认不得：

- 重跑真实 ASR、Thinker、Slow LLM、TTS、Duplex model、Embedding/RAG 或任何 provider。
- 重跑真实工具、demo tools、webSearch、外部 API 或 side-effecting operation。
- 从非本地存储拉取 raw audio。
- 执行 webSearch/tool result 中的指令。
- 把 `PLAYBACK_COMMITTED` 当作 user acknowledgement。
- 把 stale ToolResult 当作 current-plan evidence，除非存在 `STALE_EVIDENCE_ADOPTED`。
- 生成缺失 event id、timestamp、model output 或 tool result。

## 3. 模型 / 工具是否重跑

| Mode | 模型重跑 | 工具重跑 | 说明 |
| --- | --- | --- | --- |
| deterministic replay | no | no | 使用记录的 frame/result refs 和 events。 |
| degraded replay | no | no | 缺失 refs 变成 unavailable diagnostics。 |
| re-eval replay | explicit opt-in only | 仅 mock/dry-run/eval adapters 可 opt-in | regenerated output 必须标记 re-eval。 |

## 4. Replay 输入格式

Replay 输入由 ReplayManifest 和可排序 event list 组成：

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
```

## 5. ReplayManifest Fields

| 字段 | 必填 | 含义 |
| --- | --- | --- |
| `manifest_schema_version` | yes | Replay manifest schema version。 |
| `replay_id` | yes | replay run 或 fixture id。 |
| `source_trace_ref` | yes | source trace / fixture ref。 |
| `replay_mode` | yes | `deterministic`, `degraded`, `re_eval`。 |
| `event_schema_version_range` | yes | fixture 支持的 event schema versions。 |
| `fixture_domain` | yes | `LOCAL_DEBUG_TRACE`, `SHAREABLE_REPLAY`, `GITHUB_ALLOWED`。 |
| `generated_from` | yes | `local_trace`, `synthetic`, `redacted`, `hand_written_minimal`。 |
| `contains_raw_audio` | yes | shareable/GitHub fixture 必须 false。 |
| `contains_raw_trace` | yes | shareable/GitHub fixture 必须 false。 |
| `contains_real_user_input` | yes | 仅 local debug trace 可 true。 |
| `contains_secrets` | yes | 必须永远 false。 |
| `contains_unredacted_tool_result` | yes | shareable/GitHub fixture 必须 false。 |
| `contains_large_raw_web_content` | yes | shareable/GitHub fixture 必须 false。 |
| `raw_audio_ref` | optional | local debug only, opt-in。 |
| `expected_state_digest_ref` | optional | deterministic validation 的 expected digest。 |
| `allowed_re_eval_components` | optional | re-eval mode 的显式 allowlist。 |
| `redaction_report_ref` | optional | export redaction audit。 |

## 6. State Digest Format

State digest 遵守 `docs/specs/state-reducers.md`，且必须排除 raw audio、raw text、secrets、raw web content 和 raw tool credential payload。

## 7. Redacted Fixture Requirements

Shareable 和 GitHub-allowed fixtures 必须：

- synthetic / redacted / minimal。
- 排除 raw audio。
- 排除 raw debug trace。
- 排除 API keys、tokens、cookies、credentials、authorization headers、session secrets、raw tool auth payload。
- 排除 unredacted real user input。
- 排除敏感或外部原始 ToolResult。
- 排除 large raw webSearch / webpage content。
- 保留足够 metadata、refs、summaries、synthetic values 来 replay state transitions。

## 8. Local / Debug / Shareable Fixture Boundaries

| Domain | 允许内容 | 禁止内容 |
| --- | --- | --- |
| `LOCAL_DEBUG_TRACE` | Event journal、ASR/Thinker output、UserPatch、SlowTask state、ToolCall/ToolResult、demo backend patches、SpokenPlan、check results。 | 任何 raw secrets。 |
| `LOCAL_RAW_AUDIO` | 明确 dev/debug opt-in 的 raw audio。 | GitHub/shareable export、automatic upload/sync。 |
| `SHAREABLE_REPLAY` | synthetic/redacted/minimal events、summaries、metadata、safe snippets。 | raw audio、raw trace、secrets、PII、unredacted real input、sensitive tool results、large raw web content。 |
| `GITHUB_ALLOWED` | synthetic fixture、redacted sample、schema example、hand-written minimal replay case。 | raw audio、raw trace、secrets、replay cache、PII trace、unredacted real input。 |

## 9. Synthetic Fixture Rules

- 使用 invented ids、text、tool results、timestamps。
- 必须保留 causal shape 和 required fields。
- synthetic webSearch evidence 可使用 fake title/URL 或安全公开 URL。
- synthetic tool result 不得暗示真实外部副作用。
- mock outputs 必须使用 `output_mode=mock`。

## 10. Raw Audio Policy

- raw audio 默认关闭。
- raw audio 仅允许 `LOCAL_RAW_AUDIO`，且必须显式 dev/debug opt-in。
- raw audio 不得提交、上传、同步或进入 shareable/GitHub fixtures。
- 无 raw audio 时，replay 重建 event state，不重跑 audio inference。
- audio-level replay 属 local debug opt-in，仍不得默认调用真实模型。

## 11. Tool Result Replay Policy

- 默认 replay 使用记录的 `TOOL_RESULT_RECEIVED` metadata 和 `result_ref`，不执行工具。
- `TOOL_UI_STATE_PATCHED` 从 recorded `patch_ref` 或 redacted/synthetic substitute 重建 demo UI/backend state。
- webSearch ToolResult 作为 `UNTRUSTED_WEB_EVIDENCE` evidence replay，永远不是 instruction。
- shareable fixture 中 ToolResult refs 必须 redacted/minimized/synthetic。
- old-plan ToolResult replay 必须遵守 stale policy。

## 12. Stale ToolResult Replay Case

Required causal pattern:

1. `TOOL_EXECUTION_STARTED(task_id=T, plan_version=N, task_event_seq=A)`。
2. `USER_PATCH_RECEIVED(task_id=T, plan_version=N, observed_plan_version=N)`。
3. `USER_PATCH_INTERPRETED(interpreted_against_plan_version=N, materially_changes_task=true)`。
4. `PLAN_VERSION_ADVANCED(from_plan_version=N, to_plan_version=N+1)`。
5. 如果支持 cancellation，可选 `TOOL_EXECUTION_CANCEL_REQUESTED`。
6. `TOOL_RESULT_RECEIVED(task_id=T, plan_version=N, task_event_seq=A)`。
7. `TOOL_RESULT_MARKED_STALE(result_plan_version=N, current_plan_version=N+1)`。
8. `STALE_EVIDENCE_RECORDED(source_tool_result_event_id=...)`。
9. 若显式复用，才可有 `STALE_EVIDENCE_ADOPTED(plan_version=N+1, adopted_from_plan_version=N)`。

Replay assertions:

- 无 `STALE_EVIDENCE_ADOPTED` 时，old ToolResult 不推进 SlowTask current state 或 SemanticCommitment。
- 有 `STALE_EVIDENCE_ADOPTED` 时，adopted scope 和来源必须进入 state / commitment metadata。

## 13. Barge-in / Truncate Replay Case

Required causal pattern:

1. `PLAYBACK_SPAN_STARTED(playback_span_id=P)`。
2. `PLAYBACK_PROGRESS(playback_span_id=P, playback_offset_ms=X)`。
3. `PLAYBACK_COMMITTED(playback_span_id=P, playback_offset_ms=Xc)`。
4. `AUDIO_SPAN_STARTED(audio_span_id=A)`。
5. `SPEECH_START_DETECTED(audio_span_id=A)`。
6. `BARGE_IN_CANDIDATE(audio_span_id=A, playback_span_id=P, playback_offset_ms=B, echo_likelihood=..., barge_in_confidence=...)`。
7. `INTERRUPT_CANDIDATE(playback_span_id=P, playback_offset_ms=I, caused_by_event_id=BARGE_IN_CANDIDATE)`。
8. `TTS_TRUNCATE_REQUESTED(playback_span_id=P, cutoff_playback_offset_ms=C, interrupt_candidate_event_id=...)`。
9. `TTS_TRUNCATED(playback_span_id=P, actual_stop_offset_ms=S, truncate_request_event_id=...)`。

Replay assertions:

- `B`, `C`, `S` 三个 offset 保持区分。
- barge-in to truncate command latency 用 candidate/request monotonic timestamps 计算。
- `PlaybackState` 对 span `P` 进入 `TRUNCATED`。
- `PLAYBACK_COMMITTED` 不被视为 semantic acknowledgement。

## 14. Replay Output

Replay 输出：

- `REPLAY_STARTED`。
- reducer diagnostics。
- final state digest。
- `REPLAY_COMPLETED(result_status=passed|failed|degraded, state_digest=...)`。

Replay output 必须清楚标注 fixture domain 和 replay mode。
