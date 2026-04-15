import sqlite3
import json
from typing import List, Optional
from datetime import datetime
from config import Config
from models import JobAnalysis, BilibiliCourse, JDRecord, CourseRecord

class Database:
    def __init__(self, db_path: str = Config.DB_PATH):
        self.db_path = db_path
        self.init_db()
    
    def get_connection(self):
        return sqlite3.connect(self.db_path)
    
    def init_db(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS jd_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                jd_text TEXT NOT NULL,
                skills TEXT NOT NULL,
                difficulty TEXT NOT NULL,
                job_summary TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
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
        ''')
        
        conn.commit()
        conn.close()
    
    def save_jd_record(self, jd_text: str, analysis: JobAnalysis) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO jd_records (jd_text, skills, difficulty, job_summary, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            jd_text,
            json.dumps(analysis.skills, ensure_ascii=False),
            analysis.difficulty,
            analysis.job_summary,
            datetime.now().isoformat()
        ))
        
        jd_record_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return jd_record_id
    
    def save_courses(self, jd_record_id: int, courses: List[BilibiliCourse]):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        for course in courses:
            cursor.execute('''
                INSERT INTO course_records (
                    skill, title, url, view_count, favorite_count, like_count, 
                    coin_count, publish_date, uploader, rank_score, jd_record_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
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
                datetime.now().isoformat()
            ))
        
        conn.commit()
        conn.close()
    
    def get_jd_records(self, limit: int = 10) -> List[JDRecord]:
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, jd_text, skills, difficulty, job_summary, created_at
            FROM jd_records ORDER BY created_at DESC LIMIT ?
        ''', (limit,))
        
        records = []
        for row in cursor.fetchall():
            records.append(JDRecord(
                id=row[0],
                jd_text=row[1],
                analysis=JobAnalysis(
                    skills=json.loads(row[2]),
                    difficulty=row[3],
                    job_summary=row[4]
                ),
                created_at=datetime.fromisoformat(row[5])
            ))
        
        conn.close()
        return records
    
    def get_courses_by_jd_id(self, jd_record_id: int) -> List[BilibiliCourse]:
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT skill, title, url, view_count, favorite_count, like_count, 
                   coin_count, publish_date, uploader, rank_score
            FROM course_records WHERE jd_record_id = ? ORDER BY skill, rank_score DESC
        ''', (jd_record_id,))
        
        courses = []
        for row in cursor.fetchall():
            courses.append(BilibiliCourse(
                skill=row[0],
                title=row[1],
                url=row[2],
                view_count=row[3],
                favorite_count=row[4],
                like_count=row[5],
                coin_count=row[6],
                publish_date=row[7],
                uploader=row[8],
                rank_score=row[9]
            ))
        
        conn.close()
        return courses
