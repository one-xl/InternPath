from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


SessionStatus = Literal[
    "ACTIVE",
    "WAITING_FOR_USER",
    "READY_FOR_CONFIRMATION",
    "SATISFIED",
    "ARCHIVED",
    "FAILED",
]
RunStatus = Literal["QUEUED", "RUNNING", "PAUSED", "COMPLETED", "FAILED"]
SuggestionAction = Literal["accepted", "rejected", "needs_revision", "applied", "restore"]


class ResumeAdvisorSessionCreate(BaseModel):
    resume_id: str = Field(min_length=1, max_length=255)
    jd_text: str = Field(min_length=1, max_length=50000)
    analysis_record_id: str | None = Field(default=None, max_length=255)
    title: str | None = Field(default=None, max_length=255)

    @field_validator("jd_text")
    @classmethod
    def normalize_jd_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("请提供目标岗位 JD。")
        return text


class ResumeAdvisorMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=10000)
    client_message_id: str = Field(min_length=1, max_length=255)
    remember: bool = False
    message_kind: Literal["text", "question", "fact", "preference"] = "text"

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("消息不能为空。")
        return text


class ResumeSuggestionActionRequest(BaseModel):
    action: SuggestionAction
    feedback: str = Field(default="", max_length=4000)


class ResumeAdvisorFinishRequest(BaseModel):
    confirmation: Literal["satisfied"]
