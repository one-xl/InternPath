from __future__ import annotations

import json
from typing import Any, Callable
from uuid import uuid4

import httpx

from backend.resume_rag import retrieve_chunks

from .graph import build_optimization_graph
from .prompts import ORCHESTRATOR_PROMPT


class ResumeOptimizationService:
    def __init__(self, db: Any, *, resume_provider: Callable[[Any, str], dict[str, Any] | None], project_provider: Callable[[Any, list[int], str], list[dict[str, Any]]], enqueue_run: Callable[[str, Any], None] | None = None):
        self.db = db
        self.resume_provider = resume_provider
        self.project_provider = project_provider
        self.enqueue_run = enqueue_run
        self.sessions: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _model_call(user_id: Any, config_id: str | None) -> Callable[[str, str], str]:
        from ai_analyzer import AIAnalyzer

        client, _resolved, _provider, model = AIAnalyzer()._client(user_id, config_id, True)

        def call(system: str, content: str) -> str:
            response = client.chat.completions.create(model=model, temperature=0.2, messages=[{"role": "system", "content": system}, {"role": "user", "content": content}])
            return str(response.choices[0].message.content or "")
        return call

    @staticmethod
    def _blocks(resume: dict[str, Any]) -> list[dict[str, Any]]:
        return [{"id": str(block.get("id") or index), "text": str(block.get("text") or ""), "location": block.get("locator") or {}, "section": block.get("sectionName") or block.get("sectionId") or ""} for index, block in enumerate(resume.get("blocks") or []) if str(block.get("text") or "").strip()]

    @staticmethod
    def _retrieve(query: str, resume_blocks: list[dict[str, Any]], project_chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        documents = [{"documentId": "resume", "content": item["text"], "metadata": {"sourceType": "resume", "blockId": item["id"], "locator": item["location"]}} for item in resume_blocks]
        documents.extend(project_chunks)
        try:
            response = httpx.post("http://127.0.0.1:8000/ai/rag/search", json={"query": query, "documents": documents, "topK": 10, "strategy": "hybrid"}, timeout=20)
            response.raise_for_status()
            return list(response.json().get("results") or [])
        except Exception:
            # Keep the user workflow usable when the separate service is unavailable.
            chunks = [{"id": item["id"], "content": item["text"], "locator": item["location"], "section": item["section"]} for item in resume_blocks]
            return [{"chunkId": item.get("id"), "text": item.get("content"), "score": item.get("score"), "metadata": {"sourceType": "resume", "locator": item.get("locator")}} for item in retrieve_chunks(query, chunks, top_k=8).get("topChunks", [])]

    def start(self, *, user_id: Any, resume_id: str, jd_text: str, model_config_id: str | None, project_scope: str, project_ids: list[int]) -> dict[str, Any]:
        resume = self.resume_provider(user_id, resume_id)
        if not resume:
            raise LookupError("未找到简历")
        blocks = self._blocks(resume)
        if not blocks:
            raise ValueError("简历清洗后没有可分析文本")
        session_id = f"resume-opt-{uuid4().hex}"
        self.db.create_agent_resume_task(task_id=session_id, user_id=user_id, resume_id=resume_id, original_resume_name=str((resume.get("file") or {}).get("name") or "resume"), jd_text=jd_text)
        self.sessions[session_id] = {"userId": str(user_id), "resumeId": resume_id, "modelConfigId": model_config_id, "projectScope": project_scope, "projectIds": project_ids, "blocks": blocks, "jdText": jd_text, "messages": [{"role": "assistant", "content": "已开始清洗简历并编排 JD 分析、检索与 HR 审查。"}], "state": {"events": [{"agent": "orchestrator", "status": "queued"}]}}
        self.db.add_agent_resume_turn(task_id=session_id, user_id=user_id, role="assistant", content="已开始清洗简历并编排 JD 分析、检索与 HR 审查。", answer_type="status")
        self.db.update_agent_resume_task_status(session_id, user_id, "PENDING", optimized_resume_md=json.dumps(self.sessions[session_id], ensure_ascii=False, default=str))
        if self.enqueue_run:
            self.enqueue_run(session_id, user_id)
        else:
            self.run(user_id, session_id)
        return {"sessionId": session_id, "snapshot": self.snapshot(user_id, session_id)}

    def run(self, user_id: Any, session_id: str) -> None:
        session = self._load(user_id, session_id)
        self.db.update_agent_resume_task_status(session_id, user_id, "RUNNING")
        projects = self.project_provider(user_id, list(session.get("projectIds") or []), str(session.get("projectScope") or "none")) if session.get("projectScope") in {"all", "selected"} else []
        try:
            state = build_optimization_graph(self._retrieve).invoke({"jd_text": session["jdText"], "resume_blocks": session["blocks"], "project_chunks": projects, "model_call": self._model_call(user_id, session.get("modelConfigId")), "events": []})
            session["state"] = state
            summary = state.get("summary") or "分析完成"
            session["messages"].append({"role": "assistant", "content": summary})
            self.db.add_agent_resume_turn(task_id=session_id, user_id=user_id, role="assistant", content=summary, answer_type="optimization_summary")
            self.db.update_agent_resume_task_status(session_id, user_id, "COMPLETED", optimized_resume_md=json.dumps(session, ensure_ascii=False, default=str), logs=json.dumps(state.get("events") or [], ensure_ascii=False))
        except Exception as exc:
            self.db.update_agent_resume_task_status(session_id, user_id, "FAILED", error_message=str(exc))
            raise

    def _load(self, user_id: Any, session_id: str) -> dict[str, Any]:
        session = self.sessions.get(session_id)
        if not session:
            task = self.db.get_agent_resume_task(user_id, session_id)
            if task and task.get("optimized_resume_md"):
                session = json.loads(task["optimized_resume_md"])
                self.sessions[session_id] = session
        if not session or session["userId"] != str(user_id):
            raise LookupError("未找到优化会话")
        return session

    def snapshot(self, user_id: Any, session_id: str) -> dict[str, Any]:
        session = self._load(user_id, session_id)
        state = session["state"]
        task = self.db.get_agent_resume_task(user_id, session_id) or {}
        return {"sessionId": session_id, "status": task.get("status") or "PENDING", "messages": session["messages"], "resumeBlocks": session["blocks"], "requirements": state.get("requirements", []), "evidence": state.get("evidence", []), "diffs": state.get("diffs", []), "hr": state.get("hr", {}), "events": state.get("events", [])}

    def chat(self, user_id: Any, session_id: str, message: str) -> dict[str, Any]:
        session = self._load(user_id, session_id)
        session["messages"].append({"role": "user", "content": message})
        self.db.add_agent_resume_turn(task_id=session_id, user_id=user_id, role="user", content=message, answer_type="chat")
        context = {
            "jd": session["jdText"],
            "userMessage": message,
            "resumeBlocks": session.get("blocks", []),
            "hr": session["state"].get("hr", {}),
            "diffs": session["state"].get("diffs", []),
            "evidence": session["state"].get("evidence", [])[:6],
        }
        answer = self._model_call(user_id, session.get("modelConfigId"))(ORCHESTRATOR_PROMPT, json.dumps(context, ensure_ascii=False))
        if not answer.strip():
            answer = "我已收到你的消息。请继续说明希望确认、修改或补充的内容。"
        session["messages"].append({"role": "assistant", "content": answer})
        self.db.add_agent_resume_turn(task_id=session_id, user_id=user_id, role="assistant", content=answer, answer_type="chat")
        self.db.update_agent_resume_task_status(session_id, user_id, "COMPLETED", optimized_resume_md=json.dumps(session, ensure_ascii=False, default=str))
        return {"message": answer, "snapshot": self.snapshot(user_id, session_id)}
