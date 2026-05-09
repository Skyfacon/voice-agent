# Thinker Capability Spike

## Status

evidence_report

## Date

2026-05-09

## Scope

This report evaluates audio semantic frame candidates for Thinker-style evidence: audio understanding, emotion, audio captioning, semantic close, assistant-directedness hints, and structured output. It also reviews whether omni/audio models should be used as Thinker-as-Fast-System or Thinker-as-Composer.

## Architecture Role

Thinker produces SemanticFrame-style evidence from audio/text context. It can help interpret user intent, emotion, assistant-directedness, uncertainty, and semantic completeness. It must not own turn ingress commit, final SlowTask facts, tool authorization, or playback truncate policy.

## ADR Constraints

- ADR-001: Interaction Controller owns turn ingress; Thinker evidence cannot commit a turn by itself.
- ADR-008: Thinker evidence is fused with ASR evidence; conflict resolution is SlowTask-led.
- ADR-009: Thinker-as-Composer may realize speech but cannot rewrite immutable facts, required fields, resolved arguments, tool status, risk warnings, or confirmation state.
- ADR-011: any audio/omni model must be behind an adapter with a declared capability matrix.
- ADR-016: SlowTask owns confirmation state and final plan/fact evolution.

## Candidate Shortlist

- Qwen3-Omni: primary candidate for multimodal audio understanding and audio captioning; official project exposes Thinker/Talker architecture, multilingual audio, and DashScope API path.
- Qwen2.5-Omni: fallback/earlier Qwen omni candidate with end-to-end multimodal input and streaming text/speech output.
- MiniCPM-o 2.6 / current MiniCPM-o family: local/A100 exploration candidate for full-duplex multimodal interaction; current official materials emphasize MiniCPM-o 4.5 while preserving 2.6 lineage.
- GLM-4-Voice: speech-dialogue candidate with Chinese/English speech understanding and generation; useful for voice-style experiments.
- Ultravox: audio-to-text multimodal LLM candidate for realtime voice understanding where text output is enough.
- Moshi and VITA-Audio: supplemental spoken-dialogue research candidates, not first MVP-3 Thinker picks.

## Official Sources Checked

- Qwen3-Omni GitHub: https://github.com/QwenLM/Qwen3-Omni
- Qwen2.5-Omni GitHub: https://github.com/QwenLM/Qwen2.5-Omni
- MiniCPM-o GitHub: https://github.com/OpenBMB/MiniCPM-o
- GLM-4-Voice GitHub: https://github.com/THUDM/GLM-4-Voice
- Ultravox GitHub: https://github.com/fixie-ai/ultravox
- Moshi GitHub: https://github.com/kyutai-labs/moshi
- VITA GitHub: https://github.com/VITA-MLLM/VITA
- Qwen Omni API documentation linked from official Qwen repositories: https://help.aliyun.com/zh/model-studio/user-guide/qwen-omni

## Capability Matrix Assessment

| field | Qwen3-Omni | Qwen2.5-Omni | MiniCPM-o family | GLM-4-Voice | Ultravox | Moshi / VITA |
| --- | --- | --- | --- | --- | --- | --- |
| adapter_type | thinker | thinker | thinker | thinker | thinker | thinker |
| provider | Qwen / Alibaba | Qwen / Alibaba | OpenBMB | THUDM | Fixie | Kyutai / VITA |
| model_name | Qwen3-Omni | Qwen2.5-Omni | MiniCPM-o-2.6_or_4.5 | GLM-4-Voice | Ultravox | Moshi_or_VITA |
| deployment_mode | api_or_self_hosted | api_or_self_hosted | self_hosted | self_hosted | api_or_self_hosted | self_hosted |
| supports_streaming_input | real | real | real | real | real | real |
| supports_streaming_output | real | real | real | degraded | real | real |
| supports_audio_input | real | real | real | real | real | real |
| supports_audio_output | real | real | real | real | unsupported | real |
| supports_audio_timestamps | unknown | unknown | unknown | unknown | unknown | unknown |
| supports_structured_json | degraded | degraded | degraded | degraded | degraded | degraded |
| supports_tool_calling | unknown | unknown | unknown | unknown | unknown | unknown |
| supports_cancellation | degraded | degraded | degraded | degraded | degraded | degraded |
| supports_emotion | degraded | degraded | degraded | real | unknown | degraded |
| supports_audio_caption | real | degraded | unknown | unknown | unknown | unknown |
| supports_tts | real | real | real | real | unsupported | real |
| supports_tts_truncate | unsupported | unsupported | unsupported | unsupported | unsupported | unsupported |
| supports_tts_pause_resume | unsupported | unsupported | unsupported | unsupported | unsupported | unsupported |
| supports_semantic_close | degraded | degraded | degraded | degraded | degraded | degraded |
| supports_assistant_directedness | degraded | degraded | degraded | degraded | degraded | degraded |
| max_audio_seconds | unknown | unknown | unknown | unknown | unknown | unknown |
| max_context_tokens | unknown | unknown | unknown | unknown | model_dependent_unknown | unknown |
| max_output_tokens | unknown | unknown | unknown | unknown | model_dependent_unknown | unknown |
| expected_first_token_latency_ms | unknown | unknown | unknown | unknown | unknown | unknown |
| expected_first_audio_latency_ms | unknown | unknown | unknown | unknown | not_applicable | degraded |
| output_mode | real_or_degraded | fallback | degraded | degraded | fallback | degraded |
| degradation_notes | best primary candidate, but JSON stability requires harness | good fallback; older capability envelope | promising local path, but current 4.5 docs note speech-output instability and hardware needs | strong speech style evidence, but less aligned with JSON SemanticFrame | text-only output can still produce SemanticFrame evidence | useful research; not first adapter candidate |

## Candidate Comparison

Qwen3-Omni is the strongest primary Thinker candidate because its official materials emphasize audio/video/text understanding, audio captioning, streaming, and a Thinker/Talker separation that maps naturally to this project’s role split. Qwen2.5-Omni is a credible fallback with similar architecture but older capability claims.

MiniCPM-o is attractive for self-hosted full-duplex research, especially on A100-class hardware, but official current materials also warn about instability and demo latency constraints. GLM-4-Voice is useful for expressive speech-dialogue experiments, but Thinker needs stable semantic evidence more than speech generation. Ultravox is compelling where audio input to streaming text is enough. Moshi and VITA are important comparison points for full-duplex interaction but should not be the initial MVP-3 Thinker adapter.

## Recommended MVP Usage

Use Qwen3-Omni as the primary Thinker candidate for SemanticFrame experiments. Use Qwen2.5-Omni or Ultravox as fallback depending on whether audio-only text evidence is sufficient. Use MiniCPM-o for self-hosted A100 research, not as first MVP-3 dependency.

Thinker should output a validated SemanticFrame candidate, for example intent hypotheses, slots, uncertainty, emotion hints, audio caption, semantic-close hint, and assistant-directedness hint. All fields remain evidence until the Interaction Controller and SlowTask consume them under ADR rules.

## API / Deployment Notes

Qwen Omni has an API path through DashScope/Bailian and open model paths in official repositories. Self-host candidates need GPU isolation and must not run inside Interaction Controller loops. Adapters should support separate profiles for `thinker_fast_system` and `thinker_composer` so the same model family does not blur authority boundaries.

## Latency and Resource Notes

Thinker latency can be higher than Duplex because it is not the barge-in hot path. Streaming partial SemanticFrame evidence may be useful, but the first stable frame should be measured against user interruption scenarios and ASR partial churn. Self-host omni models can be GPU-heavy; MiniCPM-o current documentation references notable memory requirements for newer variants.

## Schema / Structured Output Notes

Structured JSON should be treated as degraded until schema-constrained harnesses prove stability. The adapter should parse and validate model output into a local SemanticFrame schema, retry on invalid JSON, and mark output degraded when validation repairs are needed. Model-native tool calling should be ignored for Thinker role unless explicitly normalized as evidence; Thinker must not execute tools.

## Cancellation / Timeout / Retry Notes

If model-side cancellation is absent, close the client stream and attach late output to stale evidence. Timeouts should preserve ASR/Duplex evidence and emit a degraded missing-Thinker marker. Retries must use the same evidence snapshot and should not let a later retry mutate already committed task facts.

## Trace and Privacy Notes

Store only structured SemanticFrame evidence and redacted metadata. Avoid raw audio, raw transcripts with sensitive content, prompt secrets, and provider credentials. Audio caption may reveal private background context, so it should be minimized and redacted in fixtures.

## Degradation Proposal

- If JSON fails, retry with schema-only prompt, then degrade to minimal key-value frame.
- If audio input fails, use ASR text-only Thinker fallback and mark audio evidence unavailable.
- If emotion or assistant-directedness is unstable, expose confidence and keep it advisory.
- If Qwen3-Omni API is unavailable, use Qwen2.5-Omni or Ultravox for text SemanticFrame evidence.

## Risks

- A single omni model can appear to solve ASR, Thinker, TTS, Duplex, and SlowTask together, but that would collapse adapter boundaries and replayability.
- Semantic-close hints could be mistaken for turn ingress decisions.
- Composer prompts could accidentally rewrite SemanticCommitment facts if not checked.
- Audio caption can expose private environment information.
- Structured JSON reliability is unknown without a project-specific harness.

## Suggested Follow-up Experiments

- Prompt Qwen3-Omni for SemanticFrame JSON on synthetic Mandarin, English, mixed, noisy, and interrupted clips.
- Compare ASR-only vs audio+ASR SemanticFrame conflicts.
- Evaluate emotion and assistant-directedness calibration against labeled fixtures.
- Test Composer role prompts with immutable facts and coverage checks.
- Measure timeout and stale-result behavior under interrupted audio streams.

## Recommendation

Use Qwen3-Omni as the first Thinker evidence candidate, with Qwen2.5-Omni or Ultravox as fallbacks and MiniCPM-o reserved for self-hosted research. Keep Thinker authority narrow: evidence and spoken realization only, never turn ingress, tool authorization, truncate policy, or SlowTask final facts.
