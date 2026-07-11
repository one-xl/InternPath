from __future__ import annotations

import backend.resume_advisor.verification as verification

from backend.resume_advisor.verification import (
    decode_jd_requirements,
    draft_resume_suggestion,
    review_suggestion_quality,
    review_with_hr_critic,
    verify_suggestion_facts,
)


def test_jd_requirement_is_not_candidate_fact_evidence():
    result = verify_suggestion_facts(
        original_text="负责 FastAPI 接口开发",
        proposed_text="负责 FastAPI 与 Redis 接口开发",
        resume_evidence_texts=["负责 FastAPI 接口开发"],
        confirmed_facts=[],
        jd_text="岗位要求熟悉 FastAPI 和 Redis",
    )

    assert result.status == "needs_user"
    assert any("Redis" in issue.claim for issue in result.fact_issues)
    assert all("JD" not in ref for issue in result.fact_issues for ref in issue.evidence_refs)


def test_chinese_technology_from_jd_also_requires_candidate_evidence():
    result = verify_suggestion_facts(
        original_text="负责 FastAPI 接口开发",
        proposed_text="使用消息队列处理异步任务",
        resume_evidence_texts=["负责 FastAPI 接口开发"],
        confirmed_facts=[],
        jd_text="熟悉消息队列与异步任务优先",
    )

    assert result.status == "needs_user"
    assert any(issue.category == "skill" and issue.claim == "消息队列" for issue in result.fact_issues)


def test_new_skill_role_and_result_without_evidence_require_user_input():
    result = verify_suggestion_facts(
        original_text="参与 FastAPI 接口开发",
        proposed_text="主导 Redis 缓存架构设计，使接口性能提升 30%",
        resume_evidence_texts=["参与 FastAPI 接口开发"],
        confirmed_facts=[],
    )

    assert result.status == "needs_user"
    categories = {issue.category for issue in result.fact_issues}
    assert {"skill", "role", "result", "quantitative"} <= categories


def test_explicitly_denied_claim_is_unsupported():
    result = verify_suggestion_facts(
        original_text="参与接口开发",
        proposed_text="使用 Redis 缓存优化接口",
        resume_evidence_texts=["参与接口开发"],
        confirmed_facts=[
            {"claimValue": "没有 Redis 缓存经历", "status": "denied", "id": "fact-denied"},
        ],
    )

    assert result.status == "unsupported"
    assert any(issue.category == "skill" and issue.status == "unsupported" for issue in result.fact_issues)


def test_quality_gate_rejects_only_when_fact_verification_is_incomplete():
    result = review_suggestion_quality(
        original_text="负责接口开发",
        proposed_text="```text\n• 使用 Redis 优化接口\n```",
        evidence_block_ids=["block-1"],
        fact_status="needs_user",
    )

    assert result.is_passed is False
    assert "事实尚未核验通过" in result.issues


def test_quality_gate_allows_semantic_rephrases_and_presentation_prefixes():
    result = review_suggestion_quality(
        original_text="负责 FastAPI 接口开发",
        proposed_text="优化后：• 使用 FastAPI 开发接口",
        evidence_block_ids=["block-1"],
        fact_status="supported",
    )

    assert result.is_passed is True
    assert result.issues == []


def test_jd_decoding_reuses_the_same_model_result_from_cache(monkeypatch):
    calls = 0
    cache: dict[str, object] = {}

    class FakeJobDecoder:
        def __init__(self, **_kwargs):
            pass

        async def decode_job(self, _jd_text):
            nonlocal calls
            calls += 1
            return {"hard_requirements": {"skills": ["FastAPI"]}, "soft_requirements": {}, "core_duties": []}

    monkeypatch.setattr("backend.agents.job_decoder.JobDecoder", FakeJobDecoder)
    monkeypatch.setattr(verification, "get_agent_cache", lambda _namespace, key: cache.get(key), raising=False)
    monkeypatch.setattr(verification, "set_agent_cache", lambda _namespace, key, value: cache.setdefault(key, value), raising=False)

    first = decode_jd_requirements(
        jd_text="岗位要求熟悉 FastAPI",
        fallback_requirements=["FastAPI"],
        model_client=object(),
        model_id="gpt-test",
    )
    second = decode_jd_requirements(
        jd_text="岗位要求熟悉 FastAPI",
        fallback_requirements=["FastAPI"],
        model_client=object(),
        model_id="gpt-test",
    )

    assert first == second == ["FastAPI"]
    assert calls == 1


def test_jd_decoding_reports_miss_then_hit(monkeypatch):
    cache: dict[str, object] = {}
    cache_events: list[tuple[str, bool]] = []

    class FakeJobDecoder:
        def __init__(self, **_kwargs):
            pass

        async def decode_job(self, _jd_text):
            return {"hard_requirements": {"skills": ["FastAPI"]}, "soft_requirements": {}, "core_duties": []}

    monkeypatch.setattr("backend.agents.job_decoder.JobDecoder", FakeJobDecoder)
    monkeypatch.setattr(verification, "get_agent_cache", lambda _namespace, key: cache.get(key), raising=False)
    monkeypatch.setattr(verification, "set_agent_cache", lambda _namespace, key, value: cache.setdefault(key, value), raising=False)

    for _ in range(2):
        decode_jd_requirements(
            jd_text="岗位要求熟悉 FastAPI",
            fallback_requirements=["FastAPI"],
            model_client=object(),
            model_id="gpt-test",
            on_cache_event=lambda namespace, hit: cache_events.append((namespace, hit)),
        )

    assert cache_events == [
        ("resume_advisor_jd_decode_v1", False),
        ("resume_advisor_jd_decode_v1", True),
    ]


def test_resume_draft_reuses_the_same_model_result_from_cache(monkeypatch):
    calls = 0
    cache: dict[str, object] = {}

    class FakeResumeCopywriter:
        def __init__(self, **_kwargs):
            pass

        async def rewrite_section(self, **_kwargs):
            nonlocal calls
            calls += 1
            return "• 使用 FastAPI 开发接口"

    monkeypatch.setattr("backend.agents.resume_copywriter.ResumeCopywriter", FakeResumeCopywriter)
    monkeypatch.setattr(verification, "get_agent_cache", lambda _namespace, key: cache.get(key))
    monkeypatch.setattr(verification, "set_agent_cache", lambda _namespace, key, value: cache.setdefault(key, value))

    first = draft_resume_suggestion(
        original_text="负责 FastAPI 接口开发",
        section_name="项目经历",
        jd_requirements=["FastAPI"],
        model_client=object(),
        model_id="gpt-test",
    )
    second = draft_resume_suggestion(
        original_text="负责 FastAPI 接口开发",
        section_name="项目经历",
        jd_requirements=["FastAPI"],
        model_client=object(),
        model_id="gpt-test",
    )

    assert first.proposed_text == second.proposed_text == "• 使用 FastAPI 开发接口"
    assert calls == 1


def test_resume_draft_forwards_provider_deltas_without_masquerading_cache_as_stream(monkeypatch):
    cache: dict[str, object] = {}
    cache_events: list[tuple[str, bool]] = []
    first_deltas: list[str] = []
    cached_deltas: list[str] = []

    class FakeResumeCopywriter:
        def __init__(self, **_kwargs):
            pass

        async def rewrite_section(self, **kwargs):
            kwargs["on_delta"]("• 使用")
            kwargs["on_delta"](" FastAPI 开发接口")
            return "• 使用 FastAPI 开发接口"

    monkeypatch.setattr("backend.agents.resume_copywriter.ResumeCopywriter", FakeResumeCopywriter)
    monkeypatch.setattr(verification, "get_agent_cache", lambda _namespace, key: cache.get(key))
    monkeypatch.setattr(verification, "set_agent_cache", lambda _namespace, key, value: cache.setdefault(key, value))

    first = draft_resume_suggestion(
        original_text="负责 FastAPI 接口开发",
        section_name="项目经历",
        jd_requirements=["FastAPI"],
        model_client=object(),
        model_id="gpt-test",
        on_delta=first_deltas.append,
        on_cache_event=lambda namespace, hit: cache_events.append((namespace, hit)),
    )
    second = draft_resume_suggestion(
        original_text="负责 FastAPI 接口开发",
        section_name="项目经历",
        jd_requirements=["FastAPI"],
        model_client=object(),
        model_id="gpt-test",
        on_delta=cached_deltas.append,
        on_cache_event=lambda namespace, hit: cache_events.append((namespace, hit)),
    )

    assert first.proposed_text == second.proposed_text == "• 使用 FastAPI 开发接口"
    assert first_deltas == ["• 使用", " FastAPI 开发接口"]
    assert cached_deltas == []
    assert cache_events == [
        ("resume_advisor_draft_v1", False),
        ("resume_advisor_draft_v1", True),
    ]


def test_resume_draft_cache_tracks_effective_user_preferences(monkeypatch):
    cache: dict[str, object] = {}
    calls: list[str] = []
    preferences = {"u1": ["保持简洁"], "u2": ["保留更多技术细节"]}

    class FakePreferenceDB:
        def get_preferences(self, user_id, _section_name):
            return preferences.get(str(user_id), [])

    class FakeResumeCopywriter:
        def __init__(self, **_kwargs):
            pass

        async def rewrite_section(self, **kwargs):
            calls.append(str(kwargs["user_id"]))
            return f"{kwargs['user_id']}:{'|'.join(kwargs['preference_rules'])}"

    monkeypatch.setattr("backend.memory.preference_db.PreferenceDB", FakePreferenceDB)
    monkeypatch.setattr("backend.agents.resume_copywriter.ResumeCopywriter", FakeResumeCopywriter)
    monkeypatch.setattr(verification, "get_agent_cache", lambda _namespace, key: cache.get(key))
    monkeypatch.setattr(verification, "set_agent_cache", lambda _namespace, key, value: cache.setdefault(key, value))

    first = draft_resume_suggestion(
        original_text="负责 FastAPI 接口开发", section_name="项目经历", jd_requirements=["FastAPI"],
        model_client=object(), model_id="gpt-test", user_id="u1",
    )
    second = draft_resume_suggestion(
        original_text="负责 FastAPI 接口开发", section_name="项目经历", jd_requirements=["FastAPI"],
        model_client=object(), model_id="gpt-test", user_id="u2",
    )
    repeated = draft_resume_suggestion(
        original_text="负责 FastAPI 接口开发", section_name="项目经历", jd_requirements=["FastAPI"],
        model_client=object(), model_id="gpt-test", user_id="u1",
    )

    assert first.proposed_text == repeated.proposed_text == "u1:保持简洁"
    assert second.proposed_text == "u2:保留更多技术细节"
    assert calls == ["u1", "u2"]


def test_hr_review_reuses_the_same_model_result_from_cache(monkeypatch):
    calls = 0
    cache: dict[str, object] = {}

    class FakeHRCritic:
        def __init__(self, **_kwargs):
            pass

        async def evaluate(self, **_kwargs):
            nonlocal calls
            calls += 1
            return {"score": 90, "is_passed": True, "critique": "事实一致", "suggestions": "无"}

    monkeypatch.setattr("backend.agents.hr_critic.HRCritic", FakeHRCritic)
    monkeypatch.setattr(verification, "get_agent_cache", lambda _namespace, key: cache.get(key))
    monkeypatch.setattr(verification, "set_agent_cache", lambda _namespace, key, value: cache.setdefault(key, value))

    first = review_with_hr_critic(
        original_text="负责 FastAPI 接口开发",
        proposed_text="• 使用 FastAPI 开发接口",
        section_name="项目经历",
        jd_text="需要 FastAPI",
        model_client=object(),
        model_id="gpt-test",
    )
    second = review_with_hr_critic(
        original_text="负责 FastAPI 接口开发",
        proposed_text="• 使用 FastAPI 开发接口",
        section_name="项目经历",
        jd_text="需要 FastAPI",
        model_client=object(),
        model_id="gpt-test",
    )

    assert first.is_passed is second.is_passed is True
    assert calls == 1
