import json
import re

import httpx
from openai import APIConnectionError, APITimeoutError, AuthenticationError, OpenAI

from config import Config
from models import JobAnalysis

_PLACEHOLDER_KEYS = frozenset(
    {"your_api_key_here", "your_deepseek_or_openai_api_key_here", ""}
)


def _strip_json_fence(text: str) -> str:
    """去掉 ```json ... ``` 等围栏，便于解析。"""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s*```\s*$", "", t)
    return t.strip()


class AIAnalyzer:
    def __init__(self):
        timeout = httpx.Timeout(
            Config.LLM_TIMEOUT,
            connect=min(30.0, float(Config.LLM_TIMEOUT)),
        )
        self._http_client = httpx.Client(timeout=timeout)
        self.model = Config.LLM_MODEL

    def _client(self) -> OpenAI:
        key = (Config.LLM_API_KEY or "").strip()
        if key.lower() in _PLACEHOLDER_KEYS:
            raise Exception(
                "未配置有效的 LLM_API_KEY：请在项目根目录创建 .env，"
                "设置 LLM_API_KEY（参考 .env.example），保存后重启 Streamlit。"
            )
        return OpenAI(
            api_key=key,
            base_url=Config.LLM_BASE_URL,
            http_client=self._http_client,
        )

    def extract_skills(self, jd_text: str) -> JobAnalysis:
        client = self._client()

        system_prompt = """
        你是一个专业的招聘信息分析专家。请分析给定的岗位 JD（招聘要求），并提取以下信息：

        1. skills: 提取核心技能列表，包括：
           - 硬核技术（如 Rust, WPF, Python, 机器学习等）
           - 软技能（如沟通能力、团队协作、项目管理等）

        2. difficulty: 评估岗位难度，只能是以下三个值之一："简单", "中等", "困难"

        3. job_summary: 用 100-200 字简要描述岗位的核心要求和职责

        请严格返回 JSON 格式，不要包含任何其他文字说明。
        JSON 格式示例：
        {
            "skills": ["Python", "机器学习", "团队协作"],
            "difficulty": "中等",
            "job_summary": "这是一个需要 Python 和机器学习技能的岗位..."
        }
        """

        user_prompt = f"请分析以下岗位 JD：\n\n{jd_text}"

        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
            )

            result_text = (response.choices[0].message.content or "").strip()
            result_text = _strip_json_fence(result_text)
            result = json.loads(result_text)

            return JobAnalysis(**result)

        except APIConnectionError as e:
            raise Exception(
                "无法连接到大模型服务（Connection error）。请检查："
                "1) 本机网络/VPN 能否访问 "
                f"{Config.LLM_BASE_URL}；"
                "2) .env 中 LLM_BASE_URL 是否与服务商文档一致；"
                "3) 公司网络是否需设置系统代理或 HTTPS_PROXY；"
                "4) 可适当增大 .env 中的 LLM_TIMEOUT。"
                f" 原始错误: {e}"
            ) from e
        except APITimeoutError as e:
            raise Exception(
                f"大模型请求超时（当前超时 {Config.LLM_TIMEOUT}s）。"
                "可在 .env 中增大 LLM_TIMEOUT 后重试。"
                f" 原始错误: {e}"
            ) from e
        except AuthenticationError as e:
            raise Exception(
                "API 密钥无效或未授权。请检查 .env 中的 LLM_API_KEY 是否正确。"
                f" 原始错误: {e}"
            ) from e
        except json.JSONDecodeError as e:
            raise Exception(
                f"模型返回内容不是合法 JSON，请重试或更换模型。解析错误: {e}"
            ) from e
        except Exception as e:
            raise Exception(f"AI 分析失败: {str(e)}") from e
