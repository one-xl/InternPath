"""
待办事项管理工具 (Todo Tool)
支持多 Session 隔离的增删查改待办事项存储
"""

import json
import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class TodoStore:
    """内存与多 Session 隔离的 Todo 存储器"""

    def __init__(self):
        self._store: Dict[str, List[str]] = {}

    def add_todo(self, session_id: str, content: str) -> str:
        if session_id not in self._store:
            self._store[session_id] = []
        if content not in self._store[session_id]:
            self._store[session_id].append(content)
        return f"已成功为当前窗口添加待办事项: {content}"

    def list_todos(self, session_id: str) -> List[str]:
        return self._store.get(session_id, [])

    def remove_todo(self, session_id: str, index: int) -> str:
        todos = self.list_todos(session_id)
        target_idx = index - 1 if index >= 1 else index
        if 0 <= target_idx < len(todos):
            removed = todos.pop(target_idx)
            return f"已移除待办 #{index}: {removed}"
        return f"删除失败：无效的索引 {index}"

    def clear(self, session_id: str) -> None:
        if session_id in self._store:
            self._store[session_id] = []


global_todo_store = TodoStore()


def manage_todo(action: str, content: Optional[str] = None, session_id: str = "default", index: Optional[int] = None) -> str:
    """
    待办事项工具入口函数
    :param action: 操作类型 'add', 'list', 'remove'
    :param content: 待办文本 (add 时使用)
    :param session_id: Session 窗口标识
    :param index: 要删除的索引 (remove 时使用)
    :return: 文本说明
    """
    action_lower = action.lower() if action else "list"

    if action_lower == "add":
        if not content:
            return "添加待办失败：未提供 content 内容"
        return global_todo_store.add_todo(session_id, content)

    elif action_lower == "list":
        todos = global_todo_store.list_todos(session_id)
        if not todos:
            return "当前暂无待办事项。"
        formatted = [f"{i+1}. {item}" for i, item in enumerate(todos)]
        return "\n".join(formatted)

    elif action_lower == "remove":
        if index is None:
            return "删除待办失败：未提供 index 索引"
        res = global_todo_store.remove_todo(session_id, index)
        if "删除失败" in res:
            return "错误：无效的索引"
        return res

    return f"未知操作类型: {action}"


# 别名兼容
handle_todo = manage_todo

TODO_SCHEMA = {
    "type": "function",
    "function": {
        "name": "todo",
        "description": "管理个人待办事项。支持 'add'(添加待办), 'list'(列出所有待办), 'remove'(删除待办)。",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "list", "remove"],
                    "description": "操作类型：'add' | 'list' | 'remove'",
                },
                "content": {
                    "type": "string",
                    "description": "待办事项的具体内容 (action='add' 时必填)",
                },
                "session_id": {
                    "type": "string",
                    "description": "当前对话窗口 Session 标识",
                },
                "index": {
                    "type": "integer",
                    "description": "要删除的待办事项索引 (action='remove' 时必填，从 1 开始)",
                },
            },
            "required": ["action"],
        },
    },
}
