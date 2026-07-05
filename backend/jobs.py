from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from app_log import log_event
from config import Config
from database import Database
from backend.task_queue import get_redis_connection
from service import CareerPathAIService


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
        expert_options = dict(payload.get("expert_options") or {})
        draft_id = payload.get("draft_id")

        chunks = service.get_knowledge_chunks_for_analysis(user_id, knowledge_document_ids)
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
            selected_document_ids=knowledge_document_ids,
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
    enable_agent_resume: bool = False,
) -> None:
    from backend.background_analyzer import run_background_resume_analysis

    run_background_resume_analysis(
        user_id=user_id,
        record_id=record_id,
        draft_data=draft_data,
        resume_file_id=resume_file_id,
        embedding_config_id=embedding_config_id,
        chat_config_id=chat_config_id,
        enable_agent_resume=enable_agent_resume,
    )


def run_agent_resume_orchestration_job(
    task_id: str,
    user_id: Any,
    config_id: str | None,
    is_co_pilot: bool,
) -> None:
    from backend.agents.orchestrator import Orchestrator
    from backend.agents.tools.hitl_tool import HumanInteractionRequired

    run_id = uuid4().hex
    redis = _acquire_agent_task_lock(task_id, run_id)
    if redis is None:
        log_event(
            service="BACKEND",
            level="INFO",
            event="agent_resume_lock_skipped",
            detail=f"taskId: {task_id} | userId: {user_id} | reason: already running",
        )
        return

    try:
        try:
            asyncio.run(
                Orchestrator().run_orchestration(
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


def worker_healthcheck() -> dict[str, str]:
    # Useful as a tiny import target for deployment smoke checks.
    Database().get_connection().close()
    return {"status": "ok"}
