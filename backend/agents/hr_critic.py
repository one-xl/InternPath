import os
import re
import json
from typing import Any, Dict, Optional
from backend.agents.base import BaseAgent
from backend.agents.schemas import HRCriticOutput, parse_json_model

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
        except Exception as e:
            # 异常发生时，提供简易的默认 Prompt 兜底
            self.system_prompt = (
                "你是一个大厂技术面试官和简历专家。请以 JSON 格式输出评分与建议。\n"
                "必须包含 score (0-100), is_passed (bool, >=85), critique (str), suggestions (str)。"
            )

    async def evaluate(
        self,
        section_name: str,
        original_content: str,
        optimized_content: str,
        jd_text: str,
        user_id: str = "default"
    ) -> Dict[str, Any]:
        """
        评估优化后的简历段落。

        Args:
            section_name (str): 简历模块名称（例如：项目经历）。
            original_content (str): 原始简历中对应的段落内容。
            optimized_content (str): 优化后的段落内容。
            jd_text (str): 目标岗位 JD 文本。
            user_id (str): 用户 ID。

        Returns:
            dict: 包含 score, is_passed, critique, suggestions 的评估结果。
        """
        # 重置上下文（加载 System Prompt 并支持 Few-shot 规则）
        self.reset_context(user_id=user_id, query="")

        # 构造待评审的用户提示词
        user_prompt = f"""
请评估以下优化后的简历段落质量：

[目标模块名称]
{section_name}

[原始简历段落]
{original_content}

[优化后的简历段落]
{optimized_content}

[目标岗位描述 (JD)]
{jd_text}

请严格按照系统提示词定义的 JSON 格式输出结果。
"""

        # 调用父类的通用 LLM 方法，temperature 设为较稳定的 0.2
        llm_response = await self._call_llm(
            system_prompt=self.context[0]["content"],
            user_prompt=user_prompt,
            temperature=0.2
        )

        return self._parse_evaluation_result(llm_response)

    def _parse_evaluation_result(self, raw_text: str) -> Dict[str, Any]:
        """
        安全地从大模型的响应中解析 JSON 评估数据。

        Args:
            raw_text (str): 大模型返回的原始字符串。

        Returns:
            dict: 解析后的字典。
        """
        clean_text = raw_text.strip()

        return parse_json_model(clean_text, HRCriticOutput, "HR 审计结果").model_dump()
