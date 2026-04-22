import json
import sqlite3
from datetime import datetime
from typing import List, Optional

from config import Config
from models import BilibiliCourse, JDRecord, JobAnalysis


class Database:
    def __init__(self, db_path: str = Config.DB_PATH):
        self.db_path = db_path
        self.init_db()

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def init_db(self):
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS jd_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                jd_text TEXT NOT NULL,
                skills TEXT NOT NULL,
                difficulty TEXT NOT NULL,
                job_summary TEXT NOT NULL,
                display_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

        conn.commit()
        conn.close()

    def save_jd_record(self, jd_text: str, analysis: JobAnalysis) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        jd_record_id = self.get_next_available_jd_record_id(cursor)
        cursor.execute(
            """
            INSERT INTO jd_records (id, jd_text, skills, difficulty, job_summary, display_name, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                jd_record_id,
                jd_text,
                json.dumps(analysis.skills, ensure_ascii=False),
                analysis.difficulty,
                analysis.job_summary,
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

    def rename_jd_record(self, jd_record_id: int, display_name: Optional[str]) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE jd_records SET display_name = ? WHERE id = ?",
            (display_name, jd_record_id),
        )
        conn.commit()
        conn.close()

    def delete_jd_record(self, jd_record_id: int) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM course_records WHERE jd_record_id = ?", (jd_record_id,))
        cursor.execute("DELETE FROM jd_records WHERE id = ?", (jd_record_id,))
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
            jd_text=row[1],
            analysis=JobAnalysis(
                skills=json.loads(row[2]),
                difficulty=row[3],
                job_summary=row[4],
            ),
            display_name=row[5],
            created_at=datetime.fromisoformat(row[6]),
        )

    def get_jd_record_by_id(self, jd_record_id: int) -> Optional[JDRecord]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, jd_text, skills, difficulty, job_summary, display_name, created_at
            FROM jd_records WHERE id = ?
            """,
            (jd_record_id,),
        )
        row = cursor.fetchone()
        conn.close()
        if row is None:
            return None
        return self.build_jd_record(row)

    def get_jd_records(self, limit: int = 10) -> List[JDRecord]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, jd_text, skills, difficulty, job_summary, display_name, created_at
            FROM jd_records
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
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
