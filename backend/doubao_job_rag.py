from __future__ import annotations

import json
import re
from typing import Any

import httpx
from openai import APIConnectionError, APITimeoutError, AuthenticationError, OpenAI

from config import Config


PLACEHOLDER_KEYS = {"", "your_api_key_here", "your_deepseek_or_openai_api_key_here", "your_doubao_api_key_here"}


class DoubaoAnalysisError(RuntimeError):
    """Raised when the LLM analysis cannot be completed."""


def strip_json_fence(text: str) -> str:
    value = text.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s*```\s*$", "", value)
    return value.strip()


def llm_client() -> OpenAI:
    api_key = (Config.LLM_API_KEY or "").strip()
    if api_key.lower() in PLACEHOLDER_KEYS:
        raise DoubaoAnalysisError("未配置有效的 LLM_API_KEY，请在项目根目录 .env 中配置 Doubao API Key 后重启服务")
    timeout = httpx.Timeout(Config.LLM_TIMEOUT, connect=min(30.0, float(Config.LLM_TIMEOUT)))
    return OpenAI(
        api_key=api_key,
        base_url=Config.LLM_BASE_URL,
        http_client=httpx.Client(timeout=timeout),
    )


def clamp_score(value: Any, default: int = 50) -> int:
    try:
        score = int(round(float(value)))
    except (TypeError, ValueError):
        score = default
    return max(0, min(100, score))


def decision_from_score(score: int) -> str:
    if score >= 85:
        return "strong_yes"
    if score >= 70:
        return "yes"
    if score >= 50:
        return "maybe"
    return "no"


def risk_from_score(score: int) -> str:
    if score >= 75:
        return "low"
    if score >= 50:
        return "medium"
    return "high"


def priority_from_score(score: int) -> str:
    if score >= 85:
        return "P0"
    if score >= 70:
        return "P1"
    if score >= 50:
        return "P2"
    return "P3"


def as_string_list(value: Any, limit: int = 8) -> list[str]:
    if not isinstance(value, list):
        return []
    out = [str(item).strip() for item in value if str(item).strip()]
    return out[:limit]


def normalize_dimension(item: dict[str, Any], index: int) -> dict[str, Any]:
    label = str(item.get("label") or item.get("id") or f"匹配维度 {index + 1}").strip()
    return {
        "id": str(item.get("id") or label),
        "label": label,
        "score": clamp_score(item.get("score"), 50),
        "tags": as_string_list(item.get("tags"), 8),
        "explanation": str(item.get("explanation") or "模型未给出解释").strip(),
    }


def normalize_advice(item: dict[str, Any], index: int) -> dict[str, Any]:
    priority = str(item.get("priority") or "medium")
    if priority not in {"high", "medium", "low"}:
        priority = "medium"
    return {
        "id": str(item.get("id") or f"advice-{index}"),
        "priority": priority,
        "issue": str(item.get("issue") or "简历表达需要更贴近 JD").strip(),
        "suggestion": str(item.get("suggestion") or "基于已检索到的经历重写，不要新增未发生的经历。").strip(),
        "example": str(item.get("example") or "请补充可验证的动作、技术栈和结果指标。").strip(),
        "impact": str(item.get("impact") or "提升筛选通过率和面试追问质量。").strip(),
    }


def normalize_learning(item: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "id": str(item.get("id") or f"learning-{index}"),
        "skill": str(item.get("skill") or "项目表达").strip(),
        "order": int(item.get("order") or index + 1),
        "estimatedTime": str(item.get("estimatedTime") or item.get("estimated_time") or "2-3 天").strip(),
        "practiceDirection": str(item.get("practiceDirection") or item.get("practice_direction") or "围绕缺口做一个可展示的小练习。").strip(),
        "interviewFocus": str(item.get("interviewFocus") or item.get("interview_focus") or "准备场景、方案、取舍和结果。").strip(),
    }


def normalize_llm_result(raw: dict[str, Any]) -> dict[str, Any]:
    score = clamp_score(raw.get("matchScore", raw.get("match_score", 50)), 50)
    decision = str(raw.get("decision") or decision_from_score(score))
    if decision not in {"strong_yes", "yes", "maybe", "no"}:
        decision = decision_from_score(score)
    risk_level = str(raw.get("riskLevel") or raw.get("risk_level") or risk_from_score(score))
    if risk_level not in {"low", "medium", "high"}:
        risk_level = risk_from_score(score)
    priority = str(raw.get("priority") or priority_from_score(score))
    if priority not in {"P0", "P1", "P2", "P3"}:
        priority = priority_from_score(score)

    dimensions = raw.get("dimensions")
    if not isinstance(dimensions, list):
        dimensions = []
    advice = raw.get("resumeAdvice") or raw.get("resume_advice")
    if not isinstance(advice, list):
        advice = []
    learning = raw.get("learningSuggestions") or raw.get("learning_suggestions")
    if not isinstance(learning, list):
        learning = []

    return {
        "decision": decision,
        "matchScore": score,
        "riskLevel": risk_level,
        "priority": priority,
        "oneLineReason": str(raw.get("oneLineReason") or raw.get("one_line_reason") or "模型已基于 JD 和检索片段完成判断。").strip(),
        "detectedKeywords": as_string_list(raw.get("detectedKeywords") or raw.get("detected_keywords"), 12),
        "missingKeywords": as_string_list(raw.get("missingKeywords") or raw.get("missing_keywords"), 12),
        "dimensions": [normalize_dimension(item, index) for index, item in enumerate(dimensions[:8]) if isinstance(item, dict)],
        "resumeAdvice": [normalize_advice(item, index) for index, item in enumerate(advice[:8]) if isinstance(item, dict)],
        "learningSuggestions": [normalize_learning(item, index) for index, item in enumerate(learning[:8]) if isinstance(item, dict)],
        "nextActions": as_string_list(raw.get("nextActions") or raw.get("next_actions"), 7),
    }


def build_system_prompt() -> str:
    return """
你是一个严格、务实的个人求职决策助手。你要基于 JD 和 RAG 检索到的简历片段，判断这个岗位是否值得投，并给出可执行的简历改造建议。

重要约束：
1. 只能基于提供的简历片段、解析出的技能/项目/教育概要做判断。
2. 不要编造候选人没有的经历。
3. 简历改写必须引用、改写或强化已有经历，不能凭空新增项目。
4. 对没有证据的能力，要放入 missingKeywords 或 resumeAdvice.issue。
5. 输出必须是合法 JSON，不要 Markdown，不要解释性前后缀。

字段要求：
{
  "decision": "strong_yes | yes | maybe | no",
  "matchScore": 0-100,
  "riskLevel": "low | medium | high",
  "priority": "P0 | P1 | P2 | P3",
  "oneLineReason": "一句话说明是否值得投",
  "detectedKeywords": ["JD 中识别出的关键词"],
  "missingKeywords": ["简历证据不足的关键词"],
  "dimensions": [
    {"id": "skills", "label": "技能匹配", "score": 0-100, "tags": ["命中词"], "explanation": "简短解释"}
  ],
  "resumeAdvice": [
    {"id": "xxx", "priority": "high|medium|low", "issue": "当前问题", "suggestion": "修改建议", "example": "可直接使用的简历表达", "impact": "影响程度"}
  ],
  "learningSuggestions": [
    {"id": "xxx", "skill": "技能", "order": 1, "estimatedTime": "2-3 天", "practiceDirection": "练习方向", "interviewFocus": "面试准备重点"}
  ],
  "nextActions": ["3-7 条下一步行动"]
}
"""


def analyze_job_with_doubao(
    payload: dict[str, Any],
    user_id: Optional[Any] = None,
    config_id: Optional[str] = None
) -> dict[str, Any]:
    from ai_analyzer import AIAnalyzer
    analyzer = AIAnalyzer()
    client, resolved_config_id, provider, model_id = analyzer._client(user_id, config_id)

    compact_payload = {
        "jdText": payload.get("jdText", ""),
        "targetType": payload.get("targetType", ""),
        "jobDirection": payload.get("jobDirection", ""),
        "draft": payload.get("draft") or {},
        "resumeFile": payload.get("resumeFile") or {},
        "retrievalSummary": payload.get("retrievalSummary", ""),
        "retrievedChunks": [
            {
                "id": chunk.get("id"),
                "section": chunk.get("section"),
                "score": chunk.get("score"),
                "keywords": chunk.get("keywords") or [],
                "content": chunk.get("content"),
            }
            for chunk in (payload.get("retrievedChunks") or [])[:8]
            if isinstance(chunk, dict)
        ],
        "extractedProfile": (payload.get("parsedResume") or {}).get("extractedProfile") or {},
    }

    try:
        response = client.chat.completions.create(
            model=model_id,
            messages=[
                {"role": "system", "content": build_system_prompt()},
                {"role": "user", "content": json.dumps(compact_payload, ensure_ascii=False)},
            ],
            temperature=0.2,
        )
        content = strip_json_fence(response.choices[0].message.content or "")
        return normalize_llm_result(json.loads(content))
    except APIConnectionError as exc:
        raise DoubaoAnalysisError(f"无法连接大模型服务，请检查网络、代理和配置：{exc}") from exc
    except APITimeoutError as exc:
        raise DoubaoAnalysisError(f"大模型请求超时（当前 {Config.LLM_TIMEOUT}s）：{exc}") from exc
    except AuthenticationError as exc:
        raise DoubaoAnalysisError(f"大模型 API Key 无效或未授权：{exc}") from exc
    except json.JSONDecodeError as exc:
        raise DoubaoAnalysisError(f"大模型返回内容不是合法 JSON：{exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise DoubaoAnalysisError(f"大模型分析失败：{exc}") from exc

