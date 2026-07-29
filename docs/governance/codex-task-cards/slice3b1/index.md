# Slice 3B.1 Task Card Index

Use Quick mode for localized work that does not cross an accepted architecture
boundary. Use one Task Card for a coherent boundary change with its own
verification gate. Use the Work Package when the goal requires several
dependent cards; execution advances one verified card at a time and stops at
the first failed gate.

File existence is not completion evidence. Every entry begins `not-started` and
must pass its verify-first focused and overlap checks before becoming
`verified`.

| ID | Title | Dependencies | Status | Link |
| --- | --- | --- | --- | --- |
| `TC-S3B1-01` | Canonical events, conditional envelopes, and safe refs | None | `not-started` | [Open card](TC-S3B1-01-events-and-envelopes.md) |
| `TC-S3B1-02` | Provider-free capabilities and assembly | `TC-S3B1-01` | `not-started` | [Open card](TC-S3B1-02-capabilities-and-assembly.md) |
| `TC-S3B1-03` | Typed protocol and shared transport | None | `not-started` | [Open card](TC-S3B1-03-protocol-and-transport.md) |
| `TC-S3B1-04` | Deterministic scripted wire | `TC-S3B1-03` | `not-started` | [Open card](TC-S3B1-04-scripted-wire.md) |
| `TC-S3B1-05` | Candidate quarantine and ephemeral payload ownership | `TC-S3B1-03` | `not-started` | [Open card](TC-S3B1-05-candidate-quarantine.md) |
| `TC-S3B1-06` | Session Pump, readiness, and generation lifecycle | `TC-S3B1-01` through `TC-S3B1-05` | `not-started` | [Open card](TC-S3B1-06-session-lifecycle.md) |
| `TC-S3B1-07` | Context, Route Evidence, Router, and join-only orchestration | `TC-S3B1-01`, `02`, `05`, `06` | `not-started` | [Open card](TC-S3B1-07-route-evidence-and-orchestration.md) |
| `TC-S3B1-08` | Fail-closed Gate and contract-only release | `TC-S3B1-01`, `02`, `05`, `06`, `07` | `not-started` | [Open card](TC-S3B1-08-gate-and-release.md) |
| `TC-S3B1-09` | ADR-018 replay reducer and digest | `TC-S3B1-01`, `06`, `07`, `08` | `not-started` | [Open card](TC-S3B1-09-replay.md) |
| `TC-S3B1-10` | Controller ingress, runner, scenarios, and safe result | `TC-S3B1-01` through `TC-S3B1-09` | `not-started` | [Open card](TC-S3B1-10-scenario-runner.md) |
| `TC-S3B1-11` | CLI, minimal fixtures, and acceptance evidence | `TC-S3B1-09`, `TC-S3B1-10` | `not-started` | [Open card](TC-S3B1-11-cli-and-acceptance.md) |
| `WP-S3B1-01` | Provider-free protocol-faithful Slice 3B.1 | Dependency DAG above | `not-started` | [Open Work Package](WP-S3B1-01.md) |

The detailed predecessor is retained as the
[historical master plan](../../../superpowers/plans/2026-07-27-qwen-slice3b1-protocol-faithful-fake.md).
It is provenance, not the normal active execution surface.
