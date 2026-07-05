from __future__ import annotations

import os
import re
from typing import Any

from config import Config


def get_workspace_dir(user_id: Any, task_id: str) -> str:
    workspace_dir = os.path.abspath(
        os.path.join(Config.USER_DB_DIR, "workspaces", f"user_{user_id}", f"task_{task_id}")
    )
    os.makedirs(workspace_dir, exist_ok=True)
    return workspace_dir


def _validate_workspace_relative_path(filename: str) -> str:
    raw_name = str(filename or "").strip()
    if not raw_name:
        raise ValueError("文件名不能为空")
    if "\x00" in raw_name:
        raise ValueError("文件名包含非法字符")
    if os.path.isabs(raw_name) or os.path.splitdrive(raw_name)[0]:
        raise PermissionError(f"越权防护拦截：不允许使用绝对路径 {filename}")

    parts = [part for part in re.split(r"[\\/]+", raw_name) if part]
    if not parts or any(part in {".", ".."} for part in parts):
        raise PermissionError(f"越权防护拦截：不允许路径穿越或空路径片段 {filename}")
    if any(len(part) > 180 for part in parts):
        raise ValueError("文件名片段过长")
    if any(re.search(r'[<>:"|?*]', part) for part in parts):
        raise ValueError("文件名包含非法字符")
    return os.path.join(*parts)


def get_safe_workspace_path(user_id: Any, task_id: str, filename: str) -> str:
    workspace_dir = get_workspace_dir(user_id, task_id)
    safe_relative_path = _validate_workspace_relative_path(filename)
    target_path = os.path.abspath(os.path.join(workspace_dir, safe_relative_path))

    if os.path.commonpath([workspace_dir, target_path]) != workspace_dir:
        raise PermissionError(f"越权防护拦截：尝试读取或写入工作区外部的文件 {filename}")

    return target_path


def tool_read_file(user_id: Any, task_id: str, filename: str) -> str:
    try:
        path = get_safe_workspace_path(user_id, task_id, filename)
        if not os.path.exists(path):
            return f"错误：文件 {filename} 不存在。可用工具创建或读取其他文件。"
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"读取文件失败：{str(e)}"


def tool_write_file(user_id: Any, task_id: str, filename: str, content: str) -> str:
    try:
        path = get_safe_workspace_path(user_id, task_id, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"成功：内容已写入文件 {filename}"
    except Exception as e:
        return f"写入文件失败：{str(e)}"


def tool_list_files(user_id: Any, task_id: str) -> str:
    try:
        workspace_dir = get_workspace_dir(user_id, task_id)
        files = os.listdir(workspace_dir)
        if not files:
            return "工作区内暂无文件。"
        return "工作区内文件列表：\n" + "\n".join(files)
    except Exception as e:
        return f"获取文件列表失败：{str(e)}"
