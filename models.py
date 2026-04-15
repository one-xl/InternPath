from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

class JobAnalysis(BaseModel):
    skills: List[str] = Field(..., description="提取的技能列表")
    difficulty: str = Field(..., description="难度评估：简单/中等/困难")
    job_summary: str = Field(..., description="岗位简述")

class BilibiliCourse(BaseModel):
    title: str = Field(..., description="视频标题")
    url: str = Field(..., description="视频URL")
    view_count: int = Field(..., description="播放量")
    favorite_count: int = Field(..., description="收藏数")
    like_count: int = Field(..., description="点赞数")
    coin_count: int = Field(default=0, description="投币数")
    publish_date: str = Field(..., description="发布日期")
    uploader: str = Field(..., description="UP主")
    skill: str = Field(..., description="对应的技能")
    rank_score: float = Field(default=0.0, description="排序分数")

class SkillPackage(BaseModel):
    skills: List[str] = Field(..., description="技能列表")
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    version: str = Field(default="1.0")

class JDRecord(BaseModel):
    id: Optional[int] = None
    jd_text: str
    analysis: JobAnalysis
    created_at: datetime = Field(default_factory=datetime.now)

class CourseRecord(BaseModel):
    id: Optional[int] = None
    skill: str
    course: BilibiliCourse
    jd_record_id: int
    created_at: datetime = Field(default_factory=datetime.now)
