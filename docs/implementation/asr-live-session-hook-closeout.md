# ASR Live Session Hook Closeout

## Goal F Scope

Goal F added an explicit opt-in live session ASR hook over the Goal E ASR
runtime wrapper. The hook runs only after a committed audio turn and keeps ASR
as transcript/text projection evidence. It does not make ASR own turn ingress,
semantic close, assistant directedness, Router winner selection, SlowTask final
facts, confirmation, tool authorization, Composer behavior, Tool Executor
behavior, UI patching, or playback.

## Provider And Session Path

- provider: Alibaba Cloud Bailian / DashScope
- model alias: qwen3-asr-flash
- transport: adapter-internal direct_http
- approval packet: docs/implementation/asr-live-eval-approval-packet.md
- live session smoke entrypoint: scripts/asr-live-session-smoke
- session hook path: src/voice_agent/runtime/asr_session_hook.py
- explicit runtime mode: approved_real_live_eval
- default mode: provider_free
- credential handling: runtime environment only, read at adapter call-time

## Live Session Smoke Result

Final approved outbound live-session smoke ran with synthetic input only and
passed through the opt-in session hook:

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

An earlier sandboxed invocation emitted a metadata-only ADAPTER_REQUEST_FAILED
event with provider_request_failed before the approved outbound provider
request was allowed.

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

- ASR output enters the Event Journal through AsrRuntimeAdapter and AsrAdapterContract.
- ASR_TRANSCRIPT_OUTPUT_EMITTED is caused by TURN_INGRESS_COMMITTED.
- The session hook defaults to provider_free and does not call provider transport by default.
- The explicit live session mode uses injectable transport; tests use fake transport.
- Missing approval fails closed before transport call.
- Missing credential fails closed before transport call.
- Output refs are safe refs: asr_frame_ref and text_ref.
- audio_timestamps_ref is omitted because timestamp metadata is unavailable.
- Missing timestamps emit ADAPTER_OUTPUT_DEGRADED.
- Final-only streaming emits ADAPTER_OUTPUT_DEGRADED.
- Malformed or absent transcript emits ADAPTER_OUTPUT_VALIDATION_FAILED.
- Timeout and final request failures use ADAPTER_REQUEST_RETRYING and ADAPTER_REQUEST_FAILED.
- Replay remains provider-free and uses recorded refs and metadata only.
- Runtime startup and assembly do not provider-probe.
- No ADR change was made.
- No canonical event change was made.
