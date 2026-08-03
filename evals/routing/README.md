# Audio Routing Evaluation

This directory defines the repository-safe evaluation contract for the audio routing path:

```text
committed audio turn + current task context
  -> model routing evidence and foreground candidate
  -> deterministic RouterDecision
  -> deterministic foreground gate and task-side effects
```

The evaluation has three separate layers. Results from different layers must not be merged into one accuracy number.

| Layer | System under test | Primary question |
| --- | --- | --- |
| Model | ASR / Thinker / Fast Interaction adapter profile | Did the model derive useful routing evidence from the audio and context? |
| Router | deterministic Router and TaskFocusState policy | Did normalized evidence produce an allowed `RouterDecision`? |
| E2E | Router, foreground gate, UserPatch / SlowTask effects and event journal | Was the resulting user-visible and task-visible behavior safe and correct? |

The existing seven-case `src/voice_agent/runtime/mvp6_routing_golden_eval.py` is a provider-free Router contract smoke test. It injects synthetic routing hints and does **not** measure model routing capability, prompt quality, audio robustness, or production readiness. It remains useful as a fast regression smoke and is not replaced by this dataset.

## Milestone 1 commands

Run the corpus audit and render the synthetic Human Review Gate 1 packet with:

```bash
scripts/routing-eval audit
scripts/routing-eval review
```

The deterministic Router and E2E contract runs deliberately require an explicit oracle flag:

```bash
scripts/routing-eval router --oracle-policy
scripts/routing-eval e2e --oracle-policy
```

Those two commands derive normalized evidence from draft gold solely to test policy, foreground-gate, task-effect and replay wiring. Their reports state `model_evaluated=false`; they are not model scores. Model capability evaluation must instead use `model_runner.py` with an explicitly selected adapter/profile and keep its results separate.

## Repository layout

```text
evals/routing/
  README.md
  schema/                         # case and manifest schema
  manifests/                      # synthetic/redacted JSONL cases
  rubrics/
    routing-labeling-guide.md
    error-cost-policy.md
  profiles/                       # prompt/profile metadata, never raw provider prompts
```

Runner code, generated reports, local audio and provider responses do not belong in this directory unless they are synthetic, redacted and minimal.

## Case contract

The stable scenario DSL uses these top-level fields:

```json
{
  "schema_name": "voice_agent.routing_eval.case.v1",
  "case_id": "routing_patch_budget_001",
  "scenario_family_id": "patch_budget",
  "split": "prompt_dev",
  "input": {
    "modality": "text",
    "locale": "zh-CN",
    "utterance_text": "预算改成五百"
  },
  "context": {
    "template": "ACTIVE_TASK_PLANNING",
    "active_task": {
      "task_id": "task_trip_001",
      "task_type": "trip_planning",
      "summary": "规划上海三日游",
      "lifecycle_phase": "PLANNING",
      "plan_version": 2
    }
  },
  "gold": {
    "task_focus_allowed": ["ACTIVE_TASK_PATCH"],
    "router_decisions_allowed": ["PATCH_ACTIVE_SLOW_TASK"],
    "router_decisions_forbidden": ["FAST_ONLY", "SPAWN_SLOW_TASK", "IGNORE"],
    "foreground_policy": "ACK_PATCH",
    "side_effect_expectations": {
      "slow_task_created": false,
      "user_patch_emitted": true,
      "external_side_effects": "FORBIDDEN"
    }
  },
  "tags": [],
  "criticality": "high",
  "annotation_status": "draft"
}
```

`schema_name` must be `voice_agent.routing_eval.case.v1`. `gold` is evaluator-only data. It must never be copied into model input, adapter evidence, Router context, event journal payloads, prompt examples for the same split, or an audio-generation prompt that exposes labels.

`input` contains `modality`, `locale`, and exactly one of `utterance_text` or `audio_ref`. An `audio_ref` uses only `audio-eval://synthetic/<token>`, `audio-eval://local/<token>` or `audio-eval://locked/<token>`; it is not a filesystem path or network URL. `context` contains `template` and an optional `active_task` with `task_id`, `task_type`, `summary`, `lifecycle_phase`, `plan_version`, and optional `pending_confirmation_scope`.

Use `allowed` sets where more than one product-compliant outcome exists. Use `forbidden` sets for safety constraints that must hold even when the exact preferred outcome remains under review. The allowed and forbidden Router sets are disjoint and together cover all four Router decisions. Do not force genuinely ambiguous cases into a false single-label ground truth.

## Context templates

The first dataset version uses eight deterministic context templates:

1. `NO_ACTIVE_TASK`
2. `ACTIVE_TASK_PLANNING`
3. `ACTIVE_TASK_WAITING_TOOL`
4. `ACTIVE_TASK_WAITING_CONFIRMATION`
5. `ACTIVE_TASK_WAITING_SLOT`
6. `ACTIVE_TASK_FINALIZING`
7. `TERMINAL_TASK`
8. `NON_ASSISTANT_BACKGROUND`

Templates generate canonical, synthetic event history; they do not add event names or runtime capabilities. Active-task templates bind `task_id`, `plan_version` and `task_event_seq`. Confirmation, cancel and task switching remain owned by SlowTask under ADR-016.

## Data lifecycle

The long-term target is:

- 288 semantic base cases;
- 384 local synthetic-audio views, including robustness variants;
- 48 consented real-human locked holdout recordings.

Development begins with 80 high-value contrast-set draft cases arranged in 20 four-case families. These families span related FAST, SPAWN, PATCH/control and IGNORE/AMBIGUOUS decisions; they are not strict minimal pairs and do not claim that exactly one variable changes. Human Review Gate 1 approves the routing ontology and difficult labels before expansion to 288 cases. Later expansion adds separately identified, true one-variable minimal pairs. Audit and review tooling still accept the old `minimal_pair` tag as contrast-set membership for backward compatibility, without inferring strict-pair semantics. Reviewed records advance from `draft` to `human_reviewed` or `adjudicated`; freezing is a dataset-version operation, not an annotation status. Human Review Gate 2 reviews synthetic-to-real gaps and locked holdout results before any prompt/profile promotion decision.

All variants from one `scenario_family_id` must stay in the same split. Paraphrases, TTS voices, noisy versions and human readings of the same semantic case may not cross splits. See the implementation plan for the split and promotion policy.

## Safety and artifact policy

- Raw audio, raw trace, provider request/response bodies, secrets and unredacted real user input are local-only and never committed.
- Repository manifests contain only synthetic/redacted text, deterministic recipes, safe references and aggregate metrics.
- `real`, `mock`, `fallback` and `degraded` results are reported separately.
- Replay consumes recorded events and never re-runs models, TTS or tools.
- Model candidate text is not a task fact and is never considered user-visible unless the deterministic foreground gate commits it.

The normative labeling rules are in [routing-labeling-guide.md](rubrics/routing-labeling-guide.md). Release-blocking failures and weighted metrics are in [error-cost-policy.md](rubrics/error-cost-policy.md). The phased delivery plan is in [`docs/implementation/audio-routing-eval-plan.md`](../../docs/implementation/audio-routing-eval-plan.md).
