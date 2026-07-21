from __future__ import annotations

from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict

from backend.agents.tool_registry import (
    AgentToolContext,
    AgentToolProfile,
    AgentToolRegistry,
    AgentToolSideEffect,
    AgentToolSpec,
)


def _schema_for(arguments: dict[str, Any]) -> dict[str, Any]:
    properties: dict[str, dict[str, str]] = {}
    for key, value in arguments.items():
        if isinstance(value, bool):
            value_type = "boolean"
        elif isinstance(value, int):
            value_type = "integer"
        elif isinstance(value, float):
            value_type = "number"
        elif isinstance(value, list):
            value_type = "array"
        elif isinstance(value, dict):
            value_type = "object"
        else:
            value_type = "string"
        properties[key] = {"type": value_type}
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


class _JdParseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jdText: str


class _JdParseOutput(BaseModel):
    requirements: list[str]


class _ResumeRetrievalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jdText: str


class _ResumeRetrievalOutput(BaseModel):
    evidenceCount: int
    chunkIds: list[str]
    retrievalMode: Literal["ai_service_hybrid", "local_lexical_fallback"]
    semanticMode: Literal["embedding", "unavailable"] | None = None


class _BlockOperationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    blockId: str


class _VerificationOutput(BaseModel):
    status: str
    issueCount: int


class _QualityReviewOutput(BaseModel):
    isPassed: bool
    score: float
    issueCount: int
    reviewer: str


_TOOL_MODELS: dict[str, tuple[type[BaseModel], type[BaseModel]]] = {
    "extract_jd_requirements": (_JdParseInput, _JdParseOutput),
    "parse_jd_requirements": (_JdParseInput, _JdParseOutput),
    "retrieve_resume_evidence": (_ResumeRetrievalInput, _ResumeRetrievalOutput),
    "verify_suggestion_facts": (_BlockOperationInput, _VerificationOutput),
    "hr_quality_review": (_BlockOperationInput, _QualityReviewOutput),
}


class ResumeAdvisorToolRuntime:
    """Run one bounded Advisor operation through the shared tool contract."""

    def execute(
        self,
        *,
        name: str,
        user_id: Any,
        session_id: str,
        trace_id: str,
        arguments: dict[str, Any],
        handler: Callable[[], dict[str, Any]],
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        input_model, output_model = _TOOL_MODELS.get(name, (None, None))

        def wrapped_handler(_ctx: AgentToolContext, _arguments: dict[str, Any]) -> dict[str, Any]:
            return {"ok": True, "data": handler()}

        registry = AgentToolRegistry([
            AgentToolSpec(
                name=name,
                description=f"ResumeAdvisor bounded operation: {name}.",
                parameters_schema=_schema_for(arguments),
                handler=wrapped_handler,
                read_only=True,
                timeout_seconds=timeout_seconds,
                side_effect=AgentToolSideEffect.READ,
                profiles=frozenset({AgentToolProfile.RESUME_ADVISOR}),
                input_model=input_model,
                output_model=output_model,
            )
        ])
        return registry.execute_profiled(
            name,
            arguments,
            AgentToolContext(
                user_id=user_id,
                task_id=session_id,
                is_co_pilot=False,
                profile=AgentToolProfile.RESUME_ADVISOR,
                trace_id=trace_id,
            ),
        )
