from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from config import Config
from backend.resume_rag import SECTION_IMPORTANCE

from .verification import (
    draft_resume_suggestion,
    decode_jd_requirements,
    review_suggestion_quality,
    review_with_hr_critic,
    SuggestionDraft,
    verify_suggestion_facts,
)
from .tool_runtime import ResumeAdvisorToolRuntime
from .context import build_advisor_context_snapshot


_KEYWORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#./-]{1,}|[\u4e00-\u9fff]{2,}")
_STOP_WORDS = {"负责", "要求", "需要", "相关", "岗位", "经验", "能力", "优先", "我们", "你将", "以及", "进行"}
_FOLLOW_UP_PREFIXES = ("为什么", "为何", "怎么", "如何", "能否", "可以", "解释", "这条", "这个")
_REVISION_HINTS = ("改短", "精简", "精炼", "更克制", "换个说法", "改写", "重写", "语气")
_FIRST_TOKEN_SLO_MS = 10_000
_EDITABLE_BLOCK_KINDS = {"bullet", "paragraph", "table_cell"}
_NON_EDITABLE_SECTION_IDS = {"contact", "objective"}
_ADVISOR_SECTION_BONUSES = {
    "project_experience": 0.40,
    "work_experience": 0.34,
    "research": 0.28,
    "coursework": 0.24,
    "skills": 0.18,
    "education": 0.12,
    "self_introduction": 0.10,
    "generic_section": -0.36,
}
_PERSONAL_FIELD_RE = re.compile(
    r"(?:姓名|性别|年龄|生日|出生(?:日期|年月)?|电话|手机|邮箱|邮件|地址|现居|籍贯|微信|身份证|"
    r"name|gender|age|birth(?:day| date)?|phone|mobile|email|address)\s*[:：]",
    flags=re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?86[-\s]?)?1[3-9]\d{9}(?!\d)")
_DATE_OF_BIRTH_RE = re.compile(r"(?:19|20)\d{2}[./-年]\d{1,2}[./-月]\d{1,2}日?")
_NAME_LIKE_RE = re.compile(r"^[\u4e00-\u9fff]{2,4}$")
_GENERIC_REQUIREMENTS = {
    "负责", "要求", "需要", "相关", "岗位", "经验", "能力", "优先", "我们", "你将", "以及", "进行",
    "熟悉", "掌握", "具备", "良好", "优秀", "开发", "实习", "本科", "学历", "专业", "工作", "团队",
}


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        text = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _elapsed_ms(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None:
        return None
    return max(0, int((end - start).total_seconds() * 1000))


def _public_error_summary(exc: Exception) -> dict[str, Any]:
    return {"errorType": exc.__class__.__name__}


def _verify_with_holder(
    holder: dict[str, Any],
    *,
    original_text: str,
    proposed_text: str,
    resume_evidence_texts: list[str],
    confirmed_facts: list[dict[str, Any]],
    jd_text: str,
) -> dict[str, Any]:
    value = verify_suggestion_facts(
        original_text=original_text,
        proposed_text=proposed_text,
        resume_evidence_texts=resume_evidence_texts,
        confirmed_facts=confirmed_facts,
        jd_text=jd_text,
    )
    holder["value"] = value
    return {"status": value.status, "issueCount": len(value.fact_issues)}


def _review_with_holder(holder: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    value = review_with_hr_critic(**kwargs)
    holder["value"] = value
    return {
        "isPassed": value.is_passed,
        "score": value.score,
        "issueCount": len(value.issues),
        "reviewer": value.reviewer,
    }


def _jd_requirements(jd_text: str) -> list[str]:
    values: list[str] = []
    for token in _KEYWORD_RE.findall(jd_text):
        normalized = token.strip()
        if normalized in _STOP_WORDS or normalized.lower() in {item.lower() for item in _STOP_WORDS}:
            continue
        if normalized not in values:
            values.append(normalized)
    return values[:12]


def _copy_safe_reformat(text: str) -> str:
    """Improve scanability without adding any candidate claim."""
    compact = re.sub(r"\s+", " ", text).strip()
    compact = re.sub(r"^[-•·*]\s*", "", compact)
    return f"• {compact}" if compact else compact


def _normalized_match_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def _effective_section_id(block: dict[str, Any]) -> str:
    section_id = str(block.get("sectionId") or "generic_section").strip() or "generic_section"
    section_name = str(block.get("sectionName") or "")
    if "求职意向" in section_name or "职业目标" in section_name or "意向岗位" in section_name:
        return "objective"
    if "课程" in section_name:
        return "coursework"
    return section_id


def _is_personal_identity_block(block: dict[str, Any]) -> bool:
    section_id = _effective_section_id(block)
    section_name = str(block.get("sectionName") or "")
    text = str(block.get("text") or "").strip()
    if section_id in _NON_EDITABLE_SECTION_IDS:
        return True
    if any(label in section_name for label in ("基本信息", "个人信息", "联系方式", "求职意向", "职业目标")):
        return True
    if _PERSONAL_FIELD_RE.search(text) or _EMAIL_RE.search(text) or _PHONE_RE.search(text) or _DATE_OF_BIRTH_RE.search(text):
        return True
    # DOCX textboxes can be read after an unrelated heading. A bare short Chinese name
    # under a misclassified self-introduction block must still never become rewrite input.
    return section_id in {"self_introduction", "generic_section"} and bool(_NAME_LIKE_RE.fullmatch(text))


def _is_editable_candidate(block: dict[str, Any]) -> bool:
    return (
        str(block.get("kind") or "") in _EDITABLE_BLOCK_KINDS
        and bool(str(block.get("text") or "").strip())
        and not _is_personal_identity_block(block)
    )


def _section_priority(block: dict[str, Any]) -> int:
    section_id = _effective_section_id(block)
    baseline = float(SECTION_IMPORTANCE.get(section_id, SECTION_IMPORTANCE.get("generic_section", 0.0)))
    return int(round((baseline + _ADVISOR_SECTION_BONUSES.get(section_id, 0.0)) * 100))


def _requirement_matches_text(requirement: str, text: Any) -> bool:
    normalized_requirement = _normalized_match_text(requirement)
    return bool(normalized_requirement) and normalized_requirement in _normalized_match_text(text)


def _block_requirement_matches(block: dict[str, Any], requirements: list[str]) -> int:
    text = str(block.get("text") or "")
    return sum(1 for requirement in requirements if _requirement_matches_text(requirement, text))


def _is_actionable_requirement(requirement: str) -> bool:
    normalized = _normalized_match_text(requirement)
    return len(normalized) >= 2 and normalized not in _GENERIC_REQUIREMENTS


class ResumeAdvisorGraph:
    """One-run graph for the evidence-first advisor mode.

    The graph deliberately stops after one question or one suggestion. It does not write the
    original file and it never treats JD text as candidate evidence.
    """

    def __init__(
        self,
        repository: Any,
        *,
        model_client: Any | None = None,
        model_id: str = "",
        model_provider: Any | None = None,
    ):
        self.repository = repository
        self.model_client = model_client
        self.model_id = model_id
        self.model_provider = model_provider
        self.tool_runtime = ResumeAdvisorToolRuntime()

    def _list_session_facts(self, *, user_id: Any, session_id: str) -> list[dict[str, Any]]:
        list_session_facts = getattr(self.repository, "list_session_facts", None)
        if callable(list_session_facts):
            facts = list_session_facts(user_id, session_id)
        else:
            # Older repository fakes only expose the original confirmed-facts method.
            facts = self.repository.list_confirmed_facts(user_id, session_id)
        return [fact for fact in facts if isinstance(fact, dict)]

    @staticmethod
    def _rank_candidate_blocks(blocks: list[dict[str, Any]], requirements: list[str]) -> list[dict[str, Any]]:
        return sorted(
            blocks,
            key=lambda block: (
                -_section_priority(block),
                -_block_requirement_matches(block, requirements),
                int(block.get("order") or 0),
            ),
        )

    @staticmethod
    def _supporting_evidence_blocks(
        *,
        current_block: dict[str, Any],
        all_blocks: list[dict[str, Any]],
        requirements: list[str],
    ) -> list[dict[str, Any]]:
        """Keep the target first and attach a few JD-relevant, non-PII resume facts."""
        selected = [current_block]
        matches = [
            block
            for block in all_blocks
            if block.get("id") != current_block.get("id")
            and _is_editable_candidate(block)
            and _block_requirement_matches(block, requirements)
        ]
        for block in ResumeAdvisorGraph._rank_candidate_blocks(matches, requirements):
            if len(selected) >= 4:
                break
            selected.append(block)
        return selected

    @staticmethod
    def _supporting_user_fact_ids(facts: list[dict[str, Any]], proposed_text: str) -> list[str]:
        proposed = _normalized_match_text(proposed_text)
        if not proposed:
            return []
        fact_ids: list[str] = []
        for fact in facts:
            if fact.get("status") != "confirmed":
                continue
            fact_id = str(fact.get("id") or "")
            if not fact_id:
                continue
            claim_key = str(fact.get("claimKey") or "")
            claim_value = str(fact.get("claimValue") or "")
            if claim_key.startswith("requirement:"):
                if _requirement_matches_text(claim_key.removeprefix("requirement:"), proposed):
                    fact_ids.append(fact_id)
                continue
            terms = [term for term in _KEYWORD_RE.findall(f"{claim_key} {claim_value}") if len(term) >= 2]
            if any(_requirement_matches_text(term, proposed) for term in terms):
                fact_ids.append(fact_id)
        return list(dict.fromkeys(fact_ids))

    @staticmethod
    def _next_missing_requirement(
        *,
        requirements: list[str],
        blocks: list[dict[str, Any]],
        confirmed_facts: list[dict[str, Any]],
        denied_facts: list[dict[str, Any]],
        asked_keys: set[str],
    ) -> str | None:
        resume_text = "\n".join(str(block.get("text") or "") for block in blocks)
        confirmed_text = "\n".join(str(fact.get("claimValue") or "") for fact in confirmed_facts)
        denied_keys = {str(fact.get("claimKey") or "").lower() for fact in denied_facts}
        denied_values = "\n".join(str(fact.get("claimValue") or "") for fact in denied_facts)
        for requirement in requirements:
            normalized = _normalized_match_text(requirement)
            question_key = f"requirement:{normalized}"
            if (
                not _is_actionable_requirement(requirement)
                or _requirement_matches_text(requirement, resume_text)
                or _requirement_matches_text(requirement, confirmed_text)
                or question_key in denied_keys
                or _requirement_matches_text(requirement, denied_values)
                or question_key in asked_keys
            ):
                continue
            return requirement
        return None

    def _ask_for_requirement_evidence(
        self,
        *,
        user_id: Any,
        session_id: str,
        run_id: str,
        requirement: str,
    ) -> dict[str, Any]:
        normalized = _normalized_match_text(requirement)
        question_key = f"requirement:{normalized}"
        message = self.repository.append_turn(
            user_id=user_id,
            session_id=session_id,
            role="assistant",
            content=(
                f"JD 强调「{requirement}」，但我还没有在项目、实习、课程或技能中找到可核验的对应证据。"
                "你是否有真实的相关职责、技术选择或结果？如果没有，请明确说明；我会保留这个真实缺口，不会把 JD 当成你的经历。"
            ),
            message_kind="question",
            run_id=run_id,
            payload={
                "questionKey": question_key,
                "why": "缺少这项事实时，不能在后续建议中新增该声明。",
                "target": "项目/实习经历、相关课程或技能段",
                "evidenceTypes": ["具体职责", "技术选择", "可验证结果"],
            },
        )
        self.repository.update_session(
            user_id,
            session_id,
            session_status="WAITING_FOR_USER",
            active_run_id=run_id,
        )
        self.repository.append_event(
            user_id=user_id,
            session_id=session_id,
            run_id=run_id,
            message_id=message["id"],
            event_type="question",
            payload={"questionKey": question_key},
        )
        self.repository.update_run(user_id=user_id, run_id=run_id, status="PAUSED")
        return {"status": "WAITING_FOR_USER", "message": message}

    @staticmethod
    def _draft_copy(text: str) -> str:
        return _copy_safe_reformat(text)

    def _draft_suggestion(
        self,
        text: str,
        *,
        section_name: str,
        jd_requirements: list[str],
        model_client: Any | None,
        model_id: str,
        revision_feedback: str = "",
        context_snapshot: str = "",
        user_id: Any = "default",
        on_delta: Callable[[str], None] | None = None,
        on_cache_event: Callable[[str, bool], None] | None = None,
        on_provider_usage: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> SuggestionDraft:
        if model_client is None or not model_id:
            return SuggestionDraft(
                proposed_text=self._apply_local_revision_feedback(self._draft_copy(text), revision_feedback),
                issue="将已有事实整理为一条可快速扫描的简历要点。",
                rationale="本地保守草拟：只调整项目符号和空白，后续仍需通过事实与质量门。",
                expected_impact="让招聘者更容易定位已有事实。",
                priority="high" if section_name in {"project_experience", "work_experience"} else "medium",
            )
        return draft_resume_suggestion(
            original_text=text,
            section_name=section_name,
            jd_requirements=jd_requirements,
            model_client=model_client,
            model_id=model_id,
            revision_feedback=revision_feedback,
            context_snapshot=context_snapshot,
            user_id=user_id,
            on_delta=on_delta,
            on_cache_event=on_cache_event,
            on_provider_usage=on_provider_usage,
        )

    def _get_run_snapshot(self, *, user_id: Any, run_id: str) -> dict[str, Any]:
        get_run = getattr(self.repository, "get_run", None)
        if not callable(get_run):
            return {}
        try:
            value = get_run(user_id=user_id, run_id=run_id)
        except Exception:
            return {}
        return value if isinstance(value, dict) else {}

    def _merge_run_telemetry(self, *, user_id: Any, run_id: str, telemetry: dict[str, Any]) -> None:
        merge = getattr(self.repository, "merge_run_telemetry", None)
        if not callable(merge):
            return
        try:
            merge(user_id=user_id, run_id=run_id, telemetry=telemetry)
        except Exception:
            pass

    def _is_cancelled(self, *, user_id: Any, run_id: str) -> bool:
        checker = getattr(self.repository, "is_run_cancelled", None)
        if not callable(checker):
            return False
        return bool(checker(user_id=user_id, run_id=run_id))

    def _cancelled_result(self, *, user_id: Any, session_id: str, run_id: str) -> dict[str, Any]:
        run = self._get_run_snapshot(user_id=user_id, run_id=run_id)
        if str(run.get("status") or "") != "CANCELLED":
            self.repository.update_run(user_id=user_id, run_id=run_id, status="CANCELLED")
            self.repository.append_event(
                user_id=user_id,
                session_id=session_id,
                run_id=run_id,
                event_type="run_cancelled",
                payload={"stage": "run_control"},
            )
        return {"status": "CANCELLED"}

    @staticmethod
    def _provider_first_token_ms(model_client: Any) -> int | None:
        value = getattr(model_client, "_internpath_provider_first_token_ms", None)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return max(0, int(value))
        return None

    def run(self, *, user_id: Any, session_id: str, run_id: str) -> dict[str, Any]:
        session = self.repository.get_session(user_id, session_id)
        if not session:
            raise LookupError("未找到简历优化会话。")

        if self._is_cancelled(user_id=user_id, run_id=run_id):
            return self._cancelled_result(user_id=user_id, session_id=session_id, run_id=run_id)

        self.repository.update_run(user_id=user_id, run_id=run_id, status="RUNNING")
        run_snapshot = self._get_run_snapshot(user_id=user_id, run_id=run_id)
        run_created_at = _parse_timestamp(run_snapshot.get("createdAt"))
        run_started_at = _parse_timestamp(run_snapshot.get("startedAt"))
        queue_ms = _elapsed_ms(run_created_at, run_started_at)
        self.repository.append_event(
            user_id=user_id,
            session_id=session_id,
            run_id=run_id,
            event_type="progress",
            payload={"stage": "refresh_context", "summary": "正在校验简历快照与岗位要求。"},
        )

        model_client, model_id = self._resolve_model(user_id)
        resume_view = self.repository.get_resume_view(user_id, session_id)
        blocks = [block for block in resume_view.get("blocks", []) if isinstance(block, dict)]
        suggestions = self.repository.list_suggestions(user_id, session_id)
        session_facts = self._list_session_facts(user_id=user_id, session_id=session_id)
        confirmed_facts = [fact for fact in session_facts if fact.get("status") == "confirmed"]
        denied_facts = [fact for fact in session_facts if fact.get("status") == "denied"]
        messages = self.repository.list_turns(user_id, session_id)
        follow_up = next(
            (
                message
                for message in reversed(messages)
                if self._is_suggestion_follow_up(message)
            ),
            None,
        )
        active_suggestion = next(
            (
                suggestion
                for suggestion in reversed(suggestions)
                if suggestion.get("status") in {"proposed", "accepted"}
            ),
            None,
        )
        if follow_up and active_suggestion:
            return self._reply_to_suggestion_follow_up(
                user_id=user_id,
                session_id=session_id,
                run_id=run_id,
                user_message=follow_up,
                suggestion=active_suggestion,
            )
        latest_user_message = next(
            (message for message in reversed(messages) if message.get("role") == "user"),
            None,
        )
        implicit_revision = active_suggestion if self._is_suggestion_revision_request(latest_user_message) else None
        if implicit_revision:
            self.repository.update_suggestion_status(user_id, str(implicit_revision["id"]), "needs_revision")
        revision_request = implicit_revision or next(
            (suggestion for suggestion in reversed(suggestions) if suggestion.get("status") == "needs_revision"),
            None,
        )
        rejected_blocks = {
            str(suggestion.get("target", {}).get("blockId") or "")
            for suggestion in suggestions
            if suggestion.get("status") == "rejected"
        }
        denied_question_keys = {
            str(fact.get("claimKey") or "")
            for fact in denied_facts
        }
        denied_blocks = {
            question_key.split(":", 2)[1]
            for question_key in denied_question_keys
            if question_key.startswith("fact:") and len(question_key.split(":", 2)) == 3
        }
        completed_blocks = {
            str(suggestion.get("target", {}).get("blockId") or "")
            for suggestion in suggestions
            if suggestion.get("status") in {"proposed", "accepted", "applied"}
        }

        def block_reference_ids(block: dict[str, Any]) -> set[str]:
            return {
                str(value)
                for value in [block.get("id"), *(block.get("legacyBlockIds") or [])]
                if str(value or "")
            }

        ranking_requirements = _jd_requirements(str(session.get("jdText") or ""))
        candidates = [
            block
            for block in blocks
            if _is_editable_candidate(block)
            and block_reference_ids(block).isdisjoint(rejected_blocks)
            and block_reference_ids(block).isdisjoint(denied_blocks)
            and block_reference_ids(block).isdisjoint(completed_blocks)
        ]

        if revision_request:
            requested_block_id = str(revision_request.get("target", {}).get("blockId") or "")
            candidates = [block for block in blocks if requested_block_id in block_reference_ids(block)]
        else:
            candidates = self._rank_candidate_blocks(candidates, ranking_requirements)
        revision_feedback = str(latest_user_message.get("content") or "") if implicit_revision and latest_user_message else next(
            (
                str(message.get("content") or "")
                for message in reversed(messages)
                if isinstance(message.get("payload"), dict)
                and message["payload"].get("suggestionId") == (revision_request or {}).get("id")
                and message["payload"].get("action") == "needs_revision"
            ),
            "",
        )
        asked_keys = {
            str(message.get("payload", {}).get("questionKey") or "")
            for message in messages
            if isinstance(message.get("payload"), dict)
        }
        missing_requirement = self._next_missing_requirement(
            requirements=ranking_requirements,
            blocks=blocks,
            confirmed_facts=confirmed_facts,
            denied_facts=denied_facts,
            asked_keys=asked_keys,
        )

        # If the resume has no JD-relevant editable evidence at all, clarify the
        # most important gap before polishing an unrelated sentence.
        if (
            candidates
            and not revision_request
            and not any(_block_requirement_matches(block, ranking_requirements) for block in candidates)
            and missing_requirement
        ):
            return self._ask_for_requirement_evidence(
                user_id=user_id,
                session_id=session_id,
                run_id=run_id,
                requirement=missing_requirement,
            )

        if not candidates:
            applied_exists = any(suggestion.get("status") == "applied" for suggestion in suggestions)
            editable_content_exists = any(_is_editable_candidate(block) for block in blocks)
            if missing_requirement and (applied_exists or editable_content_exists):
                return self._ask_for_requirement_evidence(
                    user_id=user_id,
                    session_id=session_id,
                    run_id=run_id,
                    requirement=missing_requirement,
                )

            message = self.repository.append_turn(
                user_id=user_id,
                session_id=session_id,
                role="assistant",
                content="当前简历中没有新的、可在不增加事实的前提下继续优化的段落。请确认是否满意，或告诉我想继续讨论的具体位置。",
                message_kind="completion",
                run_id=run_id,
                payload={"status": "READY_FOR_CONFIRMATION"},
            )
            self.repository.update_session(
                user_id,
                session_id,
                session_status="READY_FOR_CONFIRMATION",
                active_run_id=run_id,
            )
            self.repository.append_event(
                user_id=user_id,
                session_id=session_id,
                run_id=run_id,
                message_id=message["id"],
                event_type="message",
                payload={"messageKind": "completion"},
            )
            self.repository.update_run(user_id=user_id, run_id=run_id, status="COMPLETED")
            return {"status": "READY_FOR_CONFIRMATION", "message": message}

        block = candidates[0]
        original_text = str(block.get("text") or "").strip()
        supporting_blocks = self._supporting_evidence_blocks(
            current_block=block,
            all_blocks=blocks,
            requirements=ranking_requirements,
        )
        supporting_evidence_block_ids = [
            str(item.get("id") or "")
            for item in supporting_blocks
            if str(item.get("id") or "")
        ]
        preferences: list[str] = []
        try:
            from backend.memory.preference_db import PreferenceDB

            preference_db = PreferenceDB(db=getattr(self.repository, "db", None))
            preferences = list(dict.fromkeys([
                *preference_db.get_preferences(user_id, "resume_advisor"),
                *preference_db.get_preferences(user_id, str(block.get("sectionId") or "resume_advisor")),
            ]))
        except Exception:
            preferences = []
        context_snapshot = build_advisor_context_snapshot(
            current_block=block,
            jd_requirements=_jd_requirements(str(session.get("jdText") or "")),
            messages=messages,
            facts=confirmed_facts,
            preferences=preferences,
            max_chars=Config.ADVISOR_CONTEXT_MAX_CHARS,
            recent_turn_limit=Config.ADVISOR_CONTEXT_RECENT_TURNS,
        )
        self._merge_run_telemetry(
            user_id=user_id,
            run_id=run_id,
            telemetry={
                "contextVersion": context_snapshot["version"],
                "contextHash": context_snapshot["hash"],
                "contextChars": context_snapshot["characterCount"],
                "compactedMessageCount": context_snapshot["compactedMessageCount"],
            },
        )
        supplementary_evidence = "\n".join(
            f"- {str(item.get('locationLabel') or item.get('sectionName') or '简历内容')}: {str(item.get('text') or '').strip()}"
            for item in supporting_blocks[1:]
            if str(item.get("text") or "").strip()
        )
        context_prompt = str(context_snapshot["promptText"])
        if supplementary_evidence:
            context_prompt = (
                f"{context_prompt}\n\n[同份简历中可核验的补充证据]\n"
                f"{supplementary_evidence[:1200]}"
            )

        def record_cache_event(namespace: str, hit: bool) -> None:
            self.repository.append_event(
                user_id=user_id,
                session_id=session_id,
                run_id=run_id,
                event_type="cache",
                payload={
                    "namespace": namespace,
                    "hit": hit,
                    "stage": "cache_lookup",
                    "modelId": model_id,
                },
            )

        def record_provider_usage(agent: str, usage: dict[str, Any]) -> None:
            self.repository.append_event(
                user_id=user_id,
                session_id=session_id,
                run_id=run_id,
                event_type="provider_usage",
                payload={
                    "agent": agent,
                    "modelId": model_id,
                    **(usage if isinstance(usage, dict) else {}),
                },
            )

        def emit_tool_call(tool_name: str, stage: str) -> tuple[str, float]:
            call_id = f"tool-{uuid4().hex}"
            self.repository.append_event(
                user_id=user_id,
                session_id=session_id,
                run_id=run_id,
                event_type="tool_call",
                payload={
                    "callId": call_id,
                    "toolName": tool_name,
                    "stage": stage,
                    "agent": "resume_advisor",
                    "blockId": block.get("id"),
                },
            )
            return call_id, time.monotonic()

        def emit_tool_result(
            *,
            call_id: str,
            tool_name: str,
            stage: str,
            started_at: float,
            ok: bool,
            summary: dict[str, Any],
        ) -> None:
            self.repository.append_event(
                user_id=user_id,
                session_id=session_id,
                run_id=run_id,
                event_type="tool_result",
                payload={
                    "callId": call_id,
                    "toolName": tool_name,
                    "stage": stage,
                    "agent": "resume_advisor",
                    "blockId": block.get("id"),
                    "ok": ok,
                    "durationMs": max(0, int((time.monotonic() - started_at) * 1000)),
                    "summary": summary,
                },
            )

        def execute_operation(
            *,
            tool_name: str,
            stage: str,
            arguments: dict[str, Any],
            handler: Callable[[], dict[str, Any]],
        ) -> dict[str, Any]:
            call_id, started_at = emit_tool_call(tool_name, stage)
            outcome = self.tool_runtime.execute(
                name=tool_name,
                user_id=user_id,
                session_id=session_id,
                trace_id=str(run_snapshot.get("traceId") or session.get("traceId") or ""),
                arguments=arguments,
                handler=handler,
            )
            if outcome.get("ok"):
                data = outcome.get("data") if isinstance(outcome.get("data"), dict) else {}
                public_data = (
                    {"requirementCount": len(data.get("requirements", []))}
                    if tool_name == "extract_jd_requirements"
                    else {key: value for key, value in data.items() if key != "raw"}
                )
                emit_tool_result(
                    call_id=call_id,
                    tool_name=tool_name,
                    stage=stage,
                    started_at=started_at,
                    ok=True,
                    summary={"meta": outcome.get("meta", {}), **public_data},
                )
                return data
            error = outcome.get("error") if isinstance(outcome.get("error"), dict) else {}
            emit_tool_result(
                call_id=call_id,
                tool_name=tool_name,
                stage=stage,
                started_at=started_at,
                ok=False,
                summary={"code": str(error.get("code") or "tool_execution_failed")},
            )
            raise RuntimeError(str(error.get("message") or f"Advisor tool failed: {tool_name}"))

        if self._is_cancelled(user_id=user_id, run_id=run_id):
            return self._cancelled_result(user_id=user_id, session_id=session_id, run_id=run_id)
        requirements_result = execute_operation(
            tool_name="extract_jd_requirements",
            stage="jd_requirements",
            arguments={"jdText": str(session.get("jdText") or "")},
            handler=lambda: {
                "requirements": decode_jd_requirements(
                    jd_text=str(session.get("jdText") or ""),
                    fallback_requirements=_jd_requirements(str(session.get("jdText") or "")),
                    model_client=model_client,
                    model_id=model_id,
                    allow_model_call=False,
                    on_cache_event=record_cache_event,
                )
            },
        )
        requirements = [str(item) for item in requirements_result.get("requirements", [])]
        self.repository.append_event(
            user_id=user_id,
            session_id=session_id,
            run_id=run_id,
            event_type="progress",
            payload={
                "stage": "draft_suggestion",
                "summary": "模型正在生成本段建议。",
                "agent": "resume_copywriter",
                "modelId": model_id,
                "blockId": block.get("id"),
            },
        )

        pending_deltas: list[str] = []
        pending_chars = 0
        last_delta_at = time.monotonic()
        emitted_first_delta = False
        model_started_at = time.monotonic()

        def flush_model_delta(*, force: bool = False) -> None:
            nonlocal pending_chars, last_delta_at, emitted_first_delta
            if not pending_deltas:
                return
            if not force and emitted_first_delta and pending_chars < 48 and time.monotonic() - last_delta_at < 0.12:
                return
            chunk = "".join(pending_deltas)
            pending_deltas.clear()
            pending_chars = 0
            payload: dict[str, Any] = {
                "delta": chunk,
                "stage": "draft_suggestion",
                "agent": "resume_copywriter",
                "modelId": model_id,
                "blockId": block.get("id"),
            }
            if not emitted_first_delta:
                fallback_provider_first_token_ms = max(0, int((time.monotonic() - model_started_at) * 1000))
                provider_first_token_ms = self._provider_first_token_ms(model_client)
                provider_first_token_ms = (
                    provider_first_token_ms
                    if provider_first_token_ms is not None
                    else fallback_provider_first_token_ms
                )
                measured_end_to_end_ms = _elapsed_ms(run_created_at, datetime.now())
                end_to_end_first_token_ms = (
                    measured_end_to_end_ms
                    if measured_end_to_end_ms is not None
                    else max(0, (queue_ms or 0) + provider_first_token_ms)
                )
                first_token_metrics = {
                    "firstTokenMs": provider_first_token_ms,
                    "providerFirstTokenMs": provider_first_token_ms,
                    "queueMs": max(0, int(queue_ms or 0)),
                    "endToEndFirstTokenMs": end_to_end_first_token_ms,
                    "firstTokenSloMs": _FIRST_TOKEN_SLO_MS,
                    "firstTokenSloMet": end_to_end_first_token_ms <= _FIRST_TOKEN_SLO_MS,
                }
                payload.update(first_token_metrics)
            self.repository.append_event(
                user_id=user_id,
                session_id=session_id,
                run_id=run_id,
                event_type="model_delta",
                payload=payload,
            )
            if not emitted_first_delta:
                self._merge_run_telemetry(user_id=user_id, run_id=run_id, telemetry=first_token_metrics)
            emitted_first_delta = True
            last_delta_at = time.monotonic()

        def on_model_delta(delta: str) -> None:
            nonlocal pending_chars
            if not delta:
                return
            pending_deltas.append(delta)
            pending_chars += len(delta)
            flush_model_delta()

        if self._is_cancelled(user_id=user_id, run_id=run_id):
            return self._cancelled_result(user_id=user_id, session_id=session_id, run_id=run_id)
        try:
            draft = self._draft_suggestion(
                original_text,
                section_name=str(block.get("sectionId") or ""),
                jd_requirements=requirements,
                model_client=model_client,
                model_id=model_id,
                revision_feedback=revision_feedback,
                context_snapshot=context_prompt,
                user_id=user_id,
                on_delta=on_model_delta,
                on_cache_event=record_cache_event,
                on_provider_usage=record_provider_usage,
            )
        finally:
            flush_model_delta(force=True)
        if self._is_cancelled(user_id=user_id, run_id=run_id):
            return self._cancelled_result(user_id=user_id, session_id=session_id, run_id=run_id)
        copy_text = draft.proposed_text
        if self._is_cancelled(user_id=user_id, run_id=run_id):
            return self._cancelled_result(user_id=user_id, session_id=session_id, run_id=run_id)
        verification_holder: dict[str, Any] = {}
        execute_operation(
            tool_name="verify_suggestion_facts",
            stage="fact_verification",
            arguments={"blockId": str(block.get("id") or "")},
            handler=lambda: _verify_with_holder(
                verification_holder,
                original_text=original_text,
                proposed_text=copy_text,
                confirmed_facts=confirmed_facts,
                jd_text=str(session.get("jdText") or ""),
                resume_evidence_texts=[str(item.get("text") or "") for item in supporting_blocks],
            ),
        )
        verification = verification_holder["value"]
        if self._is_cancelled(user_id=user_id, run_id=run_id):
            return self._cancelled_result(user_id=user_id, session_id=session_id, run_id=run_id)
        if verification.status != "supported":
            issues = [issue.message for issue in verification.fact_issues]
            question_key = f"fact:{block['id']}:{'|'.join(issue.claim for issue in verification.fact_issues)}"
            message = self.repository.append_turn(
                user_id=user_id,
                session_id=session_id,
                role="assistant",
                content=(
                    "这条改写包含目前无法由简历或已确认事实支持的声明，暂不提供可复制文本。"
                    f"请补充可核验依据，或确认没有这些经历：{'；'.join(issues)}"
                ),
                message_kind="question",
                run_id=run_id,
                payload={
                    "questionKey": question_key,
                    "why": "JD 只能描述岗位要求，不能证明候选人事实。",
                    "target": block.get("locationLabel") or block.get("sectionName") or "简历正文",
                    "evidenceTypes": ["原简历中的具体描述", "可验证的职责", "真实结果数据"],
                    "factIssues": [issue.model_dump() for issue in verification.fact_issues],
                },
            )
            self.repository.update_session(
                user_id,
                session_id,
                session_status="WAITING_FOR_USER",
                active_run_id=run_id,
            )
            self.repository.append_event(
                user_id=user_id,
                session_id=session_id,
                run_id=run_id,
                message_id=message["id"],
                event_type="question",
                payload={"questionKey": question_key, "factStatus": verification.status},
            )
            self.repository.update_run(user_id=user_id, run_id=run_id, status="PAUSED")
            return {"status": "WAITING_FOR_USER", "message": message}

        if self._is_cancelled(user_id=user_id, run_id=run_id):
            return self._cancelled_result(user_id=user_id, session_id=session_id, run_id=run_id)
        quality_holder: dict[str, Any] = {}
        execute_operation(
            tool_name="hr_quality_review",
            stage="quality_review",
            arguments={"blockId": str(block.get("id") or "")},
            handler=lambda: _review_with_holder(
                quality_holder,
                original_text=original_text,
                proposed_text=copy_text,
                section_name=str(block.get("sectionName") or "其他"),
                jd_text=str(session.get("jdText") or ""),
                model_client=model_client,
                model_id=model_id,
                on_cache_event=record_cache_event,
                on_provider_usage=record_provider_usage,
            ),
        )
        quality = quality_holder["value"]
        local_quality = review_suggestion_quality(
            original_text=original_text,
            proposed_text=copy_text,
            evidence_block_ids=supporting_evidence_block_ids,
            fact_status=verification.status,
        )
        if not local_quality.is_passed:
            quality = local_quality
        if not quality.is_passed:
            message = self.repository.append_turn(
                user_id=user_id,
                session_id=session_id,
                role="assistant",
                content="这条建议未通过本地质量检查，暂不提供复制。请告诉我希望怎样调整。",
                message_kind="text",
                run_id=run_id,
                payload={
                    "quality": quality.model_dump(),
                    "target": {
                        "blockId": block["id"],
                        "locationLabel": block.get("locationLabel") or block.get("sectionName") or "简历正文",
                    },
                    "issue": draft.issue,
                },
            )
            self.repository.update_session(
                user_id,
                session_id,
                session_status="WAITING_FOR_USER",
                active_run_id=run_id,
            )
            self.repository.append_event(
                user_id=user_id,
                session_id=session_id,
                run_id=run_id,
                message_id=message["id"],
                event_type="message",
                payload={"messageKind": "text", "qualityPassed": False},
            )
            self.repository.update_run(user_id=user_id, run_id=run_id, status="PAUSED")
            return {"status": "WAITING_FOR_USER", "message": message}

        if self._is_cancelled(user_id=user_id, run_id=run_id):
            return self._cancelled_result(user_id=user_id, session_id=session_id, run_id=run_id)
        location = {
            "blockId": block["id"],
            "sectionId": block.get("sectionId") or "generic_section",
            "sectionName": block.get("sectionName") or "其他",
            "itemLabel": block.get("itemLabel"),
            "sourceFormat": (block.get("locator") or {}).get("sourceFormat", "txt"),
            "pageNumber": (block.get("locator") or {}).get("pageNumber"),
            "locationLabel": block.get("locationLabel") or block.get("sectionName") or "简历正文",
            "locatorConfidence": block.get("locatorConfidence") or "approximate",
            "bbox": (block.get("locator") or {}).get("bbox"),
        }
        suggestion = self.repository.create_suggestion(
            user_id=user_id,
            session_id=session_id,
            run_id=run_id,
            data={
                "parentSuggestionId": revision_request.get("id") if revision_request else None,
                "target": location,
                "originalTextHash": block.get("textHash") or "",
                "priority": "high" if block.get("sectionId") in {"project_experience", "work_experience"} else "medium",
                "issue": "根据你的反馈，重新整理这条可核验的简历要点。" if revision_request else draft.issue,
                "originalText": original_text,
                "proposedText": copy_text,
                "copyText": copy_text,
                "rationale": f"{draft.rationale} 已通过事实与质量检查；不引入 JD 中未被简历证据支持的技能、数字或职责。",
                "expectedImpact": draft.expected_impact,
                "jdRequirementIds": requirements,
                "resumeEvidenceBlockIds": supporting_evidence_block_ids,
                "userFactIds": self._supporting_user_fact_ids(confirmed_facts, copy_text),
                "factStatus": verification.status,
                "factIssues": [issue.message for issue in verification.fact_issues],
                "status": "proposed",
            },
        )
        message = self.repository.append_turn(
            user_id=user_id,
            session_id=session_id,
            role="assistant",
            content="我找到了一处可以在不改变事实的前提下整理的内容。请查看建议卡并决定是否采用、修订或保留原文。",
            message_kind="suggestion",
            run_id=run_id,
            payload={"suggestionId": suggestion["id"]},
        )
        self.repository.update_session(
            user_id,
            session_id,
            session_status="WAITING_FOR_USER",
            active_run_id=run_id,
        )
        self.repository.append_event(
            user_id=user_id,
            session_id=session_id,
            run_id=run_id,
            message_id=message["id"],
            suggestion_id=suggestion["id"],
            event_type="suggestion",
            payload={"factStatus": suggestion["factStatus"]},
        )
        self.repository.update_run(user_id=user_id, run_id=run_id, status="PAUSED")
        return {"status": "WAITING_FOR_USER", "suggestion": suggestion, "message": message}

    def _resolve_model(self, user_id: Any) -> tuple[Any | None, str]:
        if self.model_provider is not None:
            try:
                resolved = self.model_provider(user_id)
                if resolved:
                    return resolved
            except Exception:
                pass
        return self.model_client, self.model_id

    @staticmethod
    def _is_suggestion_follow_up(message: dict[str, Any]) -> bool:
        if message.get("role") != "user":
            return False
        payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
        if payload.get("action") or payload.get("suggestionId"):
            return False
        content = str(message.get("content") or "").strip()
        return bool(content) and (
            content.endswith(("?", "？"))
            or content.startswith(_FOLLOW_UP_PREFIXES)
        )

    @staticmethod
    def _is_suggestion_revision_request(message: dict[str, Any] | None) -> bool:
        if not message or message.get("role") != "user":
            return False
        payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
        if payload.get("action") or payload.get("suggestionId"):
            return False
        content = str(message.get("content") or "").strip()
        return any(hint in content for hint in _REVISION_HINTS)

    def _reply_to_suggestion_follow_up(
        self,
        *,
        user_id: Any,
        session_id: str,
        run_id: str,
        user_message: dict[str, Any],
        suggestion: dict[str, Any],
    ) -> dict[str, Any]:
        target = suggestion.get("target") if isinstance(suggestion.get("target"), dict) else {}
        location = str(target.get("locationLabel") or "当前段落")
        original = str(suggestion.get("originalText") or "原文内容")
        proposed = str(suggestion.get("proposedText") or suggestion.get("copyText") or "建议文本")
        rationale = str(suggestion.get("rationale") or "在不新增事实的前提下提升可扫描性。")
        message = self.repository.append_turn(
            user_id=user_id,
            session_id=session_id,
            role="assistant",
            content=(
                f"这条建议对应「{location}」。原文是“{original}”，建议改为“{proposed}”。"
                f"这样处理的原因是：{rationale}。"
                "如果你想调整语气或长度，直接告诉我即可；确认采用、保留或修订后，我再继续下一处。"
            ),
            message_kind="text",
            run_id=run_id,
            payload={
                "replyToMessageId": user_message.get("id"),
                "suggestionId": suggestion.get("id"),
                "mode": "suggestion_follow_up",
            },
        )
        self.repository.update_session(
            user_id,
            session_id,
            session_status="WAITING_FOR_USER",
            active_run_id=run_id,
        )
        self.repository.append_event(
            user_id=user_id,
            session_id=session_id,
            run_id=run_id,
            message_id=message["id"],
            event_type="message",
            payload={"messageKind": "text", "mode": "suggestion_follow_up"},
        )
        self.repository.update_run(user_id=user_id, run_id=run_id, status="PAUSED")
        return {"status": "WAITING_FOR_USER", "message": message}

    @staticmethod
    def _apply_local_revision_feedback(text: str, feedback: str) -> str:
        if "改短" not in feedback:
            return text
        stripped = text.lstrip("• ").strip()
        first_clause = re.split(r"[；。]", stripped, maxsplit=1)[0].strip()
        return f"• {first_clause}" if first_clause else text
