from __future__ import annotations

from typing import Any

from backend.agents.base import BaseAgent
from backend.resume_advisor.verification import verify_suggestion_facts


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
            namespace="hallucination_tools",
        )
        return BaseAgent._collect_responses_stream_sync(
            openai_client,
            create_kwargs,
            model=model_id,
            namespace="hallucination_tools",
        )

    BaseAgent._clear_provider_cache_usage(openai_client)
    BaseAgent._remember_provider_request(
        openai_client,
        endpoint_mode="chat_completions",
        stream=False,
        model=model_id,
        namespace="hallucination_tools",
    )
    response = openai_client.chat.completions.create(
        model=model_id,
        messages=messages,
        temperature=temperature,
    )
    BaseAgent._remember_provider_cache_usage(openai_client, response)
    return BaseAgent._extract_stream_delta(response)


def tool_verify_anti_hallucination(openai_client: Any, model_id: str, original_content: str, optimized_content: str) -> str:
    prompt = f"""
请扮演一个严格的“简历幻觉审查专家”。对比以下“原始简历段落”和“优化后简历段落”，审查优化后段落是否存在以下幻觉/不实捏造问题：
1. 捏造了原段落中完全没有的专业技能、工具、框架（尤其是没有在JD中提及的、但被AI凭空捏造出来的）。
2. 夸大了在项目中的职责和贡献（例如原句是“参与开发”，优化后变成了“主导/负责设计架构”）。
3. 凭空虚构了具体量化的成果数据（如“性能提升50%”、“带来100万营收”等，原句没有任何量化指标）。

[原始简历段落]
{original_content}

[优化后简历段落]
{optimized_content}

请给出审查结论，按以下格式输出：
判断：
- 是否存在幻觉风险：[是/否]
- 风险严重程度：[无/低/中/高]
- 修改建议：[说明为什么有幻觉，应如何修正；如果无，写无]
"""
    try:
        return _call_text_llm(
            openai_client,
            model_id,
            [
                {"role": "system", "content": "你是一个严格的简历幻觉审查助手。请给出结构化审查结论，不要有多余的废话。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
        ) or "幻觉验证失败。"
    except Exception as e:
        return f"幻觉审查大模型调用失败：{str(e)}"


def check_resume_fact_integrity(
    original_content: str,
    optimized_content: str,
    evidence_text: str = "",
) -> dict[str, Any]:
    result = verify_suggestion_facts(
        original_text=original_content or "",
        proposed_text=optimized_content or "",
        resume_evidence_texts=[evidence_text] if evidence_text else [],
    )
    legacy_labels = {
        "quantitative": "新增量化指标",
        "date": "新增日期",
        "organization": "新增机构名称",
    }
    issues = [
        f"{legacy_labels[issue.category]}: {issue.claim}" if issue.category in legacy_labels else issue.message
        for issue in result.fact_issues
    ]
    return {
        "ok": result.is_supported,
        "issues": issues,
        "message": "；".join(issues),
        "status": result.status,
        "factIssues": [issue.model_dump() for issue in result.fact_issues],
    }
