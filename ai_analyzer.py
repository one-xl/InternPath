import json
from typing import Optional
from openai import OpenAI
from config import Config
from models import JobAnalysis

class AIAnalyzer:
    def __init__(self):
        self.client = OpenAI(
            api_key=Config.LLM_API_KEY,
            base_url=Config.LLM_BASE_URL
        )
        self.model = Config.LLM_MODEL
    
    def extract_skills(self, jd_text: str) -> JobAnalysis:
        system_prompt = """
        你是一个专业的招聘信息分析专家。请分析给定的岗位 JD（招聘要求），并提取以下信息：

        1. skills: 提取核心技能列表，包括：
           - 硬核技术（如 Rust, WPF, Python, 机器学习等）
           - 软技能（如沟通能力、团队协作、项目管理等）

        2. difficulty: 评估岗位难度，只能是以下三个值之一："简单", "中等", "困难"

        3. job_summary: 用 100-200 字简要描述岗位的核心要求和职责

        请严格返回 JSON 格式，不要包含任何其他文字说明。
        JSON 格式示例：
        {
            "skills": ["Python", "机器学习", "团队协作"],
            "difficulty": "中等",
            "job_summary": "这是一个需要 Python 和机器学习技能的岗位..."
        }
        """
        
        user_prompt = f"请分析以下岗位 JD：\n\n{jd_text}"
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                response_format={"type": "json_object"}
            )
            
            result_text = response.choices[0].message.content.strip()
            result = json.loads(result_text)
            
            return JobAnalysis(**result)
        
        except Exception as e:
            raise Exception(f"AI 分析失败: {str(e)}")
