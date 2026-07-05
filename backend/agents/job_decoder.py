import os
import re
import json
from typing import Any, Dict, Optional
from backend.agents.base import BaseAgent
from backend.agents.schemas import JobDecodeOutput, parse_json_model

class JobDecoder(BaseAgent):
    """
    岗位解码专家智能体，负责深度解析岗位 JD，提取结构化的硬性与软性要求。
    """
    def __init__(
        self,
        agent_id: str = "job_decoder",
        role: str = "Job_Decoder",
        model: str = "gpt-4o-mini",
        openai_client: Optional[Any] = None
    ):
        """
        初始化 JobDecoder 智能体。
        """
        super().__init__(agent_id=agent_id, role=role, model=model, openai_client=openai_client)
        self._load_system_prompt()

    def _load_system_prompt(self) -> None:
        """
        从本地 md 文件加载系统提示词模板，失败则使用内置提示词。
        """
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            prompt_path = os.path.join(current_dir, "prompts", "job_decoder.md")
            if os.path.exists(prompt_path):
                with open(prompt_path, "r", encoding="utf-8") as f:
                    self.system_prompt = f.read()
                    return
        except Exception:
            pass

        self.system_prompt = (
            "你是一个专业的岗位解码专家。负责深度解析招聘岗位描述 (JD)，"
            "提取岗位所需的硬性要求（如核心技术栈、工具链、学历背景、工作年限等）"
            "与软性要求（如项目经验、高并发、性能调优、团队协作等行业或背景要求）。\n"
            "请严格以 JSON 格式输出解析画像，包含以下字段：\n"
            "- hard_requirements: 包含 technical_stack (list of str), education (str), experience_years (str)\n"
            "- soft_requirements: 包含 industry_background (list of str), project_attributes (list of str), soft_skills (list of str)\n"
            "- core_duties: 岗位核心职责列表 (list of str)\n"
            "请确保 JSON 格式合法且不包含 markdown 格式标记。"
        )

    async def decode_job(self, jd_text: str) -> dict:
        """
        深度解析岗位 JD，返回结构化的解码画像。

        Args:
            jd_text (str): 岗位描述 (JD) 文本。

        Returns:
            dict: 结构化的岗位画像字典。
        """
        self.reset_context(user_id="default", query="")

        user_prompt = f"""
请深度解析以下岗位 JD 文本，提取出结构化的硬性要求、软性要求和核心职责：

[岗位 JD 文本]
{jd_text}

请严格按照系统提示词要求的 JSON 格式输出。
"""

        llm_response = await self._call_llm(
            system_prompt=self.system_prompt,
            user_prompt=user_prompt,
            temperature=0.2
        )

        return self._parse_json_result(llm_response)

    def _parse_json_result(self, raw_text: str) -> dict:
        """
        安全地从大模型的响应中解析 JSON 岗位画像。
        """
        clean_text = raw_text.strip()

        return parse_json_model(clean_text, JobDecodeOutput, "岗位解码结果").model_dump()
