import json
import os
import sqlite3
from datetime import datetime
from typing import Any, List, Optional, Tuple

from auth import hash_password, normalize_username, verify_password_hash
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


class DatabaseCursorWrapper:
    def __init__(self, cursor, is_postgres: bool):
        self._cursor = cursor
        self._is_postgres = is_postgres
        self._lastrowid = None

    def execute(self, query: str, params: tuple = ()):
        if self._is_postgres:
            query = query.replace("?", "%s")
            # Also translate common SQLite-specific table creation keywords
            if "CREATE TABLE" in query.upper():
                query = query.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
            is_insert = query.strip().upper().startswith("INSERT")
            if is_insert and "RETURNING" not in query.upper():
                q = query.strip()
                if q.endswith(";"):
                    q = q[:-1]
                query = f"{q} RETURNING id"
                self._cursor.execute(query, params)
                res = self._cursor.fetchone()
                self._lastrowid = res[0] if res else None
                return self
        
        self._cursor.execute(query, params)
        if not self._is_postgres:
            self._lastrowid = self._cursor.lastrowid
        return self

    @property
    def lastrowid(self):
        if self._is_postgres:
            return self._lastrowid
        return self._cursor.lastrowid

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
        self._conn = conn
        self._is_postgres = is_postgres

    def cursor(self):
        return DatabaseCursorWrapper(self._conn.cursor(), self._is_postgres)

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
    def __init__(self, db_path: str = Config.DB_PATH):
        self.db_path = db_path
        db_url = os.getenv("DATABASE_URL")
        self.is_postgres = bool(db_url and (db_url.startswith("postgresql://") or db_url.startswith("postgres://")))
        self.init_db()

    def get_connection(self):
        db_url = os.getenv("DATABASE_URL")
        if db_url and (db_url.startswith("postgresql://") or db_url.startswith("postgres://")):
            import psycopg2
            conn = psycopg2.connect(db_url)
            return DatabaseConnectionWrapper(conn, True)
        else:
            conn = sqlite3.connect(self.db_path)
            return DatabaseConnectionWrapper(conn, False)

    @classmethod
    def for_user(cls, user_id: int) -> "Database":
        return cls(Config.DB_PATH)

    def _column_exists(self, cursor, table_name: str, column_name: str) -> bool:
        if self.is_postgres:
            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT 1 
                    FROM information_schema.columns 
                    WHERE table_name = %s AND column_name = %s
                )
                """,
                (table_name.lower(), column_name.lower()),
            )
            return bool(cursor.fetchone()[0])
        else:
            columns = {
                row[1].lower()
                for row in cursor.execute(f"PRAGMA table_info({table_name})").fetchall()
            }
            return column_name.lower() in columns

    def init_db(self):
        conn = self.get_connection()
        cursor = conn.cursor()

        if self.is_postgres:
            # 1. Enable extensions
            try:
                cursor.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")
            except Exception:
                pass
            
            has_pgvector = False
            try:
                cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                has_pgvector = True
            except Exception:
                pass

            # 2. Create users table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
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
                    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    username VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            # 4. Create analysis_records table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_records (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
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
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    status VARCHAR(50) NOT NULL,
                    input_json JSONB NOT NULL,
                    failed_step VARCHAR(255),
                    error_message TEXT,
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
                    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
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
                    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
                    provider VARCHAR(50) NOT NULL,
                    model_id VARCHAR(255) NOT NULL,
                    display_name VARCHAR(255),
                    encrypted_api_key TEXT,
                    is_server_managed BOOLEAN NOT NULL DEFAULT FALSE,
                    enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    config_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            if not self._column_exists(cursor, "model_configs", "config_json"):
                cursor.execute("ALTER TABLE model_configs ADD COLUMN config_json TEXT")

            # 8. Create embeddings table
            embedding_type = "vector" if has_pgvector else "JSONB"
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS embeddings (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    analysis_id UUID REFERENCES analysis_records(id) ON DELETE CASCADE,
                    source_type VARCHAR(50) NOT NULL,
                    source_id VARCHAR(255),
                    content_hash VARCHAR(255),
                    embedding {embedding_type},
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
                    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
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
                    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
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
                    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
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
                    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
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
                    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
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
                    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
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
                    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
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
                    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
                    document_id INTEGER REFERENCES knowledge_document(id) ON DELETE CASCADE,
                    chunk_index INTEGER,
                    chunk_text TEXT,
                    token_count INTEGER,
                    metadata_json TEXT,
                    created_at TEXT
                );
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_workflow_log (
                    id SERIAL PRIMARY KEY,
                    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
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
                    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
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
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_analysis_records_user_created ON analysis_records(user_id, created_at DESC);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_drafts_user_updated ON drafts(user_id, updated_at DESC);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_settings_user ON user_settings(user_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_model_configs_user_provider ON model_configs(user_id, provider);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_embeddings_user_analysis ON embeddings(user_id, analysis_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_embeddings_user_hash ON embeddings(user_id, content_hash);")
            
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_jd_records_user_created ON jd_records(user_id, created_at);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_analysis_report_user_created ON analysis_report(user_id, created_at);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_analysis_task_user_updated ON analysis_task(user_id, updated_at);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_document_user ON knowledge_document(user_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_chunk_user_doc ON knowledge_chunk(user_id, document_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_job_postings_user ON job_postings(user_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_fit_exam_attempts_user ON fit_exam_attempts(user_id);")

            # 11. Sessions table for persistent authentication
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    token VARCHAR(64) PRIMARY KEY,
                    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP NOT NULL
                );
                """
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);")

        else:
            # SQLite setup (keep existing)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS registered_devices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_signature TEXT NOT NULL UNIQUE,
                    user_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS jd_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    jd_text TEXT NOT NULL,
                    skills TEXT NOT NULL,
                    difficulty TEXT NOT NULL,
                    job_summary TEXT NOT NULL,
                    personal_decision_json TEXT,
                    display_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS course_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    skill TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    view_count INTEGER NOT NULL,
                    favorite_count INTEGER NOT NULL,
                    like_count INTEGER NOT NULL,
                    coin_count INTEGER DEFAULT 0,
                    publish_date TEXT NOT NULL,
                    uploader TEXT NOT NULL,
                    rank_score REAL NOT NULL,
                    jd_record_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (jd_record_id) REFERENCES jd_records(id)
                )
                """
            )

            if not self._column_exists(cursor, "jd_records", "display_name"):
                cursor.execute("ALTER TABLE jd_records ADD COLUMN display_name TEXT")
            if not self._column_exists(cursor, "jd_records", "user_id"):
                cursor.execute("ALTER TABLE jd_records ADD COLUMN user_id INTEGER")
            if not self._column_exists(cursor, "jd_records", "personal_decision_json"):
                cursor.execute("ALTER TABLE jd_records ADD COLUMN personal_decision_json TEXT")

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS job_postings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    title TEXT NOT NULL,
                    company TEXT NOT NULL DEFAULT '',
                    region TEXT NOT NULL DEFAULT '',
                    latitude REAL,
                    longitude REAL,
                    transit_minutes INTEGER,
                    salary_monthly_k REAL NOT NULL,
                    jd_record_id INTEGER,
                    source_url TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
                """
            )

            if not self._column_exists(cursor, "job_postings", "user_id"):
                cursor.execute("ALTER TABLE job_postings ADD COLUMN user_id INTEGER")

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS salary_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_posting_id INTEGER NOT NULL,
                    observed_at TIMESTAMP NOT NULL,
                    salary_monthly_k REAL NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY (job_posting_id) REFERENCES job_postings(id)
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS fit_exam_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    jd_record_id INTEGER,
                    major_profile TEXT NOT NULL DEFAULT '',
                    paper_json TEXT NOT NULL,
                    answers_json TEXT NOT NULL,
                    score REAL NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (jd_record_id) REFERENCES jd_records(id),
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
                """
            )

            if not self._column_exists(cursor, "fit_exam_attempts", "user_id"):
                cursor.execute("ALTER TABLE fit_exam_attempts ADD COLUMN user_id INTEGER")

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_task (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    task_id TEXT UNIQUE NOT NULL,
                    jd_id INTEGER,
                    status TEXT,
                    enable_rag INTEGER,
                    enable_verification INTEGER,
                    enable_hallucination_check INTEGER,
                    enable_rewrite INTEGER,
                    error_message TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_report (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    task_id TEXT NOT NULL,
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
                    hallucination_risk TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS claim_check_result (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    task_id TEXT NOT NULL,
                    claim_id TEXT,
                    claim_text TEXT,
                    claim_type TEXT,
                    check_status TEXT,
                    confidence_score REAL,
                    evidence_count INTEGER,
                    reason TEXT,
                    evidence_json TEXT,
                    created_at TEXT
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_document (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    title TEXT,
                    file_name TEXT,
                    file_type TEXT,
                    source_type TEXT,
                    raw_text TEXT,
                    summary TEXT,
                    chunk_count INTEGER,
                    status TEXT,
                    error_message TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_chunk (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    document_id INTEGER,
                    chunk_index INTEGER,
                    chunk_text TEXT,
                    token_count INTEGER,
                    metadata_json TEXT,
                    created_at TEXT,
                    FOREIGN KEY (document_id) REFERENCES knowledge_document(id)
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_workflow_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    task_id TEXT NOT NULL,
                    node_name TEXT,
                    status TEXT,
                    duration_ms INTEGER,
                    input_summary TEXT,
                    output_summary TEXT,
                    error_message TEXT,
                    created_at TEXT
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_quality_evaluation (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    task_id TEXT NOT NULL,
                    final_quality_score REAL,
                    quality_grade TEXT,
                    quality_gate_status TEXT,
                    evidence_coverage_score REAL,
                    hallucination_risk_score REAL,
                    citation_completeness_score REAL,
                    resume_honesty_score REAL,
                    match_score_reasonableness REAL,
                    issues_json TEXT,
                    summary TEXT,
                    created_at TEXT
                )
                """
            )

            # Create indexes for performance and scoping
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_jd_records_user_created ON jd_records(user_id, created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_analysis_report_user_created ON analysis_report(user_id, created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_analysis_task_user_updated ON analysis_task(user_id, updated_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_document_user ON knowledge_document(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_chunk_user_doc ON knowledge_chunk(user_id, document_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_job_postings_user ON job_postings(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_fit_exam_attempts_user ON fit_exam_attempts(user_id)")

            # Create standard table setup for SQLite new columns
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS drafts (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER,
                    status TEXT NOT NULL,
                    input_json TEXT NOT NULL,
                    failed_step TEXT,
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS user_settings (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL UNIQUE,
                    settings_json TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS model_configs (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER,
                    provider TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    display_name TEXT,
                    encrypted_api_key TEXT,
                    is_server_managed INTEGER NOT NULL DEFAULT 0,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    config_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            )
            if not self._column_exists(cursor, "model_configs", "config_json"):
                cursor.execute("ALTER TABLE model_configs ADD COLUMN config_json TEXT")
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS embeddings (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    analysis_id TEXT,
                    source_type TEXT NOT NULL,
                    source_id TEXT,
                    content_hash TEXT,
                    embedding TEXT,
                    metadata_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_records (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    input_json TEXT NOT NULL DEFAULT '{}',
                    parsed_jd_json TEXT,
                    parsed_resume_json TEXT,
                    requirement_matches_json TEXT,
                    hard_constraint_results_json TEXT,
                    result_json TEXT,
                    failed_step TEXT,
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            )

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_analysis_records_user ON analysis_records(user_id, created_at DESC);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);")

        conn.commit()
        conn.close()


    def backfill_user_databases(self):
        """Scans for user_data/user_* databases and migrates them into the main database."""
        import os
        import sqlite3
        import re
        
        user_db_dir = Config.USER_DB_DIR
        if not os.path.isdir(user_db_dir):
            return
            
        # Get all subdirectories matching user_(\d+)
        for name in os.listdir(user_db_dir):
            dir_path = os.path.join(user_db_dir, name)
            if not os.path.isdir(dir_path):
                continue
            m = re.match(r"^user_(\d+)$", name)
            if not m:
                continue
            
            user_id = int(m.group(1))
            old_db_path = os.path.join(dir_path, "career_path.db")
            if not os.path.isfile(old_db_path):
                continue
                
            # If already migrated (marked by career_path.db.migrated)
            migrated_mark = old_db_path + ".migrated"
            if os.path.isfile(migrated_mark):
                continue
                
            print(f"[MIGRATION] Starting database migration for user_id={user_id} from {old_db_path}")
            
            try:
                # Open connection to the source database
                src_conn = sqlite3.connect(old_db_path)
                src_cursor = src_conn.cursor()
                
                # Check if tables exist in the source database
                def table_exists(tbl_name):
                    res = src_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tbl_name,)).fetchone()
                    return res is not None
                
                dest_conn = self.get_connection()
                dest_cursor = dest_conn.cursor()
                
                dest_cursor.execute("BEGIN TRANSACTION")
                
                # 1. jd_records
                jd_mapping = {}
                if table_exists("jd_records"):
                    rows = src_cursor.execute(
                        "SELECT id, jd_text, skills, difficulty, job_summary, personal_decision_json, display_name, created_at FROM jd_records"
                    ).fetchall()
                    for r in rows:
                        old_id, jd_text, skills, difficulty, job_summary, personal_decision_json, display_name, created_at = r
                        dest_cursor.execute(
                            """
                            INSERT INTO jd_records (user_id, jd_text, skills, difficulty, job_summary, personal_decision_json, display_name, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (user_id, jd_text, skills, difficulty, job_summary, personal_decision_json, display_name, created_at)
                        )
                        jd_mapping[old_id] = dest_cursor.lastrowid
                
                # 2. course_records
                if table_exists("course_records") and jd_mapping:
                    rows = src_cursor.execute(
                        "SELECT skill, title, url, view_count, favorite_count, like_count, coin_count, publish_date, uploader, rank_score, jd_record_id, created_at FROM course_records"
                    ).fetchall()
                    for r in rows:
                        skill, title, url, view_count, favorite_count, like_count, coin_count, publish_date, uploader, rank_score, old_jd_id, created_at = r
                        new_jd_id = jd_mapping.get(old_jd_id)
                        if new_jd_id:
                            dest_cursor.execute(
                                """
                                INSERT INTO course_records (skill, title, url, view_count, favorite_count, like_count, coin_count, publish_date, uploader, rank_score, jd_record_id, created_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (skill, title, url, view_count, favorite_count, like_count, coin_count, publish_date, uploader, rank_score, new_jd_id, created_at)
                            )
                
                # 3. job_postings
                job_mapping = {}
                if table_exists("job_postings"):
                    rows = src_cursor.execute(
                        "SELECT id, title, company, region, latitude, longitude, transit_minutes, salary_monthly_k, jd_record_id, source_url, created_at FROM job_postings"
                    ).fetchall()
                    for r in rows:
                        old_id, title, company, region, latitude, longitude, transit_minutes, salary_monthly_k, old_jd_id, source_url, created_at = r
                        new_jd_id = jd_mapping.get(old_jd_id) if old_jd_id else None
                        dest_cursor.execute(
                            """
                            INSERT INTO job_postings (user_id, title, company, region, latitude, longitude, transit_minutes, salary_monthly_k, jd_record_id, source_url, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (user_id, title, company, region, latitude, longitude, transit_minutes, salary_monthly_k, new_jd_id, source_url, created_at)
                        )
                        job_mapping[old_id] = dest_cursor.lastrowid
                        
                # 4. salary_snapshots
                if table_exists("salary_snapshots") and job_mapping:
                    rows = src_cursor.execute(
                        "SELECT job_posting_id, observed_at, salary_monthly_k, note FROM salary_snapshots"
                    ).fetchall()
                    for r in rows:
                        old_job_id, observed_at, salary_monthly_k, note = r
                        new_job_id = job_mapping.get(old_job_id)
                        if new_job_id:
                            dest_cursor.execute(
                                """
                                INSERT INTO salary_snapshots (job_posting_id, observed_at, salary_monthly_k, note)
                                VALUES (?, ?, ?, ?)
                                """,
                                (new_job_id, observed_at, salary_monthly_k, note)
                            )
                            
                # 5. fit_exam_attempts
                if table_exists("fit_exam_attempts"):
                    rows = src_cursor.execute(
                        "SELECT jd_record_id, major_profile, paper_json, answers_json, score, created_at FROM fit_exam_attempts"
                    ).fetchall()
                    for r in rows:
                        old_jd_id, major_profile, paper_json, answers_json, score, created_at = r
                        new_jd_id = jd_mapping.get(old_jd_id) if old_jd_id else None
                        dest_cursor.execute(
                            """
                            INSERT INTO fit_exam_attempts (user_id, jd_record_id, major_profile, paper_json, answers_json, score, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (user_id, new_jd_id, major_profile, paper_json, answers_json, score, created_at)
                        )
                        
                # 6. analysis_task
                if table_exists("analysis_task"):
                    rows = src_cursor.execute(
                        "SELECT task_id, jd_id, status, enable_rag, enable_verification, enable_hallucination_check, enable_rewrite, error_message, created_at, updated_at FROM analysis_task"
                    ).fetchall()
                    for r in rows:
                        task_id, old_jd_id, status, enable_rag, enable_verification, enable_hallucination_check, enable_rewrite, error_message, created_at, updated_at = r
                        new_jd_id = jd_mapping.get(old_jd_id) if old_jd_id else None
                        exists = dest_cursor.execute("SELECT 1 FROM analysis_task WHERE task_id = ?", (task_id,)).fetchone()
                        if not exists:
                            dest_cursor.execute(
                                """
                                INSERT INTO analysis_task (user_id, task_id, jd_id, status, enable_rag, enable_verification, enable_hallucination_check, enable_rewrite, error_message, created_at, updated_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (user_id, task_id, new_jd_id, status, enable_rag, enable_verification, enable_hallucination_check, enable_rewrite, error_message, created_at, updated_at)
                            )
                            
                # 7. analysis_report
                if table_exists("analysis_report"):
                    rows = src_cursor.execute(
                        "SELECT task_id, jd_text, resume_text, knowledge_texts, original_analysis_json, final_report_json, evidence_summary_json, hallucination_control_json, citations_json, credibility_score, evidence_coverage, hallucination_risk, created_at, updated_at FROM analysis_report"
                    ).fetchall()
                    for r in rows:
                        task_id, jd_text, resume_text, knowledge_texts, original_analysis_json, final_report_json, evidence_summary_json, hallucination_control_json, citations_json, credibility_score, evidence_coverage, hallucination_risk, created_at, updated_at = r
                        dest_cursor.execute(
                            """
                            INSERT INTO analysis_report (user_id, task_id, jd_text, resume_text, knowledge_texts, original_analysis_json, final_report_json, evidence_summary_json, hallucination_control_json, citations_json, credibility_score, evidence_coverage, hallucination_risk, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (user_id, task_id, jd_text, resume_text, knowledge_texts, original_analysis_json, final_report_json, evidence_summary_json, hallucination_control_json, citations_json, credibility_score, evidence_coverage, hallucination_risk, created_at, updated_at)
                        )
                        
                # 8. claim_check_result
                if table_exists("claim_check_result"):
                    rows = src_cursor.execute(
                        "SELECT task_id, claim_id, claim_text, claim_type, check_status, confidence_score, evidence_count, reason, evidence_json, created_at FROM claim_check_result"
                    ).fetchall()
                    for r in rows:
                        task_id, claim_id, claim_text, claim_type, check_status, confidence_score, evidence_count, reason, evidence_json, created_at = r
                        dest_cursor.execute(
                            """
                            INSERT INTO claim_check_result (user_id, task_id, claim_id, claim_text, claim_type, check_status, confidence_score, evidence_count, reason, evidence_json, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (user_id, task_id, claim_id, claim_text, claim_type, check_status, confidence_score, evidence_count, reason, evidence_json, created_at)
                        )
                        
                # 9. knowledge_document
                doc_mapping = {}
                if table_exists("knowledge_document"):
                    rows = src_cursor.execute(
                        "SELECT id, title, file_name, file_type, source_type, raw_text, summary, chunk_count, status, error_message, created_at, updated_at FROM knowledge_document"
                    ).fetchall()
                    for r in rows:
                        old_id, title, file_name, file_type, source_type, raw_text, summary, chunk_count, status, error_message, created_at, updated_at = r
                        dest_cursor.execute(
                            """
                            INSERT INTO knowledge_document (user_id, title, file_name, file_type, source_type, raw_text, summary, chunk_count, status, error_message, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (user_id, title, file_name, file_type, source_type, raw_text, summary, chunk_count, status, error_message, created_at, updated_at)
                        )
                        doc_mapping[old_id] = dest_cursor.lastrowid
                        
                # 10. knowledge_chunk
                if table_exists("knowledge_chunk") and doc_mapping:
                    rows = src_cursor.execute(
                        "SELECT document_id, chunk_index, chunk_text, token_count, metadata_json, created_at FROM knowledge_chunk"
                    ).fetchall()
                    for r in rows:
                        old_doc_id, chunk_index, chunk_text, token_count, metadata_json, created_at = r
                        new_doc_id = doc_mapping.get(old_doc_id)
                        if new_doc_id:
                            dest_cursor.execute(
                                """
                                INSERT INTO knowledge_chunk (user_id, document_id, chunk_index, chunk_text, token_count, metadata_json, created_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                                """,
                                (user_id, new_doc_id, chunk_index, chunk_text, token_count, metadata_json, created_at)
                            )
                            
                # 11. analysis_workflow_log
                if table_exists("analysis_workflow_log"):
                    rows = src_cursor.execute(
                        "SELECT task_id, node_name, status, duration_ms, input_summary, output_summary, error_message, created_at FROM analysis_workflow_log"
                    ).fetchall()
                    for r in rows:
                        task_id, node_name, status, duration_ms, input_summary, output_summary, error_message, created_at = r
                        dest_cursor.execute(
                            """
                            INSERT INTO analysis_workflow_log (user_id, task_id, node_name, status, duration_ms, input_summary, output_summary, error_message, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (user_id, task_id, node_name, status, duration_ms, input_summary, output_summary, error_message, created_at)
                        )
                        
                # 12. analysis_quality_evaluation
                if table_exists("analysis_quality_evaluation"):
                    rows = src_cursor.execute(
                        "SELECT task_id, final_quality_score, quality_grade, quality_gate_status, evidence_coverage_score, hallucination_risk_score, citation_completeness_score, resume_honesty_score, match_score_reasonableness, issues_json, summary, created_at FROM analysis_quality_evaluation"
                    ).fetchall()
                    for r in rows:
                        task_id, final_quality_score, quality_grade, quality_gate_status, evidence_coverage_score, hallucination_risk_score, citation_completeness_score, resume_honesty_score, match_score_reasonableness, issues_json, summary, created_at = r
                        dest_cursor.execute(
                            """
                            INSERT INTO analysis_quality_evaluation (user_id, task_id, final_quality_score, quality_grade, quality_gate_status, evidence_coverage_score, hallucination_risk_score, citation_completeness_score, resume_honesty_score, match_score_reasonableness, issues_json, summary, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (user_id, task_id, final_quality_score, quality_grade, quality_gate_status, evidence_coverage_score, hallucination_risk_score, citation_completeness_score, resume_honesty_score, match_score_reasonableness, issues_json, summary, created_at)
                        )
                
                dest_cursor.execute("COMMIT")
                dest_conn.close()
                src_conn.close()
                
                # Mark as successfully migrated by creating .migrated file
                with open(migrated_mark, "w") as f:
                    f.write(f"Migrated at {datetime.now().isoformat()}\n")
                
                print(f"[MIGRATION] Successfully migrated user_id={user_id}")
            except Exception as exc:
                print(f"[MIGRATION] ERROR migrating user_id={user_id}: {exc}")

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
        except sqlite3.IntegrityError as exc:
            raise ValueError("username_taken") from exc
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
            SELECT id, username, password_hash, created_at
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

        return User(id=row[0], username=row[1], created_at=datetime.fromisoformat(row[3]))

    def get_user_by_id(self, user_id: int) -> Optional[User]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, username, created_at
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        )
        row = cursor.fetchone()
        conn.close()
        if row is None:
            return None
        return User(id=row[0], username=row[1], created_at=datetime.fromisoformat(row[2]))

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
        cursor.execute("DELETE FROM registered_devices WHERE user_id = ?", (user_id,))
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
                skills=json.loads(row[3]),
                difficulty=row[4],
                job_summary=row[5],
                personal_decision=self._load_json(row[6], None),
            ),
            display_name=row[7],
            created_at=datetime.fromisoformat(row[8]),
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
            cursor.execute(
                """
                INSERT INTO knowledge_chunk (
                    user_id, document_id, chunk_index, chunk_text, token_count, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    document_id,
                    chunk_index,
                    text,
                    token_count,
                    self._dump_json(metadata),
                    now,
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
        cursor.execute(
            f"""
            SELECT c.id, c.user_id, c.document_id, c.chunk_index, c.chunk_text, c.token_count,
                   c.metadata_json, c.created_at, d.title, d.file_name, d.source_type
            FROM knowledge_chunk c
            JOIN knowledge_document d ON d.id = c.document_id
            WHERE c.document_id IN ({placeholders}) AND c.user_id = ?
            ORDER BY c.document_id ASC, c.chunk_index ASC
            """,
            params,
        )
        rows = cursor.fetchall()
        conn.close()
        return [
            {
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
            for row in rows
        ]

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

    def _load_json(self, value: Optional[str], default: Any) -> Any:
        if not value:
            return default
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return default

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
                    created_at=datetime.fromisoformat(row[11]),
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
                observed_at=datetime.fromisoformat(row[2]),
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
        """jd_record_id -> (score, time) 取该 JD 下最近一次测验得分。"""
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
            best[int(jd_id)] = (float(score), datetime.fromisoformat(created_at))
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
            raw = json.loads(row[4])
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
                    answers=list(json.loads(row[5] or "[]")),
                    score=float(row[6]),
                    created_at=datetime.fromisoformat(row[7]),
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
            cursor.execute("SELECT 1 FROM drafts WHERE id = ? AND user_id = ?", (draft_id, user_id))
            exists = cursor.fetchone() is not None
        else:
            exists = False

        if exists:
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
                    VALUES (?, ?, ?, ?, ?, ?, ?)
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
        cursor.execute("SELECT id, user_id, status, input_json, failed_step, error_message, created_at, updated_at FROM drafts WHERE id = ? AND user_id = ?", (draft_id, user_id))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        return {
            "id": row[0],
            "user_id": row[1],
            "status": row[2],
            "input_json": json.loads(row[3]) if row[3] else {},
            "failed_step": row[4],
            "error_message": row[5],
            "created_at": row[6],
            "updated_at": row[7]
        }

    def list_drafts(self, user_id: Any) -> List[dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, user_id, status, input_json, failed_step, error_message, created_at, updated_at FROM drafts WHERE user_id = ? ORDER BY updated_at DESC", (user_id,))
        rows = cursor.fetchall()
        conn.close()
        return [
            {
                "id": r[0],
                "user_id": r[1],
                "status": r[2],
                "input_json": json.loads(r[3]) if r[3] else {},
                "failed_step": r[4],
                "error_message": r[5],
                "created_at": r[6],
                "updated_at": r[7]
            } for r in rows
        ]

    def delete_draft(self, user_id: Any, draft_id: Any) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM drafts WHERE id = ? AND user_id = ?", (draft_id, user_id))
        conn.commit()
        conn.close()
        return True

    def clear_converted_drafts(self, user_id: Any) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM drafts WHERE user_id = ? AND status = 'converted_to_history'", (user_id,))
        conn.commit()
        conn.close()

    # USER SETTINGS CRUD methods
    def save_settings(self, user_id: Any, settings_json: dict) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        
        cursor.execute("SELECT 1 FROM user_settings WHERE user_id = ?", (user_id,))
        exists = cursor.fetchone() is not None
        
        if exists:
            cursor.execute(
                "UPDATE user_settings SET settings_json = ?, updated_at = ? WHERE user_id = ?",
                (json.dumps(settings_json, ensure_ascii=False), now, user_id)
            )
        else:
            from uuid import uuid4
            new_id = str(uuid4())
            if self.is_postgres:
                cursor.execute(
                    "INSERT INTO user_settings (user_id, settings_json, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    (user_id, json.dumps(settings_json, ensure_ascii=False), now, now)
                )
            else:
                cursor.execute(
                    "INSERT INTO user_settings (id, user_id, settings_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (new_id, user_id, json.dumps(settings_json, ensure_ascii=False), now, now)
                )
        conn.commit()
        conn.close()

    def get_settings(self, user_id: Any) -> dict:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT settings_json FROM user_settings WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return {}
        return json.loads(row[0]) if row[0] else {}

    # MODEL CONFIGS CRUD methods
    @staticmethod
    def _is_api_key_placeholder(api_key: Optional[str]) -> bool:
        if not api_key:
            return True
        return api_key.strip() in {
            "",
            "••••••••",
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
            
        cfg_json_str = config_json if isinstance(config_json, str) else (json.dumps(config_json, ensure_ascii=False) if config_json else None)
        
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
        
        if row:
            existing_id = row[0]
            if encrypted_key:
                cursor.execute(
                    """
                    UPDATE model_configs 
                    SET display_name = ?, encrypted_api_key = ?, is_server_managed = ?, enabled = ?, config_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (display_name, encrypted_key, 1 if is_server_managed else 0, 1 if enabled else 0, cfg_json_str, now, existing_id)
                )
            else:
                cursor.execute(
                    """
                    UPDATE model_configs 
                    SET display_name = ?, is_server_managed = ?, enabled = ?, config_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (display_name, 1 if is_server_managed else 0, 1 if enabled else 0, cfg_json_str, now, existing_id)
                )
            ret_id = existing_id
        else:
            if self.is_postgres:
                cursor.execute(
                    """
                    INSERT INTO model_configs (id, user_id, provider, model_id, display_name, encrypted_api_key, is_server_managed, enabled, config_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (new_id, user_id, provider, model_id, display_name, encrypted_key, is_server_managed, enabled, cfg_json_str, now, now)
                )
                ret_id = new_id
            else:
                cursor.execute(
                    """
                    INSERT INTO model_configs (id, user_id, provider, model_id, display_name, encrypted_api_key, is_server_managed, enabled, config_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (new_id, user_id, provider, model_id, display_name, encrypted_key, 1 if is_server_managed else 0, 1 if enabled else 0, cfg_json_str, now, now)
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
            extra = json.loads(r[8]) if r[8] else {}
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
            item["name"] = r[4] or extra.get("name", "")
            item["enabled"] = bool(r[7])
            item["apiKey"] = "••••••••" if r[5] else ""
            configs.append(item)
        return configs

    def get_model_api_key(self, user_id: Optional[Any], provider: str, model_id: str) -> str:
        conn = self.get_connection()
        cursor = conn.cursor()
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
        row = cursor.fetchone()
        conn.close()
        if not row or not row[0]:
            return ""

        api_key = self.decrypt_api_key(row[0]).strip()
        return "" if self._is_api_key_placeholder(api_key) else api_key

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

        if self.is_postgres:
            cursor.execute(
                """
                INSERT INTO analysis_records (id, user_id, status, input_json, result_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
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
        cursor.execute("DELETE FROM analysis_records WHERE id = ? AND user_id = ?", (record_id, user_id))
        deleted = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return deleted

    def update_analysis_record_status(self, user_id: Any, record_id: Any, status: str) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
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
            cursor.execute("SELECT 1 FROM users WHERE username = ?", ("admin@example.com",))
            if cursor.fetchone() is None:
                hashed = hash_password("ChangeMe123!")
                now = datetime.now().isoformat()
                if self.is_postgres:
                    cursor.execute(
                        "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                        ("admin@example.com", hashed, now)
                    )
                else:
                    from uuid import uuid4
                    cursor.execute(
                        "INSERT INTO users (id, username, password_hash, created_at) VALUES (?, ?, ?, ?)",
                        (1, "admin@example.com", hashed, now)
                    )
                conn.commit()
                print("【安全提示】本地默认账号仅用于开发，请在生产环境中修改密码。")
        except Exception as e:
            print(f"Error seeding user: {e}")
        finally:
            conn.close()
