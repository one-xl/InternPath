import json
import os
import hashlib
from datetime import datetime
from typing import Any, List, Optional, Tuple
from uuid import uuid4

from auth import hash_password, normalize_username, verify_password_hash, parse_password_hash
from config import Config
from models import (
    BilibiliCourse,
    AnalysisReport,
    AnalysisTask,
    ClaimCheckResult,
    FitExamAttempt,
    FitExamPaper,
    FitExamQuestion,
    JDRecord,
    JobAnalysis,
    JobPosting,
    SalarySnapshot,
    User,
)


def safe_datetime(val) -> Optional[datetime]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.replace(tzinfo=None)
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val).replace(tzinfo=None)
        except ValueError:
            return datetime.strptime(val.split(".")[0], "%Y-%m-%d %H:%M:%S")
    return None


def safe_json_load(value: Any, default: Any = None) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, (str, bytes, bytearray)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


class DatabaseCursorWrapper:
    def __init__(self, cursor, is_postgres: bool):
        if not is_postgres:
            raise RuntimeError("DatabaseCursorWrapper supports PostgreSQL connections only.")
        self._cursor = cursor
        self._lastrowid = None

    def execute(self, query: str, params: tuple = ()):
        query = query.replace("?", "%s")
        # Translate legacy table creation keywords used by older query helpers.
        if "CREATE TABLE" in query.upper():
            query = query.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
        is_insert = query.strip().upper().startswith("INSERT")
        if is_insert and "RETURNING" not in query.upper():
            # Avoid appending "RETURNING id" if the table does not have an "id" column
            q_lower = query.lower()
            has_no_id_col = (
                "into sessions" in q_lower or
                "into user_settings" in q_lower or
                "into agent_resume_tasks" in q_lower or
                "into agent_resume_conversation_state" in q_lower or
                "into agent_cache_entries" in q_lower or
                "into model_config_assignments" in q_lower
            )
            if not has_no_id_col:
                q = query.strip()
                if q.endswith(";"):
                    q = q[:-1]
                query = f"{q} RETURNING id"
                self._cursor.execute(query, params)
                res = self._cursor.fetchone()
                self._lastrowid = res[0] if res else None
                return self

        self._cursor.execute(query, params)
        return self

    @property
    def lastrowid(self):
        return self._lastrowid

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def fetchmany(self, size=None):
        return self._cursor.fetchmany(size) if size is not None else self._cursor.fetchmany()

    def __getattr__(self, name):
        return getattr(self._cursor, name)

    def __iter__(self):
        return iter(self._cursor)


class DatabaseConnectionWrapper:
    def __init__(self, conn, is_postgres: bool):
        if not is_postgres:
            raise RuntimeError("DatabaseConnectionWrapper supports PostgreSQL connections only.")
        self._conn = conn

    def cursor(self):
        return DatabaseCursorWrapper(self._conn.cursor(), True)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.rollback()
        else:
            self.commit()
        self.close()

    def __getattr__(self, name):
        return getattr(self._conn, name)


class Database:
    _DEFAULT_DB_PATH = Config.DB_PATH

    @property
    def is_postgres(self) -> bool:
        return True

    @is_postgres.setter
    def is_postgres(self, value: bool) -> None:
        if value is not True:
            raise RuntimeError("InternPath runtime supports PostgreSQL only.")

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path if db_path is not None else Config.DB_PATH
        self.database_url = (Config.DATABASE_URL or os.getenv("DATABASE_URL") or "").strip()
        self.schema_name = self._resolve_schema_name(self.db_path)
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required. InternPath now runs on PostgreSQL only.")
        if not (self.database_url.startswith("postgresql://") or self.database_url.startswith("postgres://")):
            raise RuntimeError("DATABASE_URL must be a PostgreSQL connection string.")
        self.is_postgres = True
        try:
            import psycopg2
            conn = psycopg2.connect(self.database_url)
            self._prepare_connection(conn)
            conn.close()
        except Exception as exc:
            raise RuntimeError(f"PostgreSQL is required but unavailable: {exc}") from exc
        self.init_db()

    def get_connection(self):
        import psycopg2
        conn = psycopg2.connect(self.database_url)
        self._prepare_connection(conn)
        return DatabaseConnectionWrapper(conn, True)

    def _resolve_schema_name(self, db_path: str) -> str:
        configured_schema = (Config.DATABASE_SCHEMA or os.getenv("DATABASE_SCHEMA") or "public").strip() or "public"
        if self._is_custom_db_path(db_path):
            path_key = os.path.abspath(str(db_path)).lower()
            return f"internpath_test_{hashlib.sha1(path_key.encode('utf-8')).hexdigest()[:16]}"
        return self._validate_schema_name(configured_schema)

    def _is_custom_db_path(self, db_path: str) -> bool:
        try:
            return os.path.abspath(str(db_path)) != os.path.abspath(str(self._DEFAULT_DB_PATH))
        except Exception:
            return str(db_path) != str(self._DEFAULT_DB_PATH)

    def _validate_schema_name(self, schema_name: str) -> str:
        if not schema_name or not schema_name[0].isalpha() or not schema_name.replace("_", "").isalnum():
            raise RuntimeError("DATABASE_SCHEMA must contain only letters, numbers, and underscores, and start with a letter.")
        return schema_name

    def _prepare_connection(self, conn) -> None:
        schema_name = self._validate_schema_name(self.schema_name)
        cursor = conn.cursor()
        cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"')
        cursor.execute(f'SET search_path TO "{schema_name}", public')
        conn.commit()
        cursor.close()

    @classmethod
    def for_user(cls, user_id: int) -> "Database":
        db = cls()
        db._ensure_user_id(user_id)
        return db

    def _ensure_user_id(self, user_id: int) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        username = f"system-user-{int(user_id)}@internpath.local"
        cursor.execute(
            """
            INSERT INTO users (id, username, password_hash, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (id) DO NOTHING
            """,
            (int(user_id), username, hash_password(f"system-user-{int(user_id)}"), datetime.now().isoformat()),
        )
        cursor.execute(
            "SELECT setval(pg_get_serial_sequence('users', 'id'), COALESCE((SELECT MAX(id) FROM users), 1), true)"
        )
        conn.commit()
        conn.close()

    def _ensure_numeric_user_id(self, user_id: Any) -> None:
        try:
            numeric_user_id = int(user_id)
        except (TypeError, ValueError):
            return
        self._ensure_user_id(numeric_user_id)

    def _serialize_datetime_value(self, value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        return value

    def _column_exists(self, cursor, table_name: str, column_name: str) -> bool:
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = %s
                  AND column_name = %s
            )
            """,
            (table_name.lower(), column_name.lower()),
        )
        return bool(cursor.fetchone()[0])

    def _table_columns(self, cursor, table_name: str) -> set[str]:
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = %s
            """,
            (table_name.lower(),),
        )
        return {str(row[0]).lower() for row in cursor.fetchall()}

    def _is_unique_constraint_error(self, exc: Exception) -> bool:
        if getattr(exc, "pgcode", None) == "23505":
            return True
        message = str(exc).lower()
        return "unique" in message or "duplicate" in message

    def init_db(self):
        conn = self.get_connection()
        cursor = conn.cursor()

        if self.is_postgres:
            # 1. Enable required PostgreSQL extensions.
            try:
                cursor.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;")
                conn.commit()
            except Exception as exc:
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise RuntimeError(f"PostgreSQL extension pgcrypto is required: {exc}") from exc

            try:
                cursor.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;")
                conn.commit()
            except Exception as exc:
                try:
                    conn.rollback()
                except Exception:
                    pass
                if Config.PGVECTOR_REQUIRED:
                    raise RuntimeError(f"PostgreSQL extension vector is required: {exc}") from exc
                raise

            # 2. Create users table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(255) UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            # 3. Create registered_devices table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS registered_devices (
                    id SERIAL PRIMARY KEY,
                    device_signature VARCHAR(255) UNIQUE NOT NULL,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    username VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            # 4. Create analysis_records table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_records (
                    id VARCHAR(255) PRIMARY KEY DEFAULT gen_random_uuid()::text,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    status VARCHAR(50) NOT NULL,
                    input_json JSONB NOT NULL,
                    parsed_jd_json JSONB,
                    parsed_resume_json JSONB,
                    requirement_matches_json JSONB,
                    hard_constraint_results_json JSONB,
                    result_json JSONB,
                    failed_step VARCHAR(255),
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            # 5. Create drafts table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS drafts (
                    id VARCHAR(255) PRIMARY KEY DEFAULT gen_random_uuid()::text,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    status VARCHAR(50) NOT NULL,
                    input_json JSONB NOT NULL,
                    failed_step VARCHAR(255),
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            # 5b. Create resumes table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS resumes (
                    id VARCHAR(255) PRIMARY KEY,
                    user_id VARCHAR(255) NOT NULL,
                    file_name VARCHAR(255) NOT NULL,
                    file_size INTEGER NOT NULL,
                    file_type VARCHAR(100),
                    parsed_json JSONB NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            # 6. Create user_settings table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS user_settings (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    settings_json JSONB NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            # 7. Create model_configs table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS model_configs (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    provider VARCHAR(50) NOT NULL,
                    model_id VARCHAR(255) NOT NULL,
                    display_name VARCHAR(255),
                    encrypted_api_key TEXT,
                    is_server_managed BOOLEAN NOT NULL DEFAULT FALSE,
                    enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    config_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    owner_type VARCHAR(50) NOT NULL DEFAULT 'user',
                    created_by_admin_id INTEGER REFERENCES users(id) ON DELETE SET NULL
                );
                """
            )
            if not self._column_exists(cursor, "model_configs", "config_json"):
                cursor.execute("ALTER TABLE model_configs ADD COLUMN config_json TEXT")
            if not self._column_exists(cursor, "users", "role"):
                cursor.execute("ALTER TABLE users ADD COLUMN role VARCHAR(50) DEFAULT 'user'")
            if not self._column_exists(cursor, "model_configs", "owner_type"):
                cursor.execute("ALTER TABLE model_configs ADD COLUMN owner_type VARCHAR(50) DEFAULT 'user'")
            if not self._column_exists(cursor, "model_configs", "created_by_admin_id"):
                cursor.execute("ALTER TABLE model_configs ADD COLUMN created_by_admin_id INTEGER REFERENCES users(id) ON DELETE SET NULL")
            if not self._column_exists(cursor, "users", "is_active"):
                cursor.execute("ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT TRUE")
            if not self._column_exists(cursor, "users", "expires_at"):
                cursor.execute("ALTER TABLE users ADD COLUMN expires_at TIMESTAMP")
            if not self._column_exists(cursor, "users", "generation_limit"):
                cursor.execute("ALTER TABLE users ADD COLUMN generation_limit INTEGER DEFAULT 5")
            if not self._column_exists(cursor, "users", "remark"):
                cursor.execute("ALTER TABLE users ADD COLUMN remark TEXT")

            # 7b. Create model_config_assignments table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS model_config_assignments (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    config_id UUID NOT NULL REFERENCES model_configs(id) ON DELETE CASCADE,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    assigned_by_admin_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (config_id, user_id)
                );
                """
            )

            # 7c. Create model_usage_logs table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS model_usage_logs (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    config_id UUID REFERENCES model_configs(id) ON DELETE SET NULL,
                    assignment_id UUID REFERENCES model_config_assignments(id) ON DELETE SET NULL,
                    analysis_id VARCHAR(255),
                    provider VARCHAR(50) NOT NULL,
                    model_id VARCHAR(255) NOT NULL,
                    usage_type VARCHAR(50),
                    endpoint TEXT,
                    success BOOLEAN NOT NULL,
                    error_type TEXT,
                    prompt_tokens INTEGER,
                    completion_tokens INTEGER,
                    total_tokens INTEGER,
                    input_chars INTEGER,
                    output_chars INTEGER,
                    latency_ms INTEGER,
                    cost_estimate NUMERIC,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            # 7d. Create admin_audit_logs table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_audit_logs (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    admin_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    action VARCHAR(255) NOT NULL,
                    target_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    target_resource_type VARCHAR(255),
                    target_resource_id VARCHAR(255),
                    metadata_json JSONB,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            # 8. Create embeddings table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS embeddings (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    analysis_id VARCHAR(255) REFERENCES analysis_records(id) ON DELETE CASCADE,
                    source_type VARCHAR(50) NOT NULL,
                    source_id VARCHAR(255),
                    content_hash VARCHAR(255),
                    embedding vector,
                    metadata_json JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            # 9. Create all other original tables for PostgreSQL
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS jd_records (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    jd_text TEXT NOT NULL,
                    skills TEXT NOT NULL,
                    difficulty VARCHAR(50) NOT NULL,
                    job_summary TEXT NOT NULL,
                    personal_decision_json TEXT,
                    display_name VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS course_records (
                    id SERIAL PRIMARY KEY,
                    skill VARCHAR(255) NOT NULL,
                    title VARCHAR(255) NOT NULL,
                    url TEXT NOT NULL,
                    view_count INTEGER NOT NULL,
                    favorite_count INTEGER NOT NULL,
                    like_count INTEGER NOT NULL,
                    coin_count INTEGER DEFAULT 0,
                    publish_date VARCHAR(50) NOT NULL,
                    uploader VARCHAR(255) NOT NULL,
                    rank_score REAL NOT NULL,
                    jd_record_id INTEGER NOT NULL REFERENCES jd_records(id) ON DELETE CASCADE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS job_postings (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    title VARCHAR(255) NOT NULL,
                    company VARCHAR(255) NOT NULL DEFAULT '',
                    region VARCHAR(255) NOT NULL DEFAULT '',
                    latitude REAL,
                    longitude REAL,
                    transit_minutes INTEGER,
                    salary_monthly_k REAL NOT NULL,
                    jd_record_id INTEGER REFERENCES jd_records(id) ON DELETE SET NULL,
                    source_url TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS salary_snapshots (
                    id SERIAL PRIMARY KEY,
                    job_posting_id INTEGER NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
                    observed_at TIMESTAMP NOT NULL,
                    salary_monthly_k REAL NOT NULL,
                    note TEXT NOT NULL DEFAULT ''
                );
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS fit_exam_attempts (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    jd_record_id INTEGER REFERENCES jd_records(id) ON DELETE SET NULL,
                    major_profile VARCHAR(255) NOT NULL DEFAULT '',
                    paper_json TEXT NOT NULL,
                    answers_json TEXT NOT NULL,
                    score REAL NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_task (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    task_id VARCHAR(255) UNIQUE NOT NULL,
                    jd_id INTEGER,
                    status VARCHAR(50),
                    enable_rag INTEGER,
                    enable_verification INTEGER,
                    enable_hallucination_check INTEGER,
                    enable_rewrite INTEGER,
                    error_message TEXT,
                    created_at TEXT,
                    updated_at TEXT
                );
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_report (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    task_id VARCHAR(255) NOT NULL,
                    jd_text TEXT,
                    resume_text TEXT,
                    knowledge_texts TEXT,
                    original_analysis_json TEXT,
                    final_report_json TEXT,
                    evidence_summary_json TEXT,
                    hallucination_control_json TEXT,
                    citations_json TEXT,
                    credibility_score REAL,
                    evidence_coverage REAL,
                    hallucination_risk VARCHAR(50),
                    created_at TEXT,
                    updated_at TEXT
                );
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS claim_check_result (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    task_id VARCHAR(255) NOT NULL,
                    claim_id VARCHAR(255),
                    claim_text TEXT,
                    claim_type VARCHAR(50),
                    check_status VARCHAR(50),
                    confidence_score REAL,
                    evidence_count INTEGER,
                    reason TEXT,
                    evidence_json TEXT,
                    created_at TEXT
                );
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_document (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    title VARCHAR(255),
                    file_name VARCHAR(255),
                    file_type VARCHAR(50),
                    source_type VARCHAR(50),
                    raw_text TEXT,
                    summary TEXT,
                    chunk_count INTEGER,
                    status VARCHAR(50),
                    error_message TEXT,
                    created_at TEXT,
                    updated_at TEXT
                );
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_chunk (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    document_id INTEGER REFERENCES knowledge_document(id) ON DELETE CASCADE,
                    chunk_index INTEGER,
                    chunk_text TEXT,
                    token_count INTEGER,
                    metadata_json TEXT,
                    created_at TEXT,
                    section_id VARCHAR(255),
                    section_type VARCHAR(255),
                    section_title VARCHAR(255),
                    hierarchy_json TEXT,
                    semantic_type VARCHAR(255),
                    importance REAL,
                    keywords_json TEXT,
                    embedding_text TEXT,
                    embedding vector
                );
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_workflow_log (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    task_id VARCHAR(255) NOT NULL,
                    node_name VARCHAR(255),
                    status VARCHAR(50),
                    duration_ms INTEGER,
                    input_summary TEXT,
                    output_summary TEXT,
                    error_message TEXT,
                    created_at TEXT
                );
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_quality_evaluation (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    task_id VARCHAR(255) NOT NULL,
                    final_quality_score REAL,
                    quality_grade VARCHAR(50),
                    quality_gate_status VARCHAR(50),
                    evidence_coverage_score REAL,
                    hallucination_risk_score REAL,
                    citation_completeness_score REAL,
                    resume_honesty_score REAL,
                    match_score_reasonableness REAL,
                    issues_json TEXT,
                    summary TEXT,
                    created_at TEXT
                );
                """
            )

            # 10. Indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_model_configs_owner_type ON model_configs(owner_type, enabled);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_model_config_assignments_user ON model_config_assignments(user_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_model_config_assignments_config ON model_config_assignments(config_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_model_usage_logs_user ON model_usage_logs(user_id, created_at DESC);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_model_usage_logs_config ON model_usage_logs(config_id, created_at DESC);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_model_usage_logs_provider_model ON model_usage_logs(provider, model_id, created_at DESC);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_model_usage_logs_success ON model_usage_logs(success, created_at DESC);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_analysis_records_user_created ON analysis_records(user_id, created_at DESC);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_drafts_user_updated ON drafts(user_id, updated_at DESC);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_settings_user ON user_settings(user_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_model_configs_user_provider ON model_configs(user_id, provider);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_embeddings_user_analysis ON embeddings(user_id, analysis_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_embeddings_user_hash ON embeddings(user_id, content_hash);")
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS email_verification_codes (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    email VARCHAR(255) NOT NULL,
                    code_hash TEXT NOT NULL,
                    purpose VARCHAR(50) NOT NULL DEFAULT 'register',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 5,
                    expires_at TIMESTAMP NOT NULL,
                    used_at TIMESTAMP,
                    request_ip VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_email_codes_email_purpose ON email_verification_codes(email, purpose, created_at DESC);")

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_jd_records_user_created ON jd_records(user_id, created_at);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_analysis_report_user_created ON analysis_report(user_id, created_at);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_analysis_task_user_updated ON analysis_task(user_id, updated_at);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_document_user ON knowledge_document(user_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_chunk_user_doc ON knowledge_chunk(user_id, document_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_job_postings_user ON job_postings(user_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_fit_exam_attempts_user ON fit_exam_attempts(user_id);")

            # PostgreSQL columns migration for knowledge_chunk
            if not self._column_exists(cursor, "knowledge_chunk", "section_id"):
                cursor.execute("ALTER TABLE knowledge_chunk ADD COLUMN section_id VARCHAR(255)")
            if not self._column_exists(cursor, "knowledge_chunk", "section_type"):
                cursor.execute("ALTER TABLE knowledge_chunk ADD COLUMN section_type VARCHAR(255)")
            if not self._column_exists(cursor, "knowledge_chunk", "section_title"):
                cursor.execute("ALTER TABLE knowledge_chunk ADD COLUMN section_title VARCHAR(255)")
            if not self._column_exists(cursor, "knowledge_chunk", "hierarchy_json"):
                cursor.execute("ALTER TABLE knowledge_chunk ADD COLUMN hierarchy_json TEXT")
            if not self._column_exists(cursor, "knowledge_chunk", "semantic_type"):
                cursor.execute("ALTER TABLE knowledge_chunk ADD COLUMN semantic_type VARCHAR(255)")
            if not self._column_exists(cursor, "knowledge_chunk", "importance"):
                cursor.execute("ALTER TABLE knowledge_chunk ADD COLUMN importance REAL")
            if not self._column_exists(cursor, "knowledge_chunk", "keywords_json"):
                cursor.execute("ALTER TABLE knowledge_chunk ADD COLUMN keywords_json TEXT")
            if not self._column_exists(cursor, "knowledge_chunk", "embedding_text"):
                cursor.execute("ALTER TABLE knowledge_chunk ADD COLUMN embedding_text TEXT")
            if not self._column_exists(cursor, "knowledge_chunk", "embedding"):
                cursor.execute("ALTER TABLE knowledge_chunk ADD COLUMN embedding vector")

            # 11. Sessions table for persistent authentication
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    token VARCHAR(64) PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP NOT NULL
                );
                """
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);")

            # 12. star_stories table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS star_stories (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    title VARCHAR(255) NOT NULL,
                    situation TEXT,
                    task TEXT,
                    action TEXT,
                    result TEXT,
                    full_text TEXT,
                    style VARCHAR(50) DEFAULT 'standard',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_star_stories_user ON star_stories(user_id);")

            # 13. announcements table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS announcements (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    title VARCHAR(255) NOT NULL,
                    content TEXT NOT NULL,
                    start_time TIMESTAMP NOT NULL,
                    end_time TIMESTAMP NOT NULL,
                    target_type VARCHAR(50) NOT NULL DEFAULT 'all',
                    target_users TEXT,
                    announcement_type VARCHAR(50) NOT NULL DEFAULT 'top',
                    show_behavior VARCHAR(50) NOT NULL DEFAULT 'once',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_announcements_time ON announcements(start_time, end_time);")

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_analysis_records_user ON analysis_records(user_id, created_at DESC);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_model_configs_owner_type ON model_configs(owner_type, enabled);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_model_config_assignments_user ON model_config_assignments(user_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_model_config_assignments_config ON model_config_assignments(config_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_model_usage_logs_user ON model_usage_logs(user_id, created_at DESC);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_model_usage_logs_config ON model_usage_logs(config_id, created_at DESC);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_model_usage_logs_provider_model ON model_usage_logs(provider, model_id, created_at DESC);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_model_usage_logs_success ON model_usage_logs(success, created_at DESC);")

        # Check and alter announcements table to ensure compatibility with announcement_type column
        try:
            if not self._column_exists(cursor, "announcements", "announcement_type"):
                cursor.execute("ALTER TABLE announcements ADD COLUMN announcement_type VARCHAR(50) DEFAULT 'top';")
        except Exception as e:
            print(f"[DATABASE] Migration warning for announcements type column: {e}")

        # Check and alter announcements table to ensure compatibility with show_behavior column
        try:
            if not self._column_exists(cursor, "announcements", "show_behavior"):
                cursor.execute("ALTER TABLE announcements ADD COLUMN show_behavior VARCHAR(50) DEFAULT 'once';")
        except Exception as e:
            print(f"[DATABASE] Migration warning for announcements show_behavior column: {e}")

        # 14. Create agent_resume_tasks table
        try:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_resume_tasks (
                    task_id VARCHAR(255) PRIMARY KEY,
                    user_id VARCHAR(255) NOT NULL,
                    trace_id VARCHAR(255),
                    status VARCHAR(50) NOT NULL,
                    resume_id VARCHAR(255),
                    original_resume_name VARCHAR(255),
                    jd_text TEXT,
                    workspace_path VARCHAR(500),
                    logs TEXT,
                    optimized_resume_md TEXT,
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent_resume_tasks_user ON agent_resume_tasks(user_id);")
        except Exception as e:
            print(f"[DATABASE] Error creating agent_resume_tasks table: {e}")

        # 澧為噺杩佺Щ锛氫负 agent_resume_tasks 琛ㄨˉ鍏?pending_question, human_answer, execution_plan 瀛楁
        # 缁熶竴浣跨敤鍚屼竴涓?cursor 杩涜澧為噺淇敼锛屼笉鍐嶅紑鍚柊杩炴帴锛岄槻姝?PostgreSQL 骞跺彂浜嬪姟姝婚攣瀵艰嚧杩炴帴琚己琛屾柇寮€
        for col_name in ["pending_question", "human_answer", "execution_plan"]:
            if not self._column_exists(cursor, "agent_resume_tasks", col_name):
                cursor.execute(f"ALTER TABLE agent_resume_tasks ADD COLUMN {col_name} TEXT;")
        if not self._column_exists(cursor, "agent_resume_tasks", "trace_id"):
            cursor.execute("ALTER TABLE agent_resume_tasks ADD COLUMN trace_id VARCHAR(255);")
        cursor.execute(
            """
            UPDATE agent_resume_tasks
            SET trace_id = CONCAT('tr-', REPLACE(gen_random_uuid()::text, '-', ''))
            WHERE trace_id IS NULL OR trace_id = ''
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_resume_turns (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                task_id VARCHAR(255) NOT NULL,
                user_id VARCHAR(255) NOT NULL,
                step_index INTEGER,
                role VARCHAR(50) NOT NULL,
                content TEXT NOT NULL,
                answer_type VARCHAR(50) DEFAULT '',
                remember BOOLEAN DEFAULT FALSE,
                evidence_scope VARCHAR(50) DEFAULT '',
                consumed_at TIMESTAMP NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES agent_resume_tasks(task_id) ON DELETE CASCADE
            );
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_resume_turns_task_step ON agent_resume_turns(user_id, task_id, step_index, created_at);"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_resume_turns_unconsumed ON agent_resume_turns(user_id, task_id, step_index, role, consumed_at);"
        )
        if not self._column_exists(cursor, "agent_resume_turns", "summary"):
            cursor.execute("ALTER TABLE agent_resume_turns ADD COLUMN summary TEXT DEFAULT '';")

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_resume_conversation_state (
                task_id VARCHAR(255) PRIMARY KEY,
                user_id VARCHAR(255) NOT NULL,
                summary TEXT DEFAULT '',
                global_preferences TEXT DEFAULT '[]',
                fact_ledger TEXT DEFAULT '[]',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES agent_resume_tasks(task_id) ON DELETE CASCADE
            );
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_resume_conversation_state_user ON agent_resume_conversation_state(user_id, updated_at DESC);"
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_preferences (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id VARCHAR(255) NOT NULL,
                section_name VARCHAR(255) NOT NULL,
                preference_text TEXT NOT NULL,
                source_task_id VARCHAR(255),
                evidence_text TEXT,
                tags TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (user_id, section_name, preference_text)
            );
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_preferences_user_section ON agent_preferences(user_id, section_name, created_at DESC);"
        )
        for col_name, col_type in [
            ("source_task_id", "VARCHAR(255)"),
            ("evidence_text", "TEXT"),
            ("tags", "TEXT"),
        ]:
            if not self._column_exists(cursor, "agent_preferences", col_name):
                cursor.execute(f"ALTER TABLE agent_preferences ADD COLUMN {col_name} {col_type};")

        from backend.migrations.resume_advisor import run_resume_advisor_migrations

        run_resume_advisor_migrations(cursor)
        conn.commit()
        conn.close()


    def create_user(self, username: str, password: str, device_signature: Optional[str] = None) -> int:
        normalized = normalize_username(username)
        if not normalized:
            raise ValueError("username_required")
        if len(password) < 8:
            raise ValueError("password_too_short")

        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if device_signature:
                cursor.execute(
                    "SELECT 1 FROM registered_devices WHERE device_signature = ?",
                    (device_signature,),
                )
                if cursor.fetchone() is not None:
                    raise ValueError("device_already_registered")

            cursor.execute(
                """
                INSERT INTO users (username, password_hash, created_at)
                VALUES (?, ?, ?)
                """,
                (normalized, hash_password(password), datetime.now().isoformat()),
            )
            user_id = int(cursor.lastrowid)
            if device_signature:
                cursor.execute(
                    """
                    INSERT INTO registered_devices (device_signature, user_id, username, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (device_signature, user_id, normalized, datetime.now().isoformat()),
                )
            conn.commit()
            return user_id
        except Exception as exc:
            if self._is_unique_constraint_error(exc):
                raise ValueError("username_taken") from exc
            raise
        finally:
            conn.close()

    def authenticate_user(self, username: str, password: str) -> Optional[User]:
        normalized = normalize_username(username)
        if not normalized or not password:
            return None

        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, username, password_hash, created_at, role, is_active, expires_at, generation_limit, remark
            FROM users
            WHERE username = ?
            """,
            (normalized,),
        )
        row = cursor.fetchone()
        conn.close()
        if row is None:
            return None

        if not verify_password_hash(password, row[2]):
            return None

        is_active_val = bool(row[5]) if row[5] is not None else True
        expires_at_val = safe_datetime(row[6]) if row[6] else None
        generation_limit_val = int(row[7]) if row[7] is not None else 5
        remark_val = row[8] if row[8] else None

        return User(
            id=row[0],
            username=row[1],
            role=row[4],
            created_at=safe_datetime(row[3]),
            is_active=is_active_val,
            expires_at=expires_at_val,
            generation_limit=generation_limit_val,
            remark=remark_val
        )

    def get_user_by_id(self, user_id: int) -> Optional[User]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, username, created_at, role, is_active, expires_at, generation_limit, remark
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        )
        row = cursor.fetchone()
        conn.close()
        if row is None:
            return None
        is_active_val = bool(row[4]) if row[4] is not None else True
        expires_at_val = safe_datetime(row[5]) if row[5] else None
        generation_limit_val = int(row[6]) if row[6] is not None else 5
        remark_val = row[7] if row[7] else None
        return User(
            id=row[0],
            username=row[1],
            role=row[3],
            created_at=safe_datetime(row[2]),
            is_active=is_active_val,
            expires_at=expires_at_val,
            generation_limit=generation_limit_val,
            remark=remark_val
        )

    def get_user_by_username(self, username: str) -> Optional[User]:
        normalized = normalize_username(username)
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, username, created_at, role, is_active, expires_at, generation_limit, remark
            FROM users
            WHERE username = ?
            """,
            (normalized,),
        )
        row = cursor.fetchone()
        conn.close()
        if row is None:
            return None
        is_active_val = bool(row[4]) if row[4] is not None else True
        expires_at_val = safe_datetime(row[5]) if row[5] else None
        generation_limit_val = int(row[6]) if row[6] is not None else 5
        remark_val = row[7] if row[7] else None
        return User(
            id=row[0],
            username=row[1],
            role=row[3],
            created_at=safe_datetime(row[2]),
            is_active=is_active_val,
            expires_at=expires_at_val,
            generation_limit=generation_limit_val,
            remark=remark_val
        )

    def list_users_with_devices(self) -> list[dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                u.id,
                u.username,
                u.created_at,
                COUNT(d.id) AS device_count,
                MAX(d.created_at) AS last_device_at
            FROM users u
            LEFT JOIN registered_devices d ON d.user_id = u.id
            GROUP BY u.id, u.username, u.created_at
            ORDER BY u.created_at DESC, u.id DESC
            """
        )
        rows = cursor.fetchall()
        conn.close()
        return [
            {
                "id": row[0],
                "username": row[1],
                "created_at": row[2],
                "device_count": int(row[3] or 0),
                "last_device_at": row[4] or "",
            }
            for row in rows
        ]

    def update_user_password(self, user_id: int, password: str) -> None:
        if len(password) < 8:
            raise ValueError("password_too_short")

        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(password), user_id),
        )
        conn.commit()
        conn.close()

    def clear_registered_devices(self, user_id: int) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM registered_devices WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()

    def delete_user(self, user_id: int) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        # Clean up related records explicitly
        cursor.execute("DELETE FROM registered_devices WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM drafts WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM user_settings WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM model_config_assignments WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM fit_exam_attempts WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM analysis_records WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM course_records WHERE jd_record_id IN (SELECT id FROM jd_records WHERE user_id = ?)", (user_id,))
        cursor.execute("DELETE FROM jd_records WHERE user_id = ?", (user_id,))
        # Delete user
        cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        conn.close()

    def get_user_count(self) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        count = int(cursor.fetchone()[0])
        conn.close()
        return count

    def save_jd_record(self, user_id: Any, jd_text: str, analysis: JobAnalysis) -> Any:
        self._ensure_numeric_user_id(user_id)
        conn = self.get_connection()
        cursor = conn.cursor()
        if self.is_postgres:
            cursor.execute(
                """
                INSERT INTO jd_records (
                    user_id, jd_text, skills, difficulty, job_summary,
                    personal_decision_json, display_name, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    jd_text,
                    json.dumps(analysis.skills, ensure_ascii=False),
                    analysis.difficulty,
                    analysis.job_summary,
                    self._dump_json(analysis.personal_decision) if analysis.personal_decision else "",
                    None,
                    datetime.now().isoformat(),
                ),
            )
            jd_record_id = cursor.lastrowid
        else:
            jd_record_id = self.get_next_available_jd_record_id(cursor)
            cursor.execute(
                """
                INSERT INTO jd_records (
                    id, user_id, jd_text, skills, difficulty, job_summary,
                    personal_decision_json, display_name, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    jd_record_id,
                    user_id,
                    jd_text,
                    json.dumps(analysis.skills, ensure_ascii=False),
                    analysis.difficulty,
                    analysis.job_summary,
                    self._dump_json(analysis.personal_decision) if analysis.personal_decision else "",
                    None,
                    datetime.now().isoformat(),
                ),
            )
        conn.commit()
        conn.close()
        return jd_record_id

    def save_jd_record_and_convert_draft(self, user_id: Any, jd_text: str, analysis: JobAnalysis, draft_id: Optional[str] = None) -> Any:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("BEGIN TRANSACTION;")
            if self.is_postgres:
                cursor.execute(
                    """
                    INSERT INTO jd_records (
                        user_id, jd_text, skills, difficulty, job_summary,
                        personal_decision_json, display_name, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        jd_text,
                        json.dumps(analysis.skills, ensure_ascii=False),
                        analysis.difficulty,
                        analysis.job_summary,
                        self._dump_json(analysis.personal_decision) if analysis.personal_decision else "",
                        None,
                        datetime.now().isoformat(),
                    ),
                )
                jd_record_id = cursor.lastrowid
            else:
                jd_record_id = self.get_next_available_jd_record_id(cursor)
                cursor.execute(
                    """
                    INSERT INTO jd_records (
                        id, user_id, jd_text, skills, difficulty, job_summary,
                        personal_decision_json, display_name, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        jd_record_id,
                        user_id,
                        jd_text,
                        json.dumps(analysis.skills, ensure_ascii=False),
                        analysis.difficulty,
                        analysis.job_summary,
                        self._dump_json(analysis.personal_decision) if analysis.personal_decision else "",
                        None,
                        datetime.now().isoformat(),
                    ),
                )
            if draft_id:
                cursor.execute(
                    "UPDATE drafts SET status = ?, updated_at = ? WHERE id = ? AND user_id = ?",
                    ("converted_to_history", datetime.now().isoformat(), draft_id, user_id)
                )
            conn.commit()
            return jd_record_id
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def get_next_available_jd_record_id(self, cursor) -> int:
        rows = cursor.execute("SELECT id FROM jd_records ORDER BY id ASC").fetchall()
        next_id = 1
        for (record_id,) in rows:
            if record_id != next_id:
                break
            next_id += 1
        return next_id

    def rename_jd_record(self, user_id: int, jd_record_id: int, display_name: Optional[str]) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE jd_records SET display_name = ? WHERE id = ? AND user_id = ?",
            (display_name, jd_record_id, user_id),
        )
        conn.commit()
        conn.close()

    def delete_jd_record(self, user_id: int, jd_record_id: int) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM course_records WHERE jd_record_id IN (SELECT id FROM jd_records WHERE id = ? AND user_id = ?)",
            (jd_record_id, user_id),
        )
        cursor.execute(
            "UPDATE job_postings SET jd_record_id = NULL WHERE jd_record_id = ? AND user_id = ?",
            (jd_record_id, user_id),
        )
        cursor.execute(
            "UPDATE fit_exam_attempts SET jd_record_id = NULL WHERE jd_record_id = ? AND user_id = ?",
            (jd_record_id, user_id),
        )
        cursor.execute("DELETE FROM jd_records WHERE id = ? AND user_id = ?", (jd_record_id, user_id))
        conn.commit()
        conn.close()

    def jd_record_belongs_to_user(self, user_id: int, jd_record_id: int) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM jd_records WHERE id = ? AND user_id = ?",
            (jd_record_id, user_id),
        )
        res = cursor.fetchone()
        conn.close()
        return res is not None

    def save_courses(self, user_id: int, jd_record_id: int, courses: List[BilibiliCourse], *, replace: bool = False):
        if not self.jd_record_belongs_to_user(user_id, jd_record_id):
            raise ValueError("unauthorized_or_not_found")
        conn = self.get_connection()
        cursor = conn.cursor()
        if replace:
            cursor.execute("DELETE FROM course_records WHERE jd_record_id = ?", (jd_record_id,))

        for course in courses:
            cursor.execute(
                """
                INSERT INTO course_records (
                    skill, title, url, view_count, favorite_count, like_count,
                    coin_count, publish_date, uploader, rank_score, jd_record_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    course.skill,
                    course.title,
                    course.url,
                    course.view_count,
                    course.favorite_count,
                    course.like_count,
                    course.coin_count,
                    course.publish_date,
                    course.uploader,
                    course.rank_score,
                    jd_record_id,
                    datetime.now().isoformat(),
                ),
            )

        conn.commit()
        conn.close()

    def build_jd_record(self, row) -> JDRecord:
        return JDRecord(
            id=row[0],
            user_id=row[1],
            jd_text=row[2],
            analysis=JobAnalysis(
                skills=safe_json_load(row[3], []),
                difficulty=row[4],
                job_summary=row[5],
                personal_decision=self._load_json(row[6], None),
            ),
            display_name=row[7],
            created_at=safe_datetime(row[8]),
        )

    def get_jd_record_by_id(self, user_id: int, jd_record_id: int) -> Optional[JDRecord]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, user_id, jd_text, skills, difficulty, job_summary,
                   personal_decision_json, display_name, created_at
            FROM jd_records WHERE id = ? AND user_id = ?
            """,
            (jd_record_id, user_id),
        )
        row = cursor.fetchone()
        conn.close()
        if row is None:
            return None
        return self.build_jd_record(row)

    def get_jd_records(self, user_id: int, limit: int = 10) -> List[JDRecord]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, user_id, jd_text, skills, difficulty, job_summary,
                   personal_decision_json, display_name, created_at
            FROM jd_records
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        rows = cursor.fetchall()
        conn.close()
        return [self.build_jd_record(row) for row in rows]

    def get_courses_by_jd_id(self, user_id: int, jd_record_id: int) -> List[BilibiliCourse]:
        if not self.jd_record_belongs_to_user(user_id, jd_record_id):
            return []
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT skill, title, url, view_count, favorite_count, like_count,
                   coin_count, publish_date, uploader, rank_score
            FROM course_records
            WHERE jd_record_id = ?
            ORDER BY skill, rank_score DESC
            """,
            (jd_record_id,),
        )

        courses = []
        for row in cursor.fetchall():
            courses.append(
                BilibiliCourse(
                    skill=row[0],
                    title=row[1],
                    url=row[2],
                    view_count=row[3],
                    favorite_count=row[4],
                    like_count=row[5],
                    coin_count=row[6],
                    publish_date=row[7],
                    uploader=row[8],
                    rank_score=row[9],
                )
            )

        conn.close()
        return courses

    def create_analysis_task(
        self,
        *,
        user_id: int,
        task_id: str,
        jd_id: Optional[int] = None,
        status: str = "PENDING",
        enable_rag: bool = True,
        enable_verification: bool = True,
        enable_hallucination_check: bool = True,
        enable_rewrite: bool = True,
        error_message: str = "",
    ) -> int:
        self._ensure_numeric_user_id(user_id)
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute(
            """
            INSERT INTO analysis_task (
                user_id, task_id, jd_id, status, enable_rag, enable_verification,
                enable_hallucination_check, enable_rewrite, error_message, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                task_id,
                jd_id,
                status,
                int(enable_rag),
                int(enable_verification),
                int(enable_hallucination_check),
                int(enable_rewrite),
                error_message,
                now,
                now,
            ),
        )
        row_id = int(cursor.lastrowid)
        conn.commit()
        conn.close()
        return row_id

    def update_analysis_task_status(
        self,
        user_id: int,
        task_id: str,
        status: str,
        error_message: Optional[str] = None,
    ) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE analysis_task
            SET status = ?, error_message = COALESCE(?, error_message), updated_at = ?
            WHERE task_id = ? AND user_id = ?
            """,
            (status, error_message, datetime.now().isoformat(), task_id, user_id),
        )
        conn.commit()
        conn.close()

    def create_agent_resume_task(
        self,
        *,
        task_id: str,
        user_id: Any,
        resume_id: Optional[str] = None,
        original_resume_name: Optional[str] = None,
        jd_text: Optional[str] = None,
        workspace_path: Optional[str] = None,
    ) -> None:
        conn = self.get_connection()
        cursor = DatabaseCursorWrapper(conn.cursor(), self.is_postgres)
        now = datetime.now().isoformat()
        user_key = str(user_id)
        trace_id = f"tr-{uuid4().hex}"
        cursor.execute(
            """
            INSERT INTO agent_resume_tasks (
                task_id, user_id, trace_id, status, resume_id, original_resume_name,
                jd_text, workspace_path, logs, optimized_resume_md, error_message,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                user_key,
                trace_id,
                "PENDING",
                resume_id,
                original_resume_name,
                jd_text,
                workspace_path,
                "[]",
                "",
                "",
                now,
                now,
            ),
        )
        conn.commit()
        conn.close()

    def update_agent_resume_task_status(
        self,
        task_id: str,
        user_id: Any,
        status: str,
        error_message: Optional[str] = None,
        logs: Optional[str] = None,
        optimized_resume_md: Optional[str] = None,
        pending_question: Optional[str] = None,
        human_answer: Optional[str] = None,
        execution_plan: Optional[str] = None,
    ) -> None:
        conn = self.get_connection()
        cursor = DatabaseCursorWrapper(conn.cursor(), self.is_postgres)
        now = datetime.now().isoformat()
        user_key = str(user_id)

        # Build dynamic updates
        updates = ["status = ?", "updated_at = ?"]
        params = [status, now]

        if error_message is not None:
            updates.append("error_message = ?")
            params.append(error_message)
        if logs is not None:
            updates.append("logs = ?")
            params.append(logs)
        if optimized_resume_md is not None:
            updates.append("optimized_resume_md = ?")
            params.append(optimized_resume_md)
        if pending_question is not None:
            updates.append("pending_question = ?")
            params.append(pending_question)
        if human_answer is not None:
            updates.append("human_answer = ?")
            params.append(human_answer)
        if execution_plan is not None:
            updates.append("execution_plan = ?")
            params.append(execution_plan)

        params.extend([task_id, user_key])
        sql = f"UPDATE agent_resume_tasks SET {', '.join(updates)} WHERE task_id = ? AND user_id = ?"

        cursor.execute(sql, tuple(params))
        conn.commit()
        conn.close()

    def get_agent_resume_task(self, user_id: Any, task_id: str) -> Optional[dict]:
        conn = self.get_connection()
        cursor = DatabaseCursorWrapper(conn.cursor(), self.is_postgres)
        cursor.execute(
            """
            SELECT task_id, user_id, trace_id, status, resume_id, original_resume_name,
                   jd_text, workspace_path, logs, optimized_resume_md, error_message,
                   created_at, updated_at, pending_question, human_answer, execution_plan,
                   interaction_mode
            FROM agent_resume_tasks
            WHERE task_id = ? AND user_id = ?
            """,
            (task_id, str(user_id)),
        )
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        return {
            "task_id": row[0],
            "user_id": row[1],
            "trace_id": row[2],
            "status": row[3],
            "resume_id": row[4],
            "original_resume_name": row[5],
            "jd_text": row[6],
            "workspace_path": row[7],
            "logs": row[8],
            "optimized_resume_md": row[9],
            "error_message": row[10],
            "created_at": row[11],
            "updated_at": row[12],
            "pending_question": row[13],
            "human_answer": row[14],
            "execution_plan": row[15],
            "interaction_mode": row[16],
        }

    def list_user_agent_resume_tasks(self, user_id: Any) -> list[dict]:
        conn = self.get_connection()
        cursor = DatabaseCursorWrapper(conn.cursor(), self.is_postgres)
        cursor.execute(
            """
            SELECT task_id, user_id, trace_id, status, resume_id, original_resume_name,
                   jd_text, workspace_path, logs, optimized_resume_md, error_message,
                   created_at, updated_at, interaction_mode
            FROM agent_resume_tasks
            WHERE user_id = ?
            ORDER BY created_at DESC
            """,
            (str(user_id),),
        )
        rows = cursor.fetchall()
        conn.close()
        tasks = []
        for row in rows:
            tasks.append({
                "task_id": row[0],
                "user_id": row[1],
                "trace_id": row[2],
                "status": row[3],
                "resume_id": row[4],
                "original_resume_name": row[5],
                "jd_text": row[6],
                "workspace_path": row[7],
                "logs": row[8],
                "optimized_resume_md": row[9],
                "error_message": row[10],
                "created_at": row[11],
                "updated_at": row[12],
                "interaction_mode": row[13],
            })
        return tasks

    def list_recent_agent_resume_task_candidates(
        self,
        user_id: Any,
        *,
        resume_id: Optional[str] = None,
        limit: int = 40,
    ) -> list[dict]:
        conn = self.get_connection()
        cursor = DatabaseCursorWrapper(conn.cursor(), self.is_postgres)
        capped_limit = max(1, min(int(limit or 40), 200))
        params: list[Any] = [str(user_id)]
        resume_clause = ""
        if resume_id:
            resume_clause = "AND resume_id = ?"
            params.append(resume_id)
        params.append(capped_limit)
        cursor.execute(
            f"""
            SELECT task_id, user_id, trace_id, status, resume_id, original_resume_name,
                   jd_text, workspace_path, logs, optimized_resume_md, error_message,
                   created_at, updated_at, pending_question, human_answer, execution_plan,
                   interaction_mode
            FROM agent_resume_tasks
            WHERE user_id = ?
              {resume_clause}
              AND status IN ('PENDING', 'RUNNING', 'WAITING_FOR_HUMAN', 'COMPLETED')
            ORDER BY created_at DESC
            LIMIT ?
            """,
            tuple(params),
        )
        rows = cursor.fetchall()
        conn.close()
        tasks = []
        for row in rows:
            tasks.append({
                "task_id": row[0],
                "user_id": row[1],
                "trace_id": row[2],
                "status": row[3],
                "resume_id": row[4],
                "original_resume_name": row[5],
                "jd_text": row[6],
                "workspace_path": row[7],
                "logs": row[8],
                "optimized_resume_md": row[9],
                "error_message": row[10],
                "created_at": row[11],
                "updated_at": row[12],
                "pending_question": row[13],
                "human_answer": row[14],
                "execution_plan": row[15],
                "interaction_mode": row[16],
            })
        return tasks

    def delete_agent_resume_task(self, user_id: Any, task_id: str) -> bool:
        conn = self.get_connection()
        cursor = DatabaseCursorWrapper(conn.cursor(), self.is_postgres)
        cursor.execute(
            "DELETE FROM agent_resume_tasks WHERE task_id = ? AND user_id = ?",
            (task_id, str(user_id)),
        )
        affected = cursor.rowcount
        conn.commit()
        conn.close()
        return affected > 0

    def add_agent_resume_turn(
        self,
        *,
        task_id: str,
        user_id: Any,
        role: str,
        content: str,
        step_index: Optional[int] = None,
        answer_type: str = "",
        remember: bool = False,
        evidence_scope: str = "",
        summary: str = "",
    ) -> str:
        text = str(content or "").strip()
        if not text:
            raise ValueError("turn content cannot be empty")
        conn = self.get_connection()
        cursor = DatabaseCursorWrapper(conn.cursor(), self.is_postgres)
        cursor.execute(
            """
            INSERT INTO agent_resume_turns (
                task_id, user_id, step_index, role, content,
                answer_type, remember, evidence_scope, summary, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                str(user_id),
                step_index,
                str(role),
                text,
                str(answer_type or ""),
                bool(remember),
                str(evidence_scope or ""),
                str(summary or ""),
                datetime.now().isoformat(),
            ),
        )
        turn_id = str(cursor.lastrowid or "")
        conn.commit()
        conn.close()
        return turn_id

    def list_agent_resume_turns(self, user_id: Any, task_id: str) -> list[dict]:
        conn = self.get_connection()
        cursor = DatabaseCursorWrapper(conn.cursor(), self.is_postgres)
        cursor.execute(
            """
            SELECT id, task_id, user_id, step_index, role, content,
                   answer_type, remember, evidence_scope, consumed_at, created_at, summary
            FROM agent_resume_turns
            WHERE user_id = ? AND task_id = ?
            ORDER BY created_at ASC
            """,
            (str(user_id), task_id),
        )
        rows = cursor.fetchall()
        conn.close()
        return [
            {
                "id": str(row[0]),
                "task_id": row[1],
                "user_id": row[2],
                "step_index": row[3],
                "role": row[4],
                "content": row[5],
                "answer_type": row[6] or "",
                "remember": bool(row[7]),
                "evidence_scope": row[8] or "",
                "consumed_at": row[9],
                "created_at": row[10],
                "summary": row[11] or "",
            }
            for row in rows
        ]

    def list_unconsumed_agent_answer_turns(self, user_id: Any, task_id: str, step_index: int) -> list[dict]:
        conn = self.get_connection()
        cursor = DatabaseCursorWrapper(conn.cursor(), self.is_postgres)
        cursor.execute(
            """
            SELECT id, task_id, user_id, step_index, role, content,
                   answer_type, remember, evidence_scope, consumed_at, created_at, summary
            FROM agent_resume_turns
            WHERE user_id = ?
              AND task_id = ?
              AND step_index = ?
              AND role = 'user'
              AND consumed_at IS NULL
            ORDER BY created_at ASC
            """,
            (str(user_id), task_id, int(step_index)),
        )
        rows = cursor.fetchall()
        conn.close()
        return [
            {
                "id": str(row[0]),
                "task_id": row[1],
                "user_id": row[2],
                "step_index": row[3],
                "role": row[4],
                "content": row[5],
                "answer_type": row[6] or "",
                "remember": bool(row[7]),
                "evidence_scope": row[8] or "",
                "consumed_at": row[9],
                "created_at": row[10],
                "summary": row[11] or "",
            }
            for row in rows
        ]

    def mark_agent_resume_turns_consumed(self, turn_ids: list[str]) -> None:
        clean_ids = [str(item) for item in turn_ids if str(item or "").strip()]
        if not clean_ids:
            return
        conn = self.get_connection()
        cursor = DatabaseCursorWrapper(conn.cursor(), self.is_postgres)
        cursor.execute(
            "UPDATE agent_resume_turns SET consumed_at = ? WHERE id = ANY(?::uuid[])",
            (datetime.now().isoformat(), clean_ids),
        )
        conn.commit()
        conn.close()

    def get_agent_resume_conversation_state(self, user_id: Any, task_id: str) -> dict[str, Any]:
        conn = self.get_connection()
        cursor = DatabaseCursorWrapper(conn.cursor(), self.is_postgres)
        cursor.execute(
            """
            SELECT task_id, user_id, summary, global_preferences, fact_ledger, updated_at
            FROM agent_resume_conversation_state
            WHERE user_id = ? AND task_id = ?
            """,
            (str(user_id), task_id),
        )
        row = cursor.fetchone()
        conn.close()
        if not row:
            return {
                "task_id": task_id,
                "user_id": str(user_id),
                "summary": "",
                "global_preferences": [],
                "fact_ledger": [],
                "updated_at": "",
            }
        return {
            "task_id": row[0],
            "user_id": row[1],
            "summary": row[2] or "",
            "global_preferences": safe_json_load(row[3], []),
            "fact_ledger": safe_json_load(row[4], []),
            "updated_at": row[5],
        }

    def upsert_agent_resume_conversation_state(
        self,
        *,
        task_id: str,
        user_id: Any,
        summary: str = "",
        global_preferences: Optional[list[str]] = None,
        fact_ledger: Optional[list[str]] = None,
    ) -> None:
        now = datetime.now().isoformat()
        conn = self.get_connection()
        cursor = DatabaseCursorWrapper(conn.cursor(), self.is_postgres)
        cursor.execute(
            """
            INSERT INTO agent_resume_conversation_state (
                task_id, user_id, summary, global_preferences, fact_ledger, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (task_id) DO UPDATE SET
                user_id = EXCLUDED.user_id,
                summary = EXCLUDED.summary,
                global_preferences = EXCLUDED.global_preferences,
                fact_ledger = EXCLUDED.fact_ledger,
                updated_at = EXCLUDED.updated_at
            """,
            (
                task_id,
                str(user_id),
                str(summary or ""),
                json.dumps(global_preferences or [], ensure_ascii=False),
                json.dumps(fact_ledger or [], ensure_ascii=False),
                now,
            ),
        )
        conn.commit()
        conn.close()

    def save_agent_preference(
        self,
        user_id: Any,
        section_name: str,
        preference_text: str,
        source_task_id: Optional[str] = None,
        evidence_text: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> None:
        text = str(preference_text or "").strip()
        if not text:
            return

        conn = self.get_connection()
        cursor = DatabaseCursorWrapper(conn.cursor(), self.is_postgres)
        cursor.execute(
            """
            INSERT INTO agent_preferences (
                user_id, section_name, preference_text, source_task_id, evidence_text, tags
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (user_id, section_name, preference_text) DO NOTHING
            """,
            (
                str(user_id),
                str(section_name),
                text,
                source_task_id,
                evidence_text,
                json.dumps(tags or [], ensure_ascii=False),
            ),
        )
        conn.commit()
        conn.close()

    def get_agent_preferences(self, user_id: Any, section_name: str, limit: int = 30) -> list[str]:
        section_aliases = [str(section_name)]
        try:
            from backend.resume_rag import SECTION_ALIASES
            normalized = str(section_name).strip().lower()
            for canonical, aliases in SECTION_ALIASES.items():
                values = [canonical, *(aliases or [])]
                if normalized in {str(value).strip().lower() for value in values}:
                    section_aliases = list(dict.fromkeys([str(value) for value in values]))
                    break
        except Exception:
            pass

        conn = self.get_connection()
        cursor = DatabaseCursorWrapper(conn.cursor(), self.is_postgres)
        cursor.execute(
            """
            SELECT preference_text
            FROM agent_preferences
            WHERE user_id = ? AND section_name = ANY(?::text[])
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (str(user_id), section_aliases, int(limit)),
        )
        rows = cursor.fetchall()
        conn.close()
        return [str(row[0]) for row in reversed(rows)]

    def list_agent_preference_records(self, user_id: Any, limit: int = 100) -> list[dict[str, Any]]:
        conn = self.get_connection()
        cursor = DatabaseCursorWrapper(conn.cursor(), self.is_postgres)
        cursor.execute(
            """
            SELECT id, section_name, preference_text, source_task_id, created_at
            FROM agent_preferences
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (str(user_id), max(1, min(int(limit), 100))),
        )
        rows = cursor.fetchall()
        conn.close()
        return [
            {
                "id": str(row[0]),
                "sectionName": str(row[1]),
                "text": str(row[2]),
                "sourceTaskId": str(row[3] or ""),
                "createdAt": row[4],
            }
            for row in rows
        ]

    def delete_agent_preference(self, user_id: Any, preference_id: str) -> bool:
        conn = self.get_connection()
        cursor = DatabaseCursorWrapper(conn.cursor(), self.is_postgres)
        cursor.execute(
            "DELETE FROM agent_preferences WHERE id = ? AND user_id = ? RETURNING id",
            (preference_id, str(user_id)),
        )
        deleted = cursor.fetchone() is not None
        conn.commit()
        conn.close()
        return deleted

    def save_analysis_report(
        self,
        *,
        user_id: int,
        task_id: str,
        jd_text: str,
        resume_text: str = "",
        knowledge_texts: Optional[List[str]] = None,
        original_analysis: Optional[Any] = None,
        final_report: Optional[dict] = None,
        evidence_summary: Optional[dict] = None,
        hallucination_control: Optional[dict] = None,
        citations: Optional[List[dict]] = None,
        credibility_score: Optional[float] = None,
        evidence_coverage: Optional[float] = None,
        hallucination_risk: str = "",
    ) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        original_payload = self._jsonable(original_analysis or {})
        evidence_payload = evidence_summary or {}
        coverage = evidence_coverage
        if coverage is None and isinstance(evidence_payload, dict):
            raw = evidence_payload.get("evidenceCoverage")
            coverage = float(raw) if raw is not None else None
        hallucination_payload = hallucination_control or {}
        risk = hallucination_risk or str(hallucination_payload.get("riskLevel", "") or "")
        cursor.execute(
            """
            INSERT INTO analysis_report (
                user_id, task_id, jd_text, resume_text, knowledge_texts, original_analysis_json,
                final_report_json, evidence_summary_json, hallucination_control_json, citations_json,
                credibility_score, evidence_coverage, hallucination_risk, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                task_id,
                jd_text,
                resume_text,
                self._dump_json(knowledge_texts or []),
                self._dump_json(original_payload),
                self._dump_json(final_report or {}),
                self._dump_json(evidence_payload),
                self._dump_json(hallucination_payload),
                self._dump_json(citations or []),
                credibility_score,
                coverage,
                risk,
                now,
                now,
            ),
        )
        row_id = int(cursor.lastrowid)
        conn.commit()
        conn.close()
        return row_id

    def save_claim_check_results(
        self,
        user_id: int,
        task_id: str,
        verification_results: List[dict],
    ) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM claim_check_result WHERE task_id = ? AND user_id = ?", (task_id, user_id))
        now = datetime.now().isoformat()
        for item in verification_results or []:
            evidence = item.get("evidenceChunks") or item.get("evidence") or []
            status = str(item.get("status") or item.get("checkStatus") or "").lower()
            cursor.execute(
                """
                INSERT INTO claim_check_result (
                    user_id, task_id, claim_id, claim_text, claim_type, check_status,
                    confidence_score, evidence_count, reason, evidence_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    task_id,
                    str(item.get("claimId") or item.get("claim_id") or ""),
                    str(item.get("claimText") or item.get("claim") or ""),
                    str(item.get("claimType") or item.get("claim_type") or "GENERAL"),
                    status,
                    float(item.get("confidenceScore") or item.get("confidence") or 0.0),
                    len(evidence) if isinstance(evidence, list) else 0,
                    str(item.get("reason") or ""),
                    self._dump_json(evidence if isinstance(evidence, list) else []),
                    now,
                ),
            )
        conn.commit()
        conn.close()

    def get_analysis_report(
        self,
        user_id: int,
        *,
        task_id: Optional[str] = None,
        report_id: Optional[int] = None,
    ) -> Optional[dict]:
        if task_id is None and report_id is None:
            raise ValueError("task_id_or_report_id_required")
        conn = self.get_connection()
        cursor = conn.cursor()
        if report_id is not None:
            cursor.execute(
                """
                SELECT id, user_id, task_id, jd_text, resume_text, knowledge_texts,
                       original_analysis_json, final_report_json, evidence_summary_json,
                       hallucination_control_json, citations_json, credibility_score,
                       evidence_coverage, hallucination_risk, created_at, updated_at
                FROM analysis_report WHERE id = ? AND user_id = ?
                """,
                (report_id, user_id),
            )
        else:
            cursor.execute(
                """
                SELECT id, user_id, task_id, jd_text, resume_text, knowledge_texts,
                       original_analysis_json, final_report_json, evidence_summary_json,
                       hallucination_control_json, citations_json, credibility_score,
                       evidence_coverage, hallucination_risk, created_at, updated_at
                FROM analysis_report WHERE task_id = ? AND user_id = ?
                ORDER BY created_at DESC, id DESC LIMIT 1
                """,
                (task_id, user_id),
            )
        row = cursor.fetchone()
        conn.close()
        return self._build_analysis_report_dict(row) if row else None

    def list_analysis_reports(self, user_id: int, limit: int = 20) -> List[dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, user_id, task_id, jd_text, resume_text, knowledge_texts,
                   original_analysis_json, final_report_json, evidence_summary_json,
                   hallucination_control_json, citations_json, credibility_score,
                   evidence_coverage, hallucination_risk, created_at, updated_at
            FROM analysis_report
            WHERE user_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        rows = cursor.fetchall()
        conn.close()
        return [self._build_analysis_report_dict(row) for row in rows]

    def get_claim_check_results(self, user_id: int, task_id: str) -> List[dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, user_id, task_id, claim_id, claim_text, claim_type, check_status,
                   confidence_score, evidence_count, reason, evidence_json, created_at
            FROM claim_check_result
            WHERE task_id = ? AND user_id = ?
            ORDER BY id ASC
            """,
            (task_id, user_id),
        )
        rows = cursor.fetchall()
        conn.close()
        return [
            {
                "id": row[0],
                "user_id": row[1],
                "task_id": row[2],
                "claim_id": row[3] or "",
                "claim_text": row[4] or "",
                "claim_type": row[5] or "GENERAL",
                "check_status": row[6] or "",
                "confidence_score": float(row[7] or 0.0),
                "evidence_count": int(row[8] or 0),
                "reason": row[9] or "",
                "evidence": self._load_json(row[10], []),
                "created_at": row[11],
            }
            for row in rows
        ]

    def save_workflow_logs(
        self,
        user_id: int,
        task_id: str,
        workflow_logs: List[dict],
    ) -> None:
        self._ensure_numeric_user_id(user_id)
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM analysis_workflow_log WHERE task_id = ? AND user_id = ?", (task_id, user_id))
        now = datetime.now().isoformat()
        for item in workflow_logs or []:
            cursor.execute(
                """
                INSERT INTO analysis_workflow_log (
                    user_id, task_id, node_name, status, duration_ms, input_summary,
                    output_summary, error_message, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    task_id,
                    str(item.get("nodeName") or item.get("node_name") or ""),
                    str(item.get("status") or ""),
                    int(item.get("durationMs") or item.get("duration_ms") or 0),
                    str(item.get("inputSummary") or item.get("input_summary") or ""),
                    str(item.get("outputSummary") or item.get("output_summary") or ""),
                    str(item.get("error") or item.get("error_message") or ""),
                    now,
                ),
            )
        conn.commit()
        conn.close()

    def get_workflow_logs(self, user_id: int, task_id: str) -> List[dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, user_id, task_id, node_name, status, duration_ms,
                   input_summary, output_summary, error_message, created_at
            FROM analysis_workflow_log
            WHERE task_id = ? AND user_id = ?
            ORDER BY id ASC
            """,
            (task_id, user_id),
        )
        rows = cursor.fetchall()
        conn.close()
        return [
            {
                "id": row[0],
                "user_id": row[1],
                "task_id": row[2],
                "nodeName": row[3] or "",
                "status": row[4] or "",
                "durationMs": int(row[5] or 0),
                "inputSummary": row[6] or "",
                "outputSummary": row[7] or "",
                "error": row[8] or None,
                "created_at": row[9],
            }
            for row in rows
        ]

    def save_quality_evaluation(
        self,
        user_id: int,
        task_id: str,
        quality_evaluation: dict,
    ) -> None:
        self._ensure_numeric_user_id(user_id)
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM analysis_quality_evaluation WHERE task_id = ? AND user_id = ?", (task_id, user_id))
        scores = quality_evaluation.get("scores") if isinstance(quality_evaluation.get("scores"), dict) else {}
        cursor.execute(
            """
            INSERT INTO analysis_quality_evaluation (
                user_id, task_id, final_quality_score, quality_grade, quality_gate_status,
                evidence_coverage_score, hallucination_risk_score, citation_completeness_score,
                resume_honesty_score, match_score_reasonableness, issues_json, summary, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                task_id,
                float(quality_evaluation.get("finalQualityScore") or 0),
                str(quality_evaluation.get("qualityGrade") or ""),
                str(quality_evaluation.get("qualityGateStatus") or ""),
                float(scores.get("evidenceCoverageScore") or 0),
                float(scores.get("hallucinationRiskScore") or 0),
                float(scores.get("citationCompletenessScore") or 0),
                float(scores.get("resumeHonestyScore") or 0),
                float(scores.get("matchScoreReasonableness") or 0),
                self._dump_json(quality_evaluation.get("issues") or []),
                str(quality_evaluation.get("summary") or ""),
                datetime.now().isoformat(),
            ),
        )
        conn.commit()
        conn.close()

    def get_quality_evaluation(self, user_id: int, task_id: str) -> Optional[dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, user_id, task_id, final_quality_score, quality_grade, quality_gate_status,
                   evidence_coverage_score, hallucination_risk_score, citation_completeness_score,
                   resume_honesty_score, match_score_reasonableness, issues_json, summary, created_at
            FROM analysis_quality_evaluation
            WHERE task_id = ? AND user_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (task_id, user_id),
        )
        row = cursor.fetchone()
        conn.close()
        return self._build_quality_evaluation_dict(row) if row else None

    def list_low_quality_reports(self, user_id: int, limit: int = 20) -> List[dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT q.id, q.user_id, q.task_id, q.final_quality_score, q.quality_grade,
                   q.quality_gate_status, q.evidence_coverage_score, q.hallucination_risk_score,
                   q.citation_completeness_score, q.resume_honesty_score,
                   q.match_score_reasonableness, q.issues_json, q.summary, q.created_at,
                   r.id, r.jd_text
            FROM analysis_quality_evaluation q
            LEFT JOIN analysis_report r ON r.task_id = q.task_id
            WHERE q.user_id = ?
              AND (q.quality_gate_status != 'PASSED' OR q.final_quality_score < 70)
            ORDER BY q.created_at DESC, q.id DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        rows = cursor.fetchall()
        conn.close()
        out = []
        for row in rows:
            item = self._build_quality_evaluation_dict(row[:14])
            item["report_id"] = row[14]
            item["jd_text"] = row[15] or ""
            out.append(item)
        return out

    def create_knowledge_document(
        self,
        *,
        user_id: int,
        title: str,
        file_name: str,
        file_type: str,
        source_type: str,
        raw_text: str,
        summary: str = "",
        status: str = "PENDING",
        error_message: str = "",
    ) -> int:
        self._ensure_numeric_user_id(user_id)
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute(
            """
            INSERT INTO knowledge_document (
                user_id, title, file_name, file_type, source_type, raw_text, summary,
                chunk_count, status, error_message, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                title,
                file_name,
                file_type,
                source_type,
                raw_text,
                summary,
                0,
                status,
                error_message,
                now,
                now,
            ),
        )
        row_id = int(cursor.lastrowid)
        conn.commit()
        conn.close()
        return row_id

    def update_knowledge_document_status(
        self,
        user_id: int,
        document_id: int,
        status: str,
        error_message: Optional[str] = None,
        chunk_count: Optional[int] = None,
    ) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE knowledge_document
            SET status = ?,
                error_message = COALESCE(?, error_message),
                chunk_count = COALESCE(?, chunk_count),
                updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (status, error_message, chunk_count, datetime.now().isoformat(), document_id, user_id),
        )
        conn.commit()
        conn.close()

    def save_knowledge_chunks(
        self,
        user_id: int,
        document_id: int,
        chunks: List[dict],
    ) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM knowledge_chunk WHERE document_id = ? AND user_id = ?", (document_id, user_id))
        now = datetime.now().isoformat()
        for index, chunk in enumerate(chunks):
            metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
            text = str(chunk.get("text") or chunk.get("chunk_text") or "")
            chunk_index = int(chunk.get("chunkIndex", chunk.get("chunk_index", index)))
            token_count = int(chunk.get("tokenCount", chunk.get("token_count", len(text))))

            section_id = chunk.get("sectionId") or metadata.get("sectionId")
            section_type = chunk.get("sectionType") or metadata.get("sectionType") or "generic_section"
            section_title = chunk.get("sectionTitle") or metadata.get("sectionTitle") or "Document Content"

            hierarchy = chunk.get("hierarchy") or metadata.get("hierarchy") or [section_title]
            hierarchy_json = self._dump_json(hierarchy)

            semantic_type = chunk.get("semanticType") or metadata.get("semanticType") or "general"
            importance = float(chunk.get("importance", metadata.get("importance", 0.60)))

            keywords = chunk.get("keywords") or metadata.get("keywords") or []
            keywords_json = self._dump_json(keywords)

            embedding_text = chunk.get("embeddingText") or chunk.get("embedding_text") or text
            embedding = chunk.get("embedding") or metadata.get("embedding")
            embedding_value = None
            if isinstance(embedding, list) and embedding:
                embedding_value = "[" + ",".join(str(float(x)) for x in embedding) + "]"

            cursor.execute(
                """
                INSERT INTO knowledge_chunk (
                    user_id, document_id, chunk_index, chunk_text, token_count, metadata_json, created_at,
                    section_id, section_type, section_title, hierarchy_json, semantic_type, importance,
                    keywords_json, embedding_text, embedding
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    document_id,
                    chunk_index,
                    text,
                    token_count,
                    self._dump_json(metadata),
                    now,
                    section_id,
                    section_type,
                    section_title,
                    hierarchy_json,
                    semantic_type,
                    importance,
                    keywords_json,
                    embedding_text,
                    embedding_value,
                ),
            )
        conn.commit()
        conn.close()

    def list_knowledge_documents(
        self,
        user_id: int,
        source_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        if source_type:
            cursor.execute(
                """
                SELECT id, user_id, title, file_name, file_type, source_type, raw_text, summary,
                       chunk_count, status, error_message, created_at, updated_at
                FROM knowledge_document
                WHERE user_id = ? AND source_type = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (user_id, source_type, limit),
            )
        else:
            cursor.execute(
                """
                SELECT id, user_id, title, file_name, file_type, source_type, raw_text, summary,
                       chunk_count, status, error_message, created_at, updated_at
                FROM knowledge_document
                WHERE user_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (user_id, limit),
            )
        rows = cursor.fetchall()
        conn.close()
        return [self._build_knowledge_document_dict(row) for row in rows]

    def get_knowledge_document(
        self,
        user_id: int,
        document_id: int,
    ) -> Optional[dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, user_id, title, file_name, file_type, source_type, raw_text, summary,
                   chunk_count, status, error_message, created_at, updated_at
            FROM knowledge_document
            WHERE id = ? AND user_id = ?
            """,
            (document_id, user_id),
        )
        row = cursor.fetchone()
        conn.close()
        return self._build_knowledge_document_dict(row) if row else None

    def get_knowledge_chunks(
        self,
        user_id: int,
        document_ids: List[int],
    ) -> List[dict]:
        if not document_ids:
            return []
        placeholders = ",".join("?" for _ in document_ids)
        params: list[Any] = [int(doc_id) for doc_id in document_ids]
        params.append(user_id)
        conn = self.get_connection()
        cursor = conn.cursor()

        available_cols = self._table_columns(cursor, "knowledge_chunk")

        extra_selects = ""
        if "section_id" in available_cols:
            extra_selects = (
                ", c.section_id, c.section_type, c.section_title, c.hierarchy_json, "
                "c.semantic_type, c.importance, c.keywords_json, c.embedding_text"
            )
            if "embedding" in available_cols:
                extra_selects += ", c.embedding"

        cursor.execute(
            f"""
            SELECT c.id, c.user_id, c.document_id, c.chunk_index, c.chunk_text, c.token_count,
                   c.metadata_json, c.created_at, d.title, d.file_name, d.source_type {extra_selects}
            FROM knowledge_chunk c
            JOIN knowledge_document d ON d.id = c.document_id
            WHERE c.document_id IN ({placeholders}) AND c.user_id = ?
            ORDER BY c.document_id ASC, c.chunk_index ASC
            """,
            params,
        )
        rows = cursor.fetchall()
        conn.close()

        results = []
        for row in rows:
            chunk_dict = {
                "id": row[0],
                "user_id": row[1],
                "document_id": row[2],
                "chunk_index": row[3],
                "chunk_text": row[4] or "",
                "token_count": int(row[5] or 0),
                "metadata": self._load_json(row[6], {}),
                "created_at": row[7],
                "title": row[8] or "",
                "file_name": row[9] or "",
                "source_type": row[10] or "other",
            }

            # Populate backward-compatible defaults or read from query
            if extra_selects:
                chunk_dict["sectionId"] = row[11]
                chunk_dict["sectionType"] = row[12] or "generic_section"
                chunk_dict["sectionTitle"] = row[13] or "Document Content"
                chunk_dict["hierarchy"] = self._load_json(row[14], [chunk_dict["sectionTitle"]])
                chunk_dict["semanticType"] = row[15] or "general"
                chunk_dict["importance"] = float(row[16] or 0.60)
                chunk_dict["keywords"] = self._load_json(row[17], [])
                chunk_dict["embeddingText"] = row[18] or chunk_dict["chunk_text"]
                if "embedding" in available_cols and len(row) > 19 and row[19] is not None:
                    chunk_dict["embedding"] = self._parse_embedding_value(row[19])
            else:
                chunk_dict["sectionId"] = f"sec-{chunk_dict['source_type']}-pre"
                chunk_dict["sectionType"] = "generic_section"
                chunk_dict["sectionTitle"] = "Document Content"
                chunk_dict["hierarchy"] = ["Document Content"]
                chunk_dict["semanticType"] = "general"
                chunk_dict["importance"] = 0.60;
                chunk_dict["keywords"] = []
                chunk_dict["embeddingText"] = chunk_dict["chunk_text"]

            results.append(chunk_dict)

        return results

    def delete_knowledge_document(
        self,
        user_id: int,
        document_id: int,
    ) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM knowledge_chunk WHERE document_id = ? AND user_id = ?",
            (document_id, user_id),
        )
        cursor.execute(
            "DELETE FROM knowledge_document WHERE id = ? AND user_id = ?",
            (document_id, user_id),
        )
        deleted = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return deleted

    def _build_knowledge_document_dict(self, row) -> dict:
        return {
            "id": row[0],
            "user_id": row[1],
            "title": row[2] or "",
            "file_name": row[3] or "",
            "file_type": row[4] or "",
            "source_type": row[5] or "other",
            "raw_text": row[6] or "",
            "summary": row[7] or "",
            "chunk_count": int(row[8] or 0),
            "status": row[9] or "",
            "error_message": row[10] or "",
            "created_at": row[11],
            "updated_at": row[12],
        }

    def _build_analysis_report_dict(self, row) -> dict:
        return {
            "id": row[0],
            "user_id": row[1],
            "task_id": row[2],
            "jd_text": row[3] or "",
            "resume_text": row[4] or "",
            "knowledge_texts": self._load_json(row[5], []),
            "original_analysis": self._load_json(row[6], {}),
            "final_report": self._load_json(row[7], {}),
            "evidence_summary": self._load_json(row[8], {}),
            "hallucination_control": self._load_json(row[9], {}),
            "citations": self._load_json(row[10], []),
            "credibility_score": row[11],
            "evidence_coverage": row[12],
            "hallucination_risk": row[13] or "",
            "created_at": row[14],
            "updated_at": row[15],
        }

    def _build_quality_evaluation_dict(self, row) -> dict:
        return {
            "id": row[0],
            "user_id": row[1],
            "task_id": row[2],
            "finalQualityScore": float(row[3] or 0),
            "qualityGrade": row[4] or "",
            "qualityGateStatus": row[5] or "",
            "scores": {
                "evidenceCoverageScore": float(row[6] or 0),
                "hallucinationRiskScore": float(row[7] or 0),
                "citationCompletenessScore": float(row[8] or 0),
                "resumeHonestyScore": float(row[9] or 0),
                "matchScoreReasonableness": float(row[10] or 0),
            },
            "issues": self._load_json(row[11], []),
            "summary": row[12] or "",
            "created_at": row[13],
        }

    def _dump_json(self, value: Any) -> str:
        return json.dumps(self._jsonable(value), ensure_ascii=False)

    def _load_json(self, value: Any, default: Any) -> Any:
        return safe_json_load(value, default)

    def _parse_embedding_value(self, value: Any) -> List[float]:
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            return [float(item) for item in value]
        text = str(value).strip()
        if not text:
            return []
        if text.startswith("[") and text.endswith("]"):
            text = text[1:-1]
        return [float(item) for item in text.split(",") if item.strip()]

    def _jsonable(self, value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if isinstance(value, datetime):
            return value.isoformat()
        return value

    def insert_job_posting(self, posting: JobPosting) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO job_postings (
                user_id, title, company, region, latitude, longitude, transit_minutes,
                salary_monthly_k, jd_record_id, source_url, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                posting.user_id,
                posting.title,
                posting.company,
                posting.region,
                posting.latitude,
                posting.longitude,
                posting.transit_minutes,
                posting.salary_monthly_k,
                posting.jd_record_id,
                posting.source_url,
                datetime.now().isoformat(),
            ),
        )
        job_id = int(cursor.lastrowid)
        conn.commit()
        conn.close()
        return job_id

    def update_job_posting_salary(self, user_id: int, job_posting_id: int, salary_monthly_k: float) -> None:
        if not self.job_posting_belongs_to_user(user_id, job_posting_id):
            raise ValueError("unauthorized_or_not_found")
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE job_postings SET salary_monthly_k = ? WHERE id = ? AND user_id = ?",
            (salary_monthly_k, job_posting_id, user_id),
        )
        conn.commit()
        conn.close()

    def list_job_postings(self, user_id: int, limit: int = 200) -> List[JobPosting]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, user_id, title, company, region, latitude, longitude, transit_minutes,
                   salary_monthly_k, jd_record_id, source_url, created_at
            FROM job_postings
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        rows = cursor.fetchall()
        conn.close()
        out: List[JobPosting] = []
        for row in rows:
            out.append(
                JobPosting(
                    id=row[0],
                    user_id=row[1],
                    title=row[2],
                    company=row[3] or "",
                    region=row[4] or "",
                    latitude=row[5],
                    longitude=row[6],
                    transit_minutes=row[7],
                    salary_monthly_k=float(row[8]),
                    jd_record_id=row[9],
                    source_url=row[10] or "",
                    created_at=safe_datetime(row[11]),
                )
            )
        return out

    def add_salary_snapshot(
        self,
        user_id: int,
        job_posting_id: int,
        salary_monthly_k: float,
        *,
        note: str = "",
        observed_at: Optional[datetime] = None,
    ) -> int:
        if not self.job_posting_belongs_to_user(user_id, job_posting_id):
            raise ValueError("unauthorized_or_not_found")
        conn = self.get_connection()
        cursor = conn.cursor()
        ts = (observed_at or datetime.now()).isoformat()
        cursor.execute(
            """
            INSERT INTO salary_snapshots (job_posting_id, observed_at, salary_monthly_k, note)
            VALUES (?, ?, ?, ?)
            """,
            (job_posting_id, ts, salary_monthly_k, note),
        )
        snap_id = int(cursor.lastrowid)
        conn.commit()
        conn.close()
        return snap_id

    def job_posting_belongs_to_user(self, user_id: int, job_posting_id: int) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM job_postings WHERE id = ? AND user_id = ?",
            (job_posting_id, user_id),
        )
        ok = cursor.fetchone() is not None
        conn.close()
        return ok

    def get_salary_snapshots(self, user_id: int, job_posting_id: int) -> List[SalarySnapshot]:
        if not self.job_posting_belongs_to_user(user_id, job_posting_id):
            return []
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, job_posting_id, observed_at, salary_monthly_k, note
            FROM salary_snapshots
            WHERE job_posting_id = ?
            ORDER BY observed_at ASC, id ASC
            """,
            (job_posting_id,),
        )
        rows = cursor.fetchall()
        conn.close()
        return [
            SalarySnapshot(
                id=row[0],
                job_posting_id=row[1],
                observed_at=safe_datetime(row[2]),
                salary_monthly_k=float(row[3]),
                note=row[4] or "",
            )
            for row in rows
        ]

    def save_fit_exam_attempt(self, attempt: FitExamAttempt) -> int:
        paper_payload = {
            "questions": [
                {
                    "stem": q.stem,
                    "options": q.options,
                    "correct_index": q.correct_index,
                    "category": getattr(q, "category", "") or "",
                }
                for q in attempt.paper.questions
            ]
        }
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO fit_exam_attempts (
                user_id, jd_record_id, major_profile, paper_json, answers_json, score, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt.user_id,
                attempt.jd_record_id,
                attempt.major_profile,
                json.dumps(paper_payload, ensure_ascii=False),
                json.dumps(attempt.answers, ensure_ascii=False),
                attempt.score,
                datetime.now().isoformat(),
            ),
        )
        row_id = int(cursor.lastrowid)
        conn.commit()
        conn.close()
        return row_id

    def get_latest_fit_score_by_jd(self, user_id: int) -> dict[int, Tuple[float, datetime]]:
        """Return latest fit-exam score by JD id."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT jd_record_id, score, created_at
            FROM fit_exam_attempts
            WHERE jd_record_id IS NOT NULL AND user_id = ?
            ORDER BY created_at DESC
            """,
            (user_id,),
        )
        rows = cursor.fetchall()
        conn.close()
        best: dict[int, Tuple[float, datetime]] = {}
        for jd_id, score, created_at in rows:
            if jd_id is None:
                continue
            if jd_id in best:
                continue
            best[int(jd_id)] = (float(score), safe_datetime(created_at))
        return best

    def get_fit_exam_attempts(self, user_id: int, limit: int = 30) -> List[FitExamAttempt]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, user_id, jd_record_id, major_profile, paper_json, answers_json, score, created_at
            FROM fit_exam_attempts
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        rows = cursor.fetchall()
        conn.close()
        attempts: List[FitExamAttempt] = []
        for row in rows:
            raw = safe_json_load(row[4], {})
            questions = [
                FitExamQuestion(
                    stem=item["stem"],
                    options=item["options"],
                    correct_index=int(item["correct_index"]),
                    category=str(item.get("category", "") or ""),
                )
                for item in raw.get("questions", [])
            ]
            attempts.append(
                FitExamAttempt(
                    id=row[0],
                    user_id=row[1],
                    jd_record_id=row[2],
                    major_profile=row[3] or "",
                    paper=FitExamPaper(questions=questions),
                    answers=list(safe_json_load(row[5], [])),
                    score=float(row[6]),
                    created_at=safe_datetime(row[7]),
                )
            )
        return attempts

    # API key encryption helpers
    def encrypt_api_key(self, api_key: str) -> str:
        if not api_key:
            return ""
        key = os.getenv("MODEL_SECRET_ENCRYPTION_KEY")
        if not key:
            import base64
            xor_key = b"fallback-secret-key-internpath-dashboard"
            xored = bytes(c ^ xor_key[i % len(xor_key)] for i, c in enumerate(api_key.encode('utf-8')))
            return base64.b64encode(xored).decode('utf-8')
        try:
            from cryptography.fernet import Fernet
            import hashlib
            import base64
            key_bytes = key.encode('utf-8')
            hashed_key = base64.urlsafe_b64encode(hashlib.sha256(key_bytes).digest())
            f = Fernet(hashed_key)
            return f.encrypt(api_key.encode('utf-8')).decode('utf-8')
        except Exception:
            import base64
            xor_key = b"fallback-secret-key-internpath-dashboard"
            xored = bytes(c ^ xor_key[i % len(xor_key)] for i, c in enumerate(api_key.encode('utf-8')))
            return base64.b64encode(xored).decode('utf-8')

    def decrypt_api_key(self, encrypted_key: str) -> str:
        if not encrypted_key:
            return ""
        key = os.getenv("MODEL_SECRET_ENCRYPTION_KEY")
        if not key:
            import base64
            try:
                decoded = base64.b64decode(encrypted_key.encode('utf-8'))
                xor_key = b"fallback-secret-key-internpath-dashboard"
                xored = bytes(c ^ xor_key[i % len(xor_key)] for i, c in enumerate(decoded))
                return xored.decode('utf-8')
            except Exception:
                return encrypted_key
        try:
            from cryptography.fernet import Fernet
            import hashlib
            import base64
            key_bytes = key.encode('utf-8')
            hashed_key = base64.urlsafe_b64encode(hashlib.sha256(key_bytes).digest())
            f = Fernet(hashed_key)
            return f.decrypt(encrypted_key.encode('utf-8')).decode('utf-8')
        except Exception:
            import base64
            try:
                decoded = base64.b64decode(encrypted_key.encode('utf-8'))
                xor_key = b"fallback-secret-key-internpath-dashboard"
                xored = bytes(c ^ xor_key[i % len(xor_key)] for i, c in enumerate(decoded))
                return xored.decode('utf-8')
            except Exception:
                return encrypted_key

    # DRAFTS CRUD methods
    def save_draft(self, user_id: Any, input_json: dict, status: str = "DRAFT", failed_step: Optional[str] = None, error_message: Optional[str] = None, draft_id: Optional[str] = None) -> Any:
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()

        from uuid import uuid4
        new_id = draft_id or str(uuid4())

        if draft_id:
            if self.is_postgres:
                cursor.execute("SELECT 1 FROM drafts WHERE id = %s AND user_id = %s", (draft_id, user_id))
            else:
                cursor.execute("SELECT 1 FROM drafts WHERE id = ? AND user_id = ?", (draft_id, user_id))
            exists = cursor.fetchone() is not None
        else:
            exists = False

        if exists:
            if self.is_postgres:
                cursor.execute(
                    """
                    UPDATE drafts
                    SET status = %s, input_json = %s, failed_step = %s, error_message = %s, updated_at = %s
                    WHERE id = %s AND user_id = %s
                    """,
                    (status, json.dumps(input_json, ensure_ascii=False), failed_step, error_message, now, draft_id, user_id)
                )
            else:
                cursor.execute(
                    """
                    UPDATE drafts
                    SET status = ?, input_json = ?, failed_step = ?, error_message = ?, updated_at = ?
                    WHERE id = ? AND user_id = ?
                    """,
                    (status, json.dumps(input_json, ensure_ascii=False), failed_step, error_message, now, draft_id, user_id)
                )
            ret_id = draft_id
        else:
            if self.is_postgres:
                cursor.execute(
                    """
                    INSERT INTO drafts (user_id, status, input_json, failed_step, error_message, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (user_id, status, json.dumps(input_json, ensure_ascii=False), failed_step, error_message, now, now)
                )
                ret_id = cursor.lastrowid or new_id
            else:
                cursor.execute(
                    """
                    INSERT INTO drafts (id, user_id, status, input_json, failed_step, error_message, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (new_id, user_id, status, json.dumps(input_json, ensure_ascii=False), failed_step, error_message, now, now)
                )
                ret_id = new_id

        conn.commit()
        conn.close()
        return ret_id

    def get_draft(self, user_id: Any, draft_id: Any) -> Optional[dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        if self.is_postgres:
            cursor.execute("SELECT id, user_id, status, input_json, failed_step, error_message, created_at, updated_at FROM drafts WHERE id = %s AND user_id = %s", (draft_id, user_id))
        else:
            cursor.execute("SELECT id, user_id, status, input_json, failed_step, error_message, created_at, updated_at FROM drafts WHERE id = ? AND user_id = ?", (draft_id, user_id))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        return {
            "id": row[0],
            "user_id": row[1],
            "status": row[2],
            "input_json": safe_json_load(row[3], {}),
            "failed_step": row[4],
            "error_message": row[5],
            "created_at": row[6],
            "updated_at": row[7]
        }

    def list_drafts(self, user_id: Any) -> List[dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        if self.is_postgres:
            cursor.execute("SELECT id, user_id, status, input_json, failed_step, error_message, created_at, updated_at FROM drafts WHERE user_id = %s ORDER BY updated_at DESC", (user_id,))
        else:
            cursor.execute("SELECT id, user_id, status, input_json, failed_step, error_message, created_at, updated_at FROM drafts WHERE user_id = ? ORDER BY updated_at DESC", (user_id,))
        rows = cursor.fetchall()
        conn.close()
        return [
            {
                "id": r[0],
                "user_id": r[1],
                "status": r[2],
                "input_json": safe_json_load(r[3], {}),
                "failed_step": r[4],
                "error_message": r[5],
                "created_at": r[6],
                "updated_at": r[7]
            } for r in rows
        ]

    def delete_draft(self, user_id: Any, draft_id: Any) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        if self.is_postgres:
            cursor.execute("DELETE FROM drafts WHERE id = %s AND user_id = %s", (draft_id, user_id))
        else:
            cursor.execute("DELETE FROM drafts WHERE id = ? AND user_id = ?", (draft_id, user_id))
        conn.commit()
        conn.close()
        return True

    def clear_converted_drafts(self, user_id: Any) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        if self.is_postgres:
            cursor.execute("DELETE FROM drafts WHERE user_id = %s AND status = 'converted_to_history'", (user_id,))
        else:
            cursor.execute("DELETE FROM drafts WHERE user_id = ? AND status = 'converted_to_history'", (user_id,))
        conn.commit()
        conn.close()

    # USER SETTINGS CRUD methods
    def save_settings(self, user_id: Any, settings_json: dict) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()

        if self.is_postgres:
            cursor.execute("SELECT 1 FROM user_settings WHERE user_id = %s", (user_id,))
        else:
            cursor.execute("SELECT 1 FROM user_settings WHERE user_id = ?", (user_id,))
        exists = cursor.fetchone() is not None

        settings_str = json.dumps(settings_json, ensure_ascii=False)
        if exists:
            if self.is_postgres:
                cursor.execute(
                    "UPDATE user_settings SET settings_json = %s::jsonb, updated_at = %s WHERE user_id = %s",
                    (settings_str, now, user_id)
                )
            else:
                cursor.execute(
                    "UPDATE user_settings SET settings_json = ?, updated_at = ? WHERE user_id = ?",
                    (settings_str, now, user_id)
                )
        else:
            from uuid import uuid4
            new_id = str(uuid4())
            if self.is_postgres:
                cursor.execute(
                    "INSERT INTO user_settings (user_id, settings_json, created_at, updated_at) VALUES (%s, %s::jsonb, %s, %s)",
                    (user_id, settings_str, now, now)
                )
            else:
                cursor.execute(
                    "INSERT INTO user_settings (id, user_id, settings_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (new_id, user_id, settings_str, now, now)
                )
        conn.commit()
        conn.close()

    def get_settings(self, user_id: Any) -> dict:
        conn = self.get_connection()
        cursor = conn.cursor()
        if self.is_postgres:
            cursor.execute("SELECT settings_json FROM user_settings WHERE user_id = %s", (user_id,))
        else:
            cursor.execute("SELECT settings_json FROM user_settings WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return {}
        return safe_json_load(row[0], {})

    # EMAIL VERIFICATION CRUD methods
    def create_email_verification_code(
        self,
        email: str,
        code_hash: str,
        purpose: str,
        expires_at: datetime,
        max_attempts: int,
        request_ip: str = "",
    ) -> str:
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        from uuid import uuid4
        code_id = str(uuid4())
        cursor.execute(
            """
            INSERT INTO email_verification_codes
                (id, email, code_hash, purpose, attempts, max_attempts, expires_at, request_ip, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (code_id, email, code_hash, purpose, 0, max_attempts, expires_at.isoformat(), request_ip, now),
        )
        conn.commit()
        conn.close()
        return code_id

    def get_latest_email_verification_code(self, email: str, purpose: str) -> Optional[dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, email, code_hash, purpose, attempts, max_attempts, expires_at, used_at, created_at
            FROM email_verification_codes
            WHERE email = ? AND purpose = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (email, purpose),
        )
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        return {
            "id": row[0],
            "email": row[1],
            "code_hash": row[2],
            "purpose": row[3],
            "attempts": int(row[4] or 0),
            "max_attempts": int(row[5] or 5),
            "expires_at": row[6],
            "used_at": row[7],
            "created_at": row[8],
        }

    def increment_email_verification_attempts(self, code_id: str) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE email_verification_codes SET attempts = attempts + 1 WHERE id = ?",
            (code_id,),
        )
        conn.commit()
        conn.close()

    def mark_email_verification_code_used(self, code_id: str) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE email_verification_codes SET used_at = ? WHERE id = ?",
            (datetime.now().isoformat(), code_id),
        )
        conn.commit()
        conn.close()

    # MODEL CONFIGS CRUD methods
    @staticmethod
    def _is_api_key_placeholder(api_key: Optional[str]) -> bool:
        if not api_key:
            return True
        return api_key.strip() in {
            "",
            "********",
            "SERVER_SECRET_MANAGED",
            "your_api_key_here",
            "your_model_secret_encryption_key_here",
        }

    def save_model_config(self, user_id: Optional[Any], provider: str, model_id: str, display_name: Optional[str], api_key: str, is_server_managed: bool = False, enabled: bool = True, config_json: Optional[Any] = None, config_id: Optional[str] = None) -> Any:
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()

        encrypted_key = None
        if not self._is_api_key_placeholder(api_key):
            encrypted_key = self.encrypt_api_key(api_key)

        cfg_dict = {}
        if config_json:
            if isinstance(config_json, str):
                try:
                    cfg_dict = json.loads(config_json)
                except Exception:
                    cfg_dict = {}
            elif isinstance(config_json, dict):
                cfg_dict = dict(config_json)

        cfg_dict["modelId"] = model_id
        cfg_dict["model_id"] = model_id
        cfg_dict["provider"] = provider
        if display_name:
            cfg_dict["name"] = display_name
            cfg_dict["display_name"] = display_name
        cfg_json_str = json.dumps(cfg_dict, ensure_ascii=False)

        row = None
        if config_id:
            cursor.execute("SELECT id FROM model_configs WHERE id = ?", (config_id,))
            row = cursor.fetchone()

        if not row:
            if user_id:
                cursor.execute("SELECT id FROM model_configs WHERE user_id = ? AND provider = ? AND model_id = ?", (user_id, provider, model_id))
            else:
                cursor.execute("SELECT id FROM model_configs WHERE user_id IS NULL AND provider = ? AND model_id = ?", (provider, model_id))
            row = cursor.fetchone()

        from uuid import uuid4
        new_id = config_id or str(uuid4())

        sm_val = bool(is_server_managed)
        en_val = bool(enabled)

        if row:
            existing_id = row[0]
            if encrypted_key:
                cursor.execute(
                    """
                    UPDATE model_configs
                    SET provider = ?, model_id = ?, display_name = ?, encrypted_api_key = ?, is_server_managed = ?, enabled = ?, config_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (provider, model_id, display_name, encrypted_key, sm_val, en_val, cfg_json_str, now, existing_id)
                )
            else:
                cursor.execute(
                    """
                    UPDATE model_configs
                    SET provider = ?, model_id = ?, display_name = ?, is_server_managed = ?, enabled = ?, config_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (provider, model_id, display_name, sm_val, en_val, cfg_json_str, now, existing_id)
                )
            ret_id = existing_id
        else:
            cursor.execute(
                """
                INSERT INTO model_configs (id, user_id, provider, model_id, display_name, encrypted_api_key, is_server_managed, enabled, config_json, created_at, updated_at, owner_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'user')
                """,
                (new_id, user_id, provider, model_id, display_name, encrypted_key, sm_val, en_val, cfg_json_str, now, now)
            )
            ret_id = new_id

        conn.commit()
        conn.close()
        return ret_id

    def list_model_configs(self, user_id: Optional[Any]) -> List[dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        if user_id:
            cursor.execute(
                """
                SELECT id, user_id, provider, model_id, display_name, encrypted_api_key, is_server_managed, enabled, config_json, created_at, updated_at
                FROM model_configs
                WHERE user_id = ? OR user_id IS NULL
                ORDER BY created_at ASC
                """,
                (user_id,)
            )
        else:
            cursor.execute(
                """
                SELECT id, user_id, provider, model_id, display_name, encrypted_api_key, is_server_managed, enabled, config_json, created_at, updated_at
                FROM model_configs
                WHERE user_id IS NULL
                ORDER BY created_at ASC
                """
            )
        rows = cursor.fetchall()
        conn.close()

        configs = []
        for r in rows:
            extra = safe_json_load(r[8], {})
            item = {
                "id": r[0],
                "user_id": r[1],
                "provider": r[2],
                "model_id": r[3],
                "display_name": r[4],
                "has_api_key": bool(r[5]),
                "api_key": "••••••••" if r[5] else "",
                "is_server_managed": bool(r[6]),
                "enabled": bool(r[7]),
                "created_at": r[9],
                "updated_at": r[10]
            }
            item.update(extra)
            # Override standard keys to match what frontend uses
            item["id"] = r[0]
            item["provider"] = r[2]
            item["modelId"] = r[3]
            item["model_id"] = r[3]
            item["name"] = r[4] or extra.get("name", "")
            item["enabled"] = bool(r[7])
            item["apiKey"] = "••••••••" if r[5] else ""
            configs.append(item)
        return configs

    def get_model_api_key(self, user_id: Optional[Any], provider: str, model_id: str) -> str:
        conn = self.get_connection()
        cursor = conn.cursor()

        def first_usable_key(rows: list[Any]) -> str:
            for row in rows:
                if not row or not row[0]:
                    continue
                api_key = self.decrypt_api_key(row[0]).strip()
                if not self._is_api_key_placeholder(api_key):
                    return api_key
            return ""

        if user_id:
            cursor.execute(
                """
                SELECT encrypted_api_key
                FROM model_configs
                WHERE enabled = TRUE
                  AND (user_id = ? OR user_id IS NULL)
                  AND provider = ?
                  AND model_id = ?
                ORDER BY CASE WHEN user_id = ? THEN 0 ELSE 1 END, updated_at DESC
                LIMIT 1
                """,
                (user_id, provider, model_id, user_id),
            )
        else:
            cursor.execute(
                """
                SELECT encrypted_api_key
                FROM model_configs
                WHERE enabled = TRUE
                  AND user_id IS NULL
                  AND provider = ?
                  AND model_id = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (provider, model_id),
            )
        rows = cursor.fetchall()
        api_key = first_usable_key(rows)
        if api_key:
            conn.close()
            return api_key

        if user_id:
            cursor.execute(
                """
                SELECT encrypted_api_key
                FROM model_configs
                WHERE enabled = TRUE
                  AND (user_id = ? OR user_id IS NULL)
                  AND provider = ?
                  AND encrypted_api_key IS NOT NULL
                ORDER BY CASE WHEN user_id = ? THEN 0 ELSE 1 END, updated_at DESC
                LIMIT 5
                """,
                (user_id, provider, user_id),
            )
        else:
            cursor.execute(
                """
                SELECT encrypted_api_key
                FROM model_configs
                WHERE enabled = TRUE
                  AND user_id IS NULL
                  AND provider = ?
                  AND encrypted_api_key IS NOT NULL
                ORDER BY updated_at DESC
                LIMIT 5
                """,
                (provider,),
            )
        rows = cursor.fetchall()
        conn.close()
        return first_usable_key(rows)

    def delete_model_config(self, user_id: Any, config_id: Any) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM model_configs WHERE id = ? AND user_id = ?", (config_id, user_id))
        conn.commit()
        conn.close()
        return True

    # ANALYSIS RECORDS CRUD (frontend analysis pipeline results)
    def save_analysis_record(self, user_id: Any, status: str, result_json: dict, input_json: Optional[dict] = None, record_id: Optional[str] = None) -> str:
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        from uuid import uuid4
        new_id = record_id or str(uuid4())
        input_str = json.dumps(input_json or {}, ensure_ascii=False)
        result_str = json.dumps(result_json, ensure_ascii=False)

        exists = False
        if record_id:
            if self.is_postgres:
                cursor.execute(
                    "SELECT 1 FROM analysis_records WHERE id = %s AND user_id = %s",
                    (record_id, user_id)
                )
            else:
                cursor.execute(
                    "SELECT 1 FROM analysis_records WHERE id = ? AND user_id = ?",
                    (record_id, user_id)
                )
            exists = cursor.fetchone() is not None

        if exists:
            if self.is_postgres:
                cursor.execute(
                    """
                    UPDATE analysis_records
                    SET status = %s, input_json = %s, result_json = %s, updated_at = %s
                    WHERE id = %s AND user_id = %s
                    """,
                    (status, input_str, result_str, now, record_id, user_id)
                )
            else:
                cursor.execute(
                    """
                    UPDATE analysis_records
                    SET status = ?, input_json = ?, result_json = ?, updated_at = ?
                    WHERE id = ? AND user_id = ?
                    """,
                    (status, input_str, result_str, now, record_id, user_id)
                )
        else:
            if self.is_postgres:
                cursor.execute(
                    """
                    INSERT INTO analysis_records (id, user_id, status, input_json, result_json, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (new_id, user_id, status, input_str, result_str, now, now)
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO analysis_records (id, user_id, status, input_json, result_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (new_id, user_id, status, input_str, result_str, now, now)
                )
        conn.commit()
        conn.close()
        return new_id

    def list_analysis_records(self, user_id: Any, limit: int = 30) -> List[dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        if self.is_postgres:
            cursor.execute(
                "SELECT id, user_id, status, input_json, result_json, created_at, updated_at FROM analysis_records WHERE user_id = %s ORDER BY created_at DESC LIMIT %s",
                (user_id, limit)
            )
        else:
            cursor.execute(
                "SELECT id, user_id, status, input_json, result_json, created_at, updated_at FROM analysis_records WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit)
            )
        rows = cursor.fetchall()
        conn.close()
        out = []
        for r in rows:
            result = self._load_json(r[4], {})
            result["id"] = r[0]
            result["status"] = r[2]
            if not result.get("createdAt"):
                result["createdAt"] = r[5]
            out.append(result)
        return out

    def get_analysis_record(self, user_id: Any, record_id: Any) -> Optional[dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        if self.is_postgres:
            cursor.execute(
                "SELECT id, user_id, status, input_json, result_json, created_at, updated_at FROM analysis_records WHERE id = %s AND user_id = %s",
                (record_id, user_id)
            )
        else:
            cursor.execute(
                "SELECT id, user_id, status, input_json, result_json, created_at, updated_at FROM analysis_records WHERE id = ? AND user_id = ?",
                (record_id, user_id)
            )
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        result = self._load_json(row[4], {})
        result["id"] = row[0]
        result["status"] = row[2]
        if not result.get("createdAt"):
            result["createdAt"] = row[5]
        return result

    def delete_analysis_record(self, user_id: Any, record_id: Any) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        if self.is_postgres:
            cursor.execute("DELETE FROM analysis_records WHERE id = %s AND user_id = %s", (record_id, user_id))
        else:
            cursor.execute("DELETE FROM analysis_records WHERE id = ? AND user_id = ?", (record_id, user_id))
        deleted = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return deleted

    def update_analysis_record_status(self, user_id: Any, record_id: Any, status: str) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        if self.is_postgres:
            cursor.execute(
                "UPDATE analysis_records SET status = %s, updated_at = %s WHERE id = %s AND user_id = %s",
                (status, now, record_id, user_id)
            )
        else:
            cursor.execute(
                "UPDATE analysis_records SET status = ?, updated_at = ? WHERE id = ? AND user_id = ?",
                (status, now, record_id, user_id)
            )
        conn.commit()
        conn.close()

    # SESSION CRUD methods (persistent database-backed sessions)
    def create_session(self, token: str, user_id: Any, expires_at: datetime) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, user_id, datetime.now().isoformat(), expires_at.isoformat())
        )
        conn.commit()
        conn.close()

    def get_session_user_id(self, token: str) -> Optional[Any]:
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute(
            "SELECT user_id FROM sessions WHERE token = ? AND expires_at > ?",
            (token, now)
        )
        row = cursor.fetchone()
        conn.close()
        if row is None:
            return None
        return row[0]

    def delete_session(self, token: str) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
        conn.close()

    def delete_user_sessions(self, user_id: Any) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()

    def cleanup_expired_sessions(self) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        count = cursor.rowcount
        conn.commit()
        conn.close()
        return count

    def seed_db(self) -> None:
        """Seeds the default admin user into the database."""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT password_hash FROM users WHERE username = ?", ("admin@example.com",))
            row = cursor.fetchone()
            if row is None:
                hashed = hash_password("ChangeMe123!")
                now = datetime.now().isoformat()
                if self.is_postgres:
                    cursor.execute(
                        "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
                        ("admin@example.com", hashed, "admin", now)
                    )
                else:
                    cursor.execute(
                        "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
                        ("admin@example.com", hashed, "admin", now)
                    )
                conn.commit()
                print("[SECURITY] Default local admin account is for development only. Change the password in production.")
            else:
                stored_hash = row[0]
                if parse_password_hash(stored_hash) is None:
                    # Self-heal corrupted password hash
                    hashed = hash_password("ChangeMe123!")
                    cursor.execute(
                        "UPDATE users SET password_hash = ?, role = 'admin' WHERE username = ?",
                        (hashed, "admin@example.com")
                    )
                    conn.commit()
                    print("銆愬畨鍏ㄤ慨澶嶃€戞娴嬪埌榛樿绠＄悊鍛樺搱甯屽凡鎹熷潖锛屽凡鑷姩淇骞堕噸缃负 ChangeMe123!")
                else:
                    cursor.execute("UPDATE users SET role = 'admin' WHERE username = ?", ("admin@example.com",))
                    conn.commit()

            # 鈹€鈹€ Repair test@example.com with test1234 鈹€鈹€
            cursor.execute("SELECT password_hash FROM users WHERE username = ?", ("test@example.com",))
            row_test = cursor.fetchone()
            if row_test is None:
                hashed_test = hash_password("test1234")
                now = datetime.now().isoformat()
                cursor.execute(
                    "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
                    ("test@example.com", hashed_test, "user", now)
                )
                conn.commit()
                print("[SEED] Created test@example.com with default password test1234.")
            else:
                stored_hash_test = row_test[0]
                if parse_password_hash(stored_hash_test) is None or not verify_password_hash("test1234", stored_hash_test):
                    hashed_test = hash_password("test1234")
                    cursor.execute(
                        "UPDATE users SET password_hash = ?, role = 'user', is_active = TRUE WHERE username = ?",
                        (hashed_test, "test@example.com")
                    )
                    conn.commit()
                    print("[SEED] Reset test@example.com to default password test1234.")

            # 鈹€鈹€ Repair testuser@example.com with test1234 鈹€鈹€
            cursor.execute("SELECT password_hash FROM users WHERE username = ?", ("testuser@example.com",))
            row_testuser = cursor.fetchone()
            if row_testuser is None:
                hashed_testuser = hash_password("test1234")
                now = datetime.now().isoformat()
                cursor.execute(
                    "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
                    ("testuser@example.com", hashed_testuser, "user", now)
                )
                conn.commit()
            else:
                stored_hash_testuser = row_testuser[0]
                if parse_password_hash(stored_hash_testuser) is None or not verify_password_hash("test1234", stored_hash_testuser):
                    hashed_testuser = hash_password("test1234")
                    cursor.execute(
                        "UPDATE users SET password_hash = ?, is_active = TRUE WHERE username = ?",
                        (hashed_testuser, "testuser@example.com")
                    )
                    conn.commit()

            # 鈹€鈹€ Repair 'test' user with test1234 and ensure active 鈹€鈹€
            cursor.execute("SELECT password_hash FROM users WHERE username = ?", ("test",))
            row_t = cursor.fetchone()
            if row_t is not None:
                stored_hash_t = row_t[0]
                if parse_password_hash(stored_hash_t) is None or not verify_password_hash("test1234", stored_hash_t):
                    hashed_t = hash_password("test1234")
                    cursor.execute(
                        "UPDATE users SET password_hash = ?, is_active = TRUE WHERE username = ?",
                        (hashed_t, "test")
                    )
                    conn.commit()
        except Exception as e:
            print(f"Error seeding user: {e}")
        finally:
            conn.close()

    def list_user_available_configs(self, user_id: Any) -> List[dict]:
        conn = self.get_connection()
        cursor = conn.cursor()

        # 1. Fetch user-owned configs (owner_type = 'user' or null)
        cursor.execute(
            """
            SELECT id, user_id, provider, model_id, display_name, encrypted_api_key, is_server_managed, enabled, config_json, created_at, updated_at, COALESCE(owner_type, 'user')
            FROM model_configs
            WHERE user_id = ? AND (owner_type IS NULL OR owner_type = 'user')
            ORDER BY created_at ASC
            """,
            (user_id,)
        )
        owned_rows = cursor.fetchall()

        # 2. Fetch assigned admin-managed configs
        cursor.execute(
            """
            SELECT c.id, c.user_id, c.provider, c.model_id, c.display_name, c.encrypted_api_key, c.is_server_managed, c.enabled, c.config_json, c.created_at, c.updated_at, c.owner_type
            FROM model_configs c
            JOIN model_config_assignments a ON c.id = a.config_id
            WHERE a.user_id = ? AND a.enabled = ? AND c.enabled = ? AND c.owner_type IN ('admin', 'system')
            ORDER BY c.created_at ASC
            """,
            (user_id, True, True)
        )
        assigned_rows = cursor.fetchall()
        conn.close()

        configs = []
        # Process user-owned configs
        for r in owned_rows:
            extra = safe_json_load(r[8], {})
            item = {
                "id": r[0],
                "user_id": r[1],
                "provider": r[2],
                "modelId": r[3],
                "name": r[4] or extra.get("name") or extra.get("display_name") or "",
                "apiKey": "••••••••" if r[5] else "",
                "is_server_managed": bool(r[6]),
                "enabled": bool(r[7]),
                "created_at": r[9],
                "updated_at": r[10],
                "owner_type": r[11],
                "source": "user_owned",
                "editable": True
            }
            # Merge extra options
            item.update({k: v for k, v in extra.items() if k not in item})
            # Ensure keys correct
            item["id"] = r[0]
            item["provider"] = r[2]
            item["modelId"] = r[3]
            item["model_id"] = r[3]
            item["name"] = r[4] or extra.get("name") or extra.get("display_name") or ""
            item["apiKey"] = "••••••••" if r[5] else ""
            item["enabled"] = bool(r[7])
            configs.append(item)

        # Process admin-assigned configs
        for r in assigned_rows:
            extra = safe_json_load(r[8], {})
            item = {
                "id": r[0],
                "user_id": r[1],
                "provider": r[2],
                "modelId": r[3],
                "name": r[4] or extra.get("name") or extra.get("display_name") or "",
                "apiKey": "服务器托管",
                "is_server_managed": True,
                "enabled": bool(r[7]),
                "created_at": r[9],
                "updated_at": r[10],
                "owner_type": r[11],
                "source": "admin_assigned",
                "editable": False
            }
            # Merge extra options
            item.update({k: v for k, v in extra.items() if k not in item})
            item["id"] = r[0]
            item["provider"] = r[2]
            item["modelId"] = r[3]
            item["model_id"] = r[3]
            item["name"] = r[4] or extra.get("name") or extra.get("display_name") or ""
            item["apiKey"] = "服务器托管"
            item["enabled"] = bool(r[7])
            configs.append(item)

        return configs

    def get_model_api_key_v2(self, user_id: Any, provider: str, model_id: str, config_id: Optional[str] = None) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        conn = self.get_connection()
        cursor = conn.cursor()

        # Validate UUIDs for PostgreSQL to prevent DataError crashes
        is_valid_config_uuid = False
        if config_id:
            try:
                from uuid import UUID
                UUID(str(config_id))
                is_valid_config_uuid = True
            except ValueError:
                pass

        is_valid_user_uuid = True

        # 1. Try resolving by config_id if provided and valid
        if is_valid_config_uuid and is_valid_user_uuid:
            # Check user-owned
            cursor.execute(
                """
                SELECT encrypted_api_key, id, owner_type
                FROM model_configs
                WHERE id = ? AND user_id = ? AND (owner_type IS NULL OR owner_type = 'user')
                """,
                (config_id, user_id)
            )
            row = cursor.fetchone()
            if row:
                conn.close()
                key = self.decrypt_api_key(row[0]).strip() if row[0] else ""
                return key, row[1], None

            # Check admin-assigned
            cursor.execute(
                """
                SELECT c.encrypted_api_key, c.id, a.id
                FROM model_configs c
                JOIN model_config_assignments a ON c.id = a.config_id
                WHERE c.id = ? AND a.user_id = ? AND a.enabled = ? AND c.enabled = ? AND c.owner_type IN ('admin', 'system')
                """,
                (config_id, user_id, True, True)
            )
            row = cursor.fetchone()
            if row:
                conn.close()
                key = self.decrypt_api_key(row[0]).strip() if row[0] else ""
                return key, row[1], row[2]

        # 2. Resolve by provider and model_id
        if is_valid_user_uuid:
            # First try user-owned configs
            cursor.execute(
                """
                SELECT encrypted_api_key, id
                FROM model_configs
                WHERE user_id = ? AND provider = ? AND model_id = ? AND (owner_type IS NULL OR owner_type = 'user') AND enabled = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (user_id, provider, model_id, True)
            )
            row = cursor.fetchone()
            if row:
                conn.close()
                key = self.decrypt_api_key(row[0]).strip() if row[0] else ""
                return key, row[1], None

            # Then try admin-assigned configs
            cursor.execute(
                """
                SELECT c.encrypted_api_key, c.id, a.id
                FROM model_configs c
                JOIN model_config_assignments a ON c.id = a.config_id
                WHERE a.user_id = ? AND c.provider = ? AND c.model_id = ? AND a.enabled = ? AND c.enabled = ? AND c.owner_type IN ('admin', 'system')
                ORDER BY c.updated_at DESC
                LIMIT 1
                """,
                (user_id, provider, model_id, True, True)
            )
            row = cursor.fetchone()
            if row:
                conn.close()
                key = self.decrypt_api_key(row[0]).strip() if row[0] else ""
                return key, row[1], row[2]

        conn.close()
        return None, None, None

    def log_model_usage(
        self,
        user_id: Any,
        config_id: Optional[str],
        assignment_id: Optional[str],
        analysis_id: Optional[str],
        provider: str,
        model_id: str,
        usage_type: str,
        endpoint: Optional[str],
        success: bool,
        error_type: Optional[str],
        prompt_tokens: Optional[int],
        completion_tokens: Optional[int],
        total_tokens: Optional[int],
        input_chars: Optional[int],
        output_chars: Optional[int],
        latency_ms: int,
        cost_estimate: Optional[float] = None
    ) -> str:
        conn = self.get_connection()
        cursor = conn.cursor()
        from uuid import uuid4
        log_id = str(uuid4())
        now = datetime.now().isoformat()

        db_success = 1 if success else 0
        if self.is_postgres:
            db_success = success

        cursor.execute(
            """
            INSERT INTO model_usage_logs (
                id, user_id, config_id, assignment_id, analysis_id,
                provider, model_id, usage_type, endpoint, success, error_type,
                prompt_tokens, completion_tokens, total_tokens, input_chars, output_chars,
                latency_ms, cost_estimate, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                log_id, user_id, config_id, assignment_id, analysis_id,
                provider, model_id, usage_type, endpoint, db_success, error_type,
                prompt_tokens, completion_tokens, total_tokens, input_chars, output_chars,
                latency_ms, cost_estimate, now
            )
        )
        conn.commit()
        conn.close()
        return log_id

    def log_admin_audit(
        self,
        admin_user_id: Any,
        action: str,
        target_user_id: Optional[Any] = None,
        target_resource_type: Optional[str] = None,
        target_resource_id: Optional[str] = None,
        metadata_json: Optional[dict] = None
    ) -> str:
        conn = self.get_connection()
        cursor = conn.cursor()
        from uuid import uuid4
        audit_id = str(uuid4())
        now = datetime.now().isoformat()
        meta_str = json.dumps(metadata_json or {}, ensure_ascii=False)

        cursor.execute(
            """
            INSERT INTO admin_audit_logs (
                id, admin_user_id, action, target_user_id,
                target_resource_type, target_resource_id, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (audit_id, admin_user_id, action, target_user_id, target_resource_type, target_resource_id, meta_str, now)
        )
        conn.commit()
        conn.close()
        return audit_id

    def admin_list_users(self) -> List[dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, username, role, created_at, is_active, expires_at, generation_limit, remark
            FROM users
            ORDER BY created_at DESC
            """
        )
        users = []
        for row in cursor.fetchall():
            u_id = row[0]
            # Get assignment count
            cursor.execute("SELECT COUNT(*) FROM model_config_assignments WHERE user_id = ?", (u_id,))
            assign_count = cursor.fetchone()[0]
            # Get usage count
            cursor.execute("SELECT COUNT(*) FROM model_usage_logs WHERE user_id = ?", (u_id,))
            usage_count = cursor.fetchone()[0]

            # Find last login / last active time if available (from sessions table)
            cursor.execute("SELECT MAX(created_at) FROM sessions WHERE user_id = ?", (u_id,))
            last_login_row = cursor.fetchone()
            last_login = self._serialize_datetime_value(last_login_row[0]) if last_login_row and last_login_row[0] else None

            # Find assigned model configurations displays
            cursor.execute(
                """
                SELECT c.display_name
                FROM model_configs c
                JOIN model_config_assignments a ON c.id = a.config_id
                WHERE a.user_id = ? AND a.enabled = ?
                """,
                (u_id, True)
            )
            assigned_models = [r[0] or "Unnamed model" for r in cursor.fetchall()]

            is_active_val = bool(row[4]) if row[4] is not None else True
            expires_at_val = self._serialize_datetime_value(row[5]) if row[5] else None
            generation_limit_val = int(row[6]) if row[6] is not None else 5
            remark_val = row[7] if row[7] else ""

            users.append({
                "id": u_id,
                "username": row[1],
                "role": row[2],
                "created_at": self._serialize_datetime_value(row[3]),
                "is_active": is_active_val,
                "expires_at": expires_at_val,
                "generation_limit": generation_limit_val,
                "remark": remark_val,
                "assignment_count": assign_count,
                "usage_count": usage_count,
                "last_login": last_login,
                "assigned_models": assigned_models
            })
        conn.close()
        return users

    def admin_create_temp_user(self, username: str, password_hash: str, expires_at: Optional[str]) -> int:
        normalized = normalize_username(username)
        if not normalized:
            raise ValueError("username_required")
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO users (username, password_hash, created_at, is_active, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    normalized,
                    password_hash,
                    datetime.now().isoformat(),
                    True,
                    expires_at,
                ),
            )
            user_id = int(cursor.lastrowid)
            conn.commit()
            return user_id
        except Exception as exc:
            raise ValueError("username_taken") from exc
        finally:
            conn.close()

    def admin_update_user_status(self, user_id: Any, is_active: bool) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        val = is_active
        cursor.execute("UPDATE users SET is_active = ? WHERE id = ?", (val, user_id))
        conn.commit()
        conn.close()

    def admin_update_user_expiry(self, user_id: Any, expires_at: Optional[str]) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET expires_at = ? WHERE id = ?", (expires_at, user_id))
        conn.commit()
        conn.close()

    def admin_update_user_generation_limit(self, user_id: Any, limit: int) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET generation_limit = ? WHERE id = ?", (limit, user_id))
        conn.commit()
        conn.close()

    def admin_update_username(self, user_id: Any, new_username: str) -> None:
        normalized = normalize_username(new_username)
        if not normalized:
            raise ValueError("username_required")
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE users SET username = ? WHERE id = ?", (normalized, user_id))
            conn.commit()
        except Exception as exc:
            if self._is_unique_constraint_error(exc):
                raise ValueError("username_taken") from exc
            raise exc
        finally:
            conn.close()

    def admin_update_remark(self, user_id: Any, remark: str) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET remark = ? WHERE id = ?", (remark, user_id))
        conn.commit()
        conn.close()

    def decrement_user_generation_limit(self, user_id: Any) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET generation_limit = generation_limit - 1 WHERE id = ? AND role != 'admin' AND generation_limit > 0", (user_id,))
        conn.commit()
        conn.close()

    def admin_list_model_configs(self) -> List[dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, user_id, provider, model_id, display_name, encrypted_api_key, is_server_managed, enabled, config_json, created_at, updated_at, owner_type
            FROM model_configs
            WHERE owner_type IN ('admin', 'system')
            ORDER BY created_at DESC
            """
        )
        configs = []
        for r in cursor.fetchall():
            cfg_id = r[0]
            cursor.execute("SELECT COUNT(*) FROM model_config_assignments WHERE config_id = ?", (cfg_id,))
            assign_count = cursor.fetchone()[0]

            extra = safe_json_load(r[8], {})
            item = {
                "id": cfg_id,
                "user_id": r[1],
                "provider": r[2],
                "modelId": r[3],
                "name": r[4] or extra.get("name") or extra.get("display_name") or "",
                "apiKey": "••••••••" if r[5] else "",
                "is_server_managed": bool(r[6]),
                "enabled": bool(r[7]),
                "created_at": r[9],
                "updated_at": r[10],
                "owner_type": r[11],
                "assignment_count": assign_count
            }
            item.update({k: v for k, v in extra.items() if k not in item})
            item["id"] = cfg_id
            item["provider"] = r[2]
            item["modelId"] = r[3]
            item["model_id"] = r[3]
            item["name"] = r[4] or extra.get("name") or extra.get("display_name") or ""
            item["apiKey"] = "••••••••" if r[5] else ""
            item["enabled"] = bool(r[7])
            configs.append(item)
        conn.close()
        return configs

    def admin_create_model_config(
        self,
        admin_user_id: Any,
        provider: str,
        model_id: str,
        display_name: str,
        api_key: str,
        enabled: bool = True,
        config_json: Optional[dict] = None
    ) -> str:
        conn = self.get_connection()
        cursor = conn.cursor()
        from uuid import uuid4
        new_id = str(uuid4())
        now = datetime.now().isoformat()

        encrypted_key = self.encrypt_api_key(api_key) if api_key else None
        cfg_dict = dict(config_json) if config_json else {}
        cfg_dict["modelId"] = model_id
        cfg_dict["model_id"] = model_id
        cfg_dict["provider"] = provider
        if display_name:
            cfg_dict["name"] = display_name
            cfg_dict["display_name"] = display_name
        cfg_json_str = json.dumps(cfg_dict, ensure_ascii=False)

        if self.is_postgres:
            cursor.execute(
                """
                INSERT INTO model_configs (
                    id, user_id, provider, model_id, display_name, encrypted_api_key,
                    is_server_managed, enabled, config_json, created_at, updated_at,
                    owner_type, created_by_admin_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id, admin_user_id, provider, model_id, display_name, encrypted_key,
                    True, enabled, cfg_json_str, now, now, 'admin', admin_user_id
                )
            )
        else:
            cursor.execute(
                """
                INSERT INTO model_configs (
                    id, user_id, provider, model_id, display_name, encrypted_api_key,
                    is_server_managed, enabled, config_json, created_at, updated_at,
                    owner_type, created_by_admin_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id, admin_user_id, provider, model_id, display_name, encrypted_key,
                    1, 1 if enabled else 0, cfg_json_str, now, now, 'admin', admin_user_id
                )
            )
        conn.commit()
        conn.close()
        return new_id

    def admin_update_model_config(
        self,
        config_id: str,
        provider: str,
        model_id: str,
        display_name: str,
        api_key: Optional[str] = None,
        enabled: Optional[bool] = None,
        config_json: Optional[dict] = None
    ) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT owner_type FROM model_configs WHERE id = ?", (config_id,))
        row = cursor.fetchone()
        if not row or row[0] not in ('admin', 'system'):
            conn.close()
            return False

        now = datetime.now().isoformat()

        updates = ["provider = ?", "model_id = ?", "display_name = ?", "updated_at = ?"]
        params = [provider, model_id, display_name, now]

        if api_key and not self._is_api_key_placeholder(api_key):
            updates.append("encrypted_api_key = ?")
            params.append(self.encrypt_api_key(api_key))

        if enabled is not None:
            updates.append("enabled = ?")
            params.append(enabled)

        if config_json is not None:
            config_json["modelId"] = model_id
            config_json["model_id"] = model_id
            config_json["provider"] = provider
            if display_name:
                config_json["name"] = display_name
                config_json["display_name"] = display_name
            updates.append("config_json = ?")
            params.append(json.dumps(config_json, ensure_ascii=False))

        params.append(config_id)

        query = f"UPDATE model_configs SET {', '.join(updates)} WHERE id = ?"
        cursor.execute(query, tuple(params))
        conn.commit()
        conn.close()
        return True

    def admin_assign_model_config(
        self,
        admin_user_id: Any,
        config_id: str,
        target_user_ids: List[Any]
    ) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT owner_type FROM model_configs WHERE id = ?", (config_id,))
        row = cursor.fetchone()
        if not row or row[0] not in ('admin', 'system'):
            conn.close()
            raise ValueError("not_admin_managed_config")

        now = datetime.now().isoformat()
        from uuid import uuid4

        for user_id in target_user_ids:
            cursor.execute("SELECT id FROM model_config_assignments WHERE config_id = ? AND user_id = ?", (config_id, user_id))
            exist_row = cursor.fetchone()
            if exist_row:
                if self.is_postgres:
                    cursor.execute(
                        "UPDATE model_config_assignments SET enabled = TRUE, updated_at = ? WHERE id = ?",
                        (now, exist_row[0])
                    )
                else:
                    cursor.execute(
                        "UPDATE model_config_assignments SET enabled = 1, updated_at = ? WHERE id = ?",
                        (now, exist_row[0])
                    )
            else:
                new_id = str(uuid4())
                if self.is_postgres:
                    cursor.execute(
                        """
                        INSERT INTO model_config_assignments (id, config_id, user_id, assigned_by_admin_id, enabled, created_at, updated_at)
                        VALUES (?, ?, ?, ?, TRUE, ?, ?)
                        """,
                        (new_id, config_id, user_id, admin_user_id, now, now)
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO model_config_assignments (id, config_id, user_id, assigned_by_admin_id, enabled, created_at, updated_at)
                        VALUES (?, ?, ?, ?, 1, ?, ?)
                        """,
                        (new_id, config_id, user_id, admin_user_id, now, now)
                    )
        conn.commit()
        conn.close()

    def admin_revoke_model_config(
        self,
        config_id: str,
        target_user_ids: List[Any]
    ) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        for user_id in target_user_ids:
            cursor.execute("DELETE FROM model_config_assignments WHERE config_id = ? AND user_id = ?", (config_id, user_id))
        conn.commit()
        conn.close()

    def admin_get_assignments(self, config_id: str) -> List[dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT a.id, a.user_id, u.username, a.enabled, a.created_at
            FROM model_config_assignments a
            JOIN users u ON a.user_id = u.id
            WHERE a.config_id = ?
            ORDER BY a.created_at DESC
            """,
            (config_id,)
        )
        assignments = []
        for r in cursor.fetchall():
            assignments.append({
                "id": r[0],
                "user_id": r[1],
                "username": r[2],
                "enabled": bool(r[3]),
                "created_at": r[4]
            })
        conn.close()
        return assignments

    def admin_get_usage_summary(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        provider: Optional[str] = None,
        model_id: Optional[str] = None,
        user_id: Optional[Any] = None
    ) -> dict:
        conn = self.get_connection()
        cursor = conn.cursor()

        filters = []
        params = []

        if start_date:
            filters.append("created_at >= ?")
            params.append(start_date)
        if end_date:
            filters.append("created_at <= ?")
            params.append(end_date)
        if provider:
            filters.append("provider = ?")
            params.append(provider)
        if model_id:
            filters.append("model_id = ?")
            params.append(model_id)
        if user_id:
            filters.append("user_id = ?")
            params.append(user_id)

        where_clause = ""
        if filters:
            where_clause = "WHERE " + " AND ".join(filters)

        success_check = "success = TRUE"
        fail_check = "success = FALSE"

        cursor.execute(
            f"""
            SELECT
                COUNT(*) as total_calls,
                SUM(CASE WHEN {success_check} THEN 1 ELSE 0 END) as success_calls,
                SUM(CASE WHEN {fail_check} THEN 1 ELSE 0 END) as failed_calls,
                AVG(latency_ms) as avg_latency,
                SUM(prompt_tokens) as total_prompt_tokens,
                SUM(completion_tokens) as total_completion_tokens,
                SUM(total_tokens) as total_tokens
            FROM model_usage_logs
            {where_clause}
            """,
            tuple(params)
        )
        row = cursor.fetchone()

        summary = {
            "totalCalls": row[0] or 0,
            "successCalls": row[1] or 0,
            "failedCalls": row[2] or 0,
            "avgLatency": round(row[3], 2) if row[3] is not None else 0,
            "totalPromptTokens": row[4] or 0,
            "totalCompletionTokens": row[5] or 0,
            "totalTokens": row[6] or 0
        }

        # Group by User
        cursor.execute(
            f"""
            SELECT u.username, COUNT(*) as count
            FROM model_usage_logs l
            LEFT JOIN users u ON l.user_id = u.id
            {where_clause}
            GROUP BY u.username
            ORDER BY count DESC
            """,
            tuple(params)
        )
        summary["byUser"] = [{"username": r[0] or "鏈煡鐢ㄦ埛", "count": r[1]} for r in cursor.fetchall()]

        # Group by Model
        cursor.execute(
            f"""
            SELECT model_id, COUNT(*) as count
            FROM model_usage_logs
            {where_clause}
            GROUP BY model_id
            ORDER BY count DESC
            """,
            tuple(params)
        )
        summary["byModel"] = [{"modelId": r[0], "count": r[1]} for r in cursor.fetchall()]

        # Group by Provider
        cursor.execute(
            f"""
            SELECT provider, COUNT(*) as count
            FROM model_usage_logs
            {where_clause}
            GROUP BY provider
            ORDER BY count DESC
            """,
            tuple(params)
        )
        summary["byProvider"] = [{"provider": r[0], "count": r[1]} for r in cursor.fetchall()]

        # Group by Day
        date_expr = "TO_CHAR(created_at, 'YYYY-MM-DD')"
        cursor.execute(
            f"""
            SELECT {date_expr} as day, COUNT(*) as count
            FROM model_usage_logs
            {where_clause}
            GROUP BY day
            ORDER BY day ASC
            """,
            tuple(params)
        )
        summary["byDay"] = [{"day": r[0], "count": r[1]} for r in cursor.fetchall()]

        conn.close()
        return summary

    def admin_get_usage_logs(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        provider: Optional[str] = None,
        model_id: Optional[str] = None,
        user_id: Optional[Any] = None,
        success: Optional[bool] = None,
        page: int = 1,
        page_size: int = 20
    ) -> dict:
        conn = self.get_connection()
        cursor = conn.cursor()

        filters = []
        params = []

        if start_date:
            filters.append("l.created_at >= ?")
            params.append(start_date)
        if end_date:
            filters.append("l.created_at <= ?")
            params.append(end_date)
        if provider:
            filters.append("l.provider = ?")
            params.append(provider)
        if model_id:
            filters.append("l.model_id = ?")
            params.append(model_id)
        if user_id:
            filters.append("l.user_id = ?")
            params.append(user_id)
        if success is not None:
            if self.is_postgres:
                filters.append("l.success = ?")
                params.append(success)
            else:
                filters.append("l.success = ?")
                params.append(1 if success else 0)

        where_clause = ""
        if filters:
            where_clause = "WHERE " + " AND ".join(filters)

        cursor.execute(f"SELECT COUNT(*) FROM model_usage_logs l {where_clause}", tuple(params))
        total_count = cursor.fetchone()[0]

        offset = (page - 1) * page_size

        # DatabaseCursorWrapper translates placeholders before psycopg2 execution.
        limit_offset_clause = "LIMIT ? OFFSET ?"
        # We need to copy params list so we don't pollute the counting query
        log_params = list(params)
        log_params.extend([page_size, offset])

        cursor.execute(
            f"""
            SELECT
                l.id, l.user_id, u.username, l.config_id, c.display_name as config_name,
                l.provider, l.model_id, l.usage_type, l.endpoint, l.success, l.error_type,
                l.prompt_tokens, l.completion_tokens, l.total_tokens, l.input_chars, l.output_chars,
                l.latency_ms, l.created_at
            FROM model_usage_logs l
            LEFT JOIN users u ON l.user_id = u.id
            LEFT JOIN model_configs c ON l.config_id = c.id
            {where_clause}
            ORDER BY l.created_at DESC
            {limit_offset_clause}
            """,
            tuple(log_params)
        )

        logs = []
        for r in cursor.fetchall():
            logs.append({
                "id": r[0],
                "userId": r[1],
                "username": r[2] or "鏈煡鐢ㄦ埛",
                "configId": r[3],
                "configName": r[4] or "榛樿/鏈煡",
                "provider": r[5],
                "modelId": r[6],
                "usageType": r[7],
                "endpoint": r[8],
                "success": bool(r[9]),
                "errorType": r[10],
                "promptTokens": r[11],
                "completionTokens": r[12],
                "totalTokens": r[13],
                "inputChars": r[14],
                "outputChars": r[15],
                "latencyMs": r[16],
                "createdAt": r[17]
            })

        conn.close()
        return {
            "logs": logs,
            "totalCount": total_count,
            "page": page,
            "pageSize": page_size,
            "totalPages": (total_count + page_size - 1) // page_size if page_size > 0 else 1
        }

    def get_cached_embedding_simple(self, user_id: Any, content_hash: str) -> Optional[List[float]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if self.is_postgres:
                cursor.execute(
                    """
                    SELECT embedding
                    FROM embeddings
                    WHERE user_id = %s AND content_hash = %s
                    LIMIT 1
                    """,
                    (user_id, content_hash)
                )
            else:
                cursor.execute(
                    """
                    SELECT embedding
                    FROM embeddings
                    WHERE user_id = ? AND content_hash = ?
                    LIMIT 1
                    """,
                    (user_id, content_hash)
                )
            row = cursor.fetchone()
            if row:
                emb_val = row[0]
                if isinstance(emb_val, str):
                    if emb_val.startswith("[") and emb_val.endswith("]"):
                        try:
                            return json.loads(emb_val)
                        except:
                            try:
                                cleaned = emb_val.strip("[]")
                                return [float(x) for x in cleaned.split(",") if x.strip()]
                            except:
                                pass
                    else:
                        try:
                            cleaned = emb_val.strip("[]")
                            return [float(x) for x in cleaned.split(",") if x.strip()]
                        except:
                            pass
                elif isinstance(emb_val, list):
                    return emb_val
                elif emb_val is not None:
                    try:
                        return list(emb_val)
                    except:
                        pass
            return None
        except Exception as e:
            print(f"[DATABASE] Error in get_cached_embedding_simple: {e}")
            return None
        finally:
            conn.close()

    def get_cached_embedding(self, user_id: Any, content_hash: str, provider: str, model_id: str) -> Optional[List[float]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if self.is_postgres:
                cursor.execute(
                    """
                    SELECT embedding, metadata_json
                    FROM embeddings
                    WHERE user_id = %s AND content_hash = %s
                    """,
                    (user_id, content_hash)
                )
            else:
                cursor.execute(
                    """
                    SELECT embedding, metadata_json
                    FROM embeddings
                    WHERE user_id = ? AND content_hash = ?
                    """,
                    (user_id, content_hash)
                )
            rows = cursor.fetchall()
            for row in rows:
                emb_val, meta_str = row
                meta = safe_json_load(meta_str, {})
                if meta.get("provider") == provider and meta.get("model_id") == model_id:
                    if isinstance(emb_val, str):
                        if emb_val.startswith("[") and emb_val.endswith("]"):
                            try:
                                return json.loads(emb_val)
                            except:
                                try:
                                    cleaned = emb_val.strip("[]")
                                    return [float(x) for x in cleaned.split(",") if x.strip()]
                                except:
                                    pass
                        else:
                            try:
                                cleaned = emb_val.strip("[]")
                                return [float(x) for x in cleaned.split(",") if x.strip()]
                            except:
                                pass
                    elif isinstance(emb_val, list):
                        return emb_val
                    elif emb_val is not None:
                        try:
                            return list(emb_val)
                        except:
                            pass
            return None
        except Exception as e:
            print(f"[DATABASE] Error getting cached embedding: {e}")
            return None
        finally:
            conn.close()

    def save_embedding(
        self,
        user_id: Any,
        content_hash: str,
        embedding: List[float],
        provider: str,
        model_id: str,
        source_type: str = "chunk",
        source_id: Optional[str] = None,
        analysis_id: Optional[str] = None
    ) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            from uuid import uuid4
            new_id = str(uuid4())
            meta = {
                "provider": provider,
                "model_id": model_id,
                "dimensions": len(embedding)
            }
            meta_str = json.dumps(meta)

            if self.is_postgres:
                has_pgvector = False
                try:
                    cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
                    has_pgvector = cursor.fetchone() is not None
                except:
                    pass

                if has_pgvector:
                    emb_val = "[" + ",".join(str(x) for x in embedding) + "]"
                else:
                    emb_val = json.dumps(embedding)

                cursor.execute(
                    """
                    INSERT INTO embeddings (id, user_id, analysis_id, source_type, source_id, content_hash, embedding, metadata_json)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (new_id, user_id, analysis_id, source_type, source_id, content_hash, emb_val, meta_str)
                )
            else:
                emb_val = json.dumps(embedding)
                cursor.execute(
                    """
                    INSERT INTO embeddings (id, user_id, analysis_id, source_type, source_id, content_hash, embedding, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (new_id, user_id, analysis_id, source_type, source_id, content_hash, emb_val, meta_str)
                )
            conn.commit()
        except Exception as e:
            print(f"[DATABASE] Error saving embedding: {e}")
        finally:
            conn.close()

    def create_announcement(self, title: str, content: str, start_time: str, end_time: str, target_type: str = 'all', target_users: Optional[str] = None, announcement_type: str = 'top', show_behavior: str = 'once') -> str:
        conn = self.get_connection()
        cursor = conn.cursor()
        from uuid import uuid4
        new_id = str(uuid4())
        try:
            cursor.execute(
                """
                INSERT INTO announcements (id, title, content, start_time, end_time, target_type, target_users, announcement_type, show_behavior)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (new_id, title, content, start_time, end_time, target_type, target_users, announcement_type, show_behavior)
            )
            conn.commit()
            return new_id
        except Exception as e:
            print(f"[DATABASE] Error creating announcement: {e}")
            raise e
        finally:
            conn.close()

    def update_announcement(self, id: str, title: str, content: str, start_time: str, end_time: str, target_type: str = 'all', target_users: Optional[str] = None, announcement_type: str = 'top', show_behavior: str = 'once') -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE announcements
                SET title = ?, content = ?, start_time = ?, end_time = ?, target_type = ?, target_users = ?, announcement_type = ?, show_behavior = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (title, content, start_time, end_time, target_type, target_users, announcement_type, show_behavior, id)
            )
            conn.commit()
            return True
        except Exception as e:
            print(f"[DATABASE] Error updating announcement: {e}")
            raise e
        finally:
            conn.close()

    def delete_announcement(self, id: str) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "DELETE FROM announcements WHERE id = ?",
                (id,)
            )
            conn.commit()
            return True
        except Exception as e:
            print(f"[DATABASE] Error deleting announcement: {e}")
            raise e
        finally:
            conn.close()

    def get_announcements(self) -> List[dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT id, title, content, start_time, end_time, target_type, target_users, created_at, updated_at, announcement_type, show_behavior FROM announcements ORDER BY created_at DESC"
            )
            rows = cursor.fetchall()
            announcements = []
            for r in rows:
                announcements.append({
                     "id": str(r[0]),
                     "title": r[1],
                     "content": r[2],
                     "start_time": r[3].isoformat() if isinstance(r[3], datetime) else str(r[3]),
                     "end_time": r[4].isoformat() if isinstance(r[4], datetime) else str(r[4]),
                     "target_type": r[5],
                     "target_users": r[6],
                     "created_at": r[7].isoformat() if isinstance(r[7], datetime) else str(r[7]),
                     "updated_at": r[8].isoformat() if isinstance(r[8], datetime) else str(r[8]),
                     "announcement_type": r[9] if len(r) > 9 else 'top',
                     "show_behavior": r[10] if len(r) > 10 else 'once'
                })
            return announcements
        except Exception as e:
            print(f"[DATABASE] Error getting announcements: {e}")
            return []
        finally:
            conn.close()

    def get_active_announcements_for_user(self, username: str) -> List[dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT id, title, content, start_time, end_time, target_type, target_users, announcement_type, show_behavior FROM announcements"
            )
            rows = cursor.fetchall()
            active_announcements = []
            now = datetime.now()

            for r in rows:
                start_dt = safe_datetime(r[3])
                end_dt = safe_datetime(r[4])

                # Check time
                if start_dt and end_dt:
                    if not (start_dt <= now <= end_dt):
                        continue

                target_type = r[5]
                target_users_str = r[6] or ""

                # Check user targeting
                if target_type == 'specific':
                     user_list = [u.strip().lower() for u in target_users_str.split(",") if u.strip()]
                     if username.lower() not in user_list:
                         continue

                active_announcements.append({
                     "id": str(r[0]),
                     "title": r[1],
                     "content": r[2],
                     "start_time": start_dt.isoformat() if start_dt else str(r[3]),
                     "end_time": end_dt.isoformat() if end_dt else str(r[4]),
                     "target_type": target_type,
                     "target_users": target_users_str,
                     "announcement_type": r[7] if len(r) > 7 else 'top',
                     "show_behavior": r[8] if len(r) > 8 else 'once'
                })
            return active_announcements
        except Exception as e:
            print(f"[DATABASE] Error getting active announcements: {e}")
            return []
        finally:
            conn.close()

    def save_user_resume(
        self,
        user_id: Any,
        resume_id: str,
        file_name: str,
        file_size: int,
        file_type: str,
        parsed_resume: dict,
        *,
        content_hash: Optional[str] = None,
    ) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            user_key = str(user_id)
            parsed_json_str = json.dumps(parsed_resume)
            normalized_hash = str(
                content_hash
                or parsed_resume.get("contentHash")
                or (parsed_resume.get("file") or {}).get("contentHash")
                or hashlib.sha256(parsed_json_str.encode("utf-8")).hexdigest()
            )
            if self.is_postgres:
                cursor.execute("SELECT 1 FROM resumes WHERE id = %s AND user_id = %s", (resume_id, user_key))
                row = cursor.fetchone()
                if row is not None:
                    cursor.execute(
                        "UPDATE resumes SET file_name = %s, file_size = %s, file_type = %s, content_hash = %s, parsed_json = %s::jsonb, deleted_at = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = %s AND user_id = %s",
                        (file_name, file_size, file_type, normalized_hash, parsed_json_str, resume_id, user_key)
                    )
                else:
                    cursor.execute(
                        "SELECT id, version_no FROM resumes WHERE user_id = %s AND file_name = %s ORDER BY version_no DESC, created_at DESC LIMIT 1",
                        (user_key, file_name),
                    )
                    previous_version = cursor.fetchone()
                    parent_resume_id = previous_version[0] if previous_version else None
                    version_no = int(previous_version[1] or 0) + 1 if previous_version else 1
                    if parent_resume_id:
                        cursor.execute(
                            "UPDATE resumes SET is_current = FALSE, updated_at = CURRENT_TIMESTAMP WHERE id = %s AND user_id = %s",
                            (parent_resume_id, user_key),
                        )
                    cursor.execute(
                        "INSERT INTO resumes (id, user_id, file_name, file_size, file_type, content_hash, parent_resume_id, version_no, is_current, parsed_json) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s::jsonb)",
                        (resume_id, user_key, file_name, file_size, file_type, normalized_hash, parent_resume_id, version_no, parsed_json_str)
                    )
            else:
                cursor.execute("SELECT 1 FROM resumes WHERE id = ? AND user_id = ?", (resume_id, user_id))
                row = cursor.fetchone()
                if row is not None:
                    cursor.execute(
                        "UPDATE resumes SET file_name = ?, file_size = ?, file_type = ?, parsed_json = ?, deleted_at = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
                        (file_name, file_size, file_type, parsed_json_str, resume_id, user_id)
                    )
                else:
                    cursor.execute(
                        "INSERT INTO resumes (id, user_id, file_name, file_size, file_type, parsed_json) VALUES (?, ?, ?, ?, ?, ?)",
                        (resume_id, user_id, file_name, file_size, file_type, parsed_json_str)
                    )
            conn.commit()
        except Exception as e:
            print(f"[DATABASE] Error saving resume: {e}")
            raise e
        finally:
            conn.close()

    def find_user_resume_by_content_hash(self, user_id: Any, content_hash: str) -> Optional[dict]:
        """Return the immutable resume version with the same uploaded bytes for this user."""
        normalized_hash = str(content_hash or "").strip()
        if not normalized_hash:
            return None
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT parsed_json FROM resumes WHERE user_id = %s AND content_hash = %s ORDER BY updated_at DESC LIMIT 1",
                (str(user_id), normalized_hash),
            )
            row = cursor.fetchone()
            return safe_json_load(row[0]) if row else None
        finally:
            conn.close()

    def restore_user_resume_by_content_hash(self, user_id: Any, content_hash: str) -> Optional[dict]:
        """Restore a soft-deleted immutable version when identical bytes are uploaded again."""
        normalized_hash = str(content_hash or "").strip()
        if not normalized_hash:
            return None
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if self.is_postgres:
                cursor.execute(
                    "UPDATE resumes SET deleted_at = NULL, is_current = TRUE, updated_at = CURRENT_TIMESTAMP WHERE user_id = %s AND content_hash = %s",
                    (str(user_id), normalized_hash),
                )
            else:
                cursor.execute(
                    "UPDATE resumes SET deleted_at = NULL, is_current = 1, updated_at = CURRENT_TIMESTAMP WHERE user_id = ? AND content_hash = ?",
                    (user_id, normalized_hash),
                )
            conn.commit()
        finally:
            conn.close()
        return self.find_user_resume_by_content_hash(user_id, normalized_hash)

    def list_user_resumes(self, user_id: Any) -> List[dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if self.is_postgres:
                cursor.execute(
                    "SELECT id, file_name, file_size, file_type, content_hash, version_no, is_current, created_at, updated_at FROM resumes WHERE user_id = %s AND deleted_at IS NULL ORDER BY created_at DESC",
                    (str(user_id),)
                )
            else:
                cursor.execute(
                    "SELECT id, file_name, file_size, file_type, content_hash, version_no, is_current, created_at, updated_at FROM resumes WHERE user_id = ? AND deleted_at IS NULL ORDER BY created_at DESC",
                    (user_id,)
                )
            rows = cursor.fetchall()
            resumes = []
            for r in rows:
                resumes.append({
                    "id": str(r[0]),
                    "name": r[1],
                    "size": r[2],
                    "type": r[3],
                    "contentHash": r[4],
                    "versionNo": r[5],
                    "isCurrent": bool(r[6]),
                    "createdAt": safe_datetime(r[7]).isoformat() if r[7] else None,
                    "updatedAt": safe_datetime(r[8]).isoformat() if r[8] else None,
                })
            return resumes
        except Exception as e:
            print(f"[DATABASE] Error listing resumes: {e}")
            return []
        finally:
            conn.close()

    def get_user_resume(self, user_id: Any, resume_id: str) -> Optional[dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if self.is_postgres:
                cursor.execute(
                    "SELECT parsed_json FROM resumes WHERE id = %s AND user_id = %s",
                    (resume_id, str(user_id))
                )
            else:
                cursor.execute(
                    "SELECT parsed_json FROM resumes WHERE id = ? AND user_id = ?",
                    (resume_id, user_id)
                )
            row = cursor.fetchone()
            if row:
                return safe_json_load(row[0])
            return None
        except Exception as e:
            print(f"[DATABASE] Error getting resume: {e}")
            return None
        finally:
            conn.close()

    def delete_user_resume(self, user_id: Any, resume_id: str) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if self.is_postgres:
                cursor.execute(
                    "UPDATE resumes SET deleted_at = CURRENT_TIMESTAMP, is_current = FALSE, updated_at = CURRENT_TIMESTAMP WHERE id = %s AND user_id = %s",
                    (resume_id, str(user_id))
                )
            else:
                cursor.execute(
                    "UPDATE resumes SET deleted_at = CURRENT_TIMESTAMP, is_current = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
                    (resume_id, user_id)
                )
            conn.commit()
            return True
        except Exception as e:
            print(f"[DATABASE] Error deleting resume: {e}")
            return False
        finally:
            conn.close()
