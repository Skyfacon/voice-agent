from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from voice_agent.evals.routing.cli import main


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "routing-eval"
FORBIDDEN_JSON_FRAGMENTS = (
    "utterance_text",
    "transcript",
    "audio_ref",
    "raw_audio",
    "prompt_body",
    "provider_body",
    "provider_payload",
    "/Users/",
    "../",
    "api_key",
    "authorization",
)


def test_audit_uses_prompt_dev_by_default_and_emits_safe_json(capsys) -> None:
    exit_code = main(["audit"])
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert exit_code == 0
    assert result["status"] == "passed"
    assert result["case_count"] == 80
    assert result["bucket_counts"] == {
        "fast": 20,
        "ignore_ambiguous": 12,
        "patch_control": 28,
        "spawn": 20,
    }
    _assert_safe_json_stdout(captured.out)


def test_review_renders_safe_synthetic_markdown_to_stdout(capsys) -> None:
    exit_code = main(["review"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert output.startswith("# Audio Routing Human Review Packet\n")
    assert "Cases requiring review: 80" in output
    assert "rpd_f01_fast" in output
    assert "帮我持续关注明天早上的天气" in output
    for forbidden in (
        "/Users/",
        "audio-eval://",
        "provider_body",
        "prompt_dump",
        "api_key=",
    ):
        assert forbidden not in output


@pytest.mark.parametrize("command", ("router", "e2e"))
def test_policy_commands_fail_closed_without_explicit_oracle_flag(
    command: str, capsys
) -> None:
    with pytest.raises(SystemExit) as caught:
        main([command])

    captured = capsys.readouterr()
    assert caught.value.code == 2
    assert captured.out == ""
    assert "requires explicit --oracle-policy" in captured.err
    assert "not a model evaluation" in captured.err


@pytest.mark.parametrize("command", ("router", "e2e"))
def test_oracle_policy_commands_are_explicitly_not_model_results(
    command: str, capsys
) -> None:
    exit_code = main([command, "--oracle-policy"])
    output = capsys.readouterr().out
    result = json.loads(output)

    assert exit_code == 0
    assert result["command"] == command
    assert result["model_evaluated"] is False
    assert result["oracle_evidence_used"] is True
    assert result["gold_derived_evidence"] is True
    assert result["interpretation"] == "not_a_model_evaluation"
    assert result["execution_scope"] == "deterministic_policy_contract_only"
    assert result["report"]["summary"]["case_count"] == 80
    assert result["report"]["critical_violations"]["count"] == 0
    _assert_safe_json_stdout(output)


def test_script_entrypoint_runs_with_repository_python() -> None:
    environment = os.environ.copy()
    environment["VOICE_AGENT_PYTHON"] = sys.executable
    completed = subprocess.run(
        [str(SCRIPT), "audit"],
        cwd=REPO_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["status"] == "passed"
    _assert_safe_json_stdout(completed.stdout)


def _assert_safe_json_stdout(output: str) -> None:
    json.loads(output)
    lowered = output.lower()
    for forbidden in FORBIDDEN_JSON_FRAGMENTS:
        assert forbidden.lower() not in lowered
