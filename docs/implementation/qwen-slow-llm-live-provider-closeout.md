# Qwen Slow LLM Live Provider Closeout

## Goal

This closeout records merge readiness for the Qwen Slow LLM real provider
adapter readiness worktree. The worktree goal is to prove that Qwen can be used
behind the Slow LLM adapter boundary with approval-gated synthetic live eval,
safe validation, safe failure metadata, and no raw provider artifact retention.

This branch is not connected to business SlowTask runtime. It does not implement
SlowTask agentic loop behavior, runtime adapter selection for production
SlowTask, tool authorization, UI patching, Composer output, checker verdicts,
or playback.

## Completed Provider-Free Readiness Gates

- Credential handling uses opaque adapter-local handles and runtime-only secret
  values.
- Provider client and direct HTTP transport live only inside Qwen Slow LLM
  adapter code.
- Business modules do not import the Qwen live transport/client.
- Request binding carries `task_id`, `plan_version`, `observed_plan_version`,
  `interpreted_against_plan_version`, `task_event_seq`, `adapter_request_id`,
  and causal refs.
- Qwen evidence parsing accepts exactly one JSON object.
- Qwen evidence validation rejects task binding mismatch, ownership claims,
  boundary assertion failures, raw artifact retention, unsafe refs, and
  credential-like content.
- Timeout, retry, request failure, validation failure, and degraded paths map to
  existing canonical adapter events only.
- Valid output emits `SLOW_LLM_STRUCTURED_OUTPUT_EMITTED` only after
  validation, through `SlowLLMStructuredOutputContract` and
  `AdapterCallbackAppendBoundary`.
- Synthetic live eval gates fail closed for incomplete approval packets,
  placeholder model aliases, missing credential values, unsafe input fixtures,
  and over-budget request counts.

## Completed Live Provider Path

- Adapter transport: `direct_http_only`
- SDK dependency: no SDK import
- Model alias: `qwen3.6-plus`
- Endpoint:
  `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`
- Credential scope: adapter-internal call time only
- Synthetic input path:
  `tests/fixtures/synthetic/qwen-slow-llm-inputs.jsonl`
- Live eval entrypoint: `scripts/qwen-slow-llm-live-eval`
- Approval packet:
  `docs/implementation/qwen-slow-llm-live-provider-eval-approval-packet.md`

## Request Body Assumptions

The smoke eval profile uses the OpenAI-compatible chat completions shape:

- `response_format={"type":"json_object"}`
- `enable_thinking=false`
- `max_completion_tokens=800`
- `temperature=0`

`enable_thinking=false` is a synthetic smoke eval profile choice. It bounds
non-streaming latency while proving provider reachability, request construction,
response text extraction, parser/validator behavior, event boundary behavior,
and redacted summary behavior. It must not be treated as the business SlowTask
deliberative profile.

A future business SlowTask deliberative profile may intentionally use provider
thinking mode, a longer timeout budget, different output budget, or streaming
transport. That work belongs to a separate SlowTask agentic loop plan/worktree
and must preserve the existing adapter, Event Journal, Tool Executor, Composer,
Checker, Playback, and stale-result boundaries.

## Redacted Synthetic Live Eval Result

The latest approved synthetic live eval reached 3/3 validated outputs with
metadata-only reporting:

- request_count: 3
- success_count: 3
- validation_failed_count: 0
- retry_count: 0
- request_failed_count: 0
- timeout_count: 0
- raw_provider_body included: false
- raw_provider_request included: false
- raw_provider_response included: false
- headers included: false
- secret included: false

No raw provider request body, raw provider response body, headers,
Authorization value, Bearer value, SDK object, trace, diagnostic artifact,
secret, or real user input is part of this closeout.

## Qwen Output Authority Boundary

Qwen output remains an evidence candidate only:

- does not advance SlowTask
- does not authorize or execute tools
- does not patch UI
- does not generate SemanticCommitment
- does not generate SpokenPlan
- does not generate Checker verdict
- does not trigger playback

Only SlowTask may consume validated normalized evidence and decide whether any
current-plan state transition, stale-evidence adoption, tool path, commitment,
or user-facing progress event is allowed.

## Scope Boundaries

This closeout makes no ADR/spec change. It adds no new canonical event. It adds
no SDK import. It does not connect the adapter to business SlowTask runtime and
does not implement the SlowTask agentic loop.

Future SlowTask agentic loop work should be planned separately. That plan must
define the provider-neutral adapter selection seam, SlowTask-owned interpretation
of validated evidence, iteration limits, tool authorization handoff, Composer
handoff, replay fixtures, and live eval gates.

## Merge Readiness Checklist

- Qwen real provider path exists only behind adapter-internal direct HTTP
  transport.
- Approval-gated synthetic live eval has one successful redacted smoke result.
- Provider-free tests cover request body shape, credential safety, failure
  classification, validation failure, summary redaction, and no business-module
  direct transport import.
- Replay and acceptance remain provider-free and use only
  synthetic/redacted/minimal fixtures.
- No raw provider body, raw trace, diagnostics, local replay cache, raw audio,
  generated audio, secret, real user input, or large raw web content is committed.
- No new canonical event name is introduced.
- No ADR/spec change is included.
- No SDK import is introduced.
- Business SlowTask runtime integration is explicitly out of scope for this
  worktree.
