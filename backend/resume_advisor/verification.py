from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field, model_validator

from backend.agents.cache import build_cache_key, get_agent_cache, set_agent_cache


FactStatus = Literal["supported", "needs_user", "unsupported"]
_ADVISOR_CACHE_SCHEMA_VERSION = "resume-advisor-v2"


class HRCriticReviewError(RuntimeError):
    """Base error for a required independent HR review that cannot be trusted."""

    model_status: Literal["unavailable", "failed", "invalid_output"] = "failed"


class HRCriticUnavailableError(HRCriticReviewError):
    """Raised when no configured model can perform the required HR review."""

    model_status = "unavailable"


class HRCriticProviderError(HRCriticReviewError):
    """Raised when the HRCritic provider invocation does not complete."""

    model_status = "failed"


class HRCriticInvalidOutputError(HRCriticReviewError):
    """Raised when HRCritic output cannot satisfy the required review contract."""

    model_status = "invalid_output"


class RagEvidenceReviewError(RuntimeError):
    """A required model review of retrieved evidence could not be trusted."""

    model_status: Literal["unavailable", "failed", "invalid_output"] = "failed"


class RagEvidenceReviewUnavailableError(RagEvidenceReviewError):
    model_status = "unavailable"


class RagEvidenceReviewInvalidOutputError(RagEvidenceReviewError):
    model_status = "invalid_output"

_QUANTITATIVE_PATTERN = (
    r"(?<![A-Za-z0-9])(?:\d+(?:\.\d+)?\s*(?:%|％|倍|x|X|ms|毫秒|秒|分钟|小时|天|周|月|年|"
    r"人|次|个|万|亿|k|K|w|W|QPS|TPS|DAU|MAU|PV|UV|GB|MB|KB|元|¥|\$))"
)
_DATE_PATTERN = r"(?:20\d{2}|19\d{2})(?:[./年-]\s?(?:0?[1-9]|1[0-2])(?:月)?)?"
_ORG_PATTERN = r"[\u4e00-\u9fa5A-Za-z0-9·&（）()]{2,32}(?:大学|学院|公司|集团|银行|证券|科技|实验室|研究院)"
_TECH_PATTERN = r"\b[A-Za-z][A-Za-z0-9+#./_-]{1,}\b"
_ROLE_TERMS = ("主导", "牵头", "负责人", "架构师", "技术负责人", "owner", "lead", "owned")
_RESULT_TERMS = ("提升", "降低", "增长", "缩短", "节省", "减少", "达成", "带来", "实现")
_ASSERTION_PUNCTUATION = r"[，,。；;：:！!？?\n]"
_ASSERTION_CONNECTOR = r"(?:并且|以及|同时|并|且|及|和)"
_ASSERTION_BOUNDARY = rf"(?:^|{_ASSERTION_PUNCTUATION}|{_ASSERTION_CONNECTOR})"
_ASSERTION_SUBJECT = r"(?:(?:候选人|该候选人|申请人|本人|你)\s*)?"
_ASSERTION_QUALIFIERS = r"(?:(?:能够|能|可|会|已|曾|将|主要|独立)\s*)*"
_ACTION_VERBS = (
    r"(?:承担|负责|协助|主导|推动|协调|管理|统筹|组织|对接|维护|实施|执行|制定|"
    r"搭建|开发|测试|分析|处理|跟进|参与|完成)"
)
_CAPABILITY_VERBS = r"(?:具备|掌握|熟悉|擅长|精通|拥有|具有)"
_NON_ASSERTIVE_PREFIXES = (
    "不表示", "并非", "不是", "不", "未", "没有", "无", "无法", "不能",
    "JD", "岗位要求", "职位要求", "招聘要求", "假设", "如果", "是否",
)
_ACTION_ASSERTION_RE = re.compile(
    rf"{_ASSERTION_BOUNDARY}\s*[•·*-]?\s*{_ASSERTION_SUBJECT}{_ASSERTION_QUALIFIERS}"
    rf"(?P<claim>{_ACTION_VERBS}(?![的地得])[^\n，,。；;！!？?]{{2,48}}?)"
    rf"(?=$|{_ASSERTION_PUNCTUATION}|{_ASSERTION_CONNECTOR}(?={_ACTION_VERBS}))"
)
_ACTION_SUBJECT_ASSERTION_RE = re.compile(
    rf"(?:候选人|该候选人|申请人|本人)\s*{_ASSERTION_QUALIFIERS}"
    rf"(?P<claim>{_ACTION_VERBS}(?![的地得])[^\n，,。；;！!？?]{{2,48}}?)"
    rf"(?=$|{_ASSERTION_PUNCTUATION}|{_ASSERTION_CONNECTOR}(?={_ACTION_VERBS}))"
)
_CAPABILITY_ASSERTION_RE = re.compile(
    rf"{_ASSERTION_BOUNDARY}\s*[•·*-]?\s*{_ASSERTION_SUBJECT}{_ASSERTION_QUALIFIERS}"
    rf"(?P<claim>{_CAPABILITY_VERBS}(?![的地得])[^\n，,。；;！!？?]{{2,48}}?)"
    rf"(?=$|{_ASSERTION_PUNCTUATION}|{_ASSERTION_CONNECTOR}(?={_CAPABILITY_VERBS}))"
)
_CAPABILITY_SUBJECT_ASSERTION_RE = re.compile(
    rf"(?:候选人|该候选人|申请人|本人)\s*{_ASSERTION_QUALIFIERS}"
    rf"(?P<claim>{_CAPABILITY_VERBS}(?![的地得])[^\n，,。；;！!？?]{{2,48}}?)"
    rf"(?=$|{_ASSERTION_PUNCTUATION}|{_ASSERTION_CONNECTOR}(?={_CAPABILITY_VERBS}))"
)
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
    hr_review: dict[str, Any] = Field(default_factory=dict)


class SuggestionDraft(BaseModel):
    outcome: Literal["revision", "affirmation"] = "revision"
    proposed_text: str = Field(default="", max_length=12000)
    issue: str = Field(min_length=1, max_length=1000)
    rationale: str = Field(min_length=1, max_length=3000)
    expected_impact: str = Field(min_length=1, max_length=1000)
    priority: Literal["high", "medium", "low"] = "medium"
    affirmation: str = Field(default="", max_length=3000)
    highlight_locations: list[str] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def require_content_for_the_selected_outcome(self) -> "SuggestionDraft":
        if self.outcome == "revision" and not self.proposed_text.strip():
            raise ValueError("revision output requires proposed_text")
        if self.outcome == "affirmation" and not self.affirmation.strip():
            raise ValueError("affirmation output requires affirmation")
        if self.outcome == "affirmation" and not self.highlight_locations:
            raise ValueError("affirmation output requires highlight_locations")
        return self


def _matches(pattern: str, text: str) -> list[str]:
    return list(dict.fromkeys(match.group(0).strip() for match in re.finditer(pattern, text, flags=re.IGNORECASE)))


def _has_non_assertive_prefix(text: str, claim_start: int) -> bool:
    clause_start = max(text.rfind(marker, 0, claim_start) for marker in "，,。；;：:！!？?\n") + 1
    prefix = text[clause_start:claim_start]
    return any(marker in prefix for marker in _NON_ASSERTIVE_PREFIXES)


def _assertion_claims(patterns: tuple[re.Pattern[str], ...], text: str) -> list[str]:
    """Return explicit candidate assertions, not explanatory references to resume text."""
    return list(dict.fromkeys(
        re.sub(r"\s+", " ", match.group("claim")).strip()
        for pattern in patterns
        for match in pattern.finditer(text)
        if match.group("claim").strip()
        and not _has_non_assertive_prefix(text, match.start("claim"))
    ))


def _contains(value: str, text: str) -> bool:
    def normalise_numbers(item: str) -> str:
        translated = item.translate(str.maketrans("零一二三四五六七八九两", "01234567892"))
        return re.sub(r"\s+", "", translated)

    return normalise_numbers(value).casefold() in normalise_numbers(text).casefold()


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
        "role": "职责或角色声明",
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
        proposed_claims=[
            *tech_claims,
            *_assertion_claims(
                (_CAPABILITY_ASSERTION_RE, _CAPABILITY_SUBJECT_ASSERTION_RE),
                proposed_text,
            ),
        ],
        original_and_evidence=evidence,
        denied=denied,
    )
    _append_new_claims(
        issues,
        category="role",
        proposed_claims=[
            *(term for term in _ROLE_TERMS if _contains(term, proposed_text)),
            *_assertion_claims(
                (_ACTION_ASSERTION_RE, _ACTION_SUBJECT_ASSERTION_RE),
                proposed_text,
            ),
        ],
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


def is_presentation_only_rewrite(*, original_text: str, proposed_text: str) -> bool:
    """Detect edits that only shuffle formatting or nearly identical wording.

    An Advisor suggestion exists to improve JD-relevant evidence expression, not to
    spend a turn replacing punctuation or breaking one sentence into several.  This
    intentionally catches the latter while leaving genuine, evidence-backed rewrites
    to the independent HR review.
    """
    def normalized(value: str) -> str:
        return "".join(
            character
            for character in unicodedata.normalize("NFKC", value).casefold()
            if not character.isspace()
            and not unicodedata.category(character).startswith(("P", "Z"))
        )

    original = normalized(original_text)
    proposed = normalized(proposed_text)
    if not original or not proposed:
        return False
    if original == proposed:
        return True
    if min(len(original), len(proposed)) < 48:
        return False

    sequence_similarity = difflib.SequenceMatcher(None, original, proposed).ratio()
    original_counts = {character: original.count(character) for character in set(original)}
    proposed_counts = {character: proposed.count(character) for character in set(proposed)}
    shared_characters = sum(
        min(original_counts.get(character, 0), proposed_counts.get(character, 0))
        for character in set(original_counts) | set(proposed_counts)
    )
    content_overlap = shared_characters / max(len(original), len(proposed))
    return sequence_similarity >= 0.90 and content_overlap >= 0.93


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
    elif is_presentation_only_rewrite(original_text=original_text, proposed_text=clean_proposed):
        issues.append("建议仅调整标点、断句或近似措辞，未形成与 JD 相关的实质优化")
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
    context_snapshot: str = "",
    user_id: Any = "default",
    on_delta: Callable[[str], None] | None = None,
    on_cache_event: Callable[[str, bool], None] | None = None,
    on_provider_usage: Callable[[str, dict[str, Any]], None] | None = None,
) -> SuggestionDraft:
    """Ask ResumeCopywriter for one structured draft; this harness never invents copy fields."""
    text = original_text.strip()
    if model_client is None or not model_id:
        raise ValueError("ResumeCopywriter requires a configured model")

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
        "resume_advisor_draft_v2",
        model_id,
        original_text,
        section_name,
        jd_requirements,
        revision_feedback,
        context_snapshot,
        preference_rules,
        schema_version=_ADVISOR_CACHE_SCHEMA_VERSION,
        tool_version="resume-copywriter-structured-v1",
    )
    cached = get_agent_cache("resume_advisor_draft_v2", cache_key)
    if isinstance(cached, dict):
        try:
            draft = SuggestionDraft.model_validate(cached)
            if on_cache_event:
                on_cache_event("resume_advisor_draft_v2", True)
            return draft
        except Exception:
            pass
    if on_cache_event:
        on_cache_event("resume_advisor_draft_v2", False)

    from backend.agents.resume_copywriter import ResumeCopywriter

    copywriter = ResumeCopywriter(model=model_id, openai_client=model_client)
    try:
        generated = _run_async(
            copywriter.generate_advisor_suggestion(
                section_name=section_name,
                original_content=text,
                jd_requirements=jd_requirements,
                revision_feedback=revision_feedback,
                context_snapshot=context_snapshot,
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
    draft = SuggestionDraft.model_validate(generated)
    set_agent_cache("resume_advisor_draft_v2", cache_key, draft.model_dump())
    return draft


def decode_jd_requirements(
    *,
    jd_text: str,
    fallback_requirements: list[str],
    model_client: Any | None = None,
    model_id: str = "",
    allow_model_call: bool = True,
    require_model: bool = False,
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
        if require_model:
            raise ValueError("JobDecoder requires a configured model")
        set_agent_cache("resume_advisor_jd_decode_v1", cache_key, fallback)
        return fallback
    try:
        from backend.agents.job_decoder import JobDecoder

        decoded = _run_async(JobDecoder(model=model_id, openai_client=model_client).decode_job(jd_text))
    except Exception:
        if require_model:
            raise
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


def review_rag_evidence(
    *,
    jd_text: str,
    jd_requirements: list[str],
    candidates: list[dict[str, Any]],
    model_client: Any | None = None,
    model_id: str = "",
    user_id: Any = "default",
    on_cache_event: Callable[[str, bool], None] | None = None,
    on_provider_usage: Callable[[str, dict[str, Any]], None] | None = None,
) -> Any:
    """Require an LLM to select attributable evidence from RAG candidates."""
    if model_client is None or not model_id:
        raise RagEvidenceReviewUnavailableError("RAG evidence review requires a configured model")
    normalized_candidates = [
        candidate for candidate in candidates
        if isinstance(candidate, dict)
        and str(candidate.get("id") or candidate.get("chunkId") or "").strip()
        and str(candidate.get("content") or "").strip()
    ]
    if not normalized_candidates:
        raise RagEvidenceReviewInvalidOutputError("RAG returned no usable evidence candidates")
    allowed_ids = {
        str(candidate.get("id") or candidate.get("chunkId") or "")
        for candidate in normalized_candidates
    }
    cache_key = build_cache_key(
        "resume_advisor_rag_evidence_v1",
        model_id,
        jd_text,
        jd_requirements,
        [
            {
                "id": str(candidate.get("id") or candidate.get("chunkId") or ""),
                "content": str(candidate.get("content") or ""),
                "sourceBlockIds": candidate.get("sourceBlockIds") or (candidate.get("metadata") or {}).get("sourceBlockIds") or [],
            }
            for candidate in normalized_candidates
        ],
        schema_version=_ADVISOR_CACHE_SCHEMA_VERSION,
        tool_version="resume-rag-evidence-reviewer-v1",
    )
    cached = get_agent_cache("resume_advisor_rag_evidence_v1", cache_key)
    if isinstance(cached, dict):
        try:
            from backend.agents.rag_evidence_reviewer import RagEvidenceReview

            result = RagEvidenceReview.model_validate(cached)
            unknown_ids = set(result.selected_chunk_ids) - allowed_ids
            if unknown_ids:
                raise RagEvidenceReviewInvalidOutputError(
                    f"Cached RAG evidence review selected unknown chunks: {', '.join(sorted(unknown_ids))}"
                )
            if on_cache_event:
                on_cache_event("resume_advisor_rag_evidence_v1", True)
            return result
        except Exception:
            pass
    if on_cache_event:
        on_cache_event("resume_advisor_rag_evidence_v1", False)
    try:
        from backend.agents.rag_evidence_reviewer import RagEvidenceReviewer

        result = _run_async(
            RagEvidenceReviewer(model=model_id, openai_client=model_client).review(
                jd_text=jd_text,
                jd_requirements=jd_requirements,
                candidates=normalized_candidates,
                user_id=str(user_id),
            )
        )
    except ValueError as exc:
        raise RagEvidenceReviewInvalidOutputError("RAG evidence reviewer returned an invalid contract") from exc
    except Exception as exc:
        raise RagEvidenceReviewError("RAG evidence reviewer invocation failed") from exc
    finally:
        if on_provider_usage:
            try:
                from backend.agents.base import BaseAgent

                on_provider_usage("resume_rag_reviewer", BaseAgent.pop_provider_cache_usage(model_client))
            except Exception:
                on_provider_usage("resume_rag_reviewer", {})
    unknown_ids = set(result.selected_chunk_ids) - allowed_ids
    if unknown_ids:
        raise RagEvidenceReviewInvalidOutputError(
            f"RAG evidence reviewer selected unknown chunks: {', '.join(sorted(unknown_ids))}"
        )
    set_agent_cache("resume_advisor_rag_evidence_v1", cache_key, result.model_dump())
    return result


def review_with_hr_critic(
    *,
    original_text: str,
    proposed_text: str,
    section_name: str,
    jd_text: str,
    resume_evidence_texts: list[str] | None = None,
    confirmed_facts: list[dict[str, Any]] | None = None,
    model_client: Any | None = None,
    model_id: str = "",
    on_cache_event: Callable[[str, bool], None] | None = None,
    on_provider_usage: Callable[[str, dict[str, Any]], None] | None = None,
) -> QualityReviewResult:
    """Require an independent HRCritic decision after deterministic preflight checks."""
    local = review_suggestion_quality(
        original_text=original_text,
        proposed_text=proposed_text,
        evidence_block_ids=["quality-gate"],
        fact_status="supported",
    )
    if not local.is_passed:
        return local
    if model_client is None or not str(model_id).strip():
        raise HRCriticUnavailableError("HRCritic requires a configured model")

    review_evidence = [
        str(item).strip()
        for item in (resume_evidence_texts or [])
        if str(item).strip()
    ]
    review_confirmed_facts = [
        str(fact.get("claimValue") or "")
        for fact in (confirmed_facts or [])
        if str(fact.get("status") or "") == "confirmed"
        and str(fact.get("claimValue") or "").strip()
    ]

    cache_key = build_cache_key(
        "resume_advisor_quality_v1",
        model_id,
        original_text,
        proposed_text,
        section_name,
        jd_text,
        review_evidence,
        review_confirmed_facts,
        schema_version=_ADVISOR_CACHE_SCHEMA_VERSION,
        tool_version="hr-critic-v2",
    )
    cached = get_agent_cache("resume_advisor_quality_v1", cache_key)
    if isinstance(cached, dict):
        try:
            result = _quality_result_from_hr_evaluation(cached.get("hr_review"))
            if on_cache_event:
                on_cache_event("resume_advisor_quality_v1", True)
            return result
        except HRCriticInvalidOutputError:
            raise
    if on_cache_event:
        on_cache_event("resume_advisor_quality_v1", False)
    try:
        from backend.agents.hr_critic import HRCritic, HRCriticOutputError

        evaluation = _run_async(
            HRCritic(model=model_id, openai_client=model_client).evaluate_advisor_suggestion(
                section_name=section_name,
                original_content=original_text,
                optimized_content=proposed_text,
                jd_text=jd_text,
                resume_evidence_texts=review_evidence,
                confirmed_facts=review_confirmed_facts,
            )
        )
    except HRCriticOutputError as exc:
        raise HRCriticInvalidOutputError("HRCritic returned invalid structured output") from exc
    except Exception as exc:
        raise HRCriticProviderError("HRCritic review invocation failed") from exc
    finally:
        if on_provider_usage:
            try:
                from backend.agents.base import BaseAgent

                on_provider_usage("hr_critic", BaseAgent.pop_provider_cache_usage(model_client))
            except Exception:
                on_provider_usage("hr_critic", {})
    result = _quality_result_from_hr_evaluation(evaluation)
    set_agent_cache("resume_advisor_quality_v1", cache_key, result.model_dump())
    return result


def _quality_result_from_hr_evaluation(evaluation: Any) -> QualityReviewResult:
    """Validate and retain the model-produced HR decision without adding user prose."""
    try:
        from backend.agents.hr_critic import HRCriticEvaluation

        structured = HRCriticEvaluation.model_validate(evaluation)
    except Exception as exc:
        raise HRCriticInvalidOutputError("HRCritic review did not match the required schema") from exc

    return QualityReviewResult(
        is_passed=structured.is_passed,
        score=structured.score,
        issues=[] if structured.is_passed else [structured.critique],
        reviewer="hr_critic",
        hr_review=structured.model_dump(mode="json"),
    )


def _run_async(coroutine: Any) -> Any:
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    raise RuntimeError("同步 Advisor 草拟器不能在已运行的事件循环中调用模型。")
