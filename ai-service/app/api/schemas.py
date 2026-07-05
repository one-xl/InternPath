"""Pydantic schemas for the InternPath AI service."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator


class _ApiModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class DocumentInput(_ApiModel):
    documentId: str
    content: str
    chunkId: str | None = None
    sectionId: str | None = None
    sectionType: str | None = None
    sectionTitle: str | None = None
    hierarchy: list[str] = Field(default_factory=list)
    semanticType: str | None = None
    importance: float | None = None
    keywords: list[str] = Field(default_factory=list)
    embeddingText: str | None = None
    embedding: list[float] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RagSearchRequest(_ApiModel):
    query: str
    documents: list[DocumentInput] = Field(default_factory=list)
    topK: StrictInt = Field(default=5, ge=1, le=20)

    @field_validator("query")
    @classmethod
    def query_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must be a non-empty string")
        return value


class AnalysisOptions(_ApiModel):
    enableRag: StrictBool = True
    enableVerification: StrictBool = True
    enableHallucinationCheck: StrictBool = True
    enableRewrite: StrictBool = True


class AnalyzeJdRequest(_ApiModel):
    taskId: str
    userId: str
    jdText: str
    resumeText: str = ""
    knowledgeTexts: list[str] = Field(default_factory=list)
    documents: list[DocumentInput] = Field(default_factory=list)
    options: AnalysisOptions = Field(default_factory=AnalysisOptions)
    embeddingModelId: str | None = None
    embeddingProvider: str | None = None
    embeddingApiKey: str | None = None
    embeddingBaseUrl: str | None = None

    @field_validator("jdText")
    @classmethod
    def jd_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("jdText must be a non-empty string")
        return value


class VerifyReportRequest(_ApiModel):
    report: dict[str, Any]
    jdText: str = ""
    resumeText: str = ""
    evidenceChunks: list[dict[str, Any]] = Field(default_factory=list)
