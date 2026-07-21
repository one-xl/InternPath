import json
import os
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator

from backend.agents.base import BaseAgent
from backend.agents.schemas import HRCriticOutput, parse_json_model


class HRCriticOutputError(ValueError):
    """The provider responded, but its review cannot be trusted as a gate decision."""


class HRCriticDimension(BaseModel):
    """One independently assessed review dimension returned by the model."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    verdict: Literal["pass", "fail"]
    rationale: str = Field(min_length=1, max_length=2000)
    evidence_basis: list[str] = Field(default_factory=list, max_length=8)


class HRCriticEvaluation(BaseModel):
    """Strict, model-produced contract required before a suggestion can be released."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    score: StrictInt = Field(ge=0, le=100)
    is_passed: StrictBool
    factual_fidelity: HRCriticDimension
    role_jd_relevance: HRCriticDimension
    clarity_scannability: HRCriticDimension
    recruiting_usefulness: HRCriticDimension
    critique: str = Field(min_length=1, max_length=3000)
    suggestions: str = Field(min_length=1, max_length=3000)

    @model_validator(mode="after")
    def require_consistent_gate_decision(self) -> "HRCriticEvaluation":
        all_dimensions_pass = all(
            dimension.verdict == "pass"
            for dimension in (
                self.factual_fidelity,
                self.role_jd_relevance,
                self.clarity_scannability,
                self.recruiting_usefulness,
            )
        )
        if self.is_passed != all_dimensions_pass:
            raise ValueError("is_passed must match the verdict of every HRCritic review dimension")
        return self

class HRCritic(BaseAgent):
    """
    专家审计官智能体，负责评估简历优化段落的质量，并返回评分与改进建议。
    """
    def __init__(
        self,
        agent_id: str = "hr_critic",
        role: str = "HR_Critic",
        model: str = "gpt-4o-mini",
        openai_client: Optional[Any] = None
    ):
        """
        初始化 HRCritic 智能体。

        Args:
            agent_id (str): 智能体 ID。
            role (str): 智能体角色。
            model (str): 所选大模型名称。
            openai_client (Any, optional): OpenAI 客户端实例。
        """
        super().__init__(agent_id=agent_id, role=role, model=model, openai_client=openai_client)
        self._load_system_prompt()

    def _load_system_prompt(self) -> None:
        """
        从本地 md 文件加载系统提示词模板。
        """
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            prompt_path = os.path.join(current_dir, "prompts", "hr_critic.md")
            with open(prompt_path, "r", encoding="utf-8") as f:
                self.system_prompt = f.read()
        except Exception:
            self.system_prompt = (
                "你是独立的简历招聘审核门。JD 只能用于判断岗位相关性，不能证明候选人事实。"
                "仅输出严格 JSON，且必须包含 score、is_passed、factual_fidelity、role_jd_relevance、"
                "clarity_scannability、recruiting_usefulness、critique、suggestions。"
            )

    async def evaluate(
        self,
        section_name: str,
        original_content: str,
        optimized_content: str,
        jd_text: str,
        user_id: str = "default",
        resume_evidence_texts: Optional[list[str]] = None,
        confirmed_facts: Optional[list[str]] = None,
    ) -> Dict[str, Any]:
        """Legacy-compatible HR evaluation for existing orchestration callers."""
        response = await self._request_evaluation(
            section_name=section_name,
            original_content=original_content,
            optimized_content=optimized_content,
            jd_text=jd_text,
            user_id=user_id,
            resume_evidence_texts=resume_evidence_texts,
            confirmed_facts=confirmed_facts,
        )
        return self._parse_evaluation_result(response)

    async def evaluate_advisor_suggestion(
        self,
        *,
        section_name: str,
        original_content: str,
        optimized_content: str,
        jd_text: str,
        resume_evidence_texts: Optional[list[str]] = None,
        confirmed_facts: Optional[list[str]] = None,
        user_id: str = "default",
    ) -> Dict[str, Any]:
        """Strict independent gate used only before an Advisor suggestion is released."""
        response = await self._request_evaluation(
            section_name=section_name,
            original_content=original_content,
            optimized_content=optimized_content,
            jd_text=jd_text,
            user_id=user_id,
            resume_evidence_texts=resume_evidence_texts,
            confirmed_facts=confirmed_facts,
        )
        return self._parse_advisor_evaluation_result(response)

    async def _request_evaluation(
        self,
        *,
        section_name: str,
        original_content: str,
        optimized_content: str,
        jd_text: str,
        user_id: str,
        resume_evidence_texts: Optional[list[str]],
        confirmed_facts: Optional[list[str]],
    ) -> str:
        self.reset_context(user_id=user_id, query="")
        evidence_text = "\n".join(
            f"- {str(item).strip()}"
            for item in (resume_evidence_texts or [])
            if str(item).strip()
        ) or "无"
        confirmed_fact_text = "\n".join(
            f"- {str(item).strip()}"
            for item in (confirmed_facts or [])
            if str(item).strip()
        ) or "无"

        user_prompt = f"""
请作为独立招聘审核门评估以下候选人可见的简历建议。不要改写简历，也不要生成候选人可见文本。

[目标模块名称]
{section_name}

[原始简历段落]
{original_content}

[优化后的简历段落]
{optimized_content}

[同份简历的补充证据]
{evidence_text}

[用户已确认事实]
{confirmed_fact_text}

[目标岗位描述 (JD)]
{jd_text}

原始段落、补充证据和已确认事实可以用于判断事实保真；JD 绝不能用作候选人事实证据。
请严格按照系统提示词定义的 JSON 格式输出结果。
"""

        llm_response = await self._call_llm(
            system_prompt=self.context[0]["content"],
            user_prompt=user_prompt,
            temperature=0.2
        )

        return str(llm_response or "")

    def _parse_evaluation_result(self, raw_text: str) -> Dict[str, Any]:
        """Keep the historic four-field contract while accepting new strict reviews."""
        clean_text = raw_text.strip()
        try:
            strict = parse_json_model(clean_text, HRCriticEvaluation, "HR 审计结果")
        except ValueError:
            try:
                return parse_json_model(clean_text, HRCriticOutput, "HR 审计结果").model_dump()
            except ValueError as exc:
                raise HRCriticOutputError(str(exc)) from exc
        return {
            "score": strict.score,
            "is_passed": strict.is_passed,
            "critique": strict.critique,
            "suggestions": strict.suggestions,
        }

    def _parse_advisor_evaluation_result(self, raw_text: str) -> Dict[str, Any]:
        """Reject any Advisor review that does not include every independent dimension."""
        if not isinstance(raw_text, str):
            raise HRCriticOutputError("Advisor HR 审计结果必须是一个原始 JSON 对象。")
        clean_text = raw_text.strip()
        if not clean_text:
            raise HRCriticOutputError("Advisor HR 审计结果不能为空。")
        try:
            payload = json.loads(clean_text)
        except json.JSONDecodeError as exc:
            raise HRCriticOutputError("Advisor HR 审计结果必须是一个完整的原始 JSON 对象。") from exc
        if not isinstance(payload, dict):
            raise HRCriticOutputError("Advisor HR 审计结果必须是一个 JSON 对象。")
        try:
            return HRCriticEvaluation.model_validate(payload).model_dump()
        except Exception as exc:
            raise HRCriticOutputError(str(exc)) from exc
