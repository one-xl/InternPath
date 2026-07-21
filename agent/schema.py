"""
数据结构模型定义模块 (Schema)
定义 Message、ToolCall、ToolResult、TraceStep 及 Agent 执行输出结果。
支持别名兼容以保证测试集与全项目 100% 连贯无缝运行！
"""

import json
import time
from typing import Dict, Any, List, Optional, Literal
from pydantic import BaseModel, Field


def format_tool_calls_to_openai(tool_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """将多种异构/扁平工具调用结构统一转换为标准 OpenAI 要求的规范 json 格式，并序列化 arguments 字段"""
    openai_tool_calls = []
    for tc in tool_calls:
        if not isinstance(tc, dict):
            continue
        if "function" in tc and "type" in tc:
            func_data = tc.get("function") or {}
            args = func_data.get("arguments")
            if args is not None and not isinstance(args, str):
                func_data = dict(func_data)
                func_data["arguments"] = json.dumps(args, ensure_ascii=False)
                tc = dict(tc)
                tc["function"] = func_data
            openai_tool_calls.append(tc)
        else:
            tc_id = tc.get("id") or "call_default"
            name = tc.get("name")
            args = tc.get("arguments") or {}
            if not isinstance(args, str):
                args_str = json.dumps(args, ensure_ascii=False)
            else:
                args_str = args
            openai_tool_calls.append({
                "id": tc_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": args_str
                }
            })
    return openai_tool_calls


class Message(BaseModel):
    """对话消息标准结构"""
    role: Literal["system", "user", "assistant", "tool"] = Field(..., description="消息角色")
    content: Optional[str] = Field(None, description="消息文本内容")
    name: Optional[str] = Field(None, description="工具名称 (仅当 role 为 tool 时存在)")
    tool_call_id: Optional[str] = Field(None, description="Tool Call ID (用于 OpenAI 规范匹配)")
    tool_calls: Optional[List[Dict[str, Any]]] = Field(None, description="Assistant 调用的工具列表")

    def to_openai_format(self) -> Dict[str, Any]:
        """转换为标准 OpenAI API message 字典"""
        msg: Dict[str, Any] = {"role": self.role, "content": self.content or ""}
        if self.name and self.role == "tool":
            msg["name"] = self.name
        if self.tool_call_id:
            msg["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            msg["tool_calls"] = format_tool_calls_to_openai(self.tool_calls)
        return msg


class ToolCall(BaseModel):
    """工具调用解析结构"""
    id: str = Field(..., description="工具调用的唯一标识符")
    name: str = Field(..., description="工具名称")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="传给工具的实参字典")

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "name": self.name, "arguments": self.arguments}


class ToolResult(BaseModel):
    """工具执行结果结构"""
    call_id: str = Field(..., description="对应的 ToolCall ID")
    name: str = Field(..., description="调用的工具名称")
    output: str = Field(..., description="工具输出的字符串文本或JSON字符串")
    is_error: bool = Field(False, description="执行过程是否报错")
    execution_time: float = Field(0.0, description="执行耗时（秒）")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "call_id": self.call_id,
            "name": self.name,
            "output": self.output,
            "is_error": self.is_error,
            "execution_time": self.execution_time,
        }


class TraceStep(BaseModel):
    """单个步骤的 Execution Trace 记录"""
    step: int = Field(..., description="Loop 中的第几步步数 (从 1 开始)")
    thought: Optional[str] = Field(None, description="Agent 的思考链/推理过程")
    tool_calls: List[ToolCall] = Field(default_factory=list, description="本步调用的工具列表")
    tool_results: List[ToolResult] = Field(default_factory=list, description="工具调用的输出结果")
    response_content: Optional[str] = Field(None, description="本步最终生成的回答（若有）")
    timestamp: float = Field(default_factory=time.time, description="时间戳")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step": self.step,
            "thought": self.thought or "",
            "tool_calls": [tc.to_dict() for tc in self.tool_calls],
            "tool_results": [tr.to_dict() for tr in self.tool_results],
            "response_content": self.response_content or "",
            "timestamp": self.timestamp,
        }


# 别名兼容，防止拼写差异
StepTrace = TraceStep


class AgentResponse(BaseModel):
    """Agent 执行最终返回结果"""
    final_answer: str = Field(..., description="Agent 返回给用户的最终回答")
    turns_used: int = Field(1, description="消耗的总轮次/步骤数")
    step_count: Optional[int] = Field(None, description="别名兼容步骤数")
    traces: List[TraceStep] = Field(default_factory=list, description="完整的 Trace 执行步骤日志")
    is_real_api: bool = Field(False, description="是否使用真实大模型 API")
    model_used: str = Field("gpt-4o-mini", description="模型名称")

    def __init__(self, **data):
        if "step_count" in data and "turns_used" not in data:
            data["turns_used"] = data["step_count"]
        elif "turns_used" in data and "step_count" not in data:
            data["step_count"] = data["turns_used"]
        super().__init__(**data)


class LLMResponse(BaseModel):
    """LLM 单轮响应结果"""
    thought: Optional[str] = Field(None, description="思维链或思考过程")
    content: Optional[str] = Field(None, description="回复文本")
    tool_calls: Optional[List[ToolCall]] = Field(None, description="工具调用列表")

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)
