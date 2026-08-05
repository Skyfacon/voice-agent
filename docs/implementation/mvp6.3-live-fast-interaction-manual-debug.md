# MVP6.3 Live Fast Interaction Manual Debug Flow

## Status

Local-only manual debug instructions. Do not commit approval packets, raw audio,
provider request bodies, provider response bodies, local QA history, diagnostics,
secrets, or local replay cache.

## Acceptance Scenarios

- MVP6.3-LIVE-FAST-ANSWER-PASS-001
- MVP6.3-LIVE-QA-PARALLEL-001
- MVP6.3-LIVE-ASR-FAIL-ANSWER-PRESERVED-001
- MVP6.3-LIVE-FAST-TIMEOUT-FALLBACK-001
- MVP6.3-LIVE-SLOW-DISCARD-TEMPLATE-001
- MVP6.3-LIVE-PATCH-DISCARD-TEMPLATE-001
- MVP6.3-REPLAY-NO-PROVIDER-RERUN-001
- MVP6.3-SAFETY-EXPORT-001

## Approval Packet Shape

The complete debug-console QA profile uses two provider calls: parallel ASR
observation plus audio-native Fast Interaction. ASR supplies the displayed
Question; it does not feed Fast Interaction.

The request adapter IDs must exactly match the packet IDs. An older ASR +
Thinker packet cannot authorize this profile.

The provider-facing Fast Interaction model ID is `qwen3.5-omni-flash`; the
independent adapter role remains `fast_interaction` under ADR-017.

```json
{
  "approval_id": "mvp6.3-live-fast-interaction-local",
  "live_provider_opt_in": true,
  "local_wav_opt_in": true,
  "metadata_only_output": true,
  "replay_reruns_provider": false,
  "provider_adapter_ids": [
    "mvp5_asr_adapter",
    "mvp63_fast_interaction_runtime"
  ],
  "credential_env_var_name": "DASHSCOPE_API_KEY",
  "max_provider_calls": 2,
  "timeout_ms": 1500,
  "safe_output_ref": "summary://mvp6.3/live-fast-interaction/local"
}
```

For a fast-only latency isolation run, disable ASR observation and use only
`provider_adapter_ids=["mvp63_fast_interaction_runtime"]` with
`max_provider_calls=1`. That profile intentionally cannot display a real
Question transcript.

For an explicit ASR-text fallback run, use
`provider_adapter_ids=["mvp5_asr_adapter","mvp63_fast_interaction_runtime"]`
and `max_provider_calls=2`, and verify metadata labels
`fast_interaction_input_mode=asr_text_fallback`.

## Run

```bash
scripts/mvp6-debug-console --approval-packet outputs/mvp6-debug-console/mvp6.3-approval.json
```

Open `http://127.0.0.1:8766`.

## Expected Metadata

- `fast_interaction_output_mode=real|degraded|fallback`
- `fast_interaction_input_mode=audio_native`
- `asr_output_mode=real|degraded`
- `qa_status=complete|question_unavailable|answer_fallback|redacted|failed`
- `foreground_gate_decision=passed|failed|not_run`
- `foreground_output_basis=reply_candidate|template_ack|template_clarify|silence_policy`
- `fast_interaction_provider_http_ms`
- `fast_interaction_parse_validate_emit_ms`
- `fast_interaction_total_ms`
- `fast_interaction_timed_out`
- `fast_answer_ready_offset_ms`
- `qa_pair_ready_offset_ms`
- `provider_calls_parallel`
- `provider_calls_overlapped`
- `router_ms`
- `foreground_gate_ms`
- `foreground_output_finalize_ms`

Unavailable timing fields appear as `null`; they are not reported as zero.

## Safety Checks

The local response and explicitly enabled ignored QA history may include the
normalized ASR Question and runtime-approved displayed Answer. They must not
include raw audio, raw prompt, provider body, provider response, discarded
candidate text, local paths, credentials, authorization headers, diagnostics,
traces, or local replay cache. Committed/shareable artifacts must not include
unredacted real user input.

If the normalized Question or committed Answer resembles an API key, JWT,
authorization value, private key, or explicit credential assignment, the page
shows a redacted status and the original text is not written to QA history.

Deterministic replay must use recorded events and refs only. It must not rerun
ASR, Fast Interaction, Thinker, TTS, tools, or external providers.
