import json
import re
import time
import hashlib
from typing import List, Optional, Tuple, Any

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


_SKILLS_CACHE = {}
_DECISION_CACHE = {}
_REWRITE_CACHE = {}
_STAGE2_CHECK_CACHE = {}

def _limit_cache_size(cache_dict: dict, max_size: int = 1000):
    if len(cache_dict) > max_size:
        try:
            oldest_key = next(iter(cache_dict))
            cache_dict.pop(oldest_key, None)
        except StopIteration:
            pass


class AIAnalyzer:
    def __init__(self):
        timeout = httpx.Timeout(
            Config.LLM_TIMEOUT,
            connect=min(30.0, float(Config.LLM_TIMEOUT)),
        )
        self._http_client = httpx.Client(timeout=timeout)
        self.model = Config.LLM_MODEL

    def _client(self, user_id: Optional[Any] = None, config_id: Optional[str] = None, allow_fallback: bool = True) -> Tuple[OpenAI, Optional[str], str, str]:
        # 1. If user_id is provided, try to find it in the database
        if user_id:
            try:
                from database import Database
                db = Database()
                placeholder = "%s" if db.is_postgres else "?"
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    if config_id and config_id.strip():
                        cursor.execute(
                            f"""
                            SELECT id, provider, model_id, encrypted_api_key, config_json
                            FROM model_configs
                            WHERE id = {placeholder} AND user_id = {placeholder} AND enabled
                            """,
                            (config_id, user_id)
                        )
                        rows = cursor.fetchall()
                        if not rows:
                            cursor.execute(
                                f"""
                                SELECT c.id, c.provider, c.model_id, c.encrypted_api_key, c.config_json
                                FROM model_configs c
                                JOIN model_config_assignments a ON c.id = a.config_id
                                WHERE c.id = {placeholder} AND a.user_id = {placeholder} AND a.enabled AND c.enabled
                                """,
                                (config_id, user_id)
                            )
                            rows = cursor.fetchall()
                    else:
                        cursor.execute(
                            f"""
                            SELECT id, provider, model_id, encrypted_api_key, config_json
                            FROM model_configs
                            WHERE user_id = {placeholder} AND enabled
                            ORDER BY updated_at DESC
                            """,
                            (user_id,)
                        )
                        rows = cursor.fetchall()
                        if not rows:
                            cursor.execute(
                                f"""
                                SELECT c.id, c.provider, c.model_id, c.encrypted_api_key, c.config_json
                                FROM model_configs c
                                JOIN model_config_assignments a ON c.id = a.config_id
                                WHERE a.user_id = {placeholder} AND a.enabled AND c.enabled
                                ORDER BY c.updated_at DESC
                                """,
                                (user_id,)
                            )
                            rows = cursor.fetchall()
                
                if rows:
                    for r in rows:
                        cfg_id, provider, model_id, encrypted_key, config_json = r
                        decrypted_key = db.decrypt_api_key(encrypted_key).strip() if encrypted_key else ""
                        if decrypted_key:
                            base_url = ""
                            if config_json:
                                import json
                                try:
                                    extra = json.loads(config_json)
                                    base_url = extra.get("baseUrl") or extra.get("base_url") or ""
                                except:
                                    pass
                            
                            if not base_url:
                                if provider == "gemini":
                                    base_url = "https://generativelanguage.googleapis.com/v1beta"
                                elif provider == "openai-compatible":
                                    base_url = "https://api.openai.com/v1"
                                    
                            if base_url:
                                self.model = model_id
                                if provider == "gemini":
                                    base = base_url.rstrip("/")
                                    if not base.endswith("/openai"):
                                        base_url = f"{base}/openai"
                                else:
                                    # Format custom baseUrl for OpenAI Python SDK client
                                    base = base_url.rstrip("/")
                                    if base.endswith("/chat/completions"):
                                        base_url = base[:-17].rstrip("/")
                                    elif base.endswith("/chat"):
                                        base_url = base[:-5].rstrip("/")
                                    else:
                                        try:
                                            import urllib.parse
                                            import re
                                            parsed = urllib.parse.urlparse(base)
                                            path = parsed.path.rstrip("/")
                                            if not path or not re.search(r"/(v\d+[^/]*)$", path):
                                                base = f"{base}/v1"
                                        except:
                                            pass
                                        base_url = base
                                        
                                return OpenAI(
                                    api_key=decrypted_key,
                                    base_url=base_url,
                                    http_client=self._http_client,
                                ), cfg_id, provider, model_id
            except Exception as e:
                print(f"[STAR_AI] Database model config resolution error: {e}")

        # Fallback to system default LLM from .env
        if not allow_fallback:
            raise Exception("请先在个人中心 > 模型配置中配置并启用您的大模型，STAR 工坊需要使用您已配置的模型。")
        if Config.LLM_API_KEY and Config.LLM_API_KEY not in _PLACEHOLDER_KEYS and Config.LLM_BASE_URL:
            self.model = Config.LLM_MODEL
            base_url = Config.LLM_BASE_URL.rstrip("/")
            try:
                import urllib.parse, re as _re
                parsed = urllib.parse.urlparse(base_url)
                path = parsed.path.rstrip("/")
                if not path or not _re.search(r"/(v\d+[^/]*)$", path):
                    base_url = f"{base_url}/v1"
            except Exception:
                pass
            return OpenAI(
                api_key=Config.LLM_API_KEY,
                base_url=base_url,
                http_client=self._http_client,
            ), None, "default", Config.LLM_MODEL

        raise Exception("系统默认大模型为空，请先在个人中心/设置中配置并启用您的自定义模型。")


    def extract_skills(self, jd_text: str, user_id: Optional[Any] = None) -> JobAnalysis:
        client, _, _, model_id = self._client(user_id)
        jd_hash = hashlib.md5(jd_text.encode("utf-8")).hexdigest()
        cache_key = f"{jd_hash}:{model_id}"
        if cache_key in _SKILLS_CACHE:
            print(f"[AI_ANALYZER] extract_skills cache hit for key: {cache_key}")
            return _SKILLS_CACHE[cache_key]

        system_prompt = """
        你是面向个人求职者的 JD 拆解助手。请分析给定岗位 JD，并提取：
        1. skills: 核心技能列表，包含硬技能 and 少量关键软技能。
        2. difficulty: 岗位难度，只能是 "简单"、"中等"、"困难" 之一。
        3. job_summary: 100-200 字中文摘要，说明岗位职责、能力要求 and 适合的人。

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
            res = JobAnalysis(**json.loads(result_text))
            _SKILLS_CACHE[cache_key] = res
            _limit_cache_size(_SKILLS_CACHE)
            return res
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
        user_id: Optional[Any] = None,
    ) -> PersonalDecision:
        client, _, _, model_id = self._client(user_id)
        jd_hash = hashlib.md5(jd_text.encode("utf-8")).hexdigest()
        resume_hash = hashlib.md5(resume_text.encode("utf-8")).hexdigest()
        k_hash = hashlib.md5("".join(sorted(knowledge_texts or [])).encode("utf-8")).hexdigest()
        cache_key = f"{jd_hash}:{resume_hash}:{k_hash}:{model_id}"
        if cache_key in _DECISION_CACHE:
            print(f"[AI_ANALYZER] generate_personal_decision cache hit for key: {cache_key}")
            return _DECISION_CACHE[cache_key]

        system_prompt = """
        你是一个严格但务实的个人求职产品经理。你的任务不是夸用户，而是帮个人判断这个岗位是否值得投，
        并把 JD 拆成可执行的简历改造和补短板行动。

        只返回 JSON，字段必须完整：
        {
          "recommendation": "APPLY | CONSIDER | SKIP",
          "score_breakdown": {
            "hard_constraint_match": 0,
            "tech_stack_match": 0,
            "project_relevance": 0,
            "bonus_points": 0
          },
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

        评分维度与细则（百分制，必须严格遵守以下标尺）：
        1. "hard_constraint_match" (学历/硬性门槛过滤, 权重 30%):
           - 完全符合学历、年限、地点等限制：85 - 100 分。
           - 核心门槛严重不符（如学历不符、毕业年限错配，或明确要求全职但候选人只能兼职）：直接给 0 - 30 分。
        2. "tech_stack_match" (核心技能匹配度, 权重 30%):
           - 技术栈与 JD 核心要求完全匹配且有项目佐证：85 - 100 分。
           - 掌握 50% - 80% 的主要技能或有相似技术栈：60 - 84 分。
           - 缺失岗位最基础或最核心的技术（如投前端但完全不会 React/Vue/JS）：0 - 59 分。
        3. "project_relevance" (经历与项目相关度, 权重 30%):
           - 有 1 个或多个高度相似的业务或职责项目背景：85 - 100 分。
           - 技术栈重合，但业务场景或项目深度偏离较大：60 - 84 分。
           - 纯转行、无任何相关实习或项目经验：0 - 59 分。
        4. "bonus_points" (加分项与加分亮点, 权重 10%):
           - 完全契合 JD 提及的“优先”条件或有竞赛/大厂实习加分：85 - 100 分。
           - 无明显加分亮点，但基础履历完整扎实：60 - 84 分。
           - 简历空洞无亮点：0 - 59 分。

        评分刻度示例参考（Few-shot Anchor）：
        - 示例 A（综合折合 92分 - APPLY）：候选人是资深前端，技术栈（React, TS）与 JD 100% 重合，有 2 段同类大厂实习，且符合所有硬门槛。
          JSON 拆分为：{"hard_constraint_match": 95, "tech_stack_match": 95, "project_relevance": 92, "bonus_points": 88}
        - 示例 B（综合折合 71分 - CONSIDER）：候选人技术栈匹配（Vue），但没有 JD 要求的 React 经验。有 1 段普通项目经验，没有大厂背景，但符合硬门槛。
          JSON 拆分为：{"hard_constraint_match": 85, "tech_stack_match": 70, "project_relevance": 68, "bonus_points": 60}
        - 示例 C（综合折合 43分 - SKIP）：候选人是后端开发，想投递前端实习岗位，完全不具备前端项目经验且学历门槛不符。
          JSON 拆分为：{"hard_constraint_match": 30, "tech_stack_match": 45, "project_relevance": 40, "bonus_points": 45}
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
                temperature=0.1,
            )
            result_text = _strip_json_fence((response.choices[0].message.content or "").strip())
            raw = json.loads(result_text)
            
            # Enforce backend-calculated unified scoring (education 30%, skills 30%, projects 30%, keywords/bonus 10%)
            breakdown = raw.get("score_breakdown") or {}
            h_match = max(0, min(100, int(breakdown.get("hard_constraint_match", 50))))
            t_match = max(0, min(100, int(breakdown.get("tech_stack_match", 50))))
            p_match = max(0, min(100, int(breakdown.get("project_relevance", 50))))
            b_match = max(0, min(100, int(breakdown.get("bonus_points", 50))))
            
            calculated_score = int(round(h_match * 0.3 + t_match * 0.3 + p_match * 0.3 + b_match * 0.1))
            # Apply hard constraint blocker cap (Scheme 1 rule)
            if h_match <= 40:
                calculated_score = min(59, calculated_score)
                
            raw["match_score"] = max(0, min(100, calculated_score))
            raw["score_breakdown"] = {
                "hard_constraint_match": h_match,
                "tech_stack_match": t_match,
                "project_relevance": p_match,
                "bonus_points": b_match
            }
            decision_obj = PersonalDecision(**raw)
            _DECISION_CACHE[cache_key] = decision_obj
            _limit_cache_size(_DECISION_CACHE)
            return decision_obj
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
        user_id: Optional[Any] = None,
    ) -> FitExamPaper:
        client, _, _, _ = self._client(user_id)
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
        user_id: Optional[Any] = None,
    ) -> SalaryTrendPrediction:
        client, _, _, _ = self._client(user_id)
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


    def generate_star_segment_suggestion(
        self,
        *,
        segment_type: str,
        input_text: str,
        jd_text: Optional[str] = None,
        resume_text: Optional[str] = None,
        current_star: Optional[dict] = None,
        user_id: Optional[Any] = None,
        config_id: Optional[str] = None,
    ) -> str:
        client, resolved_config_id, provider, model_id = self._client(user_id, config_id, allow_fallback=False)
        current = current_star or {}
        
        system_prompt = f"""
        你是极其资深的简历打磨和求职规划专家。你的任务是协助用户针对特定的项目经历，按照 STAR 原则打磨其第 {segment_type} 阶段的文字。
        STAR 拆解指引：
        - S (Situation) 背景: 交代当时面临的系统背景、业务瓶颈、系统痛点、或是技术债务。
        - T (Task) 任务: 交代明确的技术或业务目标，比如首屏时间降到1s以内，QPS提升两倍，或解决内存泄露。
        - A (Action) 行动: 说明你具体采用了什么技术、组件、重构方案、算法，如何排查问题并付诸实现的。
        - R (Result) 结果: 突出量化的业务收益、技术指标指标变化、高并发负载测试、用户认可等。

        当前打磨目标是：【{segment_type}】阶段。
        请基于用户已有的输入（如果有），结合提供的 JD（岗位要求）和用户原有简历（如果有），给出 200 字以内的润色建议，甚至可以直接写出 2-3 个可以直接参考采用的高清专业表达句子供用户挑选。
        只返回专业润色方案与直接拷贝句型，使用 Markdown 格式，不要说客套话。
        """

        user_prompt = f"""
        用户在【{segment_type}】阶段当前的输入是：
        “{input_text}”

        当前项目的其他部分已填写内容：
        - Situation(背景): {current.get("situation", "（未填）")}
        - Task(任务): {current.get("task", "（未填）")}
        - Action(行动): {current.get("action", "（未填）")}
        - Result(结果): {current.get("result", "（未填）")}

        相关岗位 JD 核心要求：
        {jd_text or "（未提供相关JD）"}

        用户已有简历上下文：
        {resume_text or "（未提供简历）"}
        """

        import time
        start_time = time.time()
        success = False
        error_type = None
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0
        output_text = ""

        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.35,
            )
            output_text = (response.choices[0].message.content or "").strip()
            success = True

            usage = getattr(response, "usage", None)
            if usage:
                prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
                completion_tokens = getattr(usage, "completion_tokens", 0) or 0
                total_tokens = getattr(usage, "total_tokens", 0) or 0

            return output_text
        except Exception as e:
            error_type = type(e).__name__
            raise Exception(f"AI 智能建议生成失败: {e}") from e
        finally:
            duration = int((time.time() - start_time) * 1000)
            if user_id:
                try:
                    from database import Database
                    db = Database()
                    input_chars = len(system_prompt) + len(user_prompt)
                    output_chars = len(output_text)
                    db.log_model_usage(
                        user_id=user_id,
                        config_id=resolved_config_id,
                        assignment_id=None,
                        analysis_id=None,
                        provider=provider,
                        model_id=model_id,
                        usage_type="chat",
                        endpoint="/api/star/generate-segment",
                        success=success,
                        error_type=error_type,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=total_tokens,
                        input_chars=input_chars,
                        output_chars=output_chars,
                        latency_ms=duration
                    )
                except Exception as ex:
                    print(f"[STAR_AI] Failed to log usage: {ex}")

    def polish_star_story(
        self,
        *,
        situation: str,
        task: str,
        action: str,
        result: str,
        style: str = "standard",
        jd_text: Optional[str] = None,
        user_id: Optional[Any] = None,
        config_id: Optional[str] = None,
    ) -> str:
        client, resolved_config_id, provider, model_id = self._client(user_id, config_id, allow_fallback=False)
        
        style_prompt = ""
        if style == "big-tech":
            style_prompt = "【大厂风】：要求措辞高级，突出微服务、分布式、系统可用性、高并发保障、健壮架构设计、团队方法论、业务闭环思考。大量使用如“高内聚低耦合”、“高可用保证”、“高并发瓶颈突破”等工业界硬核词汇。"
        elif style == "start-up":
            style_prompt = "【初创/突击风】：要求突出“从0到1”、“独立交付”、“低成本快迭代”、“业务快速变现”、“全栈 ownership”。措辞突出敏捷、高交付效率、解决实际业务卡点、独立排除万难的精神。"
        else:
            style_prompt = "【通用标准风】：逻辑极其严密，条理清晰，突出专业技术扎实度与严密的闭环逻辑。符合主流中大型公司的简历评估金标准。"

        system_prompt = f"""
        你是极其顶级的技术简历撰写专家。你的任务是将用户提供的 STAR (Situation, Task, Action, Result) 4个拆解字段，重塑并融合成一段极具含金量、可以直接贴入简历的【项目描述】。
        
        风格要求：{style_prompt}

        核心合成规范：
        1. 请使用 Markdown 格式输出。
        2. 请先提供一小段项目整体概述（2-3句话，说明项目性质和背景）。
        3. 然后，以结构清晰的【 Bullet Points（项目职责与成果列项）】输出（3-5点为宜）。
        4. Bullet Points 必须将 Action 和 Result 深度结合，例如“采用 XX 架构，重构 XX 模块 (Action)，从而使得 XX 指标提升 XX (Result)”。
        5. 对数字指标（Result 中的量化数字）务必进行合理加粗，显得极具说服力。
        6. 不要说任何多余的解释、寒暄或说明，直接输出最终合成的项目话术段落。
        """

        user_prompt = f"""
        用户输入的 STAR 碎片如下：
        S (背景): {situation}
        T (任务): {task}
        A (行动): {action}
        R (结果): {result}

        用户正在应聘的 JD 信息（如果提供，请尽量融入其高频关键词如对应技术栈或名词）：
        {jd_text or "（未提供）"}
        """

        import time
        start_time = time.time()
        success = False
        error_type = None
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0
        output_text = ""

        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
            )
            output_text = (response.choices[0].message.content or "").strip()
            success = True

            usage = getattr(response, "usage", None)
            if usage:
                prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
                completion_tokens = getattr(usage, "completion_tokens", 0) or 0
                total_tokens = getattr(usage, "total_tokens", 0) or 0

            return output_text
        except Exception as e:
            error_type = type(e).__name__
            raise Exception(f"STAR 故事智能抛光失败: {e}") from e
        finally:
            duration = int((time.time() - start_time) * 1000)
            if user_id:
                try:
                    from database import Database
                    db = Database()
                    input_chars = len(system_prompt) + len(user_prompt)
                    output_chars = len(output_text)
                    db.log_model_usage(
                        user_id=user_id,
                        config_id=resolved_config_id,
                        assignment_id=None,
                        analysis_id=None,
                        provider=provider,
                        model_id=model_id,
                        usage_type="chat",
                        endpoint="/api/star/polish",
                        success=success,
                        error_type=error_type,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=total_tokens,
                        input_chars=input_chars,
                        output_chars=output_chars,
                        latency_ms=duration
                    )
                except Exception as ex:
                    print(f"[STAR_AI] Failed to log usage: {ex}")

    def smart_rewrite_star(
        self,
        *,
        original_text: str,
        style: str = "standard",
        jd_text: Optional[str] = None,
        user_id: Optional[Any] = None,
        config_id: Optional[str] = None,
    ) -> dict:
        client, resolved_config_id, provider, model_id = self._client(user_id, config_id, allow_fallback=False)
        orig_hash = hashlib.md5(original_text.encode("utf-8")).hexdigest()
        jd_hash = hashlib.md5((jd_text or "").encode("utf-8")).hexdigest()
        cache_key = f"{orig_hash}:{style}:{jd_hash}:{model_id}"
        if cache_key in _REWRITE_CACHE:
            print(f"[AI_ANALYZER] smart_rewrite_star cache hit for key: {cache_key}")
            return _REWRITE_CACHE[cache_key]

        style_prompt = ""
        if style == "big-tech":
            style_prompt = "【大厂风】：措辞高级，突出微服务、分布式、高并发、高可用、架构设计、业务闭环、团队方法论。"
        elif style == "start-up":
            style_prompt = "【初创/突击风】：突出从0到1、独立交付、低成本快迭代、业务快速变现、全栈 ownership。"
        else:
            style_prompt = "【通用标准风】：逻辑严密，条理清晰，专业技术扎实，符合主流中大型公司简历评估金标准。"

        system_prompt = f"""你是极其顶级的技术简历撰写专家。用户将提供一段原始的项目经历描述（可能是简历片段、面试草稿、或随意记录的项目笔记），你需要：

1. 按照 STAR 原则（Situation 背景、Task 任务、Action 行动、Result 结果）对原文进行深度拆解分析。
2. 同时按照指定风格将原文改写润色成一段可直接贴入简历的项目描述。

风格要求：{style_prompt}

润色规范：
- 项目描述以 2-3 句概述开头，说明项目性质和背景
- 之后以 3-5 个 Bullet Points 输出核心职责与成果
- Bullet Points 将 Action 和 Result 深度结合
- 对量化数字指标进行加粗
- 使用 Markdown 格式

输出格式要求：严格输出以下 JSON 格式，不要包含任何其他文字、代码块标记或说明：
{{
  "situation": "拆解出的项目背景（1-3句话）",
  "task": "拆解出的核心任务目标（1-2句话）",
  "action": "拆解出的具体技术行动（2-4句话）",
  "result": "拆解出的量化成果（1-3句话）",
  "polishedText": "完整的润色后简历项目描述（Markdown格式）"
}}"""

        jd_prompt = f"用户正在应聘的岗位 JD：\n{jd_text}" if jd_text else "（未提供应聘 JD）"
        user_prompt = f"""以下是用户的原始项目经历描述：

{original_text}

{jd_prompt}"""

        import time
        import json as json_mod
        start_time = time.time()
        success = False
        error_type = None
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0
        output_text = ""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # Ensure "json" is present in the messages to satisfy some providers like Doubao/OpenAI
        has_json = False
        for msg in messages:
            if "json" in (msg.get("content") or "").lower():
                has_json = True
                break
        if not has_json and messages:
            messages[-1]["content"] += "\n\nReturn the output in JSON format."

        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.3,
                response_format={"type": "json_object"},
                max_tokens=4096,
            )
            output_text = (response.choices[0].message.content or "").strip()
            success = True

            usage = getattr(response, "usage", None)
            if usage:
                prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
                completion_tokens = getattr(usage, "completion_tokens", 0) or 0
                total_tokens = getattr(usage, "total_tokens", 0) or 0
        except Exception as first_err:
            err_msg = str(first_err).lower()
            if "blocked" in err_msg or "content_filter" in err_msg:
                error_type = type(first_err).__name__
                raise Exception(
                    "该模型的内容安全策略拒绝了此请求（输入内容可能触发了审核）。"
                    "请尝试：(1) 切换其他模型配置；(2) 简化或调整输入内容；"
                    "(3) 检查模型服务商的安全过滤设置。"
                    f" 原始错误: {first_err}"
                ) from first_err
            else:
                error_type = type(first_err).__name__
                raise Exception(f"STAR 智能改写失败: {first_err}") from first_err

        try:
            # Parse JSON from response (strip markdown code fence if present)
            clean = output_text
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[-1]
            if clean.endswith("```"):
                clean = clean.rsplit("```", 1)[0]
            clean = clean.strip()

            parsed = json_mod.loads(clean)
            res = {
                "situation": parsed.get("situation", ""),
                "task": parsed.get("task", ""),
                "action": parsed.get("action", ""),
                "result": parsed.get("result", ""),
                "polishedText": parsed.get("polishedText", ""),
            }
            _REWRITE_CACHE[cache_key] = res
            _limit_cache_size(_REWRITE_CACHE)
            return res
        except json_mod.JSONDecodeError:
            # Fallback: return raw text as polishedText
            res = {
                "situation": "",
                "task": "",
                "action": "",
                "result": "",
                "polishedText": output_text,
            }
            _REWRITE_CACHE[cache_key] = res
            _limit_cache_size(_REWRITE_CACHE)
            return res
        except Exception as e:
            error_type = type(e).__name__
            raise Exception(f"STAR 智能改写失败: {e}") from e
        finally:
            duration = int((time.time() - start_time) * 1000)
            if user_id:
                try:
                    from database import Database
                    db = Database()
                    input_chars = len(system_prompt) + len(user_prompt)
                    output_chars = len(output_text)
                    db.log_model_usage(
                        user_id=user_id,
                        config_id=resolved_config_id,
                        assignment_id=None,
                        analysis_id=None,
                        provider=provider,
                        model_id=model_id,
                        usage_type="chat",
                        endpoint="/api/star/smart-rewrite",
                        success=success,
                        error_type=error_type,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=total_tokens,
                        input_chars=input_chars,
                        output_chars=output_chars,
                        latency_ms=duration
                    )
                except Exception as ex:
                    print(f"[STAR_AI] Failed to log usage: {ex}")

    def stage2_llm_check(self, user_id: Any, resume_text: str, jd_text: str) -> Tuple[bool, str]:
        """Checks if the resume meets the hard constraints of the JD using a cheap LLM call."""
        client, resolved_config_id, provider, model_id = self._client(user_id)
        
        resume_hash = hashlib.md5(resume_text.encode("utf-8")).hexdigest()
        jd_hash = hashlib.md5(jd_text.encode("utf-8")).hexdigest()
        cache_key = f"{resume_hash}:{jd_hash}:{model_id}"
        if cache_key in _STAGE2_CHECK_CACHE:
            print(f"[AI_ANALYZER] stage2_llm_check cache hit for key: {cache_key}")
            return _STAGE2_CHECK_CACHE[cache_key]
        
        system_prompt = """
        你是求职门槛甄别助手。你的任务是根据求职者简历与招聘 JD，判断求职者是否满足该职位的硬性指标/基本门槛。
        硬性指标主要包括：学历要求、工作年限、特定的极重要证书或必须具备的特定技能。
        如果求职者基本满足或没有明确冲突，返回 passed 为 true。如果存在明显冲突或缺失（例如：JD要求必须是统招硕士，求职者为大专；或者JD要求有3年相关工作经验，求职者完全是应届生且无相关项目），返回 passed 为 false 并给出理由。
        
        只返回如下 JSON 格式，不要有任何其他文字或 markdown 标记：
        {
          "passed": true,
          "reason": "如果通过则可以为空，如果不通过说明不符合哪些条件"
        }
        """
        
        user_prompt = f"### 候选人简历 ###\n{resume_text}\n\n### 岗位职位描述(JD) ###\n{jd_text}"
        
        start_time = time.time()
        success = True
        error_type = None
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0
        output_text = ""
        
        try:
            # We set a low max_tokens to keep the call fast and cheap.
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                max_tokens=150,
            )
            output_text = (response.choices[0].message.content or "").strip()
            cleaned = _strip_json_fence(output_text)
            
            data = json.loads(cleaned)
            passed = bool(data.get("passed", True))
            reason = data.get("reason", "")
            
            if hasattr(response, "usage") and response.usage:
                prompt_tokens = getattr(response.usage, "prompt_tokens", 0)
                completion_tokens = getattr(response.usage, "completion_tokens", 0)
                total_tokens = getattr(response.usage, "total_tokens", 0)
                
            res = (passed, reason)
            _STAGE2_CHECK_CACHE[cache_key] = res
            _limit_cache_size(_STAGE2_CHECK_CACHE)
            return res
        except Exception as e:
            success = False
            error_type = type(e).__name__
            # Fallback on API failure: assume passed to avoid blockages
            return True, f"API 校验异常跳过: {e}"
        finally:
            duration = int((time.time() - start_time) * 1000)
            if user_id:
                try:
                    from database import Database
                    db = Database()
                    db.log_model_usage(
                        user_id=user_id,
                        config_id=resolved_config_id,
                        assignment_id=None,
                        analysis_id=None,
                        provider=provider,
                        model_id=model_id,
                        usage_type="chat",
                        endpoint="/api/jobs/import/stage2-check",
                        success=success,
                        error_type=error_type,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=total_tokens,
                        input_chars=len(system_prompt) + len(user_prompt),
                        output_chars=len(output_text),
                        latency_ms=duration
                    )
                except Exception as ex:
                    print(f"[STAR_AI] Failed to log usage: {ex}")

