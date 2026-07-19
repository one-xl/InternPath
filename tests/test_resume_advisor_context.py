from backend.resume_advisor.context import build_advisor_context_snapshot


def test_context_snapshot_preserves_recent_messages_and_bounds_compacted_history():
    snapshot = build_advisor_context_snapshot(
        current_block={"id": "block-1", "text": "负责 FastAPI 接口开发", "sectionName": "项目经历"},
        jd_requirements=["FastAPI", "Redis"],
        messages=[
            {"role": "user", "content": f"早期讨论 {index} " + "x" * 120}
            for index in range(6)
        ] + [{"role": "user", "content": "请保留简洁语气"}],
        facts=[{"claimKey": "redis", "claimValue": "使用过 Redis", "status": "confirmed", "scope": "global"}],
        preferences=["避免夸张措辞"],
        max_chars=900,
        recent_turn_limit=2,
    )

    assert snapshot["version"] == "advisor-context-v1"
    assert snapshot["compactedMessageCount"] == 5
    assert snapshot["recentMessages"][-1]["content"] == "请保留简洁语气"
    assert "避免夸张措辞" in snapshot["promptText"]
    assert len(snapshot["promptText"]) <= 900
    assert snapshot["hash"]
