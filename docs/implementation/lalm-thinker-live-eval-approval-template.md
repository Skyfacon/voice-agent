# LALM Thinker Live Eval Approval Template

Status: template_only_no_live_eval_approval

Date: 2026-06-15

This packet is a human-review template for a future synthetic, metadata-only
LALM Thinker live eval. It is intentionally not approved by default.

## Purpose

Define the metadata that a human must review before any future LALM Thinker
live eval command can be considered for approval. The Goal C command only
checks this packet and reports gate status; it does not call a provider or
produce live eval results.

## Non-goals

- No provider call.
- No credential or environment secret read.
- No provider SDK dependency.
- No real provider transport.
- No live eval output generation.
- No runtime adapter event emission.
- No Router, SlowTask, Tool Executor, Composer, playback, ADR, or canonical
  event registry change.
- No production traffic.

## Required approval fields

The fail-closed command skeleton expects these fields in JSON or markdown
bullet form:

- approval_packet_schema: voice_agent.lalm_thinker.live_eval_approval.v1
- human_approved: false
- provider_model_alias: synthetic-lalm-thinker-model-alias-human-repin-required
- provider_model_alias_recheck_date: YYYY-MM-DD
- synthetic_input_set_ref: synthetic-input-set://lalm-thinker/metadata-only-v1
- synthetic_input_set_only: true
- cost_quota_time_budget: placeholder-minimal-budget-human-must-review
- max_request_count: 3
- per_request_timeout_ms: 30000
- retry_limit: 1
- output_location: outputs/lalm-thinker/live-eval/metadata-only
- output_location_policy: local_only_ignored
- cleanup_policy: delete local outputs after metadata summary review
- redaction_non_retention_policy: metadata only and no raw provider bodies retained
- forbidden_artifacts_acknowledged: false
- allowed_outputs: ['gate_status_metadata_only']
- fail_closed_behavior: block without complete human approval packet
- provider_native_tool_execution_allowed: false
- canonical_event_changes_allowed: false
- production_traffic_allowed: false

## Provider/model alias and recheck date

The provider/model alias must be a human-reviewed alias, not a cached or
unverified assumption. The recheck date must be filled in immediately before
Goal D work starts. Placeholder aliases, stale aliases, or aliases marked
`human-repin-required` must fail closed.

Do not place endpoint credentials, credential-bearing URLs, token values,
cookies, authorization headers, account identifiers, or provider request bodies
in this packet.

## Synthetic input set only

The approval scope is synthetic input only. The input set must be metadata-only,
minimal, and provider-neutral. It must not contain real user input, raw audio,
raw traces, prompt dumps, provider responses, provider-native tool payloads, or
large raw web content.

## Cost/quota/time budget

The packet must name a small request count, quota, and time budget that a human
has reviewed. These values are planning limits for a future Goal D approval;
Goal C does not spend quota or run the eval.

## Timeout/retry limits

The packet must set a per-request timeout and retry limit. The Goal C command
only validates that the limits are present and bounded as metadata. It does not
perform network retries.

## Output location and cleanup policy

The output location must be under an ignored local-only path approved for LALM
Thinker eval metadata, such as `outputs/lalm-thinker/` or
`diagnostics/lalm-thinker/`. The command must reject repo-tracked paths,
absolute paths, parent traversal, raw audio paths, trace paths, local replay
cache paths, and paths for other adapters.

The cleanup policy must explain how local-only outputs are deleted or reduced
after review. No output directory is created by Goal C.

## Redaction / non-retention policy

The packet must state that live eval processing, if separately approved later,
retains only aggregate metadata and safe refs. Provider bodies, prompts, raw
audio, raw traces, replay cache, secrets, and real user input must be discarded
or blocked before any artifact can be retained.

## Forbidden artifacts

This packet and any future eval artifacts must explicitly forbid:

- raw provider request / response body retention
- full prompt dump retention
- raw audio
- raw trace
- local replay cache committed
- secrets/tokens/cookies/credentials
- unredacted real user input
- provider-native tool execution
- canonical event changes
- production traffic
- provider SDK objects
- provider schemas
- raw SemanticFrame JSON
- raw summaries
- raw tool-call arguments
- credential-bearing endpoints or config refs

## Allowed outputs

For Goal C, the only allowed output is command-line gate status metadata:
`gate_status_metadata_only`.

A future Goal D approval may separately allow redacted aggregate metadata
summaries or synthetic fixtures, but only after explicit human approval. This
template does not grant that approval.

## Fail-closed behavior

The command must return a non-zero exit when approval is missing, malformed,
incomplete, not human-approved, stale, unsafe, credential-like, or points to an
unsafe output location. Error messages must report safe categories and failure
refs only. They must not echo raw approval content, secrets, provider payloads,
prompt text, or output path contents.

The command must not call a provider, read environment secrets, import provider
SDKs, invoke real or future transport, create output files, emit runtime adapter
events, or generate live eval results.

## Human approval checklist

- Confirm the provider/model alias has been rechecked on the stated date.
- Confirm the input set is synthetic and metadata-only.
- Confirm the cost, quota, request count, timeout, and retry budget are small
  and intentionally approved.
- Confirm output location is ignored local-only LALM Thinker metadata storage.
- Confirm cleanup policy is acceptable.
- Confirm redaction and non-retention policy forbids raw bodies, prompts, raw
  audio, raw traces, replay cache, secrets, and real user input.
- Confirm provider-native tool execution is forbidden.
- Confirm no canonical event, ADR, Router, SlowTask, Tool Executor, Composer,
  or playback ownership change is included.
- Set `forbidden_artifacts_acknowledged: true` only after checking the
  forbidden artifact list.
- Set `human_approved: true` only for the exact future command invocation and
  budget being approved.

## Template approval status

This template does not approve live eval by itself. It is a packet shape and
review checklist only. Goal D still requires separate explicit human approval
before any real transport, credential handle, provider call, or metadata-only
synthetic live eval may be attempted.
