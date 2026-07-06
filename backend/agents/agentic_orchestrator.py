from __future__ import annotations

import asyncio
import json
import time
import traceback
from typing import Any, Optional

from ai_analyzer import AIAnalyzer
from backend.agents.orchestrator import Orchestrator
from backend.agents.tool_loop import (
    AgenticToolLoop,
    ResponsesJsonActionModelTurn,
    ResponsesNativeToolModelTurn,
)
from backend.agents.tool_registry import AgentToolContext, DEFAULT_AGENT_TOOL_REGISTRY
from backend.agents.tools.docx_tools import materialize_original_resume_file
from backend.agents.tools.hitl_tool import HumanInteractionRequired
from backend.agents.tools.workspace_tools import tool_read_file, tool_write_file


class AgenticOrchestrator(Orchestrator):
    async def run_orchestration(
        self,
        task_id: str,
        user_id: Any,
        config_id: Optional[str],
        is_co_pilot: bool = True,
        tool_calling_mode: str = "auto",
    ) -> None:
        self.logs = []
        self.current_status = "RUNNING"
        plan_data: dict[str, Any] = {}

        try:
            task = self.db.get_agent_resume_task(user_id, task_id)
            if not task:
                raise ValueError(f"Agentic resume task does not exist: {task_id}")
            self.trace_id = str(task.get("trace_id") or task_id)

            plan_data = self._load_plan(task.get("execution_plan"))
            if config_id is None:
                config_id = plan_data.get("config_id")

            normalized_tool_mode = str(tool_calling_mode or "auto").strip().lower().replace("-", "_")
            effective_tool_mode = "native_responses" if normalized_tool_mode == "native_responses" else "json_action"
            plan_data["effective_tool_calling_mode"] = effective_tool_mode
            self._save_plan(task_id, user_id, plan_data, normalized_tool_mode, "RUNNING")
            self.log_step(
                task_id,
                user_id,
                "info",
                "Agentic tool loop is starting.",
                {
                    "execution_mode": "agentic",
                    "tool_calling_mode": normalized_tool_mode,
                    "effective_tool_calling_mode": effective_tool_mode,
                },
                stage="agentic_bootstrap",
                agent="AgenticOrchestrator",
                status="running",
            )

            resume_id = task.get("resume_id")
            resume_data = self.db.get_user_resume(user_id, resume_id)
            if not resume_data:
                raise ValueError("Resume record was not found for this task.")
            resume_text = resume_data.get("cleanedText") or resume_data.get("rawText") or ""
            jd_text = task.get("jd_text") or ""
            if not str(resume_text).strip():
                raise ValueError("Resume text is empty.")
            if not str(jd_text).strip():
                raise ValueError("JD text is empty.")

            tool_write_file(user_id, task_id, "original_resume.txt", resume_text)
            tool_write_file(user_id, task_id, "job_description.txt", jd_text)
            tool_write_file(user_id, task_id, "stream_preview.md", "Agentic tool loop started.")
            materialize_original_resume_file(user_id, task_id, resume_id, db=self.db)
            self.log_step(
                task_id,
                user_id,
                "info",
                "Workspace files are ready for the agentic tool loop.",
                {
                    "resume_characters": len(resume_text),
                    "jd_characters": len(jd_text),
                },
                stage="workspace",
                agent="AgenticOrchestrator",
            )

            analyzer = AIAnalyzer()
            openai_client, resolved_cfg_id, provider, model_id = await asyncio.to_thread(
                analyzer._client,
                user_id,
                config_id,
                True,
            )
            self.openai_client = openai_client
            self.model = model_id
            plan_data["config_id"] = resolved_cfg_id or config_id
            plan_data["is_co_pilot"] = is_co_pilot
            self._save_plan(task_id, user_id, plan_data, normalized_tool_mode, "RUNNING")
            self.log_step(
                task_id,
                user_id,
                "info",
                "Resolved model configuration for agentic mode.",
                {
                    "provider": provider,
                    "config_id": resolved_cfg_id or config_id,
                    "model_id": model_id,
                },
                stage="model_config",
                agent="AIAnalyzer",
                model_id=model_id,
            )

            loop = AgenticToolLoop(DEFAULT_AGENT_TOOL_REGISTRY)
            ctx = AgentToolContext(
                user_id=user_id,
                task_id=task_id,
                resume_text=resume_text,
                jd_text=jd_text,
                is_co_pilot=is_co_pilot,
            )
            retry_failure_point = plan_data.get("retry_request") if isinstance(plan_data.get("retry_request"), dict) else None
            started_at = time.perf_counter()
            if effective_tool_mode == "native_responses":
                model_turn = ResponsesNativeToolModelTurn(
                    openai_client,
                    model_id,
                    tools=DEFAULT_AGENT_TOOL_REGISTRY.responses_tools(is_co_pilot=is_co_pilot),
                    namespace="agentic_resume_native_tools",
                    temperature=0.1,
                )
                result = loop.run_native_responses_loop(
                    ctx,
                    model_turn,
                    event_sink=self._event_sink(task_id, user_id, plan_data, normalized_tool_mode),
                    retry_failure_point=retry_failure_point,
                )
            else:
                model_turn = ResponsesJsonActionModelTurn(
                    openai_client,
                    model_id,
                    namespace="agentic_resume_json_action",
                    temperature=0.1,
                )
                result = loop.run_json_action_loop(
                    ctx,
                    model_turn,
                    event_sink=self._event_sink(task_id, user_id, plan_data, normalized_tool_mode),
                    retry_failure_point=retry_failure_point,
                )
            duration_ms = int((time.perf_counter() - started_at) * 1000)

            if result.status == "needs_human":
                self.current_status = "WAITING_FOR_HUMAN"
                self._save_plan(task_id, user_id, plan_data, normalized_tool_mode, "WAITING_FOR_HUMAN")
                self.log_step(
                    task_id,
                    user_id,
                    "info",
                    "Agentic loop is waiting for user input.",
                    stage="human_required",
                    agent="AgenticOrchestrator",
                    duration_ms=duration_ms,
                    status="waiting",
                )
                return

            if result.status != "completed":
                raise RuntimeError(result.error or f"Agentic tool loop ended with status: {result.status}")

            loop_metrics = self._summarize_loop_events(result.events)
            if self._has_successful_tool_result(result.events, "finalize_resume_artifacts"):
                loop_metrics["skipped_duplicate_finalize"] = True
                loop_metrics["forced_finalize"] = False
            else:
                finalize_started_at = time.perf_counter()
                finalize_result = DEFAULT_AGENT_TOOL_REGISTRY.execute("finalize_resume_artifacts", {}, ctx)
                loop_metrics["forced_finalize"] = True
                loop_metrics["skipped_duplicate_finalize"] = False
                loop_metrics["manual_finalize_ok"] = bool(finalize_result.get("ok"))
                loop_metrics["manual_finalize_duration_ms"] = int((time.perf_counter() - finalize_started_at) * 1000)
            plan_data["agentic_metrics"] = loop_metrics
            final_resume_md = self._read_final_markdown(user_id, task_id, resume_text)
            self.current_status = "COMPLETED"
            self._save_plan(task_id, user_id, plan_data, normalized_tool_mode, "COMPLETED")
            self.db.update_agent_resume_task_status(
                task_id=task_id,
                user_id=user_id,
                status="COMPLETED",
                logs=json.dumps(self.logs, ensure_ascii=False),
                optimized_resume_md=final_resume_md,
                execution_plan=json.dumps(plan_data, ensure_ascii=False),
            )
            self.log_step(
                task_id,
                user_id,
                "info",
                "Agentic tool loop completed.",
                {
                    "turns": result.turns,
                    "duration_ms": duration_ms,
                    "agentic_metrics": loop_metrics,
                },
                stage="finalize",
                agent="AgenticOrchestrator",
                duration_ms=duration_ms,
            )

        except HumanInteractionRequired:
            self.current_status = "WAITING_FOR_HUMAN"
            raise
        except Exception as exc:
            self.current_status = "FAILED"
            err_msg = str(exc)
            print(f"[AGENTIC_ORCHESTRATOR_ERROR] Task {task_id} failed: {err_msg}\n{traceback.format_exc()}")
            self.log_step(
                task_id,
                user_id,
                "error",
                f"Agentic tool loop failed: {err_msg}",
                stage="agentic",
                agent="AgenticOrchestrator",
                status="failed",
                error_type=exc.__class__.__name__,
            )
            self.db.update_agent_resume_task_status(
                task_id=task_id,
                user_id=user_id,
                status="FAILED",
                error_message=err_msg,
                logs=json.dumps(self.logs, ensure_ascii=False),
                execution_plan=json.dumps(plan_data, ensure_ascii=False) if plan_data else None,
            )
            raise

    def _event_sink(
        self,
        task_id: str,
        user_id: Any,
        plan_data: dict[str, Any] | None = None,
        tool_calling_mode: str = "auto",
    ):
        last_tool_call: dict[str, Any] = {}

        def sink(event: dict[str, Any]) -> None:
            event_type = str(event.get("type") or "")
            turn = event.get("turn")
            if event_type == "model_turn_start":
                self.log_step(
                    task_id,
                    user_id,
                    "thought",
                    f"Model turn {turn} started.",
                    event,
                    stage="model_turn",
                    agent="AgenticToolLoop",
                    status="running",
                )
                return
            if event_type == "model_delta":
                content = str(event.get("content") or "")
                mode = str(event.get("mode") or "")
                self.log_step(
                    task_id,
                    user_id,
                    "thought",
                    f"Model returned {'native Responses output' if mode == 'native_responses' else 'JSON action'} for turn {turn}.",
                    {"content": content[:4000]},
                    stage="model_delta",
                    agent="AgenticToolLoop",
                )
                return
            if event_type == "model_stream_delta":
                content = str(event.get("content") or "")
                total_chars = int(event.get("total_chars") or len(content))
                self.log_step(
                    task_id,
                    user_id,
                    "thought",
                    f"模型正在流式输出公开动作（{total_chars} public characters received）.",
                    {
                        "content": content[:1200],
                        "total_chars": total_chars,
                        "final": bool(event.get("final")),
                        "mode": str(event.get("mode") or ""),
                    },
                    stage="model_stream_delta",
                    agent="AgenticToolLoop",
                    status="running",
                )
                return
            if event_type == "provider_usage":
                self.log_step(
                    task_id,
                    user_id,
                    "info",
                    "Provider usage was reported for agentic model turn.",
                    stage="provider_usage",
                    agent="AgenticToolLoop",
                    model_id=str(event.get("providerModel") or self.model or ""),
                    provider_cache=event,
                )
                return
            if event_type == "tool_call":
                tool_name = str(event.get("tool_name") or "")
                is_bootstrap = bool(event.get("bootstrap"))
                last_tool_call.clear()
                last_tool_call.update({
                    "tool_name": tool_name,
                    "arguments": event.get("arguments") or {},
                    "turn": turn,
                    "bootstrap": is_bootstrap,
                })
                self.log_step(
                    task_id,
                    user_id,
                    "tool_call",
                    f"{'Bootstrap tool' if is_bootstrap else 'Calling tool'}: {tool_name}",
                    {
                        "tool_name": tool_name,
                        "arguments": event.get("arguments") or {},
                        "bootstrap": is_bootstrap,
                        "bootstrap_index": event.get("bootstrap_index"),
                    },
                    stage="tool_call",
                    agent="AgenticToolLoop",
                    status="running",
                )
                return
            if event_type == "tool_result":
                tool_name = str(event.get("tool_name") or "")
                ok = bool(event.get("ok"))
                waiting_for_human = tool_name == "ask_user_for_fact"
                self._refresh_stream_preview_after_tool(user_id, task_id, tool_name, ok)
                if not ok and not waiting_for_human and plan_data is not None:
                    arguments = last_tool_call.get("arguments") if last_tool_call.get("tool_name") == tool_name else {}
                    self._record_failure_point(
                        task_id,
                        user_id,
                        plan_data,
                        {
                            "failed_stage": "tool_result",
                            "failed_tool_name": tool_name,
                            "failed_tool_arguments": arguments or {},
                            "failed_model_input_ref": f"turn:{turn or last_tool_call.get('turn') or ''}",
                            "failed_sequence": len(self.logs) + 1,
                            "error": event.get("error") or "",
                        },
                        tool_calling_mode=tool_calling_mode,
                    )
                self.log_step(
                    task_id,
                    user_id,
                    "tool_response" if ok or waiting_for_human else "error",
                    f"Tool {tool_name} {'is waiting for user input' if waiting_for_human else ('completed' if ok else 'failed')}.",
                    event,
                    stage="tool_result",
                    agent="AgenticToolLoop",
                    duration_ms=int(event.get("duration_ms") or 0),
                    status="waiting" if waiting_for_human else ("completed" if ok else "failed"),
                    error_type="" if ok or waiting_for_human else "ToolExecutionError",
                )
                return
            if event_type == "error":
                if plan_data is not None:
                    self._record_failure_point(
                        task_id,
                        user_id,
                        plan_data,
                        {
                            "failed_stage": str(event.get("stage") or "agentic"),
                            "failed_tool_name": str(last_tool_call.get("tool_name") or ""),
                            "failed_tool_arguments": last_tool_call.get("arguments") or {},
                            "failed_model_input_ref": f"turn:{turn or last_tool_call.get('turn') or ''}",
                            "failed_sequence": len(self.logs) + 1,
                            "error": event.get("error") or "",
                            "failed_model_input": event.get("failed_model_input") if isinstance(event.get("failed_model_input"), dict) else {},
                            "last_successful_tool_result": event.get("last_successful_tool_result") if isinstance(event.get("last_successful_tool_result"), dict) else {},
                        },
                        tool_calling_mode=tool_calling_mode,
                    )
                self.log_step(
                    task_id,
                    user_id,
                    "error",
                    str(event.get("error") or "Agentic loop error."),
                    event,
                    stage="agentic",
                    agent="AgenticToolLoop",
                    status="failed",
                    error_type="AgenticLoopError",
                )
                return
            if event_type == "done":
                self.log_step(
                    task_id,
                    user_id,
                    "info",
                    "Model produced final answer.",
                    event,
                    stage="final_answer",
                    agent="AgenticToolLoop",
                )

        return sink

    @staticmethod
    def _has_successful_tool_result(events: list[dict[str, Any]], tool_name: str) -> bool:
        return any(
            event.get("type") == "tool_result"
            and event.get("tool_name") == tool_name
            and bool(event.get("ok"))
            for event in events
        )

    @classmethod
    def _summarize_loop_events(cls, events: list[dict[str, Any]]) -> dict[str, Any]:
        metrics = {
            "model_turns": 0,
            "model_delta_events": 0,
            "provider_usage_events": 0,
            "tool_calls": 0,
            "tool_results": 0,
            "successful_tool_results": 0,
            "failed_tool_results": 0,
            "tool_duration_ms": 0,
            "finalize_already_completed": cls._has_successful_tool_result(events, "finalize_resume_artifacts"),
        }
        for event in events:
            event_type = str(event.get("type") or "")
            if event_type == "model_turn_start":
                metrics["model_turns"] += 1
            elif event_type == "model_delta":
                metrics["model_delta_events"] += 1
            elif event_type == "provider_usage":
                metrics["provider_usage_events"] += 1
            elif event_type == "tool_call":
                metrics["tool_calls"] += 1
            elif event_type == "tool_result":
                metrics["tool_results"] += 1
                if event.get("ok"):
                    metrics["successful_tool_results"] += 1
                else:
                    metrics["failed_tool_results"] += 1
                try:
                    metrics["tool_duration_ms"] += int(event.get("duration_ms") or 0)
                except (TypeError, ValueError):
                    pass
        return metrics

    def _refresh_stream_preview_after_tool(self, user_id: Any, task_id: str, tool_name: str, ok: bool) -> None:
        if not ok or tool_name not in {"replace_resume_section", "finalize_resume_artifacts"}:
            return
        assembled = tool_read_file(user_id, task_id, "assembled_resume.txt")
        if assembled and not assembled.startswith("错误：") and not assembled.startswith("读取文件失败："):
            tool_write_file(user_id, task_id, "stream_preview.md", assembled)

    @staticmethod
    def _load_plan(raw_plan: Any) -> dict[str, Any]:
        if isinstance(raw_plan, dict):
            return raw_plan
        if not raw_plan:
            return {}
        try:
            parsed = json.loads(raw_plan)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _save_plan(
        self,
        task_id: str,
        user_id: Any,
        plan_data: dict[str, Any],
        tool_calling_mode: str,
        status: str,
    ) -> None:
        plan_data["bootstrap_only"] = bool(plan_data.get("bootstrap_only", True))
        plan_data["execution_mode"] = "agentic"
        plan_data["tool_calling_mode"] = tool_calling_mode if tool_calling_mode in {"auto", "json_action", "native_responses"} else "auto"
        plan_data["agentic_status"] = status
        plan_data.setdefault("steps", [])
        plan_data.setdefault("cache_stats", {"hits": 0, "misses": 0, "saved_model_calls": 0, "items": []})
        self.db.update_agent_resume_task_status(
            task_id=task_id,
            user_id=user_id,
            status=status,
            execution_plan=json.dumps(plan_data, ensure_ascii=False),
        )

    def _record_failure_point(
        self,
        task_id: str,
        user_id: Any,
        plan_data: dict[str, Any],
        failure_point: dict[str, Any],
        *,
        tool_calling_mode: str,
    ) -> None:
        previous = plan_data.get("failure_point") if isinstance(plan_data.get("failure_point"), dict) else {}
        retry_count = 0
        if isinstance(previous, dict):
            try:
                retry_count = int(previous.get("retry_count") or previous.get("retryCount") or 0)
            except (TypeError, ValueError):
                retry_count = 0
        normalized = {
            "failed_stage": str(failure_point.get("failed_stage") or "agentic"),
            "failed_tool_name": str(failure_point.get("failed_tool_name") or ""),
            "failed_tool_arguments": failure_point.get("failed_tool_arguments") if isinstance(failure_point.get("failed_tool_arguments"), dict) else {},
            "failed_model_input_ref": str(failure_point.get("failed_model_input_ref") or ""),
            "failed_sequence": int(failure_point.get("failed_sequence") or 0),
            "retry_count": retry_count,
            "error": str(failure_point.get("error") or ""),
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        if isinstance(failure_point.get("failed_model_input"), dict):
            normalized["failed_model_input"] = failure_point["failed_model_input"]
        if isinstance(failure_point.get("last_successful_tool_result"), dict):
            normalized["last_successful_tool_result"] = failure_point["last_successful_tool_result"]
        plan_data["failure_point"] = normalized
        plan_data["failed_stage"] = normalized["failed_stage"]
        plan_data["failed_tool_name"] = normalized["failed_tool_name"]
        plan_data["failed_tool_arguments"] = normalized["failed_tool_arguments"]
        plan_data["failed_model_input_ref"] = normalized["failed_model_input_ref"]
        plan_data["failed_sequence"] = normalized["failed_sequence"]
        self._save_plan(task_id, user_id, plan_data, tool_calling_mode, "RUNNING")

    @staticmethod
    def _read_final_markdown(user_id: Any, task_id: str, fallback_text: str) -> str:
        for filename in ("optimized_resume.md", "assembled_resume.txt"):
            text = tool_read_file(user_id, task_id, filename)
            if text and not text.startswith("错误：") and not text.startswith("读取文件失败："):
                if filename == "assembled_resume.txt":
                    tool_write_file(user_id, task_id, "optimized_resume.md", text)
                tool_write_file(user_id, task_id, "stream_preview.md", text)
                return text
        tool_write_file(user_id, task_id, "optimized_resume.md", fallback_text)
        tool_write_file(user_id, task_id, "stream_preview.md", fallback_text)
        return fallback_text
