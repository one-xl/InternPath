from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.message import EmailMessage
import hashlib
import hmac
import json
import asyncio
import os
from pathlib import Path
import re
import secrets
import smtplib
import time
from typing import Any, Literal, Optional
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile, status, Cookie, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field

from database import Database
from document_parser import DocumentParseError
from models import JobAnalysis
from backend.doubao_job_rag import DoubaoAnalysisError, analyze_job_with_doubao, PLACEHOLDER_KEYS
from backend.job_import import JobImportPayload, parse_salary_range
from backend.ats_simulator import simulate_ats_compatibility
from backend.resume_rag import parse_resume, repair_resume_chunk_sections, retrieve_chunks
from backend.agents.base import BaseAgent
from backend.agents.cache import normalize_cache_text
from backend.agents.events import append_agent_log_json, build_agent_log
from backend.jobs import (
    run_agent_resume_orchestration_job,
    run_async_analysis_job,
    run_background_resume_analysis_job,
    run_resume_optimization_job,
)
from backend.resume_optimization import ResumeOptimizationService
from backend.resume_optimization.router import build_router as build_resume_optimization_router
from backend.task_queue import cancel_job, enqueue_job
from backend.docx_boundary_check import DocxBoundaryCheckConfig, check_docx_file_boundaries
from service import CareerPathAIService
from config import Config
from auth import hash_password, normalize_username
import httpx


class AuthRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=8)


class RegisterRequest(AuthRequest):
    verification_code: str = Field(default="", min_length=0, max_length=12)


class EmailCodeRequest(BaseModel):
    username: str = Field(..., min_length=1)


class GenerateTempUsersRequest(BaseModel):
    duration_hours: float
    quantity: int


class UpdateUserStatusRequest(BaseModel):
    is_active: bool


class UpdateUserExpiryRequest(BaseModel):
    expires_at: Optional[str] = None


class UpdateUserGenerationLimitRequest(BaseModel):
    generation_limit: int = Field(..., ge=0)


class UpdateUsernameRequest(BaseModel):
    username: str = Field(..., min_length=1)


class UpdateUserRemarkRequest(BaseModel):
    remark: str



class AnalyzeRequest(BaseModel):
    jd_text: str = Field(..., min_length=20)
    resume_text: str = ""
    knowledge_document_ids: list[int] = Field(default_factory=list)
    project_knowledge_scope: Literal["all", "selected", "none"] = "none"
    project_knowledge_document_ids: list[int] = Field(default_factory=list)
    expert_options: dict[str, bool] = Field(default_factory=dict)
    draft_id: Optional[str] = None
    async_mode: bool = True


class BackgroundAnalysisStartRequest(BaseModel):
    record_id: str
    draft: dict
    resume_file_id: str
    embedding_config_id: Optional[str] = None
    chat_config_id: Optional[str] = None
    project_knowledge_scope: Literal["all", "selected", "none"] = "none"
    project_knowledge_document_ids: list[int] = Field(default_factory=list)
    enable_agent_resume: bool = False
    legacy_artifact_mode: bool = False


class TailorFormFieldsRequest(BaseModel):
    resume_file_id: str
    jd_text: str
    fields: list[str]
    chat_config_id: Optional[str] = None


class ATSSimulateRequest(BaseModel):
    jd_text: str = ""
    jd_id: Optional[Any] = None


class RenameRecordRequest(BaseModel):
    display_name: str = ""



class ResumeRetrieveRequest(BaseModel):
    jdText: str = Field(..., min_length=1)
    resumeFileId: str = Field(..., min_length=1)
    topK: int = Field(default=8, ge=1, le=20)


class JobRagAnalyzeRequest(BaseModel):
    jdText: str = Field(..., min_length=20)
    targetType: str = ""
    jobDirection: str = ""
    resumeFileId: str = ""
    retrievedChunkIds: list[str] = Field(default_factory=list)
    draft: dict[str, Any] = Field(default_factory=dict)
    resumeFile: dict[str, Any] = Field(default_factory=dict)
    parsedResume: dict[str, Any] = Field(default_factory=dict)
    retrievedChunks: list[dict[str, Any]] = Field(default_factory=list)
    retrievalSummary: str = ""


class UserResponse(BaseModel):
    id: Any
    username: str
    role: str = "user"
    created_at: datetime
    is_active: bool = True
    expires_at: Optional[datetime] = None
    generation_limit: int = 5


AgentExecutionMode = Literal["pipeline", "agentic"]
AgentToolCallingMode = Literal["native_responses", "json_action", "auto"]
DEFAULT_AGENT_EXECUTION_MODE: AgentExecutionMode = "agentic"
DEFAULT_AGENT_TOOL_CALLING_MODE: AgentToolCallingMode = "native_responses"


def normalize_agent_execution_mode(
    value: Any,
    *,
    default: AgentExecutionMode = DEFAULT_AGENT_EXECUTION_MODE,
) -> AgentExecutionMode:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if not normalized:
        return default
    if normalized == "agentic":
        return "agentic"
    if normalized == "pipeline":
        return "pipeline"
    return default


def normalize_agent_tool_calling_mode(
    value: Any,
    *,
    default: AgentToolCallingMode = DEFAULT_AGENT_TOOL_CALLING_MODE,
) -> AgentToolCallingMode:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if not normalized:
        return default
    if normalized in {"native_responses", "json_action"}:
        return normalized
    return default


def parse_agent_execution_options(execution_plan: str | None) -> dict[str, str]:
    options = {
        "executionMode": DEFAULT_AGENT_EXECUTION_MODE,
        "toolCallingMode": DEFAULT_AGENT_TOOL_CALLING_MODE,
    }
    if not execution_plan:
        return options
    try:
        plan_data = json.loads(execution_plan)
    except Exception:
        return options
    if not isinstance(plan_data, dict):
        return options
    has_execution_mode = bool(plan_data.get("execution_mode") or plan_data.get("executionMode"))
    has_tool_calling_mode = bool(plan_data.get("tool_calling_mode") or plan_data.get("toolCallingMode"))
    if not has_execution_mode and not has_tool_calling_mode:
        return {
            "executionMode": "pipeline",
            "toolCallingMode": "auto",
        }
    options["executionMode"] = normalize_agent_execution_mode(
        plan_data.get("execution_mode") or plan_data.get("executionMode")
    )
    options["toolCallingMode"] = normalize_agent_tool_calling_mode(
        plan_data.get("tool_calling_mode") or plan_data.get("toolCallingMode")
    )
    return options


class AgentOptimizeResumeRequest(BaseModel):
    resume_id: str
    jd_text: str = Field(..., min_length=1)
    config_id: Optional[str] = None
    task_id: Optional[str] = None
    is_co_pilot: Optional[bool] = True
    execution_mode: Optional[str] = None
    executionMode: Optional[str] = None
    tool_calling_mode: Optional[str] = None
    toolCallingMode: Optional[str] = None
    legacy_mode: bool = False

    def normalized_execution_mode(self) -> AgentExecutionMode:
        return normalize_agent_execution_mode(
            self.execution_mode or self.executionMode,
            default=DEFAULT_AGENT_EXECUTION_MODE,
        )

    def normalized_tool_calling_mode(self) -> AgentToolCallingMode:
        return normalize_agent_tool_calling_mode(
            self.tool_calling_mode or self.toolCallingMode,
            default=DEFAULT_AGENT_TOOL_CALLING_MODE,
        )


class AgentAnswerRequest(BaseModel):
    answer: Optional[str] = None
    answer_text: Optional[str] = None
    answer_type: Literal["evidence", "preference", "skip", "clarification", "instruction", "question"] = "evidence"
    remember: bool = False
    evidence_scope: Literal["current_step", "resume", "jd", "global"] = "current_step"

    def normalized_answer(self) -> str:
        text = self.answer_text if self.answer_text is not None else self.answer
        text = str(text or "").strip()
        if self.answer_type == "skip" and not text:
            return "无补充，请保持原始事实继续。"
        return text


class SaveAgentResumeEditRequest(BaseModel):
    section_index: int
    new_text: str


class ModelProxyRequest(BaseModel):
    provider: str
    modelId: str
    requestBody: dict[str, Any]
    endpoint: Optional[str] = None
    configId: Optional[str] = None


async def persist_model_usage_in_background(auth_db: Database, usage: dict[str, Any]) -> None:
    """Keep non-critical usage auditing out of the request/stream hot path."""
    try:
        await asyncio.to_thread(auth_db.log_model_usage, **usage)
    except Exception as exc:
        # Do not turn a successful provider response into a failed user request.
        print(f"[MODEL_USAGE_AUDIT] Failed to persist deferred usage log: {exc}")


class TestConnectionRequest(BaseModel):
    provider: str
    modelId: str
    endpoint: Optional[str] = None
    type: Optional[str] = None
    configId: Optional[str] = None


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_json_list(raw: Any) -> list[Any]:
    if isinstance(raw, list):
        return raw
    if not raw:
        return []
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return []
    return parsed if isinstance(parsed, list) else []


def _normalize_agent_log(raw_log: Any, trace_id: str = "") -> dict[str, Any] | None:
    if not isinstance(raw_log, dict):
        return None
    duration = raw_log.get("durationMs", raw_log.get("duration_ms"))
    retry_count = raw_log.get("retryCount", raw_log.get("retry_count"))
    return {
        "timestamp": str(raw_log.get("timestamp") or ""),
        "type": str(raw_log.get("type") or "info"),
        "message": str(raw_log.get("message") or ""),
        "detail": raw_log.get("detail"),
        "traceId": str(raw_log.get("traceId") or raw_log.get("trace_id") or trace_id),
        "stage": str(raw_log.get("stage") or raw_log.get("type") or "unknown"),
        "agent": str(raw_log.get("agent") or ""),
        "status": str(raw_log.get("status") or ""),
        "cacheNamespace": str(raw_log.get("cacheNamespace") or raw_log.get("cache_namespace") or ""),
        "cacheHit": raw_log.get("cacheHit", raw_log.get("cache_hit")),
        "durationMs": None if duration in {None, ""} else _to_int(duration),
        "modelId": str(raw_log.get("modelId") or raw_log.get("model_id") or ""),
        "providerCacheAvailable": bool(raw_log.get("providerCacheAvailable") or raw_log.get("provider_cache_available")),
        "providerCacheHit": raw_log.get("providerCacheHit", raw_log.get("provider_cache_hit")),
        "providerCachedTokens": _to_int(raw_log.get("providerCachedTokens") or raw_log.get("provider_cached_tokens")),
        "providerCacheMissTokens": _to_int(raw_log.get("providerCacheMissTokens") or raw_log.get("provider_cache_miss_tokens")),
        "providerInputTokens": _to_int(raw_log.get("providerInputTokens") or raw_log.get("provider_input_tokens")),
        "providerEndpointMode": str(raw_log.get("providerEndpointMode") or raw_log.get("provider_endpoint_mode") or ""),
        "providerStream": raw_log.get("providerStream", raw_log.get("provider_stream")),
        "providerPromptCacheKey": str(raw_log.get("providerPromptCacheKey") or raw_log.get("provider_prompt_cache_key") or ""),
        "providerPromptCacheRetention": str(raw_log.get("providerPromptCacheRetention") or raw_log.get("provider_prompt_cache_retention") or ""),
        "providerPromptCacheDisabledReason": str(raw_log.get("providerPromptCacheDisabledReason") or raw_log.get("provider_prompt_cache_disabled_reason") or ""),
        "retryCount": _to_int(retry_count),
        "errorType": str(raw_log.get("errorType") or raw_log.get("error_type") or ""),
        "sequence": _to_int(raw_log.get("sequence")),
    }


def parse_agent_logs(raw_logs: Any, trace_id: str = "") -> list[dict[str, Any]]:
    raw_items = _parse_json_list(raw_logs)
    logs: list[dict[str, Any]] = []
    for item in raw_items:
        normalized = _normalize_agent_log(item, trace_id)
        if normalized is not None:
            logs.append(normalized)
    return logs


def append_agent_resume_log(
    task: dict[str, Any],
    message: str,
    *,
    log_type: str = "info",
    detail: Any = None,
    retry_count: int = 0,
) -> str:
    return append_agent_log_json(
        task.get("logs"),
        build_agent_log(
            message,
            log_type=log_type,
            detail=detail,
            trace_id=str(task.get("trace_id") or task.get("task_id") or ""),
            task_id=str(task.get("task_id") or ""),
            stage="retry",
            agent="Retry",
            status="retrying",
            retry_count=retry_count,
        ),
    )


def recover_agent_retry_options(execution_plan: str | None) -> tuple[str | None, bool]:
    options = recover_agent_retry_execution_options(execution_plan)
    return options["config_id"], options["is_co_pilot"]


def recover_agent_retry_execution_options(execution_plan: str | None) -> dict[str, Any]:
    fallback = {
        "config_id": None,
        "is_co_pilot": True,
        "execution_mode": DEFAULT_AGENT_EXECUTION_MODE,
        "tool_calling_mode": DEFAULT_AGENT_TOOL_CALLING_MODE,
    }
    if not execution_plan:
        return fallback
    try:
        plan_data = json.loads(execution_plan)
    except Exception:
        return fallback
    if not isinstance(plan_data, dict):
        return fallback
    config_id = plan_data.get("config_id")
    return {
        "config_id": str(config_id) if config_id else None,
        "is_co_pilot": bool(plan_data.get("is_co_pilot", True)),
        "execution_mode": normalize_agent_execution_mode(
            plan_data.get("execution_mode") or plan_data.get("executionMode")
        ),
        "tool_calling_mode": normalize_agent_tool_calling_mode(
            plan_data.get("tool_calling_mode") or plan_data.get("toolCallingMode")
        ),
    }


def prepare_agent_retry_execution_plan(execution_plan: str | None) -> tuple[str | None, dict[str, Any], int]:
    plan_data: dict[str, Any] = {}
    if execution_plan:
        try:
            parsed = json.loads(execution_plan)
            if isinstance(parsed, dict):
                plan_data = parsed
        except Exception:
            plan_data = {}
    failure_point = plan_data.get("failure_point")
    if not isinstance(failure_point, dict):
        failure_point = {}
    existing_retry_count = _to_int(
        failure_point.get("retry_count")
        or failure_point.get("retryCount")
        or plan_data.get("retry_count")
    )
    retry_count = existing_retry_count + 1
    retry_request = {
        "failed_stage": str(failure_point.get("failed_stage") or ""),
        "failed_tool_name": str(failure_point.get("failed_tool_name") or ""),
        "failed_tool_arguments": failure_point.get("failed_tool_arguments") if isinstance(failure_point.get("failed_tool_arguments"), dict) else {},
        "failed_model_input_ref": str(failure_point.get("failed_model_input_ref") or ""),
        "failed_sequence": _to_int(failure_point.get("failed_sequence")),
        "retry_count": retry_count,
        "requested_at": datetime.now().isoformat(),
    }
    if isinstance(failure_point.get("failed_model_input"), dict):
        retry_request["failed_model_input"] = failure_point["failed_model_input"]
    if isinstance(failure_point.get("last_successful_tool_result"), dict):
        retry_request["last_successful_tool_result"] = failure_point["last_successful_tool_result"]
    if failure_point:
        plan_data["failure_point"] = {**failure_point, "retry_count": retry_count}
        plan_data["retry_request"] = retry_request
        plan_data["retry_count"] = retry_count
        return json.dumps(plan_data, ensure_ascii=False), retry_request, retry_count
    plan_data["retry_count"] = retry_count
    return json.dumps(plan_data, ensure_ascii=False) if plan_data else execution_plan, retry_request, retry_count


def serialize_cache_stats(execution_plan: str | None) -> dict[str, Any]:
    cache_stats = {
        "hits": 0,
        "misses": 0,
        "hitRate": 0,
        "savedModelCalls": 0,
        "items": [],
    }
    if not execution_plan:
        return cache_stats
    try:
        plan_data = json.loads(execution_plan)
    except Exception:
        return cache_stats
    raw_stats = plan_data.get("cache_stats") if isinstance(plan_data, dict) else None
    if not isinstance(raw_stats, dict):
        return cache_stats

    raw_items = raw_stats.get("items")
    items = []
    if isinstance(raw_items, list):
        for item in raw_items[-80:]:
            if not isinstance(item, dict):
                continue
            items.append({
                "namespace": str(item.get("namespace") or ""),
                "label": str(item.get("label") or ""),
                "hit": bool(item.get("hit")),
                "savedModelCalls": _to_int(item.get("saved_model_calls") or item.get("savedModelCalls")),
                "stage": str(item.get("stage") or item.get("label") or ""),
                "agent": str(item.get("agent") or ""),
                "timestamp": str(item.get("timestamp") or ""),
            })

    hits = _to_int(raw_stats.get("hits"))
    misses = _to_int(raw_stats.get("misses"))
    total = hits + misses
    return {
        "hits": hits,
        "misses": misses,
        "hitRate": round((hits / total) * 100) if total else 0,
        "savedModelCalls": _to_int(raw_stats.get("saved_model_calls") or raw_stats.get("savedModelCalls")),
        "items": items,
    }


def serialize_provider_cache_stats(logs: list[dict[str, Any]]) -> dict[str, Any]:
    checks = 0
    hits = 0
    cached_tokens = 0
    miss_tokens = 0
    input_tokens = 0
    items: list[dict[str, Any]] = []
    for log in logs:
        if not isinstance(log, dict) or not log.get("providerCacheAvailable"):
            continue
        checks += 1
        hit = log.get("providerCacheHit") is True
        if hit:
            hits += 1
        cached = _to_int(log.get("providerCachedTokens"))
        missed = _to_int(log.get("providerCacheMissTokens"))
        input_count = _to_int(log.get("providerInputTokens"))
        cached_tokens += cached
        miss_tokens += missed
        input_tokens += input_count
        items.append({
            "stage": str(log.get("stage") or ""),
            "agent": str(log.get("agent") or ""),
            "modelId": str(log.get("modelId") or ""),
            "hit": hit,
            "cachedTokens": cached,
            "cacheMissTokens": missed,
            "inputTokens": input_count,
            "endpointMode": str(log.get("providerEndpointMode") or ""),
            "stream": log.get("providerStream"),
            "promptCacheDisabledReason": str(log.get("providerPromptCacheDisabledReason") or ""),
            "timestamp": str(log.get("timestamp") or ""),
        })
    return {
        "checks": checks,
        "hits": hits,
        "misses": max(0, checks - hits),
        "hitRate": round((hits / checks) * 100) if checks else 0,
        "cachedTokens": cached_tokens,
        "cacheMissTokens": miss_tokens,
        "inputTokens": input_tokens,
        "items": items[-80:],
    }


def format_sse_event(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def serialize_retry_available_event(task: dict[str, Any], logs: list[dict[str, Any]]) -> dict[str, Any] | None:
    if str(task.get("status") or "") != "FAILED":
        return None
    try:
        plan_data = json.loads(task.get("execution_plan") or "{}")
    except Exception:
        return None
    if not isinstance(plan_data, dict):
        return None
    failure_point = plan_data.get("failure_point")
    if not isinstance(failure_point, dict) or not failure_point:
        return None
    trace_id = str(task.get("trace_id") or task.get("task_id") or "")
    return {
        "traceId": trace_id,
        "taskId": str(task.get("task_id") or ""),
        "stage": str(failure_point.get("failed_stage") or "retry"),
        "agent": "Retry",
        "status": "available",
        "timestamp": str(task.get("updated_at") or datetime.now().isoformat()),
        "sequence": _to_int(failure_point.get("failed_sequence")) or len(logs) + 1,
        "failedStage": str(failure_point.get("failed_stage") or ""),
        "failedToolName": str(failure_point.get("failed_tool_name") or ""),
        "failedToolArguments": failure_point.get("failed_tool_arguments") if isinstance(failure_point.get("failed_tool_arguments"), dict) else {},
        "failedModelInputRef": str(failure_point.get("failed_model_input_ref") or ""),
        "retryCount": _to_int(failure_point.get("retry_count") or failure_point.get("retryCount")),
        "error": str(failure_point.get("error") or task.get("error_message") or ""),
    }


def build_agent_stage_metrics(
    logs: list[dict[str, Any]],
    cache_stats: dict[str, Any],
    trace_id: str = "",
) -> list[dict[str, Any]]:
    stages: dict[str, dict[str, Any]] = {}

    def ensure_stage(stage_name: str) -> dict[str, Any]:
        key = stage_name or "unknown"
        if key not in stages:
            stages[key] = {
                "traceId": trace_id,
                "stage": key,
                "agent": "",
                "status": "pending",
                "durationMs": 0,
                "modelCalls": 0,
                "savedModelCalls": 0,
                "cacheHits": 0,
                "cacheMisses": 0,
                "cacheNamespace": "",
                "retryCount": 0,
                "errorType": "",
                "lastMessage": "",
                "updatedAt": "",
            }
        return stages[key]

    for log in logs:
        stage = ensure_stage(str(log.get("stage") or log.get("type") or "unknown"))
        stage["traceId"] = str(log.get("traceId") or trace_id)
        stage["agent"] = str(log.get("agent") or stage["agent"])
        stage["status"] = str(log.get("status") or ("failed" if log.get("type") == "error" else "completed"))
        stage["lastMessage"] = str(log.get("message") or stage["lastMessage"])
        stage["updatedAt"] = str(log.get("timestamp") or stage["updatedAt"])
        stage["retryCount"] = max(_to_int(stage.get("retryCount")), _to_int(log.get("retryCount")))
        if log.get("durationMs") is not None:
            stage["durationMs"] += _to_int(log.get("durationMs"))
            if log.get("modelId"):
                stage["modelCalls"] += 1
        if log.get("cacheNamespace"):
            stage["cacheNamespace"] = str(log.get("cacheNamespace"))
        if log.get("cacheHit") is True:
            stage["cacheHits"] += 1
        elif log.get("cacheHit") is False:
            stage["cacheMisses"] += 1
        if log.get("errorType"):
            stage["errorType"] = str(log.get("errorType"))

    for item in cache_stats.get("items") or []:
        if not isinstance(item, dict):
            continue
        stage = ensure_stage(str(item.get("stage") or item.get("label") or item.get("namespace") or "cache"))
        stage["agent"] = str(item.get("agent") or stage["agent"] or "Cache")
        stage["cacheNamespace"] = str(item.get("namespace") or stage["cacheNamespace"])
        if item.get("hit"):
            stage["cacheHits"] += 1
            stage["savedModelCalls"] += _to_int(item.get("savedModelCalls"))
        else:
            stage["cacheMisses"] += 1

    return list(stages.values())


def serialize_agent_turn(turn: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(turn.get("id") or ""),
        "taskId": str(turn.get("task_id") or ""),
        "stepIndex": turn.get("step_index"),
        "role": str(turn.get("role") or ""),
        "content": str(turn.get("content") or ""),
        "answerType": str(turn.get("answer_type") or ""),
        "remember": bool(turn.get("remember")),
        "evidenceScope": str(turn.get("evidence_scope") or ""),
        "consumedAt": str(turn.get("consumed_at") or ""),
        "createdAt": str(turn.get("created_at") or ""),
        "summary": str(turn.get("summary") or ""),
    }


def serialize_agent_conversation_state(state: dict[str, Any] | None) -> dict[str, Any]:
    state = state or {}
    return {
        "summary": str(state.get("summary") or ""),
        "globalPreferences": list(state.get("global_preferences") or []),
        "factLedger": list(state.get("fact_ledger") or []),
        "updatedAt": str(state.get("updated_at") or ""),
    }


def read_agent_stream_preview(user_id: Any, task_id: str) -> str:
    if user_id is None or not task_id:
        return ""
    try:
        from backend.agents.tools.workspace_tools import tool_read_file

        preview = tool_read_file(user_id, task_id, "stream_preview.md")
        if preview.startswith("错误：") or preview.startswith("读取文件失败："):
            return ""
        return preview
    except Exception:
        return ""


def read_latest_agent_modification_patch(user_id: Any, task_id: str) -> dict[str, Any] | None:
    if user_id is None or not task_id:
        return None
    try:
        from backend.agents.tools.workspace_tools import tool_read_file

        raw_log = tool_read_file(user_id, task_id, "modification_log.json")
        if raw_log.startswith("错误：") or raw_log.startswith("读取文件失败："):
            return None
        items = json.loads(raw_log)
    except Exception:
        return None
    if not isinstance(items, list) or not items:
        return None
    latest = items[-1]
    if not isinstance(latest, dict):
        return None
    return {
        "section_name": str(latest.get("section_name") or ""),
        "section_index": _to_int(latest.get("section_index")),
        "original": str(latest.get("original") or ""),
        "new": str(latest.get("new") or ""),
        "reason": str(latest.get("reason") or ""),
        "timestamp": str(latest.get("timestamp") or ""),
    }


def prewarm_agent_resume_workspace(
    *,
    user_id: Any,
    task_id: str,
    resume_text: str,
    jd_text: str,
) -> dict[str, Any]:
    detail = {
        "resumeCharacters": len(resume_text or ""),
        "jdCharacters": len(jd_text or ""),
        "files": [],
        "errors": [],
    }
    try:
        from backend.agents.tools.workspace_tools import tool_write_file

        preview_text = (
            "已创建任务，正在排队接入后台 worker。\n\n"
            f"- 简历正文已预热：{detail['resumeCharacters']} 字符\n"
            f"- JD 已预热：{detail['jdCharacters']} 字符\n"
            "- 下一步：worker 接手后会解析偏好、模型配置、缓存和工具链。"
        )
        for filename, content in (
            ("original_resume.txt", resume_text),
            ("job_description.txt", jd_text),
            ("stream_preview.md", preview_text),
        ):
            result = tool_write_file(user_id, task_id, filename, content)
            if str(result).startswith("成功："):
                detail["files"].append(filename)
            else:
                detail["errors"].append({"file": filename, "message": str(result)})
    except Exception as exc:
        detail["errors"].append({"file": "workspace", "message": str(exc)})
    return detail


def get_agent_resume_artifact_state(user_id: Any, task_id: str) -> dict[str, bool]:
    state = {"hasDocx": False, "hasPdf": False}
    if user_id is None or not task_id:
        return state
    try:
        from backend.agents.tools.workspace_tools import get_safe_workspace_path

        state["hasDocx"] = os.path.exists(get_safe_workspace_path(user_id, task_id, "optimized_resume.docx"))
        state["hasPdf"] = os.path.exists(get_safe_workspace_path(user_id, task_id, "optimized_resume.pdf"))
    except Exception:
        pass
    return state


def optimized_resume_download_filename(task: dict[str, Any], suffix: str) -> str:
    original = os.path.basename(str(task.get("original_resume_name") or "resume"))
    stem = os.path.splitext(original)[0].strip() or "resume"
    safe_stem = re.sub(r'[\\/:*?"<>|]+', "_", stem).strip(" .") or "resume"
    return f"optimized_{safe_stem}.{suffix.lstrip('.')}"


def serialize_agent_task_summary(
    task: dict[str, Any],
    *,
    parsed_logs: list[dict[str, Any]] | None = None,
    include_artifacts: bool = True,
) -> dict[str, Any]:
    trace_id = str(task.get("trace_id") or "")
    logs = parsed_logs if parsed_logs is not None else parse_agent_logs(task.get("logs"), trace_id)
    execution_plan = task.get("execution_plan")
    execution_options = parse_agent_execution_options(execution_plan)
    cache_stats = serialize_cache_stats(execution_plan)
    provider_cache_stats = serialize_provider_cache_stats(logs)
    task_id = str(task.get("task_id") or "")
    user_id = task.get("user_id")
    stream_preview_md = read_agent_stream_preview(user_id, task_id)
    artifacts = {"hasDocx": False, "hasPdf": False}
    modification_log: list[dict[str, Any]] = []
    is_legacy_artifact = str(task.get("interaction_mode") or "artifact_legacy") == "artifact_legacy"
    if include_artifacts and is_legacy_artifact and user_id is not None and task_id:
        try:
            from backend.agents.tools.workspace_tools import get_safe_workspace_path, tool_read_file

            artifacts = get_agent_resume_artifact_state(user_id, task_id)
            raw_log = tool_read_file(user_id, task_id, "modification_log.json")
            loaded_log = json.loads(raw_log)
            if isinstance(loaded_log, list):
                modification_log = [item for item in loaded_log if isinstance(item, dict)]
        except Exception:
            pass

    return {
        "taskId": task.get("task_id"),
        "interactionMode": task.get("interaction_mode") or "artifact_legacy",
        "traceId": trace_id,
        "status": task.get("status"),
        "resumeId": task.get("resume_id"),
        "originalResumeName": task.get("original_resume_name"),
        "jdText": task.get("jd_text"),
        "logs": logs,
        "optimizedResumeMd": task.get("optimized_resume_md") or "",
        "streamPreviewMd": stream_preview_md,
        "errorMessage": task.get("error_message") or "",
        "createdAt": task.get("created_at"),
        "updatedAt": task.get("updated_at"),
        "modificationDiffMd": "",
        "hasDocx": artifacts["hasDocx"],
        "hasPdf": artifacts["hasPdf"],
        "modificationLog": modification_log,
        "pendingQuestion": task.get("pending_question") or "",
        "humanAnswer": task.get("human_answer") or "",
        "executionPlan": execution_plan or "",
        "executionMode": execution_options["executionMode"],
        "toolCallingMode": execution_options["toolCallingMode"],
        "conversationTurns": [],
        "conversationState": serialize_agent_conversation_state(None),
        "localReuseStats": cache_stats,
        "cacheStats": cache_stats,
        "providerCacheStats": provider_cache_stats,
        "stageMetrics": build_agent_stage_metrics(logs, cache_stats, trace_id),
    }


def _dedupe_text_items(items: list[Any], limit: int = 40) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        text = str(item or "").strip()
        key = normalize_cache_text(text)
        if not text or key in seen:
            continue
        seen.add(key)
        deduped.append(text)
    return deduped[-limit:]


def _truncate_conversation_summary(summary: str, limit: int = 1200) -> str:
    text = re.sub(r"\s+", " ", str(summary or "")).strip()
    if len(text) <= limit:
        return text
    return text[-limit:].lstrip("；,，。 ")


def merge_agent_conversation_state(
    current_state: dict[str, Any],
    *,
    answer: str,
    answer_type: str,
    evidence_scope: str,
    active_section: str,
) -> dict[str, Any]:
    summary = str(current_state.get("summary") or "")
    global_preferences = _dedupe_text_items(list(current_state.get("global_preferences") or []))
    fact_ledger = _dedupe_text_items(list(current_state.get("fact_ledger") or []))

    clean_answer = str(answer or "").strip()
    if clean_answer and answer_type not in {"skip", "question"}:
        scope_label = {
            "current_step": active_section or "当前步骤",
            "resume": "整份简历",
            "jd": "目标岗位",
            "global": "全局偏好",
        }.get(evidence_scope, evidence_scope)
        summary_piece = f"{scope_label}收到{answer_type}：{clean_answer}"
        summary = _truncate_conversation_summary("；".join(item for item in [summary, summary_piece] if item))

        if answer_type in {"preference", "instruction"} or evidence_scope == "global":
            global_preferences = _dedupe_text_items([*global_preferences, clean_answer])
        if answer_type in {"evidence", "clarification", "instruction"}:
            fact_ledger = _dedupe_text_items([*fact_ledger, clean_answer])

    return {
        "summary": summary,
        "global_preferences": global_preferences,
        "fact_ledger": fact_ledger,
    }


def build_agent_question_explanation(
    *,
    task: dict[str, Any],
    plan_data: dict[str, Any],
    active_section: str,
    active_step_index: int | None,
    question: str,
) -> str:
    step_goal = ""
    original_content = ""
    if isinstance(plan_data, dict):
        for step in plan_data.get("steps") or []:
            if not isinstance(step, dict):
                continue
            try:
                step_index = int(step.get("step_index"))
            except (TypeError, ValueError):
                step_index = None
            if active_step_index is None or step_index == active_step_index:
                step_goal = str(step.get("improvement_goal") or "")
                original_content = str(step.get("original_content") or "")
                break

    parts = [
        f"当前停在「{active_section or '当前段落'}」步骤。",
        "Agent 暂停是为了让后续改写只使用你确认过的事实和偏好。",
    ]
    if step_goal:
        parts.append(f"这一步的优化目标是：{step_goal}")
    if original_content:
        preview = original_content.replace("\n", " ").strip()[:120]
        parts.append(f"当前依据的原文片段是：{preview}")
    if task.get("pending_question"):
        parts.append(f"原待确认问题是：{task.get('pending_question')}")
    if question:
        parts.append(f"针对你的追问「{question}」，建议先补充真实证据或明确不要调整的范围；如果只是询问原因，本次不会推进执行。")
    return "\n".join(parts)


class AdminModelConfigRequest(BaseModel):
    provider: str
    modelId: str
    name: str
    apiKey: str
    enabled: bool = True
    config_json: Optional[dict[str, Any]] = None


class AdminAssignRequest(BaseModel):
    userIds: list[Any]


class AdminAnnouncementRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1)
    start_time: str
    end_time: str
    target_type: str = "all"
    target_users: Optional[str] = None
    announcement_type: str = "top"
    show_behavior: str = "once"


class SlidingWindowLimiter:
    def __init__(self):
        self.requests = defaultdict(list)

    def is_allowed(self, key: str, limit: int, window_seconds: int) -> bool:
        now = time.time()
        cutoff = now - window_seconds
        self.requests[key] = [t for t in self.requests[key] if t > cutoff]
        if len(self.requests[key]) >= limit:
            return False
        self.requests[key].append(now)
        return True


SESSION_MAX_AGE_SECONDS = 7200


@dataclass
class AppState:
    service: CareerPathAIService
    auth_db: Database
    resume_store: dict[str, dict[str, Any]] = field(default_factory=dict)


class UploadedFileAdapter:
    def __init__(self, file_name: str, content: bytes):
        self.name = file_name
        self._content = content

    def getvalue(self) -> bytes:
        return self._content


def openai_chat_body(model_id: str, request_body: dict) -> dict:
    messages = []
    contents = request_body.get("contents", [])
    for item in contents:
        role = item.get("role", "user")
        if role == "model":
            role = "assistant"
        parts = item.get("parts", [])
        text_content = ""
        for part in parts:
            if isinstance(part, dict) and "text" in part:
                text_content += part["text"]
            elif isinstance(part, str):
                text_content += part
        messages.append({"role": role, "content": text_content})

    gen_config = request_body.get("generationConfig", {})
    temperature = gen_config.get("temperature", 0.2)
    max_tokens = gen_config.get("maxOutputTokens") or gen_config.get("max_tokens") or 4096

    openai_body = {
        "model": model_id,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    response_mime = gen_config.get("responseMimeType")
    if response_mime == "application/json":
        openai_body["response_format"] = {"type": "json_object"}
        # Ensure the prompt contains the word 'json' to satisfy the constraint of some providers like Doubao/OpenAI
        has_json_word = False
        for msg in messages:
            if "json" in msg.get("content", "").lower():
                has_json_word = True
                break
        if not has_json_word and messages:
            # Append JSON instruction to the last message
            messages[-1]["content"] += "\n\nReturn the output in JSON format."

    return openai_body


def openai_responses_body(
    model_id: str,
    request_body: dict,
    *,
    prompt_cache_extra: Optional[dict[str, Any]] = None,
    prompt_cache_namespace: str = "model_proxy",
) -> dict:
    input_items = []
    contents = request_body.get("contents", [])
    for item in contents:
        role = item.get("role", "user")
        if role == "model":
            role = "assistant"
        if role not in {"user", "assistant"}:
            role = "user"
        parts = item.get("parts", [])
        text_content = ""
        for part in parts:
            if isinstance(part, dict) and "text" in part:
                text_content += part["text"]
            elif isinstance(part, str):
                text_content += part
        if text_content:
            input_items.append({"role": role, "content": text_content})

    gen_config = request_body.get("generationConfig", {})
    temperature = gen_config.get("temperature", 0.2)
    max_tokens = gen_config.get("maxOutputTokens") or gen_config.get("max_tokens") or 4096

    responses_body = {
        "model": model_id,
        "input": input_items or "",
        "temperature": temperature,
        "max_output_tokens": max_tokens,
    }
    responses_body.update(BaseAgent.responses_prompt_cache_kwargs(
        extra=prompt_cache_extra,
        model=model_id,
        namespace=prompt_cache_namespace,
    ))

    response_mime = gen_config.get("responseMimeType")
    if response_mime == "application/json":
        responses_body["text"] = {"format": {"type": "json_object"}}
        has_json_word = False
        for item in input_items:
            if "json" in item.get("content", "").lower():
                has_json_word = True
                break
        if not has_json_word and input_items:
            input_items[-1]["content"] += "\n\nReturn the output in JSON format."

    return responses_body


def wrap_openai_chat_response(res_json: dict) -> dict:
    choices = res_json.get("choices", [])
    text = ""
    finish_reason = "STOP"
    if choices:
        msg = choices[0].get("message", {})
        text = msg.get("content", "") or ""
        fr = choices[0].get("finish_reason", "stop")
        if fr == "stop":
            finish_reason = "STOP"
        elif fr == "length":
            finish_reason = "MAX_TOKENS"
        else:
            finish_reason = "STOP"

    usage = res_json.get("usage") or {}
    if not isinstance(usage, dict):
        usage = {}
    prompt_tokens = usage.get("prompt_tokens") or 0
    completion_tokens = usage.get("completion_tokens") or 0
    total_tokens = usage.get("total_tokens") or 0

    return {
        "candidates": [
            {
                "content": {
                    "parts": [
                        { "text": text }
                    ]
                },
                "finishReason": finish_reason
            }
        ],
        "usageMetadata": {
            "promptTokenCount": prompt_tokens,
            "candidatesTokenCount": completion_tokens,
            "totalTokenCount": total_tokens
        }
    }


def wrap_openai_responses_response(res_json: dict) -> dict:
    text = BaseAgent._extract_response_text(res_json)
    usage = res_json.get("usage") or {}
    if not isinstance(usage, dict):
        usage = {}

    prompt_tokens = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
    completion_tokens = usage.get("output_tokens") or usage.get("completion_tokens") or 0
    total_tokens = usage.get("total_tokens") or (prompt_tokens + completion_tokens)

    status_value = str(res_json.get("status") or "").lower()
    incomplete_details = res_json.get("incomplete_details") or {}
    incomplete_reason = ""
    if isinstance(incomplete_details, dict):
        incomplete_reason = str(incomplete_details.get("reason") or "").lower()
    finish_reason = "MAX_TOKENS" if status_value == "incomplete" or incomplete_reason == "max_output_tokens" else "STOP"

    return {
        "candidates": [
            {
                "content": {
                    "parts": [
                        { "text": text }
                    ]
                },
                "finishReason": finish_reason
            }
        ],
        "usageMetadata": {
            "promptTokenCount": prompt_tokens,
            "candidatesTokenCount": completion_tokens,
            "totalTokenCount": total_tokens
        }
    }


def prompt_from_gemini_request(request_body: dict) -> str:
    contents = request_body.get("contents", [])
    text_content = ""
    for item in contents:
        parts = item.get("parts", [])
        for part in parts:
            if isinstance(part, dict) and "text" in part:
                text_content += part["text"]
            elif isinstance(part, str):
                text_content += part
    return text_content


def chat_base_url(user_id: Any, provider: str, model_id: str) -> str:
    if provider == "gemini":
        return Config.GEMINI_BASE_URL or "https://generativelanguage.googleapis.com/v1beta"

    from database import Database
    db = Database()
    conn = db.get_connection()
    cursor = conn.cursor()

    # 1. Try user-owned config
    cursor.execute(
        """
        SELECT config_json
        FROM model_configs
        WHERE user_id = ? AND provider = ? AND model_id = ? AND (owner_type IS NULL OR owner_type = 'user') AND enabled = ?
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (user_id, provider, model_id, True)
    )
    row = cursor.fetchone()

    # 2. Try admin-assigned config
    if not row:
        cursor.execute(
            """
            SELECT c.config_json
            FROM model_configs c
            JOIN model_config_assignments a ON c.id = a.config_id
            WHERE a.user_id = ? AND c.provider = ? AND c.model_id = ? AND a.enabled = ? AND c.enabled = ? AND c.owner_type IN ('admin', 'system')
            ORDER BY c.updated_at DESC
            LIMIT 1
            """,
            (user_id, provider, model_id, True, True)
        )
        row = cursor.fetchone()

    conn.close()

    if row and row[0]:
        import json
        try:
            extra = json.loads(row[0])
            base_url = extra.get("baseUrl") or extra.get("base_url")
            if base_url:
                return base_url.strip()
        except Exception:
            pass

    return ""


def chat_config_extra(config_id: Optional[str]) -> dict[str, Any]:
    if not config_id:
        return {}
    try:
        from uuid import UUID
        UUID(str(config_id))
    except Exception:
        return {}

    db = Database()
    conn = db.get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT config_json FROM model_configs WHERE id = ?", (config_id,))
        row = cursor.fetchone()
    finally:
        conn.close()

    if not row or not row[0]:
        return {}
    try:
        extra = json.loads(row[0])
    except Exception:
        return {}
    return extra if isinstance(extra, dict) else {}


def chat_base_url_for_config(config_id: Optional[str]) -> str:
    extra = chat_config_extra(config_id)
    base_url = extra.get("baseUrl") or extra.get("base_url")
    return base_url.strip() if isinstance(base_url, str) and base_url.strip() else ""


def openai_chat_url(base_url: str) -> str:
    import urllib.parse
    import re

    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/chat"):
        return f"{base}/completions"

    try:
        parsed = urllib.parse.urlparse(base)
        path = parsed.path.rstrip("/")
        # If path does not end with version prefix (e.g. v1, v2, v1beta, v3)
        if not path or not re.search(r"/(v\d+[^/]*)$", path):
            base = f"{base}/v1"
    except Exception:
        pass

    return f"{base}/chat/completions"


def openai_responses_url(base_url: str) -> str:
    import urllib.parse
    import re

    base = base_url.rstrip("/")
    if base.endswith("/responses"):
        return base
    if base.endswith("/chat/completions"):
        base = base[:-17].rstrip("/")
    elif base.endswith("/chat"):
        base = base[:-5].rstrip("/")

    try:
        parsed = urllib.parse.urlparse(base)
        path = parsed.path.rstrip("/")
        if not path or not re.search(r"/(v\d+[^/]*)$", path):
            base = f"{base}/v1"
    except Exception:
        pass

    return f"{base}/responses"


def chat_stream_api_mode(config_id: Optional[str]) -> str:
    extra = chat_config_extra(config_id)
    return BaseAgent._normalize_stream_api_mode(
        extra.get("streamApiMode") or extra.get("stream_api_mode")
    )


def create_app(
    *,
    service: Optional[CareerPathAIService] = None,
    auth_db: Optional[Database] = None,
) -> FastAPI:
    app = FastAPI(title="InternPath Personal Workbench API")

    @app.middleware("http")
    async def retire_legacy_resume_optimization(request: Request, call_next):
        if request.url.path.startswith("/api/agent/resume"):
            return JSONResponse(
                status_code=status.HTTP_410_GONE,
                content={"detail": "旧版简历定向优化已删除，请使用新的 Agent 页面。"},
            )
        return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        import traceback
        traceback.print_exc()
        try:
            from app_log import log_event
            log_event(
                service="BACKEND",
                level="ERROR",
                event="validation_error",
                detail=f"URL: {request.url.path} | Errors: {exc.errors()}"
            )
        except Exception:
            pass
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "detail": f"鍙傛暟鏍￠獙澶辫触: {str(exc.errors())}",
                "error_type": "RequestValidationError",
                "errors": exc.errors()
            }
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        try:
            from app_log import log_event
            level = "ERROR" if exc.status_code >= 500 else "WARNING"
            log_event(
                service="BACKEND",
                level=level,
                event="http_exception",
                detail=f"URL: {request.url.path} | Status: {exc.status_code} | Detail: {exc.detail}"
            )
        except Exception:
            pass
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": exc.detail,
                "error_type": "HTTPException"
            }
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        import traceback
        traceback.print_exc()
        error_type = exc.__class__.__name__
        error_detail = str(exc) or "No detail provided"
        tb_str = traceback.format_exc()
        try:
            from app_log import log_event
            log_event(
                service="BACKEND",
                level="ERROR",
                event="unhandled_exception",
                detail=f"URL: {request.url.path} | [{error_type}] {error_detail} | Traceback: {tb_str}"
            )
        except Exception:
            pass
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": f"鏈嶅姟鍣ㄥ唴閮ㄩ敊璇? [{error_type}] {error_detail}",
                "error_type": error_type,
                "reason": error_detail
            }
        )

    # CORS: in production only allow configured origin; in development allow localhost
    if Config.IS_PRODUCTION and Config.FRONTEND_ORIGIN:
        allowed_origins = [Config.FRONTEND_ORIGIN]
    else:
        allowed_origins = [
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:4173",
            "http://localhost:4173",
        ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_origin_regex="chrome-extension://.*",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    state = AppState(
        service=service or CareerPathAIService(),
        auth_db=auth_db or Database(),
    )
    # Seed default development admin user if not present
    state.auth_db.seed_db()
    # Clean up expired sessions on startup
    try:
        cleaned = state.auth_db.cleanup_expired_sessions()
        if cleaned:
            print(f"[SESSION] Cleaned up {cleaned} expired session(s).")
    except Exception:
        pass

    limiter = SlidingWindowLimiter()

    def check_rate_limit(key: str, limit: int, window_seconds: int, skip: bool = False):
        if skip:
            return
        if not limiter.is_allowed(key, limit, window_seconds):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="请求过于频繁，请稍后再试。",
            )

    def issue_token(user_id: Any) -> str:
        token = uuid4().hex
        from datetime import timedelta
        expires_at = datetime.now() + timedelta(seconds=SESSION_MAX_AGE_SECONDS)
        state.auth_db.create_session(token, user_id, expires_at)
        return token

    def ensure_resume_sections(
        user_id: Any,
        resume_id: str,
        parsed_resume: dict[str, Any],
        *,
        persist: bool = True,
    ) -> dict[str, Any]:
        repaired, changed = repair_resume_chunk_sections(parsed_resume)
        if not changed:
            return parsed_resume

        state.resume_store[resume_id] = {
            "parsed_resume": repaired,
            "user_id": user_id,
        }
        if not persist:
            return repaired

        file_info = repaired.get("file") if isinstance(repaired.get("file"), dict) else {}
        file_name = file_info.get("name") or "resume"
        file_size = int(file_info.get("size") or 0)
        file_type = file_info.get("type") or "application/octet-stream"
        db_targets = [state.auth_db]
        try:
            db_targets.append(state.service.user_db(user_id))
        except Exception as exc:
            print(f"[RESUME] Failed to open service DB for repaired chunks {resume_id}: {exc}")
        for db_target in db_targets:
            try:
                db_target.save_user_resume(
                    user_id=user_id,
                    resume_id=resume_id,
                    file_name=file_name,
                    file_size=file_size,
                    file_type=file_type,
                    parsed_resume=repaired,
                )
            except Exception as exc:
                print(f"[RESUME] Failed to persist repaired chunks for {resume_id}: {exc}")
        return repaired

    def current_user_id(
        session_cookie: Optional[str] = Cookie(default=None, alias="session_id"),
        authorization: str = Header(default="")
    ) -> Any:
        # Bearer token takes priority over cookie
        token = None
        if authorization:
            scheme, _, bearer_token = authorization.partition(" ")
            if scheme.lower() == "bearer" and bearer_token:
                token = bearer_token
        if not token:
            token = session_cookie

        if not token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录状态无效，请重新登录。")
        user_id = state.auth_db.get_session_user_id(token)
        if user_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录状态已过期，请重新登录。")

        user = state.auth_db.get_user_by_id(user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在。")

        if user.role != "admin":
            # Strip timezone to safely compare naive datetime.now() with potentially aware user.expires_at
            user_expires = user.expires_at.replace(tzinfo=None) if user.expires_at else None
            if user_expires and datetime.now() > user_expires:
                if user.is_active:
                    try:
                        state.auth_db.admin_update_user_status(user_id, False)
                        state.auth_db.delete_user_sessions(user_id)
                    except Exception as exc:
                        print(f"[WARNING] Concurrent expiry update for user_id={user_id}: {exc}")
                    user.is_active = False
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="该账号已过期停用，请联系管理员。")

            if not user.is_active:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="该账号已被停用，请联系管理员。")

        return user_id


    resume_optimization_service = ResumeOptimizationService(
        state.auth_db,
        resume_provider=state.auth_db.get_user_resume,
        project_provider=lambda user_id, document_ids, scope: state.service.get_project_knowledge_chunks_for_analysis(
            user_id, document_ids, scope=scope
        ),
        enqueue_run=lambda session_id, user_id: enqueue_job(
            run_resume_optimization_job,
            session_id=session_id,
            user_id=user_id,
            job_id=session_id,
            queue_name=Config.RQ_ADVISOR_QUEUE_NAME,
        ),
    )
    app.include_router(build_resume_optimization_router(resume_optimization_service, current_user_id))



    def current_admin_user(
        user_id: Any = Depends(current_user_id)
    ) -> Any:
        user = state.auth_db.get_user_by_id(user_id)
        if user is None or user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="权限不足，只有管理员可以执行此操作。",
            )
        return user_id

    def set_session_cookie(response: Response, token: str) -> None:
        response.set_cookie(
            key="session_id",
            value=token,
            httponly=True,
            max_age=SESSION_MAX_AGE_SECONDS,
            samesite="lax",
            secure=Config.IS_PRODUCTION,
        )

    def auth_payload(user_id: Any, token: str) -> dict[str, Any]:
        user = state.auth_db.get_user_by_id(user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user_not_found")
        return {
            "token": token,
            "user": UserResponse(
                id=user.id or user_id,
                username=user.username,
                role=user.role,
                created_at=user.created_at,
                is_active=user.is_active,
                expires_at=user.expires_at,
            ).model_dump(mode="json"),
        }


    def model_api_key(user_id: Any, provider: str, model_id: str, env_key: str) -> str:
        saved_key = state.auth_db.get_model_api_key(user_id, provider, model_id)
        if saved_key:
            return saved_key
        return (env_key or "").strip()

    def normalize_email(value: str) -> str:
        email = value.strip().lower()
        if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请输入有效的邮箱地址。")
        return email

    def email_code_hash(email: str, code: str) -> str:
        secret = (
            os.getenv("EMAIL_CODE_SECRET")
            or os.getenv("MODEL_SECRET_ENCRYPTION_KEY")
            or "internpath-email-code-dev-secret"
        )
        return hmac.new(secret.encode("utf-8"), f"{email}:{code}".encode("utf-8"), hashlib.sha256).hexdigest()

    def send_email_code(email: str, code: str) -> bool:
        if not Config.SMTP_HOST or not Config.SMTP_USERNAME or not Config.SMTP_PASSWORD:
            print(f"[EMAIL_CODE][DEV] {email} -> {code}")
            return False

        message = EmailMessage()
        message["Subject"] = "InternPath 注册验证码"
        message["From"] = Config.MAIL_FROM
        message["To"] = email
        message.set_content(
            f"你的 InternPath 注册验证码是：{code}\n\n"
            f"验证码 {Config.EMAIL_CODE_TTL_MINUTES} 分钟内有效。若不是你本人操作，请忽略这封邮件。"
        )

        with smtplib.SMTP(Config.SMTP_HOST, Config.SMTP_PORT, timeout=15) as smtp:
            if Config.SMTP_USE_TLS:
                smtp.starttls()
            if Config.SMTP_USERNAME or Config.SMTP_PASSWORD:
                smtp.login(Config.SMTP_USERNAME, Config.SMTP_PASSWORD)
            smtp.send_message(message)
        return True

    def verify_register_code(email: str, code: str) -> None:
        if not Config.EMAIL_VERIFICATION_REQUIRED:
            return
        normalized_code = code.strip()
        if not re.match(r"^\d{6}$", normalized_code):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请输入 6 位邮箱验证码。")

        record = state.auth_db.get_latest_email_verification_code(email, "register")
        if not record:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先获取邮箱验证码。")
        if record["used_at"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码已使用，请重新获取。")
        if record["attempts"] >= record["max_attempts"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码尝试次数过多，请重新获取。")
        if datetime.fromisoformat(str(record["expires_at"])) < datetime.now():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码已过期，请重新获取。")

        expected_hash = email_code_hash(email, normalized_code)
        if not hmac.compare_digest(expected_hash, record["code_hash"]):
            state.auth_db.increment_email_verification_attempts(record["id"])
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码错误，请重新输入。")

        state.auth_db.mark_email_verification_code_used(record["id"])

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        try:
            db_conn = state.auth_db.get_connection()
            db_conn.close()
        except Exception as exc:
            db_url = os.getenv("DATABASE_URL")
            if not db_url:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="数据库配置缺失，请检查服务器环境变量。",
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="数据库连接失败，请检查 PostgreSQL 服务是否已启动。",
                )
        return {"ok": True, "database": "connected"}

    @app.post("/api/resumes/upload")
    async def upload_resume(
        file: UploadFile = File(...),
        user_id: Any = Depends(current_user_id)
    ) -> dict[str, Any]:
        content = await file.read()
        if len(content) > 10 * 1024 * 1024:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传文件过大，请压缩后重新上传。")

        content_hash = hashlib.sha256(content).hexdigest()
        existing_resume = await asyncio.to_thread(
            state.auth_db.find_user_resume_by_content_hash,
            user_id,
            content_hash,
        )
        if existing_resume:
            await asyncio.to_thread(
                state.auth_db.restore_user_resume_by_content_hash,
                user_id,
                content_hash,
            )
            existing_resume_id = str(
                existing_resume.get("file", {}).get("id") or ""
            )
            existing_resume = await asyncio.to_thread(
                ensure_resume_sections,
                user_id,
                existing_resume_id,
                existing_resume,
            )
            print(f"[UPLOAD] Reused existing resume version with matching content hash for '{file.filename}'.")
            existing_resume_id = str(existing_resume.get("file", {}).get("id") or existing_resume_id)
            state.resume_store[existing_resume_id] = {
                "parsed_resume": existing_resume,
                "user_id": user_id,
            }
            return {
                "resumeFile": existing_resume["file"],
                "parsedResume": existing_resume,
            }

        try:
            parsed_resume = await asyncio.to_thread(parse_resume, file.filename or "resume", file.content_type or "", content)
        except DocumentParseError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        # Save to persistent database
        try:
            await asyncio.to_thread(
                state.auth_db.save_user_resume,
                user_id=user_id,
                resume_id=parsed_resume["file"]["id"],
                file_name=parsed_resume["file"]["name"],
                file_size=parsed_resume["file"]["size"],
                file_type=parsed_resume["file"]["type"],
                parsed_resume=parsed_resume,
                content_hash=content_hash,
            )
        except Exception as e:
            print(f"[ERROR] Failed to save resume to DB: {e}")

        state.resume_store[parsed_resume["file"]["id"]] = {
            "parsed_resume": parsed_resume,
            "user_id": user_id,
        }
        return {
            "resumeFile": parsed_resume["file"],
            "parsedResume": parsed_resume,
        }

    @app.post("/api/documents/docx-boundary-check")
    async def check_docx_boundary_format(
        file: UploadFile = File(...),
        save_evidence: Optional[bool] = Form(None),
        region_ratio: Optional[float] = Form(None),
        edge_band_ratio: Optional[float] = Form(None),
        use_llm: Optional[bool] = Form(None),
        llm_required: Optional[bool] = Form(None),
        user_id: Any = Depends(current_user_id),
    ) -> dict[str, Any]:
        original_name = file.filename or "upload.docx"
        if Path(original_name).suffix.lower() != ".docx":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持 DOCX 文件")

        content = await file.read()
        if not content:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件为空，请重新选择")
        if len(content) > 10 * 1024 * 1024:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传文件过大，请压缩后重新上传。")

        task_id = f"docx-boundary-{uuid4().hex}"
        workspace_dir = Path(Config.USER_DB_DIR) / "workspaces" / f"user_{user_id}" / f"task_{task_id}" / "docx_boundary_input"
        workspace_dir.mkdir(parents=True, exist_ok=True)
        input_path = workspace_dir / "input.docx"
        await asyncio.to_thread(input_path.write_bytes, content)

        base_config = DocxBoundaryCheckConfig.from_app_config()
        runtime_config = DocxBoundaryCheckConfig(
            region_ratio=region_ratio if region_ratio is not None else base_config.region_ratio,
            edge_band_ratio=edge_band_ratio if edge_band_ratio is not None else base_config.edge_band_ratio,
            dark_pixel_threshold=base_config.dark_pixel_threshold,
            min_edge_dark_pixels=base_config.min_edge_dark_pixels,
            min_edge_dark_ratio=base_config.min_edge_dark_ratio,
            horizontal_line_width_ratio=base_config.horizontal_line_width_ratio,
            vertical_line_height_ratio=base_config.vertical_line_height_ratio,
            min_vertical_edge_lines=base_config.min_vertical_edge_lines,
            save_evidence=save_evidence if save_evidence is not None else base_config.save_evidence,
            evidence_dir=base_config.evidence_dir,
            llm_enabled=use_llm if use_llm is not None else base_config.llm_enabled,
            llm_required=llm_required if llm_required is not None else base_config.llm_required,
            llm_model=base_config.llm_model,
            llm_base_url=base_config.llm_base_url,
            llm_temperature=base_config.llm_temperature,
            llm_timeout=base_config.llm_timeout,
        ).normalized()

        try:
            return await asyncio.to_thread(
                check_docx_file_boundaries,
                input_path,
                user_id=user_id,
                task_id=task_id,
                config=runtime_config,
                file_label=Path(original_name).name,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    @app.get("/api/resumes")
    def list_resumes(user_id: Any = Depends(current_user_id)) -> dict[str, Any]:
        resumes = state.auth_db.list_user_resumes(user_id)
        return {"resumes": resumes}

    @app.get("/api/resumes/{resume_id}")
    def get_resume(resume_id: str, user_id: Any = Depends(current_user_id)) -> dict[str, Any]:
        entry = state.resume_store.get(resume_id)
        if entry is None:
            db_resume = state.auth_db.get_user_resume(user_id, resume_id)
            if db_resume:
                entry = {
                    "parsed_resume": db_resume,
                    "user_id": user_id,
                }
                state.resume_store[resume_id] = entry

        if entry is None or entry.get("user_id") != user_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="记录不存在或无权访问。")
        parsed_resume = ensure_resume_sections(user_id, resume_id, entry.get("parsed_resume") or {})
        entry["parsed_resume"] = parsed_resume
        return {"parsedResume": parsed_resume}

    @app.delete("/api/resumes/{resume_id}")
    def delete_resume(resume_id: str, user_id: Any = Depends(current_user_id)) -> dict[str, Any]:
        success_auth = state.auth_db.delete_user_resume(user_id, resume_id)
        success_svc = False
        try:
            success_svc = state.service.user_db(user_id).delete_user_resume(user_id, resume_id)
        except Exception:
            pass
        state.resume_store.pop(resume_id, None)
        return {"ok": success_auth or success_svc}

    @app.post("/api/resumes/retrieve")
    def retrieve_resume(
        payload: ResumeRetrieveRequest,
        user_id: Any = Depends(current_user_id)
    ) -> dict[str, Any]:
        entry = state.resume_store.get(payload.resumeFileId)
        if entry is None:
            db_resume = state.auth_db.get_user_resume(user_id, payload.resumeFileId)
            if db_resume:
                entry = {
                    "parsed_resume": db_resume,
                    "user_id": user_id,
                }
                state.resume_store[payload.resumeFileId] = entry

        if entry is None or entry.get("user_id") != user_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="记录不存在或无权访问。")
        parsed_resume = ensure_resume_sections(user_id, payload.resumeFileId, entry.get("parsed_resume") or {})
        entry["parsed_resume"] = parsed_resume
        try:
            return retrieve_chunks(payload.jdText, parsed_resume.get("chunks", []), payload.topK)
        except DocumentParseError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/api/resumes/{resume_id}/vectorize")
    async def vectorize_resume(resume_id: str, user_id: Any = Depends(current_user_id)) -> dict[str, Any]:
        # 涓夌骇鑷€傚簲璇诲彇鍏滃簳锛?
        # 1. 鍐呭瓨缂撳瓨 resume_store
        entry = state.resume_store.get(resume_id)
        db_resume = None
        if entry and entry.get("user_id") == user_id:
            db_resume = entry.get("parsed_resume")

        # 2. state.auth_db
        if not db_resume:
            db_resume = await asyncio.to_thread(state.auth_db.get_user_resume, user_id, resume_id)

        # 3. state.service.user_db(user_id)
        if not db_resume:
            try:
                db_resume = await asyncio.to_thread(
                    lambda: state.service.user_db(user_id).get_user_resume(user_id, resume_id)
                )
            except Exception:
                pass

        if not db_resume:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="简历不存在或无权访问。")

        db_resume = await asyncio.to_thread(ensure_resume_sections, user_id, resume_id, db_resume)
        chunks = db_resume.get("chunks", [])
        if not chunks:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="简历中不包含有效的文本片段。")

        from concurrent.futures import ThreadPoolExecutor

        def process_chunk(chunk):
            content = chunk.get("content") or chunk.get("text") or ""
            emb = state.service.get_embedding_for_text(user_id, content)
            if emb:
                if "metadata" not in chunk:
                    chunk["metadata"] = {}
                chunk["metadata"]["embedding"] = emb
                chunk["embedding"] = emb

        max_workers = min(16, len(chunks))

        def run_thread_pool():
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                list(executor.map(process_chunk, chunks))

        await asyncio.to_thread(run_thread_pool)

        db_resume["vectorized"] = True
        db_resume["chunks"] = chunks

        file_name = db_resume.get("file", {}).get("name", "resume.pdf")
        file_size = db_resume.get("file", {}).get("size", 1024)
        file_type = db_resume.get("file", {}).get("type", "application/pdf")

        save_errors = []
        try:
            await asyncio.to_thread(
                state.auth_db.save_user_resume,
                user_id=user_id,
                resume_id=resume_id,
                file_name=file_name,
                file_size=file_size,
                file_type=file_type,
                parsed_resume=db_resume
            )
        except Exception as e:
            save_errors.append(f"auth_db: {e}")

        try:
            await asyncio.to_thread(
                lambda: state.service.user_db(user_id).save_user_resume(
                    user_id=user_id,
                    resume_id=resume_id,
                    file_name=file_name,
                    file_size=file_size,
                    file_type=file_type,
                    parsed_resume=db_resume
                )
            )
        except Exception as e:
            save_errors.append(f"service_db: {e}")

        if len(save_errors) == 2:
            print(f"[ERROR] Failed to save vectorized resume: {save_errors}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"保存向量化简历失败: {save_errors}")

        state.resume_store[resume_id] = {
            "parsed_resume": db_resume,
            "user_id": user_id
        }

        return {"ok": True, "vectorized": True}

    @app.post("/api/analysis/job-rag")
    def analyze_job_rag(
        payload: JobRagAnalyzeRequest,
        user_id: Any = Depends(current_user_id)
    ) -> dict[str, Any]:
        if len(payload.jdText) > 5000:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="输入内容过长，请减少无关内容后再分析。")

        entry = state.resume_store.get(payload.resumeFileId) if payload.resumeFileId else None
        if entry is None and payload.resumeFileId:
            db_resume = state.auth_db.get_user_resume(user_id, payload.resumeFileId)
            if db_resume:
                entry = {
                    "parsed_resume": db_resume,
                    "user_id": user_id,
                }
                state.resume_store[payload.resumeFileId] = entry

        if entry is not None:
            if entry.get("user_id") != user_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="记录不存在或无权访问。")
            parsed_resume = entry.get("parsed_resume")
        else:
            parsed_resume = None

        if parsed_resume is None and payload.parsedResume:
            parsed_resume = payload.parsedResume
        if parsed_resume is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="记录不存在或无权访问。")
        if payload.resumeFileId:
            parsed_resume = ensure_resume_sections(user_id, payload.resumeFileId, parsed_resume)
        chunks = parsed_resume.get("chunks", []) or []
        selected = [chunk for chunk in chunks if chunk.get("id") in set(payload.retrievedChunkIds)]
        if not selected and payload.retrievedChunks:
            selected = payload.retrievedChunks
        if not selected:
            selected = retrieve_chunks(payload.jdText, chunks, 8)["topChunks"]
        resume_file = payload.resumeFile or parsed_resume.get("file") or {}
        try:
            llm_result = analyze_job_with_doubao(
                {
                    "jdText": payload.jdText,
                    "targetType": payload.targetType,
                    "jobDirection": payload.jobDirection,
                    "draft": payload.draft,
                    "resumeFile": resume_file,
                    "parsedResume": parsed_resume,
                    "retrievedChunks": selected,
                    "retrievalSummary": payload.retrievalSummary,
                },
                user_id=user_id
            )
        except DoubaoAnalysisError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
        return {
            "id": uuid4().hex,
            "createdAt": datetime.now().isoformat(),
            "draft": payload.draft,
            "resumeFile": resume_file,
            "parsedResume": parsed_resume,
            "retrievedResumeChunks": selected,
            "retrievalSummary": payload.retrievalSummary,
            "llmProvider": "doubao-compatible",
            **llm_result,
        }

    @app.post("/api/auth/register")
    def register(payload: RegisterRequest, response: Response) -> dict[str, Any]:
        email = normalize_email(payload.username)
        verify_register_code(email, payload.verification_code)
        try:
            user_id = state.auth_db.create_user(email, payload.password)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        token = issue_token(user_id)
        set_session_cookie(response, token)
        return auth_payload(user_id, token)

    @app.post("/api/auth/send-email-code")
    def send_register_email_code(payload: EmailCodeRequest, request: Request) -> dict[str, Any]:
        email = normalize_email(payload.username)
        client_ip = request.client.host if request.client else "unknown"
        check_rate_limit(f"email_code_ip:{client_ip}", 10, 3600)
        check_rate_limit(f"email_code_addr:{email}", 3, 600)

        if state.auth_db.get_user_by_username(email):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该邮箱已注册，请直接登录。")

        code = f"{secrets.randbelow(1_000_000):06d}"
        expires_at = datetime.now() + timedelta(minutes=Config.EMAIL_CODE_TTL_MINUTES)
        state.auth_db.create_email_verification_code(
            email=email,
            code_hash=email_code_hash(email, code),
            purpose="register",
            expires_at=expires_at,
            max_attempts=Config.EMAIL_CODE_MAX_ATTEMPTS,
            request_ip=client_ip,
        )

        try:
            sent = send_email_code(email, code)
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"验证码邮件发送失败：{str(exc)}") from exc

        response: dict[str, Any] = {
            "ok": True,
            "message": "验证码已发送，请查收邮箱。",
            "expiresInSeconds": Config.EMAIL_CODE_TTL_MINUTES * 60,
        }
        if not sent and not Config.IS_PRODUCTION:
            response["devCode"] = code
            response["message"] = "本地未配置 SMTP，验证码已输出到后端日志。"
        return response

    @app.post("/api/auth/login")
    def login(payload: AuthRequest, request: Request, response: Response) -> dict[str, Any]:
        norm_username = normalize_username(payload.username)
        key_user = f"login_fail_user:{norm_username}"

        # Clean up old timestamps to keep memory clean
        cutoff = time.time() - 900
        limiter.requests[key_user] = [t for t in limiter.requests[key_user] if t > cutoff]

        if len(limiter.requests[key_user]) >= 5:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="请求过于频繁，请稍后再试。")

        user = state.auth_db.authenticate_user(payload.username, payload.password)
        if user is None or user.id is None:
            limiter.requests[key_user].append(time.time())
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="邮箱或密码错误，请重新输入。")

        if user.role != "admin":
            # Strip timezone to safely compare naive datetime.now() with potentially aware user.expires_at
            user_expires = user.expires_at.replace(tzinfo=None) if user.expires_at else None
            if user_expires and datetime.now() > user_expires:
                if user.is_active:
                    try:
                        state.auth_db.admin_update_user_status(user.id, False)
                        state.auth_db.delete_user_sessions(user.id)
                    except Exception as exc:
                        print(f"[WARNING] Concurrent login expiry update for user_id={user.id}: {exc}")
                    user.is_active = False
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="该账号已过期停用，请联系管理员。")

            if not user.is_active:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="该账号已被停用，请联系管理员。")


        token = issue_token(user.id)
        set_session_cookie(response, token)
        return auth_payload(user.id, token)


    @app.post("/api/auth/logout")
    def logout(response: Response, user_id: Any = Depends(current_user_id)) -> dict[str, bool]:
        state.auth_db.delete_user_sessions(user_id)
        response.delete_cookie(key="session_id", httponly=True, samesite="lax", secure=Config.IS_PRODUCTION)
        return {"ok": True}

    @app.post("/api/models/chat-completions")
    async def chat_completions(
        payload: ModelProxyRequest,
        user_id: Any = Depends(current_user_id)
    ) -> Response:
        user = state.auth_db.get_user_by_id(user_id)
        if user and user.role != "admin":
            if user.generation_limit is None or user.generation_limit <= 0:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="你的账号生成额度已用尽，请联系管理员增加次数。",
                )

        if payload.provider and ("embed" in payload.provider.lower() or "doubao" in payload.provider.lower()):
            raise HTTPException(status_code=400, detail="Unsupported chat provider")

        check_rate_limit(f"chat_comp:{user_id}", 10, 3600, skip=user is not None and user.role == "admin")

        model_id = payload.modelId.strip()
        api_key, resolved_config_id, resolved_assignment_id = state.auth_db.get_model_api_key_v2(
            user_id, payload.provider, model_id, payload.configId
        )
        if not api_key:
            env_key = Config.GEMINI_API_KEY if payload.provider == "gemini" else Config.LLM_API_KEY
            api_key = env_key.strip() if env_key else ""

        if not api_key:
            raise HTTPException(status_code=500, detail="未找到可用的 LLM API Key。请在模型配置中保存 API Key，或在服务器 .env 中设置。")

        if not re.match(r"^[a-zA-Z0-9\-_./]+$", model_id):
            raise HTTPException(status_code=400, detail="Invalid model ID format")

        if payload.provider == "gemini":
            url = f"{chat_base_url(user_id, payload.provider, model_id)}/models/{model_id}:generateContent"
            headers = {
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
            }
            request_json = payload.requestBody
            wrap_openai = False
        else:
            base_url = chat_base_url_for_config(resolved_config_id) or chat_base_url(user_id, payload.provider, model_id)
            if not base_url:
                raise HTTPException(status_code=400, detail="Base URL is required for OpenAI Compatible or Custom chat models.")
            chat_extra = chat_config_extra(resolved_config_id)
            stream_api_mode = BaseAgent._normalize_stream_api_mode(
                chat_extra.get("streamApiMode") or chat_extra.get("stream_api_mode")
            )
            if stream_api_mode == "responses":
                url = openai_responses_url(base_url)
                request_json = openai_responses_body(
                    model_id,
                    payload.requestBody,
                    prompt_cache_extra=chat_extra,
                    prompt_cache_namespace="model_proxy",
                )
                wrap_openai = "responses"
            else:
                url = openai_chat_url(base_url)
                request_json = openai_chat_body(model_id, payload.requestBody)
                wrap_openai = "chat_completions"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            }

        start_time = time.time()
        success = False
        res = None
        try:
            async with httpx.AsyncClient() as client:
                res = await client.post(url, headers=headers, json=request_json, timeout=300.0)
                success = res.status_code == 200
                if wrap_openai and res.status_code == 200:
                    try:
                        res_json = res.json()
                    except Exception:
                        raise HTTPException(
                            status_code=502,
                            detail=f"Failed to communicate with LLM provider: Expected JSON but got text/html. Upstream response preview: {res.text[:500]}"
                        )
                    wrapped_json = (
                        wrap_openai_responses_response(res_json)
                        if wrap_openai == "responses"
                        else wrap_openai_chat_response(res_json)
                    )
                    return Response(
                        content=json.dumps(wrapped_json, ensure_ascii=False),
                        status_code=200,
                        media_type="application/json"
                    )
                # Intercept non-200 upstream responses that return HTML (e.g. Cloudflare 504/502 pages)
                if res.status_code != 200:
                    content_type = (res.headers.get("content-type") or "").lower()
                    raw_text = res.text[:500] if res.text else ""
                    is_html = "text/html" in content_type or raw_text.strip().startswith("<!") or raw_text.strip().startswith("<html")
                    if is_html:
                        status_map = {
                            502: "上游模型服务网关错误 (502)，请稍后重试或切换模型。",
                            503: "上游模型服务暂时不可用 (503)，请稍后重试。",
                            504: "上游模型服务响应超时 (504)，请稍后重试或切换模型。",
                            429: "上游模型服务请求限流 (429)，请稍后重试。",
                            403: "上游模型服务拒绝访问 (403)，可能是额度不足或 API Key 无效。",
                        }
                        detail = status_map.get(res.status_code, f"上游模型服务返回异常 ({res.status_code})，请稍后重试或切换模型。")
                        raise HTTPException(status_code=502, detail=detail)
                    # Non-HTML error: try to extract a clean error message from JSON
                    try:
                        err_json = res.json()
                        err_msg = err_json.get("error", {}).get("message", "") if isinstance(err_json.get("error"), dict) else str(err_json.get("error", ""))
                        if err_msg:
                            err_status = 502 if res.status_code in (401, 403) else res.status_code
                            raise HTTPException(status_code=err_status, detail=f"涓婃父妯″瀷鏈嶅姟閿欒 ({res.status_code}): {err_msg}")
                    except (ValueError, TypeError):
                        pass
                returned_status = 502 if res.status_code in (401, 403) else res.status_code
                return Response(
                    content=res.content,
                    status_code=returned_status,
                    media_type="application/json"
                )
        except Exception as exc:
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=502, detail=f"Failed to communicate with LLM provider: {str(exc)}")
        finally:
            duration = int((time.time() - start_time) * 1000)
            print(f"[AUDIT] Event: model_chat_completions | userId: {user_id} | provider: {payload.provider} | modelId: {model_id} | durationMs: {duration} | success: {success}")

            # Log usage non-sensitively
            try:
                prompt_tokens = None
                completion_tokens = None
                total_tokens = None
                input_chars = len(prompt_from_gemini_request(payload.requestBody)) if payload.provider == "gemini" else 0
                output_chars = 0
                error_type = None

                if success and res is not None:
                    res_data = res.json()
                    if payload.provider == "gemini":
                        usage = res_data.get("usageMetadata", {})
                        prompt_tokens = usage.get("promptTokenCount")
                        completion_tokens = usage.get("candidatesTokenCount")
                        total_tokens = usage.get("totalTokenCount")

                        candidates = res_data.get("candidates", [])
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            if parts:
                                output_chars = len(parts[0].get("text", ""))
                    else:
                        if wrap_openai == "responses":
                            usage = res_data.get("usage", {})
                            prompt_tokens = usage.get("input_tokens") or usage.get("prompt_tokens")
                            completion_tokens = usage.get("output_tokens") or usage.get("completion_tokens")
                            total_tokens = usage.get("total_tokens")
                            output_chars = len(BaseAgent._extract_response_text(res_data))
                        elif wrap_openai:
                            usage = res_data.get("usage", {})
                            prompt_tokens = usage.get("prompt_tokens")
                            completion_tokens = usage.get("completion_tokens")
                            total_tokens = usage.get("total_tokens")
                            choices = res_data.get("choices", [])
                            if choices:
                                output_chars = len(choices[0].get("message", {}).get("content", ""))
                        else:
                            usage = res_data.get("usageMetadata", {}) or res_data.get("usage", {})
                            prompt_tokens = usage.get("prompt_tokens") or usage.get("promptTokenCount")
                            completion_tokens = usage.get("completion_tokens") or usage.get("candidatesTokenCount")
                            total_tokens = usage.get("total_tokens") or usage.get("totalTokenCount")
                else:
                    error_type = f"HTTP_{res.status_code}" if res is not None else "CONNECTION_ERROR"

                if payload.provider != "gemini":
                    try:
                        input_chars = len(prompt_from_gemini_request(payload.requestBody))
                    except Exception:
                        pass

                analysis_id = payload.requestBody.get("analysis_id") or payload.requestBody.get("analysisId")

                asyncio.create_task(
                    persist_model_usage_in_background(
                        state.auth_db,
                        {
                            "user_id": user_id,
                            "config_id": resolved_config_id,
                            "assignment_id": resolved_assignment_id,
                            "analysis_id": analysis_id,
                            "provider": payload.provider,
                            "model_id": model_id,
                            "usage_type": "chat",
                            "endpoint": None,
                            "success": success,
                            "error_type": error_type,
                            "prompt_tokens": prompt_tokens,
                            "completion_tokens": completion_tokens,
                            "total_tokens": total_tokens,
                            "input_chars": input_chars,
                            "output_chars": output_chars,
                            "latency_ms": duration,
                        },
                    ),
                    name=f"model-usage-audit-{user_id}",
                )
            except Exception as e:
                print(f"[ERROR] Failed to log model usage: {e}")

    @app.post("/api/models/embeddings")
    async def embeddings(
        payload: ModelProxyRequest,
        user_id: Any = Depends(current_user_id)
    ) -> Response:
        user = state.auth_db.get_user_by_id(user_id)
        if user and user.role != "admin":
            if user.generation_limit is None or user.generation_limit <= 0:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="你的账号生成额度已用尽，请联系管理员增加次数。",
                )

        if not payload.provider or ("embed" not in payload.provider.lower() and "doubao" not in payload.provider.lower() and "volc" not in payload.provider.lower()):
            raise HTTPException(status_code=400, detail="Unsupported embedding provider")

        check_rate_limit(f"embeddings:{user_id}", 30, 3600, skip=user is not None and user.role == "admin")

        api_key, resolved_config_id, resolved_assignment_id = state.auth_db.get_model_api_key_v2(
            user_id, payload.provider, payload.modelId.strip(), payload.configId
        )
        if not api_key:
            api_key = Config.LLM_API_KEY.strip() if Config.LLM_API_KEY else ""

        if not api_key or api_key.lower() in PLACEHOLDER_KEYS:
            raise HTTPException(status_code=500, detail="未找到可用的向量模型 API Key。请在模型配置中保存 API Key，或在服务器 .env 中设置。")

        endpoint = payload.endpoint or "/embeddings/multimodal"
        if not re.match(r"^/[a-zA-Z0-9\-_/]+$", endpoint):
            raise HTTPException(status_code=400, detail="Invalid endpoint format")

        volcano_base = (Config.LLM_BASE_URL or "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
        url = f"{volcano_base}{endpoint}"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        import hashlib

        # Extract text to embed
        input_text = None
        input_data = payload.requestBody.get("input")
        if input_data:
            if isinstance(input_data, list) and len(input_data) > 0:
                first = input_data[0]
                if isinstance(first, str):
                    input_text = first
                elif isinstance(first, dict):
                    input_text = first.get("text")
            elif isinstance(input_data, str):
                input_text = input_data

        content_hash = None
        if input_text:
            content_hash = hashlib.sha256(input_text.encode('utf-8')).hexdigest()

        # Check cache if we successfully extracted the text
        if content_hash:
            cached_vector = state.auth_db.get_cached_embedding(
                user_id, content_hash, payload.provider, payload.modelId.strip()
            )
            if cached_vector is not None:
                # Cache hit! Construct a mocked response format based on provider/endpoint
                if "/multimodal" in endpoint or "multimodal" in payload.provider.lower():
                    mock_res = {"data": {"embedding": cached_vector}}
                else:
                    mock_res = {"data": [{"embedding": cached_vector}]}

                print(f"[AUDIT] Cache Hit: model_embeddings | userId: {user_id} | provider: {payload.provider} | modelId: {payload.modelId}")
                return Response(
                    content=json.dumps(mock_res),
                    status_code=200,
                    media_type="application/json"
                )

        start_time = time.time()
        success = False
        res = None
        try:
            async with httpx.AsyncClient() as client:
                res = await client.post(url, headers=headers, json=payload.requestBody, timeout=120.0)
                success = res.status_code == 200
                if success and content_hash:
                    # Save to cache
                    try:
                        res_json = res.json()
                        embedding_vector = None
                        if "/multimodal" in endpoint or "multimodal" in payload.provider.lower():
                            emb = res_json.get("data", {}).get("embedding")
                            if isinstance(emb, list):
                                embedding_vector = emb
                        else:
                            data = res_json.get("data")
                            if isinstance(data, list) and len(data) > 0:
                                emb = data[0].get("embedding")
                                if isinstance(emb, list):
                                    embedding_vector = emb
                        if embedding_vector:
                            state.auth_db.save_embedding(
                                user_id=user_id,
                                content_hash=content_hash,
                                embedding=embedding_vector,
                                provider=payload.provider,
                                model_id=payload.modelId.strip()
                            )
                    except Exception as cache_err:
                        print(f"[ERROR] Failed to save embedding to cache: {cache_err}")

                returned_status = 502 if res.status_code in (401, 403) else res.status_code
                return Response(
                    content=res.content,
                    status_code=returned_status,
                    media_type="application/json"
                )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Failed to communicate with embedding provider: {str(exc)}")
        finally:
            duration = int((time.time() - start_time) * 1000)
            print(f"[AUDIT] Event: model_embeddings | userId: {user_id} | provider: {payload.provider} | modelId: {payload.modelId} | durationMs: {duration} | success: {success}")

            # Log usage non-sensitively
            try:
                prompt_tokens = None
                total_tokens = None
                input_chars = 0
                error_type = None

                try:
                    input_data = payload.requestBody.get("input", [])
                    if isinstance(input_data, list):
                        for item in input_data:
                            if isinstance(item, str):
                                input_chars += len(item)
                            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                                input_chars += len(item["text"])
                    elif isinstance(input_data, str):
                        input_chars = len(input_data)
                except Exception:
                    pass

                if success and res is not None:
                    try:
                        usage = res.json().get("usage", {})
                        prompt_tokens = usage.get("prompt_tokens")
                        total_tokens = usage.get("total_tokens")
                    except Exception:
                        pass
                else:
                    error_type = f"HTTP_{res.status_code}" if res is not None else "CONNECTION_ERROR"

                analysis_id = payload.requestBody.get("analysis_id") or payload.requestBody.get("analysisId")

                state.auth_db.log_model_usage(
                    user_id=user_id,
                    config_id=resolved_config_id,
                    assignment_id=resolved_assignment_id,
                    analysis_id=analysis_id,
                    provider=payload.provider,
                    model_id=payload.modelId.strip(),
                    usage_type="embedding",
                    endpoint=endpoint,
                    success=success,
                    error_type=error_type,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=None,
                    total_tokens=total_tokens,
                    input_chars=input_chars,
                    output_chars=0,
                    latency_ms=duration
                )
            except Exception as e:
                print(f"[ERROR] Failed to log embedding usage: {e}")

    @app.post("/api/models/test-connection")
    async def test_connection(
        payload: TestConnectionRequest,
        user_id: Any = Depends(current_user_id)
    ) -> dict[str, Any]:
        user_for_rate = state.auth_db.get_user_by_id(user_id)
        check_rate_limit(f"test_conn:{user_id}", 10, 3600, skip=user_for_rate is not None and user_for_rate.role == "admin")

        model_id = payload.modelId.strip()
        api_key, resolved_config_id, resolved_assignment_id = state.auth_db.get_model_api_key_v2(
            user_id, payload.provider, model_id, payload.configId
        )
        if not api_key:
            env_key = Config.GEMINI_API_KEY if payload.provider == "gemini" else Config.LLM_API_KEY
            api_key = env_key.strip() if env_key else ""

        start_time = time.time()
        success = False
        res_status = None
        message = ""
        url = ""

        try:
            if payload.provider == "gemini":
                if not api_key:
                    message = "未找到可用的 Gemini API Key，请在模型配置或服务器 .env 中设置 GEMINI_API_KEY。"
                    return {"ok": False, "message": message}

                gemini_base = (Config.GEMINI_BASE_URL or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
                url = f"{gemini_base}/models/{payload.modelId}:generateContent"

                test_body = {
                    "contents": [{"parts": [{"text": "Return exactly:\n{\"ok\":true}"}]}],
                    "generationConfig": {"temperature": 0, "maxOutputTokens": 256, "responseMimeType": "application/json"}
                }

                async with httpx.AsyncClient() as client:
                    res = await client.post(url, headers={"Content-Type": "application/json", "x-goog-api-key": api_key}, json=test_body, timeout=20.0)
                    res_status = res.status_code
                    success = res.status_code == 200
                    if success:
                        return {
                            "ok": True,
                            "message": "连接成功",
                            "upstreamStatus": res.status_code,
                            "url": url,
                            "rawResponseText": res.text[:500],
                        }
                    message = "Gemini 连接失败，请检查 Model ID、API Key 权限或额度。"
                    try:
                        body = res.json()
                        message = body.get("error", {}).get("message") or body.get("message") or message
                    except Exception:
                        pass
                    return {
                        "ok": False,
                        "message": message,
                        "upstreamStatus": res.status_code,
                        "url": url,
                        "rawResponseText": res.text[:500],
                    }

            elif "doubao" in payload.provider or "volc" in payload.provider or payload.provider == "openai-compatible" or payload.provider == "custom":
                if not api_key or api_key.lower() in PLACEHOLDER_KEYS:
                    message = "未找到可用的模型 API Key，请在模型配置或服务器 .env 中设置 LLM_API_KEY。"
                    return {"ok": False, "message": message}

                if payload.type == "chat" and payload.provider in {"openai-compatible", "custom"}:
                    base_url = chat_base_url_for_config(resolved_config_id) or chat_base_url(user_id, payload.provider, model_id)
                    if not base_url:
                        message = "请先为该大语言模型配置 Base URL。"
                        return {"ok": False, "message": message}
                    chat_extra = chat_config_extra(resolved_config_id)
                    stream_api_mode = BaseAgent._normalize_stream_api_mode(
                        chat_extra.get("streamApiMode") or chat_extra.get("stream_api_mode")
                    )
                    if stream_api_mode == "responses":
                        url = openai_responses_url(base_url)
                        test_body = openai_responses_body(
                            payload.modelId,
                            {
                                "contents": [
                                    {"role": "user", "parts": [{"text": "Return exactly: {\"ok\": true} in JSON format."}]}
                                ],
                                "generationConfig": {
                                    "temperature": 0,
                                    "maxOutputTokens": 256,
                                    "responseMimeType": "application/json",
                                },
                            },
                            prompt_cache_extra=chat_extra,
                            prompt_cache_namespace="model_test_connection",
                        )
                    else:
                        url = openai_chat_url(base_url)
                        test_body = {
                            "model": payload.modelId,
                            "messages": [{"role": "user", "content": "Return exactly: {\"ok\": true} in JSON format."}],
                            "temperature": 0,
                            "max_tokens": 256,
                            "response_format": {"type": "json_object"},
                        }
                    async with httpx.AsyncClient() as client:
                        res = await client.post(url, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json=test_body, timeout=20.0)
                        res_status = res.status_code
                        success = res.status_code == 200
                        if success:
                            return {
                                "ok": True,
                                "message": "连接成功",
                                "upstreamStatus": res.status_code,
                                "url": url,
                                "rawResponseText": res.text[:500],
                            }
                        message = "大语言模型连接失败，请检查 Base URL、Model ID、API Key 权限或额度。"
                        try:
                            body = res.json()
                            message = body.get("error", {}).get("message") or body.get("message") or message
                        except Exception:
                            pass
                        return {
                            "ok": False,
                            "message": message,
                            "upstreamStatus": res.status_code,
                            "url": url,
                            "rawResponseText": res.text[:500],
                        }

                volcano_base = (Config.LLM_BASE_URL or "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
                endpoint = payload.endpoint or "/embeddings/multimodal"
                url = f"{volcano_base}{endpoint}"

                test_body = {
                    "model": payload.modelId,
                    "input": [{"type": "text", "text": "test"}] if endpoint == "/embeddings/multimodal" else ["test"]
                }
                async with httpx.AsyncClient() as client:
                    res = await client.post(url, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json=test_body, timeout=20.0)
                    res_status = res.status_code
                    success = res.status_code == 200
                    if success:
                        return {
                            "ok": True,
                            "message": "连接成功",
                            "upstreamStatus": res.status_code,
                            "url": url,
                            "rawResponseText": res.text[:500],
                        }
                    message = "向量模型连接失败，请检查 Model ID、API Key 权限或额度。"
                    try:
                        body = res.json()
                        message = body.get("error", {}).get("message") or body.get("message") or message
                    except Exception:
                        pass
                    return {
                        "ok": False,
                        "message": message,
                        "upstreamStatus": res.status_code,
                        "url": url,
                        "rawResponseText": res.text[:500],
                    }

            message = "不支持的 Provider 连接测试。"
            return {"ok": False, "message": message}

        except Exception as exc:
            message = f"连接失败：{str(exc)}"
            return {
                "ok": False,
                "message": message,
                "url": url,
                "rawResponseText": "",
            }
        finally:
            duration = int((time.time() - start_time) * 1000)
            try:
                error_type = f"HTTP_{res_status}" if res_status is not None else ("EXCEPTION" if not success else None)
                state.auth_db.log_model_usage(
                    user_id=user_id,
                    config_id=resolved_config_id,
                    assignment_id=resolved_assignment_id,
                    analysis_id=None,
                    provider=payload.provider,
                    model_id=model_id,
                    usage_type="model_test",
                    endpoint=payload.endpoint if payload.endpoint else None,
                    success=success,
                    error_type=error_type,
                    prompt_tokens=None,
                    completion_tokens=None,
                    total_tokens=None,
                    input_chars=0,
                    output_chars=0,
                    latency_ms=duration
                )
            except Exception as e:
                print(f"[ERROR] Failed to log test connection usage: {e}")

    @app.get("/api/me")
    def me(user_id: Any = Depends(current_user_id)) -> dict[str, Any]:
        user = state.auth_db.get_user_by_id(user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user_not_found")
        return UserResponse(
            id=user.id or user_id,
            username=user.username,
            role=user.role,
            created_at=user.created_at,
            is_active=user.is_active,
            expires_at=user.expires_at,
            generation_limit=user.generation_limit
        ).model_dump(mode="json")


    @app.get("/api/materials")
    def list_materials(
        source_type: Optional[str] = None,
        user_id: Any = Depends(current_user_id),
    ) -> dict[str, Any]:
        normalized_source_type = source_type.strip().lower() if source_type else None
        return {"documents": state.service.list_knowledge_documents(user_id, normalized_source_type)}

    @app.post("/api/materials")
    async def upload_material(
        file: UploadFile = File(...),
        title: str = Form(default=""),
        source_type: str = Form(default="resume"),
        user_id: Any = Depends(current_user_id),
    ) -> dict[str, Any]:
        content = await file.read()
        if len(content) > 20 * 1024 * 1024:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传文件过大，请限制在 20MB 以内。")
        adapter = UploadedFileAdapter(file.filename or "upload.txt", content)
        source_type = source_type.strip().lower() or "resume"
        try:
            document = await asyncio.to_thread(
                state.service.upload_knowledge_document, user_id, adapter, source_type, title=title
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return {"document": document}

    @app.delete("/api/materials/{document_id}")
    def delete_material(document_id: int, user_id: Any = Depends(current_user_id)) -> dict[str, bool]:
        return {"deleted": state.service.delete_knowledge_document(user_id, document_id)}



    # 鈹€鈹€ Log Reporting Route 鈹€鈹€

    @app.post("/api/logs/report")
    def report_frontend_log(
        payload: dict[str, Any],
        session_id: Optional[str] = Cookie(default=None),
        authorization: str = Header(default="")
    ) -> dict[str, Any]:
        user_id = None
        token = None
        if authorization:
            scheme, _, bearer_token = authorization.partition(" ")
            if scheme.lower() == "bearer" and bearer_token:
                token = bearer_token
        if not token:
            token = session_id
        if token:
            user_id = state.auth_db.get_session_user_id(token)

        event = payload.get("event", "frontend_event")
        detail = payload.get("detail", "")
        level = payload.get("level", "INFO")

        detail_str = f"userId={user_id} | {detail}" if user_id else detail
        from app_log import log_event
        log_event("FRONTEND", level, event, detail_str)
        return {"ok": True}

    # 鈹€鈹€ History routes (record_id uses str for UUID compat) 鈹€鈹€

    @app.get("/api/history")
    def list_history(limit: int = 30, user_id: Any = Depends(current_user_id)) -> dict[str, Any]:
        records = state.auth_db.list_analysis_records(user_id, limit)
        return {"records": records}

    @app.post("/api/history")
    def save_history_record(payload: dict[str, Any], user_id: Any = Depends(current_user_id)) -> dict[str, Any]:
        user = state.auth_db.get_user_by_id(user_id)

        result = payload.get("result") or payload
        is_failed = False
        if isinstance(result, dict) and (result.get("is_failed") or result.get("isFailed")):
            is_failed = True
        elif isinstance(payload, dict) and (payload.get("is_failed") or payload.get("isFailed")):
            is_failed = True

        status_val = payload.get("status") or result.get("status") or "watching"
        if status_val == "failed":
            is_failed = True

        if user and user.role != "admin" and not is_failed:
            if user.generation_limit is None or user.generation_limit <= 0:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="你的账号生成额度已用尽，请联系管理员增加次数。",
                )

        record_id = payload.get("id") or result.get("id")
        new_id = state.auth_db.save_analysis_record(
            user_id=user_id,
            status=status_val,
            result_json=result,
            input_json=result.get("draft"),
            record_id=record_id,
        )

        # Decrement limit for standard users after successful save
        if user and user.role != "admin" and not is_failed:
            state.auth_db.decrement_user_generation_limit(user_id)

        return {"id": new_id, "ok": True}

    @app.get("/api/history/{record_id}")
    def get_record(record_id: str, user_id: Any = Depends(current_user_id)) -> dict[str, Any]:
        record = state.auth_db.get_analysis_record(user_id, record_id)
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="记录不存在或无权访问。")

        # Merging latest agent resume details from the agent task
        task = state.auth_db.get_agent_resume_task(user_id, record_id)
        if task:
            record["optimized_resume_md"] = task.get("optimized_resume_md") or record.get("optimized_resume_md")

            from backend.agents.tools.workspace_tools import get_safe_workspace_path, tool_read_file
            import os
            import json

            try:
                res_log = tool_read_file(user_id, record_id, "modification_log.json")
                if "错误：" not in res_log:
                    record["modification_log"] = json.loads(res_log)
            except:
                pass

            try:
                docx_path = get_safe_workspace_path(user_id, record_id, "optimized_resume.docx")
                record["has_docx"] = os.path.exists(docx_path)
            except:
                pass

            try:
                pdf_path = get_safe_workspace_path(user_id, record_id, "optimized_resume.pdf")
                record["has_pdf"] = os.path.exists(pdf_path)
            except:
                pass

        return {"record": record}

    @app.patch("/api/history/{record_id}")
    def rename_record(
        record_id: str,
        payload: dict[str, Any],
        user_id: Any = Depends(current_user_id),
    ) -> dict[str, bool]:
        new_status = (payload.get("status") or "").strip()
        if new_status:
            state.auth_db.update_analysis_record_status(user_id, record_id, new_status)
        return {"ok": True}

    @app.delete("/api/history/{record_id}")
    def delete_record(record_id: str, user_id: Any = Depends(current_user_id)) -> dict[str, bool]:
        deleted = state.auth_db.delete_analysis_record(user_id, record_id)
        return {"deleted": deleted}

    # 鈹€鈹€ Analysis (with transaction-safe draft conversion) 鈹€鈹€

    @app.post("/api/analysis/background-start")
    def start_background_analysis(
        payload: BackgroundAnalysisStartRequest,
        user_id: Any = Depends(current_user_id)
    ) -> dict[str, Any]:
        if payload.enable_agent_resume and not payload.legacy_artifact_mode:
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="自动生成下载型简历已退役。请在分析完成后进入简历定向优化会话。",
            )
        user = state.auth_db.get_user_by_id(user_id)
        if user and user.role != "admin":
            if user.generation_limit is None or user.generation_limit <= 0:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="你的账号生成额度已用尽，请联系管理员增加次数。",
                )

        # Initialize placeholder in analysis_records with status 'pending'
        steps_list = [
            { "id": "validate", "title": "检查输入与配置", "description": "正在验证输入内容并加载模型配置...", "status": "running" },
            { "id": "resume_embedding", "title": "向量化简历片段", "description": "正在生成简历片段的向量索引...", "status": "pending" },
            { "id": "jd_embedding", "title": "向量化岗位 JD", "description": "正在对岗位描述进行结构化分析与向量化...", "status": "pending" },
            { "id": "retrieve_chunks", "title": "检索最相关片段", "description": "基于语义相似度检索最匹配的简历经历...", "status": "pending" },
            { "id": "gemini_analysis", "title": "调用模型分析", "description": "大语言模型正在进行匹配度分析与改写建议...", "status": "pending" },
        ]
        if payload.enable_agent_resume:
            steps_list.append({ "id": "agent_resume", "title": "智能简历优化", "description": "Agent 正在针对岗位对简历进行定制重写...", "status": "pending" })
        steps_list.append({ "id": "save_history", "title": "保存分析记录", "description": "保存分析数据到云端面板...", "status": "pending" })

        initial_result = {
            "id": payload.record_id,
            "createdAt": datetime.now().isoformat(),
            "draft": payload.draft,
            "status": "pending",
            "progressStep": 0,
            "enable_agent_resume": payload.enable_agent_resume,
            "steps": steps_list
        }

        state.auth_db.save_analysis_record(
            user_id=user_id,
            status="pending",
            result_json=initial_result,
            input_json=payload.draft,
            record_id=payload.record_id
        )

        enqueue_job(
            run_background_resume_analysis_job,
            user_id,
            payload.record_id,
            payload.draft,
            payload.resume_file_id,
            payload.embedding_config_id,
            payload.chat_config_id,
            payload.project_knowledge_scope,
            payload.project_knowledge_document_ids,
            payload.enable_agent_resume,
            payload.legacy_artifact_mode,
            job_id=payload.record_id,
        )

        return {
            "ok": True,
            "recordId": payload.record_id,
            "status": "pending"
        }

    @app.post("/api/analysis/tailor-form-fields")
    def tailor_form_fields(
        payload: TailorFormFieldsRequest,
        user_id: Any = Depends(current_user_id)
    ) -> dict[str, Any]:
        from backend.background_analyzer import tailor_form_fields_py
        try:
            res = tailor_form_fields_py(
                user_id=user_id,
                resume_file_id=payload.resume_file_id,
                jd_text=payload.jd_text,
                fields=payload.fields,
                chat_config_id=payload.chat_config_id
            )
            return {
                "ok": True,
                "tailored_data": res["tailored_data"],
                "profile": res["profile"]
            }
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc)
            )

    @app.post("/api/analyze")
    def analyze(
        payload: AnalyzeRequest,
        user_id: Any = Depends(current_user_id)
    ) -> dict[str, Any]:
        user = state.auth_db.get_user_by_id(user_id)
        if user and user.role != "admin":
            if user.generation_limit is None or user.generation_limit <= 0:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="你的账号生成额度已用尽，请联系管理员增加次数。",
                )

        check_rate_limit(f"analyze:{user_id}", 10, 3600, skip=user is not None and user.role == "admin")
        if len(payload.jd_text) > 5000:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="输入内容过长，请减少无关内容后再分析。")

        task_id = f"internpath-{uuid4().hex}"
        db = state.service.user_db(user_id)
        db.create_analysis_task(
            user_id=user_id,
            task_id=task_id,
            status="PENDING",
            enable_rag=bool(payload.expert_options.get("enableRag", True)),
            enable_verification=bool(payload.expert_options.get("enableVerification", True)),
            enable_hallucination_check=bool(payload.expert_options.get("enableHallucinationCheck", True)),
            enable_rewrite=bool(payload.expert_options.get("enableRewrite", True)),
        )
        enqueue_job(
            run_async_analysis_job,
            user_id,
            payload.model_dump(mode="json"),
            task_id,
            job_id=task_id,
        )
        return {
            "taskId": task_id,
            "status": "PENDING",
            "async": True,
        }

    @app.post("/api/jobs/import")
    def import_job_posting(
        payload: JobImportPayload,
        user_id: Any = Depends(current_user_id)
    ) -> dict[str, Any]:
        # 1. Parse salary range to monthly float in k
        salary_k = parse_salary_range(payload.salary_range)

        # 2. Add job posting (initially with jd_record_id = None)
        from models import JobPosting as PydanticJobPosting
        posting = PydanticJobPosting(
            user_id=user_id,
            title=payload.title,
            company=payload.company,
            region=payload.location,
            salary_monthly_k=salary_k,
            source_url=payload.source_url
        )
        job_id = state.service.add_job_posting(user_id, posting)

        # 3. Run two-stage auto-matching pipeline
        match_result = state.service.auto_match_job_posting(user_id, payload.jd_text)

        # 4. If matching passed, queue full async RAG analysis
        task_id = None
        if match_result.get("passed"):
            task_id = f"internpath-{uuid4().hex}"
            db = state.service.user_db(user_id)
            # Create an analysis task record
            db.create_analysis_task(
                user_id=user_id,
                task_id=task_id,
                status="PENDING",
                enable_rag=True,
                enable_verification=True,
                enable_hallucination_check=True,
                enable_rewrite=True,
            )
            # Fetch active resume to analyze against
            resumes = db.list_user_resumes(user_id)
            resume_text = ""
            if resumes:
                resume_data = db.get_user_resume(user_id, resumes[0]["id"])
                if resume_data:
                    resume_text = resume_data.get("cleanedText") or resume_data.get("rawText") or ""

            # Construct standard AnalyzeRequest payload
            analyze_payload = AnalyzeRequest(
                jd_text=payload.jd_text,
                resume_text=resume_text,
                async_mode=True
            )

            # Queue full RAG analysis and eventually update the job posting's jd_record_id.
            enqueue_job(
                run_async_analysis_job,
                user_id,
                analyze_payload.model_dump(mode="json"),
                task_id,
                job_id,
                job_id=task_id,
            )

        return {
            "jobId": job_id,
            "matchResult": match_result,
            "taskId": task_id,
            "salary_monthly_k": salary_k
        }

    @app.post("/api/resumes/{resume_id}/ats-simulate")
    def ats_simulate_resume(
        resume_id: str,
        payload: ATSSimulateRequest,
        user_id: Any = Depends(current_user_id)
    ) -> dict[str, Any]:
        db = state.service.user_db(user_id)
        # Fetch resume data
        resume_data = db.get_user_resume(user_id, resume_id)
        if not resume_data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到指定简历。")

        resume_text = resume_data.get("cleanedText") or resume_data.get("rawText") or ""

        jd_text = payload.jd_text
        jd_skills = None

        jd_id = payload.jd_id
        if jd_id:
            record = state.service.get_jd_record(user_id, jd_id)
            if record:
                jd_text = jd_text or record.jd_text
                jd_skills = record.analysis.skills

        # Get resume metadata file name
        resumes = db.list_user_resumes(user_id)
        file_name = "resume.pdf"
        for r in resumes:
            if r["id"] == resume_id:
                file_name = r["name"]
                break

        # Run ATS simulator
        result = simulate_ats_compatibility(
            resume_text=resume_text,
            file_name=file_name,
            jd_text=jd_text,
            jd_skills=jd_skills
        )

        return result

    @app.get("/api/analysis/tasks/{task_id}")
    def get_analysis_task_status(task_id: str, user_id: Any = Depends(current_user_id)) -> dict[str, Any]:
        db = state.service.user_db(user_id)
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT task_id, jd_id, status, error_message, created_at, updated_at
            FROM analysis_task
            WHERE task_id = ? AND user_id = ?
            """,
            (task_id, user_id)
        )
        row = cursor.fetchone()
        conn.close()

        if not row:
            raise HTTPException(status_code=404, detail="Task not found")

        task_data = {
            "taskId": row[0],
            "jdId": row[1],
            "status": row[2],
            "errorMessage": row[3],
            "createdAt": row[4],
            "updatedAt": row[5]
        }

        if task_data["status"] == "SUCCESS":
            report = state.service.get_analysis_report(user_id, task_id=task_id)
            record = None
            if task_data["jdId"]:
                record_obj = state.service.get_jd_record(user_id, task_data["jdId"])
                if record_obj:
                    record = record_obj.model_dump(mode="json")

            task_data["report"] = report
            task_data["record"] = record

        return task_data

    @app.post("/api/agent/resume/optimize")
    async def agent_optimize_resume(
        payload: AgentOptimizeResumeRequest,
        user_id: Any = Depends(current_user_id)
    ) -> dict[str, Any]:
        if not payload.legacy_mode:
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="下载型简历任务已退役。请通过 /api/agent/resume/sessions 创建对话式优化会话。",
            )
        request_started_at = time.perf_counter()
        # 1. 鏍￠獙绠€鍘嗘槸鍚﹀瓨鍦?
        resume_data = state.auth_db.get_user_resume(user_id, payload.resume_id)
        if not resume_data:
            raise HTTPException(status_code=404, detail="未找到指定简历。")

        resume_text = resume_data.get("cleanedText") or resume_data.get("rawText") or ""
        if not resume_text.strip():
            raise HTTPException(status_code=400, detail="所选简历内容为空。")

        if not payload.jd_text or not payload.jd_text.strip():
            raise HTTPException(status_code=400, detail="请提供目标岗位 JD。")

        requested_is_co_pilot = payload.is_co_pilot if payload.is_co_pilot is not None else True
        execution_mode = payload.normalized_execution_mode()
        tool_calling_mode = payload.normalized_tool_calling_mode()
        if execution_mode == "agentic" and tool_calling_mode == "auto":
            tool_calling_mode = DEFAULT_AGENT_TOOL_CALLING_MODE
        if execution_mode == "pipeline":
            tool_calling_mode = "auto"
        normalized_jd = normalize_cache_text(payload.jd_text)

        # Reuse matching active/completed Agent tasks for duplicate submissions.
        # This keeps repeated resume/JD/model runs from consuming another model job.
        for candidate in state.auth_db.list_recent_agent_resume_task_candidates(
            user_id,
            resume_id=payload.resume_id,
            limit=40,
        ):
            if normalize_cache_text(candidate.get("jd_text") or "") != normalized_jd:
                continue

            candidate_status = candidate.get("status")
            if candidate_status not in {"PENDING", "RUNNING", "WAITING_FOR_HUMAN", "COMPLETED"}:
                continue

            detail = candidate
            plan_str = detail.get("execution_plan")
            if not plan_str:
                if (
                    candidate_status == "COMPLETED"
                    and detail.get("optimized_resume_md")
                    and not payload.config_id
                    and requested_is_co_pilot is False
                    and execution_mode == "pipeline"
                    and tool_calling_mode == "auto"
                ):
                    detail["logs"] = parse_agent_logs(detail.get("logs"), str(detail.get("trace_id") or detail.get("task_id") or ""))
                    return {
                        "ok": True,
                        "taskId": detail["task_id"],
                        "status": detail["status"],
                        "cacheHit": True,
                        "cacheHitSource": "legacy_completed_result",
                        "message": "已复用相同简历和 JD 的历史完成结果。",
                        "task": serialize_agent_task_summary(detail, include_artifacts=False),
                    }
                continue
            try:
                plan_data = json.loads(plan_str)
            except Exception:
                continue
            same_config = (plan_data.get("config_id") or None) == (payload.config_id or None)
            same_mode = bool(plan_data.get("is_co_pilot", True)) == bool(requested_is_co_pilot)
            plan_execution_options = parse_agent_execution_options(plan_str)
            same_execution_mode = plan_execution_options["executionMode"] == execution_mode
            same_tool_mode = plan_execution_options["toolCallingMode"] == tool_calling_mode
            if same_config and same_mode and same_execution_mode and same_tool_mode:
                detail["logs"] = parse_agent_logs(detail.get("logs"), str(detail.get("trace_id") or detail.get("task_id") or ""))
                return {
                    "ok": True,
                    "taskId": detail["task_id"],
                    "status": detail["status"],
                    "cacheHit": True,
                    "cacheHitSource": "matching_agent_task",
                    "message": "已命中相同简历、JD 和模式的历史任务，直接复用结果。",
                    "task": serialize_agent_task_summary(detail, include_artifacts=False),
                }

        # 2. 鍒涘缓 task_id 鍜岀墿鐞嗛殧绂?workspace_path
        task_id = payload.task_id or f"agent-resume-{uuid4().hex}"
        workspace_path = os.path.join(Config.USER_DB_DIR, "workspaces", f"user_{user_id}", f"task_{task_id}")

        # 3. 鍐欏叆鏁版嵁搴撳垵濮嬬姸鎬?
        state.auth_db.create_agent_resume_task(
            task_id=task_id,
            user_id=user_id,
            resume_id=payload.resume_id,
            original_resume_name=resume_data.get("name") or "resume.pdf",
            jd_text=payload.jd_text,
            workspace_path=workspace_path
        )
        created_task = state.auth_db.get_agent_resume_task(user_id, task_id) or {"task_id": task_id}
        trace_id = str(created_task.get("trace_id") or task_id)
        logs_json = append_agent_log_json(
            "[]",
            build_agent_log(
                "任务已创建：已收到简历和 JD，正在进行本地预热。",
                detail={
                    "executionMode": execution_mode,
                    "toolCallingMode": tool_calling_mode,
                    "isCoPilot": requested_is_co_pilot,
                    "resumeCharacters": len(resume_text),
                    "jdCharacters": len(payload.jd_text.strip()),
                },
                trace_id=trace_id,
                task_id=task_id,
                stage="bootstrap",
                agent="AgentGateway",
                status="running",
                duration_ms=int((time.perf_counter() - request_started_at) * 1000),
            ),
        )
        prewarm_started_at = time.perf_counter()
        prewarm_detail = prewarm_agent_resume_workspace(
            user_id=user_id,
            task_id=task_id,
            resume_text=resume_text,
            jd_text=payload.jd_text,
        )
        prewarm_duration_ms = int((time.perf_counter() - prewarm_started_at) * 1000)
        prewarm_detail["durationMs"] = prewarm_duration_ms
        logs_json = append_agent_log_json(
            logs_json,
            build_agent_log(
                (
                    "本地工作区预热完成：简历、JD 和流式预览已准备好。"
                    if not prewarm_detail["errors"]
                    else "本地工作区预热遇到非阻塞问题，后台会继续补齐。"
                ),
                detail=prewarm_detail,
                trace_id=trace_id,
                task_id=task_id,
                stage="workspace_prewarm",
                agent="AgentGateway",
                status="completed" if not prewarm_detail["errors"] else "warning",
                log_type="info" if not prewarm_detail["errors"] else "warning",
                duration_ms=prewarm_duration_ms,
            ),
        )
        state.auth_db.update_agent_resume_task_status(
            task_id=task_id,
            user_id=user_id,
            status="PENDING",
            logs=logs_json,
            execution_plan=json.dumps({
                "bootstrap_only": True,
                "config_id": payload.config_id,
                "is_co_pilot": requested_is_co_pilot,
                "execution_mode": execution_mode,
                "tool_calling_mode": tool_calling_mode,
                "steps": [],
                "cache_stats": {
                    "hits": 0,
                    "misses": 0,
                    "saved_model_calls": 0,
                    "items": [],
                },
            }, ensure_ascii=False)
        )

        # 4. 鎻愪氦浼佷笟绾ч槦鍒椾换鍔★紝鐢?RQ worker 鎵ц闀胯€楁椂 Agent workflow
        enqueue_started_at = time.perf_counter()
        try:
            enqueue_job(
                run_agent_resume_orchestration_job,
                task_id=task_id,
                user_id=user_id,
                config_id=payload.config_id,
                is_co_pilot=requested_is_co_pilot,
                execution_mode=execution_mode,
                tool_calling_mode=tool_calling_mode,
                job_id=task_id,
            )
            enqueue_duration_ms = int((time.perf_counter() - enqueue_started_at) * 1000)
        except Exception as enqueue_err:
            failed_logs = append_agent_log_json(
                logs_json,
                build_agent_log(
                    f"后台队列提交失败：{enqueue_err}",
                    detail={"error": str(enqueue_err), "queue": Config.RQ_QUEUE_NAME},
                    trace_id=trace_id,
                    task_id=task_id,
                    stage="queue",
                    agent="RQ",
                    status="failed",
                    log_type="error",
                    error_type="QueueEnqueueError",
                ),
            )
            state.auth_db.update_agent_resume_task_status(
                task_id=task_id,
                user_id=user_id,
                status="FAILED",
                error_message=str(enqueue_err),
                logs=failed_logs,
            )
            raise HTTPException(status_code=503, detail=f"后台队列提交失败：{enqueue_err}") from enqueue_err

        queued_logs = append_agent_log_json(
            logs_json,
            build_agent_log(
                "任务已进入后台队列，等待 worker 秒级接手。",
                detail={
                    "queue": Config.RQ_QUEUE_NAME,
                    "jobId": task_id,
                    "enqueueDurationMs": enqueue_duration_ms,
                    "startupElapsedMs": int((time.perf_counter() - request_started_at) * 1000),
                },
                trace_id=trace_id,
                task_id=task_id,
                stage="queue",
                agent="RQ",
                status="queued",
                duration_ms=enqueue_duration_ms,
            ),
        )
        post_enqueue_task = state.auth_db.get_agent_resume_task(user_id, task_id)
        post_enqueue_status = str((post_enqueue_task or {}).get("status") or "")
        if post_enqueue_status and post_enqueue_status != "PENDING":
            return {
                "ok": True,
                "taskId": task_id,
                "status": post_enqueue_status,
                "executionMode": execution_mode,
                "toolCallingMode": tool_calling_mode,
                "task": serialize_agent_task_summary(post_enqueue_task, include_artifacts=False) if post_enqueue_task else None,
            }
        state.auth_db.update_agent_resume_task_status(
            task_id=task_id,
            user_id=user_id,
            status="PENDING",
            logs=queued_logs,
        )
        queued_task = state.auth_db.get_agent_resume_task(user_id, task_id)

        return {
            "ok": True,
            "taskId": task_id,
            "status": "PENDING",
            "executionMode": execution_mode,
            "toolCallingMode": tool_calling_mode,
            "task": serialize_agent_task_summary(queued_task, include_artifacts=False) if queued_task else None,
        }

    @app.get("/api/agent/resume/tasks/{task_id}")
    def get_agent_resume_task_status(
        task_id: str,
        user_id: Any = Depends(current_user_id)
    ) -> dict[str, Any]:
        task = state.auth_db.get_agent_resume_task(user_id, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="鏈壘鍒拌浼樺寲浠诲姟")

        logs_list = parse_agent_logs(task.get("logs"), str(task.get("trace_id") or task_id))

        # 读取 workspace 产物并检测 DOCX
        from backend.agents.tools.workspace_tools import get_safe_workspace_path, tool_read_file
        import os

        diff_content = ""
        artifacts = {"hasDocx": False, "hasPdf": False}
        modification_log = []
        try:
            res = tool_read_file(user_id, task_id, "modification_diff.md")
            if "错误：" not in res:
                diff_content = res
        except:
            pass

        try:
            artifacts = get_agent_resume_artifact_state(user_id, task_id)
        except:
            pass

        try:
            res_log = tool_read_file(user_id, task_id, "modification_log.json")
            if "错误：" not in res_log:
                modification_log = json.loads(res_log)
        except:
            pass

        try:
            conversation_turns = [
                serialize_agent_turn(turn)
                for turn in state.auth_db.list_agent_resume_turns(user_id, task_id)
            ]
        except Exception:
            conversation_turns = []

        execution_plan = task.get("execution_plan") or ""
        execution_options = parse_agent_execution_options(execution_plan)
        cache_stats = serialize_cache_stats(execution_plan)
        provider_cache_stats = serialize_provider_cache_stats(logs_list)
        try:
            conversation_state = state.auth_db.get_agent_resume_conversation_state(user_id, task_id)
        except Exception:
            conversation_state = {}

        return {
            "taskId": task["task_id"],
            "traceId": task.get("trace_id") or "",
            "status": task["status"],
            "resumeId": task["resume_id"],
            "originalResumeName": task["original_resume_name"],
            "jdText": task["jd_text"],
            "logs": logs_list,
            "optimizedResumeMd": task["optimized_resume_md"],
            "streamPreviewMd": read_agent_stream_preview(user_id, task_id),
            "errorMessage": task["error_message"],
            "createdAt": task["created_at"],
            "updatedAt": task["updated_at"],
            "modificationDiffMd": diff_content,
            "hasDocx": artifacts["hasDocx"],
            "hasPdf": artifacts["hasPdf"],
            "modificationLog": modification_log,
            "pendingQuestion": task.get("pending_question") or "",
            "humanAnswer": task.get("human_answer") or "",
            "executionPlan": execution_plan,
            "executionMode": execution_options["executionMode"],
            "toolCallingMode": execution_options["toolCallingMode"],
            "conversationTurns": conversation_turns,
            "conversationState": serialize_agent_conversation_state(conversation_state),
            "localReuseStats": cache_stats,
            "cacheStats": cache_stats,
            "providerCacheStats": provider_cache_stats,
            "stageMetrics": build_agent_stage_metrics(logs_list, cache_stats, str(task.get("trace_id") or task_id)),
        }

    @app.post("/api/agent/resume/tasks/{task_id}/retry")
    async def retry_agent_resume_task(
        task_id: str,
        user_id: Any = Depends(current_user_id)
    ) -> dict[str, Any]:
        task = state.auth_db.get_agent_resume_task(user_id, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="未找到该优化任务")
        if task.get("status") != "FAILED":
            raise HTTPException(status_code=409, detail="只有失败的任务可以从失败点重试")

        resume_id = task.get("resume_id")
        if not resume_id or not state.auth_db.get_user_resume(user_id, resume_id):
            raise HTTPException(status_code=404, detail="未找到该任务关联的简历，无法重试")

        retry_options = recover_agent_retry_execution_options(task.get("execution_plan"))
        config_id = retry_options["config_id"]
        is_co_pilot = retry_options["is_co_pilot"]
        execution_mode = retry_options["execution_mode"]
        tool_calling_mode = retry_options["tool_calling_mode"]
        next_execution_plan, retry_request, retry_count = prepare_agent_retry_execution_plan(task.get("execution_plan"))
        retry_detail = retry_request if retry_request.get("failed_tool_name") else None
        retry_logs = append_agent_resume_log(
            task,
            (
                f"正在从失败点重试：将重放工具 {retry_request['failed_tool_name']} 的同一组参数。"
                if retry_request.get("failed_tool_name")
                else "正在从失败点重试：复用同一份简历、JD、模型配置和未完成步骤继续执行。"
            ),
            detail=retry_detail,
            retry_count=retry_count,
        )
        previous_error = task.get("error_message") or ""

        state.auth_db.update_agent_resume_task_status(
            task_id=task_id,
            user_id=user_id,
            status="RUNNING",
            error_message="",
            logs=retry_logs,
            execution_plan=next_execution_plan,
        )

        try:
            enqueue_job(
                run_agent_resume_orchestration_job,
                task_id=task_id,
                user_id=user_id,
                config_id=config_id,
                is_co_pilot=is_co_pilot,
                execution_mode=execution_mode,
                tool_calling_mode=tool_calling_mode,
                job_id=f"{task_id}:retry:{uuid4().hex}",
            )
        except Exception as enqueue_err:
            state.auth_db.update_agent_resume_task_status(
                task_id=task_id,
                user_id=user_id,
                status="FAILED",
                error_message=previous_error or str(enqueue_err),
                logs=retry_logs,
            )
            raise HTTPException(status_code=503, detail=f"重试任务入队失败：{enqueue_err}") from enqueue_err

        return {
            "ok": True,
            "taskId": task_id,
            "status": "RUNNING",
            "message": "已从失败点重新提交，正在用同一份失败数据继续调用模型。",
        }

    @app.get("/api/agent/resume/tasks/{task_id}/events")
    async def stream_agent_resume_task_events(
        task_id: str,
        request: Request,
        user_id: Any = Depends(current_user_id)
    ):
        if not await asyncio.to_thread(state.auth_db.get_agent_resume_task, user_id, task_id):
            raise HTTPException(status_code=404, detail="未找到该优化任务")

        async def event_stream():
            sent_log_count = 0
            last_snapshot_signature = ""
            last_modification_patch_signature = ""
            retry_available_sent = False
            terminal_statuses = {"COMPLETED", "FAILED", "WAITING_FOR_HUMAN"}
            stream_started_at = time.perf_counter()
            last_heartbeat_at = 0.0

            yield format_sse_event("connected", {
                "taskId": task_id,
                "timestamp": datetime.now().isoformat(),
                "pollIntervalMs": 250,
                "message": "事件流已连接，正在同步任务首包。",
            })

            while True:
                if await request.is_disconnected():
                    break

                # The worker owns persistence.  Keep the ASGI loop free to
                # flush already-available SSE frames while a snapshot is read.
                task = await asyncio.to_thread(
                    state.auth_db.get_agent_resume_task,
                    user_id,
                    task_id,
                )
                if not task:
                    yield format_sse_event("error", {"message": "任务不存在或已被删除。"})
                    break

                trace_id = str(task.get("trace_id") or task_id)
                logs = parse_agent_logs(task.get("logs"), trace_id)
                for log in logs[sent_log_count:]:
                    yield format_sse_event("agent_log", log)
                    detail = log.get("detail") if isinstance(log.get("detail"), dict) else {}
                    if (
                        str(log.get("stage") or "") == "tool_result"
                        and str(detail.get("tool_name") or "") == "replace_resume_section"
                        and detail.get("ok") is True
                    ):
                        patch = await asyncio.to_thread(
                            read_latest_agent_modification_patch,
                            user_id,
                            task_id,
                        )
                        if patch:
                            patch_signature = hashlib.sha1(
                                json.dumps(patch, ensure_ascii=False, sort_keys=True).encode("utf-8")
                            ).hexdigest()
                            if patch_signature != last_modification_patch_signature:
                                last_modification_patch_signature = patch_signature
                                yield format_sse_event("modification_patch", {
                                    "taskId": task_id,
                                    "traceId": trace_id,
                                    "patch": patch,
                                })
                sent_log_count = len(logs)

                task_status = str(task.get("status") or "")
                snapshot_started_at = time.perf_counter()
                snapshot = await asyncio.to_thread(
                    serialize_agent_task_summary,
                    task,
                    parsed_logs=logs,
                    include_artifacts=task_status in terminal_statuses,
                )
                snapshot_build_ms = int((time.perf_counter() - snapshot_started_at) * 1000)
                snapshot["eventStreamMeta"] = {
                    "snapshotBuildMs": snapshot_build_ms,
                    "artifactMode": "full" if task_status in terminal_statuses else "live",
                    "pollIntervalMs": 250 if time.perf_counter() - stream_started_at < 3 else 750,
                }
                stream_preview = str(snapshot.get("streamPreviewMd") or "")
                signature = ":".join([
                    str(snapshot.get("status") or ""),
                    str(snapshot.get("updatedAt") or ""),
                    str(sent_log_count),
                    str(snapshot.get("cacheStats", {}).get("hits") or 0),
                    str(snapshot.get("cacheStats", {}).get("misses") or 0),
                    str(snapshot.get("providerCacheStats", {}).get("cachedTokens") or 0),
                    str(snapshot.get("providerCacheStats", {}).get("checks") or 0),
                    hashlib.sha1(stream_preview.encode("utf-8")).hexdigest() if stream_preview else "",
                ])
                if signature != last_snapshot_signature:
                    last_snapshot_signature = signature
                    yield format_sse_event("snapshot", snapshot)

                if not retry_available_sent:
                    retry_event = serialize_retry_available_event(task, logs)
                    if retry_event is not None:
                        retry_available_sent = True
                        yield format_sse_event("retry_available", retry_event)

                now = time.perf_counter()
                if task_status not in terminal_statuses and now - stream_started_at >= 1.2 and now - last_heartbeat_at >= 2.0:
                    last_heartbeat_at = now
                    elapsed_seconds = round(now - stream_started_at, 1)
                    last_message = str(logs[-1].get("message") if logs else "")
                    heartbeat_stage = "queue_wait" if task_status == "PENDING" else "worker_heartbeat"
                    heartbeat_message = (
                        f"仍在等待后台 worker 接手，已等待 {elapsed_seconds} 秒。"
                        if task_status == "PENDING"
                        else f"后台仍在处理中，最近一步：{last_message or '等待下一条日志'}。"
                    )
                    yield format_sse_event("agent_log", build_agent_log(
                        heartbeat_message,
                        detail={
                            "elapsedSeconds": elapsed_seconds,
                            "lastPersistedLog": last_message,
                            "persistedLogCount": sent_log_count,
                        },
                        trace_id=trace_id,
                        task_id=task_id,
                        stage=heartbeat_stage,
                        agent="SSE",
                        status="waiting" if task_status == "PENDING" else "running",
                    ))

                if task_status in terminal_statuses:
                    yield format_sse_event("done", {
                        "taskId": task_id,
                        "status": task_status,
                        "logCount": sent_log_count,
                    })
                    break

                # A short initial window makes the first tool/thought visible
                # quickly; then back off because worker log writes are eventful,
                # not a 3 Hz state feed.
                await asyncio.sleep(0.25 if now - stream_started_at < 3 else 0.75)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/agent/resume/tasks/{task_id}/answer")
    async def answer_agent_question(
        task_id: str,
        payload: AgentAnswerRequest,
        user_id: Any = Depends(current_user_id)
    ) -> dict[str, Any]:
        answer = payload.normalized_answer()
        if payload.answer_type != "skip" and not answer:
            raise HTTPException(status_code=400, detail="请填写回答内容，或选择无补充。")

        task = state.auth_db.get_agent_resume_task(user_id, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="未找到该优化任务")

        task_status = str(task.get("status") or "")
        # 提取 execution_plan 中保留的模型配置和当前步骤，用于恢复执行或回答追问。
        config_id = None
        plan_data = {}
        plan_str = task.get("execution_plan")
        if plan_str:
            try:
                plan_data = json.loads(plan_str)
                config_id = plan_data.get("config_id")
            except:
                pass
        plan_execution_mode = normalize_agent_execution_mode(
            plan_data.get("execution_mode") or plan_data.get("executionMode")
        ) if isinstance(plan_data, dict) else DEFAULT_AGENT_EXECUTION_MODE
        plan_tool_calling_mode = normalize_agent_tool_calling_mode(
            plan_data.get("tool_calling_mode") or plan_data.get("toolCallingMode")
        ) if isinstance(plan_data, dict) else DEFAULT_AGENT_TOOL_CALLING_MODE

        active_section = ""
        active_step_index = None
        if isinstance(plan_data, dict):
            for step in plan_data.get("steps") or []:
                if isinstance(step, dict) and step.get("status") not in {"COMPLETED", "SKIPPED"}:
                    active_section = str(step.get("section_name") or "")
                    try:
                        active_step_index = int(step.get("step_index"))
                    except (TypeError, ValueError):
                        active_step_index = None
                    break

        if task_status != "WAITING_FOR_HUMAN":
            if task_status in {"PENDING", "RUNNING", "COMPLETED"}:
                try:
                    state.auth_db.add_agent_resume_turn(
                        task_id=task_id,
                        user_id=user_id,
                        step_index=active_step_index,
                        role="user",
                        content=answer,
                        answer_type=payload.answer_type,
                        remember=payload.remember,
                        evidence_scope=payload.evidence_scope,
                    )
                except Exception as turn_err:
                    print(f"[AGENT_TURNS] Failed to save non-blocking user turn: {turn_err}")

                try:
                    current_conversation_state = state.auth_db.get_agent_resume_conversation_state(user_id, task_id)
                    merged_state = merge_agent_conversation_state(
                        current_conversation_state,
                        answer=answer,
                        answer_type=payload.answer_type,
                        evidence_scope=payload.evidence_scope,
                        active_section=active_section,
                    )
                    state.auth_db.upsert_agent_resume_conversation_state(
                        task_id=task_id,
                        user_id=user_id,
                        summary=merged_state["summary"],
                        global_preferences=merged_state["global_preferences"],
                        fact_ledger=merged_state["fact_ledger"],
                    )
                except Exception as state_err:
                    print(f"[AGENT_CONVERSATION] Failed to update non-blocking conversation state: {state_err}")

                if payload.answer_type == "question":
                    explanation = build_agent_question_explanation(
                        task=task,
                        plan_data=plan_data,
                        active_section=active_section,
                        active_step_index=active_step_index,
                        question=answer,
                    )
                    try:
                        state.auth_db.add_agent_resume_turn(
                            task_id=task_id,
                            user_id=user_id,
                            step_index=active_step_index,
                            role="assistant",
                            content=explanation,
                            answer_type="clarification",
                            remember=False,
                            evidence_scope=payload.evidence_scope,
                            summary=explanation[:240],
                        )
                    except Exception as assistant_turn_err:
                        print(f"[AGENT_TURNS] Failed to save non-blocking assistant explanation: {assistant_turn_err}")
                    return {
                        "ok": True,
                        "status": task_status,
                        "message": explanation,
                        "answeredQuestion": True,
                        "recordedOnly": True,
                    }

                return {
                    "ok": True,
                    "status": task_status,
                    "recordedOnly": True,
                    "message": "已保存到本任务对话记录。"
                }
            raise HTTPException(status_code=409, detail="当前任务状态不接受回答。")

        duplicate_answer = False
        if active_step_index is not None:
            try:
                for turn in state.auth_db.list_unconsumed_agent_answer_turns(user_id, task_id, active_step_index):
                    if (
                        str(turn.get("content") or "").strip() == answer
                        and str(turn.get("answer_type") or "evidence") == payload.answer_type
                        and str(turn.get("evidence_scope") or "current_step") == payload.evidence_scope
                    ):
                        duplicate_answer = True
                        break
            except Exception as turn_lookup_err:
                print(f"[AGENT_TURNS] Failed to check duplicate user turn: {turn_lookup_err}")

        try:
            if not duplicate_answer:
                state.auth_db.add_agent_resume_turn(
                    task_id=task_id,
                    user_id=user_id,
                    step_index=active_step_index,
                    role="user",
                    content=answer,
                    answer_type=payload.answer_type,
                    remember=payload.remember,
                    evidence_scope=payload.evidence_scope,
                )
        except Exception as turn_err:
            print(f"[AGENT_TURNS] Failed to save user turn: {turn_err}")

        try:
            current_conversation_state = state.auth_db.get_agent_resume_conversation_state(user_id, task_id)
            merged_state = merge_agent_conversation_state(
                current_conversation_state,
                answer=answer,
                answer_type=payload.answer_type,
                evidence_scope=payload.evidence_scope,
                active_section=active_section,
            )
            state.auth_db.upsert_agent_resume_conversation_state(
                task_id=task_id,
                user_id=user_id,
                summary=merged_state["summary"],
                global_preferences=merged_state["global_preferences"],
                fact_ledger=merged_state["fact_ledger"],
            )
        except Exception as state_err:
            print(f"[AGENT_CONVERSATION] Failed to update conversation state: {state_err}")

        if payload.answer_type == "question":
            explanation = build_agent_question_explanation(
                task=task,
                plan_data=plan_data,
                active_section=active_section,
                active_step_index=active_step_index,
                question=answer,
            )
            try:
                state.auth_db.add_agent_resume_turn(
                    task_id=task_id,
                    user_id=user_id,
                    step_index=active_step_index,
                    role="assistant",
                    content=explanation,
                    answer_type="clarification",
                    remember=False,
                    evidence_scope=payload.evidence_scope,
                    summary=explanation[:240],
                )
            except Exception as assistant_turn_err:
                print(f"[AGENT_TURNS] Failed to save assistant explanation: {assistant_turn_err}")
            return {
                "ok": True,
                "status": "WAITING_FOR_HUMAN",
                "message": explanation,
                "answeredQuestion": True,
            }

        should_save_preference = (
            not duplicate_answer
            and payload.remember
            and payload.answer_type in {"evidence", "preference", "instruction"}
            and answer.strip()
            and "无需补充" not in answer
            and "无补充" not in answer
        )
        if should_save_preference:
            try:
                if active_section:
                    from backend.memory.preference_db import PreferenceDB
                    if payload.answer_type == "preference":
                        prefix = "用户偏好"
                    elif payload.answer_type == "instruction":
                        prefix = "用户指令"
                    else:
                        prefix = "用户补充证据"
                    PreferenceDB(state.auth_db).save_preference(
                        user_id=str(user_id),
                        section_name=active_section,
                        preference_text=f"{prefix}：{answer.strip()}",
                        source_task_id=task_id,
                        evidence_text=answer.strip(),
                        tags=[payload.answer_type, payload.evidence_scope],
                    )
            except Exception as memory_err:
                print(f"[AGENT_MEMORY] Failed to save user preference: {memory_err}")

        # 更新状态为 RUNNING，保存答案，并清除 pending_question。
        state.auth_db.update_agent_resume_task_status(
            task_id=task_id,
            user_id=user_id,
            status="RUNNING",
            pending_question="",
            human_answer=answer
        )

        # 重新提交后台任务启动 LangGraph coordinator，并保留最初的 is_co_pilot 配置。
        is_co_pilot_plan = True
        if plan_str:
            try:
                plan_data = json.loads(plan_str)
                is_co_pilot_plan = plan_data.get("is_co_pilot", True)
            except:
                pass

        try:
            enqueue_job(
                run_agent_resume_orchestration_job,
                task_id=task_id,
                user_id=user_id,
                config_id=config_id,
                is_co_pilot=is_co_pilot_plan,
                execution_mode=plan_execution_mode,
                tool_calling_mode=plan_tool_calling_mode,
                resume_payload={
                    "answer": answer,
                    "answer_type": payload.answer_type,
                    "remember": payload.remember,
                    "evidence_scope": payload.evidence_scope,
                    "step_index": active_step_index,
                },
                job_id=f"{task_id}:resume:{uuid4().hex}",
            )
        except Exception as enqueue_err:
            error_text = str(enqueue_err).lower()
            if "duplicate" in error_text or "already exists" in error_text:
                return {
                    "ok": True,
                    "status": "RUNNING",
                    "duplicateIgnored": True,
                    "message": "回答已收到，后台任务已经在继续执行。",
                }
            state.auth_db.update_agent_resume_task_status(
                task_id=task_id,
                user_id=user_id,
                status="WAITING_FOR_HUMAN",
                pending_question=task.get("pending_question") or "",
                human_answer=answer,
            )
            raise enqueue_err

        return {
            "ok": True,
            "status": "RUNNING",
            "message": "已收到答复，正在重启智能体流水线..."
        }

    @app.get("/api/agent/resume/tasks/{task_id}/download")
    def download_agent_resume(
        task_id: str,
        format: Optional[str] = None,
        user_id: Any = Depends(current_user_id)
    ):
        task = state.auth_db.get_agent_resume_task(user_id, task_id)
        if task and str(task.get("interaction_mode") or "artifact_legacy") != "artifact_legacy":
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="对话式简历会话不生成下载文件，请复制已核验建议后手动修改原简历。",
            )
        if not task or not task.get("optimized_resume_md"):
            raise HTTPException(status_code=404, detail="鏈壘鍒扮畝鍘嗗唴瀹规垨浠诲姟灏氭湭瀹屾垚")

        if format == "docx":
            from backend.agents.tools.workspace_tools import get_safe_workspace_path
            import os
            from fastapi.responses import FileResponse
            from urllib.parse import quote
            try:
                docx_path = get_safe_workspace_path(user_id, task_id, "optimized_resume.docx")
                if not os.path.exists(docx_path):
                    original_docx_path = get_safe_workspace_path(user_id, task_id, "original_resume.docx")
                    if os.path.exists(original_docx_path):
                        from backend.agents.tools.docx_tools import update_docx_resume_from_log
                        update_docx_resume_from_log(user_id, task_id)

                if not os.path.exists(docx_path):
                    raise HTTPException(
                        status_code=409,
                        detail="未找到高保真 DOCX 输出。系统已停止生成会丢失照片和模板元素的兜底 DOCX，请上传 DOCX 原件后重新优化，或下载 Markdown。",
                    )

                filename = optimized_resume_download_filename(task, "docx")
                encoded_filename = quote(filename)
                return FileResponse(
                    path=docx_path,
                    media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    filename=filename,
                    headers={
                        "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"
                    }
                )
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"DOCX 导出出错: {str(e)}")

        if format == "pdf":
            from backend.agents.tools.workspace_tools import get_safe_workspace_path
            from backend.agents.tools.docx_tools import convert_docx_to_pdf
            import os
            from fastapi.responses import FileResponse
            from urllib.parse import quote
            try:
                docx_path = get_safe_workspace_path(user_id, task_id, "optimized_resume.docx")
                workspace_dir = os.path.dirname(docx_path)
                pdf_path = os.path.join(workspace_dir, "optimized_resume.pdf")

                if not os.path.exists(docx_path):
                    original_docx_path = get_safe_workspace_path(user_id, task_id, "original_resume.docx")
                    if os.path.exists(original_docx_path):
                        from backend.agents.tools.docx_tools import update_docx_resume_from_log
                        update_docx_resume_from_log(user_id, task_id)

                if not os.path.exists(docx_path):
                    raise HTTPException(
                        status_code=409,
                        detail="未找到高保真 DOCX 输出，无法在保留照片和模板元素的前提下导出 PDF。请上传 DOCX 原件后重新优化，或下载 Markdown。",
                    )

                success = os.path.exists(pdf_path)
                if not success:
                    success = convert_docx_to_pdf(user_id, task_id, docx_path, workspace_dir)
                if success and os.path.exists(pdf_path):
                    filename = optimized_resume_download_filename(task, "pdf")
                    encoded_filename = quote(filename)
                    return FileResponse(
                        path=pdf_path,
                        media_type="application/pdf",
                        filename=filename,
                        headers={
                            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"
                        }
                    )
                else:
                    raise HTTPException(status_code=500, detail="PDF 杞崲澶辫触锛岃纭绯荤粺瀹夎鏈?LibreOffice")
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"PDF 瀵煎嚭鍑洪敊: {str(e)}")

        from fastapi.responses import Response
        filename = optimized_resume_download_filename(task, "md")
        from urllib.parse import quote
        encoded_filename = quote(filename)

        return Response(
            content=task["optimized_resume_md"],
            media_type="text/markdown",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"
            }
        )

    @app.get("/api/agent/resume/tasks")
    def list_agent_resume_tasks(
        user_id: Any = Depends(current_user_id)
    ) -> dict[str, Any]:
        tasks = state.auth_db.list_user_agent_resume_tasks(user_id)
        return {"tasks": [serialize_agent_task_summary(task) for task in tasks]}

    @app.delete("/api/agent/resume/tasks/{task_id}")
    def delete_agent_resume_task(
        task_id: str,
        user_id: Any = Depends(current_user_id)
    ) -> dict[str, Any]:
        # 1. 灏濊瘯鍒犻櫎
        success = state.auth_db.delete_agent_resume_task(user_id, task_id)
        if not success:
            raise HTTPException(status_code=404, detail="浠诲姟涓嶅瓨鍦ㄦ垨鏃犳潈鍒犻櫎")

        # 2. 娓呯悊 workspace 鐗╃悊鏂囦欢
        try:
            workspace_dir = os.path.abspath(
                os.path.join(Config.USER_DB_DIR, "workspaces", f"user_{user_id}", f"task_{task_id}")
            )
            import shutil
            if os.path.exists(workspace_dir):
                shutil.rmtree(workspace_dir)
        except Exception as e:
            print(f"[CLEANUP_WARN] Failed to delete workspace dir for task {task_id}: {e}")

        return {"ok": True}

    @app.post("/api/agent/resume/tasks/{task_id}/save")
    def save_agent_resume_edit(
        task_id: str,
        payload: SaveAgentResumeEditRequest,
        user_id: Any = Depends(current_user_id)
    ) -> dict[str, Any]:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="在线回写简历已退役。历史产物仅支持只读下载；请在对话式简历顾问中复制建议后手动修改原文件。",
        )

        task = state.auth_db.get_agent_resume_task(user_id, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="未找到对应的简历优化任务。")
        if str(task.get("interaction_mode") or "artifact_legacy") != "artifact_legacy":
            raise HTTPException(status_code=410, detail="对话式简历会话不支持原地回写文件，请复制建议后手动修改原简历。")

        from backend.agents.tools.workspace_tools import get_safe_workspace_path, tool_read_file, tool_write_file
        from backend.agents.tools.docx_tools import convert_docx_to_pdf, update_docx_resume_from_log
        import json
        import os

        sections_json = tool_read_file(user_id, task_id, "resume_sections.json")
        if "错误：" in sections_json:
            raise HTTPException(status_code=400, detail="未在工作区找到 resume_sections.json，请确认任务是否已完成。")

        try:
            sections = json.loads(sections_json)
        except Exception:
            raise HTTPException(status_code=500, detail="解析 resume_sections.json 失败。")

        idx = payload.section_index
        if idx < 0 or idx >= len(sections):
            raise HTTPException(status_code=400, detail=f"无效的段落索引: {idx}")

        old_text = sections[idx].get("content", "")
        sections[idx]["content"] = payload.new_text
        tool_write_file(user_id, task_id, "resume_sections.json", json.dumps(sections, ensure_ascii=False))

        log_json = tool_read_file(user_id, task_id, "modification_log.json")
        mod_logs = []
        if "错误：" not in log_json:
            try:
                mod_logs = json.loads(log_json)
            except Exception:
                pass

        log_item = next((item for item in mod_logs if item.get("section_index") == idx), None)
        if log_item:
            log_item["new"] = payload.new_text
            log_item["timestamp"] = datetime.now().isoformat()
        else:
            section_name = sections[idx].get("section_name", f"妯″潡 {idx}")
            mod_logs.append({
                "section_name": section_name,
                "section_index": idx,
                "original": old_text,
                "new": payload.new_text,
                "timestamp": datetime.now().isoformat(),
                "reason": "鐢ㄦ埛鍦ㄧ嚎瀹炴椂缂栬緫淇敼"
            })

        tool_write_file(user_id, task_id, "modification_log.json", json.dumps(mod_logs, ensure_ascii=False))

        assembled_content = "\n".join(sec.get("content", "") for sec in sections)
        tool_write_file(user_id, task_id, "assembled_resume.txt", assembled_content)

        md_content = tool_read_file(user_id, task_id, "optimized_resume.md")
        if "错误：" in md_content:
            md_content = assembled_content
        else:
            if old_text.strip() and old_text.strip() in md_content:
                md_content = md_content.replace(old_text.strip(), payload.new_text.strip())
            else:
                pass
        tool_write_file(user_id, task_id, "optimized_resume.md", md_content)

        state.auth_db.update_agent_resume_task_status(
            task_id=task_id,
            user_id=user_id,
            status="COMPLETED",
            optimized_resume_md=md_content
        )

        record = state.auth_db.get_analysis_record(user_id, task_id)
        if record:
            record["optimized_resume_md"] = md_content
            record["modification_log"] = mod_logs
            docx_path = get_safe_workspace_path(user_id, task_id, "optimized_resume.docx")
            pdf_path = get_safe_workspace_path(user_id, task_id, "optimized_resume.pdf")
            record["has_docx"] = os.path.exists(docx_path)
            record["has_pdf"] = os.path.exists(pdf_path)

            state.auth_db.save_analysis_record(
                user_id=user_id,
                status=record.get("status", "watching"),
                result_json=record,
                input_json=record.get("draft"),
                record_id=task_id
            )

        try:
            docx_updated = update_docx_resume_from_log(user_id, task_id)
            docx_path = get_safe_workspace_path(user_id, task_id, "optimized_resume.docx")
            workspace_dir = os.path.dirname(docx_path)
            pdf_path = os.path.join(workspace_dir, "optimized_resume.pdf")
            if os.path.exists(pdf_path):
                os.remove(pdf_path)
            if docx_updated and os.path.exists(docx_path):
                convert_docx_to_pdf(user_id, task_id, docx_path, workspace_dir)
        except Exception as e:
            print(f"[EDIT_SAVE] Failed to update docx/pdf: {e}")

        return {
            "ok": True,
            "message": "淇敼宸叉垚鍔熶繚瀛樺苟鍚屾鍒伴珮淇濈湡绠€鍘嗕腑"
        }

    # 鈹€鈹€ Drafts CRUD 鈹€鈹€

    @app.get("/api/drafts")
    def list_drafts(user_id: Any = Depends(current_user_id)) -> dict[str, Any]:
        drafts = state.auth_db.list_drafts(user_id)
        return {"drafts": drafts}

    @app.post("/api/drafts")
    def save_draft(payload: dict[str, Any], user_id: Any = Depends(current_user_id)) -> dict[str, Any]:
        input_json = payload.get("input_json", payload)
        draft_status = payload.get("status", "DRAFT")
        failed_step = payload.get("failed_step")
        error_message = payload.get("error_message")
        draft_id = payload.get("id") or payload.get("draft_id")
        new_id = state.auth_db.save_draft(
            user_id=user_id,
            input_json=input_json,
            status=draft_status,
            failed_step=failed_step,
            error_message=error_message,
            draft_id=draft_id,
        )
        return {"id": new_id, "ok": True}

    @app.get("/api/drafts/{draft_id}")
    def get_draft(draft_id: str, user_id: Any = Depends(current_user_id)) -> dict[str, Any]:
        draft = state.auth_db.get_draft(user_id, draft_id)
        if draft is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="记录不存在或无权访问。")
        return {"draft": draft}

    @app.delete("/api/drafts/{draft_id}")
    def delete_draft(draft_id: str, user_id: Any = Depends(current_user_id)) -> dict[str, bool]:
        state.auth_db.delete_draft(user_id, draft_id)
        return {"deleted": True}

    @app.post("/api/drafts/clear-converted")
    def clear_converted_drafts(user_id: Any = Depends(current_user_id)) -> dict[str, bool]:
        state.auth_db.clear_converted_drafts(user_id)
        return {"ok": True}

    # 鈹€鈹€ User Settings 鈹€鈹€

    @app.get("/api/settings")
    def get_settings(user_id: Any = Depends(current_user_id)) -> dict[str, Any]:
        settings = state.auth_db.get_settings(user_id)
        return {"settings": settings}

    @app.post("/api/settings")
    def save_settings(payload: dict[str, Any], user_id: Any = Depends(current_user_id)) -> dict[str, bool]:
        state.auth_db.save_settings(user_id, payload)
        return {"ok": True}

    # 鈹€鈹€ Model Configs CRUD 鈹€鈹€

    @app.get("/api/configs")
    def list_configs(user_id: Any = Depends(current_user_id)) -> dict[str, Any]:
        configs = state.auth_db.list_user_available_configs(user_id)
        return {"configs": configs}

    @app.post("/api/configs")
    def save_config(payload: dict[str, Any], user_id: Any = Depends(current_user_id)) -> dict[str, Any]:
        provider = payload.get("provider", "")
        model_id = payload.get("modelId") or payload.get("model_id", "")
        display_name = payload.get("name") or payload.get("display_name")
        api_key = payload.get("apiKey") or payload.get("api_key", "")
        enabled = payload.get("enabled", True)
        config_id = payload.get("id")

        # Intercept if updating a config owned by admin/system, or owned by another user (IDOR prevention)
        if config_id:
            conn = state.auth_db.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, owner_type FROM model_configs WHERE id = ?", (config_id,))
            row = cursor.fetchone()
            conn.close()
            if row:
                config_user_id, owner_type = row
                if owner_type in ("admin", "system"):
                    user = state.auth_db.get_user_by_id(user_id)
                    if not user or user.role != "admin":
                        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权修改管理员托管的配置。")
                elif config_user_id is not None and str(config_user_id) != str(user_id):
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权修改其他用户的配置。")

        # Store full config object (minus sensitive apiKey) as config_json
        safe_payload = {k: v for k, v in payload.items() if k not in ("apiKey", "api_key")}
        new_id = state.auth_db.save_model_config(
            user_id=user_id,
            provider=provider,
            model_id=model_id,
            display_name=display_name,
            api_key=api_key,
            enabled=enabled,
            config_json=safe_payload,
            config_id=config_id,
        )
        return {"id": new_id, "ok": True}

    @app.delete("/api/configs/{config_id}")
    def delete_config(config_id: str, user_id: Any = Depends(current_user_id)) -> dict[str, bool]:
        # Intercept if deleting a config owned by admin/system
        conn = state.auth_db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT owner_type FROM model_configs WHERE id = ?", (config_id,))
        row = cursor.fetchone()
        conn.close()
        if row and row[0] in ("admin", "system"):
            user = state.auth_db.get_user_by_id(user_id)
            if not user or user.role != "admin":
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权删除管理员托管的配置。")

        state.auth_db.delete_model_config(user_id, config_id)
        return {"deleted": True}

    # 鈹€鈹€ Admin Console API Endpoints 鈹€鈹€

    @app.get("/api/admin/users")
    def admin_list_users(admin_id: Any = Depends(current_admin_user)) -> dict[str, Any]:
        users = state.auth_db.admin_list_users()
        return {"users": users}

    @app.get("/api/admin/locked-users")
    def admin_get_locked_users(
        admin_id: Any = Depends(current_admin_user)
    ) -> dict[str, Any]:
        locked_users = []
        now = time.time()
        for key, ts_list in list(limiter.requests.items()):
            if key.startswith("login_fail_user:"):
                username = key.split(":", 1)[1]
                active_ts = [t for t in ts_list if t > now - 900]
                if len(active_ts) >= 5:
                    oldest_active = min(active_ts)
                    remaining = int(900 - (now - oldest_active))
                    locked_users.append({
                        "username": username,
                        "failed_count": len(active_ts),
                        "remaining_seconds": max(0, remaining)
                    })
        return {"locked_users": locked_users}

    @app.post("/api/admin/locked-users/unlock")
    def admin_unlock_user(
        payload: dict[str, str],
        admin_id: Any = Depends(current_admin_user)
    ) -> dict[str, Any]:
        username = payload.get("username", "")
        if not username:
            raise HTTPException(status_code=400, detail="未提供要解锁的用户名或邮箱。")
        norm_username = normalize_username(username)
        key = f"login_fail_user:{norm_username}"
        limiter.requests.pop(key, None)
        return {"ok": True}

    @app.post("/api/admin/users/generate-temp")
    async def admin_generate_temp_users(
        payload: GenerateTempUsersRequest,
        admin_id: Any = Depends(current_admin_user)
    ) -> dict[str, Any]:
        if payload.quantity < 1 or payload.quantity > 50:
            raise HTTPException(status_code=400, detail="生成数量必须在 1 到 50 之间。")
        if payload.duration_hours <= 0 or payload.duration_hours > 876000:
            raise HTTPException(status_code=400, detail="有效时间必须大于 0 且不能超过 100 年。")


        import string
        import secrets
        def generate_password(length=12):
            alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
            while True:
                password = ''.join(secrets.choice(alphabet) for _ in range(length))
                if (any(c.islower() for c in password)
                        and any(c.isupper() for c in password)
                        and any(c.isdigit() for c in password)
                        and any(c in "!@#$%^&*" for c in password)):
                    return password

        expires_at = datetime.now() + timedelta(hours=payload.duration_hours)
        expires_at_str = expires_at.isoformat()

        generated = []
        for _ in range(payload.quantity):
            username = f"temp_{uuid4().hex[:6]}@internpath.temp"
            password = generate_password()
            password_hash = await asyncio.to_thread(hash_password, password)
            await asyncio.to_thread(state.auth_db.admin_create_temp_user, username, password_hash, expires_at_str)
            generated.append({
                "username": username,
                "password": password,
                "expires_at": expires_at_str
            })

        state.auth_db.log_admin_audit(
            admin_user_id=admin_id,
            action="GENERATE_TEMP_USERS",
            metadata_json={"quantity": payload.quantity, "duration_hours": payload.duration_hours}
        )
        return {"ok": True, "generated_accounts": generated}


    @app.patch("/api/admin/users/{user_id}/status")
    def admin_update_user_status(
        user_id: str,
        payload: UpdateUserStatusRequest,
        admin_id: Any = Depends(current_admin_user)
    ) -> dict[str, Any]:
        if str(user_id) == str(admin_id):
            raise HTTPException(status_code=400, detail="不能禁用/修改自己的账号状态。")

        user = state.auth_db.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在。")

        state.auth_db.admin_update_user_status(user_id, payload.is_active)
        if not payload.is_active:
            state.auth_db.delete_user_sessions(user_id)

        state.auth_db.log_admin_audit(
            admin_user_id=admin_id,
            action="UPDATE_USER_STATUS",
            target_user_id=user_id,
            metadata_json={"is_active": payload.is_active}
        )
        return {"ok": True}

    @app.patch("/api/admin/users/{user_id}/expiry")
    def admin_update_user_expiry(
        user_id: str,
        payload: UpdateUserExpiryRequest,
        admin_id: Any = Depends(current_admin_user)
    ) -> dict[str, Any]:
        if str(user_id) == str(admin_id):
            raise HTTPException(status_code=400, detail="不能修改自己的账户过期时间。")

        user = state.auth_db.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在。")

        # Parse expires_at if set, otherwise None
        expires_at_str = None
        if payload.expires_at:
            try:
                dt_str = payload.expires_at.replace("Z", "+00:00")
                parsed = datetime.fromisoformat(dt_str)
                expires_at_str = parsed.isoformat()

                # Proactive session revocation if expiry is in the past
                if parsed.replace(tzinfo=None) <= datetime.now():
                    state.auth_db.admin_update_user_status(user_id, False)
                    state.auth_db.delete_user_sessions(user_id)
            except ValueError:
                raise HTTPException(status_code=400, detail="到期时间格式无效，必须为 ISO 8601 格式。")

        state.auth_db.admin_update_user_expiry(user_id, expires_at_str)
        state.auth_db.log_admin_audit(
            admin_user_id=admin_id,
            action="UPDATE_USER_EXPIRY",
            target_user_id=user_id,
            metadata_json={"expires_at": expires_at_str}
        )
        return {"ok": True}

    @app.patch("/api/admin/users/{user_id}/generation-limit")
    def admin_update_user_generation_limit(
        user_id: str,
        payload: UpdateUserGenerationLimitRequest,
        admin_id: Any = Depends(current_admin_user)
    ) -> dict[str, Any]:
        if str(user_id) == str(admin_id):
            raise HTTPException(status_code=400, detail="管理员不能修改自己的生成次数。")

        user = state.auth_db.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在。")

        state.auth_db.admin_update_user_generation_limit(user_id, payload.generation_limit)
        state.auth_db.log_admin_audit(
            admin_user_id=admin_id,
            action="UPDATE_USER_GENERATION_LIMIT",
            target_user_id=user_id,
            metadata_json={"generation_limit": payload.generation_limit}
        )
        return {"ok": True}


    @app.patch("/api/admin/users/{user_id}/username")
    def admin_update_username(
        user_id: str,
        payload: UpdateUsernameRequest,
        admin_id: Any = Depends(current_admin_user)
    ) -> dict[str, Any]:
        if str(user_id) == str(admin_id):
            raise HTTPException(status_code=400, detail="管理员不能修改自己的用户名。")

        try:
            target_id = int(user_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="无效的用户 ID。")

        user = state.auth_db.get_user_by_id(target_id)
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在。")

        new_username = payload.username.strip()
        if not new_username:
            raise HTTPException(status_code=400, detail="用户名不能为空。")

        try:
            state.auth_db.admin_update_username(target_id, new_username)
        except ValueError as exc:
            if str(exc) == "username_taken":
                raise HTTPException(status_code=400, detail="该用户名已被占用。")
            raise HTTPException(status_code=400, detail=str(exc))

        state.auth_db.log_admin_audit(
            admin_user_id=admin_id,
            action="UPDATE_USERNAME",
            target_user_id=user_id,
            metadata_json={"new_username": new_username}
        )
        return {"ok": True}


    @app.patch("/api/admin/users/{user_id}/remark")
    def admin_update_user_remark(
        user_id: str,
        payload: UpdateUserRemarkRequest,
        admin_id: Any = Depends(current_admin_user)
    ) -> dict[str, Any]:
        try:
            target_id = int(user_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="无效的用户 ID。")

        user = state.auth_db.get_user_by_id(target_id)
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在。")

        remark = payload.remark.strip()
        state.auth_db.admin_update_remark(target_id, remark)
        state.auth_db.log_admin_audit(
            admin_user_id=admin_id,
            action="UPDATE_USER_REMARK",
            target_user_id=user_id,
            metadata_json={"remark": remark}
        )
        return {"ok": True}


    @app.delete("/api/admin/users/expired")
    def admin_delete_expired_users(
        admin_id: Any = Depends(current_admin_user)
    ) -> dict[str, Any]:
        users = state.auth_db.admin_list_users()
        now = datetime.now()
        deleted_count = 0
        for u in users:
            if str(u["id"]) == str(admin_id):
                continue
            if u.get("expires_at"):
                try:
                    exp_dt = datetime.fromisoformat(u["expires_at"].replace("Z", "+00:00")).replace(tzinfo=None)
                    if exp_dt <= now:
                        state.auth_db.delete_user(int(u["id"]))
                        state.auth_db.delete_user_sessions(u["id"])
                        deleted_count += 1
                except Exception as e:
                    print(f"Error parsing expiry for user {u['id']}: {e}")

        state.auth_db.log_admin_audit(
            admin_user_id=admin_id,
            action="DELETE_EXPIRED_USERS",
            metadata_json={"deleted_count": deleted_count}
        )
        return {"ok": True, "deleted_count": deleted_count}


    @app.delete("/api/admin/users/{user_id}")
    def admin_delete_user(
        user_id: str,
        admin_id: Any = Depends(current_admin_user)
    ) -> dict[str, Any]:
        if str(user_id) == str(admin_id):
            raise HTTPException(status_code=400, detail="管理员不能删除自己的账号。")

        try:
            target_id = int(user_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="无效的用户 ID。")

        user = state.auth_db.get_user_by_id(target_id)
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在。")

        state.auth_db.delete_user(target_id)
        state.auth_db.delete_user_sessions(target_id)
        state.auth_db.log_admin_audit(
            admin_user_id=admin_id,
            action="DELETE_USER",
            target_user_id=user_id
        )
        return {"ok": True}


    @app.get("/api/admin/model-configs")
    def admin_list_model_configs(admin_id: Any = Depends(current_admin_user)) -> dict[str, Any]:
        configs = state.auth_db.admin_list_model_configs()
        return {"configs": configs}

    @app.post("/api/admin/model-configs")
    def admin_create_model_config(
        payload: AdminModelConfigRequest,
        admin_id: Any = Depends(current_admin_user)
    ) -> dict[str, Any]:
        safe_payload = payload.config_json or {}
        new_id = state.auth_db.admin_create_model_config(
            admin_user_id=admin_id,
            provider=payload.provider,
            model_id=payload.modelId,
            display_name=payload.name,
            api_key=payload.apiKey,
            enabled=payload.enabled,
            config_json=safe_payload
        )
        state.auth_db.log_admin_audit(
            admin_user_id=admin_id,
            action="CREATE_CONFIG",
            target_resource_type="model_config",
            target_resource_id=new_id,
            metadata_json={"provider": payload.provider, "modelId": payload.modelId, "name": payload.name}
        )
        return {"id": new_id, "ok": True}

    @app.patch("/api/admin/model-configs/{config_id}")
    def admin_update_model_config(
        config_id: str,
        payload: AdminModelConfigRequest,
        admin_id: Any = Depends(current_admin_user)
    ) -> dict[str, Any]:
        safe_payload = payload.config_json or {}
        success = state.auth_db.admin_update_model_config(
            config_id=config_id,
            provider=payload.provider,
            model_id=payload.modelId,
            display_name=payload.name,
            api_key=payload.apiKey,
            enabled=payload.enabled,
            config_json=safe_payload
        )
        if not success:
            raise HTTPException(status_code=404, detail="未找到该管理员配置，或该配置不属于管理员管理。")
        state.auth_db.log_admin_audit(
            admin_user_id=admin_id,
            action="UPDATE_CONFIG",
            target_resource_type="model_config",
            target_resource_id=config_id,
            metadata_json={"provider": payload.provider, "modelId": payload.modelId, "name": payload.name}
        )
        return {"ok": True}

    @app.post("/api/admin/model-configs/{config_id}/assign")
    def admin_assign_model_config(
        config_id: str,
        payload: AdminAssignRequest,
        admin_id: Any = Depends(current_admin_user)
    ) -> dict[str, Any]:
        try:
            state.auth_db.admin_assign_model_config(
                admin_user_id=admin_id,
                config_id=config_id,
                target_user_ids=payload.userIds
            )
            state.auth_db.log_admin_audit(
                admin_user_id=admin_id,
                action="ASSIGN_CONFIG",
                target_resource_type="model_config",
                target_resource_id=config_id,
                metadata_json={"assigned_users": payload.userIds}
            )
            return {"ok": True}
        except ValueError as e:
            if str(e) == "not_admin_managed_config":
                raise HTTPException(status_code=400, detail="该配置不是管理员拥有的配置，无法分配。")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/admin/model-configs/{config_id}/revoke")
    def admin_revoke_model_config(
        config_id: str,
        payload: AdminAssignRequest,
        admin_id: Any = Depends(current_admin_user)
    ) -> dict[str, Any]:
        state.auth_db.admin_revoke_model_config(
            config_id=config_id,
            target_user_ids=payload.userIds
        )
        state.auth_db.log_admin_audit(
            admin_user_id=admin_id,
            action="REVOKE_CONFIG",
            target_resource_type="model_config",
            target_resource_id=config_id,
            metadata_json={"revoked_users": payload.userIds}
        )
        return {"ok": True}

    @app.get("/api/admin/model-configs/{config_id}/assignments")
    def admin_get_assignments(
        config_id: str,
        admin_id: Any = Depends(current_admin_user)
    ) -> dict[str, Any]:
        assignments = state.auth_db.admin_get_assignments(config_id)
        return {"assignments": assignments}

    @app.get("/api/admin/model-usage/summary")
    def admin_get_usage_summary(
        startDate: Optional[str] = None,
        endDate: Optional[str] = None,
        provider: Optional[str] = None,
        modelId: Optional[str] = None,
        userId: Optional[str] = None,
        admin_id: Any = Depends(current_admin_user)
    ) -> dict[str, Any]:
        summary = state.auth_db.admin_get_usage_summary(
            start_date=startDate,
            end_date=endDate,
            provider=provider,
            model_id=modelId,
            user_id=userId
        )
        return {"summary": summary}

    @app.get("/api/admin/model-usage/logs")
    def admin_get_usage_logs(
        startDate: Optional[str] = None,
        endDate: Optional[str] = None,
        provider: Optional[str] = None,
        modelId: Optional[str] = None,
        userId: Optional[str] = None,
        success: Optional[bool] = None,
        page: int = 1,
        pageSize: int = 20,
        admin_id: Any = Depends(current_admin_user)
    ) -> dict[str, Any]:
        result = state.auth_db.admin_get_usage_logs(
            start_date=startDate,
            end_date=endDate,
            provider=provider,
            model_id=modelId,
            user_id=userId,
            success=success,
            page=page,
            page_size=pageSize
        )
        return result

    @app.get("/api/admin/announcements")
    def admin_list_announcements(
        admin_id: Any = Depends(current_admin_user)
    ) -> dict[str, Any]:
        announcements = state.auth_db.get_announcements()
        return {"announcements": announcements}

    @app.post("/api/admin/announcements")
    def admin_create_announcement(
        payload: AdminAnnouncementRequest,
        admin_id: Any = Depends(current_admin_user)
    ) -> dict[str, Any]:
        try:
            datetime.fromisoformat(payload.start_time.replace("Z", "+00:00"))
            datetime.fromisoformat(payload.end_time.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="起止时间格式无效，必须为 ISO 8601 格式。")

        ann_id = state.auth_db.create_announcement(
            title=payload.title,
            content=payload.content,
            start_time=payload.start_time,
            end_time=payload.end_time,
            target_type=payload.target_type,
            target_users=payload.target_users,
            announcement_type=payload.announcement_type,
            show_behavior=payload.show_behavior
        )
        return {"id": ann_id, "ok": True}

    @app.put("/api/admin/announcements/{ann_id}")
    def admin_update_announcement(
        ann_id: str,
        payload: AdminAnnouncementRequest,
        admin_id: Any = Depends(current_admin_user)
    ) -> dict[str, Any]:
        try:
            datetime.fromisoformat(payload.start_time.replace("Z", "+00:00"))
            datetime.fromisoformat(payload.end_time.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="起止时间格式无效，必须为 ISO 8601 格式。")

        success = state.auth_db.update_announcement(
            id=ann_id,
            title=payload.title,
            content=payload.content,
            start_time=payload.start_time,
            end_time=payload.end_time,
            target_type=payload.target_type,
            target_users=payload.target_users,
            announcement_type=payload.announcement_type,
            show_behavior=payload.show_behavior
        )
        return {"ok": success}

    @app.delete("/api/admin/announcements/{ann_id}")
    def admin_delete_announcement(
        ann_id: str,
        admin_id: Any = Depends(current_admin_user)
    ) -> dict[str, Any]:
        success = state.auth_db.delete_announcement(ann_id)
        return {"ok": success}

    @app.get("/api/announcements/active")
    def get_active_announcements(
        user_id: Any = Depends(current_user_id)
    ) -> dict[str, Any]:
        user = state.auth_db.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在。")
        active = state.auth_db.get_active_announcements_for_user(user.username)
        return {"announcements": active}

    return app


app = create_app()

frontend_dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
