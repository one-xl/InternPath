import json
import re
import asyncio
from typing import Any, Dict, List
from backend.agents.tools.resume_section_tools import tool_extract_resume_sections
from backend.agents.schemas import ExecutionPlanOutput, parse_json_model

class AgentPlanner:
    """
    动态执行计划生成器，负责分析简历和 JD 的差距，并为需要优化的简历段落制定结构化的执行计划。
    """
    async def generate_plan(
        self,
        resume_text: str,
        jd_text: str,
        openai_client: Any,
        model_id: str
    ) -> dict:
        """
        根据简历文本和岗位 JD 文本，通过大模型生成简历优化计划。

        Args:
            resume_text (str): 原始简历文本。
            jd_text (str): 目标岗位描述文本。
            openai_client (Any): OpenAI 客户端实例。
            model_id (str): 使用的 LLM 模型 ID。

        Returns:
            dict: 结构化的执行计划，格式为 {"steps": [...]}。
        """
        # 1. 提取简历的结构化段落
        sections_str = tool_extract_resume_sections(resume_text)
        sections = json.loads(sections_str)

        # 2. 构造大模型 Prompt，展现当前简历中已解析的所有段落
        sections_formatted = "\n\n".join(
            f"段落索引: {s['index']}\n段落名称: {s['section_name']}\n原始内容:\n{s['content']}"
            for s in sections
        )

        prompt = f"""
你是一位资深的职业规划专家和简历优化大师。请分析以下“简历段落”与“目标岗位描述 (JD)”之间的差距，并针对需要优化的简历段落制定一个精细化的“简历优化执行计划”。

[简历段落]
{sections_formatted}

[目标岗位描述 (JD)]
{jd_text}

请严格根据简历段落中的内容和 JD 进行对比分析，找出那些与目标岗位要求不匹配、或者可以通过改写更好地匹配 JD 要求的段落。
针对这些需要改进的段落，生成一个 JSON 格式的执行计划。

JSON 格式要求如下：
{{
  "steps": [
    {{
      "step_index": 1,
      "section_index": 0,
      "section_name": "段落名称（必须严格对应上面给出的段落名称之一）",
      "original_content": "该段落的原始文本内容",
      "improvement_goal": "针对该段落的改进目标和优化方向，阐述如何改写以匹配 JD 里的核心要求（例如：补充高并发、微服务治理或可量化指标等）",
      "status": "PENDING"
    }}
  ]
}}

注意事项：
1. 计划中的 `section_name` 必须从上述提供的简历段落名称（如：教育经历、项目经历、专业技能、自我评价、其他等）中选择，且拼写必须完全一致。
2. `section_index` 必须严格使用上文给出的段落索引，不能自行编造。
3. `step_index` 必须从 1 开始递增。
4. 如果某些段落（例如联系方式、教育经历）已经非常完善或主要是客观事实，则不需要在 `steps` 中为它们创建步骤。只为需要修改的段落生成步骤。
5. 改进目标只能要求“突出、重排、精炼、强调原文已有事实”，不得要求补充原文或用户补充中不存在的数字、公司、学校、职位、系统规模或技术栈。
6. 必须仅返回合法的 JSON 文本，不需要任何 markdown 包裹（如 ```json），也不要包含任何额外的解释或废话。
"""

        try:
            # 异步调用大模型
            response = await asyncio.to_thread(
                openai_client.chat.completions.create,
                model=model_id,
                messages=[
                    {"role": "system", "content": "你是一个只输出 JSON 格式执行计划的简历分析助手。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2
            )
            raw_content = response.choices[0].message.content or ""
        except Exception as exc:
            raise RuntimeError(f"生成简历优化计划失败: {exc}") from exc

        return self._parse_json_plan(raw_content, sections)

    def _parse_json_plan(self, raw_text: str, sections: list) -> dict:
        """
        解析大模型返回的 JSON 计划，并进行合法性校验。
        """
        clean_text = raw_text.strip()

        # 剥离 markdown 标记
        if clean_text.startswith("```"):
            clean_text = re.sub(r"^```(?:json)?\n", "", clean_text)
            clean_text = re.sub(r"\n```$", "", clean_text)
            clean_text = clean_text.strip()

        plan_model = parse_json_model(clean_text, ExecutionPlanOutput, "简历优化执行计划")
        if not plan_model.steps:
            return {"steps": []}

        # 校验 steps 中每个 section_index/section_name 是否在简历中。
        # section_index 是主键，避免多个“项目经历”段落同名时替换错位。
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
                "status": step.status
            })

        if not validated_steps:
            raise ValueError("大模型返回的简历优化计划没有匹配到任何有效简历段落。")

        return {"steps": validated_steps}
