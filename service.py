from typing import List, Tuple
from models import JobAnalysis, BilibiliCourse
from ai_analyzer import AIAnalyzer
from crawler import BilibiliCrawler
from ranker import CourseRanker
from database import Database
from practice_app import PracticeAppInvoker

class CareerPathAIService:
    def __init__(self):
        self.ai_analyzer = AIAnalyzer()
        self.crawler = BilibiliCrawler()
        self.ranker = CourseRanker()
        self.db = Database()
        self.practice_invoker = PracticeAppInvoker()
    
    def analyze_jd(self, jd_text: str) -> Tuple[JobAnalysis, List[BilibiliCourse]]:
        analysis = self.ai_analyzer.extract_skills(jd_text)
        
        all_courses = []
        for skill in analysis.skills:
            courses = self.crawler.search_skill(skill)
            all_courses.extend(courses)
        
        ranked_courses = self.ranker.rank_by_skill(all_courses)
        
        jd_record_id = self.db.save_jd_record(jd_text, analysis)
        self.db.save_courses(jd_record_id, ranked_courses)
        
        return analysis, ranked_courses
    
    def sync_to_practice_app(self, skills: List[str]) -> bool:
        return self.practice_invoker.invoke_practice_app(skills)
    
    def get_history(self, limit: int = 10):
        return self.db.get_jd_records(limit)
