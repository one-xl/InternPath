from __future__ import annotations

import json
import re
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


AGENT_SCHEMA_VERSION = "2026-07-05.agent-resume-schema-v2"

ModelT = TypeVar("ModelT", bound=BaseModel)


def extract_json_object(raw_text: str) -> dict[str, Any]:
    clean_text = (raw_text or "").strip()
    if clean_text.startswith("```"):
        fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```", clean_text, flags=re.IGNORECASE | re.DOTALL)
        if fenced:
            clean_text = fenced.group(1)
        else:
            clean_text = re.sub(r"^```(?:json)?\s*", "", clean_text, flags=re.IGNORECASE)
            clean_text = re.sub(r"\s*```$", "", clean_text)
        clean_text = clean_text.strip()

    decoder = json.JSONDecoder()
    candidates = [clean_text]
    first_brace = clean_text.find("{")
    if first_brace > 0:
        candidates.append(clean_text[first_brace:].strip())

    parsed: Any = None
    last_error: json.JSONDecodeError | None = None
    try:
        parsed = json.loads(clean_text)
    except json.JSONDecodeError as exc:
        last_error = exc
        for candidate in candidates:
            if not candidate:
                continue
            try:
                parsed, _ = decoder.raw_decode(candidate)
                break
            except json.JSONDecodeError as raw_exc:
                last_error = raw_exc
        else:
            raise ValueError("大模型输出不是合法 JSON 对象。") from last_error

    if not isinstance(parsed, dict):
        raise ValueError("大模型输出必须是 JSON 对象。")
    return parsed


def parse_json_model(raw_text: str, model_cls: type[ModelT], label: str) -> ModelT:
    payload = extract_json_object(raw_text)
    try:
        return model_cls.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"{label}未通过结构化 Schema 校验: {exc}") from exc


class StrictAgentModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExecutionPlanStep(StrictAgentModel):
    step_index: int = Field(..., ge=1)
    section_index: int = Field(..., ge=0)
    section_name: str = Field(..., min_length=1)
    original_content: str = Field(..., min_length=1)
    improvement_goal: str = Field(..., min_length=1)
    requires_human_input: bool = False
    human_question: str = ""
    status: Literal["PENDING", "RUNNING", "COMPLETED", "SKIPPED"] = "PENDING"


class ExecutionPlanOutput(StrictAgentModel):
    steps: list[ExecutionPlanStep] = Field(default_factory=list)

    @field_validator("steps")
    @classmethod
    def validate_step_order(cls, steps: list[ExecutionPlanStep]) -> list[ExecutionPlanStep]:
        expected = 1
        for step in steps:
            if step.step_index != expected:
                raise ValueError("step_index 必须从 1 开始连续递增。")
            expected += 1
        return steps


class HardRequirements(StrictAgentModel):
    technical_stack: list[str]
    education: str
    experience_years: str


class SoftRequirements(StrictAgentModel):
    industry_background: list[str]
    project_attributes: list[str]
    soft_skills: list[str]


class JobDecodeOutput(StrictAgentModel):
    hard_requirements: HardRequirements
    soft_requirements: SoftRequirements
    core_duties: list[str]


class HRCriticOutput(StrictAgentModel):
    score: int = Field(..., ge=0, le=100)
    is_passed: bool
    critique: str
    suggestions: str


class LayoutAuditOutput(StrictAgentModel):
    score: int = Field(..., ge=0, le=100)
    is_passed: bool
    issues: list[str]
