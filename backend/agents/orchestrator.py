import os
import json
import asyncio
import traceback
import copy
import time
from datetime import datetime
from typing import Any, Optional, Dict, List

from config import Config
from database import Database
from ai_analyzer import AIAnalyzer
from backend.agents.base import BaseAgent
from backend.agent_planner import AgentPlanner
from backend.agents.job_decoder import JobDecoder
from backend.agents.resume_copywriter import ResumeCopywriter
from backend.agents.tools.hitl_tool import ask_human_question, HumanInteractionRequired
from backend.agents.tools.layout_tools import check_layout_dependencies, render_docx_to_images
from backend.agents.tools.workspace_tools import tool_read_file, tool_write_file, get_safe_workspace_path
from backend.agents.tools.resume_section_tools import (
    tool_extract_resume_sections,
    tool_replace_resume_section,
    tool_generate_modification_diff,
)
from backend.agents.tools.hallucination_tools import (
    tool_verify_anti_hallucination,
    check_resume_fact_integrity,
)
from backend.agents.tools.docx_tools import (
    extract_docx_style_profile,
    generate_docx_from_markdown,
    update_docx_resume_from_log,
)
from backend.agents.layout_auditor import LayoutAuditor
from backend.agents.cache import build_cache_key, get_agent_cache, set_agent_cache

class Orchestrator(BaseAgent):
    """
    指挥协调官智能体，负责统筹协调整个简历优化流水线。
    """
    def __init__(
        self,
        agent_id: str = "orchestrator",
        role: str = "Orchestrator",
        model: str = "gpt-4o-mini",
        openai_client: Optional[Any] = None
    ):
        """
        初始化 Orchestrator 智能体。
        """
        super().__init__(agent_id=agent_id, role=role, model=model, openai_client=openai_client)
        self.db = Database()
        self.logs: List[Dict[str, Any]] = []
        self.current_status = "RUNNING"
        self.trace_id: Optional[str] = None

    def log_step(
        self,
        task_id: str,
        user_id: Any,
        step_type: str,
        message: str,
        detail: Any = None,
        *,
        stage: Optional[str] = None,
        agent: Optional[str] = None,
        cache_namespace: Optional[str] = None,
        cache_hit: Optional[bool] = None,
        duration_ms: Optional[int] = None,
        model_id: Optional[str] = None,
        retry_count: int = 0,
        status: Optional[str] = None,
        error_type: Optional[str] = None,
    ) -> None:
        """
        添加日志并即时同步更新到数据库中。
        """
        timestamp = datetime.now().isoformat()
        self.logs.append({
            "timestamp": timestamp,
            "type": step_type,
            "message": message,
            "detail": detail,
            "traceId": self.trace_id or task_id,
            "stage": stage or step_type,
            "agent": agent or self.role,
            "status": status or ("failed" if step_type == "error" else "completed"),
            "cacheNamespace": cache_namespace or "",
            "cacheHit": cache_hit,
            "durationMs": duration_ms,
            "modelId": model_id or self.model,
            "retryCount": int(retry_count or 0),
            "errorType": error_type or "",
        })
        try:
            self.db.update_agent_resume_task_status(
                task_id=task_id,
                user_id=user_id,
                status=self.current_status,
                logs=json.dumps(self.logs, ensure_ascii=False)
            )
        except Exception as e:
            print(f"[ORCHESTRATOR] Failed to update running log: {e}")

    async def run_orchestration(self, task_id: str, user_id: Any, config_id: str, is_co_pilot: bool = True) -> None:
        """
        运行简历优化工作流，替代 ReAct 单体大循环。

        Args:
            task_id (str): 任务 ID。
            user_id (Any): 用户 ID。
            config_id (str): 对应的大模型配置 ID。
            is_co_pilot (bool): 是否为协同交互（Co-Pilot）模式，默认为 True。

        Raises:
            HumanInteractionRequired: 需要人类介入提问时抛出此异常，挂起当前任务。
        """
        self.logs = []
        plan: Optional[Dict[str, Any]] = None
        cache_stats: Dict[str, Any] = {
            "hits": 0,
            "misses": 0,
            "saved_model_calls": 0,
            "items": [],
        }

        def restore_cache_stats(raw_stats: Any) -> None:
            if not isinstance(raw_stats, dict):
                return
            cache_stats["hits"] = int(raw_stats.get("hits") or 0)
            cache_stats["misses"] = int(raw_stats.get("misses") or 0)
            cache_stats["saved_model_calls"] = int(
                raw_stats.get("saved_model_calls")
                or raw_stats.get("savedModelCalls")
                or 0
            )
            raw_items = raw_stats.get("items")
            cache_stats["items"] = raw_items if isinstance(raw_items, list) else []

        def record_cache_event(
            namespace: str,
            label: str,
            hit: bool,
            saved_model_calls: int = 1,
        ) -> None:
            saved_calls = max(0, int(saved_model_calls or 0)) if hit else 0
            if hit:
                cache_stats["hits"] = int(cache_stats.get("hits") or 0) + 1
                cache_stats["saved_model_calls"] = int(cache_stats.get("saved_model_calls") or 0) + saved_calls
            else:
                cache_stats["misses"] = int(cache_stats.get("misses") or 0) + 1
            items = cache_stats.setdefault("items", [])
            if isinstance(items, list):
                items.append({
                    "namespace": namespace,
                    "label": label,
                    "hit": hit,
                    "saved_model_calls": saved_calls,
                    "stage": label,
                    "agent": self.role,
                    "timestamp": datetime.now().isoformat(),
                })
                cache_stats["items"] = items[-80:]

        def dump_plan() -> str:
            if isinstance(plan, dict):
                plan["cache_stats"] = cache_stats
                return json.dumps(plan, ensure_ascii=False)
            return ""

        try:
            self.log_step(task_id, user_id, "info", "指挥协调官开始启动工作流...")

            # 1. 获取任务数据与初始化环境
            task = self.db.get_agent_resume_task(user_id, task_id)
            if not task:
                raise ValueError(f"指定的简历优化任务不存在 (task_id: {task_id})")
            self.trace_id = str(task.get("trace_id") or task_id)

            resume_id = task.get("resume_id")
            jd_text = task.get("jd_text", "")

            # 加载简历数据
            resume_data = self.db.get_user_resume(user_id, resume_id)
            if not resume_data:
                raise ValueError("未找到指定的简历")

            resume_text = resume_data.get("cleanedText") or resume_data.get("rawText") or ""
            if not resume_text.strip():
                raise ValueError("读取到的简历文本内容为空")

            # 准备物理 Workspace 环境并写入基准文件
            tool_write_file(user_id, task_id, "original_resume.txt", resume_text)
            tool_write_file(user_id, task_id, "job_description.txt", jd_text)

            # 提取原始简历样式排版特征
            try:
                extract_docx_style_profile(user_id, task_id, resume_id)
                self.log_step(task_id, user_id, "info", "已成功提取原始简历的样式排版特征（style_profile.json）。")
            except Exception as style_err:
                self.log_step(task_id, user_id, "warning", f"提取原始简历排版特征失败（将采用默认排版）：{style_err}")

            # 解析并初始化大模型客户端
            analyzer = AIAnalyzer()
            openai_client, resolved_cfg_id, provider, model_id = await asyncio.to_thread(
                analyzer._client, user_id, config_id, True
            )
            self.openai_client = openai_client
            self.model = model_id
            self.log_step(task_id, user_id, "info", f"解析大模型配置成功。当前模型：{model_id}。")

            # 2. 检查或生成执行计划
            plan_str = task.get("execution_plan")
            if plan_str:
                try:
                    bootstrap_plan = json.loads(plan_str)
                    if isinstance(bootstrap_plan, dict) and bootstrap_plan.get("bootstrap_only"):
                        restore_cache_stats(bootstrap_plan.get("cache_stats"))
                        plan_str = ""
                except Exception:
                    pass
            if not plan_str:
                self.log_step(task_id, user_id, "info", "执行计划为空，正在生成新的优化计划...")
                planner = AgentPlanner()
                plan_cache_key = build_cache_key("resume_plan_v2", str(user_id), model_id, resume_text, jd_text)
                cached_plan = get_agent_cache("resume_plan_v2", plan_cache_key)
                if isinstance(cached_plan, dict) and isinstance(cached_plan.get("steps"), list):
                    plan = copy.deepcopy(cached_plan)
                    plan.pop("cache_stats", None)
                    for cached_step in plan.get("steps", []):
                        cached_step["status"] = "PENDING"
                    record_cache_event("resume_plan_v2", "执行计划", True, 1)
                    self.log_step(task_id, user_id, "info", "命中执行计划缓存，跳过计划生成模型调用。")
                else:
                    record_cache_event("resume_plan_v2", "执行计划", False, 1)
                    started_at = time.perf_counter()
                    plan = await planner.generate_plan(resume_text, jd_text, openai_client, model_id)
                    self.log_step(
                        task_id,
                        user_id,
                        "info",
                        "执行计划模型调用完成。",
                        stage="plan",
                        agent="AgentPlanner",
                        cache_namespace="resume_plan_v2",
                        duration_ms=int((time.perf_counter() - started_at) * 1000),
                        model_id=model_id,
                    )
                    set_agent_cache("resume_plan_v2", plan_cache_key, copy.deepcopy(plan))
                plan["config_id"] = config_id
                plan["is_co_pilot"] = is_co_pilot
                plan["trace_id"] = self.trace_id
                plan_str = dump_plan()
                self.db.update_agent_resume_task_status(
                    task_id=task_id,
                    user_id=user_id,
                    status="RUNNING",
                    execution_plan=plan_str
                )
                self.log_step(task_id, user_id, "info", "优化执行计划生成完毕，已存入数据库。")
            else:
                self.log_step(task_id, user_id, "info", "已加载已有的优化执行计划，准备断点续跑...")
                plan = json.loads(plan_str)
                restore_cache_stats(plan.get("cache_stats"))

            # 3. 解码 JD 获得岗位画像
            self.log_step(task_id, user_id, "info", "正在对岗位 JD 进行多维深度解码...")
            jd_cache_key = build_cache_key("job_decode_v2", model_id, jd_text)
            cached_job = get_agent_cache("job_decode_v2", jd_cache_key)
            if isinstance(cached_job, dict):
                decoded_job = cached_job
                record_cache_event("job_decode_v2", "JD 解码", True, 1)
                self.log_step(task_id, user_id, "info", "命中 JD 解码缓存，跳过岗位解码模型调用。")
            else:
                record_cache_event("job_decode_v2", "JD 解码", False, 1)
                decoder = JobDecoder(model=model_id, openai_client=openai_client)
                started_at = time.perf_counter()
                decoded_job = await decoder.decode_job(jd_text)
                self.log_step(
                    task_id,
                    user_id,
                    "info",
                    "岗位解码模型调用完成。",
                    stage="job_decode",
                    agent="JobDecoder",
                    cache_namespace="job_decode_v2",
                    duration_ms=int((time.perf_counter() - started_at) * 1000),
                    model_id=model_id,
                )
                set_agent_cache("job_decode_v2", jd_cache_key, decoded_job)
            self.db.update_agent_resume_task_status(
                task_id=task_id,
                user_id=user_id,
                status="RUNNING",
                execution_plan=dump_plan()
            )
            self.log_step(task_id, user_id, "info", "岗位画像解码完成。", {"decoded_job": decoded_job})

            # 初始化简历修辞专家和 HRCritic
            copywriter = ResumeCopywriter(model=model_id, openai_client=openai_client)
            from backend.agents.hr_critic import HRCritic
            critic = HRCritic(model=model_id, openai_client=openai_client)

            # 读取或生成段落划分 JSON
            sections_json = tool_read_file(user_id, task_id, "resume_sections.json")
            if "错误：" in sections_json:
                sections_json = tool_extract_resume_sections(resume_text)
                tool_write_file(user_id, task_id, "resume_sections.json", sections_json)
            sections_list = json.loads(sections_json)

            # 4. 遍历执行计划中的每一个步骤
            steps = plan.get("steps", [])
            is_copilot = plan.get("is_co_pilot", True)
            conversation_state = self.db.get_agent_resume_conversation_state(user_id, task_id)

            def format_conversation_context(state: Dict[str, Any]) -> str:
                summary = str(state.get("summary") or "").strip()
                preferences = [
                    str(item).strip()
                    for item in (state.get("global_preferences") or [])
                    if str(item).strip()
                ]
                facts = [
                    str(item).strip()
                    for item in (state.get("fact_ledger") or [])
                    if str(item).strip()
                ]
                lines: list[str] = []
                if summary:
                    lines.append(f"会话摘要：{summary[:1200]}")
                if preferences:
                    lines.append("全局偏好：" + "；".join(dict.fromkeys(preferences[-8:])))
                if facts:
                    lines.append("事实账本：" + "；".join(dict.fromkeys(facts[-12:])))
                return "\n".join(lines)

            conversation_context = format_conversation_context(conversation_state)

            for step in steps:
                if step.get("status") in {"COMPLETED", "SKIPPED"}:
                    continue

                step_name = step.get("section_name", "未知模块")
                self.log_step(task_id, user_id, "info", f"【步骤 {step.get('step_index')}】开始处理模块: {step_name}")

                # 面临关键决定或 Co-Pilot 模式触发
                should_interact = is_copilot

                # 重新从数据库获取最新 task 状态以检查 human_answer
                current_task_state = self.db.get_agent_resume_task(user_id, task_id)
                user_answer = current_task_state.get("human_answer") if current_task_state else None

                step_goal = step.get("improvement_goal", "")
                if conversation_context:
                    step_goal = f"{step_goal}\n\n[持续对话上下文]\n{conversation_context}"

                if should_interact:
                    try:
                        current_step_index = int(step.get("step_index"))
                    except (TypeError, ValueError):
                        current_step_index = 0
                    answer_turns = self.db.list_unconsumed_agent_answer_turns(
                        user_id=user_id,
                        task_id=task_id,
                        step_index=current_step_index,
                    )
                    if not answer_turns and user_answer and user_answer.strip():
                        answer_turns = [{
                            "id": "",
                            "content": user_answer.strip(),
                            "answer_type": "evidence",
                            "remember": False,
                            "evidence_scope": "current_step",
                        }]

                    if answer_turns:
                        answer_fragments = []
                        for turn in answer_turns:
                            content = str(turn.get("content") or "").strip()
                            answer_type = str(turn.get("answer_type") or "evidence")
                            if not content:
                                continue
                            if answer_type == "skip" or "无补充" in content or "无需补充" in content:
                                answer_fragments.append(f"用户明确无补充：{content}")
                            elif answer_type == "preference":
                                answer_fragments.append(f"用户偏好：{content}")
                            elif answer_type == "clarification":
                                answer_fragments.append(f"用户澄清：{content}")
                            elif answer_type == "instruction":
                                answer_fragments.append(f"用户指令：{content}")
                            elif answer_type == "question":
                                answer_fragments.append(f"用户追问：{content}")
                            else:
                                answer_fragments.append(f"用户补充可核验证据：{content}")

                        if answer_fragments:
                            self.log_step(
                                task_id,
                                user_id,
                                "info",
                                "已接收到当前步骤的人机交互反馈。",
                                {
                                    "step_index": current_step_index,
                                    "answers": answer_fragments,
                                },
                                stage="human_answer",
                                agent="Human",
                            )
                            if not all(fragment.startswith("用户明确无补充") for fragment in answer_fragments):
                                step_goal = f"{step_goal}。{'；'.join(answer_fragments)}"

                        turn_ids = [str(turn.get("id") or "") for turn in answer_turns if turn.get("id")]
                        if turn_ids:
                            self.db.mark_agent_resume_turns_consumed(turn_ids)

                        # 立即清空兼容字段，防止后续步骤污染
                        self.db.update_agent_resume_task_status(
                            task_id=task_id,
                            user_id=user_id,
                            status="RUNNING",
                            human_answer="",
                            pending_question=""
                        )
                    else:
                        # 弹出卡片并提问，抛出异常挂起当前 Agent
                        question = f"针对您简历中的「{step_name}」模块优化，为了让它更贴合目标岗位，您是否有需要额外补充的关键项目经历、职责细节或可量化数据？"
                        self.log_step(task_id, user_id, "info", f"面临模块「{step_name}」的关键决策，触发人机交互悬挂卡片...")
                        ask_human_question(task_id, user_id, question, step_index=current_step_index or None)

                # 调用 ResumeCopywriter 对该段落进行优化
                rewrite_cache_key = build_cache_key(
                    "resume_section_rewrite_v2",
                    str(user_id),
                    model_id,
                    step_name,
                    step.get("section_index"),
                    step["original_content"],
                    decoded_job,
                    step_goal,
                )
                cached_rewrite = get_agent_cache("resume_section_rewrite_v2", rewrite_cache_key)
                cached_verified = isinstance(cached_rewrite, dict) and isinstance(cached_rewrite.get("optimized_content"), str)

                if cached_verified:
                    record_cache_event("resume_section_rewrite_v2", f"段落改写:{step_name}", True, 3)
                    current_content = cached_rewrite["optimized_content"]
                    self.log_step(
                        task_id,
                        user_id,
                        "info",
                        f"命中段落「{step_name}」改写缓存，跳过修辞、HR 审计与 LLM 防幻觉调用。",
                        {"cache_key": rewrite_cache_key[:12]}
                    )
                else:
                    self.log_step(task_id, user_id, "info", f"简历修辞官开始对段落「{step_name}」进行重构改写...")
                    record_cache_event("resume_section_rewrite_v2", f"段落改写:{step_name}", False, 3)
                    started_at = time.perf_counter()
                    current_content = await copywriter.rewrite_section(
                        section_name=step_name,
                        original_content=step["original_content"],
                        decoded_job=decoded_job,
                        goal=step_goal,
                        user_id=str(user_id)
                    )
                    self.log_step(
                        task_id,
                        user_id,
                        "info",
                        f"段落「{step_name}」改写模型调用完成。",
                        stage="rewrite",
                        agent="ResumeCopywriter",
                        cache_namespace="resume_section_rewrite_v2",
                        duration_ms=int((time.perf_counter() - started_at) * 1000),
                        model_id=model_id,
                    )

                if not cached_verified:
                    # 引入 HR 审计与重试机制
                    max_retries = 2
                    retry_count = 0
                    eval_res = {}
                    while True:
                        critic_cache_key = build_cache_key(
                            "resume_hr_critic_v2",
                            model_id,
                            step_name,
                            step["original_content"],
                            current_content,
                            jd_text,
                        )
                        cached_eval = get_agent_cache("resume_hr_critic_v2", critic_cache_key)
                        if isinstance(cached_eval, dict):
                            eval_res = cached_eval
                            record_cache_event("resume_hr_critic_v2", f"HR 审计:{step_name}", True, 1)
                            self.log_step(task_id, user_id, "info", f"命中 HR 审计缓存。得分: {eval_res.get('score', 0)}分。")
                        else:
                            record_cache_event("resume_hr_critic_v2", f"HR 审计:{step_name}", False, 1)
                            started_at = time.perf_counter()
                            eval_res = await critic.evaluate(
                                section_name=step_name,
                                original_content=step["original_content"],
                                optimized_content=current_content,
                                jd_text=jd_text,
                                user_id=str(user_id)
                            )
                            self.log_step(
                                task_id,
                                user_id,
                                "info",
                                f"段落「{step_name}」HR 审计模型调用完成。",
                                stage="hr_critic",
                                agent="HRCritic",
                                cache_namespace="resume_hr_critic_v2",
                                duration_ms=int((time.perf_counter() - started_at) * 1000),
                                model_id=model_id,
                            )
                            set_agent_cache("resume_hr_critic_v2", critic_cache_key, eval_res)

                        score = eval_res.get("score", 0)
                        is_passed = eval_res.get("is_passed", False)
                        critique = eval_res.get("critique", "")
                        suggestions = eval_res.get("suggestions", "")

                        if is_passed:
                            self.log_step(task_id, user_id, "info", f"【HR审计通过】得分: {score}分。审计反馈: {critique}")
                            break

                        if retry_count >= max_retries:
                            self.log_step(task_id, user_id, "warning", f"【HR审计强行通过】已达到最大重试上限（{max_retries}次）。最终得分: {score}分。原因: {critique}")
                            break

                        retry_count += 1
                        self.log_step(
                            task_id, user_id, "warning",
                            f"【HR审计未通过】得分: {score}分。原因: {critique}。正在针对性重写润色（第 {retry_count} 次重试）...",
                            {"suggestions": suggestions},
                            stage="hr_critic",
                            agent="HRCritic",
                            retry_count=retry_count,
                            status="retrying",
                        )

                        # 调用 ResumeCopywriter 的重试优化方法
                        current_content = await copywriter.rewrite_section_retry(
                            section_name=step_name,
                            original_content=step["original_content"],
                            previous_optimized=current_content,
                            critique=critique,
                            suggestions=suggestions,
                            decoded_job=decoded_job,
                            goal=step_goal
                        )

                # 校验防幻觉（LLM 语义审查 + 本地确定性硬事实守门）
                fact_guard_passed = False
                for guard_attempt in range(2):
                    self.log_step(task_id, user_id, "info", "正在对改写文本进行防幻觉检测...")
                    verification_cache_key = build_cache_key(
                        "resume_hallucination_check_v2",
                        model_id,
                        step["original_content"],
                        current_content,
                    )
                    cached_verification = get_agent_cache("resume_hallucination_check_v2", verification_cache_key)
                    if isinstance(cached_verification, str):
                        verification_res = cached_verification
                        record_cache_event("resume_hallucination_check_v2", f"防幻觉:{step_name}", True, 1)
                        self.log_step(task_id, user_id, "info", "命中防幻觉语义审查缓存。")
                    else:
                        record_cache_event("resume_hallucination_check_v2", f"防幻觉:{step_name}", False, 1)
                        verification_res = await asyncio.to_thread(
                            tool_verify_anti_hallucination,
                            openai_client,
                            model_id,
                            step["original_content"],
                            current_content
                        )
                        set_agent_cache("resume_hallucination_check_v2", verification_cache_key, verification_res)
                    local_guard = check_resume_fact_integrity(
                        step["original_content"],
                        current_content,
                        evidence_text=f"{jd_text}\n{step_goal}"
                    )
                    self.log_step(
                        task_id,
                        user_id,
                        "info",
                        f"防幻觉审查完成，结论如下：\n{verification_res}",
                        {"local_fact_guard": local_guard}
                    )
                    if local_guard.get("ok"):
                        fact_guard_passed = True
                        break

                    if cached_verified:
                        break

                    if guard_attempt == 1:
                        break

                    self.log_step(
                        task_id,
                        user_id,
                        "warning",
                        f"本地事实守门发现新增硬事实，正在要求修辞官移除风险内容：{local_guard.get('message')}"
                    )
                    current_content = await copywriter.rewrite_section_retry(
                        section_name=step_name,
                        original_content=step["original_content"],
                        previous_optimized=current_content,
                        critique=f"事实守门未通过：{local_guard.get('message')}",
                        suggestions="删除所有未出现在原始段落、JD 或用户补充中的日期、数字、机构、规模、金额、百分比、倍数与具体技术硬事实；保留原结构并只做措辞优化。",
                        decoded_job=decoded_job,
                        goal=step_goal
                    )

                if not fact_guard_passed:
                    self.log_step(
                        task_id,
                        user_id,
                        "warning",
                        f"模块「{step_name}」因存在新增硬事实风险被跳过替换，原文保持不变。"
                    )
                    step["status"] = "COMPLETED"
                    self.db.update_agent_resume_task_status(
                        task_id=task_id,
                        user_id=user_id,
                        status="RUNNING",
                        execution_plan=dump_plan()
                    )
                    continue

                if not cached_verified:
                    set_agent_cache("resume_section_rewrite_v2", rewrite_cache_key, {
                        "optimized_content": current_content,
                        "verified_at": datetime.now().isoformat(),
                    })

                # 精精准定位 section index 进行物理替换
                sec_idx = None
                try:
                    candidate_idx = int(step.get("section_index"))
                    if any(s.get("index") == candidate_idx for s in sections_list):
                        sec_idx = candidate_idx
                except (TypeError, ValueError):
                    sec_idx = None

                if sec_idx is None:
                    original_hint = str(step.get("original_content") or "").strip()
                    for s in sections_list:
                        content = str(s.get("content") or "")
                        if original_hint and (original_hint == content or original_hint in content or content in original_hint):
                            sec_idx = s["index"]
                            break

                if sec_idx is None:
                    for s in sections_list:
                        if s["section_name"] == step_name:
                            sec_idx = s["index"]
                            break

                if sec_idx is None:
                    self.log_step(task_id, user_id, "error", f"物理替换失败：未能在简历分段数据中找到段落 {step_name}")
                    step["status"] = "COMPLETED"
                    self.db.update_agent_resume_task_status(
                        task_id=task_id, user_id=user_id, status="RUNNING",
                        execution_plan=dump_plan()
                    )
                    continue

                replace_res = await asyncio.to_thread(
                    tool_replace_resume_section,
                    user_id,
                    task_id,
                    sec_idx,
                    current_content,
                    step_goal
                )
                self.log_step(task_id, user_id, "info", f"物理替换更新已落盘。反馈: {replace_res}")

                # 将步骤标记为 COMPLETED，并写回执行计划
                step["status"] = "COMPLETED"
                self.db.update_agent_resume_task_status(
                    task_id=task_id,
                    user_id=user_id,
                    status="RUNNING",
                    execution_plan=dump_plan()
                )
                self.log_step(task_id, user_id, "info", f"模块 {step_name} 优化完成。")

            # 5. 组装输出最终的 optimized_resume.md
            self.log_step(task_id, user_id, "info", "所有步骤均已执行完毕，开始组装最终简历...")
            assembled_content = tool_read_file(user_id, task_id, "assembled_resume.txt")
            if "错误：" in assembled_content:
                sections_json = tool_read_file(user_id, task_id, "resume_sections.json")
                if "错误：" in sections_json:
                    assembled_content = resume_text
                else:
                    try:
                        assembled_content = "\n".join(sec.get("content", "") for sec in json.loads(sections_json))
                    except Exception:
                        assembled_content = resume_text
                tool_write_file(user_id, task_id, "assembled_resume.txt", assembled_content)

            # 读取修改日志并生成摘要头部
            log_json = tool_read_file(user_id, task_id, "modification_log.json")
            summary_header = "# 简历优化修改摘要\n\n"
            if "错误：" not in log_json:
                try:
                    mod_logs = json.loads(log_json)
                    for item in mod_logs:
                        summary_header += f"- **{item.get('section_name', '段落')}**: {item.get('reason', '针对性润色')}\n"
                except Exception:
                    summary_header += "- 部分模块已根据 JD 进行了针对性优化与修辞润色\n"
            else:
                summary_header += "- 部分模块已根据 JD 进行了针对性优化与修辞润色\n"

            final_resume_md = f"{summary_header}\n\n{assembled_content}"
            tool_write_file(user_id, task_id, "optimized_resume.md", final_resume_md)

            # 生成修改对照表 modification_diff.md
            await asyncio.to_thread(tool_generate_modification_diff, user_id, task_id)

            # 进行高保真 DOCX 替换或回退到 Pandoc 转换
            try:
                self.log_step(task_id, user_id, "info", "正在利用原始简历模板进行高保真段落替换...")
                replaced_docx = update_docx_resume_from_log(user_id, task_id)
                if replaced_docx:
                    self.log_step(task_id, user_id, "info", "成功生成高保真排版保留 DOCX 格式简历。")
                else:
                    self.log_step(task_id, user_id, "info", "未能完成原模板替换，正在使用样式配置生成 DOCX 兜底文件...")
                    md_path = get_safe_workspace_path(user_id, task_id, "optimized_resume.md")
                    docx_path = get_safe_workspace_path(user_id, task_id, "optimized_resume.docx")
                    try:
                        generate_docx_from_markdown(user_id, task_id, final_resume_md, docx_path)
                        self.log_step(task_id, user_id, "info", "已生成样式兜底 DOCX：optimized_resume.docx")
                    except Exception as gen_err:
                        self.log_step(task_id, user_id, "warning", f"python-docx 兜底生成失败，回退到 Pandoc：{gen_err}")
                        import subprocess
                        result = subprocess.run(
                            ["pandoc", md_path, "-o", docx_path],
                            capture_output=True, text=True, timeout=30
                        )
                        if result.returncode == 0:
                            self.log_step(task_id, user_id, "info", "已自动将简历转换为 DOCX 格式：optimized_resume.docx")
                        else:
                            self.log_step(task_id, user_id, "warning", f"DOCX 转换失败（非致命）：{result.stderr}")
            except FileNotFoundError:
                self.log_step(task_id, user_id, "info", "未检测到 pandoc，跳过 DOCX 转换。最终简历为 Markdown 格式。")
            except Exception as e:
                self.log_step(task_id, user_id, "warning", f"高保真 DOCX 段落替换或格式处理失败：{str(e)}")

            # 5.5 版面审计与环境强校验
            self.log_step(task_id, user_id, "info", "开始进行版面审计与环境依赖校验...")
            env_ok, missing_desc = check_layout_dependencies()
            if not env_ok:
                self.log_step(
                    task_id,
                    user_id,
                    "warning",
                    f"版面视觉审计依赖缺失，已跳过该审计但保留可下载简历。缺失组件：{missing_desc}"
                )
            else:
                # 环境校验通过，进行图片渲染与多模态审计
                docx_path = get_safe_workspace_path(user_id, task_id, "optimized_resume.docx")
                if not os.path.exists(docx_path):
                    self.log_step(task_id, user_id, "warning", "未找到生成的 optimized_resume.docx 文件，跳过版面视觉审计。")
                else:
                    try:
                        self.log_step(task_id, user_id, "info", "正在将 DOCX 转换为 PDF 并渲染为图片...")
                        page_image_paths = render_docx_to_images(user_id, task_id, docx_path)

                        self.log_step(task_id, user_id, "info", f"成功渲染 {len(page_image_paths)} 页图片，开始启动 LayoutAuditor 版面审计智能体...")
                        auditor = LayoutAuditor()
                        audit_res = await auditor.audit_layout(page_image_paths)

                        score = audit_res.get("score", 100)
                        issues = audit_res.get("issues", [])
                        self.log_step(task_id, user_id, "info", f"【版面审计完成】排版得分: {score}分，细节意见: {issues}")
                    except Exception as audit_err:
                        self.log_step(task_id, user_id, "warning", f"版面审计过程中发生错误：{audit_err}")

            # 6. 将任务状态更新为 COMPLETED，保存最终简历 md
            self.current_status = "COMPLETED"
            self.db.update_agent_resume_task_status(
                task_id=task_id,
                user_id=user_id,
                status="COMPLETED",
                logs=json.dumps(self.logs, ensure_ascii=False),
                optimized_resume_md=final_resume_md,
                execution_plan=dump_plan()
            )
            self.log_step(task_id, user_id, "info", "优化流水线执行全部完成！")

        except HumanInteractionRequired as hitl_exc:
            # 人机交互挂起属于正常的正常工作流挂起状态，必须直接向上抛出，使线程安全释放
            self.current_status = "WAITING_FOR_HUMAN"
            raise hitl_exc

        except Exception as exc:
            # 记录致命的错误，修改任务状态为 FAILED，并把异常抛出
            self.current_status = "FAILED"
            err_msg = str(exc)
            stack = traceback.format_exc()
            print(f"[ORCHESTRATOR_ERROR] Task {task_id} failed: {err_msg}\n{stack}")
            self.log_step(
                task_id,
                user_id,
                "error",
                f"Agent 运行发生致命错误：{err_msg}",
                stage="orchestration",
                agent=self.role,
                status="failed",
                error_type=exc.__class__.__name__,
            )
            try:
                failure_updates: Dict[str, Any] = {
                    "task_id": task_id,
                    "user_id": user_id,
                    "status": "FAILED",
                    "error_message": err_msg,
                    "logs": json.dumps(self.logs, ensure_ascii=False),
                }
                if isinstance(plan, dict):
                    failure_updates["execution_plan"] = dump_plan()
                self.db.update_agent_resume_task_status(**failure_updates)
            except Exception as db_err:
                print(f"[ORCHESTRATOR] Failed to save final failure state: {db_err}")
            raise exc
