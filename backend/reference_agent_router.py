"""FastAPI mounting layer for the copied agent-for-shengxinkeji application."""

from __future__ import annotations

import json
import os
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from agent.context_manager import ContextManager
from agent.llm_client import LLMClient
from agent.runtime import AgentRuntime
from agent.session_manager import SessionManager
from agent.tool_registry import ToolRegistry
from tools.calculator import CALCULATOR_SCHEMA, calculate
from tools.search import SEARCH_SCHEMA, search
from tools.todo import TODO_SCHEMA, handle_todo
from tools.weather import WEATHER_SCHEMA, get_weather


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str = "default"


class ConfigRequest(BaseModel):
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)


def build_reference_agent_router(current_user: Callable[..., Any]) -> APIRouter:
    llm_client = LLMClient(
        api_key=os.environ.get("OPENAI_API_KEY"),
        base_url=os.environ.get("OPENAI_BASE_URL"),
        model=os.environ.get("LLM_MODEL", "gpt-4o-mini"),
        temperature=float(os.environ.get("LLM_TEMPERATURE", "0.2")),
    )
    registry = ToolRegistry()
    registry.register_tool("weather", get_weather, WEATHER_SCHEMA)
    registry.register_tool("calculator", calculate, CALCULATOR_SCHEMA)
    registry.register_tool("todo", handle_todo, TODO_SCHEMA)
    registry.register_tool("search", search, SEARCH_SCHEMA)
    sessions = SessionManager(llm_client=llm_client, tool_registry=registry, sessions_dir="data/sessions")
    router = APIRouter(tags=["reference-agent"])

    def scoped(user_id: Any, session_id: str) -> str:
        return f"user_{user_id}:{session_id.strip() or 'default'}"

    @router.post("/api/chat")
    def chat(payload: ChatRequest, user_id: Any = Depends(current_user)) -> dict[str, Any]:
        session_id = scoped(user_id, payload.session_id)
        runtime = sessions.get_or_create_runtime(session_id)
        response = runtime.run(payload.message, session_id=session_id)
        sessions.save_session(session_id)
        todos = handle_todo(action="list", session_id=session_id)
        return {
            "final_answer": response.final_answer,
            "traces": [trace.to_dict() for trace in response.traces],
            "step_count": response.step_count,
            "is_real_api": response.is_real_api,
            "model_used": response.model_used,
            "session_id": payload.session_id,
            "session_title": sessions.get_session_title(session_id),
            "todos": json.loads(todos) if isinstance(todos, str) and todos.startswith("[") else [],
        }

    @router.get("/api/config")
    def get_config(_user_id: Any = Depends(current_user)) -> dict[str, Any]:
        key = llm_client.api_key or ""
        return {"api_key_set": bool(key and key != "mock-api-key"), "masked_key": f"{key[:4]}...{key[-4:]}" if len(key) > 8 else ("已设置" if key else "未设置"), "base_url": llm_client.base_url or "", "model": llm_client.model, "temperature": llm_client.temperature, "is_real_api": bool(llm_client._client is not None)}

    @router.post("/api/config")
    def update_config(payload: ConfigRequest, _user_id: Any = Depends(current_user)) -> dict[str, Any]:
        llm_client.update_config(api_key=payload.api_key, base_url=payload.base_url, model=payload.model, temperature=payload.temperature)
        return {"status": "success", "model": llm_client.model, "is_real_api": bool(llm_client._client is not None)}

    @router.get("/api/sessions")
    def list_sessions(user_id: Any = Depends(current_user)) -> dict[str, Any]:
        prefix = f"user_{user_id}:"
        items = [{"session_id": item["session_id"].removeprefix(prefix), "title": item["title"]} for item in sessions.list_sessions() if item["session_id"].startswith(prefix)]
        return {"sessions": items or [{"session_id": "window_1", "title": "窗口 1"}]}

    @router.get("/api/session/messages")
    def session_messages(session_id: str = Query("default"), user_id: Any = Depends(current_user)) -> dict[str, Any]:
        runtime = sessions.get_or_create_runtime(scoped(user_id, session_id))
        return {"session_id": session_id, "messages": [message for message in runtime.context_manager.get_raw_messages() if message.get("role") != "system"]}

    @router.delete("/api/session")
    def delete_session(session_id: str = Query(...), user_id: Any = Depends(current_user)) -> dict[str, str]:
        sessions.delete_session(scoped(user_id, session_id))
        return {"status": "success", "session_id": session_id}

    @router.get("/api/todos")
    def todos(session_id: str = Query("default"), user_id: Any = Depends(current_user)) -> dict[str, Any]:
        result = handle_todo(action="list", session_id=scoped(user_id, session_id))
        return {"session_id": session_id, "todos": json.loads(result) if isinstance(result, str) and result.startswith("[") else []}

    return router
