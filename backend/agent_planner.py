import asyncio
import json
import re
from typing import Any

from backend.agents.base import BaseAgent
from backend.agents.schemas import ExecutionPlanOutput, parse_json_model
from backend.agents.tools.resume_section_tools import tool_extract_resume_sections


class AgentPlanner:
    """
    Dynamic execution-plan generator for resume optimization.
    """

    async def generate_plan(
        self,
        resume_text: str,
        jd_text: str,
        openai_client: Any,
        model_id: str,
        context_text: str = "",
    ) -> dict:
        sections_str = tool_extract_resume_sections(resume_text)
        sections = json.loads(sections_str)

        sections_formatted = "\n\n".join(
            (
                f"段落索引: {s['index']}\n"
                f"段落名称: {s['section_name']}\n"
                f"原始内容:\n{s['content']}"
            )
            for s in sections
        )

        prompt = f"""
你是一位资深职业规划专家和简历优化专家。请分析以下“简历段落”与“目标岗位描述(JD)”之间的差距，并针对需要优化的简历段落制定结构化执行计划。

[简历段落]
{sections_formatted}

[目标岗位描述(JD)]
{jd_text}

{f"[已确认的用户偏好与上下文]\n{context_text}\n" if context_text.strip() else ""}

请严格根据简历段落中的内容和 JD 进行对比分析，只为需要修改的段落生成步骤。
必须返回合法 JSON，不要使用 markdown 代码块，不要输出任何解释。

JSON 格式如下：
{{
  "steps": [
    {{
      "step_index": 1,
      "section_index": 0,
      "section_name": "必须严格对应上方给出的段落名称之一",
      "original_content": "该段落的原始文本内容",
      "improvement_goal": "针对该段落的改进目标和优化方向",
      "requires_human_input": false,
      "human_question": "",
      "status": "PENDING"
    }}
  ]
}}

规则：
1. section_name 必须从上方段落名称中选择，section_index 必须使用上方给出的索引。
2. 只为确实需要修改的段落生成步骤；联系方式、教育经历等客观事实若已完善，不要生成步骤。
3. 改进目标只能要求突出、重排、精炼或强调原文已有事实，不得要求补充原文或用户补充中不存在的数字、公司、学校、职位、系统规模或技术栈。
4. 只有当段落缺少完成 JD 匹配所必需的真实经历、职责细节或可量化证据，且无法从原简历或 JD 合理确认时，requires_human_input 才能为 true。
5. 如果可以仅基于原简历已有事实安全改写，requires_human_input 必须为 false，human_question 必须为空字符串。
"""

        messages = [
            {"role": "system", "content": "你是一个只输出 JSON 格式执行计划的简历分析助手。"},
            {"role": "user", "content": prompt},
        ]

        try:
            mode = BaseAgent._normalize_stream_api_mode(
                getattr(openai_client, "_internpath_stream_api_mode", None)
            )
            if mode == "responses":
                response_args = BaseAgent._messages_to_responses_args(messages)
                create_kwargs = {
                    "model": model_id,
                    "temperature": 0.2,
                    "input": response_args["input"],
                }
                if response_args["instructions"]:
                    create_kwargs["instructions"] = response_args["instructions"]
                BaseAgent._apply_responses_prompt_cache(
                    create_kwargs,
                    openai_client,
                    model=model_id,
                    namespace="agent_planner",
                )
                raw_content = await asyncio.to_thread(
                    BaseAgent._collect_responses_stream_sync,
                    openai_client,
                    create_kwargs,
                    model=model_id,
                    namespace="agent_planner",
                )
            else:
                BaseAgent._clear_provider_cache_usage(openai_client)
                BaseAgent._remember_provider_request(
                    openai_client,
                    endpoint_mode="chat_completions",
                    stream=False,
                    model=model_id,
                    namespace="agent_planner",
                )
                response = await asyncio.to_thread(
                    openai_client.chat.completions.create,
                    model=model_id,
                    messages=messages,
                    temperature=0.2,
                )
                BaseAgent._remember_provider_cache_usage(openai_client, response)
                raw_content = BaseAgent._extract_stream_delta(response)
        except Exception as exc:
            raise RuntimeError(f"生成简历优化计划失败: {exc}") from exc

        return self._parse_json_plan(raw_content, sections)

    def _parse_json_plan(self, raw_text: str, sections: list) -> dict:
        clean_text = raw_text.strip()

        if clean_text.startswith("```"):
            clean_text = re.sub(r"^```(?:json)?\n", "", clean_text)
            clean_text = re.sub(r"\n```$", "", clean_text)
            clean_text = clean_text.strip()

        plan_model = parse_json_model(clean_text, ExecutionPlanOutput, "简历优化执行计划")
        if not plan_model.steps:
            return {"steps": []}

        sections_by_index = {s["index"]: s for s in sections}
        validated_steps = []
        for step in plan_model.steps:
            orig_sec = sections_by_index.get(step.section_index)
            if orig_sec is None:
                raise ValueError(f"大模型返回了不存在的 section_index: {step.section_index}")
            if step.section_name != orig_sec["section_name"]:
                raise ValueError(
                    f"执行计划 section_name 与 section_index 不一致: {step.section_name} != {orig_sec['section_name']}"
                )

            validated_steps.append({
                "step_index": len(validated_steps) + 1,
                "section_index": orig_sec["index"],
                "section_name": orig_sec["section_name"],
                "original_content": orig_sec["content"],
                "improvement_goal": step.improvement_goal,
                "requires_human_input": step.requires_human_input,
                "human_question": step.human_question.strip() if step.requires_human_input else "",
                "status": step.status,
            })

        if not validated_steps:
            raise ValueError("大模型返回的简历优化计划没有匹配到任何有效简历段落。")

        return {"steps": validated_steps}
