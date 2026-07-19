from __future__ import annotations

import asyncio
import json
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse

from .schemas import (
    ResumeAdvisorFinishRequest,
    ResumeAdvisorMessageCreate,
    ResumeAdvisorSessionCreate,
    ResumeSuggestionActionRequest,
)
from config import Config

from .session_module import ResumeAdvisorModule


EVENT_POLL_INTERVAL_SECONDS = 0.12
EVENT_HEARTBEAT_INTERVAL_SECONDS = 15.0
EVENT_STATUS_POLL_INTERVAL_SECONDS = Config.ADVISOR_EVENT_STATUS_POLL_SECONDS
EVENT_STREAM_BLOCK_MILLISECONDS = Config.ADVISOR_EVENT_STREAM_BLOCK_MILLISECONDS
_ACTIVE_RUN_STATUSES = {"QUEUED", "RUNNING"}


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=503, detail=f"简历顾问暂时不可用：{exc}")


def build_resume_advisor_router(
    module: ResumeAdvisorModule,
    current_user_dependency: Callable[..., Any],
) -> APIRouter:
    router = APIRouter(tags=["resume-advisor"])

    @router.post("/api/agent/resume/sessions")
    async def start_session(
        payload: ResumeAdvisorSessionCreate,
        user_id: Any = Depends(current_user_dependency),
    ) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(
                module.start_session,
                user_id=user_id,
                resume_id=payload.resume_id,
                jd_text=payload.jd_text,
                analysis_record_id=payload.analysis_record_id,
                title=payload.title or "",
            )
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.get("/api/agent/resume/sessions")
    async def list_sessions(
        limit: int = Query(default=40, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        user_id: Any = Depends(current_user_dependency),
    ) -> dict[str, Any]:
        sessions = await asyncio.to_thread(module.repository.list_sessions, user_id, limit=limit, offset=offset)
        return {"sessions": sessions, "limit": limit, "offset": offset}

    @router.get("/api/agent/resume/operations/slo")
    async def get_slo_dashboard(
        windowHours: int = Query(default=24, ge=1, le=720),
        user_id: Any = Depends(current_user_dependency),
    ) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(module.get_slo_dashboard, user_id=user_id, window_hours=windowHours)
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.get("/api/agent/resume/memory")
    async def list_memory(user_id: Any = Depends(current_user_dependency)) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(module.list_memory, user_id=user_id)
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.delete("/api/agent/resume/memory/facts/{fact_id}")
    async def revoke_memory_fact(fact_id: str, user_id: Any = Depends(current_user_dependency)) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(module.revoke_memory_fact, user_id=user_id, fact_id=fact_id)
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.delete("/api/agent/resume/memory/preferences/{preference_id}")
    async def delete_memory_preference(preference_id: str, user_id: Any = Depends(current_user_dependency)) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(module.delete_memory_preference, user_id=user_id, preference_id=preference_id)
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.get("/api/agent/resume/sessions/{session_id}")
    async def get_session(session_id: str, user_id: Any = Depends(current_user_dependency)) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(module.get_snapshot, user_id=user_id, session_id=session_id)
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.post("/api/agent/resume/sessions/{session_id}/messages")
    async def post_message(
        session_id: str,
        payload: ResumeAdvisorMessageCreate,
        user_id: Any = Depends(current_user_dependency),
    ) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(
                module.post_message,
                user_id=user_id,
                session_id=session_id,
                content=payload.content,
                client_message_id=payload.client_message_id,
                message_kind=payload.message_kind,
                remember=payload.remember,
            )
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.get("/api/agent/resume/sessions/{session_id}/events")
    async def stream_events(
        session_id: str,
        request: Request,
        afterSequence: int = Query(default=0, ge=0),
        user_id: Any = Depends(current_user_dependency),
    ) -> StreamingResponse:
        try:
            initial_status = await asyncio.to_thread(
                module.get_run_status,
                user_id=user_id,
                session_id=session_id,
            )
        except Exception as exc:
            raise _http_error(exc) from exc

        async def event_stream():
            sequence = max(0, afterSequence)
            status = initial_status
            loop = asyncio.get_running_loop()
            last_heartbeat_at = loop.time()
            last_status_check_at = 0.0
            stream_cursor: str | None = None
            get_stream_cursor = getattr(module, "get_event_stream_cursor", None)
            if callable(get_stream_cursor):
                stream_cursor = await asyncio.to_thread(get_stream_cursor, session_id=session_id)

            def encode_event(event: dict[str, Any]) -> str:
                return (
                    f"id: {event['sequence']}\n"
                    f"event: {event['type']}\n"
                    f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
                )

            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    return

                events = await asyncio.to_thread(
                    module.list_events,
                    user_id=user_id,
                    session_id=session_id,
                    after_sequence=sequence,
                )
                for event in events:
                    sequence = max(sequence, int(event.get("sequence") or 0))
                    yield encode_event(event)

                now = loop.time()
                if now - last_status_check_at >= max(0.0, EVENT_STATUS_POLL_INTERVAL_SECONDS):
                    status = await asyncio.to_thread(
                        module.get_run_status,
                        user_id=user_id,
                        session_id=session_id,
                    )
                    last_status_check_at = now
                if status not in _ACTIVE_RUN_STATUSES:
                    if EVENT_POLL_INTERVAL_SECONDS > 0:
                        await asyncio.sleep(EVENT_POLL_INTERVAL_SECONDS)
                    final_events = await asyncio.to_thread(
                        module.list_events,
                        user_id=user_id,
                        session_id=session_id,
                        after_sequence=sequence,
                    )
                    for event in final_events:
                        sequence = max(sequence, int(event.get("sequence") or 0))
                        yield encode_event(event)
                    yield f"event: done\ndata: {json.dumps({'status': status}, ensure_ascii=False)}\n\n"
                    return

                if not events and now - last_heartbeat_at >= EVENT_HEARTBEAT_INTERVAL_SECONDS:
                    yield ": keep-alive\n\n"
                    last_heartbeat_at = now
                wait_for_notification = getattr(module, "wait_for_event_notification", None)
                if not events and stream_cursor is not None and callable(wait_for_notification):
                    stream_cursor = await asyncio.to_thread(
                        wait_for_notification,
                        session_id=session_id,
                        cursor=stream_cursor,
                        block_ms=EVENT_STREAM_BLOCK_MILLISECONDS,
                    )
                elif not events:
                    await asyncio.sleep(max(0.01, EVENT_POLL_INTERVAL_SECONDS))

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @router.get("/api/agent/resume/sessions/{session_id}/resume-view")
    async def get_resume_view(session_id: str, user_id: Any = Depends(current_user_dependency)) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(module.get_resume_view, user_id=user_id, session_id=session_id)
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.get("/api/agent/resume/sessions/{session_id}/resume-file")
    async def get_resume_file(session_id: str, user_id: Any = Depends(current_user_dependency)) -> Response:
        try:
            content, media_type, file_name = await asyncio.to_thread(
                module.get_resume_file,
                user_id=user_id,
                session_id=session_id,
            )
        except Exception as exc:
            raise _http_error(exc) from exc
        safe_file_name = file_name.replace('"', "")
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f'inline; filename="{safe_file_name}"'},
        )

    @router.post("/api/agent/resume/suggestions/{suggestion_id}/actions")
    async def review_suggestion(
        suggestion_id: str,
        payload: ResumeSuggestionActionRequest,
        user_id: Any = Depends(current_user_dependency),
    ) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(
                module.review_suggestion,
                user_id=user_id,
                suggestion_id=suggestion_id,
                action=payload.action,
                feedback=payload.feedback,
            )
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.post("/api/agent/resume/sessions/{session_id}/finish")
    async def finish_session(
        session_id: str,
        _payload: ResumeAdvisorFinishRequest,
        user_id: Any = Depends(current_user_dependency),
    ) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(module.finish_session, user_id=user_id, session_id=session_id)
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.post("/api/agent/resume/sessions/{session_id}/runs/{run_id}/cancel")
    async def cancel_run(
        session_id: str,
        run_id: str,
        user_id: Any = Depends(current_user_dependency),
    ) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(module.cancel_run, user_id=user_id, session_id=session_id, run_id=run_id)
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.post("/api/agent/resume/sessions/{session_id}/archive")
    async def archive_session(session_id: str, user_id: Any = Depends(current_user_dependency)) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(module.archive_session, user_id=user_id, session_id=session_id)
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.delete("/api/agent/resume/sessions/{session_id}")
    async def delete_session(session_id: str, user_id: Any = Depends(current_user_dependency)) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(module.delete_session, user_id=user_id, session_id=session_id)
        except Exception as exc:
            raise _http_error(exc) from exc

    return router
