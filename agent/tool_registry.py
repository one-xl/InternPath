"""
工具注册中心与全局异常防护执行引擎 (Tool Registry & Safety Execution Engine)
负责工具的动态注册、Schema 导出与全局统一的安全调用机制。
内置【项目级工具异常拦截器 (Project-wide Tool Exception Interceptor)】：
拦截所有工具运行过程中的未知异常、超时、语法错误与除零错，
精准测量精确毫秒级 execution_time 耗时，并生成结构化的 Trace 结果！
"""

import time
import logging
import traceback
from typing import Dict, Any, List, Callable, Optional
from agent.schema import ToolResult

logger = logging.getLogger(__name__)


class RegisteredTool:
    """包装已注册工具，暴露 name 属性与 execute() 执行接口"""
    def __init__(self, name: str, func: Callable, registry: "ToolRegistry"):
        self.name = name
        self.func = func
        self.registry = registry

    def execute(self, arguments: Dict[str, Any], call_id: str = "") -> ToolResult:
        return self.registry.execute_tool(self.name, arguments, call_id)

    def __call__(self, *args, **kwargs):
        return self.func(*args, **kwargs)


class ToolRegistry:
    """
    Agent 工具注册与全局安全执行中心
    """

    def __init__(self):
        self._tools: Dict[str, Callable] = {}
        self._schemas: Dict[str, Dict[str, Any]] = {}

    def register_tool(self, name: str, func: Callable, schema: Dict[str, Any]) -> None:
        """注册通用工具及其标准 JSON Schema"""
        self._tools[name] = func
        
        # 统一规范：确保所有工具 Schema 在存储时均符合标准 OpenAI Tool Call schema 格式 (type: function)
        if isinstance(schema, dict) and schema.get("type") == "function" and "function" in schema:
            normalized_schema = schema
        else:
            doc = func.__doc__.strip().split('\n')[0] if func and func.__doc__ else f"Tool {name}"
            normalized_schema = {
                "type": "function",
                "function": {
                    "name": name,
                    "description": doc,
                    "parameters": schema
                }
            }
        
        self._schemas[name] = normalized_schema
        logger.info(f"成功注册 Agent 工具 [{name}]")

    def register(
        self,
        name: str,
        description: str = "",
        parameters: Optional[Dict[str, Any]] = None,
        fn: Optional[Callable] = None,
        func: Optional[Callable] = None,
        schema: Optional[Dict[str, Any]] = None,
    ) -> None:
        """兼容性注册接口"""
        target_func = fn or func
        raw_schema = parameters or schema
        
        if raw_schema:
            if isinstance(raw_schema, dict) and raw_schema.get("type") == "function" and "function" in raw_schema:
                target_schema = raw_schema
            else:
                doc_desc = target_func.__doc__.strip().split('\n')[0] if target_func and target_func.__doc__ else f"Tool {name}"
                target_schema = {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": description or doc_desc,
                        "parameters": raw_schema
                    }
                }
        else:
            doc_desc = target_func.__doc__.strip().split('\n')[0] if target_func and target_func.__doc__ else f"Tool {name}"
            target_schema = {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description or doc_desc,
                    "parameters": {"type": "object", "properties": {}},
                },
            }
            
        if target_func:
            self.register_tool(name, target_func, target_schema)

    def list_tools(self) -> List[RegisteredTool]:
        """获取包含 .name 属性的已注册工具列表"""
        return [RegisteredTool(name, func, self) for name, func in self._tools.items()]

    def get_tool(self, name: str) -> Optional[RegisteredTool]:
        """按工具名获取关联的 RegisteredTool 包装对象"""
        if name not in self._tools:
            return None
        return RegisteredTool(name, self._tools[name], self)

    def get_all_schemas(self) -> List[Dict[str, Any]]:
        """导出当前系统中所有注册工具的标准 JSON Schema 列表"""
        return list(self._schemas.values())

    def get_openai_schemas(self) -> List[Dict[str, Any]]:
        """兼容性导出 OpenAI 架构方法"""
        return self.get_all_schemas()

    def execute_tool(self, name: str, arguments: Dict[str, Any], call_id: str = "") -> ToolResult:
        """
        全局统一安全工具执行引擎：
        1. 自动测量精确执行耗时 (execution_time)。
        2. 全局拦截任意工具抛出的未捕获异常，确保 Agent 进程永不崩塌。
        3. 导出结构化的 ToolResult Trace 痕迹对象。
        """
        start_time = time.time()

        if name not in self._tools:
            elapsed = time.time() - start_time
            err_msg = f"未找到名为 [{name}] 的已注册工具。可选工具: {list(self._tools.keys())}"
            logger.warning(f"全局工具执行拦截: {err_msg}")
            return ToolResult(
                call_id=call_id,
                name=name,
                output=err_msg,
                is_error=True,
                execution_time=round(elapsed, 4),
            )

        tool_func = self._tools[name]
        try:
            logger.info(f"▶ 开始安全执行全局工具 [{name}] | 参数: {arguments}")

            if isinstance(arguments, dict):
                raw_output = tool_func(**arguments)
            else:
                raw_output = tool_func(arguments)

            elapsed = time.time() - start_time
            output_str = str(raw_output) if raw_output is not None else "执行完成（无输出）"

            logger.info(f"✔ 全局工具 [{name}] 执行成功 | 耗时: {elapsed:.4f}s")
            return ToolResult(
                call_id=call_id,
                name=name,
                output=output_str,
                is_error=False,
                execution_time=round(elapsed, 4),
            )

        except Exception as e:
            elapsed = time.time() - start_time
            stack_trace = traceback.format_exc()
            err_output = f"工具 [{name}] 执行异常: {str(e)}"
            logger.error(f"❌ 全局工具 [{name}] 捕获运行异常:\n{stack_trace}")

            return ToolResult(
                call_id=call_id,
                name=name,
                output=err_output,
                is_error=True,
                execution_time=round(elapsed, 4),
            )
