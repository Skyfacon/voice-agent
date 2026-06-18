from __future__ import annotations

from pathlib import Path


SCENARIOS = (
    "MVP6-LOCAL-CONSOLE-STARTUP-001",
    "MVP6-MIC-DRAFT-RUN-001",
    "MVP6-PROVIDER-FREE-RUN-001",
    "MVP6-LIVE-PROVIDER-GATE-001",
    "MVP6-PIPELINE-INSPECTOR-001",
    "MVP6-QA-HISTORY-001",
    "MVP6-SAFETY-REDACTION-001",
    "MVP6-NO-ARCHITECTURE-EXPANSION-001",
)


def test_mvp6_operating_doc_lists_all_acceptance_scenarios() -> None:
    doc = Path("docs/implementation/mvp6-local-debug-console.md").read_text(encoding="utf-8")
    for scenario in SCENARIOS:
        assert scenario in doc


def test_mvp6_operating_doc_states_non_goals_and_safe_artifacts() -> None:
    doc = Path("docs/implementation/mvp6-local-debug-console.md").read_text(encoding="utf-8")
    normalized_doc = " ".join(doc.split())
    required_phrases = (
        "## Local Artifact Policy",
        "All MVP6 artifacts are local-only",
        "`outputs/mvp6-debug-console/`, which is ignored by the repository",
        "approval packets",
        "uploaded browser draft wav files",
        "manual debug",
        "ignored local-only path",
        "No realtime microphone streaming",
        "No full-duplex, AEC, or barge-in",
        "No real TTS",
        "No real Slow LLM",
        "No production demo UI claim",
        "No real external side-effect tool execution",
        "No new canonical event",
        "No new RouterDecision",
        "outputs/mvp6-debug-console/qa-history.jsonl",
        "QA history is local-only",
        "raw audio is not saved to QA history",
        "Provider request bodies",
        "provider response bodies",
        "prompt dumps",
        "local paths",
        "filenames",
        "secrets",
    )
    for phrase in required_phrases:
        assert phrase in normalized_doc


def test_mvp6_operating_doc_includes_command_and_approval_template() -> None:
    doc = Path("docs/implementation/mvp6-local-debug-console.md").read_text(encoding="utf-8")
    required_phrases = (
        "scripts/mvp6-debug-console",
        "--approval-packet outputs/mvp6-debug-console/approval.json",
        "--output-root outputs/mvp6-debug-console",
        "--host 127.0.0.1",
        "--port 8766",
        '"approval_id": "mvp6-local-debug-console-local"',
        '"live_provider_opt_in": true',
        '"local_wav_opt_in": true',
        '"metadata_only_output": true',
        '"replay_reruns_provider": false',
        '"provider_adapter_ids": ["mvp5_asr_adapter", "mvp5_thinker_adapter"]',
        '"credential_env_var_name": "DASHSCOPE_API_KEY"',
        '"max_provider_calls": 2',
        '"timeout_ms": 30000',
        '"safe_output_ref": "summary://mvp6/debug-console/local"',
    )
    for phrase in required_phrases:
        assert phrase in doc
