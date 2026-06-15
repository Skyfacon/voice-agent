# ASR Runtime Integration Closeout

## Goal E Scope

Goal E connected the approved ASR real transport path to an explicit runtime
wrapper and synthetic runtime smoke path. This is runtime integration only:
ASR remains transcript/text projection evidence and does not own turn ingress,
semantic close, assistant directedness, Router decisions, SlowTask facts,
confirmation, tool authorization, Composer behavior, Tool Executor behavior,
UI patching, or playback.

## Provider And Runtime Path

- provider: Alibaba Cloud Bailian / DashScope
- model alias: qwen3-asr-flash
- transport: adapter-internal direct_http
- approval packet: docs/implementation/asr-live-eval-approval-packet.md
- runtime smoke entrypoint: scripts/asr-runtime-smoke
- runtime mode: approved_real_live_eval
- default mode: provider_free
- credential handling: runtime environment only, read at adapter call-time

## Runtime Smoke Result

Final approved outbound runtime smoke ran with synthetic input only:

- attempted request count: 1
- success count: 1
- failure count: 0
- retry count: 0
- timeout count: 0
- validation failure count: 0
- failure category counts: none
- emitted event names: ADAPTER_OUTPUT_DEGRADED, ADAPTER_OUTPUT_DEGRADED, ASR_TRANSCRIPT_OUTPUT_EMITTED
- output mode: degraded
- degraded reason: timestamp metadata unavailable and streaming output unsupported_final_only
- output storage path: diagnostics/asr/live-eval
- cleanup status: delete_local_outputs_after_summary
- local output path exists after cleanup: false
- raw artifact absence confirmed: true

Two earlier sandboxed smoke invocations emitted metadata-only
ADAPTER_REQUEST_FAILED events with provider_request_failed while outbound
network access was restricted. The final approved outbound run above completed
after allowing the networked provider request.

## Artifact Safety

- raw audio included: false
- raw transcript included: false
- raw provider body included: false
- headers included: false
- secret included: false
- real user input included: false
- local trace committed: false
- local replay cache committed: false

No raw audio, raw transcript, provider request body, provider response body,
headers, Authorization value, secret, raw trace, local replay cache, real user
input, ADR change, canonical event change, provider SDK, or business-module
direct provider import is introduced.

## Boundary Checklist

- ASR output enters the Event Journal through AsrAdapterContract.
- ASR_TRANSCRIPT_OUTPUT_EMITTED is caused by TURN_INGRESS_COMMITTED.
- Output refs are safe refs: asr_frame_ref and text_ref.
- audio_timestamps_ref is omitted because timestamp metadata is unavailable.
- Missing timestamps emit ADAPTER_OUTPUT_DEGRADED.
- Final-only streaming emits ADAPTER_OUTPUT_DEGRADED.
- Replay remains provider-free and uses recorded refs and metadata only.
- Runtime startup and assembly do not provider-probe.
- No ADR change was made.
- No canonical event change was made.
