import re
from typing import List
from datetime import datetime
from config import Config
from models import BilibiliCourse

class CourseRanker:
    def __init__(self):
        self.relevance_weight = Config.RANK_RELEVANCE_WEIGHT
        self.quality_weight = Config.RANK_QUALITY_WEIGHT
        self.timeliness_weight = Config.RANK_TIMELINESS_WEIGHT
        self.top_n = Config.TOP_COURSES_PER_SKILL
    
    def calculate_relevance_score(self, course: BilibiliCourse) -> float:
        skill = course.skill.lower()
        title = course.title.lower()
        
        if skill in title:
            return 100.0
        
        skill_words = re.split(r'[\s+\-]+', skill)
        match_count = sum(1 for word in skill_words if word and word in title)
        
        if match_count == len(skill_words):
            return 80.0
        elif match_count > 0:
            return 40.0 + (match_count / len(skill_words)) * 40.0
        else:
            return 10.0
    
    def calculate_quality_score(self, course: BilibiliCourse) -> float:
        if course.view_count == 0:
            return 0.0
        
        total_interactions = course.favorite_count + course.coin_count + course.like_count
        interaction_ratio = total_interactions / course.view_count
        
        if interaction_ratio > 0.5:
            return 100.0
        elif interaction_ratio > 0.3:
            return 80.0 + (interaction_ratio - 0.3) * 100
        elif interaction_ratio > 0.1:
            return 50.0 + (interaction_ratio - 0.1) * 150
        elif interaction_ratio > 0.05:
            return 20.0 + (interaction_ratio - 0.05) * 600
        else:
            return interaction_ratio * 400
    
    def calculate_timeliness_score(self, course: BilibiliCourse) -> float:
        try:
            if '-' in course.publish_date:
                date_parts = course.publish_date.split('-')
                if len(date_parts) >= 1:
                    year = int(date_parts[0])
                else:
                    year = datetime.now().year
            else:
                year_match = re.search(r'(\d{4})', course.publish_date)
                if year_match:
                    year = int(year_match.group(1))
                else:
                    year = datetime.now().year
            
            current_year = datetime.now().year
            years_ago = current_year - year
            
            if years_ago <= 0:
                return 100.0
            elif years_ago == 1:
                return 80.0
            elif years_ago == 2:
                return 60.0
            elif years_ago == 3:
                return 40.0
            elif years_ago == 4:
                return 20.0
            else:
                return 10.0
        
        except Exception:
            return 50.0
    
    def calculate_rank_score(self, course: BilibiliCourse) -> float:
        relevance_score = self.calculate_relevance_score(course)
        quality_score = self.calculate_quality_score(course)
        timeliness_score = self.calculate_timeliness_score(course)
        
        total_score = (
            relevance_score * self.relevance_weight +
            quality_score * self.quality_weight +
            timeliness_score * self.timeliness_weight
        )
        
        return total_score
    
    def rank_courses(self, courses: List[BilibiliCourse]) -> List[BilibiliCourse]:
        for course in courses:
            course.rank_score = self.calculate_rank_score(course)
        
        sorted_courses = sorted(courses, key=lambda x: x.rank_score, reverse=True)
        
        return sorted_courses[:self.top_n]
    
    def rank_by_skill(self, courses: List[BilibiliCourse]) -> List[BilibiliCourse]:
        skill_groups = {}
        for course in courses:
            if course.skill not in skill_groups:
                skill_groups[course.skill] = []
            skill_groups[course.skill].append(course)
        
        result = []
        for skill, skill_courses in skill_groups.items():
            ranked = self.rank_courses(skill_courses)
            result.extend(ranked)
        
        return result
