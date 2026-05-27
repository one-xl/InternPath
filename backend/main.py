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
from typing import Any, Optional
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile, status, Cookie, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from database import Database
from document_parser import DocumentParseError
from models import JobAnalysis, StarStory
from backend.doubao_job_rag import DoubaoAnalysisError, analyze_job_with_doubao, PLACEHOLDER_KEYS
from backend.resume_rag import parse_resume, retrieve_chunks
from service import CareerPathAIService
from config import Config
from auth import hash_password
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
    expert_options: dict[str, bool] = Field(default_factory=dict)
    draft_id: Optional[str] = None


class RenameRecordRequest(BaseModel):
    display_name: str = ""


class StarStorySegmentRequest(BaseModel):
    segment_type: str = Field(..., min_length=1)
    input_text: str = Field("", max_length=4000)
    jd_text: Optional[str] = Field(None, max_length=4000)
    resume_text: Optional[str] = Field(None, max_length=4000)
    current_star: Optional[dict[str, str]] = None
    config_id: Optional[str] = Field(None, max_length=100)


class StarStoryPolishRequest(BaseModel):
    situation: str = Field("", max_length=4000)
    task: str = Field("", max_length=4000)
    action: str = Field("", max_length=4000)
    result: str = Field("", max_length=4000)
    style: str = Field("standard", max_length=50)
    jd_text: Optional[str] = Field(None, max_length=4000)
    config_id: Optional[str] = Field(None, max_length=100)


class StarSmartRewriteRequest(BaseModel):
    original_text: str = Field(..., min_length=10, max_length=8000)
    style: str = Field("standard", max_length=50)
    jd_text: Optional[str] = Field(None, max_length=4000)
    config_id: Optional[str] = Field(None, max_length=100)


class StarStoryCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
    situation: str = Field("", max_length=4000)
    task: str = Field("", max_length=4000)
    action: str = Field("", max_length=4000)
    result: str = Field("", max_length=4000)
    full_text: str = Field("", max_length=16000)
    style: str = Field("standard", max_length=50)


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



class ModelProxyRequest(BaseModel):
    provider: str
    modelId: str
    requestBody: dict[str, Any]
    endpoint: Optional[str] = None
    configId: Optional[str] = None


class TestConnectionRequest(BaseModel):
    provider: str
    modelId: str
    endpoint: Optional[str] = None
    type: Optional[str] = None
    configId: Optional[str] = None


class AdminModelConfigRequest(BaseModel):
    provider: str
    modelId: str
    name: str
    apiKey: str
    enabled: bool = True
    config_json: Optional[dict[str, Any]] = None


class AdminAssignRequest(BaseModel):
    userIds: list[Any]


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
        (user_id, provider, model_id, 1 if not db.is_postgres else True)
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
            (user_id, provider, model_id, 1 if not db.is_postgres else True, 1 if not db.is_postgres else True)
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


def create_app(
    *,
    service: Optional[CareerPathAIService] = None,
    auth_db: Optional[Database] = None,
) -> FastAPI:
    app = FastAPI(title="InternPath Personal Workbench API")

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
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    state = AppState(
        service=service or CareerPathAIService(),
        auth_db=auth_db or Database(),
    )
    # Trigger automatic data migration of old databases into the consolidated shared database
    state.auth_db.backfill_user_databases()
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
                detail="请求过于频繁，请稍后再试。"
            )

    def issue_token(user_id: Any) -> str:
        token = uuid4().hex
        from datetime import timedelta
        expires_at = datetime.now() + timedelta(seconds=SESSION_MAX_AGE_SECONDS)
        state.auth_db.create_session(token, user_id, expires_at)
        return token

    def current_user_id(
        session_id: Optional[str] = Cookie(default=None),
        authorization: str = Header(default="")
    ) -> Any:
        # Bearer token takes priority over cookie
        token = None
        if authorization:
            scheme, _, bearer_token = authorization.partition(" ")
            if scheme.lower() == "bearer" and bearer_token:
                token = bearer_token
        if not token:
            token = session_id
        
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
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="该测试账号已过期停用，请联系管理员。")
            
            if not user.is_active:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="该账号已被停用，请联系管理员。")
                
        return user_id



    def current_admin_user(
        user_id: Any = Depends(current_user_id)
    ) -> Any:
        user = state.auth_db.get_user_by_id(user_id)
        if user is None or user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="权限不足，只有管理员可以执行此操作。"
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
            if not db_url and state.auth_db.is_postgres:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="数据库配置缺失，请检查服务器环境变量。"
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="数据库连接失败，请检查 PostgreSQL 服务是否已启动。"
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
        try:
            parsed_resume = parse_resume(file.filename or "resume", file.content_type or "", content)
        except DocumentParseError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        state.resume_store[parsed_resume["file"]["id"]] = {
            "parsed_resume": parsed_resume,
            "user_id": user_id,
        }
        return {
            "resumeFile": parsed_resume["file"],
            "parsedResume": parsed_resume,
        }

    @app.post("/api/resumes/retrieve")
    def retrieve_resume(
        payload: ResumeRetrieveRequest,
        user_id: Any = Depends(current_user_id)
    ) -> dict[str, Any]:
        entry = state.resume_store.get(payload.resumeFileId)
        if entry is None or entry.get("user_id") != user_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="记录不存在或无权访问。")
        parsed_resume = entry.get("parsed_resume")
        try:
            return retrieve_chunks(payload.jdText, parsed_resume.get("chunks", []), payload.topK)
        except DocumentParseError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/api/analysis/job-rag")
    def analyze_job_rag(
        payload: JobRagAnalyzeRequest,
        user_id: Any = Depends(current_user_id)
    ) -> dict[str, Any]:
        if len(payload.jdText) > 5000:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="输入内容过长，请减少无关内容后再分析。")
            
        entry = state.resume_store.get(payload.resumeFileId) if payload.resumeFileId else None
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
        key_ip = f"login_fail_ip:{request.client.host}"
        key_user = f"login_fail_user:{payload.username}"
        
        if len([t for t in limiter.requests[key_ip] if t > time.time() - 900]) >= 5 or \
           len([t for t in limiter.requests[key_user] if t > time.time() - 900]) >= 5:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="请求过于频繁，请稍后再试。")
            
        user = state.auth_db.authenticate_user(payload.username, payload.password)
        if user is None or user.id is None:
            limiter.requests[key_ip].append(time.time())
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
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="该测试账号已过期停用，请联系管理员。")
            
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
                    detail="您的账号生成额度已用尽，请联系管理员增加次数。"
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
            base_url = chat_base_url(user_id, payload.provider, model_id)
            if not base_url:
                raise HTTPException(status_code=400, detail="Base URL is required for OpenAI Compatible or Custom chat models.")
            url = openai_chat_url(base_url)
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            }
            request_json = openai_chat_body(model_id, payload.requestBody)
            wrap_openai = True
        
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
                    return Response(
                        content=json.dumps(wrap_openai_chat_response(res_json), ensure_ascii=False),
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
                            502: "上游模型服务网关错误 (502)，请稍后重试或切换模型",
                            503: "上游模型服务暂时不可用 (503)，请稍后重试",
                            504: "上游模型服务响应超时 (504)，模型可能已消耗 token 但未能返回结果。建议稍后重试或切换模型",
                            429: "上游模型服务请求限流 (429)，请稍后重试",
                            403: "上游模型服务拒绝访问 (403)，可能是余额不足或 API Key 无效",
                        }
                        detail = status_map.get(res.status_code, f"上游模型服务返回异常 ({res.status_code})，请稍后重试或切换模型")
                        raise HTTPException(status_code=502, detail=detail)
                    # Non-HTML error: try to extract a clean error message from JSON
                    try:
                        err_json = res.json()
                        err_msg = err_json.get("error", {}).get("message", "") if isinstance(err_json.get("error"), dict) else str(err_json.get("error", ""))
                        if err_msg:
                            raise HTTPException(status_code=res.status_code, detail=f"上游模型服务错误 ({res.status_code}): {err_msg}")
                    except (ValueError, TypeError):
                        pass
                return Response(
                    content=res.content,
                    status_code=res.status_code,
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
                        if wrap_openai:
                            usage = res_data.get("usage", {})
                        else:
                            usage = res_data.get("usageMetadata", {}) or res_data.get("usage", {})
                        prompt_tokens = usage.get("prompt_tokens") or usage.get("promptTokenCount")
                        completion_tokens = usage.get("completion_tokens") or usage.get("candidatesTokenCount")
                        total_tokens = usage.get("total_tokens") or usage.get("totalTokenCount")
                        
                        choices = res_data.get("choices", [])
                        if choices:
                            output_chars = len(choices[0].get("message", {}).get("content", ""))
                else:
                    error_type = f"HTTP_{res.status_code}" if res is not None else "CONNECTION_ERROR"
                    
                if payload.provider != "gemini":
                    try:
                        input_chars = len(prompt_from_gemini_request(payload.requestBody))
                    except Exception:
                        pass
                
                analysis_id = payload.requestBody.get("analysis_id") or payload.requestBody.get("analysisId")
                
                state.auth_db.log_model_usage(
                    user_id=user_id,
                    config_id=resolved_config_id,
                    assignment_id=resolved_assignment_id,
                    analysis_id=analysis_id,
                    provider=payload.provider,
                    model_id=model_id,
                    usage_type="chat",
                    endpoint=None,
                    success=success,
                    error_type=error_type,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    input_chars=input_chars,
                    output_chars=output_chars,
                    latency_ms=duration
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
                    detail="您的账号生成额度已用尽，请联系管理员增加次数。"
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
        
        start_time = time.time()
        success = False
        res = None
        try:
            async with httpx.AsyncClient() as client:
                res = await client.post(url, headers=headers, json=payload.requestBody, timeout=120.0)
                success = res.status_code == 200
                return Response(
                    content=res.content,
                    status_code=res.status_code,
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
                    message = "未找到可用的 Gemini API Key：请在模型配置中保存 API Key，或在服务器 .env 中设置 GEMINI_API_KEY。"
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
                    message = "未找到可用的向量模型 API Key：请在模型配置中保存 API Key，或在服务器 .env 中设置 LLM_API_KEY。"
                    return {"ok": False, "message": message}
                
                if payload.type == "chat" and payload.provider in {"openai-compatible", "custom"}:
                    base_url = chat_base_url(user_id, payload.provider, model_id)
                    if not base_url:
                        message = "请先为该大语言模型配置 Base URL。"
                        return {"ok": False, "message": message}
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
            
            message = "不支持的 Provider 连接测试"
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
    def list_materials(user_id: Any = Depends(current_user_id)) -> dict[str, Any]:
        return {"documents": state.service.list_knowledge_documents(user_id)}

    @app.post("/api/materials")
    async def upload_material(
        file: UploadFile = File(...),
        title: str = Form(default=""),
        source_type: str = Form(default="resume"),
        user_id: Any = Depends(current_user_id),
    ) -> dict[str, Any]:
        content = await file.read()
        adapter = UploadedFileAdapter(file.filename or "upload.txt", content)
        try:
            document = state.service.upload_knowledge_document(user_id, adapter, source_type, title=title)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return {"document": document}

    @app.delete("/api/materials/{document_id}")
    def delete_material(document_id: int, user_id: Any = Depends(current_user_id)) -> dict[str, bool]:
        return {"deleted": state.service.delete_knowledge_document(user_id, document_id)}

    # ── STAR Story Builder routes ──

    @app.post("/api/star/generate-segment")
    def generate_star_segment(
        payload: StarStorySegmentRequest,
        user_id: Any = Depends(current_user_id)
    ) -> dict[str, Any]:
        try:
            suggestion = state.service.generate_star_segment_suggestion(
                segment_type=payload.segment_type,
                input_text=payload.input_text,
                jd_text=payload.jd_text,
                resume_text=payload.resume_text,
                current_star=payload.current_star,
                user_id=user_id,
                config_id=payload.config_id,
            )
            return {"suggestion": suggestion}
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @app.post("/api/star/polish")
    def polish_star(
        payload: StarStoryPolishRequest,
        user_id: Any = Depends(current_user_id)
    ) -> dict[str, Any]:
        user = state.auth_db.get_user_by_id(user_id)
        if user and user.role != "admin":
            if user.generation_limit is None or user.generation_limit <= 0:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="您的账号生成额度已用尽，请联系管理员增加次数。"
                )
        try:
            polished_text = state.service.polish_star_story(
                situation=payload.situation,
                task=payload.task,
                action=payload.action,
                result=payload.result,
                style=payload.style,
                jd_text=payload.jd_text,
                user_id=user_id,
                config_id=payload.config_id,
            )
            if user and user.role != "admin":
                state.auth_db.decrement_user_generation_limit(user_id)
            return {"polishedText": polished_text}
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @app.post("/api/star/smart-rewrite")
    def smart_rewrite_star(
        payload: StarSmartRewriteRequest,
        user_id: Any = Depends(current_user_id)
    ) -> dict[str, Any]:
        user = state.auth_db.get_user_by_id(user_id)
        if user and user.role != "admin":
            if user.generation_limit is None or user.generation_limit <= 0:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="您的账号生成额度已用尽，请联系管理员增加次数。"
                )
        try:
            result = state.service.smart_rewrite_star(
                original_text=payload.original_text,
                style=payload.style,
                jd_text=payload.jd_text,
                user_id=user_id,
                config_id=payload.config_id,
            )
            if user and user.role != "admin":
                state.auth_db.decrement_user_generation_limit(user_id)
            return result
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @app.get("/api/star/stories")
    def list_star_stories(user_id: Any = Depends(current_user_id)) -> dict[str, Any]:
        stories = state.service.list_star_stories(user_id)
        return {"stories": stories}

    @app.post("/api/star/stories")
    def create_star_story(
        payload: StarStoryCreateRequest,
        user_id: Any = Depends(current_user_id)
    ) -> dict[str, Any]:
        try:
            story = StarStory(
                title=payload.title,
                situation=payload.situation,
                task=payload.task,
                action=payload.action,
                result=payload.result,
                full_text=payload.full_text,
                style=payload.style,
            )
            story_id = state.service.save_star_story(user_id, story)
            return {"id": str(story_id), "ok": True}
        except Exception as exc:
            import traceback, sys
            print("[STAR_SAVE_500]", str(exc), file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @app.put("/api/star/stories/{story_id}")
    def update_star_story(
        story_id: str,
        payload: StarStoryCreateRequest,
        user_id: Any = Depends(current_user_id)
    ) -> dict[str, Any]:
        try:
            story = StarStory(
                title=payload.title,
                situation=payload.situation,
                task=payload.task,
                action=payload.action,
                result=payload.result,
                full_text=payload.full_text,
                style=payload.style,
            )
            ok = state.service.update_star_story(user_id, story_id, story)
            if not ok:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="故事不存在或无权修改。")
            return {"ok": True}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @app.delete("/api/star/stories/{story_id}")
    def delete_star_story(
        story_id: str,
        user_id: Any = Depends(current_user_id)
    ) -> dict[str, Any]:
        try:
            ok = state.service.delete_star_story(user_id, story_id)
            if not ok:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="故事不存在或无权删除。")
            return {"ok": True}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    # ── History routes (record_id uses str for UUID compat) ──

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
                    detail="您的账号生成额度已用尽，请联系管理员增加次数。"
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

    # ── Analysis (with transaction-safe draft conversion) ──

    @app.post("/api/analyze")
    def analyze(payload: AnalyzeRequest, user_id: Any = Depends(current_user_id)) -> dict[str, Any]:
        user = state.auth_db.get_user_by_id(user_id)
        if user and user.role != "admin":
            if user.generation_limit is None or user.generation_limit <= 0:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="您的账号生成额度已用尽，请联系管理员增加次数。"
                )

        check_rate_limit(f"analyze:{user_id}", 10, 3600, skip=user is not None and user.role == "admin")
        if len(payload.jd_text) > 5000:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="输入内容过长，请减少无关内容后再分析。")
        chunks = state.service.get_knowledge_chunks_for_analysis(user_id, payload.knowledge_document_ids)
        knowledge_texts = [chunk.get("content", "") for chunk in chunks if chunk.get("content")]
        analysis = state.service.extract_skills(payload.jd_text, user_id=user_id)
        decision = state.service.build_personal_decision(
            jd_text=payload.jd_text,
            analysis=analysis,
            resume_text=payload.resume_text,
            knowledge_texts=knowledge_texts,
            user_id=user_id,
        )
        analysis.personal_decision = decision
        guardrail_report = state.service.analyze_jd_with_guardrails(
            user_id=user_id,
            jd_text=payload.jd_text,
            resume_text=payload.resume_text,
            knowledge_texts=knowledge_texts,
            selected_document_ids=payload.knowledge_document_ids,
            options=payload.expert_options,
            original_analysis=analysis,
        )
        # Use transaction-safe draft conversion if draft_id is provided
        db = state.service.user_db(user_id)
        if payload.draft_id:
            try:
                record_id = db.save_jd_record_and_convert_draft(user_id, payload.jd_text, analysis, draft_id=payload.draft_id)
            except Exception:
                record_id = db.save_jd_record(user_id, payload.jd_text, analysis)
        else:
            record_id = db.save_jd_record(user_id, payload.jd_text, analysis)
        record = state.service.get_jd_record(user_id, record_id)
        # Also save to analysis_records for unified history
        analysis_result = {
            "jdRecordId": record_id,
            "createdAt": record.created_at.isoformat() if record and record.created_at else "",
            "draft": {"jdText": payload.jd_text},
            "decision": decision.recommendation.lower() if decision else "",
            "matchScore": decision.match_score if decision else 0,
            "oneLineReason": decision.decision_reasons[0] if decision and decision.decision_reasons else "",
            "detectedKeywords": analysis.skills or [],
            "priority": "P1",
            "status": "watching",
        }
        state.auth_db.save_analysis_record(
            user_id=user_id,
            status="watching",
            result_json=analysis_result,
        )

        # Decrement limit for standard users after successful analyze
        if user and user.role != "admin":
            state.auth_db.decrement_user_generation_limit(user_id)

        return {
            "record": record.model_dump(mode="json") if record else None,
            "analysis": analysis.model_dump(mode="json"),
            "personal_decision": decision.model_dump(mode="json"),
            "expert_report": guardrail_report,
        }

    # ── Drafts CRUD ──

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

    # ── User Settings ──

    @app.get("/api/settings")
    def get_settings(user_id: Any = Depends(current_user_id)) -> dict[str, Any]:
        settings = state.auth_db.get_settings(user_id)
        return {"settings": settings}

    @app.post("/api/settings")
    def save_settings(payload: dict[str, Any], user_id: Any = Depends(current_user_id)) -> dict[str, bool]:
        state.auth_db.save_settings(user_id, payload)
        return {"ok": True}

    # ── Model Configs CRUD ──

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

    # ── Admin Console API Endpoints ──

    @app.get("/api/admin/users")
    def admin_list_users(admin_id: Any = Depends(current_admin_user)) -> dict[str, Any]:
        users = state.auth_db.admin_list_users()
        return {"users": users}

    @app.post("/api/admin/users/generate-temp")
    async def admin_generate_temp_users(
        payload: GenerateTempUsersRequest,
        admin_id: Any = Depends(current_admin_user)
    ) -> dict[str, Any]:
        if payload.quantity < 1 or payload.quantity > 50:
            raise HTTPException(status_code=400, detail="生成数量必须在 1 到 50 之间。")
        if payload.duration_hours <= 0 or payload.duration_hours > 876000:
            raise HTTPException(status_code=400, detail="有效时间必须大于 0 且不能超过 100 年（876000小时）。")


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
            raise HTTPException(status_code=400, detail="管理员不能禁用/修改自己的账户状态。")
        
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
            raise HTTPException(status_code=400, detail="管理员不能修改自己的账户过期时间。")
            
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
            raise HTTPException(status_code=400, detail="管理员不能修改自己的生成次数（管理员默认无限次）。")

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
            raise HTTPException(status_code=400, detail="管理员不能删除自己的账户。")
            
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
            raise HTTPException(status_code=404, detail="未找到该管理员配置，或者该配置不属于管理员管理。")
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

    return app


app = create_app()

frontend_dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
