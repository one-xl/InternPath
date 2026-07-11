from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from database import Database, safe_json_load
from .preview import preview_metadata


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _load_json(value: Any, default: Any) -> Any:
    loaded = safe_json_load(value, default)
    return default if loaded is None else loaded


class ResumeAdvisorRepository:
    """PostgreSQL adapter for durable advisor sessions, runs, and user-visible events."""

    def __init__(self, db: Database):
        self.db = db

    def create_session(
        self,
        *,
        user_id: Any,
        resume_id: str,
        resume_content_hash: str,
        jd_text: str,
        analysis_record_id: str | None = None,
        title: str = "",
    ) -> dict[str, Any]:
        session_id = f"advisor-{uuid4().hex}"
        now = datetime.now().isoformat()
        jd_content_hash = hashlib.sha256(jd_text.strip().encode("utf-8")).hexdigest()
        trace_id = f"tr-{uuid4().hex}"
        conn = self.db.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO agent_resume_tasks (
                    task_id, user_id, trace_id, status, resume_id, original_resume_name,
                    jd_text, workspace_path, logs, optimized_resume_md, error_message,
                    interaction_mode, analysis_record_id, resume_content_hash, jd_content_hash,
                    title, session_status, last_message_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    str(user_id),
                    trace_id,
                    "ACTIVE",
                    resume_id,
                    "",
                    jd_text,
                    "",
                    "[]",
                    "",
                    "",
                    "resume_advisor",
                    analysis_record_id,
                    resume_content_hash,
                    jd_content_hash,
                    title,
                    "ACTIVE",
                    now,
                    now,
                    now,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_session(user_id, session_id) or {}

    def get_session(self, user_id: Any, session_id: str) -> dict[str, Any] | None:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT task_id, user_id, trace_id, resume_id, jd_text, interaction_mode,
                       analysis_record_id, resume_content_hash, jd_content_hash, title,
                       session_status, active_run_id, last_message_at, user_satisfied_at,
                       archived_at, created_at, updated_at, error_message
                FROM agent_resume_tasks
                WHERE task_id = ? AND user_id = ? AND interaction_mode = 'resume_advisor'
                """,
                (session_id, str(user_id)),
            )
            row = cursor.fetchone()
        finally:
            conn.close()
        if not row:
            return None
        keys = [
            "id", "userId", "traceId", "resumeId", "jdText", "interactionMode",
            "analysisRecordId", "resumeContentHash", "jdContentHash", "title",
            "sessionStatus", "activeRunId", "lastMessageAt", "userSatisfiedAt",
            "archivedAt", "createdAt", "updatedAt", "errorMessage",
        ]
        return dict(zip(keys, row))

    def list_sessions(self, user_id: Any, *, limit: int = 40, offset: int = 0) -> list[dict[str, Any]]:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT task_id, user_id, trace_id, resume_id, jd_text, interaction_mode,
                       analysis_record_id, resume_content_hash, jd_content_hash, title,
                       session_status, active_run_id, last_message_at, user_satisfied_at,
                       archived_at, created_at, updated_at, error_message
                FROM agent_resume_tasks
                WHERE user_id = ? AND interaction_mode = 'resume_advisor'
                ORDER BY COALESCE(last_message_at, created_at) DESC
                LIMIT ?
                OFFSET ?
                """,
                (str(user_id), max(1, min(limit, 100)), max(0, offset)),
            )
            rows = cursor.fetchall()
        finally:
            conn.close()
        keys = [
            "id", "userId", "traceId", "resumeId", "jdText", "interactionMode",
            "analysisRecordId", "resumeContentHash", "jdContentHash", "title",
            "sessionStatus", "activeRunId", "lastMessageAt", "userSatisfiedAt",
            "archivedAt", "createdAt", "updatedAt", "errorMessage",
        ]
        return [dict(zip(keys, row)) for row in rows]

    def update_session(
        self,
        user_id: Any,
        session_id: str,
        *,
        session_status: str | None = None,
        active_run_id: str | None = None,
        error_message: str | None = None,
        user_satisfied: bool = False,
        archived: bool = False,
    ) -> None:
        updates = ["updated_at = ?", "last_message_at = ?"]
        now = datetime.now().isoformat()
        params: list[Any] = [now, now]
        if session_status is not None:
            updates.append("session_status = ?")
            params.append(session_status)
            updates.append("status = ?")
            params.append(session_status)
        if active_run_id is not None:
            updates.append("active_run_id = ?")
            params.append(active_run_id)
        if error_message is not None:
            updates.append("error_message = ?")
            params.append(error_message)
        if user_satisfied:
            updates.append("user_satisfied_at = ?")
            params.append(now)
        if archived:
            updates.append("archived_at = ?")
            params.append(now)
        params.extend([session_id, str(user_id)])
        conn = self.db.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                f"UPDATE agent_resume_tasks SET {', '.join(updates)} WHERE task_id = ? AND user_id = ? AND interaction_mode = 'resume_advisor'",
                tuple(params),
            )
            conn.commit()
        finally:
            conn.close()

    def _lock_session(self, cursor, user_id: Any, session_id: str) -> None:
        cursor.execute(
            "SELECT task_id FROM agent_resume_tasks WHERE task_id = ? AND user_id = ? FOR UPDATE",
            (session_id, str(user_id)),
        )
        if not cursor.fetchone():
            raise LookupError("未找到简历优化会话。")

    def append_turn(
        self,
        *,
        user_id: Any,
        session_id: str,
        role: str,
        content: str,
        message_kind: str,
        client_message_id: str | None = None,
        run_id: str | None = None,
        payload: dict[str, Any] | None = None,
        status: str = "COMPLETED",
        parent_turn_id: str | None = None,
    ) -> dict[str, Any]:
        turn_id = str(uuid4())
        conn = self.db.get_connection()
        cursor = conn.cursor()
        try:
            self._lock_session(cursor, user_id, session_id)
            cursor.execute(
                "SELECT COALESCE(MAX(sequence_no), 0) + 1 FROM agent_resume_turns WHERE task_id = ? AND user_id = ?",
                (session_id, str(user_id)),
            )
            sequence_no = int(cursor.fetchone()[0])
            cursor.execute(
                """
                INSERT INTO agent_resume_turns (
                    id, task_id, user_id, role, content, sequence_no, message_kind,
                    payload_json, client_message_id, run_id, parent_turn_id, status,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?::jsonb, ?, ?, ?, ?, ?)
                """,
                (
                    turn_id, session_id, str(user_id), role, content, sequence_no, message_kind,
                    _dump_json(payload or {}), client_message_id, run_id, parent_turn_id, status,
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return {
            "id": turn_id,
            "sequence": sequence_no,
            "role": role,
            "content": content,
            "messageKind": message_kind,
            "clientMessageId": client_message_id,
            "runId": run_id,
            "payload": payload or {},
            "status": status,
        }

    def find_turn_by_client_message(self, user_id: Any, session_id: str, client_message_id: str) -> dict[str, Any] | None:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT id, sequence_no, role, content, message_kind, client_message_id, run_id,
                       payload_json, status, created_at
                FROM agent_resume_turns
                WHERE user_id = ? AND task_id = ? AND client_message_id = ?
                """,
                (str(user_id), session_id, client_message_id),
            )
            row = cursor.fetchone()
        finally:
            conn.close()
        if not row:
            return None
        return {
            "id": str(row[0]), "sequence": row[1], "role": row[2], "content": row[3],
            "messageKind": row[4], "clientMessageId": row[5], "runId": row[6],
            "payload": _load_json(row[7], {}), "status": row[8], "createdAt": row[9],
        }

    def list_turns(self, user_id: Any, session_id: str) -> list[dict[str, Any]]:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT id, sequence_no, role, content, message_kind, client_message_id, run_id,
                       payload_json, status, created_at
                FROM agent_resume_turns
                WHERE user_id = ? AND task_id = ?
                ORDER BY sequence_no ASC, created_at ASC
                """,
                (str(user_id), session_id),
            )
            rows = cursor.fetchall()
        finally:
            conn.close()
        return [
            {
                "id": str(row[0]), "sequence": row[1], "role": row[2], "content": row[3],
                "messageKind": row[4], "clientMessageId": row[5], "runId": row[6],
                "payload": _load_json(row[7], {}), "status": row[8], "createdAt": row[9],
            }
            for row in rows
        ]

    def create_run(self, *, user_id: Any, session_id: str, trigger_message_id: str | None = None) -> dict[str, Any]:
        run_id = f"run-{uuid4().hex}"
        trace_id = f"tr-{uuid4().hex}"
        now = datetime.now().isoformat()
        conn = self.db.get_connection()
        cursor = conn.cursor()
        try:
            self._lock_session(cursor, user_id, session_id)
            cursor.execute(
                """
                INSERT INTO agent_resume_runs (
                    id, session_id, user_id, trigger_message_id, status, rq_job_id,
                    trace_id, telemetry_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?::jsonb, ?)
                """,
                (run_id, session_id, str(user_id), trigger_message_id, "QUEUED", run_id, trace_id, "{}", now),
            )
            cursor.execute(
                "UPDATE agent_resume_tasks SET active_run_id = ?, session_status = 'ACTIVE', status = 'ACTIVE', updated_at = ? WHERE task_id = ? AND user_id = ?",
                (run_id, now, session_id, str(user_id)),
            )
            conn.commit()
        finally:
            conn.close()
        return {"id": run_id, "sessionId": session_id, "status": "QUEUED", "traceId": trace_id}

    def update_run(
        self,
        *,
        user_id: Any,
        run_id: str,
        status: str,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        now = datetime.now().isoformat()
        finished_at = now if status in {"COMPLETED", "FAILED", "PAUSED"} else None
        conn = self.db.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE agent_resume_runs
                SET status = ?, started_at = COALESCE(started_at, ?),
                    finished_at = COALESCE(?, finished_at), error_code = ?, error_message = ?
                WHERE id = ? AND user_id = ?
                """,
                (status, now, finished_at, error_code, error_message, run_id, str(user_id)),
            )
            conn.commit()
        finally:
            conn.close()

    def get_run(self, *, user_id: Any, run_id: str) -> dict[str, Any] | None:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT id, session_id, status, trace_id, rq_job_id, started_at, finished_at,
                       error_code, error_message, telemetry_json, created_at
                FROM agent_resume_runs
                WHERE id = ? AND user_id = ?
                """,
                (run_id, str(user_id)),
            )
            row = cursor.fetchone()
        finally:
            conn.close()
        if not row:
            return None
        return {
            "id": row[0],
            "sessionId": row[1],
            "status": row[2],
            "traceId": row[3],
            "rqJobId": row[4],
            "startedAt": row[5],
            "finishedAt": row[6],
            "errorCode": row[7],
            "errorMessage": row[8],
            "telemetry": _load_json(row[9], {}),
            "createdAt": row[10],
        }

    def merge_run_telemetry(self, *, user_id: Any, run_id: str, telemetry: dict[str, Any]) -> None:
        if not telemetry:
            return
        conn = self.db.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE agent_resume_runs
                SET telemetry_json = COALESCE(telemetry_json, '{}'::jsonb) || ?::jsonb
                WHERE id = ? AND user_id = ?
                """,
                (_dump_json(telemetry), run_id, str(user_id)),
            )
            conn.commit()
        finally:
            conn.close()

    def get_slo_dashboard(self, *, user_id: Any, window_hours: int = 24) -> dict[str, Any]:
        safe_window_hours = min(24 * 30, max(1, int(window_hours)))
        since = datetime.now() - timedelta(hours=safe_window_hours)
        conn = self.db.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT telemetry_json
                FROM agent_resume_runs
                WHERE user_id = ? AND created_at >= ?
                ORDER BY created_at ASC
                """,
                (str(user_id), since.isoformat()),
            )
            rows = cursor.fetchall()
        finally:
            conn.close()

        telemetry_rows = [_load_json(row[0], {}) for row in rows]

        def percentile_95(values: list[int]) -> int | None:
            if not values:
                return None
            ordered = sorted(values)
            index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1))
            return ordered[index]

        metric_specs = {
            "queueMs": 1_000,
            "providerFirstTokenMs": 8_000,
            "endToEndFirstTokenMs": 10_000,
        }
        metrics: dict[str, dict[str, Any]] = {}
        alerts: list[dict[str, Any]] = []
        for metric_name, threshold_ms in metric_specs.items():
            values = [
                max(0, int(row[metric_name]))
                for row in telemetry_rows
                if isinstance(row, dict)
                and isinstance(row.get(metric_name), (int, float))
                and not isinstance(row.get(metric_name), bool)
            ]
            p95_ms = percentile_95(values)
            met = None if p95_ms is None else p95_ms < threshold_ms
            metrics[metric_name] = {
                "count": len(values),
                "p95Ms": p95_ms,
                "thresholdMs": threshold_ms,
                "met": met,
            }
            if met is False:
                alerts.append(
                    {
                        "code": f"{metric_name}_p95_breach",
                        "severity": "warning",
                        "metric": metric_name,
                        "observedP95Ms": p95_ms,
                        "thresholdMs": threshold_ms,
                    }
                )
        return {
            "windowHours": safe_window_hours,
            "runCount": len(telemetry_rows),
            "metrics": metrics,
            "alerts": alerts,
        }

    def get_active_run(self, user_id: Any, session_id: str) -> dict[str, Any] | None:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT id, status, trace_id, rq_job_id, started_at, finished_at, error_code, error_message
                FROM agent_resume_runs
                WHERE session_id = ? AND user_id = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (session_id, str(user_id)),
            )
            row = cursor.fetchone()
        finally:
            conn.close()
        if not row:
            return None
        return {
            "id": row[0], "status": row[1], "traceId": row[2], "rqJobId": row[3],
            "startedAt": row[4], "finishedAt": row[5], "errorCode": row[6], "errorMessage": row[7],
        }

    def append_event(
        self,
        *,
        user_id: Any,
        session_id: str,
        event_type: str,
        run_id: str | None = None,
        message_id: str | None = None,
        suggestion_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event_id = f"evt-{uuid4().hex}"
        conn = self.db.get_connection()
        cursor = conn.cursor()
        try:
            self._lock_session(cursor, user_id, session_id)
            cursor.execute(
                "SELECT COALESCE(MAX(sequence_no), 0) + 1 FROM agent_resume_events WHERE session_id = ? AND user_id = ?",
                (session_id, str(user_id)),
            )
            sequence_no = int(cursor.fetchone()[0])
            cursor.execute(
                """
                INSERT INTO agent_resume_events (
                    id, session_id, user_id, sequence_no, run_id, event_type,
                    message_id, suggestion_id, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?::jsonb, ?)
                """,
                (
                    event_id, session_id, str(user_id), sequence_no, run_id, event_type,
                    message_id, suggestion_id, _dump_json(payload or {}), datetime.now().isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()
        event = {
            "id": event_id, "sequence": sequence_no, "runId": run_id, "type": event_type,
            "messageId": message_id, "suggestionId": suggestion_id, "payload": payload or {},
        }
        from .event_stream import publish_event_notification

        publish_event_notification(session_id=session_id, sequence=sequence_no)
        return event

    def get_event_stream_cursor(self, *, session_id: str) -> str | None:
        from .event_stream import current_stream_cursor

        return current_stream_cursor(session_id=session_id)

    def wait_for_event_notification(self, *, session_id: str, cursor: str, block_ms: int) -> str:
        from .event_stream import wait_for_event_notification

        return wait_for_event_notification(session_id=session_id, cursor=cursor, block_ms=block_ms)

    def list_events(self, user_id: Any, session_id: str, after_sequence: int = 0) -> list[dict[str, Any]]:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT id, sequence_no, run_id, event_type, message_id, suggestion_id, payload_json, created_at
                FROM agent_resume_events
                WHERE user_id = ? AND session_id = ? AND sequence_no > ?
                ORDER BY sequence_no ASC
                """,
                (str(user_id), session_id, max(0, after_sequence)),
            )
            rows = cursor.fetchall()
        finally:
            conn.close()
        return [
            {
                "id": row[0], "sequence": row[1], "runId": row[2], "type": row[3],
                "messageId": str(row[4]) if row[4] else None, "suggestionId": row[5],
                "payload": _load_json(row[6], {}), "createdAt": row[7],
            }
            for row in rows
        ]

    def create_suggestion(self, *, user_id: Any, session_id: str, run_id: str, data: dict[str, Any]) -> dict[str, Any]:
        suggestion_id = f"sug-{uuid4().hex}"
        target_block_id = str(data["target"]["blockId"])
        conn = self.db.get_connection()
        cursor = conn.cursor()
        try:
            self._lock_session(cursor, user_id, session_id)
            cursor.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM agent_resume_suggestions WHERE session_id = ? AND target_block_id = ?",
                (session_id, target_block_id),
            )
            version = int(cursor.fetchone()[0])
            cursor.execute(
                """
                INSERT INTO agent_resume_suggestions (
                    id, session_id, user_id, version, parent_suggestion_id, target_block_id,
                    original_text_hash, location_json, original_text, proposed_text, copy_text,
                    issue, rationale, expected_impact, priority, jd_requirement_ids,
                    resume_evidence_block_ids, user_fact_ids, fact_status, fact_issues,
                    status, created_run_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?::jsonb, ?, ?, ?, ?, ?, ?, ?, ?::jsonb, ?::jsonb, ?::jsonb, ?, ?::jsonb, ?, ?, ?, ?)
                """,
                (
                    suggestion_id, session_id, str(user_id), version, data.get("parentSuggestionId"),
                    target_block_id, data["originalTextHash"], _dump_json(data["target"]),
                    data["originalText"], data["proposedText"], data["copyText"], data["issue"],
                    data["rationale"], data["expectedImpact"], data["priority"],
                    _dump_json(data.get("jdRequirementIds", [])),
                    _dump_json(data.get("resumeEvidenceBlockIds", [])),
                    _dump_json(data.get("userFactIds", [])), data["factStatus"],
                    _dump_json(data.get("factIssues", [])), data.get("status", "proposed"), run_id,
                    datetime.now().isoformat(), datetime.now().isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return {"id": suggestion_id, "sessionId": session_id, "version": version, **data}

    def list_suggestions(self, user_id: Any, session_id: str) -> list[dict[str, Any]]:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT id, version, parent_suggestion_id, target_block_id, original_text_hash,
                       location_json, original_text, proposed_text, copy_text, issue, rationale,
                       expected_impact, priority, jd_requirement_ids, resume_evidence_block_ids,
                       user_fact_ids, fact_status, fact_issues, status, created_run_id, created_at, updated_at
                FROM agent_resume_suggestions
                WHERE user_id = ? AND session_id = ?
                ORDER BY created_at ASC, version ASC
                """,
                (str(user_id), session_id),
            )
            rows = cursor.fetchall()
        finally:
            conn.close()
        return [
            {
                "id": row[0], "sessionId": session_id, "version": row[1], "parentSuggestionId": row[2],
                "target": _load_json(row[5], {}), "originalTextHash": row[4], "originalText": row[6],
                "proposedText": row[7], "copyText": row[8], "issue": row[9], "rationale": row[10],
                "expectedImpact": row[11], "priority": row[12], "jdRequirementIds": _load_json(row[13], []),
                "resumeEvidenceBlockIds": _load_json(row[14], []), "userFactIds": _load_json(row[15], []),
                "factStatus": row[16], "factIssues": _load_json(row[17], []), "status": row[18],
                "createdRunId": row[19], "createdAt": row[20], "updatedAt": row[21],
            }
            for row in rows
        ]

    def get_suggestion(self, user_id: Any, suggestion_id: str) -> dict[str, Any] | None:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT session_id FROM agent_resume_suggestions WHERE id = ? AND user_id = ?", (suggestion_id, str(user_id)))
            row = cursor.fetchone()
        finally:
            conn.close()
        if not row:
            return None
        return next((item for item in self.list_suggestions(user_id, row[0]) if item["id"] == suggestion_id), None)

    def update_suggestion_status(self, user_id: Any, suggestion_id: str, status: str) -> None:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "UPDATE agent_resume_suggestions SET status = ?, updated_at = ? WHERE id = ? AND user_id = ?",
                (status, datetime.now().isoformat(), suggestion_id, str(user_id)),
            )
            conn.commit()
        finally:
            conn.close()

    def restore_suggestion(self, *, user_id: Any, suggestion_id: str, run_id: str | None = None) -> dict[str, Any]:
        """Restore a historical proposal by appending a new accepted version."""
        source = self.get_suggestion(user_id, suggestion_id)
        if not source:
            raise LookupError("未找到要恢复的建议版本。")
        return self.create_suggestion(
            user_id=user_id,
            session_id=source["sessionId"],
            run_id=run_id or str(source.get("createdRunId") or "restore"),
            data={
                "parentSuggestionId": source["id"],
                "target": source["target"],
                "originalTextHash": source["originalTextHash"],
                "originalText": source["originalText"],
                "proposedText": source["proposedText"],
                "copyText": source["copyText"],
                "issue": f"恢复建议 v{source['version']}：{source['issue']}",
                "rationale": "用户主动恢复历史版本；原版本保留不被覆盖。",
                "expectedImpact": source["expectedImpact"],
                "priority": source["priority"],
                "jdRequirementIds": source["jdRequirementIds"],
                "resumeEvidenceBlockIds": source["resumeEvidenceBlockIds"],
                "userFactIds": source["userFactIds"],
                "factStatus": source["factStatus"],
                "factIssues": source["factIssues"],
                "status": "accepted" if source["factStatus"] == "supported" else "proposed",
            },
        )

    def list_confirmed_facts(self, user_id: Any, session_id: str) -> list[dict[str, Any]]:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT id, claim_key, claim_value, source_type, source_id, status, scope
                FROM agent_resume_facts
                WHERE user_id = ? AND (session_id = ? OR scope = 'global')
                ORDER BY created_at ASC
                """,
                (str(user_id), session_id),
            )
            rows = cursor.fetchall()
        finally:
            conn.close()
        return [
            {"id": row[0], "claimKey": row[1], "claimValue": row[2], "sourceType": row[3], "sourceId": row[4], "status": row[5], "scope": row[6]}
            for row in rows
        ]

    def record_fact(
        self,
        *,
        user_id: Any,
        session_id: str,
        claim_key: str,
        claim_value: str,
        source_type: str,
        source_id: str,
        status: str,
        scope: str = "session",
    ) -> str:
        fact_id = f"fact-{uuid4().hex}"
        now = datetime.now().isoformat()
        conn = self.db.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO agent_resume_facts (
                    id, session_id, user_id, claim_key, claim_value, source_type,
                    source_id, status, scope, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (session_id, claim_key, claim_value)
                DO UPDATE SET status = EXCLUDED.status, source_type = EXCLUDED.source_type,
                              source_id = EXCLUDED.source_id, updated_at = EXCLUDED.updated_at
                """,
                (fact_id, session_id, str(user_id), claim_key, claim_value, source_type, source_id, status, scope, now, now),
            )
            conn.commit()
        finally:
            conn.close()
        return fact_id

    def get_resume_view(self, user_id: Any, session_id: str) -> dict[str, Any]:
        session = self.get_session(user_id, session_id)
        if not session:
            raise LookupError("未找到简历优化会话。")
        resume = self.db.get_user_resume(user_id, session["resumeId"])
        if not resume:
            raise LookupError("会话绑定的简历快照不存在。")
        resume = self._repair_resume_sections(user_id, session["resumeId"], resume)
        # The right-hand locator and the advisor graph share this same canonical view.
        # Old snapshots may still contain extraction duplicates; do not expose them as
        # separate paragraphs or independent suggestion candidates.
        from backend.resume_rag import deduplicate_resume_blocks

        return {
            "resumeId": session["resumeId"],
            "contentHash": session["resumeContentHash"],
            "file": resume.get("file") or {},
            "blocks": deduplicate_resume_blocks(resume.get("blocks") or []),
            "preview": preview_metadata(resume),
        }

    def _repair_resume_sections(self, user_id: Any, resume_id: str, resume: dict[str, Any]) -> dict[str, Any]:
        from backend.resume_rag import repair_resume_chunk_sections

        repaired, changed = repair_resume_chunk_sections(resume)
        if not changed:
            return resume
        file_info = repaired.get("file") if isinstance(repaired.get("file"), dict) else {}
        self.db.save_user_resume(
            user_id=user_id,
            resume_id=resume_id,
            file_name=str(file_info.get("name") or "resume"),
            file_size=int(file_info.get("size") or 0),
            file_type=str(file_info.get("type") or "application/octet-stream"),
            parsed_resume=repaired,
            content_hash=str(repaired.get("contentHash") or file_info.get("contentHash") or "") or None,
        )
        return repaired

    def get_resume_file(self, user_id: Any, session_id: str) -> tuple[bytes, str, str]:
        session = self.get_session(user_id, session_id)
        if not session:
            raise LookupError("未找到简历优化会话。")
        resume = self.db.get_user_resume(user_id, session["resumeId"])
        if not resume:
            raise LookupError("会话绑定的简历快照不存在。")
        from .preview import original_file_bytes

        file_info = resume.get("file") if isinstance(resume.get("file"), dict) else {}
        return (
            original_file_bytes(resume),
            str(file_info.get("type") or "application/octet-stream"),
            str(file_info.get("name") or "resume"),
        )
