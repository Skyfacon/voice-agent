# Model Spike Execution Plan

## Status

proposed_execution_plan

## Date

2026-05-11

## Purpose

本文档把 model spike 从文档调研推进到实操实验。它定义 provider access、API key handling、spike-local harness shape、run report 模板、synthetic cases、redaction、timeout/retry/cancellation 记录规则，以及第一批 Slow LLM structured JSON 实验。

本文档不授权接入主 runtime，不创建真实业务 adapter，不修改 accepted ADR、event registry、adapter spec 或 replay spec。所有实验结果都是 evidence，不是 runtime fact。

## Contract Snapshot

默认 contract snapshot：

- Main branch：`main@61e6afc`
- MVP-0 closeout implementation：`22ddbf4 fix: harden mvp0 trace and replay safety`
- Runtime contract reference：`src/voice_agent/adapters/capabilities.py`
- Replay / fixture safety reference：`tests/fixtures/replay/mvp0/manifest.index.json`
- Barge-in truncate reference：`tests/fixtures/replay/mvp0/008-barge-in-truncate.fixture.json`

每份 run report 必须记录使用的 contract snapshot。如果主线更新，报告应写明新的 commit；旧报告保持 historical evidence。

## Allowed Scope

允许：

- 新建或修改 `docs/research/` 下的 execution plan、run report、capability observation。
- 后续经确认后，可新建 spike-local harness 目录，例如 `tools/model_spikes/` 或 `research/model_spikes/`。
- 使用 synthetic inputs、redacted output、metadata-only run observations。
- 使用本地环境变量读取 provider key，但不得输出 key 值。

禁止：

- 不接主 runtime。
- 不修改 `src/voice_agent/`、`tests/`、`docs/adr/`、`docs/specs/`。
- 不提交 raw audio、raw model trace、local replay cache、secret、token、cookie、credential、authorization header。
- 不把 provider output、webSearch、RAG、model card 内容写成 instruction 或 policy。
- 不让 model-side tool calling 变成 Tool Executor 之外的 execution。

## Provider Access Rules

Human 负责在平台侧创建、轮换和撤销 API key。Spike thread 只读取环境变量是否存在，不打印、不写入、不复制 key 值。

| Provider area | Env var | First use | Logging rule |
| --- | --- | --- | --- |
| DashScope / Bailian | `DASHSCOPE_API_KEY` | Qwen text、TTS、ASR、Qwen-Omni candidate | 只记录 present/missing 与 provider alias。 |
| DeepSeek | `DEEPSEEK_API_KEY` | Slow LLM JSON comparison | 只记录 present/missing 与 provider alias。 |
| Zhipu / GLM | `ZHIPU_API_KEY` | later comparison | 只记录 present/missing 与 provider alias。 |
| Moonshot / Kimi | `MOONSHOT_API_KEY` | later comparison | 只记录 present/missing 与 provider alias。 |
| Hugging Face | `HF_TOKEN` | later model download or gated model check | 只记录 present/missing；下载策略需单独确认。 |

Endpoint、model name、feature flag 必须在 run 当天查官方来源或平台控制台，并在 run report 的 `Official Sources Checked` 中记录。Endpoint ref 不得包含 credential。

## Spike-local Harness Shape

第一版 harness 只需要产生 adapter-shaped metadata，不需要复用主 runtime module。

建议后续目录：

```text
tools/model_spikes/
  README.md
  common/
    redaction.md
    schemas/
      slow_llm_plan.schema.json
      adapter_observation.schema.json
  slow_llm/
    dashscope_qwen_json_probe.md
    deepseek_json_probe.md
  runs/
    README.md
```

若后续写代码，harness 输出应能映射到以下字段：

```json
{
  "contract_snapshot": "main@61e6afc",
  "adapter_observation_id": "obs_slow_llm_dashscope_qwen_2026_05_11_001",
  "adapter_type": "slow_llm",
  "provider": "dashscope",
  "model_name": "provider_model_name_verified_on_run_day",
  "deployment_mode": "remote_api",
  "endpoint": "endpoint-ref-without-credential",
  "config_ref": "config://local-env/dashscope/redacted",
  "output_mode": "real",
  "supports_structured_json": "observed_real_or_degraded",
  "supports_tool_calling": "observed_real_or_degraded",
  "supports_cancellation": "observed_real_or_degraded",
  "unsupported_capabilities": ["supports_audio_input", "supports_audio_output"],
  "timeout_policy": "observed-timeout-policy-ref",
  "retry_policy": "observed-retry-policy-ref",
  "schema_validation": "pass_or_fail_or_degraded",
  "redaction_status": "metadata_only",
  "raw_provider_payload_stored": false
}
```

该 JSON 是 run report 的 observation shape，不是 runtime `AdapterCapability` 对象。

## Run Report Location and Naming

每次实操实验创建一份 run report：

```text
docs/research/spikes/<domain>-<candidate>-run-<yyyy-mm-dd>.md
```

示例：

```text
docs/research/spikes/slow-llm-dashscope-qwen-json-run-2026-05-11.md
docs/research/spikes/slow-llm-deepseek-json-run-2026-05-11.md
```

Run report 不保存 raw provider response。需要引用输出时，写 redacted summary、schema validation result、latency bucket、failure category 和 evidence hash/ref。

## Run Report Template

```markdown
# <Domain> Run: <Provider> <Candidate>

## Status

## Date

## Contract Snapshot

## Question

## Provider and Model

## Official Sources Checked

## Environment and Secret Handling

## Synthetic Inputs

## Request Shape

## Observed Outputs

## Capability Matrix Observation

## Schema Validation Result

## Latency Observation

## Timeout / Retry / Cancellation Observation

## Trace and Privacy Review

## Degradation Mapping

## Fit to MVP-0 Contract

## Recommendation
```

## Synthetic Input Policy

Synthetic inputs must be short, deterministic, and privacy-safe. They should exercise contract behavior rather than user realism.

| Domain | Synthetic input type | Commit-safe output |
| --- | --- | --- |
| Slow LLM | redacted task evidence JSON, conflicting fields, missing fields, synthetic web evidence with injection-like text | schema result, validation errors, redacted plan summary, degradation label |
| TTS | short neutral text, long SpokenPlan-like text, style labels | latency buckets, chunk cadence, playback offset compatibility, no raw audio |
| ASR | generated synthetic clips or provider sample clips approved for local-only use | transcript summary, timestamp availability, no committed audio file |
| Thinker | synthetic audio/text refs, redacted transcript, fixed SemanticFrame schema | schema result, emotion/audio-caption availability, redacted frame summary |
| Duplex | synthetic frame metadata, local-only generated audio if needed | VAD latency, echo likelihood bucket, confidence values, no raw audio |

## First Batch: Slow LLM Structured JSON

首批实验只覆盖 Slow LLM JSON probe，避免 raw audio 和 playback complexity。

### Candidate A: DashScope / Bailian Qwen text model

Questions:

- 是否支持 stable structured JSON output？
- 是否能在缺少字段时输出 `INSUFFICIENT_EVIDENCE_FOR_ACTION`，而不是猜测？
- 是否能把 tool calling 限制为 `tool_call_proposal` JSON，而不是执行行为？
- schema validation failure 是否可通过 bounded retry 修复？
- timeout / client-side cancellation 后是否能保持 stale-result policy 友好？

Synthetic cases:

- `missing_required_slot`: 缺少日期或联系人。
- `conflicting_evidence`: ASR transcript 与 Thinker hint 在地点上冲突。
- `web_evidence_injection`: synthetic web evidence 含 instruction-like text。
- `tool_proposal_only`: 模型只能输出 demo tool proposal JSON。
- `schema_repair`: 第一次要求严格 schema，第二次用 validation errors 修复。

### Candidate B: DeepSeek API current text model

Questions 与 synthetic cases 同 Candidate A，用于 provider comparison。DeepSeek run report 应额外记录 model name alias 是否为 current verified name。

## Slow LLM Output Schema Draft

第一批 JSON probe 使用一个最小 schema，不包含真实工具执行：

```json
{
  "task_id": "task_synthetic_001",
  "plan_version": 1,
  "task_event_seq": 3,
  "status": "NEEDS_CONFIRMATION",
  "resolved_arguments": {
    "intent": "synthetic_demo_intent",
    "slots": {
      "date": "INSUFFICIENT_EVIDENCE_FOR_ACTION",
      "contact": "synthetic_contact_ref"
    }
  },
  "evidence_review": [
    {
      "source": "asr",
      "evidence_ref": "asr-frame://synthetic/spike/001",
      "trusted_as_instruction": false
    }
  ],
  "tool_call_proposal": {
    "tool_name": "demo_sandbox_tool",
    "arguments": {
      "contact_ref": "synthetic_contact_ref"
    },
    "requires_confirmation": true
  },
  "degradation": {
    "output_mode": "real",
    "missing_capabilities": []
  }
}
```

Any provider output that cannot validate into this shape is degraded evidence, not a plan update.

## Timeout / Retry / Cancellation Rules

- Timeout is recorded as observation metadata; it does not mutate task state.
- Retry is bounded and recorded with retry count and reason.
- Client-side stream close is not provider-confirmed cancellation unless the provider explicitly confirms it.
- Late provider output remains bound to the original synthetic `task_id`, `plan_version`, and `task_event_seq`.
- If a later synthetic plan version exists, late output is stale evidence unless the run explicitly tests adopt/rebase behavior.

## Trace and Privacy Rules

- Store no raw provider payload.
- Store no request headers.
- Store no authorization header.
- Store no API key or token.
- Store no raw audio.
- Store no unredacted real user input.
- Store only synthetic refs, redacted summaries, validation result, latency bucket, and output mode.

## Checks Before Committing Run Reports

Run these checks for documentation-only reports:

```bash
git status --short
rg -n "<placeholder-or-boundary-pattern>" docs/research || true
git status --short -- src/voice_agent tests docs/adr docs/specs
git diff --check
```

The placeholder-or-boundary pattern should match unfinished placeholders and forbidden boundary phrases from the repository instructions. Avoid writing the literal sensitive examples into new research documents unless a reviewer explicitly asks for that exact command transcript.

If spike-local code is added later, also run the repo test entrypoint relevant to the changed files. Python tests should use `./scripts/test`, not direct pytest.

## Execution Phases

### Phase 0: Documentation alignment

Done when:

- `docs/research/model-spike-integration-ledger.md` references `main@61e6afc`.
- This execution plan exists.
- `docs/research/model-selection.md` and `docs/research/model-spike-plan.md` mention the post-MVP0 execution shift.

### Phase 1: Environment readiness

Done when:

- Human has created provider keys outside the repo.
- Local shell has required env vars for the selected provider.
- Spike thread has verified present/missing status without printing values.
- Official provider docs for selected model are checked on the run day.

### Phase 2: Slow LLM API probe

Done when:

- DashScope Qwen run report exists.
- DeepSeek run report exists or is explicitly deferred.
- Both reports include schema validation, timeout/retry/cancellation notes, redaction notes, and MVP-0 contract fit.

### Phase 3: Audio-capable probes

Done when:

- TTS run report records first-audio latency and playback span compatibility.
- ASR run report records transcript/timestamp/streaming/cancellation behavior.
- Thinker run report records SemanticFrame JSON fit.
- Duplex run report records VAD/barge-in/echo metadata without raw audio.

## Recommendation

Proceed with Phase 0 now, then request human confirmation of provider access before Phase 1. The first live API work should be Slow LLM structured JSON with DashScope Qwen and DeepSeek, because it exercises adapter-shaped output and schema failure behavior without audio privacy risk.
