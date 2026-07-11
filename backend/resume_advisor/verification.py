from __future__ import annotations

import re
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field

from backend.agents.cache import build_cache_key, get_agent_cache, set_agent_cache


FactStatus = Literal["supported", "needs_user", "unsupported"]
_ADVISOR_CACHE_SCHEMA_VERSION = "resume-advisor-v1"

_QUANTITATIVE_PATTERN = (
    r"(?<![A-Za-z0-9])(?:\d+(?:\.\d+)?\s*(?:%|％|倍|x|X|ms|毫秒|秒|分钟|小时|天|周|月|年|"
    r"人|次|个|万|亿|k|K|w|W|QPS|TPS|DAU|MAU|PV|UV|GB|MB|KB|元|¥|\$))"
)
_DATE_PATTERN = r"(?:20\d{2}|19\d{2})(?:[./年-]\s?(?:0?[1-9]|1[0-2])(?:月)?)?"
_ORG_PATTERN = r"[\u4e00-\u9fa5A-Za-z0-9·&（）()]{2,32}(?:大学|学院|公司|集团|银行|证券|科技|实验室|研究院)"
_TECH_PATTERN = r"\b[A-Za-z][A-Za-z0-9+#./_-]{1,}\b"
_ROLE_TERMS = ("主导", "牵头", "负责人", "架构师", "技术负责人", "owner", "lead", "owned")
_RESULT_TERMS = ("提升", "降低", "增长", "缩短", "节省", "减少", "达成", "带来", "实现")
_TECH_STOP_WORDS = {
    "and", "api", "app", "css", "for", "from", "http", "json", "or", "the", "to", "ui",
    "web", "with", "开发", "接口", "项目", "负责", "参与", "优化", "系统",
}
_CJK_TECH_TERMS = (
    "消息队列", "分布式", "微服务", "云原生", "容器化", "缓存", "数据库", "高并发",
    "性能优化", "自动化测试", "机器学习", "深度学习", "大模型", "数据分析", "数据可视化",
    "推荐系统", "检索增强", "异步任务", "爬虫", "服务端渲染",
)


class FactIssue(BaseModel):
    claim: str
    category: Literal["quantitative", "date", "organization", "skill", "role", "result"]
    status: FactStatus
    message: str
    evidence_refs: list[str] = Field(default_factory=list)


class FactVerificationResult(BaseModel):
    status: FactStatus
    fact_issues: list[FactIssue] = Field(default_factory=list)

    @property
    def is_supported(self) -> bool:
        return self.status == "supported"


class QualityReviewResult(BaseModel):
    is_passed: bool
    score: int = Field(ge=0, le=100)
    issues: list[str] = Field(default_factory=list)
    reviewer: Literal["local_gate", "hr_critic"] = "local_gate"


class SuggestionDraft(BaseModel):
    proposed_text: str = Field(min_length=1, max_length=12000)
    issue: str = Field(min_length=1, max_length=1000)
    rationale: str = Field(min_length=1, max_length=3000)
    expected_impact: str = Field(min_length=1, max_length=1000)
    priority: Literal["high", "medium", "low"] = "medium"


def _matches(pattern: str, text: str) -> list[str]:
    return list(dict.fromkeys(match.group(0).strip() for match in re.finditer(pattern, text, flags=re.IGNORECASE)))


def _contains(value: str, text: str) -> bool:
    return value.casefold() in text.casefold()


def _claim_status(claim: str, evidence: str, denied: str) -> FactStatus:
    if _contains(claim, denied):
        return "unsupported"
    if _contains(claim, evidence):
        return "supported"
    return "needs_user"


def _issue_message(category: str, claim: str, status: FactStatus) -> str:
    prefix = "用户已明确否认" if status == "unsupported" else "缺少可追溯证据"
    labels = {
        "quantitative": "量化结果",
        "date": "日期或年限",
        "organization": "机构名称",
        "skill": "技能或技术栈",
        "role": "角色升级表述",
        "result": "结果声明",
    }
    return f"{prefix}：{labels[category]}「{claim}」。"


def _append_new_claims(
    issues: list[FactIssue],
    *,
    category: str,
    proposed_claims: list[str],
    original_and_evidence: str,
    denied: str,
) -> None:
    for claim in proposed_claims:
        status = _claim_status(claim, original_and_evidence, denied)
        if status == "supported":
            continue
        issues.append(
            FactIssue(
                claim=claim,
                category=category,
                status=status,
                message=_issue_message(category, claim, status),
            )
        )


def verify_suggestion_facts(
    *,
    original_text: str,
    proposed_text: str,
    resume_evidence_texts: list[str] | None = None,
    confirmed_facts: list[dict[str, Any]] | None = None,
    jd_text: str = "",
) -> FactVerificationResult:
    """Verify claims using resume/user evidence only; JD is intentionally never evidence."""
    del jd_text  # Kept for callers, deliberately excluded from the evidence set.

    confirmed_facts = confirmed_facts or []
    evidence_parts = [original_text, *(resume_evidence_texts or [])]
    evidence_parts.extend(
        str(fact.get("claimValue") or "")
        for fact in confirmed_facts
        if str(fact.get("status") or "") == "confirmed"
    )
    evidence = "\n".join(part for part in evidence_parts if part)
    denied = "\n".join(
        str(fact.get("claimValue") or "")
        for fact in confirmed_facts
        if str(fact.get("status") or "") == "denied"
    )
    issues: list[FactIssue] = []

    _append_new_claims(
        issues,
        category="quantitative",
        proposed_claims=_matches(_QUANTITATIVE_PATTERN, proposed_text),
        original_and_evidence=evidence,
        denied=denied,
    )
    _append_new_claims(
        issues,
        category="date",
        proposed_claims=_matches(_DATE_PATTERN, proposed_text),
        original_and_evidence=evidence,
        denied=denied,
    )
    _append_new_claims(
        issues,
        category="organization",
        proposed_claims=_matches(_ORG_PATTERN, proposed_text),
        original_and_evidence=evidence,
        denied=denied,
    )

    tech_claims = [
        token for token in _matches(_TECH_PATTERN, proposed_text)
        if token.casefold() not in _TECH_STOP_WORDS
    ]
    tech_claims.extend(term for term in _CJK_TECH_TERMS if _contains(term, proposed_text))
    _append_new_claims(
        issues,
        category="skill",
        proposed_claims=tech_claims,
        original_and_evidence=evidence,
        denied=denied,
    )
    _append_new_claims(
        issues,
        category="role",
        proposed_claims=[term for term in _ROLE_TERMS if _contains(term, proposed_text)],
        original_and_evidence=evidence,
        denied=denied,
    )
    _append_new_claims(
        issues,
        category="result",
        proposed_claims=[term for term in _RESULT_TERMS if _contains(term, proposed_text)],
        original_and_evidence=evidence,
        denied=denied,
    )

    if any(issue.status == "unsupported" for issue in issues):
        status: FactStatus = "unsupported"
    elif issues:
        status = "needs_user"
    else:
        status = "supported"
    return FactVerificationResult(status=status, fact_issues=issues)


def review_suggestion_quality(
    *,
    original_text: str,
    proposed_text: str,
    evidence_block_ids: list[str],
    fact_status: FactStatus,
) -> QualityReviewResult:
    """Keep the deterministic gate limited to copyability and evidence safety."""
    issues: list[str] = []
    clean_proposed = proposed_text.strip()
    if not clean_proposed:
        issues.append("建议文本不能为空")
    if not evidence_block_ids:
        issues.append("建议缺少简历证据引用")
    if fact_status != "supported":
        issues.append("事实尚未核验通过")
    score = max(0, 100 - 40 * len(issues))
    return QualityReviewResult(is_passed=not issues, score=score, issues=issues)


def draft_resume_suggestion(
    *,
    original_text: str,
    section_name: str,
    jd_requirements: list[str],
    model_client: Any | None = None,
    model_id: str = "",
    revision_feedback: str = "",
    user_id: Any = "default",
    on_delta: Callable[[str], None] | None = None,
    on_cache_event: Callable[[str, bool], None] | None = None,
    on_provider_usage: Callable[[str, dict[str, Any]], None] | None = None,
) -> SuggestionDraft:
    """Create one conservative structured draft, optionally using the existing copywriter model."""
    text = original_text.strip()
    if model_client is None or not model_id:
        compact = re.sub(r"\s+", " ", text)
        compact = re.sub(r"^[-•·*]\s*", "", compact)
        return SuggestionDraft(
            proposed_text=f"• {compact}" if compact else compact,
            issue="将已有事实整理为一条可快速扫描的简历要点。",
            rationale="本地保守草拟：只调整项目符号和空白，后续仍需通过事实与质量门。",
            expected_impact="让招聘者更容易定位已有事实。",
            priority="high" if section_name in {"project_experience", "work_experience"} else "medium",
        )

    try:
        from backend.memory.preference_db import PreferenceDB

        preference_rules = [
            str(item).strip()
            for item in PreferenceDB().get_preferences(str(user_id), section_name)
            if str(item).strip()
        ]
    except Exception:
        preference_rules = []

    cache_key = build_cache_key(
        "resume_advisor_draft_v1",
        model_id,
        original_text,
        section_name,
        jd_requirements,
        revision_feedback,
        preference_rules,
        schema_version=_ADVISOR_CACHE_SCHEMA_VERSION,
        tool_version="resume-copywriter-v1",
    )
    cached = get_agent_cache("resume_advisor_draft_v1", cache_key)
    if isinstance(cached, dict):
        try:
            draft = SuggestionDraft.model_validate(cached)
            if on_cache_event:
                on_cache_event("resume_advisor_draft_v1", True)
            return draft
        except Exception:
            pass
    if on_cache_event:
        on_cache_event("resume_advisor_draft_v1", False)

    from backend.agents.resume_copywriter import ResumeCopywriter

    copywriter = ResumeCopywriter(model=model_id, openai_client=model_client)
    decoded_job = {"requirements": jd_requirements}
    try:
        proposed_text = _run_async(
            copywriter.rewrite_section(
                section_name=section_name,
                original_content=text,
                decoded_job=decoded_job,
                goal=(
                    "只优化已有事实的清晰度和可扫描性；不得新增任何技能、角色、数字或结果。"
                    f" 用户本轮修订要求：{revision_feedback.strip()}"
                ),
                user_id=str(user_id),
                on_delta=on_delta,
                preference_rules=preference_rules,
            )
        )
    finally:
        if on_provider_usage:
            try:
                from backend.agents.base import BaseAgent

                on_provider_usage("resume_copywriter", BaseAgent.pop_provider_cache_usage(model_client))
            except Exception:
                on_provider_usage("resume_copywriter", {})
    draft = SuggestionDraft(
        proposed_text=proposed_text,
        issue="根据岗位要求提升已有事实的可扫描性。",
        rationale="由 ResumeCopywriter 生成，并要求后续经过独立事实与质量门。",
        expected_impact="更清晰地呈现与岗位相关的既有职责。",
        priority="high" if section_name in {"project_experience", "work_experience"} else "medium",
    )
    set_agent_cache("resume_advisor_draft_v1", cache_key, draft.model_dump())
    return draft


def decode_jd_requirements(
    *,
    jd_text: str,
    fallback_requirements: list[str],
    model_client: Any | None = None,
    model_id: str = "",
    allow_model_call: bool = True,
    on_cache_event: Callable[[str, bool], None] | None = None,
) -> list[str]:
    """Use the existing JobDecoder when possible; JD remains a requirement source only."""
    fallback = list(dict.fromkeys(str(item).strip() for item in fallback_requirements if str(item).strip()))
    cache_key = build_cache_key(
        "resume_advisor_jd_decode_v1",
        model_id or "local",
        jd_text,
        fallback,
        schema_version=_ADVISOR_CACHE_SCHEMA_VERSION,
        tool_version="job-decoder-v1",
    )
    cached = get_agent_cache("resume_advisor_jd_decode_v1", cache_key)
    if isinstance(cached, list) and all(isinstance(item, str) for item in cached):
        if on_cache_event:
            on_cache_event("resume_advisor_jd_decode_v1", True)
        return cached
    if on_cache_event:
        on_cache_event("resume_advisor_jd_decode_v1", False)
    if not allow_model_call or model_client is None or not model_id:
        set_agent_cache("resume_advisor_jd_decode_v1", cache_key, fallback)
        return fallback
    try:
        from backend.agents.job_decoder import JobDecoder

        decoded = _run_async(JobDecoder(model=model_id, openai_client=model_client).decode_job(jd_text))
    except Exception:
        return fallback
    values: list[str] = []
    hard = decoded.get("hard_requirements") if isinstance(decoded, dict) else {}
    soft = decoded.get("soft_requirements") if isinstance(decoded, dict) else {}
    for group in (hard or {}, soft or {}):
        for value in group.values():
            if isinstance(value, list):
                values.extend(str(item).strip() for item in value if str(item).strip())
            elif str(value or "").strip():
                values.append(str(value).strip())
    values.extend(str(item).strip() for item in (decoded.get("core_duties") or []) if str(item).strip())
    requirements = list(dict.fromkeys(values))[:20] or fallback
    set_agent_cache("resume_advisor_jd_decode_v1", cache_key, requirements)
    return requirements


def review_with_hr_critic(
    *,
    original_text: str,
    proposed_text: str,
    section_name: str,
    jd_text: str,
    model_client: Any | None = None,
    model_id: str = "",
    on_cache_event: Callable[[str, bool], None] | None = None,
    on_provider_usage: Callable[[str, dict[str, Any]], None] | None = None,
) -> QualityReviewResult:
    """Use HRCritic when a configured model is available; otherwise retain deterministic local gating."""
    local = review_suggestion_quality(
        original_text=original_text,
        proposed_text=proposed_text,
        evidence_block_ids=["quality-gate"],
        fact_status="supported",
    )
    if not local.is_passed or model_client is None or not model_id:
        return local
    cache_key = build_cache_key(
        "resume_advisor_quality_v1",
        model_id,
        original_text,
        proposed_text,
        section_name,
        jd_text,
        schema_version=_ADVISOR_CACHE_SCHEMA_VERSION,
        tool_version="hr-critic-v1",
    )
    cached = get_agent_cache("resume_advisor_quality_v1", cache_key)
    if isinstance(cached, dict):
        try:
            result = QualityReviewResult.model_validate(cached)
            if on_cache_event:
                on_cache_event("resume_advisor_quality_v1", True)
            return result
        except Exception:
            pass
    if on_cache_event:
        on_cache_event("resume_advisor_quality_v1", False)
    try:
        from backend.agents.hr_critic import HRCritic

        evaluation = _run_async(
            HRCritic(model=model_id, openai_client=model_client).evaluate(
                section_name=section_name,
                original_content=original_text,
                optimized_content=proposed_text,
                jd_text=jd_text,
            )
        )
    except Exception:
        return local
    finally:
        if on_provider_usage:
            try:
                from backend.agents.base import BaseAgent

                on_provider_usage("hr_critic", BaseAgent.pop_provider_cache_usage(model_client))
            except Exception:
                on_provider_usage("hr_critic", {})
    critique = str(evaluation.get("critique") or "")
    result = QualityReviewResult(
        is_passed=bool(evaluation.get("is_passed")),
        score=int(evaluation.get("score") or 0),
        issues=[] if evaluation.get("is_passed") else [critique or "HR 质量审查未通过。"],
        reviewer="hr_critic",
    )
    set_agent_cache("resume_advisor_quality_v1", cache_key, result.model_dump())
    return result


def _run_async(coroutine: Any) -> Any:
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    raise RuntimeError("同步 Advisor 草拟器不能在已运行的事件循环中调用模型。")
