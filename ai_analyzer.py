import json
import re
from typing import List, Optional

import httpx
from openai import APIConnectionError, APITimeoutError, AuthenticationError, OpenAI

from config import Config
from models import (
    FitExamPaper,
    FitExamQuestion,
    JobAnalysis,
    PersonalDecision,
    SalaryTrendPrediction,
)

_PLACEHOLDER_KEYS = frozenset(
    {"your_api_key_here", "your_deepseek_or_openai_api_key_here", ""}
)


def _strip_json_fence(text: str) -> str:
    """Remove ```json fences so model output can be parsed as JSON."""
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
                "设置 LLM_API_KEY（参考 .env.example），保存后重启应用。"
            )
        return OpenAI(
            api_key=key,
            base_url=Config.LLM_BASE_URL,
            http_client=self._http_client,
        )

    def extract_skills(self, jd_text: str) -> JobAnalysis:
        client = self._client()
        system_prompt = """
        你是面向个人求职者的 JD 拆解助手。请分析给定岗位 JD，并提取：
        1. skills: 核心技能列表，包含硬技能和少量关键软技能。
        2. difficulty: 岗位难度，只能是 "简单"、"中等"、"困难" 之一。
        3. job_summary: 100-200 字中文摘要，说明岗位职责、能力要求和适合的人。

        只返回 JSON，不要添加解释：
        {
          "skills": ["Python", "FastAPI", "沟通协作"],
          "difficulty": "中等",
          "job_summary": "..."
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
            result_text = _strip_json_fence((response.choices[0].message.content or "").strip())
            return JobAnalysis(**json.loads(result_text))
        except APIConnectionError as e:
            raise Exception(
                "无法连接到大模型服务。请检查网络、代理和 LLM_BASE_URL。"
                f" 原始错误: {e}"
            ) from e
        except APITimeoutError as e:
            raise Exception(
                f"大模型请求超时（当前超时 {Config.LLM_TIMEOUT}s）。"
                f" 原始错误: {e}"
            ) from e
        except AuthenticationError as e:
            raise Exception(
                "API 密钥无效或未授权。请检查 .env 中的 LLM_API_KEY。"
                f" 原始错误: {e}"
            ) from e
        except json.JSONDecodeError as e:
            raise Exception(f"模型返回内容不是合法 JSON: {e}") from e
        except Exception as e:
            raise Exception(f"AI 分析失败: {str(e)}") from e

    def generate_personal_decision(
        self,
        *,
        jd_text: str,
        analysis: JobAnalysis,
        resume_text: str = "",
        knowledge_texts: Optional[List[str]] = None,
    ) -> PersonalDecision:
        client = self._client()
        system_prompt = """
        你是一个严格但务实的个人求职产品经理。你的任务不是夸用户，而是帮个人判断这个岗位是否值得投，
        并把 JD 拆成可执行的简历改造和补短板行动。

        只返回 JSON，字段必须完整：
        {
          "recommendation": "APPLY | CONSIDER | SKIP",
          "match_score": 0,
          "decision_reasons": ["3条以内，说明为什么这样判断"],
          "critical_gaps": ["关键缺口，最多5条"],
          "resume_rewrites": ["可直接写进简历的中文表达，最多5条"],
          "evidence_needed": ["还需要补充证据的经历或材料，最多5条"],
          "action_plan": ["下一步行动，3-7条"],
          "learning_plan": ["可选学习/刷题建议，最多5条"]
        }

        判断规则：
        - APPLY: 个人材料能支撑多数核心要求，缺口可短期补齐。
        - CONSIDER: 有明显机会，但需要补材料、改简历或补技能后再投。
        - SKIP: 与核心要求偏离较大，短期投入产出比低。
        - match_score 必须体现保守判断，不要虚高。
        """
        payload = {
            "jd_text": jd_text,
            "analysis": analysis.model_dump(mode="json", exclude={"personal_decision"}),
            "resume_text": resume_text,
            "knowledge_texts": knowledge_texts or [],
        }
        user_prompt = json.dumps(payload, ensure_ascii=False)

        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.25,
            )
            result_text = _strip_json_fence((response.choices[0].message.content or "").strip())
            raw = json.loads(result_text)
            raw["match_score"] = max(0, min(100, int(raw.get("match_score", 50))))
            return PersonalDecision(**raw)
        except APIConnectionError as e:
            raise Exception(f"个人决策生成无法连接到大模型服务: {e}") from e
        except APITimeoutError as e:
            raise Exception(f"个人决策生成超时: {e}") from e
        except AuthenticationError as e:
            raise Exception(f"个人决策生成认证失败: {e}") from e
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            raise Exception(f"个人决策 JSON 解析失败: {e}") from e
        except Exception as e:
            raise Exception(f"个人决策生成失败: {e}") from e

    def generate_fit_exam(
        self,
        *,
        jd_text: str,
        skills: List[str],
        major_profile: str,
        question_count: int = 8,
    ) -> FitExamPaper:
        client = self._client()
        qc = max(3, min(int(question_count), 15))
        system_prompt = """
        你是校招/实习测评命题人。根据岗位 JD、技能点与候选人专业背景，出一套四选一单选题。
        题目分为：专业知识、职业品质、性格适配。
        只返回 JSON：
        {
          "questions": [
            {
              "stem": "题干",
              "options": ["A", "B", "C", "D"],
              "correct_index": 0,
              "category": "专业知识"
            }
          ]
        }
        questions 总长度必须等于用户要求的题量。
        """
        user_prompt = (
            f"专业/方向自述：\n{major_profile or '（未提供）'}\n\n"
            f"技能列表：{json.dumps(skills, ensure_ascii=False)}\n\n"
            f"岗位 JD：\n{jd_text}\n\n"
            f"题量：{qc}"
        )

        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.35,
            )
            result_text = _strip_json_fence((response.choices[0].message.content or "").strip())
            payload = json.loads(result_text)
            questions: List[FitExamQuestion] = []
            for item in payload.get("questions") or []:
                opts = list(item.get("options") or [])
                if len(opts) != 4:
                    continue
                idx = max(0, min(3, int(item.get("correct_index", 0))))
                cat = str(item.get("category", "") or "").strip()
                if cat not in ("专业知识", "职业品质", "性格适配"):
                    cat = ""
                questions.append(
                    FitExamQuestion(
                        stem=str(item.get("stem", "")).strip(),
                        options=opts,
                        correct_index=idx,
                        category=cat,
                    )
                )
            if len(questions) < 3:
                raise ValueError("模型返回题目数量不足")
            return FitExamPaper(questions=questions)
        except APIConnectionError as e:
            raise Exception(f"无法连接到大模型服务: {e}") from e
        except APITimeoutError as e:
            raise Exception(f"大模型请求超时: {e}") from e
        except AuthenticationError as e:
            raise Exception(f"API 密钥无效或未授权: {e}") from e
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            raise Exception(f"测验卷解析失败: {e}") from e
        except Exception as e:
            raise Exception(f"出卷失败: {str(e)}") from e

    def predict_salary_trend(
        self,
        *,
        history_lines: List[str],
        linear_hint: Optional[float],
        sample_count: int,
    ) -> SalaryTrendPrediction:
        client = self._client()
        system_prompt = """
        你是劳动经济学方向的助理研究员。根据月薪时间序列（单位：千元/月）与样本量，
        给出未来 1-2 个季度的走势判断和一个点预测。只返回 JSON：
        {
          "narrative": "200字以内说明",
          "forecast_next_k": 123.4,
          "methodology_note": "一句话提醒风险"
        }
        """
        hint = "" if linear_hint is None else f"线性外推约 30 天后：{linear_hint:.2f} 千元/月。"
        user_prompt = "\n".join(history_lines) + f"\n\n样本点数：{sample_count}\n{hint}"

        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.25,
            )
            result_text = _strip_json_fence((response.choices[0].message.content or "").strip())
            payload = json.loads(result_text)
            return SalaryTrendPrediction(
                narrative=str(payload.get("narrative", "")).strip(),
                forecast_next_k=payload.get("forecast_next_k"),
                methodology_note=str(payload.get("methodology_note", "")).strip()
                or "预测仅供参考，不构成薪酬或录用承诺。",
            )
        except Exception as e:  # noqa: BLE001
            raise Exception(f"薪酬走势预测失败: {e}") from e
