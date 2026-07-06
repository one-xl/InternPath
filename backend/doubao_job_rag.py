from __future__ import annotations

import json
import re
import hashlib
import threading
from typing import Any

import httpx
from openai import APIConnectionError, APITimeoutError, AuthenticationError, OpenAI

from config import Config


PLACEHOLDER_KEYS = {"", "your_api_key_here", "your_deepseek_or_openai_api_key_here", "your_doubao_api_key_here"}

_CACHE_LOCK = threading.RLock()
_DOUBAO_CACHE = {}

def _limit_cache_size(cache_dict: dict, max_size: int = 1000):
    with _CACHE_LOCK:
        if len(cache_dict) > max_size:
            try:
                oldest_key = next(iter(cache_dict))
                cache_dict.pop(oldest_key, None)
            except StopIteration:
                pass

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
    dimensions = raw.get("dimensions")
    if not isinstance(dimensions, list):
        dimensions = []

    # Extract the scores of 4 core dimensions (education, skills, projects, keywords)
    edu_score = 50
    skills_score = 50
    proj_score = 50
    kw_score = 50
    for dim in dimensions:
        if not isinstance(dim, dict):
            continue
        dim_id = str(dim.get("id")).strip()
        dim_score = clamp_score(dim.get("score"), 50)
        if dim_id == "education":
            edu_score = dim_score
        elif dim_id == "skills":
            skills_score = dim_score
        elif dim_id == "projects":
            proj_score = dim_score
        elif dim_id == "keywords":
            kw_score = dim_score

    # Calculate overall matchScore on backend (education: 30%, skills: 30%, projects: 30%, keywords: 10%)
    calculated_score = int(round(edu_score * 0.3 + skills_score * 0.3 + proj_score * 0.3 + kw_score * 0.1))
    # Apply hard constraint blocker cap (Scheme 1 rule)
    if edu_score <= 40:
        calculated_score = min(59, calculated_score)

    score = clamp_score(calculated_score, 50)
    decision = str(raw.get("decision") or decision_from_score(score))
    if decision not in {"strong_yes", "yes", "maybe", "no"}:
        decision = decision_from_score(score)
    risk_level = str(raw.get("riskLevel") or raw.get("risk_level") or risk_from_score(score))
    if risk_level not in {"low", "medium", "high"}:
        risk_level = risk_from_score(score)
    priority = str(raw.get("priority") or priority_from_score(score))
    if priority not in {"P0", "P1", "P2", "P3"}:
        priority = priority_from_score(score)

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

评分维度与细则（百分制，必须严格遵守以下标尺）：
1. "education" (学历背景, 权重 30%):
   - 完全契合学历、工作年限、毕业年限、地点等核心硬门槛：85 - 100 分。
   - 核心门槛严重不符（如学历不符、毕业年限错配，或明确要求全职但候选人只能兼职）：直接给 0 - 30 分。
2. "skills" (技能匹配, 权重 30%):
   - 技术栈与 JD 核心要求完全匹配且有检索到的简历证据：85 - 100 分。
   - 掌握主要技能的 50% - 80% 或有相似技术栈：60 - 84 分。
   - 缺失岗位最基础或最核心的技术（如投前端但完全不会 React/Vue/JS）：0 - 59 分。
3. "projects" (项目经历, 权重 30%):
   - 有 1 个或多个高度相似的业务或职责项目背景：85 - 100 分。
   - 技术栈重合，但业务场景或项目深度偏离较大：60 - 84 分。
   - 纯转行、无任何相关实习或项目经验：0 - 59 分。
4. "keywords" (关键词覆盖, 权重 10%):
   - 完全涵盖核心关键词：85 - 100 分。
   - 覆盖中等：60 - 84 分。
   - 覆盖极低：0 - 59 分。

评分刻度示例参考（Few-shot Anchor）：
- 示例 A（综合折合 92分 - strong_yes）：候选人是资深前端，技术栈（React, TS）与 JD 100% 重合，有 2 段同类大厂实习，且符合所有硬门槛。
  维度打分：{"education": 95, "skills": 95, "projects": 92, "keywords": 88}
- 示例 B（综合折合 71分 - maybe）：候选人技术栈匹配（Vue），但没有 JD 要求的 React 经验。有 1 段普通项目经验，没有大厂背景，但符合硬门槛。
  维度打分：{"education": 85, "skills": 70, "projects": 68, "keywords": 60}
- 示例 C（综合折合 43分 - no）：候选人是后端开发，想投递前端实习岗位，完全不具备前端项目经验且学历门槛不符。
  维度打分：{"education": 30, "skills": 45, "projects": 40, "keywords": 45}

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
    {"id": "education", "label": "学历背景", "score": 0-100, "tags": ["符合项"], "explanation": "基于教育背景和岗位门槛判断"},
    {"id": "skills", "label": "技能匹配", "score": 0-100, "tags": ["命中词"], "explanation": "基于 JD 技术栈和检索片段判断"},
    {"id": "projects", "label": "项目经历", "score": 0-100, "tags": ["命中项目"], "explanation": "基于项目深度、职责边界和交付判断"},
    {"id": "keywords", "label": "关键词覆盖", "score": 0-100, "tags": ["覆盖词"], "explanation": "基于 JD 关键词在片段中的覆盖判断"}
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
    from ai_analyzer import AIAnalyzer, _call_openai_text
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

    payload_str = json.dumps(compact_payload, sort_keys=True, ensure_ascii=False)
    payload_hash = hashlib.md5(payload_str.encode("utf-8")).hexdigest()
    cache_key = f"{payload_hash}:{model_id}"

    with _CACHE_LOCK:
        if cache_key in _DOUBAO_CACHE:
            print(f"[DOUBAO_RAG] Cache hit for key: {cache_key}")
            return _DOUBAO_CACHE[cache_key]

    try:
        content, _usage = _call_openai_text(
            client,
            model_id,
            [
                {"role": "system", "content": build_system_prompt()},
                {"role": "user", "content": json.dumps(compact_payload, ensure_ascii=False)},
            ],
            temperature=0.1,
        )
        content = strip_json_fence(content or "")
        result = normalize_llm_result(json.loads(content))
        with _CACHE_LOCK:
            _DOUBAO_CACHE[cache_key] = result
            _limit_cache_size(_DOUBAO_CACHE)
        return result
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
