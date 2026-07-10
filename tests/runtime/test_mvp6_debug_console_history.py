from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from voice_agent.runtime.mvp6_debug_console_history import (
    MVP6QAHistoryEntry,
    MVP6QAHistoryError,
    append_mvp6_qa_history,
    clear_mvp6_qa_history,
    read_mvp6_qa_history,
    validate_mvp6_history_record,
)


def test_append_and_read_history_saves_question_and_debug_answer(tmp_path: Path) -> None:
    history_path = tmp_path / "outputs" / "mvp6-debug-console" / "qa-history.jsonl"
    entry = MVP6QAHistoryEntry(
        run_id="mvp6_run_fast",
        created_at="2026-06-17T00:00:00Z",
        provider_mode="fake",
        question_source="asr_transcript",
        question_text="What is the weather?",
        answer_kind="debug_route_answer",
        answer_display="Router chose FAST_ONLY from FOREGROUND_CHAT evidence.",
        actual_route="FAST_ONLY",
        router_decision="FAST_ONLY",
        route_result_kind="direct_answer",
        asr_output_mode="real",
        thinker_output_mode="real",
        fast_interaction_output_mode="real",
        foreground_gate_decision="passed",
        foreground_output_basis="reply_candidate",
        foreground_gate_failure_reason=None,
        latency_debug={"fast_interaction_total_ms": 405, "fast_interaction_timed_out": False},
        provider_call_used=False,
        fake_transport_used=True,
        event_ids=("evt_mvp6_fast",),
        safe_refs=("text://synthetic/mvp6/fast",),
    )

    appended = append_mvp6_qa_history(history_path, entry)

    lines = history_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    saved = json.loads(lines[0])
    assert saved["question_text"] == "What is the weather?"
    assert saved["answer_display"] == "Router chose FAST_ONLY from FOREGROUND_CHAT evidence."
    assert saved["raw_audio_saved"] is False
    assert saved["provider_body_saved"] is False
    assert saved["secret_saved"] is False
    assert saved["fast_interaction_output_mode"] == "real"
    assert saved["foreground_gate_decision"] == "passed"
    assert saved["foreground_output_basis"] == "reply_candidate"
    assert saved["latency_debug"]["fast_interaction_total_ms"] == 405
    assert appended["event_ids"] == ["evt_mvp6_fast"]
    assert appended["safe_refs"] == ["text://synthetic/mvp6/fast"]
    assert appended == saved
    assert read_mvp6_qa_history(history_path) == [saved]


def test_history_read_caps_latest_entries(tmp_path: Path) -> None:
    history_path = tmp_path / "outputs" / "mvp6-debug-console" / "qa-history.jsonl"
    for index in range(25):
        append_mvp6_qa_history(
            history_path,
            MVP6QAHistoryEntry(
                run_id=f"mvp6_run_{index}",
                created_at="2026-06-17T00:00:00Z",
                provider_mode="fake",
                question_source="asr_transcript",
                question_text=f"Question {index}",
                answer_kind="debug_route_answer",
                answer_display="Router chose FAST_ONLY from FOREGROUND_CHAT evidence.",
                actual_route="FAST_ONLY",
                router_decision="FAST_ONLY",
                route_result_kind="direct_answer",
                asr_output_mode="real",
                thinker_output_mode="real",
                provider_call_used=False,
                fake_transport_used=True,
            ),
        )

    latest = read_mvp6_qa_history(history_path)

    assert len(latest) == 20
    assert latest[0]["run_id"] == "mvp6_run_5"
    assert latest[-1]["run_id"] == "mvp6_run_24"


def test_history_rejects_raw_audio_paths_provider_body_and_secrets(tmp_path: Path) -> None:
    history_path = tmp_path / "outputs" / "mvp6-debug-console" / "qa-history.jsonl"
    entry = MVP6QAHistoryEntry(
        run_id="mvp6_run_unsafe",
        created_at="2026-06-17T00:00:00Z",
        provider_mode="dashscope_live",
        question_source="asr_transcript",
        question_text="Question",
        answer_kind="debug_route_answer",
        answer_display="Router chose FAST_ONLY from FOREGROUND_CHAT evidence.",
        actual_route="FAST_ONLY",
        router_decision="FAST_ONLY",
        route_result_kind="direct_answer",
        asr_output_mode="real",
        thinker_output_mode="real",
        provider_call_used=True,
        fake_transport_used=False,
        safe_refs=("file:///Users/a123/private.wav",),
    )

    with pytest.raises(MVP6QAHistoryError, match="unsafe"):
        append_mvp6_qa_history(history_path, entry)


@pytest.mark.parametrize(
    "record",
    [
        {
            "raw_audio_saved": False,
            "provider_body_saved": False,
            "secret_saved": False,
            "local_path_saved": False,
            "nested": [b"raw"],
        },
        {
            "raw_audio_saved": False,
            "provider_body_saved": False,
            "secret_saved": False,
            "local_path_saved": False,
            "nested": {"provider_body": "redacted"},
        },
        {
            "raw_audio_saved": False,
            "provider_body_saved": False,
            "secret_saved": False,
            "local_path_saved": False,
            "nested": {"access_token": "redacted"},
        },
        {
            "raw_audio_saved": True,
            "provider_body_saved": False,
            "secret_saved": False,
            "local_path_saved": False,
        },
    ],
)
def test_validate_history_record_rejects_nested_unsafe_content(record: dict[str, Any]) -> None:
    with pytest.raises(MVP6QAHistoryError, match="unsafe"):
        validate_mvp6_history_record(record)


def test_clear_history_only_clears_configured_file(tmp_path: Path) -> None:
    history_path = tmp_path / "outputs" / "mvp6-debug-console" / "qa-history.jsonl"
    append_mvp6_qa_history(
        history_path,
        MVP6QAHistoryEntry(
            run_id="mvp6_run_clear",
            created_at="2026-06-17T00:00:00Z",
            provider_mode="fake",
            question_source="asr_transcript",
            question_text="Clear this?",
            answer_kind="debug_route_answer",
            answer_display="Router chose FAST_ONLY from FOREGROUND_CHAT evidence.",
            actual_route="FAST_ONLY",
            router_decision="FAST_ONLY",
            route_result_kind="direct_answer",
            asr_output_mode="real",
            thinker_output_mode="real",
            provider_call_used=False,
            fake_transport_used=True,
        ),
    )

    clear_mvp6_qa_history(history_path)

    assert read_mvp6_qa_history(history_path) == []
    assert history_path.exists()
    assert history_path.read_text(encoding="utf-8") == ""
