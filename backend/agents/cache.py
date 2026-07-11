from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Iterator, Sequence

from config import Config
from backend.agents.schemas import AGENT_SCHEMA_VERSION


_CACHE_LOCK = threading.RLock()
_MAX_CACHE_ITEMS = 500
AGENT_TOOL_VERSION = "2026-07-05.agent-tools-v1"

CACHE_NAMESPACE_VERSIONS: dict[str, str] = {
    "resume_plan_v2": "plan-v3",
    "resume_plan_v3": "plan-v4",
    "job_decode_v2": "job-decode-v3",
    "resume_section_rewrite_v2": "section-rewrite-v3",
    "resume_hr_critic_v2": "hr-critic-v3",
    "resume_hallucination_check_v2": "hallucination-v3",
    "layout_audit_v2": "layout-audit-v3",
    "resume_advisor_jd_decode_v1": "resume-advisor-jd-v1",
    "resume_advisor_draft_v1": "resume-advisor-draft-v1",
    "resume_advisor_quality_v1": "resume-advisor-quality-v1",
}

_PROMPT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")
PROMPT_FILES_BY_NAMESPACE: dict[str, list[str]] = {
    "job_decode_v2": [os.path.join(_PROMPT_DIR, "job_decoder.md")],
    "resume_section_rewrite_v2": [os.path.join(_PROMPT_DIR, "resume_copywriter.md")],
    "resume_hr_critic_v2": [os.path.join(_PROMPT_DIR, "hr_critic.md")],
    "resume_advisor_jd_decode_v1": [os.path.join(_PROMPT_DIR, "job_decoder.md")],
    "resume_advisor_draft_v1": [os.path.join(_PROMPT_DIR, "resume_copywriter.md")],
    "resume_advisor_quality_v1": [os.path.join(_PROMPT_DIR, "hr_critic.md")],
}


def normalize_cache_text(text: str) -> str:
    """Normalize user text so harmless whitespace changes still hit cache."""
    normalized = re.sub(r"\s+", " ", (text or "").strip())
    normalized = re.sub(r"\s*([，。；：、,.;:!?！？])\s*", r"\1", normalized)
    normalized = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", normalized)
    return normalized


def stable_cache_payload(value: Any) -> Any:
    if isinstance(value, str):
        return normalize_cache_text(value)
    if isinstance(value, dict):
        return {str(k): stable_cache_payload(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [stable_cache_payload(item) for item in value]
    return value


def _hash_files(paths: Sequence[str]) -> str:
    digest = hashlib.sha256()
    has_content = False
    resolved_paths = [str(path) for path in paths if path]
    for path in sorted(resolved_paths, key=lambda value: (os.path.basename(value), value)):
        digest.update(os.path.basename(path).encode("utf-8"))
        if os.path.exists(path):
            has_content = True
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    digest.update(chunk)
        else:
            digest.update(b"<missing>")
    return digest.hexdigest() if has_content or resolved_paths else "no-prompt-file"


def build_cache_key(
    namespace: str,
    *parts: Any,
    prompt_files: Sequence[str] | None = None,
    schema_version: str | None = None,
    tool_version: str | None = None,
) -> str:
    resolved_prompt_files = list(prompt_files) if prompt_files is not None else PROMPT_FILES_BY_NAMESPACE.get(namespace, [])
    payload = {
        "namespace": namespace,
        "namespace_version": CACHE_NAMESPACE_VERSIONS.get(namespace, "default-v1"),
        "schema_version": schema_version or AGENT_SCHEMA_VERSION,
        "tool_version": tool_version or AGENT_TOOL_VERSION,
        "prompt_hash": _hash_files(resolved_prompt_files),
        "parts": [stable_cache_payload(part) for part in parts],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class AgentCacheStore(ABC):
    @abstractmethod
    def get(self, namespace: str, key: str) -> Any | None:
        raise NotImplementedError

    @abstractmethod
    def set(self, namespace: str, key: str, value: Any) -> None:
        raise NotImplementedError

    @abstractmethod
    def clear_namespace(self, namespace: str) -> None:
        raise NotImplementedError


class FileAgentCacheStore(AgentCacheStore):
    def __init__(
        self,
        base_dir: str | None = None,
        *,
        ttl_seconds: int | None = None,
        max_items: int = _MAX_CACHE_ITEMS,
    ):
        self.base_dir = base_dir or os.path.join(Config.USER_DB_DIR, "agent_cache")
        self.ttl_seconds = Config.AGENT_CACHE_TTL_SECONDS if ttl_seconds is None else int(ttl_seconds)
        self.lock_timeout_seconds = Config.AGENT_CACHE_LOCK_TIMEOUT_SECONDS
        self.max_items = max_items

    def _cache_file(self, namespace: str) -> str:
        safe_namespace = re.sub(r"[^A-Za-z0-9_.-]+", "_", namespace)
        os.makedirs(self.base_dir, exist_ok=True)
        return os.path.join(self.base_dir, f"{safe_namespace}.json")

    @contextmanager
    def _file_lock(self, namespace: str) -> Iterator[None]:
        path = self._cache_file(namespace)
        lock_path = f"{path}.lock"
        deadline = time.time() + max(0.1, float(self.lock_timeout_seconds))
        fd: int | None = None
        while True:
            try:
                fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
                os.write(fd, f"{os.getpid()} {time.time()}".encode("utf-8"))
                break
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(lock_path) > max(30.0, float(self.lock_timeout_seconds) * 2):
                        os.remove(lock_path)
                        continue
                except OSError:
                    pass
                if time.time() >= deadline:
                    raise TimeoutError(f"获取 Agent 缓存锁超时: {namespace}")
                time.sleep(0.05)
        try:
            yield
        finally:
            if fd is not None:
                os.close(fd)
            try:
                os.remove(lock_path)
            except FileNotFoundError:
                pass

    def _read_namespace(self, namespace: str) -> dict[str, Any]:
        path = self._cache_file(namespace)
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _write_namespace(self, namespace: str, data: dict[str, Any]) -> None:
        path = self._cache_file(namespace)
        tmp_path = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp_path, path)

    def _is_expired(self, item: dict[str, Any]) -> bool:
        if self.ttl_seconds <= 0:
            return False
        created_at = item.get("created_at")
        if not created_at:
            return False
        try:
            created = datetime.fromisoformat(str(created_at))
        except ValueError:
            return True
        return (datetime.now() - created).total_seconds() > self.ttl_seconds

    def _prune(self, data: dict[str, Any]) -> dict[str, Any]:
        live = {
            key: value
            for key, value in data.items()
            if isinstance(value, dict) and not self._is_expired(value)
        }
        if len(live) <= self.max_items:
            return live
        ordered = sorted(
            live.items(),
            key=lambda pair: pair[1].get("last_hit_at") or pair[1].get("created_at") or "",
        )
        for old_key, _ in ordered[: max(1, len(live) - self.max_items)]:
            live.pop(old_key, None)
        return live

    def get(self, namespace: str, key: str) -> Any | None:
        with _CACHE_LOCK:
            with self._file_lock(namespace):
                data = self._prune(self._read_namespace(namespace))
                item = data.get(key)
                if not isinstance(item, dict) or "value" not in item:
                    self._write_namespace(namespace, data)
                    return None
                if self._is_expired(item):
                    data.pop(key, None)
                    self._write_namespace(namespace, data)
                    return None
                item["last_hit_at"] = datetime.now().isoformat()
                item["hit_count"] = int(item.get("hit_count") or 0) + 1
                data[key] = item
                self._write_namespace(namespace, data)
                return item["value"]

    def set(self, namespace: str, key: str, value: Any) -> None:
        with _CACHE_LOCK:
            with self._file_lock(namespace):
                data = self._prune(self._read_namespace(namespace))
                data[key] = {
                    "value": value,
                    "created_at": datetime.now().isoformat(),
                    "last_hit_at": "",
                    "hit_count": 0,
                }
                data = self._prune(data)
                self._write_namespace(namespace, data)

    def clear_namespace(self, namespace: str) -> None:
        with _CACHE_LOCK:
            with self._file_lock(namespace):
                path = self._cache_file(namespace)
                if os.path.exists(path):
                    os.remove(path)


class RedisAgentCacheStore(AgentCacheStore):
    def __init__(
        self,
        redis_client: Any | None = None,
        *,
        ttl_seconds: int | None = None,
        key_prefix: str = "internpath:agent_cache",
    ):
        self.ttl_seconds = Config.AGENT_CACHE_TTL_SECONDS if ttl_seconds is None else int(ttl_seconds)
        self.key_prefix = key_prefix.rstrip(":")
        if redis_client is not None:
            self.redis = redis_client
        else:
            if not Config.REDIS_URL:
                raise RuntimeError("REDIS_URL is required when AGENT_CACHE_STORE=redis.")
            from redis import Redis

            self.redis = Redis.from_url(Config.REDIS_URL)

    def _redis_key(self, namespace: str, key: str) -> str:
        safe_namespace = re.sub(r"[^A-Za-z0-9_.-]+", "_", namespace)
        return f"{self.key_prefix}:{safe_namespace}:{key}"

    def get(self, namespace: str, key: str) -> Any | None:
        raw = self.redis.get(self._redis_key(namespace, key))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            payload = json.loads(str(raw))
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict) or "value" not in payload:
            return None
        payload["last_hit_at"] = datetime.now().isoformat()
        payload["hit_count"] = int(payload.get("hit_count") or 0) + 1
        encoded = json.dumps(payload, ensure_ascii=False)
        redis_key = self._redis_key(namespace, key)
        if self.ttl_seconds > 0:
            self.redis.setex(redis_key, self.ttl_seconds, encoded)
        else:
            self.redis.set(redis_key, encoded)
        return payload["value"]

    def set(self, namespace: str, key: str, value: Any) -> None:
        payload = {
            "value": value,
            "created_at": datetime.now().isoformat(),
            "last_hit_at": "",
            "hit_count": 0,
        }
        encoded = json.dumps(payload, ensure_ascii=False)
        redis_key = self._redis_key(namespace, key)
        if self.ttl_seconds > 0:
            self.redis.setex(redis_key, self.ttl_seconds, encoded)
        else:
            self.redis.set(redis_key, encoded)

    def clear_namespace(self, namespace: str) -> None:
        pattern = self._redis_key(namespace, "*")
        keys = list(self.redis.scan_iter(match=pattern))
        if keys:
            self.redis.delete(*keys)


class PostgresAgentCacheStore(AgentCacheStore):
    def __init__(
        self,
        db: Any | None = None,
        *,
        ttl_seconds: int | None = None,
        max_items: int = _MAX_CACHE_ITEMS,
    ):
        from database import Database

        self.db = db or Database()
        self.ttl_seconds = Config.AGENT_CACHE_TTL_SECONDS if ttl_seconds is None else int(ttl_seconds)
        self.max_items = max_items
        self._ensure_table()

    def _ensure_table(self) -> None:
        from database import DatabaseCursorWrapper

        conn = self.db.get_connection()
        cursor = DatabaseCursorWrapper(conn.cursor(), self.db.is_postgres)
        try:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_cache_entries (
                    namespace VARCHAR(128) NOT NULL,
                    cache_key VARCHAR(128) NOT NULL,
                    value_json TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_hit_at TIMESTAMP NULL,
                    hit_count INTEGER DEFAULT 0,
                    PRIMARY KEY (namespace, cache_key)
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_agent_cache_entries_namespace_time
                ON agent_cache_entries(namespace, created_at)
                """
            )
            conn.commit()
        finally:
            conn.close()

    def _prune_namespace(self, cursor: Any, namespace: str) -> None:
        if self.ttl_seconds > 0:
            cutoff = datetime.now() - timedelta(seconds=self.ttl_seconds)
            cursor.execute(
                "DELETE FROM agent_cache_entries WHERE namespace = ? AND created_at < ?",
                (namespace, cutoff),
            )
        cursor.execute(
            "SELECT COUNT(*) FROM agent_cache_entries WHERE namespace = ?",
            (namespace,),
        )
        count_row = cursor.fetchone()
        count = int(count_row[0] or 0) if count_row else 0
        overflow = count - self.max_items
        if overflow > 0:
            cursor.execute(
                """
                DELETE FROM agent_cache_entries
                WHERE namespace = ?
                  AND cache_key IN (
                    SELECT cache_key
                    FROM agent_cache_entries
                    WHERE namespace = ?
                    ORDER BY COALESCE(last_hit_at, created_at), created_at
                    LIMIT ?
                  )
                """,
                (namespace, namespace, overflow),
            )

    def get(self, namespace: str, key: str) -> Any | None:
        from database import DatabaseCursorWrapper

        conn = self.db.get_connection()
        cursor = DatabaseCursorWrapper(conn.cursor(), self.db.is_postgres)
        try:
            self._prune_namespace(cursor, namespace)
            cursor.execute(
                """
                SELECT value_json, created_at
                FROM agent_cache_entries
                WHERE namespace = ? AND cache_key = ?
                """,
                (namespace, key),
            )
            row = cursor.fetchone()
            if not row:
                conn.commit()
                return None
            if self.ttl_seconds > 0 and row[1]:
                created_at = row[1]
                if isinstance(created_at, str):
                    created_at = datetime.fromisoformat(created_at)
                if (datetime.now() - created_at).total_seconds() > self.ttl_seconds:
                    cursor.execute(
                        "DELETE FROM agent_cache_entries WHERE namespace = ? AND cache_key = ?",
                        (namespace, key),
                    )
                    conn.commit()
                    return None
            try:
                value = json.loads(row[0])
            except json.JSONDecodeError:
                cursor.execute(
                    "DELETE FROM agent_cache_entries WHERE namespace = ? AND cache_key = ?",
                    (namespace, key),
                )
                conn.commit()
                return None
            cursor.execute(
                """
                UPDATE agent_cache_entries
                SET last_hit_at = ?, hit_count = COALESCE(hit_count, 0) + 1
                WHERE namespace = ? AND cache_key = ?
                """,
                (datetime.now(), namespace, key),
            )
            conn.commit()
            return value
        finally:
            conn.close()

    def set(self, namespace: str, key: str, value: Any) -> None:
        from database import DatabaseCursorWrapper

        conn = self.db.get_connection()
        cursor = DatabaseCursorWrapper(conn.cursor(), self.db.is_postgres)
        try:
            self._prune_namespace(cursor, namespace)
            cursor.execute(
                """
                INSERT INTO agent_cache_entries (
                    namespace, cache_key, value_json, created_at, last_hit_at, hit_count
                )
                VALUES (?, ?, ?, ?, NULL, 0)
                ON CONFLICT (namespace, cache_key)
                DO UPDATE SET
                    value_json = EXCLUDED.value_json,
                    created_at = EXCLUDED.created_at,
                    last_hit_at = NULL,
                    hit_count = 0
                """,
                (namespace, key, json.dumps(value, ensure_ascii=False), datetime.now()),
            )
            self._prune_namespace(cursor, namespace)
            conn.commit()
        finally:
            conn.close()

    def clear_namespace(self, namespace: str) -> None:
        from database import DatabaseCursorWrapper

        conn = self.db.get_connection()
        cursor = DatabaseCursorWrapper(conn.cursor(), self.db.is_postgres)
        try:
            cursor.execute(
                "DELETE FROM agent_cache_entries WHERE namespace = ?",
                (namespace,),
            )
            conn.commit()
        finally:
            conn.close()


_STORE: AgentCacheStore | None = None
_STORE_SIGNATURE: tuple[Any, ...] | None = None


def get_agent_cache_store() -> AgentCacheStore:
    global _STORE, _STORE_SIGNATURE
    store_name = (Config.AGENT_CACHE_STORE or "file").strip().lower()
    signature = (
        store_name,
        Config.USER_DB_DIR,
        Config.REDIS_URL,
        Config.DATABASE_URL,
        Config.AGENT_CACHE_TTL_SECONDS,
        Config.AGENT_CACHE_LOCK_TIMEOUT_SECONDS,
    )
    if _STORE is not None and _STORE_SIGNATURE == signature:
        return _STORE
    if store_name == "file":
        _STORE = FileAgentCacheStore()
    elif store_name == "redis":
        _STORE = RedisAgentCacheStore()
    elif store_name in {"postgres", "postgresql"}:
        _STORE = PostgresAgentCacheStore()
    else:
        raise RuntimeError(f"未知 Agent 缓存存储类型: {store_name}")
    _STORE_SIGNATURE = signature
    return _STORE


def get_agent_cache(namespace: str, key: str) -> Any | None:
    return get_agent_cache_store().get(namespace, key)


def set_agent_cache(namespace: str, key: str, value: Any) -> None:
    get_agent_cache_store().set(namespace, key, value)


def clear_agent_cache_namespace(namespace: str) -> None:
    get_agent_cache_store().clear_namespace(namespace)
