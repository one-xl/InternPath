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


class Database:
    def __init__(self, db_path: str = Config.DB_PATH):
        self.db_path = db_path
        self.init_db()

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    @classmethod
    def for_user(cls, user_id: int) -> "Database":
        os.makedirs(Config.USER_DB_DIR, exist_ok=True)
        user_dir = os.path.join(Config.USER_DB_DIR, f"user_{int(user_id)}")
        os.makedirs(user_dir, exist_ok=True)
        return cls(os.path.join(user_dir, "career_path.db"))

    def init_db(self):
        conn = self.get_connection()
        cursor = conn.cursor()

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

        existing_columns = {
            row[1]
            for row in cursor.execute("PRAGMA table_info(jd_records)").fetchall()
        }
        if "display_name" not in existing_columns:
            cursor.execute("ALTER TABLE jd_records ADD COLUMN display_name TEXT")
        if "user_id" not in existing_columns:
            cursor.execute("ALTER TABLE jd_records ADD COLUMN user_id INTEGER")
        if "personal_decision_json" not in existing_columns:
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

        job_columns = {
            row[1]
            for row in cursor.execute("PRAGMA table_info(job_postings)").fetchall()
        }
        if "user_id" not in job_columns:
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

        attempt_columns = {
            row[1]
            for row in cursor.execute("PRAGMA table_info(fit_exam_attempts)").fetchall()
        }
        if "user_id" not in attempt_columns:
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

    def save_jd_record(self, user_id: int, jd_text: str, analysis: JobAnalysis) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
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

    def save_courses(self, jd_record_id: int, courses: List[BilibiliCourse], *, replace: bool = False):
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

    def get_courses_by_jd_id(self, jd_record_id: int) -> List[BilibiliCourse]:
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
            WHERE task_id = ?
            """,
            (status, error_message, datetime.now().isoformat(), task_id),
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
        cursor.execute("DELETE FROM claim_check_result WHERE task_id = ?", (task_id,))
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
                FROM analysis_report WHERE id = ?
                """,
                (report_id,),
            )
        else:
            cursor.execute(
                """
                SELECT id, user_id, task_id, jd_text, resume_text, knowledge_texts,
                       original_analysis_json, final_report_json, evidence_summary_json,
                       hallucination_control_json, citations_json, credibility_score,
                       evidence_coverage, hallucination_risk, created_at, updated_at
                FROM analysis_report WHERE task_id = ?
                ORDER BY created_at DESC, id DESC LIMIT 1
                """,
                (task_id,),
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

    def get_claim_check_results(self, task_id: str) -> List[dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, user_id, task_id, claim_id, claim_text, claim_type, check_status,
                   confidence_score, evidence_count, reason, evidence_json, created_at
            FROM claim_check_result
            WHERE task_id = ?
            ORDER BY id ASC
            """,
            (task_id,),
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
        cursor.execute("DELETE FROM analysis_workflow_log WHERE task_id = ?", (task_id,))
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

    def get_workflow_logs(self, task_id: str) -> List[dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, user_id, task_id, node_name, status, duration_ms,
                   input_summary, output_summary, error_message, created_at
            FROM analysis_workflow_log
            WHERE task_id = ?
            ORDER BY id ASC
            """,
            (task_id,),
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
        cursor.execute("DELETE FROM analysis_quality_evaluation WHERE task_id = ?", (task_id,))
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

    def get_quality_evaluation(self, task_id: str) -> Optional[dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, user_id, task_id, final_quality_score, quality_grade, quality_gate_status,
                   evidence_coverage_score, hallucination_risk_score, citation_completeness_score,
                   resume_honesty_score, match_score_reasonableness, issues_json, summary, created_at
            FROM analysis_quality_evaluation
            WHERE task_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (task_id,),
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
            WHERE id = ?
            """,
            (status, error_message, chunk_count, datetime.now().isoformat(), document_id),
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
        document_id: int,
        user_id: Optional[int] = None,
    ) -> Optional[dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        if user_id is None:
            cursor.execute(
                """
                SELECT id, user_id, title, file_name, file_type, source_type, raw_text, summary,
                       chunk_count, status, error_message, created_at, updated_at
                FROM knowledge_document
                WHERE id = ?
                """,
                (document_id,),
            )
        else:
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
        document_ids: List[int],
        user_id: Optional[int] = None,
    ) -> List[dict]:
        if not document_ids:
            return []
        placeholders = ",".join("?" for _ in document_ids)
        params: list[Any] = [int(doc_id) for doc_id in document_ids]
        user_clause = ""
        if user_id is not None:
            user_clause = " AND c.user_id = ?"
            params.append(user_id)
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT c.id, c.user_id, c.document_id, c.chunk_index, c.chunk_text, c.token_count,
                   c.metadata_json, c.created_at, d.title, d.file_name, d.source_type
            FROM knowledge_chunk c
            JOIN knowledge_document d ON d.id = c.document_id
            WHERE c.document_id IN ({placeholders}){user_clause}
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
        document_id: int,
        user_id: Optional[int] = None,
    ) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        if user_id is None:
            cursor.execute("DELETE FROM knowledge_chunk WHERE document_id = ?", (document_id,))
            cursor.execute("DELETE FROM knowledge_document WHERE id = ?", (document_id,))
        else:
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

    def update_job_posting_salary(self, job_posting_id: int, salary_monthly_k: float) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE job_postings SET salary_monthly_k = ? WHERE id = ?",
            (salary_monthly_k, job_posting_id),
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
        job_posting_id: int,
        salary_monthly_k: float,
        *,
        note: str = "",
        observed_at: Optional[datetime] = None,
    ) -> int:
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

    def get_salary_snapshots(self, job_posting_id: int) -> List[SalarySnapshot]:
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
