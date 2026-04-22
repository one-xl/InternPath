from typing import List, Literal, Optional, Tuple, Union

from ai_analyzer import AIAnalyzer
from crawler_api import BilibiliAPICrawlerSync
from database import Database
from models import BilibiliCourse, ExamOptionsForPractice, JDRecord, JobAnalysis
from practice_app import PracticeAppInvoker
from ranker import CourseRanker


class CareerPathAIService:
    def __init__(self):
        self.ai_analyzer = AIAnalyzer()
        self.crawler = BilibiliAPICrawlerSync()
        self.ranker = CourseRanker()
        self.db = Database()
        self.practice_invoker = PracticeAppInvoker()

    def extract_skills(self, jd_text: str) -> JobAnalysis:
        return self.ai_analyzer.extract_skills(jd_text)

    def search_courses(self, skills: List[str]) -> List[BilibiliCourse]:
        all_courses = []
        for skill in skills:
            courses = self.crawler.search_skill(skill)
            all_courses.extend(courses)
        return self.ranker.rank_by_skill(all_courses)

    def analyze_jd(self, jd_text: str) -> Tuple[JobAnalysis, List[BilibiliCourse]]:
        analysis = self.extract_skills(jd_text)
        courses = self.search_courses(analysis.skills)
        jd_record_id = self.db.save_jd_record(jd_text, analysis)
        self.db.save_courses(jd_record_id, courses)
        return analysis, courses

    def sync_to_practice_app(
        self,
        skills: List[str],
        practice_mode: Literal["direct", "ai_recommend"] = "direct",
        *,
        job_summary: str = "",
        difficulty: str = "",
        exam_options: Optional[Union[ExamOptionsForPractice, dict]] = None,
        auto_proceed: bool = False,
    ) -> bool:
        return self.practice_invoker.invoke_practice_app(
            skills,
            practice_mode,
            job_summary=job_summary,
            difficulty=difficulty,
            exam_options=exam_options,
            auto_proceed=auto_proceed,
        )

    def build_practice_package_json(
        self,
        skills: List[str],
        practice_mode: Literal["direct", "ai_recommend"] = "direct",
        *,
        job_summary: str = "",
        difficulty: str = "",
        exam_options: Optional[Union[ExamOptionsForPractice, dict]] = None,
    ) -> str:
        return self.practice_invoker.build_skill_package_json(
            skills,
            practice_mode,
            job_summary=job_summary,
            difficulty=difficulty,
            exam_options=exam_options,
        )

    def build_practice_protocol_url(
        self,
        skills: List[str],
        practice_mode: Literal["direct", "ai_recommend"] = "direct",
        *,
        job_summary: str = "",
        difficulty: str = "",
        exam_options: Optional[Union[ExamOptionsForPractice, dict]] = None,
        auto_proceed: bool = False,
    ) -> str:
        return self.practice_invoker.build_protocol_url(
            skills,
            practice_mode,
            job_summary=job_summary,
            difficulty=difficulty,
            exam_options=exam_options,
            auto_proceed=auto_proceed,
        )

    def get_history(self, limit: int = 10) -> List[JDRecord]:
        return self.db.get_jd_records(limit)

    def get_jd_record(self, jd_record_id: int) -> Optional[JDRecord]:
        return self.db.get_jd_record_by_id(jd_record_id)

    def rename_jd_record(self, jd_record_id: int, display_name: Optional[str]) -> None:
        self.db.rename_jd_record(jd_record_id, display_name)

    def delete_jd_record(self, jd_record_id: int) -> None:
        self.db.delete_jd_record(jd_record_id)
