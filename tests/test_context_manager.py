from __future__ import annotations

import copy

from backend.memory import ContextBuildResult, ContextManager


def test_compaction_preserves_recent_messages_and_exposes_loss_metadata():
    messages = [
        {"role": "user", "content": f"task_id=job-{index}: must keep the requirement {index}"}
        for index in range(15)
    ] + [{"role": "assistant", "content": "acknowledged"} for _ in range(6)]
    result = ContextManager(max_summary_chars=500).prepare(messages)

    assert isinstance(result, ContextBuildResult)
    assert result.metadata["compacted"] is True
    assert result.metadata["compacted_message_count"] == 15
    assert result.messages[1:] == messages[-6:]
    assert result.messages[0]["role"] == "system"
    assert "job-0" in result.messages[0]["content"]
    assert "[Constraints]" in result.messages[0]["content"]
    assert result.metadata["extracted_ids"]


def test_tool_output_is_summarized_deterministically_and_input_is_not_mutated():
    messages = [
        {"role": "user", "content": "find role #ABC-12"},
        {"role": "tool", "name": "lookup", "status": "success", "observation": {"id": "r-7", "title": "Backend"}},
    ] + [{"role": "assistant", "content": f"step {index}"} for index in range(19)]
    before = copy.deepcopy(messages)

    result = ContextManager(max_message_chars=80).compress_messages(messages)

    assert messages == before
    assert '"title":"Backend"' in result.messages[0]["content"]
    assert result.metadata["compacted_message_count"] == 15


def test_short_followup_fuses_latest_successful_tool_observation_with_visible_bounds():
    messages = [
        {"role": "user", "content": "Search open platform roles"},
        {"role": "tool", "name": "search_jobs", "status": "success", "observation": "job_id=role-99 " + "x" * 200},
        {"role": "tool", "name": "broken_search", "status": "failed", "observation": "ignore this"},
        {"role": "assistant", "content": "I found one."},
        {"role": "user", "content": "Why?"},
    ]
    result = ContextManager(max_tool_observation_chars=90).format_for_llm(
        messages, "You are helpful.", return_metadata=True
    )

    assert isinstance(result, ContextBuildResult)
    prompt = result.messages[0]["content"]
    assert "[Context Fusion Notice]" in prompt
    assert "tool=search_jobs" in prompt
    assert "[TRUNCATED tool observation]" in prompt
    assert result.metadata["fusion_applied"] is True
    assert result.metadata["fusion_truncated"] is True


def test_no_compaction_below_threshold_and_summary_cap_is_never_silent():
    messages = [{"role": "user", "content": "hello"}] * 20
    manager = ContextManager(max_summary_chars=100, max_message_chars=24)

    untouched = manager.prepare(messages)
    assert untouched.messages == messages
    assert untouched.metadata["compacted"] is False

    long_history = [
        {"role": "user", "content": f"must preserve job_id=long-{index} " + "x" * 100}
        for index in range(21)
    ]
    compacted = manager.prepare(long_history)
    summary = compacted.messages[0]["content"]
    assert len(summary) <= 100
    assert compacted.metadata["truncated"] is True
    assert compacted.metadata["truncation_marker_present"] is True
    assert "[TRUNCATED" in summary
