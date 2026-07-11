import os
from typing import Any, Callable, Optional, Dict
from backend.agents.base import BaseAgent

class ResumeCopywriter(BaseAgent):
    """
    简历修辞专家智能体，负责针对目标岗位画像，使用专业级规范重构特定的简历段落。
    注意：为避免文案呆板，本智能体不含有任何“STAR”等特定方法论的品牌字眼。
    """
    def __init__(
        self,
        agent_id: str = "resume_copywriter",
        role: str = "Resume_Copywriter",
        model: str = "gpt-4o-mini",
        openai_client: Optional[Any] = None
    ):
        """
        初始化 ResumeCopywriter 智能体。
        """
        super().__init__(agent_id=agent_id, role=role, model=model, openai_client=openai_client)
        self._load_system_prompt()

    def _load_system_prompt(self) -> None:
        """
        从本地 md 文件加载系统提示词模板，失败则使用内置提示词。
        """
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            prompt_path = os.path.join(current_dir, "prompts", "resume_copywriter.md")
            if os.path.exists(prompt_path):
                with open(prompt_path, "r", encoding="utf-8") as f:
                    self.system_prompt = f.read()
                    return
        except Exception:
            pass

        self.system_prompt = (
            "你是一个资深的简历修辞润色专家。你的职责是深度改写和优化简历中的特定段落，"
            "使其完美匹配目标岗位（JD）的要求。\n"
            "改写规范：\n"
            "1. 必须使用大厂标准的专业词汇和精炼的行为动词，提升语言表达的商业与工程质感。\n"
            "2. 突出可量化的实际成果和核心技术贡献（如性能提升百分比、吞吐量、开发周期缩短等）。\n"
            "3. 绝对保持事实的真实性，不能虚构、捏造经历中没有的公司名称、学校名称、时间或从未涉及的重大系统架构。\n"
            "4. 结构保留原则：必须保留原段落的时间、项目名称、基本骨架和各项的顺序，仅对具体描述内容进行精细重构润色。\n"
            "5. 请直接输出润色后的简历段落，不要包含任何多余的开场白、解释或总结。"
        )

    async def rewrite_section(
        self,
        section_name: str,
        original_content: str,
        decoded_job: dict,
        goal: str,
        user_id: str = "default",
        on_delta: Optional[Callable[[str], None]] = None,
        preference_rules: Optional[list[str]] = None,
    ) -> str:
        """
        深度重构指定的简历段落。

        Args:
            section_name (str): 简历模块名称。
            original_content (str): 段落的原始文本。
            decoded_job (dict): 岗位解码后的结构化画像。
            goal (str): 当前段落的优化目标。
            user_id (str): 用户唯一标识。

        Returns:
            str: 润色后的段落文本。
        """
        self.reset_context(user_id=user_id, query="")

        # 检索当前用户针对此模块的历史偏好与 Few-shot 规则
        if preference_rules is None:
            from backend.memory.preference_db import PreferenceDB

            pref_db = PreferenceDB()
            preferences = pref_db.get_preferences(user_id, section_name)
        else:
            preferences = [str(item).strip() for item in preference_rules if str(item).strip()]

        user_preference_prompt = ""
        if preferences:
            pref_list_str = "\n".join([f"- {p}" for p in preferences])
            user_preference_prompt = f"\n[用户的历史偏好与 Few-shot 修改要求]\n{pref_list_str}\n"

        user_prompt = f"""
请针对以下优化目标、用户历史偏好和目标岗位画像，深度改写指定的简历段落。

[待优化的简历段落名称]
{section_name}

[待优化的原始段落内容]
{original_content}
{user_preference_prompt}
[优化目标]
{goal}

[目标岗位画像]
{decoded_job}

请严格遵守系统提示词中的改写规范并参考用户历史偏好，直接返回优化重构后的简历段落文本。
"""

        if on_delta:
            llm_response = await self._call_llm_stream(
                system_prompt=self.system_prompt,
                user_prompt=user_prompt,
                temperature=0.3,
                on_delta=on_delta,
            )
        else:
            llm_response = await self._call_llm(
                system_prompt=self.system_prompt,
                user_prompt=user_prompt,
                temperature=0.3
            )

        return llm_response.strip()

    async def rewrite_section_retry(
        self,
        section_name: str,
        original_content: str,
        previous_optimized: str,
        critique: str,
        suggestions: str,
        decoded_job: dict,
        goal: str,
        on_delta: Optional[Callable[[str], None]] = None,
    ) -> str:
        """
        当审计打分未达标时，结合上一次的改写稿、审计意见和具体建议进行针对性修改。

        Args:
            section_name (str): 简历模块名称。
            original_content (str): 原始段落内容。
            previous_optimized (str): 上一次被退回的改写稿。
            critique (str): 审计专家退回的理由/批注。
            suggestions (str): 具体的修改建议。
            decoded_job (dict): 岗位解码后的画像。
            goal (str): 优化目标。

        Returns:
            str: 再次优化后的段落文本。
        """
        self.reset_context(user_id="default", query="")

        user_prompt = f"""
你之前对简历段落进行了一次改写，但是未能通过审计。请根据审计反馈进行针对性的再次修改优化。

[待优化的简历段落名称]
{section_name}

[原始段落内容]
{original_content}

[上一次被退回的改写内容]
{previous_optimized}

[审计官的退回批注]
{critique}

[审计官的具体修改建议]
{suggestions}

[优化目标]
{goal}

[目标岗位画像]
{decoded_job}

请严格针对审计官指出的不足和修改建议进行更正，并遵守所有的改写规范。直接返回再次优化后的段落文本。
"""
        if on_delta:
            llm_response = await self._call_llm_stream(
                system_prompt=self.system_prompt,
                user_prompt=user_prompt,
                temperature=0.3,
                on_delta=on_delta,
            )
        else:
            llm_response = await self._call_llm(
                system_prompt=self.system_prompt,
                user_prompt=user_prompt,
                temperature=0.3
            )
        return llm_response.strip()
