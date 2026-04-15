from typing import List, Tuple
from models import JobAnalysis, BilibiliCourse
from ai_analyzer import AIAnalyzer
from crawler_api import BilibiliAPICrawlerSync
from ranker import CourseRanker
from database import Database
from practice_app import PracticeAppInvoker

class CareerPathAIService:
    def __init__(self):
        self.ai_analyzer = AIAnalyzer()
        self.crawler = BilibiliAPICrawlerSync()
        self.ranker = CourseRanker()
        self.db = Database()
        self.practice_invoker = PracticeAppInvoker()
    
    def extract_skills(self, jd_text: str) -> JobAnalysis:
        analysis = self.ai_analyzer.extract_skills(jd_text)
        return analysis
    
    def search_courses(self, skills: List[str]) -> List[BilibiliCourse]:
        all_courses = []
        for skill in skills:
            courses = self.crawler.search_skill(skill)
            all_courses.extend(courses)
        
        ranked_courses = self.ranker.rank_by_skill(all_courses)
        return ranked_courses
    
    def analyze_jd(self, jd_text: str) -> Tuple[JobAnalysis, List[BilibiliCourse]]:
        analysis = self.extract_skills(jd_text)
        courses = self.search_courses(analysis.skills)
        
        jd_record_id = self.db.save_jd_record(jd_text, analysis)
        self.db.save_courses(jd_record_id, courses)
        
        return analysis, courses
    
    def sync_to_practice_app(self, skills: List[str]) -> bool:
        return self.practice_invoker.invoke_practice_app(skills)
    
    def get_history(self, limit: int = 10):
        return self.db.get_jd_records(limit)
