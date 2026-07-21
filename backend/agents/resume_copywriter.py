import json
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
            "1. 证据优先：JD 只能决定侧重点，不能证明候选人拥有任何技能、数字、职责或结果；无证据时不得补写。\n"
            "2. 使用与原文职责强度一致的专业词汇和行为动词，不能将协助写成主导。\n"
            "3. 绝对保持事实的真实性，不能虚构、捏造经历中没有的公司名称、学校名称、时间、技术栈、指标或架构。\n"
            "4. 结构保留原则：必须保留原段落的时间、项目名称、基本骨架和各项的顺序，仅对具体描述内容进行精细重构润色。\n"
            "5. 请直接输出润色后的简历段落，不要包含任何多余的开场白、解释或总结。"
        )

    @staticmethod
    def _parse_json_object(value: str) -> dict[str, Any]:
        """Parse one model-produced JSON object without inventing missing fields."""
        raw = str(value or "").strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else ""
            raw = raw.rsplit("```", 1)[0].strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("{")
            if start < 0:
                raise ValueError("ResumeCopywriter did not return a JSON object")
            try:
                parsed, _ = json.JSONDecoder().raw_decode(raw[start:])
            except json.JSONDecodeError as exc:
                raise ValueError("ResumeCopywriter returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("ResumeCopywriter JSON response must be an object")
        return parsed

    async def generate_advisor_suggestion(
        self,
        *,
        section_name: str,
        original_content: str,
        jd_requirements: list[str],
        revision_feedback: str = "",
        context_snapshot: str = "",
        user_id: str = "default",
        preference_rules: Optional[list[str]] = None,
        on_delta: Optional[Callable[[str], None]] = None,
    ) -> dict[str, Any]:
        """Generate the complete candidate-visible suggestion as a JSON contract."""
        self.reset_context(user_id=user_id, query="")
        preferences = [str(item).strip() for item in (preference_rules or []) if str(item).strip()]
        preference_text = "\n".join(f"- {item}" for item in preferences)
        system_prompt = (
            f"{self.system_prompt}\n\n"
            "[Resume Advisor 结构化输出契约]\n"
            "只根据给定原文、已确认事实和 RAG 检索到的同份简历证据生成一条简历建议。"
            "JD 只能决定侧重点，不能证明候选人拥有任何技能、职责、数字或结果。"
            "不得编造或强化原文没有的候选人事实，也不得把协助改写为主导。"
            "必须只输出一个 JSON 对象，不要输出 Markdown 或额外说明。"
            "JSON 必须包含 outcome、proposed_text、issue、rationale、expected_impact、priority、affirmation、highlight_locations；"
            "outcome 只能是 revision 或 affirmation，priority 只能是 high、medium 或 low。"
            "若现有表述已足够贴合 JD，不要为了改写而改写：outcome 设为 affirmation，"
            "proposed_text 为空，affirmation 用自然中文指出做得好的地方并在正文写明人类可读位置。"
            "若需要修改，outcome 设为 revision，affirmation 为空，且 proposed_text 为可直接粘贴的简历文本。"
        )
        user_prompt = (
            f"[简历段落]\n{section_name}\n\n"
            f"[原文]\n{original_content}\n\n"
            f"[JD 侧重点]\n{json.dumps(jd_requirements, ensure_ascii=False)}\n\n"
            f"[本轮修订要求]\n{revision_feedback.strip()}\n\n"
            f"[已压缩上下文]\n{context_snapshot.strip()}\n\n"
            f"[用户偏好]\n{preference_text}"
        )
        # A proposal remains quarantined until fact verification and HRCritic approve it.
        # Do not stream the JSON envelope or its candidate-visible proposed_text.
        response = await self._call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.2,
        )
        structured = self._parse_json_object(response)
        return structured

    async def request_advisor_evidence(
        self,
        *,
        location: str,
        original_content: str,
        proposed_content: str,
        unsupported_claims: list[str],
        retrieved_evidence: list[str],
        user_id: str = "default",
    ) -> str:
        """Ask one natural-language clarification when the fact gate rejects a draft."""
        self.reset_context(user_id=user_id, query="")
        evidence = "\n".join(f"- {item}" for item in retrieved_evidence if str(item).strip())
        claims = "、".join(item for item in unsupported_claims if item.strip())
        system_prompt = (
            f"{self.system_prompt}\n\n"
            "你正在与用户对话。请根据给定的简历证据和待确认声明，用一到两句自然、简洁的中文提问。"
            "不要展示内部 block ID、规则、分数、工具、RAG、模型或系统流程；不要列出表单字段。"
            "说明需要确认的事实与人类可读的简历位置，并允许用户直接在聊天输入框回答或说明没有该经历。"
        )
        user_prompt = (
            f"[简历位置]\n{location}\n\n"
            f"[原文]\n{original_content}\n\n"
            f"[未通过核验的待改写文本]\n{proposed_content}\n\n"
            f"[需要确认的声明]\n{claims}\n\n"
            f"[RAG 检索到的简历证据]\n{evidence}"
        )
        response = await self._call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.2,
        )
        question = str(response or "").strip()
        if not question:
            raise ValueError("ResumeCopywriter returned an empty evidence question")
        return question

    async def explain_advisor_suggestion(
        self,
        *,
        user_question: str,
        location: str,
        original_content: str,
        proposed_content: str,
        confirmed_facts: Optional[list[str]] = None,
        user_id: str = "default",
    ) -> str:
        """Answer one suggestion follow-up using only the verified suggestion context."""
        self.reset_context(user_id=user_id, query="")
        fact_text = "\n".join(f"- {item}" for item in (confirmed_facts or []) if str(item).strip())
        system_prompt = (
            "你是简历顾问。只根据原文、已审核改写和已确认事实回答用户问题。"
            "用户问题只能决定回答角度，不能作为候选人事实或证据。"
            "不得补充、确认、暗示或推荐未出现在这些材料中的技能、技术、数字、职责、角色、结果或 JD 要求。"
            "不要把岗位要求当作候选人的经历。用自然、简洁的中文回答，不要提及模型、模板或内部流程。"
        )
        user_prompt = (
            f"[用户问题]\n{user_question}\n\n"
            f"[位置]\n{location}\n\n"
            f"[原文]\n{original_content}\n\n"
            f"[已审核改写]\n{proposed_content}\n\n"
            f"[已确认事实]\n{fact_text}"
        )
        response = await self._call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.2,
        )
        return str(response or "").strip()

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
