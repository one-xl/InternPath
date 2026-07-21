from __future__ import annotations

import time
from threading import Lock
from typing import Any, Callable
from uuid import uuid4

from config import Config
from database import Database

from .langgraph import LangGraphResumeAdvisor
from .repository import ResumeAdvisorRepository
from .verification import review_suggestion_quality, verify_suggestion_facts


_QUESTION_PREFIXES = ("为什么", "为何", "怎么", "如何", "能否", "可以", "解释")
_ADVISOR_MODEL_CACHE: dict[str, tuple[float, Any, str]] = {}
_ADVISOR_MODEL_CACHE_LOCK = Lock()


def _resolve_advisor_model_uncached(user_id: Any) -> tuple[Any, str]:
    from ai_analyzer import AIAnalyzer

    client, _config_id, _provider, model_id = AIAnalyzer()._client(user_id, None, True)
    return client, model_id


def resolve_advisor_model(user_id: Any) -> tuple[Any, str]:
    """Resolve the user's configured chat model for optional specialist review."""
    cache_key = str(user_id)
    now = time.monotonic()
    with _ADVISOR_MODEL_CACHE_LOCK:
        cached = _ADVISOR_MODEL_CACHE.get(cache_key)
        if cached and now - cached[0] < Config.ADVISOR_MODEL_CLIENT_TTL_SECONDS:
            return cached[1], cached[2]
    client, model_id = _resolve_advisor_model_uncached(user_id)
    with _ADVISOR_MODEL_CACHE_LOCK:
        _ADVISOR_MODEL_CACHE[cache_key] = (time.monotonic(), client, model_id)
    return client, model_id


class ResumeAdvisorModule:
    """Deep module interface for the evidence-first resume advisor workflow."""

    def __init__(
        self,
        db: Database,
        *,
        enqueue_run: Callable[..., str | None] | None = None,
        cancel_enqueued_run: Callable[[str], bool] | None = None,
        repository: ResumeAdvisorRepository | None = None,
        model_provider: Callable[[Any], tuple[Any, str]] | None = None,
    ):
        self.repository = repository or ResumeAdvisorRepository(db)
        self.enqueue_run = enqueue_run
        self.cancel_enqueued_run = cancel_enqueued_run
        self.graph = LangGraphResumeAdvisor(self.repository, model_provider=model_provider)

    def start_session(
        self,
        *,
        user_id: Any,
        resume_id: str,
        jd_text: str,
        analysis_record_id: str | None = None,
        title: str = "",
        project_knowledge_scope: str = "none",
        project_knowledge_document_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        resume = self.repository.db.get_user_resume(user_id, resume_id)
        if not resume:
            raise LookupError("未找到指定简历。")
        content_hash = str(
            resume.get("contentHash")
            or (resume.get("file") or {}).get("contentHash")
            or ""
        ).strip()
        if not content_hash:
            raise ValueError("该简历缺少内容快照，请重新上传后再开始优化。")

        session = self.repository.create_session(
            user_id=user_id,
            resume_id=resume_id,
            resume_content_hash=content_hash,
            jd_text=jd_text,
            analysis_record_id=analysis_record_id,
            title=title or "简历定向优化",
        )
        scope = project_knowledge_scope if project_knowledge_scope in {"all", "selected"} else "none"
        project_document_ids = list(dict.fromkeys(int(value) for value in project_knowledge_document_ids or []))
        message = self.repository.append_turn(
            user_id=user_id,
            session_id=session["id"],
            role="assistant",
            content=(
                "已建立不可变简历快照。接下来我会一次只处理一个有证据支持的改进点。"
                if scope == "none"
                else "已建立不可变简历快照，并会把选定项目知识库作为补充证据。"
            ),
            message_kind="text",
            payload={
                "resumeContentHash": content_hash,
                "projectKnowledgeScope": scope,
                "projectKnowledgeDocumentIds": project_document_ids,
            },
        )
        self.repository.append_event(
            user_id=user_id,
            session_id=session["id"],
            event_type="message",
            message_id=message["id"],
            payload={"messageKind": "text"},
        )
        run = self.repository.create_run(user_id=user_id, session_id=session["id"], trigger_message_id=message["id"])
        self._enqueue(run["id"], user_id, session["id"])
        return {"session": self.repository.get_session(user_id, session["id"]), "run": run}

    def post_message(
        self,
        *,
        user_id: Any,
        session_id: str,
        content: str,
        client_message_id: str,
        message_kind: str = "text",
        remember: bool = False,
    ) -> dict[str, Any]:
        session = self.repository.get_session(user_id, session_id)
        if not session:
            raise LookupError("未找到简历优化会话。")
        if session["sessionStatus"] in {"SATISFIED", "ARCHIVED"}:
            raise ValueError("该会话已结束或归档，不能继续发送消息。")

        open_question_key = self._latest_question_key(user_id=user_id, session_id=session_id)
        inferred_fact_reply = (
            message_kind == "text"
            and bool(open_question_key)
            and not self._looks_like_question(content)
        )
        effective_message_kind = "fact" if inferred_fact_reply else message_kind
        run_message = self.repository.append_message_and_reserve_run(
            user_id=user_id,
            session_id=session_id,
            content=content,
            message_kind=effective_message_kind,
            client_message_id=client_message_id,
            payload={"remember": remember, "inferredFactReply": inferred_fact_reply},
        )
        if run_message["duplicate"]:
            message = run_message["message"]
            return {"duplicate": True, "message": message, "runId": message.get("runId")}
        message = run_message["message"]
        run = run_message["run"]
        if effective_message_kind == "fact":
            self.repository.record_fact(
                user_id=user_id,
                session_id=session_id,
                claim_key=open_question_key or "user_message",
                claim_value=content,
                source_type="user_message",
                source_id=message["id"],
                status="denied" if self._is_fact_denial(content) else "confirmed",
                scope="global" if remember else "session",
            )
        if message_kind == "preference" and remember:
            from backend.memory.preference_db import PreferenceDB

            PreferenceDB(db=self.repository.db).save_preference(
                user_id=user_id,
                section_name="resume_advisor",
                preference_text=content,
                source_task_id=session_id,
            )
        self.repository.append_event(
            user_id=user_id,
            session_id=session_id,
            event_type="message",
            message_id=message["id"],
            payload={"messageKind": effective_message_kind},
        )
        self._enqueue(
            run["id"],
            user_id,
            session_id,
            resume_payload={"messageId": message["id"]} if run.get("resumed") else None,
        )
        return {"duplicate": False, "message": message, "run": run}

    def _latest_question_key(self, *, user_id: Any, session_id: str) -> str:
        for turn in reversed(self.repository.list_turns(user_id, session_id)):
            if turn.get("role") != "assistant":
                continue
            payload = turn.get("payload") if isinstance(turn.get("payload"), dict) else {}
            if payload.get("mode") == "evidence_clarification":
                return f"clarification:{turn.get('id') or 'assistant'}"
            if turn.get("messageKind") != "question":
                return ""
            question_key = str(payload.get("questionKey") or "").strip()
            if question_key:
                return question_key
        return ""

    @staticmethod
    def _looks_like_question(content: str) -> bool:
        text = content.strip()
        return text.endswith(("?", "？")) or text.startswith(_QUESTION_PREFIXES)

    @staticmethod
    def _is_fact_denial(content: str) -> bool:
        return "没有" in content or "跳过" in content

    def review_suggestion(
        self,
        *,
        user_id: Any,
        suggestion_id: str,
        action: str,
        feedback: str = "",
    ) -> dict[str, Any]:
        suggestion = self.repository.get_suggestion(user_id, suggestion_id)
        if not suggestion:
            raise LookupError("未找到该建议。")
        status_by_action = {
            "accepted": "accepted",
            "rejected": "rejected",
            "needs_revision": "needs_revision",
            "applied": "applied",
        }
        if action == "restore":
            self._ensure_suggestion_is_copyable(user_id=user_id, suggestion=suggestion)
            restored = self.repository.restore_suggestion(
                user_id=user_id,
                suggestion_id=suggestion_id,
                run_id=str(suggestion.get("createdRunId") or "restore"),
            )
            message = self.repository.append_turn(
                user_id=user_id,
                session_id=suggestion["sessionId"],
                role="user",
                content=f"恢复建议 v{suggestion['version']}",
                message_kind="text",
                payload={"suggestionId": suggestion_id, "restoredSuggestionId": restored["id"], "action": action},
            )
            self.repository.append_event(
                user_id=user_id,
                session_id=suggestion["sessionId"],
                event_type="suggestion_restored",
                message_id=message["id"],
                suggestion_id=restored["id"],
                payload={"sourceSuggestionId": suggestion_id},
            )
            return {"suggestion": restored, "run": None}
        status = status_by_action.get(action)
        if not status:
            raise ValueError("不支持的建议操作。")
        if action in {"accepted", "applied"}:
            self._ensure_suggestion_is_copyable(user_id=user_id, suggestion=suggestion)
        self.repository.update_suggestion_status(user_id, suggestion_id, status)
        session_id = suggestion["sessionId"]
        run = None
        if action in {"applied", "needs_revision", "rejected"}:
            run_message = self.repository.append_message_and_reserve_run(
                user_id=user_id,
                session_id=session_id,
                content=feedback or action,
                message_kind="text",
                client_message_id=f"suggestion-{suggestion_id}-{action}-{uuid4().hex}",
                payload={"suggestionId": suggestion_id, "action": action},
            )
            message = run_message["message"]
            run = run_message["run"]
        else:
            message = self.repository.append_turn(
                user_id=user_id,
                session_id=session_id,
                role="user",
                content=feedback or action,
                message_kind="text",
                payload={"suggestionId": suggestion_id, "action": action},
            )
        self.repository.append_event(
            user_id=user_id,
            session_id=session_id,
            event_type="suggestion_action",
            message_id=message["id"],
            suggestion_id=suggestion_id,
            payload={"action": action},
        )
        if run is not None:
            self._enqueue(
                run["id"],
                user_id,
                session_id,
                resume_payload={"messageId": message["id"]} if run.get("resumed") else None,
            )
        return {"suggestion": self.repository.get_suggestion(user_id, suggestion_id), "run": run}

    def _ensure_suggestion_is_copyable(self, *, user_id: Any, suggestion: dict[str, Any]) -> None:
        if suggestion.get("factStatus") != "supported":
            raise ValueError("该建议尚未通过事实校验，不能采用或标记已粘贴。")
        view = self.repository.get_resume_view(user_id, suggestion["sessionId"])
        blocks: dict[str, dict[str, Any]] = {}
        for block in view.get("blocks", []):
            if not isinstance(block, dict):
                continue
            block_id = str(block.get("id") or "")
            if block_id:
                blocks[block_id] = block
            for legacy_id in block.get("legacyBlockIds") or []:
                legacy_id = str(legacy_id or "")
                if legacy_id:
                    blocks[legacy_id] = block
        target_block = blocks.get(str(suggestion.get("target", {}).get("blockId") or ""))
        if target_block is None:
            raise ValueError("建议绑定的原简历位置已不可用，请重新分析。")
        if str(target_block.get("textHash") or "") != str(suggestion.get("originalTextHash") or ""):
            raise ValueError("原简历内容已变化，建议已过期，请重新分析。")
        facts = self.repository.list_confirmed_facts(user_id, suggestion["sessionId"])
        verification = verify_suggestion_facts(
            original_text=str(target_block.get("text") or ""),
            proposed_text=str(suggestion.get("copyText") or ""),
            resume_evidence_texts=[str(target_block.get("text") or "")],
            confirmed_facts=facts,
        )
        quality = review_suggestion_quality(
            original_text=str(target_block.get("text") or ""),
            proposed_text=str(suggestion.get("copyText") or ""),
            evidence_block_ids=[str(target_block.get("id") or "")],
            fact_status=verification.status,
        )
        if not verification.is_supported or not quality.is_passed:
            raise ValueError("该建议未通过当前事实或质量复核，不能采用或标记已粘贴。")

    def finish_session(self, *, user_id: Any, session_id: str) -> dict[str, Any]:
        session = self.repository.get_session(user_id, session_id)
        if not session:
            raise LookupError("未找到简历优化会话。")
        self.repository.update_session(user_id, session_id, session_status="SATISFIED", user_satisfied=True)
        message = self.repository.append_turn(
            user_id=user_id,
            session_id=session_id,
            role="assistant",
            content="已按你的确认结束本次优化会话。历史建议和原始简历快照会保留供你复盘。",
            message_kind="completion",
            payload={"status": "SATISFIED"},
        )
        self.repository.append_event(
            user_id=user_id,
            session_id=session_id,
            event_type="session_finished",
            message_id=message["id"],
            payload={"status": "SATISFIED"},
        )
        return self.repository.get_session(user_id, session_id) or {}

    def archive_session(self, *, user_id: Any, session_id: str) -> dict[str, Any]:
        if not self.repository.get_session(user_id, session_id):
            raise LookupError("未找到简历优化会话。")
        self.repository.update_session(user_id, session_id, session_status="ARCHIVED", archived=True)
        return self.repository.get_session(user_id, session_id) or {}

    def delete_session(self, *, user_id: Any, session_id: str) -> dict[str, Any]:
        if not self.repository.delete_session(user_id=user_id, session_id=session_id):
            raise LookupError("未找到简历优化会话。")
        return {"ok": True}

    def cancel_run(self, *, user_id: Any, session_id: str, run_id: str) -> dict[str, Any]:
        result = self.repository.cancel_run(user_id=user_id, session_id=session_id, run_id=run_id)
        if result.get("alreadyCancelled") or self.cancel_enqueued_run is None:
            return result
        run = self.repository.get_run(user_id=user_id, run_id=run_id)
        rq_job_id = str((run or {}).get("rqJobId") or "")
        if not rq_job_id:
            return result
        try:
            result["rqCancellationRequested"] = bool(self.cancel_enqueued_run(rq_job_id))
        except Exception:
            # The durable cancellation flag remains authoritative if Redis is unavailable.
            result["rqCancellationRequested"] = False
        return result

    def list_memory(self, *, user_id: Any) -> dict[str, Any]:
        return {
            "facts": self.repository.list_global_facts(user_id),
            "preferences": self.repository.db.list_agent_preference_records(user_id),
        }

    def revoke_memory_fact(self, *, user_id: Any, fact_id: str) -> dict[str, Any]:
        if not self.repository.revoke_global_fact(user_id=user_id, fact_id=fact_id):
            raise LookupError("未找到可撤销的长期事实。")
        return {"ok": True}

    def delete_memory_preference(self, *, user_id: Any, preference_id: str) -> dict[str, Any]:
        if not self.repository.db.delete_agent_preference(user_id, preference_id):
            raise LookupError("未找到可删除的长期偏好。")
        return {"ok": True}

    def get_snapshot(self, *, user_id: Any, session_id: str) -> dict[str, Any]:
        session = self.repository.get_session(user_id, session_id)
        if not session:
            raise LookupError("未找到简历优化会话。")
        return {
            "session": session,
            "run": self.repository.get_active_run(user_id, session_id),
            "messages": self.repository.list_turns(user_id, session_id),
            "suggestions": self.repository.list_suggestions(user_id, session_id),
            "facts": self.repository.list_session_facts(user_id, session_id),
            "events": self.repository.list_events(user_id, session_id)[-160:],
        }

    def get_resume_view(self, *, user_id: Any, session_id: str) -> dict[str, Any]:
        return self.repository.get_resume_view(user_id, session_id)

    def get_resume_file(self, *, user_id: Any, session_id: str) -> tuple[bytes, str, str]:
        return self.repository.get_resume_file(user_id, session_id)

    def get_slo_dashboard(self, *, user_id: Any, window_hours: int = 24) -> dict[str, Any]:
        return self.repository.get_slo_dashboard(user_id=user_id, window_hours=window_hours)

    def list_events(self, *, user_id: Any, session_id: str, after_sequence: int = 0) -> list[dict[str, Any]]:
        return self.repository.list_events(user_id, session_id, after_sequence)

    def get_event_stream_cursor(self, *, session_id: str) -> str | None:
        return self.repository.get_event_stream_cursor(session_id=session_id)

    def wait_for_event_notification(self, *, session_id: str, cursor: str, block_ms: int) -> str:
        return self.repository.wait_for_event_notification(session_id=session_id, cursor=cursor, block_ms=block_ms)

    def get_run_status(self, *, user_id: Any, session_id: str) -> str:
        if not self.repository.get_session(user_id, session_id):
            raise LookupError("未找到简历优化会话。")
        run = self.repository.get_active_run(user_id, session_id)
        return str((run or {}).get("status") or "IDLE")

    def run_session(self, *, user_id: Any, session_id: str, run_id: str) -> dict[str, Any]:
        try:
            return self.graph.run(user_id=user_id, session_id=session_id, run_id=run_id)
        except Exception as exc:
            self.repository.update_run(
                user_id=user_id,
                run_id=run_id,
                status="FAILED",
                error_code=exc.__class__.__name__,
                error_message=str(exc),
            )
            self.repository.update_session(user_id, session_id, session_status="FAILED", error_message=str(exc))
            self.repository.append_event(
                user_id=user_id,
                session_id=session_id,
                run_id=run_id,
                event_type="error",
                payload={"error": "本轮简历顾问执行失败，请重试。"},
            )
            raise

    def resume_session(
        self,
        *,
        user_id: Any,
        session_id: str,
        run_id: str,
        resume_payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            return self.graph.resume(user_id=user_id, session_id=session_id, payload=resume_payload)
        except Exception as exc:
            self.repository.update_run(
                user_id=user_id,
                run_id=run_id,
                status="FAILED",
                error_code=exc.__class__.__name__,
                error_message=str(exc),
            )
            self.repository.update_session(user_id, session_id, session_status="FAILED", error_message=str(exc))
            raise

    def _create_or_resume_run(self, *, user_id: Any, session_id: str, message_id: str) -> dict[str, Any]:
        run = self.repository.reserve_run_for_message(user_id=user_id, session_id=session_id)
        self._enqueue(
            run["id"],
            user_id,
            session_id,
            resume_payload={"messageId": message_id} if run.get("resumed") else None,
        )
        return run

    def _enqueue(
        self,
        run_id: str,
        user_id: Any,
        session_id: str,
        *,
        resume_payload: dict[str, Any] | None = None,
    ) -> None:
        if self.enqueue_run is None:
            if resume_payload is not None:
                self.resume_session(
                    user_id=user_id,
                    session_id=session_id,
                    run_id=run_id,
                    resume_payload=resume_payload,
                )
            else:
                self.run_session(user_id=user_id, session_id=session_id, run_id=run_id)
            return
        rq_job_id = self.enqueue_run(run_id, user_id, session_id, resume_payload=resume_payload)
        if rq_job_id:
            self.repository.set_run_rq_job_id(
                user_id=user_id,
                run_id=run_id,
                rq_job_id=str(rq_job_id),
            )
