"""
内置工具集合模块
暴露所有基础工具并提供 register_default_tools 便捷注册方法。
"""

from agent.tool_registry import ToolRegistry
from tools.calculator import calculate, CALCULATOR_SCHEMA
from tools.search import search, SEARCH_SCHEMA
from tools.todo import manage_todo, TODO_SCHEMA, global_todo_store
from tools.weather import get_weather, WEATHER_SCHEMA


def register_default_tools(registry: ToolRegistry) -> None:
    """注册所有默认内置工具到 ToolRegistry"""
    registry.register(
        name="calculator",
        description="计算数学表达式，如 12 * (34 + 56) 或 2**10",
        parameters=CALCULATOR_SCHEMA,
        fn=calculate,
    )
    registry.register(
        name="search",
        description="搜索互联网或内部知识库，获取最新信息与资料",
        parameters=SEARCH_SCHEMA,
        fn=search,
    )
    registry.register(
        name="todo",
        description="管理个人或窗口待办事项，支持 'add'(添加), 'list'(查看), 'remove'(删除)",
        parameters=TODO_SCHEMA,
        fn=manage_todo,
    )
    registry.register(
        name="weather",
        description="查询指定城市实时天气和温度状况",
        parameters=WEATHER_SCHEMA,
        fn=get_weather,
    )
