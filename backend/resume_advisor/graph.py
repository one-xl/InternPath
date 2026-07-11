from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from .verification import (
    draft_resume_suggestion,
    decode_jd_requirements,
    review_suggestion_quality,
    review_with_hr_critic,
    SuggestionDraft,
    verify_suggestion_facts,
)


_KEYWORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#./-]{1,}|[\u4e00-\u9fff]{2,}")
_STOP_WORDS = {"负责", "要求", "需要", "相关", "岗位", "经验", "能力", "优先", "我们", "你将", "以及", "进行"}
_FOLLOW_UP_PREFIXES = ("为什么", "为何", "怎么", "如何", "能否", "可以", "解释", "这条", "这个")
_REVISION_HINTS = ("改短", "精简", "精炼", "更克制", "换个说法", "改写", "重写", "语气")
_FIRST_TOKEN_SLO_MS = 10_000


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
        confirmed_facts = self.repository.list_confirmed_facts(user_id, session_id)
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
            for fact in confirmed_facts
            if fact.get("status") == "denied"
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

        candidates = [
            block
            for block in blocks
            if block.get("kind") in {"bullet", "paragraph"}
            and block_reference_ids(block).isdisjoint(rejected_blocks)
            and block_reference_ids(block).isdisjoint(denied_blocks)
            and block_reference_ids(block).isdisjoint(completed_blocks)
        ]

        if revision_request:
            requested_block_id = str(revision_request.get("target", {}).get("blockId") or "")
            candidates = [block for block in blocks if requested_block_id in block_reference_ids(block)]
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

        if not candidates:
            applied_exists = any(suggestion.get("status") == "applied" for suggestion in suggestions)
            resume_text = "\n".join(str(block.get("text") or "") for block in blocks).lower()
            asked_keys = {
                str(message.get("payload", {}).get("questionKey") or "")
                for message in messages
                if isinstance(message.get("payload"), dict)
            }
            denied_values = "\n".join(
                str(fact.get("claimValue") or "")
                for fact in confirmed_facts
                if fact.get("status") == "denied"
            ).lower()
            missing_requirement = next(
                (
                    requirement
                    for requirement in _jd_requirements(str(session.get("jdText") or ""))
                    if requirement.lower() not in resume_text
                    and requirement.lower() not in denied_values
                    and f"requirement:{requirement.lower()}" not in denied_question_keys
                    and f"requirement:{requirement.lower()}" not in asked_keys
                ),
                None,
            )
            if applied_exists and missing_requirement:
                question_key = f"requirement:{missing_requirement.lower()}"
                message = self.repository.append_turn(
                    user_id=user_id,
                    session_id=session_id,
                    role="assistant",
                    content=(
                        f"JD 强调「{missing_requirement}」。你是否有可核验的相关职责、技术选择或结果？"
                        "如果没有，请选择“没有这项经历”；我会保留这个真实缺口，不会把 JD 当作你的事实。"
                    ),
                    message_kind="question",
                    run_id=run_id,
                    payload={
                        "questionKey": question_key,
                        "why": "缺少这项事实时，不能在后续建议中新增该声明。",
                        "target": "下一处简历优化建议",
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

        extract_call_id, extract_started_at = emit_tool_call("extract_jd_requirements", "jd_requirements")
        try:
            requirements = decode_jd_requirements(
                jd_text=str(session.get("jdText") or ""),
                fallback_requirements=_jd_requirements(str(session.get("jdText") or "")),
                model_client=model_client,
                model_id=model_id,
                allow_model_call=False,
                on_cache_event=record_cache_event,
            )
        except Exception as exc:
            emit_tool_result(
                call_id=extract_call_id,
                tool_name="extract_jd_requirements",
                stage="jd_requirements",
                started_at=extract_started_at,
                ok=False,
                summary=_public_error_summary(exc),
            )
            raise
        emit_tool_result(
            call_id=extract_call_id,
            tool_name="extract_jd_requirements",
            stage="jd_requirements",
            started_at=extract_started_at,
            ok=True,
            summary={"requirementCount": len(requirements)},
        )
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

        try:
            draft = self._draft_suggestion(
                original_text,
                section_name=str(block.get("sectionId") or ""),
                jd_requirements=requirements,
                model_client=model_client,
                model_id=model_id,
                revision_feedback=revision_feedback,
                user_id=user_id,
                on_delta=on_model_delta,
                on_cache_event=record_cache_event,
                on_provider_usage=record_provider_usage,
            )
        finally:
            flush_model_delta(force=True)
        copy_text = draft.proposed_text
        verification_call_id, verification_started_at = emit_tool_call(
            "verify_suggestion_facts",
            "fact_verification",
        )
        try:
            verification = verify_suggestion_facts(
                original_text=original_text,
                proposed_text=copy_text,
                resume_evidence_texts=[original_text],
                confirmed_facts=confirmed_facts,
                jd_text=str(session.get("jdText") or ""),
            )
        except Exception as exc:
            emit_tool_result(
                call_id=verification_call_id,
                tool_name="verify_suggestion_facts",
                stage="fact_verification",
                started_at=verification_started_at,
                ok=False,
                summary=_public_error_summary(exc),
            )
            raise
        emit_tool_result(
            call_id=verification_call_id,
            tool_name="verify_suggestion_facts",
            stage="fact_verification",
            started_at=verification_started_at,
            ok=True,
            summary={"status": verification.status, "issueCount": len(verification.fact_issues)},
        )
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

        quality_call_id, quality_started_at = emit_tool_call("hr_quality_review", "quality_review")
        try:
            quality = review_with_hr_critic(
                original_text=original_text,
                proposed_text=copy_text,
                section_name=str(block.get("sectionName") or "其他"),
                jd_text=str(session.get("jdText") or ""),
                model_client=model_client,
                model_id=model_id,
                on_cache_event=record_cache_event,
                on_provider_usage=record_provider_usage,
            )
        except Exception as exc:
            emit_tool_result(
                call_id=quality_call_id,
                tool_name="hr_quality_review",
                stage="quality_review",
                started_at=quality_started_at,
                ok=False,
                summary=_public_error_summary(exc),
            )
            raise
        emit_tool_result(
            call_id=quality_call_id,
            tool_name="hr_quality_review",
            stage="quality_review",
            started_at=quality_started_at,
            ok=True,
            summary={
                "isPassed": quality.is_passed,
                "score": quality.score,
                "issueCount": len(quality.issues),
                "reviewer": quality.reviewer,
            },
        )
        local_quality = review_suggestion_quality(
            original_text=original_text,
            proposed_text=copy_text,
            evidence_block_ids=[str(block["id"])],
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
                "resumeEvidenceBlockIds": [block["id"]],
                "userFactIds": [],
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
