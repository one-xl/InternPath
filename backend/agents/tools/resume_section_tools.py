from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from backend.agents.base import BaseAgent
from backend.agents.tools.workspace_tools import tool_read_file, tool_write_file
from backend.resume_rag import section_for_line


def _call_text_llm(openai_client: Any, model_id: str, messages: list[dict[str, Any]], temperature: float) -> str:
    mode = BaseAgent._normalize_stream_api_mode(
        getattr(openai_client, "_internpath_stream_api_mode", None)
    )
    if mode == "responses":
        response_args = BaseAgent._messages_to_responses_args(messages)
        create_kwargs = {
            "model": model_id,
            "temperature": temperature,
            "input": response_args["input"],
        }
        if response_args["instructions"]:
            create_kwargs["instructions"] = response_args["instructions"]
        BaseAgent._apply_responses_prompt_cache(
            create_kwargs,
            openai_client,
            model=model_id,
            namespace="resume_section_tools",
        )
        return BaseAgent._collect_responses_stream_sync(
            openai_client,
            create_kwargs,
            model=model_id,
            namespace="resume_section_tools",
        )

    BaseAgent._clear_provider_cache_usage(openai_client)
    BaseAgent._remember_provider_request(
        openai_client,
        endpoint_mode="chat_completions",
        stream=False,
        model=model_id,
        namespace="resume_section_tools",
    )
    response = openai_client.chat.completions.create(
        model=model_id,
        messages=messages,
        temperature=temperature,
    )
    BaseAgent._remember_provider_cache_usage(openai_client, response)
    return BaseAgent._extract_stream_delta(response)


def tool_analyze_gap(openai_client: Any, model_id: str, resume_text: str, jd_text: str) -> str:
    """使用大模型进行 GAP 深度差距分析。"""
    prompt = f"""
你是一位资深的职业发展专家和简历分析师。请对比以下“原始简历”与“目标职位描述 (JD)”，进行深度的 GAP 差距分析：
1. 本次投递的主要差距（简历中缺乏的、但 JD 强烈要求的核心硬技能或软实力）。
2. 简历中哪些现有的项目或工作经历是与该岗位高度相关的，需要进一步重点改写突出。
3. 给出一个简历优化的整体策略和修改大纲。
4. 必须输出一个"修改优先级表"，格式为：
   | 段落名 | 修改紧迫度(高/中/低) | 修改方向 | 预期效果 |
   其中段落名必须与 extract_resume_sections 输出的 section_name 严格对应。

[原始简历]
{resume_text}

[目标职位描述 (JD)]
{jd_text}

请给出一份结构清晰的分析报告。
"""
    try:
        return _call_text_llm(
            openai_client,
            model_id,
            [
                {"role": "system", "content": "你是一个严谨的简历 GAP 分析助手。请只输出客观的分析报告，不要有多余的废话。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        ) or "未能生成差距分析。"
    except Exception as exc:
        return f"GAP 分析调用大模型失败：{str(exc)}"


def tool_rewrite_section(
    openai_client: Any,
    model_id: str,
    section_name: str,
    original_content: str,
    improvement_goal: str,
    jd_text: str,
) -> str:
    """使用大模型和 STAR 原则优化简历特定段落。"""
    prompt = f"""
你是一位精通简历修改的专家。请针对简历的特定模块“{section_name}”进行重写优化。

优化要求：
1. 目标职位JD：
---
{jd_text}
---
2. 修改目标：{improvement_goal}
3. 优化原则：
   - 尽量采用 STAR 原则（情境 Situation、任务 Task、行动 Action、结果 Result）组织语言。
   - 突出具体的数据（如提升百分比、具体金额、吞吐量等） and 使用到的核心专业技术词汇（与JD呼应）。
   - 必须保持真实度，严禁在不了解原事实的情况下编造不存在的大型项目或夸大核心角色（例如把普通前端改为架构师）。
4. 结构保留原则：
   - 你必须以原始段落的内容和结构为基础进行润色，严禁重新组织段落结构
   - 如果原始段落包含多个子项（如多个项目），你必须保留所有子项，只允许对每个子项的描述进行优化
   - 输出的段落格式（如 bullet point、编号列表）必须与原始段落一致
   - 原始段落中的日期、公司名、学校名、职位名等事实信息必须原样保留

[原始段落内容]
{original_content}

请输出润色重构后的完美段落。
"""
    try:
        return _call_text_llm(
            openai_client,
            model_id,
            [
                {"role": "system", "content": "你是一个精通简历修改的助手。请直接输出优化后的段落文本，不需要解释你的修改过程。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
        ) or "改写失败。"
    except Exception as exc:
        return f"改写段落大模型调用失败：{str(exc)}"


def tool_rewrite_section_retry(
    openai_client: Any,
    model_id: str,
    section_name: str,
    original_content: str,
    previous_optimized: str,
    critique: str,
    suggestions: str,
    improvement_goal: str,
    jd_text: str,
) -> str:
    """
    当 HR 审计打分不合格时，结合上一次的改写稿以及 HR 审计官的批注与修改建议重写。
    """
    prompt = f"""
你是一位精通简历修改的专家。你之前对简历模块“{section_name}”进行了一次改写，但被 HR 专家审计官退回了，因为审计结果未达标。

请结合以下反馈，进行有针对性的再次改写与优化：

1. 目标职位JD：
---
{jd_text}
---
2. 修改目标：{improvement_goal}
3. 原始简历段落（必须以此为事实基础，绝对不能编造）：
---
{original_content}
---
4. 上一次被退回的改写稿：
---
{previous_optimized}
---
5. HR 专家审计官的退回批注：
> {critique}
6. HR 专家审计官的具体修改建议：
> {suggestions}

改写原则：
- 严格遵循并修正 HR 审计官指出的不足，采纳其修改建议。
- 尽量采用简历专业改写规范，突出可量化的成果（如果确实无法量化，可突出职责贡献）。
- 绝对禁止捏造不存在的技术框架、不属实的数据或虚构大型项目。
- 段落结构与原始简历一致，保留所有日期、公司名等基础事实信息。

请输出针对性修改优化后的完美段落文本。
"""
    try:
        return _call_text_llm(
            openai_client,
            model_id,
            [
                {"role": "system", "content": "你是一个精通简历修改的助手。请直接输出针对反馈优化后的段落文本，不需要任何解释。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
        ) or "重试改写失败。"
    except Exception as exc:
        return f"重试改写大模型调用失败：{str(exc)}"


def tool_extract_resume_sections(resume_text: str) -> str:
    lines = resume_text.splitlines()
    sections_list = []
    current_section = "其他"
    current_lines = []
    line_start = 1

    for i, line in enumerate(lines):
        heading = section_for_line(line)
        if heading:
            if current_lines or current_section != "其他":
                if current_lines:
                    sections_list.append({
                        "section_name": current_section,
                        "content": "\n".join(current_lines),
                        "line_start": line_start,
                        "line_end": i,
                        "index": len(sections_list),
                    })
                current_section = heading
                current_lines = [line]
                line_start = i + 1
            else:
                current_section = heading
                current_lines = [line]
                line_start = i + 1
        else:
            current_lines.append(line)

    if current_lines:
        sections_list.append({
            "section_name": current_section,
            "content": "\n".join(current_lines),
            "line_start": line_start,
            "line_end": len(lines),
            "index": len(sections_list),
        })

    return json.dumps(sections_list, ensure_ascii=False)


def tool_replace_resume_section(
    user_id: Any,
    task_id: str,
    section_index: int,
    new_content: str,
    reason: str = "根据岗位需求进行优化",
) -> str:
    try:
        sections_json = tool_read_file(user_id, task_id, "resume_sections.json")
        if "错误：" in sections_json:
            return "错误：未找到 resume_sections.json，请先执行 extract_resume_sections 并保存。"

        sections = json.loads(sections_json)
        if section_index < 0 or section_index >= len(sections):
            return f"错误：无效的段落索引 {section_index}，有效范围是 0 到 {len(sections) - 1}。"

        target_section = sections[section_index]
        original_content = target_section.get("content", "")
        section_name = target_section.get("section_name", "未知段落")
        target_section["content"] = new_content

        write_status = tool_write_file(user_id, task_id, "resume_sections.json", json.dumps(sections, ensure_ascii=False))
        if "错误" in write_status:
            return f"错误：写入 resume_sections.json 失败: {write_status}"

        log_json = tool_read_file(user_id, task_id, "modification_log.json")
        if "错误：" in log_json:
            mod_logs = []
        else:
            try:
                mod_logs = json.loads(log_json)
            except Exception:
                mod_logs = []

        mod_logs.append({
            "section_name": section_name,
            "section_index": section_index,
            "original": original_content,
            "new": new_content,
            "timestamp": datetime.now().isoformat(),
            "reason": reason,
        })

        write_log_status = tool_write_file(user_id, task_id, "modification_log.json", json.dumps(mod_logs, ensure_ascii=False))
        if "错误" in write_log_status:
            return f"错误：写入 modification_log.json 失败: {write_log_status}"

        assembled_content = "\n".join(sec.get("content", "") for sec in sections)
        write_assembled_status = tool_write_file(user_id, task_id, "assembled_resume.txt", assembled_content)
        if "错误" in write_assembled_status:
            return f"错误：写入 assembled_resume.txt 失败: {write_assembled_status}"
        write_preview_status = tool_write_file(user_id, task_id, "stream_preview.md", assembled_content)
        if "错误" in write_preview_status:
            return f"错误：写入 stream_preview.md 失败: {write_preview_status}"

        return f"成功：已替换段落「{section_name}」(index={section_index})，assembled_resume.txt 与 stream_preview.md 已更新"
    except Exception as e:
        return f"替换段落失败：{str(e)}"


def tool_generate_modification_diff(user_id: Any, task_id: str) -> str:
    try:
        log_json = tool_read_file(user_id, task_id, "modification_log.json")
        if "错误：" in log_json:
            return "错误：未找到 modification_log.json，没有修改记录。"

        mod_logs = json.loads(log_json)
        if not mod_logs:
            return "没有记录到任何修改。"

        md_lines = [
            "# 简历修改对照表 (Modification Diff)\n",
            f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
        ]

        for item in mod_logs:
            sec_name = item.get("section_name", "未知模块")
            reason = item.get("reason", "无")
            orig_text = item.get("original", "")
            new_text = item.get("new", "")

            md_lines.append(f"## 模块: {sec_name}")
            md_lines.append(f"**修改理由**: {reason}\n")
            md_lines.append("### 原始文本")
            md_lines.append("```text")
            md_lines.append(orig_text.strip() if orig_text else "")
            md_lines.append("```\n")
            md_lines.append("### 修改后文本")
            md_lines.append("```text")
            md_lines.append(new_text.strip() if new_text else "")
            md_lines.append("```\n")
            md_lines.append("---")

        diff_content = "\n".join(md_lines)
        tool_write_file(user_id, task_id, "modification_diff.md", diff_content)
        return diff_content
    except Exception as e:
        return f"生成修改对照表失败：{str(e)}"
