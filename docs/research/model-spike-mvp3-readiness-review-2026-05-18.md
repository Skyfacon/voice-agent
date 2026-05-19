# Model Spike MVP3 Readiness Review

## Status

research_orientation_single_source

本文是 model spike research lane 在进入后续 MVP3 planning / mainline sync 前的主入口复盘。它只整理现有 evidence、contract delta、风险和后续线程，不授权 runtime adapter implementation，不授权真实 provider 接入，不修改 ADR / specs / runtime / tests。

## Date

2026-05-18

## 1. 当前分支 / git 状态 / 主线 contract snapshot

### 当前分支与工作区

只读检查结果：

- 当前分支：`research/model-spikes`
- `git status --short --branch`：`## research/model-spikes...origin/research/model-spikes [ahead 18, behind 3]`
- 已存在的 research lane 变更包括：
  - `M docs/research/model-spike-integration-ledger.md`
  - 多个未跟踪 research 文档：`model-spike-mainline-sync-2026-05-17.md`、`model-spike-phase-summary-*`、`model-spike-adapter-profile-hardening-checklist-2026-05-12.md`
  - 未跟踪 `docs/research/profiles/`
  - 未跟踪若干 `docs/research/spikes/*`
  - 未跟踪 `tools/`

本复盘新增文件：

- `docs/research/model-spike-mvp3-readiness-review-2026-05-18.md`

### 主线 contract snapshot

本线程只读观察到的主线状态：

| snapshot | 含义 | 本复盘解释 |
| --- | --- | --- |
| `main@61e6afc` | 2026-05-11/12 model spike 默认历史基线 | 旧 run report / profile 仍是有效历史 evidence，但不得自动升级为当前可集成事实。 |
| `main@ac1b43f` | 2026-05-17 sync 文档记录的 current main，MVP2 slice0 replay safety | 作为 5/17 之后 research hardening 的最低新基线。 |
| `main@f325483` | 本线程 2026-05-18 本地 `main` 只读观察值 | 已包含 `mvp2/slice1-tool-execution-state` 与 `mvp2/slice2-demo-tool-executor-skeleton` 相关 merge；后续 planning 必须重新对齐此 commit 或更新 main。 |

主线 contract 快照要点：

- MVP1 已完成 mock/replay control-plane：SlowTask、UserPatch、`plan_version`、`task_event_seq`、stale evidence、confirmation、SemanticCommitment 和 acceptance runner。
- MVP2 contract 明确 Tool Executor、demo sandbox tools、`TOOL_UI_STATE_PATCHED`、webSearch evidence boundary、Thinker-as-Composer、CommitmentCoverageCheck、ProgressTruthfulnessCheck。
- `docs/specs/event-registry.md` 已列 canonical MVP2 event names，但 event name 存在不等于所有 runtime owner-boundary 已被 model spike 证明。
- `docs/specs/replay-spec.md` 明确 deterministic replay 默认不得重跑真实 ASR / Thinker / Slow LLM / TTS / Duplex / Embedding/RAG / tools / webSearch。

## 2. model spike research 已完成阶段时间线

| 日期 | 阶段 | 产物 / 结论 |
| --- | --- | --- |
| 2026-05-09 | 候选 shortlist | ASR、TTS、Thinker、Slow LLM、Duplex/VAD 初始能力探针文档完成，形成 layered adapter stack 方向。 |
| 2026-05-11 | MVP0 contract 后实操计划 | `model-spike-execution-plan.md`、`model-selection.md`、`model-spike-plan.md` 更新到 `main@61e6afc` 历史基线。 |
| 2026-05-11 | metadata-only real/local runs | DashScope Qwen Slow LLM JSON、CosyVoice TTS、Qwen-ASR、Qwen-Omni Thinker、local energy gate、local WebRTC VAD 与 WebRTC VAD harness run 完成。 |
| 2026-05-12 | spike-local dry-run harness refresh | ASR / TTS / Slow LLM / Thinker-Composer metadata harnesses 和 hardening addenda 完成；full synthetic matrices 通过验证。 |
| 2026-05-17 | mainline sync addendum | research lane 从 MVP0 baseline 校准到 MVP1 closeout + MVP2 start，要求新报告引用 `main@ac1b43f` 或更新。 |
| 2026-05-18 | readiness review | 本文整理当前可用于 MVP3 planning 的证据、blockers、Go/No-Go 与后续线程。 |

## 3. evidence inventory

### Run reports

| 领域 | 文件 | evidence label | 摘要 |
| --- | --- | --- | --- |
| Slow LLM / Qwen | `docs/research/spikes/slow-llm-dashscope-qwen-json-run-2026-05-11.md` | `observed_real` + `observed_degraded` | `qwen3.6-plus` JSON object mode、local schema validation、bounded repair、insufficient evidence、conflict preservation、tool proposal shape；client timeout observed, provider cancellation unknown。 |
| Slow LLM / DeepSeek | `docs/research/spikes/slow-llm-deepseek-json-run-2026-05-11.md` | `unknown` | key missing，未执行；仅保留 docs-shaped comparison candidate。 |
| TTS / CosyVoice | `docs/research/spikes/tts-dashscope-bailian-run-2026-05-11.md` | `observed_real` + `observed_degraded` | basic synthesis、streaming audio chunks、word timestamps、first audio bucket；client close observed，provider cancellation unknown，truncate 不属于 provider fact。 |
| ASR / Qwen-ASR | `docs/research/spikes/asr-dashscope-bailian-run-2026-05-11.md` | `observed_real` + `observed_degraded` | transcript-like output、response streaming、filetrans timestamp-like fields；silence false positive risk，true realtime mic streaming unknown。 |
| Thinker / Qwen-Omni | `docs/research/spikes/thinker-dashscope-qwen-omni-run-2026-05-11.md` | `observed_real` + `observed_degraded` | SemanticFrame JSON、audio Data URL input、evidence separation、emotion/audio-caption schema、tool proposal deltas、Composer-role shape；full structured latency too slow for hot path。 |
| Duplex/VAD energy gate | `docs/research/spikes/duplex-vad-local-run-2026-05-11.md` | `observed_degraded` | deterministic energy gate validates event-shape and offset semantics only；non-speech false positives and idealized echo subtraction remain risks。 |
| Duplex/VAD WebRTC | `docs/research/spikes/duplex-vad-webrtcvad-local-run-2026-05-11.md` | `observed_real` + `observed_degraded` | WebRTC VAD frame decisions on synthetic PCM；10/20/30 ms frames, modes 0/2/3；live mic, AEC, directedness, semantic close unknown。 |
| Duplex/VAD harness | `docs/research/spikes/duplex-vad-webrtcvad-harness-run-2026-05-11.md` | `synthetic_eval` + `observed_real` for local frame decisions | spike-local harness emitted 91 metadata-only observations and 4/4 self-check pass in temp venv。 |

### Profiles

| profile | 状态 |
| --- | --- |
| `slow-llm-qwen-capability-profile-draft-2026-05-11.md` | strongest Slow LLM draft；历史基线 `main@61e6afc`。 |
| `slow-llm-qwen-profile-hardening-addendum-2026-05-12.md` | `harden_next`；full synthetic 21 observations valid。 |
| `tts-cosyvoice-capability-profile-draft-2026-05-12.md` | viable TTS draft；truncate caveat explicit。 |
| `tts-cosyvoice-profile-hardening-addendum-2026-05-12.md` | `harden_next` with truncate caveat；full synthetic 20 observations valid。 |
| `asr-qwen-asr-capability-profile-draft-2026-05-12.md` | viable ASR draft；realtime mic and silence risk explicit。 |
| `asr-qwen-asr-profile-hardening-addendum-2026-05-12.md` | `harden_after_gap`；full synthetic 23 observations valid。 |
| `thinker-qwen-omni-capability-profile-draft-2026-05-12.md` | viable post-commit Thinker evidence draft；not Duplex hot path。 |
| `thinker-qwen-omni-profile-hardening-addendum-2026-05-12.md` | `harden_after_gap`；full synthetic 22 observations valid。 |
| `thinker-as-composer-boundary-hardening-addendum-2026-05-12.md` | Composer boundary only；do not promote to runtime integration；full synthetic 22 observations valid。 |

### Hardening addenda / proof plans

- `docs/research/model-spike-adapter-profile-hardening-checklist-2026-05-12.md`
- `docs/research/model-spike-mainline-sync-2026-05-17.md`
- ASR streaming / timestamp / cancellation proof plans
- TTS playback / truncate proof plan
- Slow LLM retry / cancellation eval plan
- Thinker / Composer eval harness plan
- Duplex/VAD realtime ingress proof plan

### Harness / tooling

| harness | path | 当前价值 |
| --- | --- | --- |
| ASR streaming eval | `tools/model_spikes/asr_streaming_eval/` | metadata-only dry-run for transcript, streaming output, timestamps, timeout/cancel, late transcript, boundary checks。 |
| TTS playback eval | `tools/model_spikes/tts_playback_eval/` | metadata-only dry-run for synthesis metadata, playback progress, truncate chain, client close, late/partial audio。 |
| Slow LLM retry eval | `tools/model_spikes/slow_llm_retry_eval/` | metadata-only dry-run for validation, repair, timeout, stale result, tool proposal, web evidence。 |
| Thinker / Composer eval | `tools/model_spikes/thinker_composer_eval/` | metadata-only dry-run for SemanticFrame, evidence separation, Composer coverage/truthfulness boundary。 |
| Duplex VAD | `tools/model_spikes/duplex_vad/` | local WebRTC VAD synthetic PCM metadata harness；does not import runtime。 |

## 4. 各领域结论表

| 领域 | 当前结论 | MVP3 planning 可用性 | 主要 blockers |
| --- | --- | --- | --- |
| Slow LLM | DashScope Qwen 是当前最强 Slow LLM candidate；validated JSON、bounded repair、missing/conflict preservation、proposal-only tool shape 已有 direct evidence。 | 可支撑 adapter profile / failure policy / schema validation planning；不可直接支撑 runtime integration。 | current model alias re-pin、provider-confirmed cancellation、streaming JSON partial quality、provider transient failure/rate-limit taxonomy、按 `main@f325483` 复核 task-bound fields。 |
| ASR | Qwen-ASR 可产出 transcript-like evidence、response streaming output、filetrans timestamp-like metadata；ASR 仍只是 text projection evidence。 | 可支撑 ASR adapter profile planning；需要把 realtime input 标成 unknown/degraded。 | true realtime mic streaming、silence/non-speech false positive policy、confidence calibration、timestamp normalization、provider cancellation。 |
| TTS | CosyVoice 可产出 basic synthesis、streaming chunks、word timestamps 和 first-audio bucket；TTS provider 不拥有 truncate truth。 | 可支撑 TTS synthesis adapter planning；Talker/playback proof 必须独立。 | Talker actual stop offset、provider cancellation、late/partial audio handling、format/rate/voice coverage、no generated audio artifact policy。 |
| Thinker | Qwen-Omni 可产出 SemanticFrame evidence、audio Data URL input、streaming text、evidence separation、tool proposal-only surface。 | 可支撑 post-commit Thinker evidence profile；不适合 Duplex hot path。 | full structured latency、semantic close unknown、assistant-directedness unknown、audio timestamp unknown、provider cancellation、larger schema stability set。 |
| Thinker-as-Composer | Composer-role shape和 synthetic boundary eval 已有；模型自称覆盖不等于安全证明。 | 可支撑 MVP2/MVP3 checker contract planning；不可独立支撑 playback。 | independent CommitmentCoverageCheck / ProgressTruthfulnessCheck runtime chain、protected-field diff checks、stale evidence rejection proof、confirmation state preservation。 |
| Duplex/VAD | WebRTC VAD synthetic PCM frame decisions可重复；barge-in candidate needs playback reference；VAD 不拥有 semantic close / directedness。 | 可支撑 local proof planning；不能支撑 full live device integration。 | live mic scheduling、real AEC/playback reference、natural speech fixture、echo/noise false positive bounds、directedness/semantic close另证。 |
| webSearch/RAG | 已有 ADR / MVP2 boundary：webSearch 是 Tool，结果必须是 `UNTRUSTED_WEB_EVIDENCE`。 | 可支撑 prompt/evidence boundary planning；没有 real RAG/provider readiness。 | mock/synthetic first pass、source attribution/redaction、large raw content exclusion、tool policy不可被 web content 修改。 |

## 5. evidence label 表

| label | 含义 | 本复盘使用规则 |
| --- | --- | --- |
| `observed_real` | 在 metadata-only real-provider 或 local run 中直接观察到。 | 可支撑 bounded capability claim，但只限 observed candidate、日期、surface 和 role。 |
| `observed_degraded` | 直接观察到但不足以满足目标行为，或必须降级使用。 | 可支撑 degradation policy / blocker，不可包装成 target-valid capability。 |
| `synthetic_eval` | 只由 spike-local synthetic dry-run / metadata harness 覆盖。 | 可支撑 schema、event shape、owner boundary，不可证明 real provider capability。 |
| `unknown` | 当前没有可靠 evidence。 | 必须保持 gap；MVP3 planning 只能设计 fallback/degraded behavior。 |
| `unsupported` | 不属于该 candidate role 或明确不能由它拥有。 | 必须列入 forbidden reliance，防止 runtime 静默依赖。 |

## 6. 足够支撑 MVP3 planning vs research hint

### 足够支撑 MVP3 planning

- 分层 adapter stack 方向：Slow LLM、ASR、TTS、Thinker、Duplex/VAD 分开接入，不用 all-in-one omni model 压缩边界。
- `output_mode` / evidence labels / capability matrix 必须成为 adapter profile 的核心字段。
- Slow LLM / ASR / TTS / Thinker 已证明可以生成 replay-safe metadata，不需要提交 raw provider payload、raw audio 或 local trace。
- Tool-like model output 只能是 proposal；Tool Executor owns execution / authorization / UI patch / normalized ToolResult。
- Composer 只做 SpokenPlan realization；coverage / truthfulness checks 必须独立。
- Deterministic replay 只消费 recorded metadata 或 synthetic fixtures，不重跑 provider / tool / VAD。

### 仍只是 research hint

- Provider-confirmed cancellation 与真实 late-result behavior。
- 当前 provider model aliases、official limits、endpoint capability 和 pricing/quotas。
- ASR true realtime mic streaming 和 timestamp normalization质量。
- TTS playback stop offset、truncate accuracy、late audio handling。
- Thinker semantic close / assistant-directedness。
- Duplex live mic scheduling、real playback reference / AEC。
- webSearch/RAG real provider behavior。
- DeepSeek、GLM、Kimi 等 comparison candidates。

## 7. 与 MVP1/MVP2 contract 对齐情况

### MVP1

对齐：

- Research docs 明确 SlowTask owns final facts、confirmation、stale/adoption、SemanticCommitment。
- UserPatch / ToolResult / SemanticCommitment 必须绑定 `task_id`、`plan_version`、`task_event_seq` 的方向正确。
- Old-plan result 默认 stale，只有 `STALE_EVIDENCE_ADOPTED` 后才可进入 current-plan reasoning。
- Terminal states sticky；late evidence 不得推进 current task。

需要复核：

- 旧 2026-05-11/12 evidence 多数仍写 `main@61e6afc`，新 hardening 必须显式补 `historical_contract_snapshot` 与 `contract_snapshot=main@f325483` 或更新。
- Slow LLM / Thinker task-bound synthetic eval 需要按当前 registry required fields 复核：`observed_plan_version`、`interpreted_against_plan_version`、current-plan stale marking、new `task_event_seq`。

### MVP2

对齐：

- Tool-like output 被明确限制为 proposal evidence。
- `TOOL_UI_STATE_PATCHED` 是唯一 demo/frontend state mutation path。
- webSearch 必须是 `UNTRUSTED_WEB_EVIDENCE`，只进 evidence，不进 instruction。
- Composer 不能 rewrite SemanticCommitment facts；playback 需要 coverage/truthfulness gate。

需要复核：

- 2026-05-17 addendum 基于 `main@ac1b43f`，本线程 local main 已到 `f325483`；MVP2 ToolExecutionState / Tool Executor skeleton contract 需要单独同步到 research docs。
- MVP2 event mapping 需要覆盖 `TOOL_MANIFEST_LOADED`、`TOOL_ARGUMENTS_PARTIAL/READY`、`TOOL_EXECUTION_AUTHORIZED/STARTED`、`TOOL_UI_STATE_PATCHED`、failure/retry/cancel、progressive stale ToolResult。
- Composer / checker dry-run 需要映射到 `SPOKEN_PLAN_EMITTED`、`COMMITMENT_COVERAGE_CHECK_*`、`PROGRESS_TRUTHFULNESS_CHECK_*`、`PLAYBACK_SPAN_STARTED.approved_check_event_id`。

## 8. 必须重做 / 复核项

| 项 | 当前状态 | 必须复核动作 |
| --- | --- | --- |
| historical `main@61e6afc` vs current `main@ac1b43f` | 旧 reports/profiles 基于 `61e6afc`；5/17 sync 要求 `ac1b43f` 或更新。 | 新 report/profile 必须保留 `historical_contract_snapshot=main@61e6afc`，并声明新 `contract_snapshot`。 |
| local main `f325483` | 本线程发现本地 main 已超过 `ac1b43f`。 | 另开 sync thread 对齐 `main@f325483` 或更新 main，尤其是 MVP2 Tool Executor skeleton。 |
| dry-run smoke counts vs full_synthetic counts | dry-run summary 文档有 ASR/TTS/Slow LLM smoke 5 条；profile/phase/ledger 记录 full synthetic ASR 23、TTS 20、Slow LLM 21、Thinker 22。 | 必须区分 `case_set=smoke` 与 `case_set=full_synthetic`；必要时重写/补一份 full synthetic summary，避免计数混用。 |
| task-bound metadata fields | 当前方向正确，但旧 docs 多为 research shape。 | 复核 `task_id`、`plan_version`、`task_event_seq`、`observed_plan_version`、`interpreted_against_plan_version`、`tool_call_id`、`confirmation_id`、`commitment_id`、source refs。 |
| MVP2 Tool Executor event mapping | research docs 仍主要停在 proposal-only boundary。 | 为 Slow LLM tool proposal、webSearch evidence、old-plan ToolResult、UI patch 建映射表，但仍不改 specs。 |
| Composer / checker mapping | Synthetic coverage/truthfulness cases存在。 | 映射到 canonical events 和 playback gate；模型自检不得成为 pass。 |
| Provider aliases / limits | 2026-05-11 aliases 已观察，但可能变动。 | 任何新 live run 当天重新查官方来源并记录日期；本线程未联网复查。 |
| Artifact policy | 当前 reports 声明无 raw audio / raw provider payload。 | 合龙前再扫 repo artifact paths 和 `.gitignore`，确保 `diagnostics/`、`traces/`、`replays/local/`、`audio/raw/`、`.env*` 覆盖。 |

## 9. MVP3 integration blockers

- MVP2 尚未 closeout；即使本地 main 已有 slice2 merge，也不能把 Tool Executor / Composer / checker runtime 当成已完成 integration proof。
- 没有任何 runtime adapter implementation approval。
- 没有 real adapter design doc / ADR delta review / mainline integration branch。
- Provider-confirmed cancellation、retry taxonomy、rate-limit handling和 health/error policy 不足。
- ASR realtime microphone streaming、TTS playback truncate、Duplex live AEC 都未 target-valid。
- Thinker semantic close / assistant-directedness 仍 unknown。
- Composer coverage/truthfulness runtime chain 未在 research lane 证明。
- Selected observations 尚未转成 mainline-approved synthetic/redacted replay/eval fixtures。
- Model aliases、limits、endpoint surfaces 需要 integration-day re-pin。

## 10. 三层路线

### 立即 sync / review / docs

1. 保留本文作为 model-spike MVP3 readiness orientation。
2. 另开 thread 做 `main@f325483` contract sync addendum，只改 `docs/research/`。
3. 复核 dry-run summary counts，补齐 smoke / full_synthetic 的命名和引用差异。
4. 为 MVP2 Tool Executor / Composer / checker event mapping 写 research-only matrix。

### 下一批 spike-local tooling / eval

1. Slow LLM：按 MVP1 closeout + current main 复核 retry / stale / tool proposal full synthetic cases。
2. Thinker-as-Composer：把 protected-field diff、coverage failure、progress truthfulness、stale evidence rejection 独立化。
3. ASR：realtime input gap 保持 explicit，补 timestamp normalization / silence policy eval。
4. TTS：补 playback progress / actual stop offset proof，不把 provider close 当 truncate。
5. Duplex/VAD：继续 local harness，加入 live-ish scheduling / playback reference proof，但不采集真实用户录音。
6. webSearch/RAG：只做 synthetic/mock untrusted evidence path，禁止 large raw content。

### 未来 MVP3 integration branch 才能做的事

- 修改 `src/voice_agent/`、`tests/`、`docs/specs/` 或 `docs/adr/`。
- 创建 runtime real ASR / Thinker / Slow LLM / TTS adapters。
- 接真实 provider 到主 runtime。
- 把 selected metadata observations 转成 mainline acceptance replay/eval fixtures。
- 定义 adapter health/error policy、secrets redaction、provider cancellation handling 和 fallback/degraded modes。

## 11. 建议拆分的后续线程清单

1. `main@f325483` model-spike mainline sync addendum。
2. Smoke vs full_synthetic dry-run count reconciliation。
3. Slow LLM task-bound metadata hardening against MVP1 closeout / current registry。
4. MVP2 Tool Executor mapping for model proposals, webSearch, stale ToolResult, UI patch。
5. Thinker-as-Composer checker mapping and protected-field diff design。
6. ASR timestamp / realtime / silence-risk eval refresh。
7. TTS playback truncate proof refresh。
8. Duplex/VAD live-ish local scheduling and playback-reference proof。
9. Provider alias / official limit re-pin plan, requiring human approval before network/provider work。
10. Mainline merge/handoff artifact order review。

## 12. mainline 合龙产物顺序

建议合龙顺序：

1. Readiness review：本文。
2. Current mainline sync addendum：更新 `ac1b43f` 到当前 `main@f325483` 或更新。
3. Evidence inventory / index：把 run reports、profiles、harnesses、labels 串成一个可检索入口。
4. Dry-run count reconciliation：明确 smoke vs full_synthetic 的 case-set 和 validation status。
5. Profile hardening refresh：为 primary candidates 补 current contract snapshot、metadata fields、MVP2 mapping。
6. MVP3 adapter profile proposal：仍在 `docs/research/` 或经批准进入 mainline specs。
7. MVP3 integration plan：只有 human 明确批准后，才进入 runtime branch。
8. Runtime implementation / tests / replay fixtures：只能在 MVP3 integration branch 做。

## 13. Go / No-Go checklist

| 检查项 | 当前判断 | 说明 |
| --- | --- | --- |
| 用于 MVP3 planning orientation | Go | 证据足够支撑规划、风险排序和后续线程拆分。 |
| 作为 candidate shortlist | Go | Slow LLM Qwen、CosyVoice、Qwen-ASR、Qwen-Omni、WebRTC VAD 仍是 primary research candidates。 |
| 作为 adapter profile hardening 输入 | Conditional Go | 需要补 current main snapshot 和 required metadata fields。 |
| 作为 runtime adapter implementation 输入 | No-Go | 没有 integration branch approval、MVP2 closeout、provider error policy 或 replay/eval fixtures。 |
| 接真实 provider 到主 runtime | No-Go | 本线程严格禁止；所有 real observations 仍是 metadata-only research evidence。 |
| 使用旧 `main@61e6afc` evidence 直接证明当前 contract | No-Go | 旧 evidence 只能保留为 historical evidence。 |
| 让 model tool call 直接执行工具或改 UI | No-Go | Tool Executor / `TOOL_UI_STATE_PATCHED` owner boundary 必须保留。 |
| 让 Composer 自证 coverage/truthfulness | No-Go | 必须有独立 checker events。 |
| 把 webSearch/RAG 内容当 instruction | No-Go | 必须保持 `UNTRUSTED_WEB_EVIDENCE`。 |

## 14. human approval gates

必须 human 明确批准后才能做：

- merge / rebase / mainline sync 操作。
- 任意联网安装或依赖下载。
- 任意真实 provider call 或 API key 使用。
- 任意真实麦克风、播放设备、真实用户录音采集。
- 任意 generated audio、raw provider payload、raw trace、local replay cache 产生或保留策略变更。
- 任意 `src/voice_agent/`、`tests/`、`docs/adr/`、`docs/specs/` 修改。
- 任意 runtime adapter implementation。
- 任意真实 external write、payment、booking、deletion、external communication 或真实设备控制。
- 新增 MVP-relevant event name、RouterDecision、TaskFocus value、SlowTask state 或 scope expansion。

## Recommendation

当前结论是：继续 research hardening 和 mainline contract sync，不进入 MVP3 runtime integration。

最推荐的下一步是先做 `main@f325483` research-only sync addendum，再做 dry-run count reconciliation 和 MVP2 Tool Executor / Composer event mapping。这样后续 MVP3 planning 可以清楚地区分 historical evidence、current contract、synthetic boundary proof 和真正的 integration blockers。
