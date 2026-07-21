from __future__ import annotations

import json

import backend.resume_advisor.verification as verification
import pytest

from backend.agents.hr_critic import HRCritic, HRCriticOutputError
from backend.resume_advisor.verification import (
    HRCriticInvalidOutputError,
    HRCriticProviderError,
    HRCriticUnavailableError,
    RagEvidenceReviewInvalidOutputError,
    decode_jd_requirements,
    draft_resume_suggestion,
    review_rag_evidence,
    review_suggestion_quality,
    review_with_hr_critic,
    verify_suggestion_facts,
)


def _hr_evaluation(*, failed_dimension: str | None = None) -> dict[str, object]:
    dimensions = {
        name: {
            "verdict": "fail" if name == failed_dimension else "pass",
            "rationale": f"{name} 审核结论。",
            "evidence_basis": ["负责 FastAPI 接口开发"],
        }
        for name in (
            "factual_fidelity",
            "role_jd_relevance",
            "clarity_scannability",
            "recruiting_usefulness",
        )
    }
    return {
        "score": 92 if failed_dimension is None else 62,
        "is_passed": failed_dimension is None,
        **dimensions,
        "critique": "模型审核结论。",
        "suggestions": "模型给出的下一步建议。",
    }


@pytest.mark.parametrize(
    "raw_review",
    [
        lambda review: f"{chr(96) * 3}json\n{review}\n{chr(96) * 3}",
        lambda review: f"```json\\n{review}\\n```",
        lambda review: f"Here is the review: {review}",
        lambda review: f"{review}\\ntrailing commentary",
    ],
)
def test_advisor_hr_review_rejects_wrapped_or_trailing_json(raw_review):
    critic = HRCritic(model="test-model")
    review = json.dumps(_hr_evaluation(), ensure_ascii=False)

    with pytest.raises(HRCriticOutputError):
        critic._parse_advisor_evaluation_result(raw_review(review))


def test_advisor_hr_review_accepts_exactly_one_raw_json_object():
    critic = HRCritic(model="test-model")
    review = json.dumps(_hr_evaluation(), ensure_ascii=False)

    result = critic._parse_advisor_evaluation_result(f"  {review}\n")

    assert result["is_passed"] is True
    assert result["factual_fidelity"]["verdict"] == "pass"


def test_legacy_hr_critic_parser_keeps_the_historic_four_field_contract():
    critic = HRCritic(model="test-model")
    raw_review = json.dumps(
        {
            "score": 88,
            "is_passed": True,
            "critique": "旧链路审核结论。",
            "suggestions": "无。",
        },
        ensure_ascii=False,
    )

    result = critic._parse_evaluation_result(raw_review)

    assert result == {
        "score": 88,
        "is_passed": True,
        "critique": "旧链路审核结论。",
        "suggestions": "无。",
    }


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


def test_new_chinese_responsibility_is_not_supported_by_the_jd():
    result = verify_suggestion_facts(
        original_text="负责 FastAPI 接口开发",
        proposed_text="负责 FastAPI 接口开发，并承担跨部门需求协调职责",
        resume_evidence_texts=["负责 FastAPI 接口开发"],
        confirmed_facts=[],
        jd_text="岗位要求具备跨部门需求协调职责",
    )

    assert result.status == "needs_user"
    assert any(
        issue.category == "role" and issue.claim == "承担跨部门需求协调职责"
        for issue in result.fact_issues
    )


def test_denied_chinese_responsibility_is_unsupported():
    result = verify_suggestion_facts(
        original_text="负责 FastAPI 接口开发",
        proposed_text="负责 FastAPI 接口开发，并承担跨部门需求协调职责",
        resume_evidence_texts=["负责 FastAPI 接口开发"],
        confirmed_facts=[
            {"claimValue": "没有承担跨部门需求协调职责的经历", "status": "denied"},
        ],
    )

    assert result.status == "unsupported"
    assert any(
        issue.category == "role" and issue.status == "unsupported"
        for issue in result.fact_issues
    )


def test_presentation_explanation_is_not_mistaken_for_a_candidate_responsibility():
    result = verify_suggestion_facts(
        original_text="负责 FastAPI 接口开发",
        proposed_text="把已有职责放在更容易看到的位置。",
        resume_evidence_texts=["负责 FastAPI 接口开发"],
        confirmed_facts=[],
    )

    assert result.status == "supported"
    assert result.fact_issues == []


def test_quality_gate_rejects_punctuation_only_resume_rewrite():
    result = review_suggestion_quality(
        original_text="负责 Agent 会话状态、单次运行状态和用户消息的持久化；支持恢复执行。",
        proposed_text="负责 Agent 会话状态、单次运行状态和用户消息的持久化。支持恢复执行。",
        evidence_block_ids=["block-1"],
        fact_status="supported",
    )

    assert result.is_passed is False
    assert any("标点" in issue for issue in result.issues)


def test_quality_gate_rejects_near_identical_sentence_reordering_without_new_value():
    result = review_suggestion_quality(
        original_text=(
            "Agent 状态与可恢复执行：将会话状态、单次运行状态和用户消息分离持久化。"
            "每条用户消息都会创建独立 Agent Run 并交由 RQ Worker 执行；"
            "当 Agent 需要补充事实时，通过 LangGraph interrupt() 暂停。"
        ),
        proposed_text=(
            "Agent 状态与可恢复执行：分离持久化会话状态、单次运行状态与用户消息。"
            "每条用户消息创建独立 Agent Run 并交由 RQ Worker 执行。"
            "当 Agent 需补充事实时，通过 LangGraph interrupt() 暂停会话。"
        ),
        evidence_block_ids=["block-1"],
        fact_status="supported",
    )

    assert result.is_passed is False
    assert any("近似措辞" in issue for issue in result.issues)


def test_new_chinese_capability_assertion_requires_candidate_evidence():
    result = verify_suggestion_facts(
        original_text="负责 FastAPI 接口开发",
        proposed_text="负责 FastAPI 接口开发，熟悉跨部门需求协调。",
        resume_evidence_texts=["负责 FastAPI 接口开发"],
        confirmed_facts=[],
        jd_text="岗位要求熟悉跨部门需求协调",
    )

    assert result.status == "needs_user"
    assert any(
        issue.category == "skill" and issue.claim == "熟悉跨部门需求协调"
        for issue in result.fact_issues
    )


@pytest.mark.parametrize(
    ("proposed_text", "category", "claim"),
    [
        ("候选人能够独立完成跨部门需求协调。", "role", "完成跨部门需求协调"),
        ("候选人拥有独立架构设计能力。", "skill", "拥有独立架构设计能力"),
        ("主要负责跨部门需求协调。", "role", "负责跨部门需求协调"),
    ],
)
def test_modal_or_qualified_assertions_require_candidate_evidence(proposed_text, category, claim):
    result = verify_suggestion_facts(
        original_text="负责 FastAPI 接口开发",
        proposed_text=proposed_text,
        resume_evidence_texts=["负责 FastAPI 接口开发"],
        confirmed_facts=[],
        jd_text="岗位要求跨部门需求协调和架构设计",
    )

    assert result.status == "needs_user"
    assert any(issue.category == category and issue.claim == claim for issue in result.fact_issues)


def test_negated_candidate_assertion_is_not_treated_as_candidate_evidence():
    result = verify_suggestion_facts(
        original_text="负责 FastAPI 接口开发",
        proposed_text="这不表示候选人承担跨部门协调职责。",
        resume_evidence_texts=["负责 FastAPI 接口开发"],
        confirmed_facts=[],
        jd_text="岗位要求跨部门协调职责",
    )

    assert result.status == "supported"
    assert result.fact_issues == []


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

        async def generate_advisor_suggestion(self, **_kwargs):
            nonlocal calls
            calls += 1
            return {
                "proposed_text": "• 使用 FastAPI 开发接口",
                "issue": "模型识别到原文可更聚焦。",
                "rationale": "模型仅重组已有 FastAPI 职责。",
                "expected_impact": "模型预计重点更清晰。",
                "priority": "high",
            }

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

    assert first.model_dump() == second.model_dump() == {
        "proposed_text": "• 使用 FastAPI 开发接口",
        "issue": "模型识别到原文可更聚焦。",
        "rationale": "模型仅重组已有 FastAPI 职责。",
        "expected_impact": "模型预计重点更清晰。",
        "priority": "high",
        "outcome": "revision",
        "affirmation": "",
        "highlight_locations": [],
    }
    assert calls == 1


def test_resume_draft_forwards_provider_deltas_without_masquerading_cache_as_stream(monkeypatch):
    cache: dict[str, object] = {}
    cache_events: list[tuple[str, bool]] = []
    first_deltas: list[str] = []
    cached_deltas: list[str] = []

    class FakeResumeCopywriter:
        def __init__(self, **_kwargs):
            pass

        async def generate_advisor_suggestion(self, **kwargs):
            kwargs["on_delta"]("• 使用 FastAPI 开发接口")
            return {
                "proposed_text": "• 使用 FastAPI 开发接口",
                "issue": "模型识别到原文可更聚焦。",
                "rationale": "模型仅重组已有 FastAPI 职责。",
                "expected_impact": "模型预计重点更清晰。",
                "priority": "high",
            }

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
    assert first_deltas == ["• 使用 FastAPI 开发接口"]
    assert cached_deltas == []
    assert cache_events == [
        ("resume_advisor_draft_v2", False),
        ("resume_advisor_draft_v2", True),
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

        async def generate_advisor_suggestion(self, **kwargs):
            calls.append(str(kwargs["user_id"]))
            return {
                "proposed_text": f"{kwargs['user_id']}:{'|'.join(kwargs['preference_rules'])}",
                "issue": "模型问题",
                "rationale": "模型理由",
                "expected_impact": "模型影响",
                "priority": "medium",
            }

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

        async def evaluate_advisor_suggestion(self, **_kwargs):
            nonlocal calls
            calls += 1
            return _hr_evaluation()

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
    third = review_with_hr_critic(
        original_text="负责 FastAPI 接口开发",
        proposed_text="• 使用 FastAPI 开发接口",
        section_name="项目经历",
        jd_text="需要 FastAPI",
        resume_evidence_texts=["曾使用 Redis 缓存热点查询"],
        confirmed_facts=[{"status": "confirmed", "claimValue": "曾使用 Redis 缓存热点查询"}],
        model_client=object(),
        model_id="gpt-test",
    )

    assert first.is_passed is second.is_passed is True
    assert third.is_passed is True
    assert first.reviewer == "hr_critic"
    assert first.hr_review["factual_fidelity"]["verdict"] == "pass"
    assert calls == 2


def test_hr_review_requires_a_model_produced_passed_decision_and_forwards_evidence(monkeypatch):
    calls: list[dict[str, object]] = []

    class FakeHRCritic:
        def __init__(self, **_kwargs):
            pass

        async def evaluate_advisor_suggestion(self, **kwargs):
            calls.append(kwargs)
            return _hr_evaluation()

    monkeypatch.setattr("backend.agents.hr_critic.HRCritic", FakeHRCritic)
    monkeypatch.setattr(verification, "get_agent_cache", lambda *_args: None)
    monkeypatch.setattr(verification, "set_agent_cache", lambda *_args: None)

    result = review_with_hr_critic(
        original_text="负责 FastAPI 接口开发",
        proposed_text="• 使用 FastAPI 开发接口，并使用 Redis 缓存热点查询",
        section_name="项目经历",
        jd_text="需要 FastAPI 和 Redis",
        resume_evidence_texts=["负责 FastAPI 接口开发", "使用 Redis 缓存热点查询"],
        confirmed_facts=[{"status": "confirmed", "claimValue": "使用 Redis 缓存热点查询"}],
        model_client=object(),
        model_id="gpt-test",
    )

    assert result.is_passed is True
    assert result.reviewer == "hr_critic"
    assert result.hr_review["role_jd_relevance"]["verdict"] == "pass"
    assert calls[0]["resume_evidence_texts"] == ["负责 FastAPI 接口开发", "使用 Redis 缓存热点查询"]
    assert calls[0]["confirmed_facts"] == ["使用 Redis 缓存热点查询"]


def test_hr_review_returns_a_model_produced_rejection_without_falling_back(monkeypatch):
    class FakeHRCritic:
        def __init__(self, **_kwargs):
            pass

        async def evaluate_advisor_suggestion(self, **_kwargs):
            return _hr_evaluation(failed_dimension="clarity_scannability")

    monkeypatch.setattr("backend.agents.hr_critic.HRCritic", FakeHRCritic)
    monkeypatch.setattr(verification, "get_agent_cache", lambda *_args: None)
    monkeypatch.setattr(verification, "set_agent_cache", lambda *_args: None)

    result = review_with_hr_critic(
        original_text="负责 FastAPI 接口开发",
        proposed_text="• 使用 FastAPI 开发接口",
        section_name="项目经历",
        jd_text="需要 FastAPI",
        model_client=object(),
        model_id="gpt-test",
    )

    assert result.is_passed is False
    assert result.reviewer == "hr_critic"
    assert result.hr_review["clarity_scannability"]["verdict"] == "fail"
    assert result.issues == ["模型审核结论。"]


def test_hr_review_fails_closed_when_no_model_is_configured():
    with pytest.raises(HRCriticUnavailableError):
        review_with_hr_critic(
            original_text="负责 FastAPI 接口开发",
            proposed_text="• 使用 FastAPI 开发接口",
            section_name="项目经历",
            jd_text="需要 FastAPI",
        )


def test_hr_review_fails_closed_when_the_provider_fails(monkeypatch):
    class FakeHRCritic:
        def __init__(self, **_kwargs):
            pass

        async def evaluate_advisor_suggestion(self, **_kwargs):
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr("backend.agents.hr_critic.HRCritic", FakeHRCritic)
    monkeypatch.setattr(verification, "get_agent_cache", lambda *_args: None)
    monkeypatch.setattr(verification, "set_agent_cache", lambda *_args: None)

    with pytest.raises(HRCriticProviderError):
        review_with_hr_critic(
            original_text="负责 FastAPI 接口开发",
            proposed_text="• 使用 FastAPI 开发接口",
            section_name="项目经历",
            jd_text="需要 FastAPI",
            model_client=object(),
            model_id="gpt-test",
        )


def test_hr_review_fails_closed_when_the_structured_contract_is_invalid(monkeypatch):
    class FakeHRCritic:
        def __init__(self, **_kwargs):
            pass

        async def evaluate_advisor_suggestion(self, **_kwargs):
            return {"score": 90, "is_passed": True, "critique": "缺字段", "suggestions": "无"}

    monkeypatch.setattr("backend.agents.hr_critic.HRCritic", FakeHRCritic)
    monkeypatch.setattr(verification, "get_agent_cache", lambda *_args: None)
    monkeypatch.setattr(verification, "set_agent_cache", lambda *_args: None)

    with pytest.raises(HRCriticInvalidOutputError):
        review_with_hr_critic(
            original_text="负责 FastAPI 接口开发",
            proposed_text="• 使用 FastAPI 开发接口",
            section_name="项目经历",
            jd_text="需要 FastAPI",
            model_client=object(),
            model_id="gpt-test",
        )


def test_rag_evidence_reviewer_calls_the_model_and_preserves_selected_provenance(monkeypatch):
    calls: list[dict[str, object]] = []

    class FakeRagEvidenceReviewer:
        def __init__(self, **_kwargs):
            pass

        async def review(self, **kwargs):
            calls.append(kwargs)
            from backend.agents.rag_evidence_reviewer import RagEvidenceReview

            return RagEvidenceReview(
                selected_chunk_ids=["chunk-fastapi"],
                relevance_summary="该片段直接说明已有 FastAPI 接口开发经历。",
                uncovered_requirements=["Redis"],
            )

    monkeypatch.setattr("backend.agents.rag_evidence_reviewer.RagEvidenceReviewer", FakeRagEvidenceReviewer)
    monkeypatch.setattr(verification, "get_agent_cache", lambda *_args: None)
    monkeypatch.setattr(verification, "set_agent_cache", lambda *_args: None)

    result = review_rag_evidence(
        jd_text="需要 FastAPI 与 Redis 经验",
        jd_requirements=["FastAPI", "Redis"],
        candidates=[
            {"id": "chunk-fastapi", "content": "负责 FastAPI 接口开发", "sourceBlockIds": ["block-1"]},
            {"id": "chunk-other", "content": "参与用户访谈", "sourceBlockIds": ["block-2"]},
        ],
        model_client=object(),
        model_id="gpt-test",
        user_id="u1",
    )

    assert result.selected_chunk_ids == ["chunk-fastapi"]
    assert result.uncovered_requirements == ["Redis"]
    assert calls[0]["candidates"][0]["sourceBlockIds"] == ["block-1"]


def test_rag_evidence_reviewer_rejects_an_unknown_chunk_id(monkeypatch):
    class FakeRagEvidenceReviewer:
        def __init__(self, **_kwargs):
            pass

        async def review(self, **_kwargs):
            from backend.agents.rag_evidence_reviewer import RagEvidenceReview

            return RagEvidenceReview(
                selected_chunk_ids=["not-retrieved"],
                relevance_summary="错误选择。",
            )

    monkeypatch.setattr("backend.agents.rag_evidence_reviewer.RagEvidenceReviewer", FakeRagEvidenceReviewer)
    monkeypatch.setattr(verification, "get_agent_cache", lambda *_args: None)
    monkeypatch.setattr(verification, "set_agent_cache", lambda *_args: None)

    with pytest.raises(RagEvidenceReviewInvalidOutputError):
        review_rag_evidence(
            jd_text="需要 FastAPI",
            jd_requirements=["FastAPI"],
            candidates=[{"id": "chunk-fastapi", "content": "负责 FastAPI 接口开发"}],
            model_client=object(),
            model_id="gpt-test",
        )
