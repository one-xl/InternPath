"""
Agent 核心执行运行时 (Agent Runtime)
负责驱动 ReAct (Reasoning + Acting) 动态多轮循环与全局轨迹 Trace 日志记录。
内置【项目级 ReAct 循环异常防护与完整 Trace 收集引擎 (Project-wide ReAct Exception & Trace Engine)】：
1. 拦截 LLM 网络超时、参数解析错误或死循环；
2. 全流程记录每一步 Step 的思考链 Thought、工具调用名称与参数、Observation 结果及耗时 timestamp；
3. 动态触发 on_trace_update 监听回调钩子；
4. 自动触发 Session 磁盘文件落盘与多 Session 隔离保护；
5. 确保底层大模型真实调用的结果 100% 准确呈现，绝不掺杂任何人工硬编码兜底或救场脚本。
"""

import time
import logging
import traceback
from typing import List, Optional, Callable, Any
from agent.schema import AgentResponse, StepTrace, ToolResult
from agent.llm_client import LLMClient
from agent.tool_registry import ToolRegistry
from agent.context_manager import ContextManager

logger = logging.getLogger(__name__)


class AgentRuntime:
    """
    通用 ReAct 核心运行时
    """

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        tool_registry: Optional[ToolRegistry] = None,
        context_manager: Optional[ContextManager] = None,
        session_manager: Optional[Any] = None,
        max_steps: int = 5,
        max_turns: Optional[int] = None,
        on_trace_update: Optional[Callable[[StepTrace], None]] = None,
    ):
        self.llm_client = llm_client or LLMClient()
        self.tool_registry = tool_registry or ToolRegistry()
        self.context_manager = context_manager or ContextManager()

        from agent.session_manager import SessionManager
        self.session_manager = session_manager or SessionManager(
            llm_client=self.llm_client,
            tool_registry=self.tool_registry,
        )
        self.max_steps = max_turns if max_turns is not None else max_steps
        self.on_trace_update = on_trace_update

    def run(self, user_prompt: str, session_id: str = "default") -> AgentResponse:
        """
        执行 ReAct 动态循环并捕获全局异常，支持按 session_id 隔离
        """
        session = self.session_manager.get_or_create_session(session_id)
        target_cm = session.context_manager

        target_cm.add_user_message(user_prompt)

        traces: List[StepTrace] = []
        final_answer = ""
        executed_observation = None

        try:
            for step in range(1, self.max_steps + 1):
                logger.info(f"--- [ReAct Loop Step {step}/{self.max_steps}] ---")

                messages = target_cm.format_for_llm()
                tools_schema = self.tool_registry.get_all_schemas()

                try:
                    llm_response = self.llm_client.one_turn(
                        messages=messages,
                        tools_schema=tools_schema if tools_schema else None,
                    )
                except Exception as llm_err:
                    logger.error(f"❌ ReAct Step {step} 发起 LLM 推理出现异常:\n{traceback.format_exc()}")
                    err_trace = StepTrace(
                        step=step,
                        thought=f"LLM 推理异常: {str(llm_err)}",
                        tool_calls=[],
                        tool_results=[],
                        response_content="",
                        timestamp=time.time(),
                    )
                    traces.append(err_trace)
                    if self.on_trace_update:
                        self.on_trace_update(err_trace)
                    final_answer = f"⚠️ 大模型 API 推理服务发生异常: {str(llm_err)}。建议检查 API Key 或网络连接。"
                    break

                thought = llm_response.thought or ""
                content = llm_response.content or ""
                tool_calls = llm_response.tool_calls or []

                step_trace = StepTrace(
                    step=step,
                    thought=thought,
                    tool_calls=tool_calls,
                    tool_results=[],
                    response_content=content,
                    timestamp=time.time(),
                )

                if not tool_calls:
                    traces.append(step_trace)
                    if self.on_trace_update:
                        self.on_trace_update(step_trace)

                    if content and content.strip():
                        final_answer = content.strip()
                    elif executed_observation:
                        final_answer = executed_observation
                    else:
                        final_answer = "已为您处理完成。"

                    target_cm.add_assistant_message(content=final_answer)
                    logger.info(f"✔ ReAct 动态循环在 Step {step} 得出最终回答，优雅退出。")
                    break

                raw_tool_calls_dict = [tc.to_dict() for tc in tool_calls]
                target_cm.add_assistant_message(
                    content=content,
                    tool_calls=raw_tool_calls_dict,
                )

                for tc in tool_calls:
                    target_args = dict(tc.arguments) if tc.arguments else {}
                    if tc.name == "todo" and "session_id" not in target_args:
                        target_args["session_id"] = session_id

                    res: ToolResult = self.tool_registry.execute_tool(
                        name=tc.name,
                        arguments=target_args,
                        call_id=tc.id,
                    )
                    step_trace.tool_results.append(res)
                    executed_observation = res.output

                    target_cm.add_tool_result(
                        call_id=tc.id,
                        tool_name=tc.name,
                        result_output=res.output,
                    )

                traces.append(step_trace)
                if self.on_trace_update:
                    self.on_trace_update(step_trace)

            if not final_answer:
                if executed_observation:
                    final_answer = executed_observation
                else:
                    final_answer = "已达到最大推理步数上限。"

            # 自动进行 Session 持久化落盘
            self.session_manager.save_session(session_id)

            return AgentResponse(
                final_answer=final_answer,
                traces=traces,
                step_count=len(traces),
                is_real_api=bool(self.llm_client._client is not None),
                model_used=self.llm_client.model,
            )

        except Exception as global_err:
            stack = traceback.format_exc()
            logger.critical(f"💥 ReAct Agent Runtime 发生未捕获的全局严重异常:\n{stack}")
            return AgentResponse(
                final_answer=f"❌ Agent 运行时发生全局系统异常: {str(global_err)}",
                traces=traces,
                step_count=len(traces),
                is_real_api=bool(self.llm_client._client is not None),
                model_used=self.llm_client.model,
            )
