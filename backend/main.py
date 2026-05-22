from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from database import Database
from document_parser import DocumentParseError
from models import JobAnalysis
from backend.doubao_job_rag import DoubaoAnalysisError, analyze_job_with_doubao
from backend.resume_rag import parse_resume, retrieve_chunks
from service import CareerPathAIService


class AuthRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=8)


class AnalyzeRequest(BaseModel):
    jd_text: str = Field(..., min_length=20)
    resume_text: str = ""
    knowledge_document_ids: list[int] = Field(default_factory=list)
    expert_options: dict[str, bool] = Field(default_factory=dict)


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
    id: int
    username: str
    created_at: datetime


@dataclass
class AppState:
    service: CareerPathAIService
    auth_db: Database
    sessions: dict[str, int] = field(default_factory=dict)
    resume_store: dict[str, dict[str, Any]] = field(default_factory=dict)


class UploadedFileAdapter:
    def __init__(self, file_name: str, content: bytes):
        self.name = file_name
        self._content = content

    def getvalue(self) -> bytes:
        return self._content


def create_app(
    *,
    service: Optional[CareerPathAIService] = None,
    auth_db: Optional[Database] = None,
) -> FastAPI:
    app = FastAPI(title="InternPath Personal Workbench API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:4173",
            "http://localhost:4173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    state = AppState(
        service=service or CareerPathAIService(),
        auth_db=auth_db or Database(),
    )

    def issue_token(user_id: int) -> str:
        token = uuid4().hex
        state.sessions[token] = user_id
        return token

    def current_user_id(authorization: str = Header(default="")) -> int:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not_authenticated")
        user_id = state.sessions.get(token)
        if user_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="session_expired")
        return user_id

    def auth_payload(user_id: int, token: str) -> dict[str, Any]:
        user = state.auth_db.get_user_by_id(user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user_not_found")
        return {
            "token": token,
            "user": UserResponse(
                id=user.id or user_id,
                username=user.username,
                created_at=user.created_at,
            ).model_dump(mode="json"),
        }

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/resumes/upload")
    async def upload_resume(file: UploadFile = File(...)) -> dict[str, Any]:
        content = await file.read()
        try:
            parsed_resume = parse_resume(file.filename or "resume", file.content_type or "", content)
        except DocumentParseError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        state.resume_store[parsed_resume["file"]["id"]] = parsed_resume
        return {
            "resumeFile": parsed_resume["file"],
            "parsedResume": parsed_resume,
        }

    @app.post("/api/resumes/retrieve")
    def retrieve_resume(payload: ResumeRetrieveRequest) -> dict[str, Any]:
        parsed_resume = state.resume_store.get(payload.resumeFileId)
        if parsed_resume is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="简历文件不存在或已过期，请重新上传")
        try:
            return retrieve_chunks(payload.jdText, parsed_resume.get("chunks", []), payload.topK)
        except DocumentParseError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/api/analysis/job-rag")
    def analyze_job_rag(payload: JobRagAnalyzeRequest) -> dict[str, Any]:
        parsed_resume = state.resume_store.get(payload.resumeFileId) if payload.resumeFileId else None
        if parsed_resume is None and payload.parsedResume:
            parsed_resume = payload.parsedResume
        if parsed_resume is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="简历文件不存在或已过期，请重新上传")
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
                }
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
    def register(payload: AuthRequest) -> dict[str, Any]:
        try:
            user_id = state.auth_db.create_user(payload.username, payload.password)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return auth_payload(user_id, issue_token(user_id))

    @app.post("/api/auth/login")
    def login(payload: AuthRequest) -> dict[str, Any]:
        user = state.auth_db.authenticate_user(payload.username, payload.password)
        if user is None or user.id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials")
        return auth_payload(user.id, issue_token(user.id))

    @app.get("/api/me")
    def me(user_id: int = Depends(current_user_id)) -> dict[str, Any]:
        user = state.auth_db.get_user_by_id(user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user_not_found")
        return UserResponse(id=user.id or user_id, username=user.username, created_at=user.created_at).model_dump(mode="json")

    @app.get("/api/materials")
    def list_materials(user_id: int = Depends(current_user_id)) -> dict[str, Any]:
        return {"documents": state.service.list_knowledge_documents(user_id)}

    @app.post("/api/materials")
    async def upload_material(
        file: UploadFile = File(...),
        title: str = Form(default=""),
        source_type: str = Form(default="resume"),
        user_id: int = Depends(current_user_id),
    ) -> dict[str, Any]:
        content = await file.read()
        adapter = UploadedFileAdapter(file.filename or "upload.txt", content)
        try:
            document = state.service.upload_knowledge_document(user_id, adapter, source_type, title=title)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return {"document": document}

    @app.delete("/api/materials/{document_id}")
    def delete_material(document_id: int, user_id: int = Depends(current_user_id)) -> dict[str, bool]:
        return {"deleted": state.service.delete_knowledge_document(user_id, document_id)}

    @app.get("/api/history")
    def list_history(limit: int = 30, user_id: int = Depends(current_user_id)) -> dict[str, Any]:
        records = state.service.get_history(user_id, limit)
        return {"records": [record.model_dump(mode="json") for record in records]}

    @app.get("/api/history/{record_id}")
    def get_record(record_id: int, user_id: int = Depends(current_user_id)) -> dict[str, Any]:
        record = state.service.get_jd_record(user_id, record_id)
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="record_not_found")
        return {"record": record.model_dump(mode="json")}

    @app.patch("/api/history/{record_id}")
    def rename_record(
        record_id: int,
        payload: RenameRecordRequest,
        user_id: int = Depends(current_user_id),
    ) -> dict[str, bool]:
        state.service.rename_jd_record(user_id, record_id, payload.display_name.strip() or None)
        return {"ok": True}

    @app.delete("/api/history/{record_id}")
    def delete_record(record_id: int, user_id: int = Depends(current_user_id)) -> dict[str, bool]:
        state.service.delete_jd_record(user_id, record_id)
        return {"deleted": True}

    @app.post("/api/analyze")
    def analyze(payload: AnalyzeRequest, user_id: int = Depends(current_user_id)) -> dict[str, Any]:
        chunks = state.service.get_knowledge_chunks_for_analysis(user_id, payload.knowledge_document_ids)
        knowledge_texts = [chunk.get("content", "") for chunk in chunks if chunk.get("content")]
        analysis = state.service.extract_skills(payload.jd_text)
        decision = state.service.build_personal_decision(
            jd_text=payload.jd_text,
            analysis=analysis,
            resume_text=payload.resume_text,
            knowledge_texts=knowledge_texts,
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
        record_id = state.service.user_db(user_id).save_jd_record(user_id, payload.jd_text, analysis)
        record = state.service.get_jd_record(user_id, record_id)
        return {
            "record": record.model_dump(mode="json") if record else None,
            "analysis": analysis.model_dump(mode="json"),
            "personal_decision": decision.model_dump(mode="json"),
            "expert_report": guardrail_report,
        }

    return app


app = create_app()

frontend_dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
