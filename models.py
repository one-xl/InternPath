from pydantic import BaseModel, ConfigDict, Field
from typing import List, Literal, Optional
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
    danmaku_count: int = Field(default=0, description="弹幕数")
    publish_date: str = Field(..., description="发布日期")
    uploader: str = Field(..., description="UP主")
    skill: str = Field(..., description="对应的技能")
    rank_score: float = Field(default=0.0, description="排序分数")
    duration: str = Field(default="", description="视频时长")
    description: str = Field(default="", description="视频描述")
    thumbnail: str = Field(default="", description="缩略图URL")
    aid: int = Field(default=0, description="视频AID")
    bvid: str = Field(default="", description="视频BVID")

class JobContextForPractice(BaseModel):
    """传给刷题软件侧 AI 推荐模块的岗位上下文（可选）。"""

    difficulty: str = Field(default="", description="岗位难度：简单/中等/困难")
    job_summary: str = Field(default="", description="岗位简述，供推荐模型理解场景")


class ExamOptionsForPractice(BaseModel):
    """
    与 AiSmartDrill `CareerPathSkillPackageModels` 中 exam_options 对齐（JSON snake_case）。
    用于「直接刷题」准备对话框默认值；AI 推荐模式下可对 DomainScope 限域（仅当显式提供 domain_hint）。
    """

    model_config = ConfigDict(extra="forbid")

    domain_hint: Optional[str] = Field(
        default=None,
        description="与刷题软件「领域」下拉文案一致或相近，如「Python」「数据库」",
    )
    difficulty: Optional[str] = Field(
        default=None,
        description="简单 / 中等 / 困难；省略或空表示不限制",
    )
    question_count: Optional[int] = Field(
        default=None,
        ge=1,
        le=50,
        description="本次组卷题量 1～50",
    )


class SkillPackage(BaseModel):
    """与 C# 刷题软件约定的技能包（JSON 文件，由 CareerPath 导出）。"""

    model_config = ConfigDict(extra="forbid")

    skills: List[str] = Field(..., description="AI 从 JD 提取的知识点/技能列表")
    practice_mode: Literal["direct", "ai_recommend"] = Field(
        ...,
        description="direct=按知识点直接选题刷题；ai_recommend=先走刷题软件内 AI 推荐题目再刷题",
    )
    job_context: JobContextForPractice = Field(
        default_factory=JobContextForPractice,
        description="岗位上下文，ai_recommend 模式下建议填写",
    )
    exam_options: Optional[ExamOptionsForPractice] = Field(
        default=None,
        description="组卷与领域提示；省略时刷题端使用自身默认（向后兼容 2.0）",
    )
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    # 仍为 2.0：exam_options 为可选扩展，旧版刷题软件可忽略未知字段。
    version: str = Field(default="2.0", description="协议版本，刷题软件据此解析")
    source: str = Field(default="careerpath_ai", description="数据来源标识")

class JDRecord(BaseModel):
    id: Optional[int] = None
    jd_text: str
    analysis: JobAnalysis
    display_name: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)

class CourseRecord(BaseModel):
    id: Optional[int] = None
    skill: str
    course: BilibiliCourse
    jd_record_id: int
    created_at: datetime = Field(default_factory=datetime.now)
