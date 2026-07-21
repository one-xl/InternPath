from __future__ import annotations

from typing import Any, Callable, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .service import ResumeOptimizationService


class StartRequest(BaseModel):
    resumeId: str
    jdText: str = Field(min_length=1)
    modelConfigId: str | None = None
    projectScope: Literal["none", "all", "selected"] = "none"
    projectDocumentIds: list[int] = Field(default_factory=list)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)


def build_router(service: ResumeOptimizationService, current_user: Callable[..., Any]) -> APIRouter:
    router = APIRouter(prefix="/api/resume-optimization", tags=["resume-optimization"])

    @router.post("/sessions")
    def start(payload: StartRequest, user_id: Any = Depends(current_user)) -> dict[str, Any]:
        try:
            return service.start(user_id=user_id, resume_id=payload.resumeId, jd_text=payload.jdText, model_config_id=payload.modelConfigId, project_scope=payload.projectScope, project_ids=payload.projectDocumentIds)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/sessions/{session_id}")
    def snapshot(session_id: str, user_id: Any = Depends(current_user)) -> dict[str, Any]:
        try:
            return service.snapshot(user_id, session_id)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.post("/sessions/{session_id}/messages")
    def chat(session_id: str, payload: ChatRequest, user_id: Any = Depends(current_user)) -> dict[str, Any]:
        try:
            return service.chat(user_id, session_id, payload.message)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
    @router.patch("/sessions/{session_id}")
    def rename(session_id: str, payload: dict[str, Any], user_id: Any = Depends(current_user)) -> dict[str, Any]:
        try:
            return service.rename_session(user_id, session_id, str(payload.get("title", "")))
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.delete("/sessions/{session_id}")
    def delete(session_id: str, user_id: Any = Depends(current_user)) -> dict[str, bool]:
        try:
            return {"deleted": service.delete_session(user_id, session_id)}
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc

    return router
