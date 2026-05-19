# Model Spike Integration Ledger

## Status

coordination_ledger

## Purpose

本文档用于对齐两条并行 worktree：

- 主线 contract：MVP-0 已实现 live-loop mock/replay spine；MVP-1 已完成 SlowTask / UserPatch / plan_version / stale evidence / confirmation mock/replay closeout；MVP-2 已进入 demo tools、Tool Executor、UI patch、Composer/checker 的 acceptance skeleton 阶段。
- Model spike research：验证真实或可自部署模型是否能够被压缩进主线 adapter contract，并产出 evidence、capability matrix、degradation proposal 与 integration risk。

本 ledger 不是 runtime implementation plan，不授权接入真实 provider，不改变 ADR、event registry、adapter spec 或 MVP scope。它只回答一个问题：以当前已完成或已开工的主线 contract shape 为准，model spike 需要提供哪些证据，后续 MVP-3 才能接得上。

## Contract Sources

- `AGENTS.md`
- `docs/implementation/mvp0-backlog.md`
- `docs/implementation/mvp1-backlog.md`
- `docs/implementation/mvp1-to-mvp2-handoff.md`
- `docs/implementation/mvp2-backlog.md`
- `docs/research/model-spike-plan.md`
- `docs/research/model-selection.md`
- `docs/specs/model-adapter-capabilities.md`
- `docs/specs/event-registry.md`
- `docs/specs/replay-spec.md`
- `docs/adr/ADR-001 Duplex Boundary and Interaction Controller.md`
- `docs/adr/ADR-003 Barge-in and TTS Truncate Contract.md`
- `docs/adr/ADR-008 ASR Thinker Evidence Fusion and SlowTask-led Conflict Resolution.md`
- `docs/adr/ADR-009 SemanticCommitment and Thinker-as-Composer Contract.md`
- `docs/adr/ADR-011 Model Adapter Capability Contract.md`
- `docs/adr/ADR-012 MVP Vertical Slice and Development SLOs.md`
- `docs/adr/ADR-014 webSearch Evidence Boundary for Demo Tools.md`
- `docs/adr/ADR-016 SlowTask Lifecycle and Confirmation State Contract.md`

如这些文档冲突，按 `AGENTS.md`、accepted ADR、`stage_b_adr_register.md` 优先。

## MVP-0 Contract Snapshot

当前对齐基线：

- Main branch snapshot：`main@61e6afc`。
- MVP-0 closeout implementation：`22ddbf4 fix: harden mvp0 trace and replay safety`。
- Mainline status document：`docs/implementation/mvp0-backlog.md` 已记录 MVP-0 Slice 0-9 完成。
- 主线 closeout 记录：`./scripts/test -q` 在 2026-05-10 通过 139 tests。

因此 model spike 的阶段已经从 “等待 MVP-0 contract 成型” 切换为 “按主线 contract 产出 adapter-shaped evidence”。2026-05-11 / 2026-05-12 的 run report 默认使用 `main@61e6afc`；2026-05-17 之后的新报告默认使用 `main@ac1b43f` 或更新的主线 commit。

## 2026-05-17 Mainline Sync

主线程已经完成 MVP-1 closeout 并进入 MVP-2 开工阶段。新的 research 对齐入口是：

- Sync addendum：`docs/research/model-spike-mainline-sync-2026-05-17.md`
- Current observed main：`main@ac1b43f`
- MVP-1 closeout doc commit：`4dea276 Document MVP-1 closeout architecture status`
- MVP-1 closeout merge reference：`2f3b359 Merge pull request #17 from Skyfacon/mvp1/slice10-acceptance-closeout`
- MVP-2 replay safety merge reference：`ac1b43f Merge pull request #19 from Skyfacon/mvp2/slice0-replay-safety`

Interpretation:

- Existing 2026-05-11 / 2026-05-12 run reports remain historical evidence against `main@61e6afc`.
- New model-spike reports should use `main@ac1b43f` or newer unless intentionally preserving a historical snapshot.
- Any task-bound model evidence must now align with MVP-1 closeout required fields, especially `task_id`, `plan_version`, `task_event_seq`, `observed_plan_version`, stale marking, stale adoption, confirmation state, and terminal stickiness.
- MVP-2 has acceptance skeleton and scope gates, but at `main@ac1b43f` real Tool Executor runtime, demo backend, frontend UI patching, Composer runtime, coverage checks, and progress truthfulness checks are not yet integration proof.
- This sync does not authorize runtime adapter implementation or provider integration.

当前实装 contract 中需要 model spike 特别贴合的字段包括：

- Capability matrix identity：`adapter_id`、`adapter_type`、`provider`、`model_name`、`deployment_mode`、`endpoint`、`health_status`、`capability_version`、`latency_class`、`error_model`、`timeout_policy`、`retry_policy`、`output_mode`、`config_ref`。
- Capability booleans：`supports_streaming_input`、`supports_streaming_output`、`supports_audio_input`、`supports_audio_output`、`supports_audio_timestamps`、`supports_structured_json`、`supports_tool_calling`、`supports_cancellation`、`supports_emotion`、`supports_audio_caption`、`supports_tts`、`supports_tts_truncate`、`supports_tts_pause_resume`、`supports_semantic_close`、`supports_assistant_directedness`。
- Numeric limits：`max_audio_seconds`、`max_context_tokens`、`max_output_tokens`、`expected_first_token_latency_ms`、`expected_first_audio_latency_ms`。
- Mock/profile bookkeeping：`mocked`、`mock_profile_ref`、`target_architecture_validation`、`unsupported_capabilities`。Real provider spike profiles should use equivalent profile bookkeeping in run reports even if they are not runtime `AdapterCapability` objects yet.
- MVP-0 event metadata refs：`asr_frame_ref`、`semantic_frame_ref`、`audio_ref`、`tts_stream_ref`、`playback_reference_ref`、`playback_span_id`、`audio_span_id`、`turn_id`、`utterance_id`、`output_mode`。
- MVP-1 task-bound refs：`task_id`、`plan_version`、`observed_plan_version`、`task_event_seq`、`patch_id`、`tool_call_id`、`confirmation_id`、`commitment_id`、stale/adoption source refs。
- MVP-2 proposal / speech refs：`tool_call_id`、`idempotency_key`、`resolved_arguments_ref`、`provenance_ref`、`ui_patch_id`、`patch_ref`、`spoken_plan_id`、`source_commitment_id`、`source_progress_event_ids`、coverage/truthfulness check refs。

## Current Research Baseline

当前 research worktree 已有以下 model spike baseline：

- `docs/research/spikes/duplex-capability-spike-2026-05-09.md`
- `docs/research/spikes/asr-capability-spike-2026-05-09.md`
- `docs/research/spikes/tts-capability-spike-2026-05-09.md`
- `docs/research/spikes/thinker-capability-spike-2026-05-09.md`
- `docs/research/spikes/slow-llm-capability-spike-2026-05-09.md`
- `docs/research/model-selection.md`

这些文档目前是 evidence research，不是 adapter profile，也不是 integration approval。它们提供 candidate shortlist 与初始 risk map；新的后续实验应使用 2026-05-17 sync 后的主线 contract shape，通过 spike-local experiments 产生 observed capability，同时保留旧 evidence 的历史 snapshot。

## 2026-05-12 Research Refresh

2026-05-12 的 model-spike lane 已从单份 run report 扩展到 repeatable spike-local dry-run eval shape。新增或刷新后的 research artifacts 包括：

- `docs/research/model-spike-phase-summary-2026-05-12.md`
- `docs/research/model-spike-adapter-profile-hardening-checklist-2026-05-12.md`
- `docs/research/profiles/slow-llm-qwen-profile-hardening-addendum-2026-05-12.md`
- `docs/research/profiles/tts-cosyvoice-profile-hardening-addendum-2026-05-12.md`
- `docs/research/profiles/asr-qwen-asr-profile-hardening-addendum-2026-05-12.md`
- `docs/research/profiles/thinker-qwen-omni-profile-hardening-addendum-2026-05-12.md`
- `docs/research/profiles/thinker-as-composer-boundary-hardening-addendum-2026-05-12.md`
- `tools/model_spikes/asr_streaming_eval/`
- `tools/model_spikes/tts_playback_eval/`
- `tools/model_spikes/slow_llm_retry_eval/`
- `tools/model_spikes/thinker_composer_eval/`
- `docs/research/spikes/asr-qwen-asr-streaming-eval-dry-run-2026-05-12.md`
- `docs/research/spikes/tts-cosyvoice-playback-eval-dry-run-2026-05-12.md`
- `docs/research/spikes/slow-llm-retry-eval-dry-run-2026-05-12.md`
- `docs/research/spikes/thinker-composer-boundary-eval-dry-run-2026-05-12.md`

Fresh full-synthetic dry-run counts:

| harness | observations | validation | provider calls | runtime imports | notes |
| --- | ---: | --- | --- | --- | --- |
| ASR streaming eval | 23 | pass | false | false | transcript, timestamp, realtime gap, cancellation, late transcript, semantic-truth boundary. |
| TTS playback eval | 20 | pass | false | false | synthesis, streaming audio, playback progress, truncate shape, client close, local stop, late/partial audio. |
| Slow LLM retry eval | 21 | pass | false | false | schema validation, repair, timeout, retry, stale, tool proposal, web evidence, context degradation. |
| Thinker / Composer eval | 22 | pass | false | false | SemanticFrame, evidence separation, Composer coverage/truthfulness boundary, semantic close/directedness unknown. |

This refresh changes Gate 1 from `mostly pass` to pass for ASR/TTS/Slow LLM/Thinker spike-local eval readiness. It does not change Gate 3: MVP-3 integration consideration remains not ready because real adapter implementation, runtime owner-boundary tests, provider health/error policy, and replay/eval fixtures are not yet approved or implemented.

The adapter profile hardening checklist is now the research entry gate for moving profile drafts toward MVP-3 consideration. It has been applied to Slow LLM Qwen, TTS CosyVoice, ASR Qwen-ASR, Thinker Qwen-Omni, and the focused Thinker-as-Composer boundary. The recommended next work item is Duplex/VAD local harness work if the next focus is realtime ingress proof, or a consolidated MVP-3 readiness gap review if the focus is integration planning.

Boundary conclusions to carry forward:

- Model outputs are evidence, not hidden control flow.
- ASR, Thinker, Slow LLM, TTS, and Duplex/VAD do not own Interaction Controller, Router, SlowTask, Tool Executor, Talker playback, or Event Journal state transitions.
- `PLAYBACK_COMMITTED` is not user acknowledgement.
- `TTS_TRUNCATED` requires Talker/playback-confirmed stop metadata, not provider stream close or client abort.
- Deterministic replay consumes recorded metadata or synthetic fixtures and does not rerun real providers.

## Mainline Sync Points

MVP-0 / MVP-1 已完成，MVP-2 已开始。因此以下同步点现在都可作为 spike run 的 contract input：

| Sync point | 主线来源 | 当前状态 | spike 使用方式 |
| --- | --- | --- | --- |
| Capability snapshot shape | MVP-0 Slice 2 / `src/voice_agent/adapters/capabilities.py` / `docs/specs/model-adapter-capabilities.md` | 已实现 | 确认 spike result 是否能填满 required capability fields，并显式列出 `unsupported_capabilities`。 |
| Audio ingress and Duplex evidence shape | MVP-0 Slice 5 / `src/voice_agent/duplex/mock_duplex.py` | 已实现 | 对齐 VAD、speech_start、speech_end、audio span refs、raw audio exclusion。 |
| Mock ASR/Thinker frame shape | MVP-0 Slice 6 / `src/voice_agent/understanding/` | 已实现 | 对齐 transcript evidence、SemanticFrame evidence、Router 之前/之后的 causal order。 |
| Playback span and progress shape | MVP-0 Slice 7 / `src/voice_agent/talker/mock_talker.py` | 已实现 | 对齐 TTS span id、playback offset、first audio latency、progress metadata。 |
| Barge-in truncate shape | MVP-0 Slice 8 / `tests/fixtures/replay/mvp0/008-barge-in-truncate.fixture.json` | 已实现 | 对齐 `BARGE_IN_CANDIDATE`、`TTS_TRUNCATE_REQUESTED`、`TTS_TRUNCATED` 与 offset semantics。 |
| Acceptance fixture conventions | MVP-0 Slice 9 / `tests/fixtures/replay/mvp0/manifest.index.json` | 已实现 | 将 spike observations 转为 synthetic/redacted replay or eval evidence，而不是 raw trace。 |
| MVP-1 SlowTask / UserPatch / stale evidence contract | MVP-1 closeout / `docs/implementation/mvp1-backlog.md` / `docs/specs/mvp1-acceptance-scenarios.md` on `main@ac1b43f` | 已实现 | Slow LLM、Thinker、ASR、Composer 相关 task-bound evidence 必须绑定 current/observed plan、`task_event_seq`、stale/adoption metadata 和 terminal late-result policy。 |
| MVP-1 event registry refinements | `docs/specs/event-registry.md` on `main@ac1b43f` | 已实现 | `USER_PATCH_INTERPRETED`、`PLAN_VERSION_ADVANCED`、`TOOL_RESULT_MARKED_STALE`、`STALE_EVIDENCE_RECORDED` 必须使用 closeout 后 required fields。 |
| MVP-2 tool/composer acceptance skeleton | `docs/implementation/mvp2-backlog.md` / `docs/specs/mvp2-acceptance-scenarios.md` / `tests/fixtures/replay/mvp2/manifest.index.json` on `main@ac1b43f` | 已开工，runtime 未证明 | Tool-like model output 只能是 proposal；Composer output 只能是 SpokenPlan draft；webSearch 必须是 `UNTRUSTED_WEB_EVIDENCE`。 |

每次 spike run report 应记录它参考的主线 commit 或 contract snapshot 日期。若主线 contract 变化，旧 spike result 保持历史 evidence，不自动升级为当前可集成事实。

## MVP-0 Slice to Model Spike Ledger

| MVP-0 slice | 主线产物 | spike 需要提供的 evidence | 是否阻塞 MVP-0 | 未来融合点 |
| --- | --- | --- | --- | --- |
| Slice 0: Repo Safety and Runtime Skeleton | `.gitignore`、fixture safety、local artifact boundary | 确认 spike code/report 不提交 raw audio、raw trace、secret、credential、unredacted real user input。 | 不阻塞 | Spike run artifact policy 与 repo safety 对齐。 |
| Slice 1: Event Envelope and Append-Only Journal | event envelope、per-session `event_seq`、journal validation | 确认 model output metadata 可引用 event ids、request ids、redacted refs，而不需要 raw provider payload。 | 不阻塞 | Adapter event metadata 与 journal envelope 对齐。 |
| Slice 2: Capability Snapshot and Mock Adapter Contracts | mock adapter capability matrices、`ADAPTER_CAPABILITY_SNAPSHOT_RECORDED` | 每个候选模型能否填充 required capability fields；不能填充的字段标 `unknown`、`degraded`、`unsupported` 或 `fallback`。 | 不阻塞 | 后续 `adapter-capability-profiles` 与 MVP-3 healthcheck。 |
| Slice 3: Deterministic State Reducers and Replay Core | deterministic replay、state digest、no model rerun | 确认 spike result 可转换为 replay-safe metadata；真实模型不得在 replay 中重跑。 | 不阻塞 | Spike run report 转 synthetic fixture 或 eval assertion。 |
| Slice 4: Text Ingress Through Interaction Controller | text ingress、turn open/accept/commit、assumed directedness | Slow LLM / Thinker text-only fallback 是否能消费 redacted text evidence；web/RAG evidence 不进入 instruction area。 | 不阻塞 | Text-only degraded path 与 SlowTask/Thinker fallback。 |
| Slice 5: Audio Span and Duplex Mock Accept Path | audio span、mock/rule speech start/end、turn commit | VAD speech_start latency、speech_end hangover、audio refs、semantic_close/assistant-directedness degradation。 | 不阻塞 | MVP-3 Duplex/VAD adapter candidate。 |
| Slice 6: Mock Understanding and Router FAST_ONLY Skeleton | mock ASR frame、mock Thinker frame、Router decision | ASR partial/final transcript、timestamp、confidence；Thinker SemanticFrame JSON、emotion/audio caption hints。 | 不阻塞 | ASR/Thinker real adapter replacement after MVP-3 gate。 |
| Slice 7: Mock Talker Playback Progress and Delivery Markers | playback span、progress、commit marker | TTS first-audio latency、stream chunk cadence、span id compatibility、audio output mode。 | 不阻塞 | TTS adapter plus Talker playback integration. |
| Slice 8: Barge-in Candidate to Truncate Flow | barge-in candidate、interrupt candidate、truncate request、truncate confirmation | Duplex VAD/AEC latency、echo likelihood、TTS playback stop offset accuracy、model request cancellation limits。 | 不阻塞，但强相关 | ADR-003 target-valid truncate evidence. |
| Slice 9: MVP-0 Replay Fixtures and Acceptance Runner | acceptance fixtures、scenario assertions | 将 spike observations 精炼为 synthetic/redacted eval cases；确认 no raw artifacts。 | 不阻塞 | MVP-3 pre-integration eval suite. |

## Model Capability Evidence Dependencies

| Model area | 依赖的主线 contract | spike evidence 输出 | 当前时机 |
| --- | --- | --- | --- |
| Duplex / VAD | Slice 5、Slice 8 | speech_start latency、barge-in latency、echo likelihood、directedness/semantic_close degradation。 | 现在可按 MVP-0 audio/barge-in metadata 做实验设计。 |
| ASR | Slice 2、Slice 6 | final/partial transcript、timestamps、streaming support、cancellation/stale policy。 | 现在可按 `MOCK_ASR_FRAME_EMITTED` refs 设计 adapter-shaped output。 |
| TTS / Talker | Slice 2、Slice 7、Slice 8 | first audio latency、streaming output、playback span compatibility、truncate compatibility。 | 现在可按 playback span / truncate offsets 做实验设计。 |
| Thinker | Slice 2、Slice 6 | SemanticFrame JSON validity、emotion、audio caption、assistant-directedness、Composer role risk。 | 现在可按 `MOCK_THINKER_FRAME_EMITTED` refs 设计 SemanticFrame output。 |
| Slow LLM | Slice 2；MVP-1 SlowTask contracts；MVP-2 tool proposal boundary | structured JSON validity、schema retry、tool proposal normalization、`plan_version` / `task_event_seq` stale behavior。 | MVP-1 contract 已补齐；后续 Slow LLM eval 必须按 `main@ac1b43f` 的 closeout required fields 复核。 |
| Embedding / RAG | ADR-014；后续 evidence boundary | source attribution、untrusted evidence labeling、redaction、timeout/cancellation。 | 不阻塞 MVP-0；等 evidence boundary 更稳后。 |

## Integration Gates

### Gate 0: Research-only readiness

通过条件：

- Worktree 在 `research/model-spikes`。
- Spike 文档只写入 `docs/research/` 或明确批准的 spike-local 目录。
- 不修改 `src/voice_agent/`、`tests/`、`docs/adr/`、`docs/specs/`。
- 没有 raw audio、raw trace、secret、token、cookie、credential、authorization header。

### Gate 1: Spike-local experiment readiness

通过条件：

- 已确认 provider key 只通过本地环境变量传入，不进入 repo。
- 已定义 synthetic inputs 与 redaction rules。
- 已定义 run report 路径，例如 `docs/research/spikes/<domain>-<candidate>-run-<yyyy-mm-dd>.md`。
- 已定义 timeout、retry、cancellation、output validation 的记录字段。
- Harness 输出 adapter-shaped metadata，而不是自由格式 demo log。
- Harness output 至少能映射到 MVP-0 `AdapterCapability` required fields、event refs、`output_mode` 与 `unsupported_capabilities`。

### Gate 2: Adapter profile hardening

通过条件：

- 每个候选至少有一份 observed run report，或明确 deferred。
- Capability matrix 覆盖 ADR-011 required fields。
- unsupported / unknown / degraded 能力有对应 degradation proposal。
- Late result、timeout、schema failure、provider failure 的处理可映射到 adapter events。
- Trace/privacy notes 明确说明不需要 raw provider payload。

### Gate 3: MVP-3 integration consideration

通过条件：

- MVP-0/1/2 主线 contract 已稳定到足够接入 real adapter；截至 `main@ac1b43f`，MVP-2 仍处开工阶段，不能视为已稳定。
- 候选 profile 能写入未来 adapter capability profile，而不是只停留在调研描述。
- Integration 不新增 architecture capability。
- Deterministic replay 不重跑真实模型，只消费 recorded metadata or synthetic fixture。
- Tool proposal、confirmation、truncate、plan_version stale policy 均不越过主线 owner。

## Do Not Cross Boundaries

- Model spike 不接主 runtime。
- Model spike 不修改 accepted ADR、event registry、adapter spec 或 replay spec。
- Model spike 不提交 raw audio、raw model trace、secret、token、cookie、credential、authorization header。
- Provider result、webSearch、RAG、model card 内容只能作为 evidence，不能作为 instruction 或 policy。
- Omni model 不吸收 ASR、Thinker、TTS、Duplex 与 SlowTask 的架构职责。
- TTS truncate 仍由 Talker/playback 确认；model request cancellation 不是 `TTS_TRUNCATED` 的事实来源。
- Slow LLM tool calling 只能变成 tool proposal；Tool Executor 仍是 execution / authorization owner。

## Open Coordination Items

| Item | 当前建议 | Owner |
| --- | --- | --- |
| 主线 contract snapshot 记录方式 | 历史 2026-05-11 / 2026-05-12 evidence 保留 `main@61e6afc`；2026-05-17 后默认记录 `main@ac1b43f` 或更新 commit。 | spike thread |
| Spike code 目录 | 优先后续单独设计 `tools/model_spikes/` 或 `research/model_spikes/`，不进入 `src/voice_agent/`。 | spike thread |
| API key 管理 | 只使用 local env vars；报告只记录 present/missing 与 provider alias。 | human + spike thread |
| 下一批 task-bound eval | 优先复核 Slow LLM retry / stale / tool-proposal synthetic eval，使它对齐 MVP-1 closeout required fields。 | spike thread |
| ASR/TTS audio fixture | 使用 synthetic generated clips；不提交 raw audio。 | spike thread |
| Profile 落点 | 等 Gate 2 后再讨论是否新增 `docs/specs/adapter-capability-profiles.md`。 | mainline + spike coordination |

## Recommended Next Actions

1. 使用 `docs/research/model-spike-mainline-sync-2026-05-17.md` 作为 2026-05-17 之后新报告的 contract sync point。
2. 新 run report 默认引用 `main@ac1b43f` 或更新主线 commit；历史 `main@61e6afc` evidence 保持历史标签，不自动升级。
3. 优先复核 Slow LLM retry / stale / tool-proposal synthetic eval，使其对齐 MVP-1 closeout required fields。
4. 第二优先复核 Thinker-as-Composer boundary eval，使其对齐 MVP-2 `SPOKEN_PLAN_EMITTED`、coverage check、progress truthfulness、playback gating scenarios。
5. Duplex/VAD realtime ingress proof 可继续按现有计划推进，因为 MVP-1 对它影响较小；但 barge-in 到 truncate 的 owner-chain 仍必须保持 Duplex evidence -> Interaction request -> Talker confirmation。
6. 继续禁止 runtime adapter implementation、真实 provider 接入、真实设备采集和 raw artifact 提交，除非另开 MVP-3 integration thread 明确批准。

## Recommendation

两条 worktree 的融合方式应是：主线产出 contract shape，model spike 产出 observed evidence，双方通过 adapter capability matrix、run report 与 integration gates 对齐。短期内，本 ledger 是对账本；中期产出 adapter profile draft；长期在 MVP-3 integration branch 中逐个接入真实 adapter。
