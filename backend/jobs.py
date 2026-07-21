from __future__ import annotations

import asyncio
from datetime import datetime
from threading import Lock
from typing import Any
from uuid import uuid4

from app_log import log_event
from config import Config
from database import Database
from backend.agents.events import append_agent_log_json, build_agent_log
from backend.task_queue import get_redis_connection
from service import CareerPathAIService


_resume_advisor_module: Any | None = None
_resume_advisor_module_lock = Lock()


def _mark_resume_advisor_run_started(*, run_id: str, user_id: Any) -> None:
    """Start queue timing before importing the Advisor workflow and its dependencies."""
    conn = Database().get_connection()
    cursor = conn.cursor()
    try:
        now = datetime.now().isoformat()
        cursor.execute(
            """
            UPDATE agent_resume_runs
            SET status = 'RUNNING', started_at = COALESCE(started_at, ?)
            WHERE id = ? AND user_id = ? AND status = 'QUEUED'
            """,
            (now, run_id, str(user_id)),
        )
        conn.commit()
    finally:
        conn.close()


def _get_resume_advisor_module() -> Any:
    global _resume_advisor_module
    if _resume_advisor_module is not None:
        return _resume_advisor_module
    with _resume_advisor_module_lock:
        if _resume_advisor_module is None:
            from backend.resume_advisor import ResumeAdvisorModule
            from backend.resume_advisor.session_module import resolve_advisor_model

            _resume_advisor_module = ResumeAdvisorModule(Database(), model_provider=resolve_advisor_model)
    return _resume_advisor_module


def warm_resume_advisor_worker() -> None:
    """Preload the first-token path once when the dedicated worker starts."""
    _get_resume_advisor_module()
    from backend.agents.resume_copywriter import ResumeCopywriter  # noqa: F401


def _agent_task_lock_key(task_id: str) -> str:
    return f"agent:task-lock:{task_id}"


def _agent_task_lock_ttl_seconds() -> int:
    return int(Config.RQ_JOB_TIMEOUT_SECONDS) + 60


def _acquire_agent_task_lock(task_id: str, run_id: str) -> Any | None:
    redis = get_redis_connection()
    acquired = redis.set(
        _agent_task_lock_key(task_id),
        run_id,
        nx=True,
        ex=_agent_task_lock_ttl_seconds(),
    )
    return redis if acquired else None


def _release_agent_task_lock(redis: Any, task_id: str, run_id: str) -> None:
    key = _agent_task_lock_key(task_id)
    script = """
    if redis.call("get", KEYS[1]) == ARGV[1] then
        return redis.call("del", KEYS[1])
    end
    return 0
    """
    try:
        redis.eval(script, 1, key, run_id)
    except Exception:
        raw_value = redis.get(key)
        if isinstance(raw_value, bytes):
            raw_value = raw_value.decode("utf-8")
        if raw_value == run_id:
            redis.delete(key)


def _append_agent_resume_runtime_log(
    *,
    task_id: str,
    user_id: Any,
    message: str,
    stage: str,
    agent: str,
    status: str = "running",
    task_status: str = "RUNNING",
    detail: Any = None,
    log_type: str = "info",
    error_type: str = "",
) -> None:
    db = Database()
    if not hasattr(db, "get_agent_resume_task"):
        return
    task = db.get_agent_resume_task(user_id, task_id)
    if not task:
        return
    trace_id = str(task.get("trace_id") or task_id)
    logs = append_agent_log_json(
        task.get("logs"),
        build_agent_log(
            message,
            log_type=log_type,
            detail=detail,
            trace_id=trace_id,
            task_id=task_id,
            stage=stage,
            agent=agent,
            status=status,
            error_type=error_type,
        ),
    )
    db.update_agent_resume_task_status(
        task_id=task_id,
        user_id=user_id,
        status=task_status,
        logs=logs,
    )


def run_async_analysis_job(
    user_id: Any,
    payload: dict[str, Any],
    task_id: str,
    job_posting_id: int | None = None,
) -> None:
    service = CareerPathAIService()
    db = service.user_db(user_id)
    log_event(
        service="BACKEND",
        level="INFO",
        event="async_analysis_start",
        detail=f"taskId: {task_id} | userId: {user_id}",
    )
    try:
        service.update_analysis_task_status(user_id, task_id, "PROCESSING")

        jd_text = str(payload.get("jd_text") or "")
        resume_text = str(payload.get("resume_text") or "")
        knowledge_document_ids = list(payload.get("knowledge_document_ids") or [])
        project_knowledge_scope = str(payload.get("project_knowledge_scope") or "none")
        project_knowledge_document_ids = list(payload.get("project_knowledge_document_ids") or [])
        expert_options = dict(payload.get("expert_options") or {})
        draft_id = payload.get("draft_id")

        if project_knowledge_scope in {"all", "selected"}:
            chunks = service.get_project_knowledge_chunks_for_analysis(
                user_id,
                project_knowledge_document_ids,
                scope=project_knowledge_scope,
            )
            selected_document_ids = project_knowledge_document_ids
        else:
            chunks = service.get_knowledge_chunks_for_analysis(user_id, knowledge_document_ids)
            selected_document_ids = knowledge_document_ids
        knowledge_texts = [chunk.get("content", "") for chunk in chunks if chunk.get("content")]
        analysis = service.extract_skills(jd_text, user_id=user_id)
        decision = service.build_personal_decision(
            jd_text=jd_text,
            analysis=analysis,
            resume_text=resume_text,
            knowledge_texts=knowledge_texts,
            user_id=user_id,
        )
        analysis.personal_decision = decision

        service.analyze_jd_with_guardrails(
            user_id=user_id,
            jd_text=jd_text,
            resume_text=resume_text,
            knowledge_texts=knowledge_texts,
            selected_document_ids=selected_document_ids,
            project_knowledge_scope=project_knowledge_scope if project_knowledge_scope in {"all", "selected"} else "none",
            options=expert_options,
            original_analysis=analysis,
            task_id=task_id,
        )

        if draft_id:
            try:
                record_id = db.save_jd_record_and_convert_draft(user_id, jd_text, analysis, draft_id=draft_id)
            except Exception:
                record_id = db.save_jd_record(user_id, jd_text, analysis)
        else:
            record_id = db.save_jd_record(user_id, jd_text, analysis)

        record = service.get_jd_record(user_id, record_id)

        if job_posting_id:
            conn = db.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE job_postings SET jd_record_id = ? WHERE id = ? AND user_id = ?",
                (record_id, job_posting_id, user_id),
            )
            conn.commit()
            conn.close()

        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE analysis_task SET jd_id = ? WHERE task_id = ? AND user_id = ?",
            (record_id, task_id, user_id),
        )
        conn.commit()
        conn.close()

        analysis_result = {
            "jdRecordId": record_id,
            "createdAt": record.created_at.isoformat() if record and record.created_at else "",
            "draft": {"jdText": jd_text},
            "decision": decision.recommendation.lower() if decision else "",
            "matchScore": decision.match_score if decision else 0,
            "oneLineReason": decision.decision_reasons[0] if decision and decision.decision_reasons else "",
            "detectedKeywords": analysis.skills or [],
            "priority": "P1",
            "status": "watching",
        }
        db.save_analysis_record(
            user_id=user_id,
            status="watching",
            result_json=analysis_result,
        )

        user = db.get_user_by_id(user_id)
        if user and user.role != "admin":
            db.decrement_user_generation_limit(user_id)

        log_event(
            service="BACKEND",
            level="INFO",
            event="async_analysis_success",
            detail=f"taskId: {task_id} | userId: {user_id} | recordId: {record_id}",
        )
    except Exception as exc:
        import traceback

        tb_str = traceback.format_exc()
        print(f"[ASYNC_ANALYSIS] RQ job {task_id} failed: {exc}")
        log_event(
            service="BACKEND",
            level="ERROR",
            event="async_analysis_failed",
            detail=f"taskId: {task_id} | userId: {user_id} | error: {exc} | traceback: {tb_str}",
        )
        service.update_analysis_task_status(user_id, task_id, "FAILED", str(exc))
        raise


def run_background_resume_analysis_job(
    user_id: Any,
    record_id: str,
    draft_data: dict[str, Any],
    resume_file_id: str,
    embedding_config_id: str | None = None,
    chat_config_id: str | None = None,
    project_knowledge_scope: str = "none",
    project_knowledge_document_ids: list[int] | None = None,
    enable_agent_resume: bool = False,
    legacy_artifact_mode: bool = False,
) -> None:
    from backend.background_analyzer import run_background_resume_analysis

    run_background_resume_analysis(
        user_id=user_id,
        record_id=record_id,
        draft_data=draft_data,
        resume_file_id=resume_file_id,
        embedding_config_id=embedding_config_id,
        chat_config_id=chat_config_id,
        project_knowledge_scope=project_knowledge_scope,
        project_knowledge_document_ids=project_knowledge_document_ids or [],
        enable_agent_resume=enable_agent_resume,
        legacy_artifact_mode=legacy_artifact_mode,
    )


def run_agent_resume_orchestration_job(
    task_id: str,
    user_id: Any,
    config_id: str | None,
    is_co_pilot: bool,
    execution_mode: str = "agentic",
    tool_calling_mode: str = "native_responses",
    resume_payload: dict[str, Any] | None = None,
) -> None:
    from backend.agents.tools.hitl_tool import HumanInteractionRequired

    run_id = uuid4().hex
    redis = _acquire_agent_task_lock(task_id, run_id)
    if redis is None:
        _append_agent_resume_runtime_log(
            task_id=task_id,
            user_id=user_id,
            message="worker 检测到同一任务已有运行锁，跳过重复执行。",
            stage="worker_lock",
            agent="RQWorker",
            status="skipped",
            task_status="RUNNING",
            detail={"runId": run_id},
        )
        log_event(
            service="BACKEND",
            level="INFO",
            event="agent_resume_lock_skipped",
            detail=f"taskId: {task_id} | userId: {user_id} | reason: already running",
        )
        return

    try:
        _append_agent_resume_runtime_log(
            task_id=task_id,
            user_id=user_id,
            message="后台 worker 已接手任务，正在启动 Agent 执行链。",
            stage="worker_start",
            agent="RQWorker",
            status="running",
            task_status="RUNNING",
            detail={
                "runId": run_id,
                "executionMode": execution_mode,
                "toolCallingMode": tool_calling_mode,
                "isCoPilot": is_co_pilot,
            },
        )
        try:
            normalized_execution_mode = str(execution_mode or "agentic").strip().lower().replace("-", "_")
            normalized_tool_calling_mode = str(tool_calling_mode or "native_responses").strip().lower().replace("-", "_")
            if normalized_execution_mode == "agentic":
                from backend.agents.langgraph_orchestrator import LangGraphAgenticOrchestrator

                orchestrator = LangGraphAgenticOrchestrator()
                if resume_payload is not None:
                    asyncio.run(
                        orchestrator.resume_orchestration(
                            task_id=task_id,
                            user_id=user_id,
                            resume_payload=resume_payload,
                        )
                    )
                else:
                    asyncio.run(
                        orchestrator.run_orchestration(
                            task_id=task_id,
                            user_id=user_id,
                            config_id=config_id,
                            is_co_pilot=is_co_pilot,
                            tool_calling_mode=normalized_tool_calling_mode,
                        )
                    )
            else:
                from backend.agents.langgraph_orchestrator import LangGraphPipelineOrchestrator

                orchestrator = LangGraphPipelineOrchestrator()
                if resume_payload is not None:
                    asyncio.run(
                        orchestrator.resume_orchestration(
                            task_id=task_id,
                            user_id=user_id,
                            resume_payload=resume_payload,
                        )
                    )
                else:
                    asyncio.run(
                        orchestrator.run_orchestration(
                            task_id=task_id,
                            user_id=user_id,
                            config_id=config_id,
                            is_co_pilot=is_co_pilot,
                        )
                    )
        except HumanInteractionRequired as exc:
            Database().update_agent_resume_task_status(
                task_id=task_id,
                user_id=user_id,
                status="WAITING_FOR_HUMAN",
                pending_question=exc.question,
            )
            log_event(
                service="BACKEND",
                level="INFO",
                event="agent_resume_waiting_for_human",
                detail=f"taskId: {task_id} | userId: {user_id}",
            )
    finally:
        _release_agent_task_lock(redis, task_id, run_id)


def run_resume_advisor_session_job(
    run_id: str,
    user_id: Any,
    session_id: str,
    resume_payload: dict[str, Any] | None = None,
) -> None:
    """RQ entry point for one durable ResumeAdvisor run."""
    _mark_resume_advisor_run_started(run_id=run_id, user_id=user_id)
    module = _get_resume_advisor_module()
    if resume_payload is not None:
        module.resume_session(
            user_id=user_id,
            session_id=session_id,
            run_id=run_id,
            resume_payload=resume_payload,
        )
    else:
        module.run_session(user_id=user_id, session_id=session_id, run_id=run_id)


def worker_healthcheck() -> dict[str, str]:
    # Useful as a tiny import target for deployment smoke checks.
    Database().get_connection().close()
    return {"status": "ok"}
