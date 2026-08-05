# Routing evaluation manifests

`prompt-dev.jsonl` is the first synthetic, text-only draft set for routing
prompt development. It contains exactly 80 cases in 20 four-case
contrast-set families. Every family is wholly contained in `prompt_dev`.
Members share a topic and expose multiple routing outcomes, but they do not
form strict minimal pairs because more than one controlled variable may differ.
Records use the `contrast_set` tag. Audit and Human Review Gate 1 tooling also
accept the legacy `minimal_pair` tag as contrast-set membership for older
manifests, but never treat it as proof of a strict one-variable pair. True
minimal pairs will be added as separately identified families after Gate 1.

The draft quota is:

| Outcome bucket | Cases |
| --- | ---: |
| `FAST_ONLY` foreground chat | 20 |
| `SPAWN_SLOW_TASK` | 20 |
| `PATCH_ACTIVE_SLOW_TASK` (patch, switch, or control candidate) | 28 |
| `IGNORE` or `AMBIGUOUS` | 12 |

The manifest is intentionally provider-free and contains no audio, provider
payload, local path, credential, or real-user data. Gold labels are evaluator
data: runners must not copy `gold`, label-derived hints, or rationale tags into
model input or journal events.

All records remain `annotation_status=draft` until the routing policy and the
critical or ambiguous cases have completed human review. A draft manifest is
useful for harness development and prompt exploration, but is not a release
gate or a claim of human-agreed ground truth.

To validate the manifest with the repository test entrypoint:

```bash
./scripts/test tests/evals/routing/test_prompt_dev_manifest.py -q
```
