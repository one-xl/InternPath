"""
Session 管理中心 (Session Manager)
管理不同窗口/用户的独立 Session 实例，支持自动根据对话生成内容提炼 Session 标题与磁盘持久化落盘。
"""

import json
import logging
import os
import re
import time
from typing import Dict, Optional, List, Any
from agent.context_manager import ContextManager

logger = logging.getLogger(__name__)


class Session:
    """单个独立对话窗口 Session"""

    def __init__(self, session_id: str, title: Optional[str] = None, system_prompt: Optional[str] = None):
        self.session_id = session_id
        self.title = title or f"窗口 {session_id.replace('window_', '')}"
        self.created_at = time.time()
        self.updated_at = time.time()
        if system_prompt:
            self.context_manager = ContextManager(system_prompt=system_prompt)
        else:
            self.context_manager = ContextManager()

    def get_context_manager(self) -> ContextManager:
        return self.context_manager

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "context": self.context_manager.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Session":
        session = cls(
            session_id=data["session_id"],
            title=data.get("title")
        )
        session.created_at = data.get("created_at", time.time())
        session.updated_at = data.get("updated_at", time.time())
        if "context" in data:
            session.context_manager = ContextManager.from_dict(data["context"])
        return session


class SessionManager:
    """Session 注册管理工厂、自动生成标题、存储器与磁盘持久化处理器"""

    def __init__(
        self,
        default_system_prompt: Optional[str] = None,
        data_dir: Optional[str] = None,
        llm_client: Optional[Any] = None,
        tool_registry: Optional[Any] = None,
        sessions_dir: Optional[str] = None,
    ):
        self.default_system_prompt = default_system_prompt
        self.llm_client = llm_client
        self.tool_registry = tool_registry
        target_dir = sessions_dir or data_dir
        self.data_dir = target_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "sessions"
        )
        os.makedirs(self.data_dir, exist_ok=True)
        self.sessions: Dict[str, Session] = {}
        self.runtimes: Dict[str, Any] = {}

    def has_session(self, session_id: str) -> bool:
        """判断特定 session_id 是否已建立"""
        if session_id in self.sessions:
            return True
        return os.path.exists(os.path.join(self.data_dir, f"{session_id}.json"))

    def get_or_create_session(self, session_id: str) -> Session:
        if session_id not in self.sessions:
            filepath = os.path.join(self.data_dir, f"{session_id}.json")
            if os.path.exists(filepath):
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    session = Session.from_dict(data)
                    self.sessions[session_id] = session
                    logger.info(f"从磁盘恢复 Session [{session_id}]")
                except Exception as e:
                    logger.error(f"恢复 Session [{session_id}] 失败: {e}")
                    session = Session(session_id=session_id, system_prompt=self.default_system_prompt)
                    self.sessions[session_id] = session
            else:
                session = Session(session_id=session_id, system_prompt=self.default_system_prompt)
                self.sessions[session_id] = session

        return self.sessions[session_id]

    def get_or_create_runtime(self, session_id: str) -> Any:
        session = self.get_or_create_session(session_id)
        from agent.runtime import AgentRuntime

        if session_id not in self.runtimes:
            rt = AgentRuntime(
                llm_client=self.llm_client,
                tool_registry=self.tool_registry,
                context_manager=session.context_manager,
                session_manager=self,
            )
            self.runtimes[session_id] = rt

        return self.runtimes[session_id]

    def update_session_title_by_first_message(self, session_id: str, first_msg: str) -> str:
        session = self.get_or_create_session(session_id)
        if session.title and not session.title.startswith("窗口 "):
            return session.title

        clean_text = re.sub(r"[^\w\s\u4e00-\u9fa5]", "", first_msg).strip()
        title = clean_text[:12] if clean_text else "新对话窗口"
        session.title = title
        self.save_session(session_id)
        return title

    def save_session(self, session_id: str) -> None:
        if session_id in self.sessions:
            session = self.sessions[session_id]
            session.updated_at = time.time()
            filepath = os.path.join(self.data_dir, f"{session_id}.json")
            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(session.to_dict(), f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"持久化保存 Session [{session_id}] 失败: {e}")

    def clear_session(self, session_id: str) -> None:
        """清空 Session 并从内存和磁盘抹除"""
        if session_id in self.sessions:
            del self.sessions[session_id]
        if session_id in self.runtimes:
            del self.runtimes[session_id]
        filepath = os.path.join(self.data_dir, f"{session_id}.json")
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception:
                pass

    def delete_session(self, session_id: str) -> bool:
        self.clear_session(session_id)
        return True

    def get_session_title(self, session_id: str) -> str:
        session = self.get_or_create_session(session_id)
        return session.title

    def list_sessions(self) -> List[Dict[str, Any]]:
        result = []
        if os.path.exists(self.data_dir):
            for fname in os.listdir(self.data_dir):
                if fname.endswith(".json"):
                    sid = fname[:-5]
                    title = self.get_session_title(sid)
                    result.append({"session_id": sid, "title": title})
        if not result:
            result.append({"session_id": "window_1", "title": "窗口 1"})
        return result
