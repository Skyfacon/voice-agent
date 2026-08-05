# Audio Routing Evaluation Implementation Plan

## Status

Implementation plan. This document does not add architecture capabilities, canonical events or accepted product policy. Accepted ADRs remain authoritative.

## Goal

Build a durable evaluation system for the browser-recorded audio path that can answer three distinct questions:

1. **Model:** did ASR / Thinker / Fast Interaction understand enough of the audio and task context to produce useful routing evidence?
2. **Router:** did deterministic TaskFocus and Router policy select an allowed `FAST_ONLY`, `SPAWN_SLOW_TASK`, `PATCH_ACTIVE_SLOW_TASK` or `IGNORE` decision?
3. **E2E:** did the foreground gate, UserPatch/SlowTask path and event journal produce the allowed user-visible and task-visible behavior?

The current seven-case `mvp6_routing_golden_eval` remains a provider-free Router contract smoke. Because it injects synthetic focus and complexity hints and makes no provider call, it is not a model/prompt/audio capability benchmark.

## Architecture constraints

The implementation must preserve:

- Router gate and TaskFocus ownership from ADR-006;
- evidence preservation and SlowTask-led semantic resolution from ADR-008;
- trace redaction, raw-audio and repository boundaries from ADR-010;
- replay/eval per vertical slice and honest real/mock/degraded reporting from ADR-012;
- SlowTask ownership of confirmation, cancel, switching and tool authorization from ADR-016;
- Fast Interaction candidate status and deterministic Fast Foreground Gate from ADR-017.

Scenario templates generate existing canonical event sequences only. Any need for a new MVP-relevant event, lifecycle state, pause/resume behavior, multi-active-task support or real external side effect stops implementation and requires an ADR change.

## Deliverables

### Dataset contract

- JSON Schema for the stable scenario DSL: `schema_name=voice_agent.routing_eval.case.v1`, `case_id`, `scenario_family_id`, `split`, `input`, `context`, `gold`, `tags`, `criticality`, `annotation_status`.
- `input` contains `modality`, `locale`, and exactly one of `utterance_text` or `audio_ref`; safe audio refs use only the `audio-eval://synthetic|local|locked/<token>` namespaces.
- `context` contains a template and optional active-task fields: `task_id`, `task_type`, `summary`, `lifecycle_phase`, `plan_version`, and optional ADR-016 `pending_confirmation_scope` for `ACTIVE_TASK_WAITING_CONFIRMATION` only.
- Gold supports `task_focus_allowed`, mutually exclusive and collectively exhaustive `router_decisions_allowed` / `router_decisions_forbidden`, `foreground_policy`, and `side_effect_expectations={slow_task_created,user_patch_emitted,external_side_effects=FORBIDDEN}`.
- Eight deterministic context templates documented in the labeling guide.
- Contrast-set and hard-negative scenario families, plus separately identified true minimal pairs that change exactly one controlled variable.
- A versioned ontology, rubric and error-cost policy.

### Runtime harness

- deterministic scenario loader and schema validation;
- context/event factory producing accepted canonical events and replay-valid task state;
- Model runner that invokes an explicitly selected adapter/profile and records its output mode;
- Router policy runner that consumes normalized evidence without a provider call;
- E2E runner that evaluates Router, foreground gate, SlowTask/UserPatch effects and replay;
- aggregate metrics and machine-readable/human-readable reports;
- prompt/profile paired comparison keyed by profile ID/version/hash.

Model, Router and E2E results are stored and reported separately. Gold data is held by the evaluator and never passed into runtime inputs.

### Data program

- 80 initial text/context contrast-set draft cases in 20 related routing families;
- 288 frozen semantic base cases after policy review;
- 384 local synthetic-audio views, including selected robustness variants;
- 48 consented real-human locked holdout recordings.

## Phased execution

### Milestone 1: contract, first 80 cases and provider-free harness

Implement:

1. labeling guide and asymmetric error policy;
2. schema and loader;
3. eight context templates and deterministic event factory;
4. 80 draft contrast-set cases covering FAST, SPAWN, PATCH/cancel/switch, IGNORE and AMBIGUOUS; these topic families are not claimed to be strict one-variable minimal pairs;
5. Router and E2E runners with fake-model boundary;
6. confusion matrix, macro-F1, weighted loss and critical-violation reporting;
7. tests proving schema failure, gold non-leakage, replay validity and gate/task-side effects.

No real provider or human audio is required. Existing seven-case smoke stays in the normal fast regression path.

### Human Review Gate 1: ontology and product policy

Humans review all 80 milestone-1 contrast-set cases, including every high-criticality, critical-violation-triggering and ambiguous case, plus AI-review disagreements. Later true one-variable minimal pairs are reviewed as policy-boundary pairs. Humans approve:

- FAST versus SPAWN boundaries, including current external facts and artifact complexity;
- active-task side chat, patch, cancellation and switch semantics;
- ambiguous clarification versus silence policy;
- critical-violation definitions and error weights;
- initial family-level split assignment.

Unresolved cases remain `draft` with `needs_product_policy`; they may not enter frozen gold. Approval freezes ontology v1.

### Milestone 2: expand and add real model/profile evaluation

Expand to 288 semantic base cases and implement the real Model runner. A target starting distribution is:

| Scenario group | Cases |
| --- | ---: |
| No active task: FAST | 48 |
| No active task: SPAWN | 54 |
| No active task: IGNORE | 30 |
| No active task: AMBIGUOUS | 24 |
| Active task: side-chat FAST | 24 |
| Active task: PATCH | 48 |
| Active task: new-task candidate | 18 |
| Active task: CANCEL/PAUSE candidate | 18 |
| Active task: AMBIGUOUS | 12 |
| Active task: IGNORE | 12 |
| **Total** | **288** |

The initial family-level split is:

- prompt development: 144 cases;
- validation/frozen regression: 72 cases;
- locked test: 72 cases.

Numbers may be adjusted at Review Gate 1 to preserve coverage, but the family isolation rule is mandatory. Prompt experiments change one controlled variable at a time and use paired reports. Locked test cases are not prompt examples and are not inspected repeatedly.

### Milestone 3: synthetic audio program

Generate audio only after semantic gold is stable:

```text
synthetic/redacted scenario text
  -> local TTS recipe
  -> canonical local WAV
  -> deterministic augmentation
  -> audio validation and safe reference
  -> Model / Router / E2E evaluation
```

Create one primary audio view for each of 288 cases and a second robustness view for 96 boundary cases, for approximately 384 local audio views. Variation dimensions include voice, rate, pause, volume, reverberation, far field, codec, clipping/dropout, background speech, overlap, filler, self-correction and mixed-language phrasing.

Audio files, raw provider bodies and detailed traces stay under ignored local output storage. Repository manifests contain deterministic recipe/seed, safe hash reference and redacted metadata only. Default tests do not make network calls or install dependencies. Real provider evaluation requires explicit approval, budget, timeout and mode labeling.

### Milestone 4: real-human locked holdout

Collect 48 recordings from consenting participants, using a balanced mixture of scripted and spontaneous tasks. Scripted readings may inherit a label only after a read-quality check; spontaneous speech receives fresh independent annotation and human adjudication.

Humans own consent, provider-transmission approval, privacy review, retention and locked-set access. Raw recordings remain local-only and are never committed or automatically synchronized.

### Human Review Gate 2: synthetic-to-real and promotion

Review:

- synthetic versus real performance gaps;
- failures by speaker, environment, directedness and context template;
- every release-blocking error on real audio;
- spontaneous annotation disagreement;
- whether a candidate prompt/profile improves frozen metrics without hiding cost in a protected slice;
- whether locked data has been exposed or overused.

Only after this review may a prompt/profile be promoted. A compromised locked family is retired into regression and replaced.

## Split and leakage controls

Leakage controls are release requirements:

1. All text paraphrases, context variations, TTS voices, augmentations and human readings sharing a `scenario_family_id` remain in one split.
2. `gold` is never included in model prompts, evidence events, Router context or audio-generation text.
3. Prompt examples and few-shot cases are identified by family and excluded from validation and locked splits.
4. Reports contain safe IDs and aggregate metrics, not raw audio, raw provider payloads or unredacted user text.
5. Blind failures are not used for tuning unless the family is formally moved out of the locked set.
6. Generated event journals contain only runtime-observable synthetic/redacted evidence; evaluator expectations are joined after execution.

Automated tests must fail on direct or derived gold leakage, family overlap, missing provenance, unknown labels and forbidden repository artifact paths.

## AI and human division of labor

AI/automation can generate scenario drafts, broad contrast sets, controlled one-variable minimal pairs, deterministic contexts, event sequences, TTS recipes, acoustic variants, draft labels, independent review suggestions, metrics and error clusters.

Humans remain required to:

- approve product routing policy;
- adjudicate critical, ambiguous and disputed gold;
- authorize and quality-check human recordings;
- manage the locked holdout;
- review synthetic-to-real gaps;
- approve prompt/profile promotion.

The efficient workflow is AI draft plus risk-based human review, not full manual authoring and not automatic self-judging by the model under test.

## Acceptance criteria

Milestone 1 is complete when:

- all 80 draft cases validate against the schema;
- event templates replay without re-running models/tools;
- Model, Router and E2E results are distinct;
- forbidden/allowed outcomes and task-side effects are scored;
- critical violations fail the run;
- gold-leakage and family-split tests pass;
- the normal repository test entrypoint passes;
- no raw audio, raw trace, provider body, credential or unredacted real input is added.

The program is complete only after both Human Review Gates. High aggregate accuracy cannot waive a critical violation or substitute for human policy approval.
